"""Run one question through the graph. Shared by the API, the CLI, MCP and the evaluator."""

from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any

from langgraph.types import Command

from insightly.agent.graph import get_graph
from insightly.agent.state import RunContext
from insightly.config import get_settings
from insightly.cost.tracker import CostLedger, TTLCache, daily_spend
from insightly.observability.logging import emit_metrics, log

_cache = TTLCache(get_settings().answer_cache_ttl_s)

PUBLIC_KEYS = [
    "status",
    "intent",
    "standalone_question",
    "sql",
    "columns",
    "rows",
    "truncated",
    "chart",
    "answer",
    "highlights",
    "faithfulness",
    "metric_ids",
    "attempts",
    "escalated",
    "first_attempt_ok",
    "trace",
    "timings_ms",
    "cost",
    "bytes_scanned",
    "clarification",
]


def _cache_key(question: str, role: str) -> str:
    return hashlib.sha256(f"{role}|{question.strip().lower()}".encode()).hexdigest()


def ask(
    question: str | None = None,
    *,
    thread_id: str | None = None,
    user_id: str = "local",
    role: str = "analyst",
    resume: str | None = None,
    use_cache: bool = True,
    graph=None,
) -> dict[str, Any]:
    """Ask a question, or resume a paused thread with ``resume`` (the clarification choice)."""
    s = get_settings()
    graph = graph or get_graph()
    thread_id = thread_id or str(uuid.uuid4())
    new_thread = thread_id and not graph.get_state({"configurable": {"thread_id": thread_id}}).values

    if question and use_cache and new_thread and resume is None:
        hit = _cache.get(_cache_key(question, role))
        if hit:
            return {
                **hit,
                "thread_id": thread_id,
                "cached": True,
                "cost": {"total_usd": 0.0, "by_model": {}, "items": []},
            }

    remaining = daily_spend.remaining(user_id)
    if remaining <= 0:
        return {
            "status": "budget_exceeded",
            "thread_id": thread_id,
            "answer": "Your daily question budget is used up. It resets at 00:00 UTC.",
        }

    ledger = CostLedger(budget_usd=min(s.request_budget_usd, remaining))
    ctx = RunContext(user_id=user_id, role=role, ledger=ledger)
    config = {
        "configurable": {"thread_id": thread_id},
        "metadata": {"user_id": user_id, "role": role},
        "run_name": "insightly.ask",
    }
    payload: Any = Command(resume=resume) if resume is not None else {"question": question}

    t0 = time.perf_counter()
    result = graph.invoke(payload, config=config, context=ctx)
    latency_ms = (time.perf_counter() - t0) * 1000
    daily_spend.add(user_id, ledger.total_usd)

    interrupts = result.get("__interrupt__")
    out = {k: result.get(k) for k in PUBLIC_KEYS}
    out.update(thread_id=thread_id, latency_ms=round(latency_ms, 1), cached=False, cost=ledger.summary())
    if interrupts:
        out["status"] = "clarify"
        out["clarification"] = interrupts[0].value
        out["answer"] = interrupts[0].value.get("question")

    if out["status"] == "ok" and question and new_thread and resume is None:
        _cache.set(_cache_key(question, role), {k: v for k, v in out.items() if k != "cost"})

    log.info(
        "ask",
        status=out["status"],
        intent=out.get("intent"),
        attempts=out.get("attempts"),
        latency_ms=out["latency_ms"],
        cost_usd=ledger.total_usd,
    )
    emit_metrics(
        {"Service": "insightly", "Status": str(out["status"])},
        {
            "LatencyMs": (latency_ms, "Milliseconds"),
            "CostUSD": (ledger.total_usd, "None"),
            "SqlAttempts": (float(out.get("attempts") or 0), "Count"),
            "InputTokens": (float(ledger.summary()["input_tokens"]), "Count"),
            "OutputTokens": (float(ledger.summary()["output_tokens"]), "Count"),
        },
    )
    return out
