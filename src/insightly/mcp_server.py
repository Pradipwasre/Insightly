"""Insightly as an MCP server (Model Context Protocol, python SDK 2.x).

Lets other agents and IDE assistants use governed analytics as tools:
  search_semantic_layer, validate_sql, run_query, ask_insightly

Run:  uv run insightly mcp            (stdio, for Claude Desktop / VS Code agents)
      uv run insightly mcp --http     (streamable HTTP on :8765)
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from insightly.agent.service import ask
from insightly.agent.sql_guard import check_sql
from insightly.data.engine import get_engine
from insightly.semantic.layer import load_semantic_layer
from insightly.semantic.retriever import get_retriever

server = MCPServer(
    name="insightly",
    instructions="Governed analytics over the retail lakehouse. Read-only. PII is never returned.",
)


@server.tool(description="Find tables, certified metrics and verified example queries.")
def search_semantic_layer(query: str, k: int = 6) -> list[dict]:
    return [
        {"id": h.doc.id, "kind": h.doc.kind, "title": h.doc.title, "text": h.doc.text}
        for h in get_retriever().search(query, k)
    ]


@server.tool(description="Check a Trino/Athena SELECT against the SQL firewall without running it.")
def validate_sql(sql: str) -> dict:
    r = check_sql(sql, load_semantic_layer().allowed_tables)
    return {"ok": r.ok, "sql": r.sql, "error": r.error, "tables": r.tables}


@server.tool(description="Run a validated read-only SELECT and return up to 200 rows.")
def run_query(sql: str) -> dict:
    r = check_sql(sql, load_semantic_layer().allowed_tables, max_rows=200)
    if not r.ok:
        return {"error": r.error}
    res = get_engine().execute(r.sql, max_rows=200)
    return {"columns": res.columns, "rows": res.rows, "truncated": res.truncated}


@server.tool(description="Ask Insightly a business question in plain English.")
def ask_insightly(question: str) -> dict:
    out = ask(question, user_id="mcp", role="analyst")
    return {k: out.get(k) for k in ("status", "answer", "sql", "columns", "rows", "metric_ids")}


def run(http: bool = False) -> None:
    if http:
        server.run(transport="streamable-http", port=8765)
    else:
        server.run()
