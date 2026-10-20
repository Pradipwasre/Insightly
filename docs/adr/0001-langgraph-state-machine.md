# ADR 0001: LangGraph state machine instead of a free-form agent

**Status:** accepted

**Context.** The prototype used `create_sql_agent` (ReAct over SQL tools) plus a Python REPL agent,
routed by keywords. Behaviour, cost and latency varied per question and failures were hard to locate.

**Decision.** One LangGraph `StateGraph` with explicit nodes (guard, route, clarify, retrieve,
generate, validate, execute, chart, answer, guard, finalize), conditional edges, and a repair loop
bounded by `max_sql_attempts`. Human-in-the-loop clarification uses `interrupt()` with a Postgres
checkpointer. Per-run dependencies (cost ledger, user, role) are passed with LangGraph's runtime
`context`, not stored in state.

**Consequences.** Every node is unit-testable and has its own metric; worst-case cost is bounded;
adding autonomy later (a planner sub-graph) is a local change. Less flexible for open-ended
questions, which are out of scope for v1.
