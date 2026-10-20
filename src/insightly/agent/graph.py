"""The Insightly LangGraph.

prepare -> guard_input -> route_intent -> [clarify] -> retrieve -> generate_sql
        -> validate_sql -> execute_sql -> [build_chart] -> compose_answer -> guard_output
        -> finalize
with a bounded repair loop (validate/execute errors go back to generate_sql, max
``max_sql_attempts``) and early exits for refusals, out-of-scope questions and budget stops.
"""

from __future__ import annotations

from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from insightly.agent import nodes as n
from insightly.agent.state import AgentState, RunContext
from insightly.config import get_settings


def _stopped(state: AgentState) -> bool:
    return state.get("status") in {"refused", "out_of_scope", "budget_exceeded"}


def after_guard(state: AgentState) -> str:
    return "finalize" if _stopped(state) else "route_intent"


def after_route(state: AgentState) -> str:
    if _stopped(state) or state.get("intent") == "small_talk":
        return "finalize"
    if state.get("intent") == "ambiguous":
        return "clarify"
    return "retrieve"


def after_sql_step(ok_next: str):
    def _route(state: AgentState) -> str:
        if _stopped(state):
            return "finalize"
        if state.get("last_error"):
            return "generate_sql" if state.get("attempts", 0) < get_settings().max_sql_attempts else "fail"
        return ok_next

    return _route


def after_generate(state: AgentState) -> str:
    return "finalize" if _stopped(state) else "validate_sql"


def after_execute(state: AgentState) -> str:
    nxt = after_sql_step("chart_or_answer")(state)
    if nxt != "chart_or_answer":
        return nxt
    return "build_chart" if state.get("wants_chart") else "compose_answer"


def build_graph(checkpointer=None):
    g = StateGraph(AgentState, context_schema=RunContext)
    g.add_node("prepare", n.prepare)
    g.add_node("guard_input", n.guard_input)
    g.add_node("route_intent", n.route_intent)
    g.add_node("clarify", n.clarify)
    g.add_node("retrieve", n.retrieve)
    g.add_node("generate_sql", n.generate_sql)
    g.add_node("validate_sql", n.validate_sql)
    g.add_node("execute_sql", n.execute_sql)
    g.add_node("build_chart", n.build_chart_node)
    g.add_node("compose_answer", n.compose_answer)
    g.add_node("guard_output", n.guard_output)
    g.add_node("fail", n.fail)
    g.add_node("finalize", n.finalize)

    g.add_edge(START, "prepare")
    g.add_edge("prepare", "guard_input")
    g.add_conditional_edges("guard_input", after_guard, ["route_intent", "finalize"])
    g.add_conditional_edges("route_intent", after_route, ["clarify", "retrieve", "finalize"])
    g.add_edge("clarify", "retrieve")
    g.add_edge("retrieve", "generate_sql")
    g.add_conditional_edges("generate_sql", after_generate, ["validate_sql", "finalize"])
    g.add_conditional_edges(
        "validate_sql", after_sql_step("execute_sql"), ["execute_sql", "generate_sql", "fail", "finalize"]
    )
    g.add_conditional_edges(
        "execute_sql", after_execute, ["build_chart", "compose_answer", "generate_sql", "fail", "finalize"]
    )
    g.add_edge("build_chart", "compose_answer")
    g.add_conditional_edges(
        "compose_answer",
        lambda s: "finalize" if _stopped(s) else "guard_output",
        ["guard_output", "finalize"],
    )
    g.add_edge("guard_output", "finalize")
    g.add_edge("fail", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)


def make_checkpointer():
    s = get_settings()
    if s.checkpointer == "postgres":
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg import Connection
        from psycopg.rows import dict_row

        from insightly.db import resolve_database_url

        conn = Connection.connect(
            resolve_database_url(), autocommit=True, prepare_threshold=0, row_factory=dict_row
        )
        saver = PostgresSaver(conn)
        saver.setup()
        return saver
    from langgraph.checkpoint.memory import InMemorySaver

    return InMemorySaver()


@lru_cache
def get_graph():
    return build_graph(make_checkpointer())
