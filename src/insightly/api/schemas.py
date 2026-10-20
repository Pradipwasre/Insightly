from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str | None = Field(default=None, max_length=1500)
    thread_id: str | None = None
    resume: str | None = Field(default=None, description="Answer to a clarification question")


class AskResponse(BaseModel):
    thread_id: str
    status: str
    answer: str | None = None
    highlights: list[str] | None = None
    sql: str | None = None
    columns: list[str] | None = None
    rows: list[list[Any]] | None = None
    truncated: bool | None = None
    chart: dict | None = None
    clarification: dict | None = None
    metric_ids: list[str] | None = None
    faithfulness: float | None = None
    attempts: int | None = None
    trace: list[str] | None = None
    latency_ms: float | None = None
    cached: bool = False
    cost: dict | None = None


class FeedbackRequest(BaseModel):
    thread_id: str
    rating: Literal["up", "down"]
    question: str
    sql: str | None = None
    corrected_sql: str | None = None
    comment: str | None = Field(default=None, max_length=2000)
