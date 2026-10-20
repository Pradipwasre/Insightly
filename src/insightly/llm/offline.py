"""Offline gateway: zero-cost, deterministic stand-in for the LLM.

It is the **retrieval-only baseline**: it picks the SQL of the most similar verified example
and uses keyword rules for routing. CI runs the whole pipeline with it (no API key needed),
and the evaluation report shows how much the real LLM improves on it.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from insightly.cost.tracker import CostLedger
from insightly.llm.schemas import AnswerDraft, JudgeScore, RouteDecision, SQLDraft

CHART_WORDS = re.compile(r"\b(plot|chart|graph|visuali[sz]e|trend|diagram)\b", re.I)
FOLLOW_UP = re.compile(r"^(and|what about|how about|now|same|only|break (it|that) down)\b", re.I)
VAGUE = re.compile(r"\b(best|good|performance|doing|how are we|insights?)\b", re.I)
SMALL_TALK = re.compile(r"^(hi|hello|hey|thanks|thank you|who are you)\b", re.I)
DOMAIN = re.compile(
    r"\b(order|revenue|sales|profit|margin|return|cancel|customer|user|product|brand|categor|"
    r"inventory|stock|deliver|ship|session|event|conversion|traffic|channel|department|"
    r"distribution|warehouse|price|aov|browser|country|signup|units|sell)",
    re.I,
)


class OfflineGateway:
    provider = "offline"

    def structured(
        self,
        *,
        node: str,
        tier: str,
        system: str,
        user: str,
        schema: type[BaseModel],
        ledger: CostLedger,
        context: dict | None = None,
    ):
        ctx = context or {}
        ledger.add_llm(node, "offline", {"input_tokens": 0, "output_tokens": 0})
        if schema is RouteDecision:
            return self._route(ctx["question"], ctx.get("previous_question"))
        if schema is SQLDraft:
            ex = next((h for h in ctx.get("hits", []) if h.doc.kind == "example"), None)
            if ex is None:
                return SQLDraft(
                    sql="SELECT 1 AS no_match",
                    tables_used=[],
                    metric_ids=[],
                    assumptions=["no similar verified example"],
                )
            return SQLDraft(
                sql=ex.doc.payload["sql"],
                tables_used=ex.doc.tables,
                metric_ids=[h.doc.payload["id"] for h in ctx["hits"] if h.doc.kind == "metric"][:1],
                assumptions=[f"reused verified example: {ex.doc.title}"],
            )
        if schema is AnswerDraft:
            rows = ctx.get("rows") or []
            cols = ctx.get("columns") or []
            if not rows:
                return AnswerDraft(answer="No results found.", highlights=[])
            first = ", ".join(f"{c} = {v}" for c, v in zip(cols, rows[0], strict=False))
            return AnswerDraft(
                answer=f"The query returned {len(rows)} rows. First row: {first}.", highlights=[]
            )
        if schema is JudgeScore:
            return JudgeScore(score=3, reason="offline judge")
        raise TypeError(schema)

    def _route(self, q: str, prev: str | None) -> RouteDecision:
        wants_chart = bool(CHART_WORDS.search(q))
        if SMALL_TALK.search(q):
            return RouteDecision(
                intent="small_talk",
                standalone_question=q,
                wants_chart=False,
                clarification_question=None,
                options=[],
            )
        if prev and FOLLOW_UP.search(q):
            return RouteDecision(
                intent="follow_up",
                standalone_question=f"{prev} {q}",
                wants_chart=wants_chart,
                clarification_question=None,
                options=[],
            )
        if VAGUE.search(q) and len(q.split()) <= 6:
            return RouteDecision(
                intent="ambiguous",
                standalone_question=q,
                wants_chart=wants_chart,
                clarification_question="Which measure should I use?",
                options=["Net revenue", "Gross profit", "Number of orders"],
            )
        if not DOMAIN.search(q):
            return RouteDecision(
                intent="out_of_scope",
                standalone_question=q,
                wants_chart=False,
                clarification_question=None,
                options=[],
            )
        return RouteDecision(
            intent="analytics",
            standalone_question=q,
            wants_chart=wants_chart,
            clarification_question=None,
            options=[],
        )

    def moderate(self, text: str) -> bool:
        return False
