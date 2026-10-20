"""Deterministic SQL firewall. Runs before any query reaches Athena.

Rules (each one is tested in tests/test_sql_guard.py):
1. exactly one statement, and it must be a query (SELECT / UNION / WITH ... SELECT)
2. no DDL, DML or engine commands anywhere in the tree
3. only tables from the semantic layer allow-list (CTE names are allowed)
4. no restricted PII columns
5. a LIMIT is added when missing
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

from insightly.config import get_settings

FORBIDDEN_NODES = tuple(
    getattr(exp, n)
    for n in (
        "Insert",
        "Update",
        "Delete",
        "Drop",
        "Create",
        "Alter",
        "Command",
        "Merge",
        "TruncateTable",
        "Grant",
        "Into",
        "Copy",
        "Use",
        "Set",
        "Pragma",
    )
    if hasattr(exp, n)
)
PII_COLUMNS = {"email", "first_name", "last_name", "street_address", "postal_code", "ip_address", "phone"}


@dataclass
class GuardResult:
    ok: bool
    sql: str = ""
    error: str | None = None
    tables: list[str] = field(default_factory=list)


def check_sql(sql: str, allowed_tables: set[str], max_rows: int | None = None) -> GuardResult:
    max_rows = max_rows or get_settings().max_rows
    sql = sql.strip().rstrip(";").strip()
    if not sql:
        return GuardResult(False, error="Empty SQL.")
    try:
        statements = [s for s in sqlglot.parse(sql, read="trino") if s is not None]
    except sqlglot.errors.ParseError as e:
        return GuardResult(False, error=f"SQL does not parse: {str(e).splitlines()[0]}")
    if len(statements) != 1:
        return GuardResult(False, error="Exactly one SQL statement is allowed.")
    root = statements[0]
    if not isinstance(root, exp.Query):
        return GuardResult(False, error="Only SELECT queries are allowed.")
    bad = next(iter(root.find_all(*FORBIDDEN_NODES)), None) if FORBIDDEN_NODES else None
    if bad is not None:
        return GuardResult(False, error=f"Forbidden operation: {type(bad).__name__}.")

    cte_names = {c.alias_or_name.lower() for c in root.find_all(exp.CTE)}
    db = get_settings().athena_database.lower()
    tables = set()
    for t in root.find_all(exp.Table):
        name = t.name.lower()
        if name in cte_names:
            continue
        if t.db and t.db.lower() not in {db, ""}:
            return GuardResult(False, error=f"Database '{t.db}' is not allowed.")
        if name not in allowed_tables:
            return GuardResult(False, error=f"Table '{name}' is not allowed. Use: {sorted(allowed_tables)}.")
        tables.add(name)
    for c in root.find_all(exp.Column):
        if c.name.lower() in PII_COLUMNS:
            return GuardResult(False, error=f"Column '{c.name}' is restricted (PII).")
    if isinstance(root, exp.Select) and root.find(exp.Star) and "events" in tables:
        return GuardResult(False, error="SELECT * on events is not allowed; select columns.")

    limit = root.args.get("limit")
    if limit is None:
        root = root.limit(max_rows)
    return GuardResult(True, sql=root.sql(dialect="trino", pretty=True), tables=sorted(tables))
