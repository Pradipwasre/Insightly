"""Submit and track OpenAI fine-tuning jobs.

* supervised     distil verified SQL into a smaller, cheaper model
* reinforcement  optimise a reasoning model against a grader (python grader below)

Which base models accept which method changes over time: check
https://platform.openai.com/docs/guides/fine-tuning before submitting, then set
INSIGHTLY_FT_BASE_MODEL. A fine-tuned model is used by setting INSIGHTLY_MODEL_SQL to its
``ft:...`` id, only after it passes ``insightly eval run`` + ``insightly eval gate``.
"""

from __future__ import annotations

import json

from insightly.finetune.dataset import OUT
from insightly.llm.gateway import openai_api_key

# Runs inside OpenAI's grader sandbox (no network, no database). It scores structural
# agreement with the reference: tables, aggregate functions, GROUP BY, time filter and
# metric expression fragments. Execution accuracy is then measured offline by the eval gate.
PYTHON_GRADER = r"""
import json, re

def _parse(text):
    try:
        return json.loads(text).get("sql", "")
    except Exception:
        return text or ""

def _feats(sql):
    s = re.sub(r"\s+", " ", sql.lower())
    return {
        "tables": set(re.findall(r"(?:from|join)\s+([a-z_]+)", s)),
        "aggs": set(re.findall(r"\b(sum|count|avg|min|max|count_if)\s*\(", s)),
        "group": "group by" in s,
        "years": set(re.findall(r"timestamp '(\d{4})", s)),
        "status_rule": "not in ('cancelled', 'returned')" in s,
    }

def grade(sample, item):
    pred = _feats(_parse(sample.get("output_text", "")))
    ref = _feats(item["reference_sql"])
    if not pred["tables"]:
        return 0.0
    def j(a, b):
        return 1.0 if not a and not b else len(a & b) / max(len(a | b), 1)
    score = (0.35 * j(pred["tables"], ref["tables"]) + 0.2 * j(pred["aggs"], ref["aggs"])
             + 0.15 * (pred["group"] == ref["group"]) + 0.15 * j(pred["years"], ref["years"])
             + 0.15 * (pred["status_rule"] == ref["status_rule"]))
    return round(score, 4)
"""


def _client():
    from openai import OpenAI

    return OpenAI(api_key=openai_api_key())


def submit(method: str, base_model: str | None, dry_run: bool = False) -> dict:
    if method not in {"supervised", "reinforcement"}:
        raise ValueError("method must be supervised or reinforcement")
    if not base_model:
        raise SystemExit("Set --base-model or INSIGHTLY_FT_BASE_MODEL (see docs/fine-tuning.md)")
    prefix = "sql_sft" if method == "supervised" else "sql_rft"
    train, val = OUT / f"{prefix}_train.jsonl", OUT / f"{prefix}_val.jsonl"
    if not train.exists():
        raise SystemExit("Run `insightly finetune build` first.")
    method_cfg: dict = {"type": method}
    if method == "supervised":
        method_cfg["supervised"] = {"hyperparameters": {"n_epochs": 3}}
    else:
        method_cfg["reinforcement"] = {
            "grader": {"type": "python", "name": "sql_structure", "source": PYTHON_GRADER},
            "hyperparameters": {"reasoning_effort": "low"},
        }
    plan = {
        "base_model": base_model,
        "method": method_cfg["type"],
        "train": str(train),
        "val": str(val),
        "train_rows": sum(1 for _ in train.open(encoding="utf-8")),
    }
    if dry_run:
        return {"dry_run": True, **plan}
    c = _client()
    train_id = c.files.create(file=train.open("rb"), purpose="fine-tune").id
    val_id = c.files.create(file=val.open("rb"), purpose="fine-tune").id
    job = c.fine_tuning.jobs.create(
        model=base_model,
        training_file=train_id,
        validation_file=val_id,
        method=method_cfg,
        suffix="insightly-sql",
        metadata={"project": "insightly"},
    )
    return {"job_id": job.id, "status": job.status, **plan}


def status(job_id: str) -> dict:
    c = _client()
    job = c.fine_tuning.jobs.retrieve(job_id)
    events = [e.message for e in c.fine_tuning.jobs.list_events(job_id, limit=10).data]
    return {
        "id": job.id,
        "status": job.status,
        "fine_tuned_model": job.fine_tuned_model,
        "trained_tokens": job.trained_tokens,
        "recent_events": events,
        "error": json.loads(job.error.model_dump_json()) if job.error else None,
    }
