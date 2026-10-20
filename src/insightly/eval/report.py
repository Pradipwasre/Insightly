"""Markdown report + release gate."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from insightly.config import ROOT_DIR

SECTIONS = {
    "Correctness": [
        "execution_accuracy",
        "valid_sql_rate",
        "final_sql_success_rate",
        "metric_fidelity",
        "component_match",
    ],
    "Retrieval and schema linking": [
        "table_recall_at_k",
        "mrr",
        "context_precision",
        "schema_precision",
        "schema_recall",
        "schema_f1",
    ],
    "Agent behaviour": [
        "intent_accuracy",
        "intent_macro_f1",
        "clarification_precision",
        "clarification_recall",
        "repair_success_rate",
        "avg_sql_attempts",
        "escalation_rate",
        "chart_validity",
        "chart_recall",
    ],
    "Answer quality": ["faithfulness", "empty_result_mismatch_rate", "judge_score"],
    "Safety": ["safety_block_rate", "pii_leak_rate"],
    "Performance and cost": [
        "latency_p50_ms",
        "latency_p95_ms",
        "cost_per_question_usd",
        "total_cost_usd",
        "avg_input_tokens",
        "avg_output_tokens",
        "prompt_cache_hit_ratio",
        "error_rate",
    ],
}


def _fmt(v) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.4f}" if v < 10 else f"{v:,.1f}"
    return str(v)


def write_markdown(out_dir: Path, meta: dict, summary: dict, results, redteam) -> None:
    lines = [
        f"# Insightly evaluation report ({meta['timestamp']})",
        "",
        f"Provider: `{meta['provider']}`  Engine: `{meta['engine']}`  "
        f"Golden set: `{meta['golden']}`  Cases: {summary['n_cases']} "
        f"(SQL {summary['n_sql_cases']}), red-team: {summary['n_redteam']}",
        "",
        "Models: " + ", ".join(f"{k}=`{v}`" for k, v in meta["models"].items()),
        "",
    ]
    for title, keys in SECTIONS.items():
        lines += [f"## {title}", "", "| metric | value |", "|---|---|"]
        lines += [f"| {k} | {_fmt(summary.get(k))} |" for k in keys]
        lines.append("")
    lines += [
        "## Failed SQL cases",
        "",
        "| id | difficulty | status | attempts | question |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        if r.gold_intent == "analytics" and not r.exec_match:
            lines.append(f"| {r.id} | {r.difficulty} | {r.status} | {r.attempts} | {r.question} |")
    lines += [
        "",
        "## Intent confusion (gold -> predicted)",
        "",
        "```",
        json.dumps(summary["intent_confusion"], indent=2),
        "```",
        "",
        "## Red-team",
        "",
        "| id | category | status | blocked | leaked |",
        "|---|---|---|---|---|",
    ]
    lines += [
        f"| {x['id']} | {x['category']} | {x['status']} | {x['blocked']} | {x['leaked']} |" for x in redteam
    ]
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def gate(report_dir: Path, baseline_dir: Path | None = None) -> list[str]:
    """Return a list of violations (empty list = pass)."""
    data = json.loads((report_dir / "summary.json").read_text(encoding="utf-8"))
    m, provider = data["metrics"], data["meta"]["provider"]
    th = yaml.safe_load((ROOT_DIR / "evals" / "thresholds.yaml").read_text(encoding="utf-8"))
    rules = th.get(provider, {})
    bad = []
    for k, lo in (rules.get("min") or {}).items():
        if m.get(k) is not None and m[k] < lo:
            bad.append(f"{k}={m[k]} < min {lo}")
    for k, hi in (rules.get("max") or {}).items():
        if m.get(k) is not None and m[k] > hi:
            bad.append(f"{k}={m[k]} > max {hi}")
    if baseline_dir and (baseline_dir / "summary.json").exists():
        base = json.loads((baseline_dir / "summary.json").read_text(encoding="utf-8"))["metrics"]
        reg = th.get("regression", {})
        for k, drop in reg.items():
            if k.endswith("_rel"):
                key = k.removesuffix("_rel")
                if base.get(key) and m.get(key) is not None and m[key] > base[key] * (1 + drop):
                    bad.append(f"{key} regressed {base[key]} -> {m[key]} (> +{drop:.0%})")
            elif base.get(k) is not None and m.get(k) is not None and m[k] < base[k] - drop:
                bad.append(f"{k} regressed {base[k]} -> {m[k]} (> -{drop})")
    return bad
