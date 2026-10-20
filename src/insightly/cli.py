"""Insightly command line.  ``uv run insightly --help``"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from insightly.config import ROOT_DIR, get_settings

app = typer.Typer(no_args_is_help=True, help="Insightly: governed text-to-SQL analytics.")
data_app = typer.Typer(no_args_is_help=True, help="Data pipeline")
eval_app = typer.Typer(no_args_is_help=True, help="Evaluation")
ft_app = typer.Typer(no_args_is_help=True, help="Fine-tuning")
cost_app = typer.Typer(no_args_is_help=True, help="Cost reports")
app.add_typer(data_app, name="data")
app.add_typer(eval_app, name="eval")
app.add_typer(ft_app, name="finetune")
app.add_typer(cost_app, name="cost")
console = Console()
RAW = ROOT_DIR / "data" / "raw"


@data_app.command("synthetic")
def data_synthetic(users: int = 5000, out: Path = RAW) -> None:
    """Generate a synthetic dataset with the real schema (no download needed)."""
    from insightly.data.synthetic import generate

    console.print(generate(out, n_users=users))


@data_app.command("curate")
def data_curate(raw: Path = RAW) -> None:
    """Clean raw CSVs into curated Parquet (data/curated)."""
    from insightly.data.curate import curate

    console.print(curate(raw, get_settings().curated_dir))


@data_app.command("publish")
def data_publish(bucket: str = typer.Option(None, envvar="INSIGHTLY_DATA_BUCKET")) -> None:
    """Upload curated Parquet to S3 and create Glue/Iceberg tables via Athena."""
    from insightly.data.publish import publish

    if not bucket:
        raise typer.BadParameter("Pass --bucket or set INSIGHTLY_DATA_BUCKET")
    console.print(publish(get_settings().curated_dir, bucket))


@app.command()
def index(force: bool = False) -> None:
    """Embed the semantic layer into the vector store (cached by content hash)."""
    from insightly.semantic.retriever import get_retriever

    r = get_retriever()
    n = r.ensure_index(force=force)
    console.print(f"indexed {n} docs (0 = already up to date); embedding cache misses: {r.embedder.misses}")


@app.command()
def ask(
    question: str, thread: str = typer.Option(None, help="thread id for follow-ups"), show_sql: bool = True
) -> None:
    """Ask a question from the terminal."""
    from insightly.agent.service import ask as _ask

    out = _ask(question, thread_id=thread, user_id="cli")
    if out["status"] == "clarify":
        c = out["clarification"]
        console.print(f"[yellow]{c['question']}[/] options: {c['options']}")
        choice = typer.prompt("Your choice")
        out = _ask(thread_id=out["thread_id"], resume=choice, user_id="cli")
    console.print(f"[bold]{out.get('answer')}[/]")
    if show_sql and out.get("sql"):
        console.print(out["sql"], style="cyan")
    if out.get("rows"):
        t = Table(*out["columns"])
        for row in out["rows"][:15]:
            t.add_row(*[str(v) for v in row])
        console.print(t)
    console.print(
        f"status={out['status']} attempts={out.get('attempts')} "
        f"latency={out.get('latency_ms')}ms cost=${out['cost']['total_usd']:.5f} "
        f"thread={out['thread_id']}"
    )


@app.command()
def serve(host: str = "0.0.0.0", port: int = 8000, reload: bool = False) -> None:
    """Run the FastAPI service."""
    import uvicorn

    uvicorn.run("insightly.api.main:app", host=host, port=port, reload=reload)


@app.command()
def mcp(http: bool = False) -> None:
    """Run the MCP server (stdio by default)."""
    from insightly.mcp_server import run

    run(http=http)


@eval_app.command("run")
def eval_run(judge: bool = False, limit: int = typer.Option(None), tag: str = typer.Option(None)) -> None:
    """Run golden + red-team evaluation and write reports/eval/<timestamp>/."""
    from insightly.eval.runner import run

    out = run(judge=judge, limit=limit, tag=tag)
    m = json.loads((out / "summary.json").read_text(encoding="utf-8"))["metrics"]
    t = Table("metric", "value")
    for k, v in m.items():
        if k != "intent_confusion":
            t.add_row(k, str(v))
    console.print(t)
    console.print(f"report: {out / 'report.md'}")


@eval_app.command("gate")
def eval_gate(
    report: Path = ROOT_DIR / "reports" / "eval" / "latest",
    baseline: Path = typer.Option(None, help="previous report dir to detect regressions"),
) -> None:
    """Exit 1 when the report violates evals/thresholds.yaml."""
    from insightly.eval.report import gate

    bad = gate(report.resolve(), baseline.resolve() if baseline else None)
    if bad:
        for b in bad:
            console.print(f"[red]FAIL[/] {b}")
        raise typer.Exit(1)
    console.print("[green]PASS[/] all thresholds met")


@eval_app.command("langsmith")
def eval_langsmith(prefix: str = "insightly") -> None:
    """Run the golden set as a LangSmith experiment."""
    from insightly.eval.langsmith_sync import run_experiment

    console.print(run_experiment(prefix))


@ft_app.command("build")
def ft_build(feedback: Path = typer.Option(None), min_examples: int = 10) -> None:
    """Build SFT/RFT JSONL datasets from verified feedback + semantic examples."""
    from insightly.finetune.dataset import build

    console.print(build(feedback_path=feedback, min_examples=min_examples))


@ft_app.command("submit")
def ft_submit(
    method: str = typer.Option("supervised", help="supervised | reinforcement"),
    base_model: str = typer.Option(None, envvar="INSIGHTLY_FT_BASE_MODEL"),
    dry_run: bool = False,
) -> None:
    """Upload the dataset and create an OpenAI fine-tuning job."""
    from insightly.finetune.jobs import submit

    console.print(submit(method=method, base_model=base_model, dry_run=dry_run))


@ft_app.command("status")
def ft_status(job_id: str) -> None:
    from insightly.finetune.jobs import status

    console.print(status(job_id))


@cost_app.command("report")
def cost_report(
    report: Path = ROOT_DIR / "reports" / "eval" / "latest", questions_per_day: int = 500
) -> None:
    """Project monthly OpenAI + Athena cost from an evaluation run."""
    from insightly.cost.report import projection

    console.print(projection(report.resolve(), questions_per_day))


if __name__ == "__main__":
    app()
