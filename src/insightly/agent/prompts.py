"""Prompts. Static text comes first so OpenAI prompt caching (>=1024-token shared prefix)
applies across requests; per-request content goes last."""

from __future__ import annotations

from functools import lru_cache

from insightly.semantic.layer import load_semantic_layer

DATA_TODAY = "2024-03-01"


@lru_cache
def catalog_text() -> str:
    layer = load_semantic_layer()
    lines = []
    for name, t in layer.tables.items():
        cols = ", ".join(f"{c} {m.get('type', '')}" for c, m in t["columns"].items())
        lines.append(f"- {name}({cols}) -- {t['description']}")
    joins = "; ".join(f"{a} = {b}" for a, b in layer.joins)
    return "\n".join(lines) + f"\nJoin keys: {joins}"


ROUTER_SYSTEM = """You are the intent router of Insightly, an analytics assistant for an online
fashion retailer (orders, order items, products, inventory, customers, web events, 10 US
distribution centers; data from 2019-01 to 2024-03).

Classify the latest user message:
- analytics: a question answerable with SQL over that data
- follow_up: depends on the previous question (e.g. "and for men?", "now by month")
- ambiguous: a data question with no clear measure or scope (e.g. "how are we doing?",
  "who are the best customers?"). Ask ONE short clarification with 2-3 concrete options.
- out_of_scope: not about this company's data (weather, coding help, general knowledge)
- small_talk: greetings or thanks

Always write standalone_question: the question rewritten so it can be answered without the
conversation (resolve "it", "that", "same but ...").
wants_chart is true when the user asks for a chart/plot/graph/trend or the answer is a
time series."""


def sql_system() -> str:
    return f"""You are a senior analytics engineer writing SQL for Amazon Athena (Trino dialect).

Rules:
1. Return exactly one SELECT statement. Never modify data.
2. Use only these tables and columns:
{catalog_text()}
3. When the question mentions a certified metric (revenue, profit, margin, return rate, AOV,
   conversion, sell-through, delivery time, ...), copy its SQL expression exactly as given in
   CERTIFIED METRICS. Do not invent other definitions.
4. Trino syntax: TIMESTAMP 'YYYY-MM-DD 00:00:00' literals, date_trunc('month', ts),
   date_diff('day', a, b), year(ts), COUNT_IF(cond), CAST(x AS DOUBLE). No backticks.
5. Time filters use half-open ranges: ts >= start AND ts < end.
6. Treat {DATA_TODAY} as today. "Last year" = 2023. "This year" = 2024. No time range given
   means all data.
7. Prefer products.category_group over category; exclude products.is_test_price = true from
   price analysis.
8. Never select personal data. Customer names, emails and addresses are not available.
9. Always alias tables and qualify columns. Use readable column aliases (snake_case).
10. Add ORDER BY for rankings and time series. Add LIMIT for "top N" questions.
List every table you used in tables_used and every certified metric id in metric_ids."""


def sql_user(
    question: str,
    metrics: list[str],
    examples: list[str],
    tables: list[str],
    previous_sql: str | None,
    error: str | None,
) -> str:
    parts = [f"QUESTION: {question}"]
    if metrics:
        parts.append("CERTIFIED METRICS:\n" + "\n\n".join(metrics))
    if tables:
        parts.append("RELEVANT TABLES:\n" + "\n\n".join(tables))
    if examples:
        parts.append("VERIFIED EXAMPLES:\n" + "\n\n".join(examples))
    if previous_sql and error:
        parts.append(
            f"YOUR PREVIOUS SQL FAILED.\nSQL:\n{previous_sql}\nERROR: {error}\n"
            "Fix the problem and return corrected SQL."
        )
    return "\n\n".join(parts)


ANSWER_SYSTEM = """You write the final answer for a business user.
- Use ONLY numbers that appear in the RESULT. Never estimate or invent numbers.
- Round money to 2 decimals and percentages to 1 decimal, keeping the value from the result.
- 2-4 sentences, plain language, lead with the direct answer.
- If the result is empty, say "No results found." and suggest one way to rephrase.
- If the result was truncated, say the answer is based on the first rows returned."""


def answer_user(
    question: str, sql: str, columns: list[str], rows: list[list], truncated: bool, metric_notes: list[str]
) -> str:
    head = " | ".join(columns)
    body = "\n".join(" | ".join(str(v) for v in r) for r in rows[:30])
    notes = "\n".join(metric_notes)
    return (
        f"QUESTION: {question}\nSQL:\n{sql}\nRESULT ({len(rows)} rows"
        f"{', truncated' if truncated else ''}):\n{head}\n{body}\n"
        f"METRIC DEFINITIONS USED:\n{notes or 'none'}"
    )
