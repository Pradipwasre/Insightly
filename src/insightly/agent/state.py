"""Graph state and per-run context."""

from __future__ import annotations

import operator
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

from insightly.cost.tracker import CostLedger


class Turn(TypedDict):
    question: str
    sql: str | None
    answer: str


class AgentState(TypedDict, total=False):
    # input
    question: str
    # routing
    intent: str
    standalone_question: str
    wants_chart: bool
    clarification: dict | None
    # retrieval
    hits: list[dict]
    # sql loop
    sql: str | None
    sql_draft: dict | None
    attempts: int
    last_error: str | None
    error_stage: str | None
    first_attempt_ok: bool | None
    escalated: bool
    # result
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool
    bytes_scanned: int
    chart: dict | None
    answer: str
    highlights: list[str]
    faithfulness: float | None
    metric_ids: list[str]
    status: str  # ok | clarify | refused | out_of_scope | failed | budget_exceeded
    # telemetry
    trace: list[str]  # node path of the current turn
    timings_ms: dict[str, float]
    cost: dict
    # memory across turns in the same thread
    history: Annotated[list[Turn], operator.add]


@dataclass
class RunContext:
    """Not checkpointed. Passed with ``graph.invoke(..., context=RunContext(...))``."""

    user_id: str = "anonymous"
    role: str = "analyst"
    ledger: CostLedger = field(default_factory=lambda: CostLedger(budget_usd=0.05))
