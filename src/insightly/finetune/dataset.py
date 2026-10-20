"""Build fine-tuning datasets from production evidence.

Sources, in priority order:
1. analyst corrections in the feedback log (``corrected_sql``), always trusted
2. thumbs-up answers whose SQL still validates and executes
3. verified examples from the semantic layer (seed data for the first job)

Golden test questions are removed (exact and near-duplicate) so evaluation stays honest.
Outputs (data/finetune/):
  sql_sft_train.jsonl / sql_sft_val.jsonl   chat format for supervised fine-tuning
  sql_rft_train.jsonl / sql_rft_val.jsonl   prompt + reference for reinforcement fine-tuning
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

import yaml

from insightly.agent import prompts
from insightly.agent.sql_guard import check_sql
from insightly.config import ROOT_DIR, get_settings
from insightly.data.engine import get_engine
from insightly.eval.runner import GOLDEN
from insightly.llm.schemas import SQLDraft
from insightly.semantic.layer import load_semantic_layer
from insightly.semantic.retriever import get_retriever

OUT = ROOT_DIR / "data" / "finetune"


def _norm_q(q: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", q.lower()).strip()


def _golden_questions() -> set[str]:
    return {_norm_q(c["question"]) for c in yaml.safe_load(GOLDEN.read_text())["cases"]}


def _too_close(q: str, golden: set[str]) -> bool:
    toks = set(_norm_q(q).split())
    for g in golden:
        gt = set(g.split())
        if toks and len(toks & gt) / len(toks | gt) >= 0.8:
            return True
    return False


def _user_prompt(question: str) -> str:
    hits = get_retriever().search(question)
    return prompts.sql_user(
        question=question,
        metrics=[h.doc.text for h in hits if h.doc.kind == "metric"],
        examples=[
            h.doc.text for h in hits if h.doc.kind == "example" and _norm_q(h.doc.title) != _norm_q(question)
        ][:4],
        tables=[h.doc.text for h in hits if h.doc.kind == "table"],
        previous_sql=None,
        error=None,
    )


def collect(feedback_path: Path | None) -> list[dict]:
    pairs: list[dict] = []
    fp = feedback_path or get_settings().feedback_path
    if fp.exists():
        for line in fp.read_text().splitlines():
            rec = json.loads(line)
            if rec.get("corrected_sql"):
                pairs.append(
                    {"question": rec["question"], "sql": rec["corrected_sql"], "source": "analyst_correction"}
                )
            elif rec.get("rating") == "up" and rec.get("sql"):
                pairs.append({"question": rec["question"], "sql": rec["sql"], "source": "thumbs_up"})
    for ex in load_semantic_layer().examples:
        pairs.append({"question": ex["question"], "sql": ex["sql"].strip(), "source": "seed"})
    return pairs


def build(
    feedback_path: Path | None = None, min_examples: int = 10, val_ratio: float = 0.2, seed: int = 13
) -> dict:
    layer = load_semantic_layer()
    golden = _golden_questions()
    seen: set[str] = set()
    rows = []
    dropped = {"duplicate": 0, "golden_leak": 0, "invalid_sql": 0, "exec_error": 0}
    for p in collect(feedback_path):
        key = _norm_q(p["question"])
        if key in seen:
            dropped["duplicate"] += 1
            continue
        if key in golden or _too_close(p["question"], golden):
            dropped["golden_leak"] += 1
            continue
        g = check_sql(p["sql"], layer.allowed_tables)
        if not g.ok:
            dropped["invalid_sql"] += 1
            continue
        try:
            get_engine().execute(g.sql, max_rows=5)
        except Exception:
            dropped["exec_error"] += 1
            continue
        seen.add(key)
        rows.append({**p, "sql": p["sql"].strip(), "tables": g.tables})
    if len(rows) < min_examples:
        raise SystemExit(f"Only {len(rows)} usable examples (< {min_examples}). Collect more feedback.")

    random.Random(seed).shuffle(rows)
    n_val = max(1, int(len(rows) * val_ratio))
    splits = {"val": rows[:n_val], "train": rows[n_val:]}
    OUT.mkdir(parents=True, exist_ok=True)
    system = prompts.sql_system()
    for split, items in splits.items():
        with (OUT / f"sql_sft_{split}.jsonl").open("w") as f:
            for r in items:
                target = SQLDraft(sql=r["sql"], tables_used=r["tables"], metric_ids=[], assumptions=[])
                f.write(
                    json.dumps(
                        {
                            "messages": [
                                {"role": "system", "content": system},
                                {"role": "user", "content": _user_prompt(r["question"])},
                                {"role": "assistant", "content": target.model_dump_json()},
                            ]
                        }
                    )
                    + "\n"
                )
        with (OUT / f"sql_rft_{split}.jsonl").open("w") as f:
            for r in items:
                f.write(
                    json.dumps(
                        {
                            "messages": [
                                {"role": "developer", "content": system},
                                {"role": "user", "content": _user_prompt(r["question"])},
                            ],
                            "reference_sql": r["sql"],
                            "reference_tables": r["tables"],
                        }
                    )
                    + "\n"
                )
    return {
        "train": len(splits["train"]),
        "val": len(splits["val"]),
        "dropped": dropped,
        "sources": {s: sum(1 for r in rows if r["source"] == s) for s in {r["source"] for r in rows}},
        "out_dir": str(OUT),
    }
