"""Structured outputs. Every LLM call returns one of these, validated by Pydantic.

All fields are required (nullable where optional) so they work with OpenAI strict
``json_schema`` mode.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Intent = Literal["analytics", "follow_up", "ambiguous", "out_of_scope", "small_talk"]


class RouteDecision(BaseModel):
    intent: Intent = Field(description="What the user wants")
    standalone_question: str = Field(
        description="The question rewritten to be fully self-contained using the conversation"
    )
    wants_chart: bool = Field(description="True if a chart/plot/graph is requested or clearly useful")
    clarification_question: str | None = Field(
        description="Only when intent is ambiguous: one short question to ask the user"
    )
    options: list[str] = Field(description="2-3 concrete options when ambiguous, else empty")


class SQLDraft(BaseModel):
    sql: str = Field(description="One Trino/Athena SELECT statement")
    tables_used: list[str] = Field(description="Tables referenced")
    metric_ids: list[str] = Field(description="Certified metric ids used, empty if none")
    assumptions: list[str] = Field(description="Assumptions made, e.g. default time range")


class AnswerDraft(BaseModel):
    answer: str = Field(description="2-4 sentence answer that only uses numbers from the result")
    highlights: list[str] = Field(description="Up to 3 short bullet insights")


class JudgeScore(BaseModel):
    score: int = Field(description="1-5")
    reason: str
