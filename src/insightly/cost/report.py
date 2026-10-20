"""Monthly cost projection from measured evaluation runs (no guessing: uses real tokens)."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path


def projection(report_dir: Path, questions_per_day: int) -> dict:
    cases = [
        json.loads(line)
        for line in (report_dir / "cases.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    meta = json.loads((report_dir / "summary.json").read_text(encoding="utf-8"))["meta"]
    n = len(cases) or 1
    per_q = sum(c["cost_usd"] for c in cases) / n
    by_status: dict[str, list[float]] = defaultdict(list)
    for c in cases:
        by_status[c["status"]].append(c["cost_usd"])
    monthly_llm = per_q * questions_per_day * 30
    return {
        "provider": meta["provider"],
        "measured_cost_per_question_usd": round(per_q, 6),
        "avg_input_tokens": round(sum(c["input_tokens"] for c in cases) / n, 1),
        "avg_cached_tokens": round(sum(c["cached_tokens"] for c in cases) / n, 1),
        "avg_output_tokens": round(sum(c["output_tokens"] for c in cases) / n, 1),
        "cost_by_status": {k: round(sum(v) / len(v), 6) for k, v in by_status.items()},
        "questions_per_day": questions_per_day,
        "projected_monthly_llm_and_query_usd": round(monthly_llm, 2),
        "note": "Infra (ECS, Aurora, NAT, ALB) is separate; see docs/cost-management.md.",
    }
