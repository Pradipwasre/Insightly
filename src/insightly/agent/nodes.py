"""Graph nodes. Each node does one job, records its timing and appends itself to the trace."""

from __future__ import annotations

import functools
import time
from collections.abc import Callable
from typing import Any

from langgraph.runtime import Runtime
from langgraph.types import interrupt

from insightly.agent import guards, prompts
from insightly.agent.chart import build_chart
from insightly.agent.faithfulness import faithfulness
from insightly.agent.sql_guard import check_sql
from insightly.agent.state import AgentState, RunContext
from insightly.config import get_settings
from insightly.cost.tracker import BudgetExceeded
from insightly.data.engine import get_engine
from insightly.llm.gateway import get_gateway, model_for
from insightly.llm.schemas import AnswerDraft, RouteDecision, SQLDraft
from insightly.observability.logging import log
from insightly.semantic.layer import load_semantic_layer
from insightly.semantic.retriever import get_retriever

Node = Callable[[AgentState, Runtime[RunContext]], dict[str, Any]]


def node(name: str) -> Callable[[Node], Node]:
    def deco(fn: Node) -> Node:
        @functools.wraps(fn)
        def wrapper(state: AgentState, runtime: Runtime[RunContext]) -> dict[str, Any]:
            t0 = time.perf_counter()
            try:
                out = fn(state, runtime)
            except BudgetExceeded as e:
                log.warning("budget_exceeded", node=name, detail=str(e))
                out = {"status": "budget_exceeded", "answer": str(e)}
            timings = dict(state.get("timings_ms") or {})
            timings[name] = round(timings.get(name, 0) + (time.perf_counter() - t0) * 1000, 1)
            out["timings_ms"] = timings
            out["trace"] = [*(out.get("trace") or state.get("trace") or []), name]
            out.setdefault("cost", runtime.context.ledger.summary())
            return out

        return wrapper

    return deco


@node("prepare")
def prepare(state: AgentState, runtime: Runtime[RunContext]) -> dict:
    # Reset per-turn fields; history survives in the thread checkpoint.
    return {
        "trace": [],
        "timings_ms": {},
        "intent": "",
        "standalone_question": state["question"],
        "wants_chart": False,
        "clarification": None,
        "hits": [],
        "sql": None,
        "sql_draft": None,
        "attempts": 0,
        "last_error": None,
        "error_stage": None,
        "first_attempt_ok": None,
        "escalated": False,
        "columns": [],
        "rows": [],
        "truncated": False,
        "bytes_scanned": 0,
        "chart": None,
        "answer": "",
        "highlights": [],
        "faithfulness": None,
        "metric_ids": [],
        "status": "running",
    }


@node("guard_input")
def guard_input(state: AgentState, runtime: Runtime[RunContext]) -> dict:
    reason = guards.check_input(state["question"])
    if reason is None and get_settings().use_moderation and get_gateway().moderate(state["question"]):
        reason = "The request was flagged by content moderation."
    if reason:
        return {"status": "refused", "answer": reason}
    return {}


@node("route_intent")
def route_intent(state: AgentState, runtime: Runtime[RunContext]) -> dict:
    history = state.get("history") or []
    turns = history[-get_settings().history_turns :]
    convo = "\n".join(f"User: {t['question']}\nAssistant: {t['answer'][:300]}" for t in turns)
    user = f"CONVERSATION SO FAR:\n{convo or '(none)'}\n\nLATEST MESSAGE: {state['question']}"
    decision: RouteDecision = get_gateway().structured(
        node="route_intent",
        tier="router",
        system=prompts.ROUTER_SYSTEM,
        user=user,
        schema=RouteDecision,
        ledger=runtime.context.ledger,
        context={
            "question": state["question"],
            "previous_question": turns[-1]["question"] if turns else None,
        },
    )
    out: dict[str, Any] = {
        "intent": decision.intent,
        "standalone_question": decision.standalone_question or state["question"],
        "wants_chart": decision.wants_chart,
    }
    if decision.intent == "ambiguous":
        out["clarification"] = {
            "question": decision.clarification_question or "Could you be more specific?",
            "options": decision.options[:3],
        }
    if decision.intent == "out_of_scope":
        out |= {
            "status": "out_of_scope",
            "answer": (
                "I can only answer questions about the company's orders, products, inventory, "
                "customers and website activity."
            ),
        }
    if decision.intent == "small_talk":
        out |= {
            "status": "ok",
            "answer": (
                "Hi! Ask me about sales, returns, products, inventory, delivery times or web "
                "conversion, for example: 'Net revenue by category in 2023'."
            ),
        }
    return out


@node("clarify")
def clarify(state: AgentState, runtime: Runtime[RunContext]) -> dict:
    # Human-in-the-loop: pause the graph until the user picks an option.
    choice = interrupt(state["clarification"])
    q = f"{state['standalone_question']} (clarified: {choice})"
    return {"standalone_question": q, "intent": "analytics"}


@node("retrieve")
def retrieve(state: AgentState, runtime: Runtime[RunContext]) -> dict:
    q = state["standalone_question"]
    hits = get_retriever().search(q)
    if get_settings().llm_provider == "openai":
        runtime.context.ledger.add_llm(
            "retrieve", get_settings().embedding_model, {"input_tokens": max(len(q) // 4, 1)}
        )
    return {
        "hits": [
            {
                "id": h.doc.id,
                "kind": h.doc.kind,
                "title": h.doc.title,
                "text": h.doc.text,
                "tables": h.doc.tables,
                "payload": h.doc.payload,
                "score": round(h.score, 5),
            }
            for h in hits
        ]
    }


class _HitView:
    """Adapter so the offline gateway can read hits like retriever objects."""

    def __init__(self, d: dict) -> None:
        from insightly.semantic.layer import Doc

        self.doc = Doc(d["id"], d["kind"], d["title"], d["text"], d["tables"], d["payload"])
        self.score = d["score"]


@node("generate_sql")
def generate_sql(state: AgentState, runtime: Runtime[RunContext]) -> dict:
    s = get_settings()
    attempts = state.get("attempts", 0)
    tier = "sql_strong" if attempts >= s.escalate_after_attempts else "sql"
    hits = state.get("hits") or []
    user = prompts.sql_user(
        question=state["standalone_question"],
        metrics=[h["text"] for h in hits if h["kind"] == "metric"],
        examples=[h["text"] for h in hits if h["kind"] == "example"][:4],
        tables=[h["text"] for h in hits if h["kind"] == "table"],
        previous_sql=state.get("sql"),
        error=state.get("last_error"),
    )
    draft: SQLDraft = get_gateway().structured(
        node="generate_sql",
        tier=tier,
        system=prompts.sql_system(),
        user=user,
        schema=SQLDraft,
        ledger=runtime.context.ledger,
        context={"hits": [_HitView(h) for h in hits], "question": state["standalone_question"]},
    )
    return {
        "sql": draft.sql,
        "sql_draft": draft.model_dump(),
        "attempts": attempts + 1,
        "escalated": state.get("escalated", False) or tier == "sql_strong",
        "metric_ids": draft.metric_ids,
        "last_error": None,
        "error_stage": None,
    }


@node("validate_sql")
def validate_sql(state: AgentState, runtime: Runtime[RunContext]) -> dict:
    res = check_sql(state["sql"] or "", load_semantic_layer().allowed_tables)
    if not res.ok:
        out = {"last_error": res.error, "error_stage": "validate"}
        if state.get("attempts") == 1:
            out["first_attempt_ok"] = False
        return out
    return {"sql": res.sql}


@node("execute_sql")
def execute_sql(state: AgentState, runtime: Runtime[RunContext]) -> dict:
    runtime.context.ledger.check("execute_sql")
    try:
        result = get_engine().execute(state["sql"])
    except Exception as e:  # engine errors are fed back to the model for repair
        msg = str(e).splitlines()[0][:400]
        out = {"last_error": msg, "error_stage": "execute"}
        if state.get("attempts") == 1:
            out["first_attempt_ok"] = False
        return out
    runtime.context.ledger.add_athena("execute_sql", result.bytes_scanned)
    out = {
        "columns": result.columns,
        "rows": result.rows,
        "truncated": result.truncated,
        "bytes_scanned": result.bytes_scanned,
    }
    if state.get("attempts") == 1:
        out["first_attempt_ok"] = True
    return out


@node("build_chart")
def build_chart_node(state: AgentState, runtime: Runtime[RunContext]) -> dict:
    return {"chart": build_chart(state["columns"], state["rows"], state["standalone_question"])}


@node("compose_answer")
def compose_answer(state: AgentState, runtime: Runtime[RunContext]) -> dict:
    hits = state.get("hits") or []
    metric_ids = set(state.get("metric_ids") or [])
    notes = [
        h["text"].split("\n")[0]
        for h in hits
        if h["kind"] == "metric" and h["payload"].get("id") in metric_ids
    ]
    rows, cols = state.get("rows") or [], state.get("columns") or []
    if not rows:
        return {
            "answer": "No results found. Try a wider time range or a different filter.",
            "highlights": [],
            "faithfulness": 1.0,
            "status": "ok",
        }
    draft: AnswerDraft = get_gateway().structured(
        node="compose_answer",
        tier="answer",
        system=prompts.ANSWER_SYSTEM,
        user=prompts.answer_user(
            state["standalone_question"], state["sql"] or "", cols, rows, state.get("truncated", False), notes
        ),
        schema=AnswerDraft,
        ledger=runtime.context.ledger,
        context={"rows": rows, "columns": cols},
    )
    score, bad = faithfulness(draft.answer + " " + " ".join(draft.highlights), rows)
    answer, highlights = draft.answer, draft.highlights
    if score < 0.8:
        # Hallucination guard: never show numbers that are not in the result.
        log.warning("unfaithful_answer_replaced", ungrounded=bad[:5])
        first = ", ".join(f"{c}: {v}" for c, v in zip(cols, rows[0], strict=False))
        answer = f"Here are the results ({len(rows)} rows). Top row: {first}."
        highlights = []
        score = 1.0
    return {"answer": answer, "highlights": highlights, "faithfulness": round(score, 3), "status": "ok"}


@node("guard_output")
def guard_output(state: AgentState, runtime: Runtime[RunContext]) -> dict:
    findings = guards.scan_output(state.get("answer", ""), state.get("rows") or [])
    if findings:
        return {
            "status": "refused",
            "rows": [],
            "chart": None,
            "answer": "The result contained restricted personal data and was withheld.",
        }
    return {}


@node("fail")
def fail(state: AgentState, runtime: Runtime[RunContext]) -> dict:
    return {
        "status": "failed",
        "answer": (
            "I could not build a working query for this question. Please rephrase it, for example "
            "by naming the measure and time range."
        ),
        "rows": [],
        "columns": [],
    }


@node("finalize")
def finalize(state: AgentState, runtime: Runtime[RunContext]) -> dict:
    turn = {"question": state["question"], "sql": state.get("sql"), "answer": state.get("answer", "")}
    return {
        "history": [turn],
        "cost": runtime.context.ledger.summary(),
        "status": state.get("status") if state.get("status") != "running" else "ok",
    }


__all__ = ["model_for"]
