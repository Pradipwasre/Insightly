"""Query engines behind one interface.

The agent always writes **Trino SQL** (the Athena engine v3 dialect). Locally, sqlglot
transpiles it to DuckDB so the same SQL, prompts and golden set work on a laptop and on AWS.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Protocol

import sqlglot

from insightly.config import get_settings
from insightly.data.curate import AGENT_TABLES, RESTRICTED_TABLES


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    elapsed_ms: float
    bytes_scanned: int = 0
    truncated: bool = False
    engine: str = ""
    extra: dict = field(default_factory=dict)

    def preview(self, n: int = 20) -> list[dict[str, Any]]:
        return [dict(zip(self.columns, r, strict=False)) for r in self.rows[:n]]


class QueryEngine(Protocol):
    name: str

    def execute(self, sql: str, max_rows: int | None = None) -> QueryResult: ...


def _jsonable(v: Any) -> Any:
    if v is None or isinstance(v, (int, float, str, bool)):
        return v
    if hasattr(v, "isoformat"):
        return v.isoformat()
    try:
        return float(v)  # Decimal
    except (TypeError, ValueError):
        return str(v)


class DuckDBEngine:
    name = "duckdb"

    def __init__(self) -> None:
        import duckdb

        s = get_settings()
        self.conn = duckdb.connect(database=":memory:")
        for t in [*AGENT_TABLES, *RESTRICTED_TABLES]:
            path = (s.curated_dir / t / "*.parquet").as_posix()
            self.conn.execute(f"CREATE OR REPLACE VIEW {t} AS SELECT * FROM read_parquet('{path}')")

    def execute(self, sql: str, max_rows: int | None = None) -> QueryResult:
        max_rows = max_rows or get_settings().max_rows
        local_sql = sqlglot.transpile(sql, read="trino", write="duckdb")[0]
        t0 = time.perf_counter()
        cur = self.conn.cursor()
        cur.execute(local_sql)
        rows = cur.fetchmany(max_rows + 1)
        cols = [d[0] for d in cur.description]
        elapsed = (time.perf_counter() - t0) * 1000
        truncated = len(rows) > max_rows
        rows = [[_jsonable(v) for v in r] for r in rows[:max_rows]]
        return QueryResult(cols, rows, elapsed, 0, truncated, self.name)


class AthenaEngine:
    """Runs SQL in an Athena workgroup. The workgroup enforces the bytes-scanned cutoff and
    result encryption; the ECS task role only has read access to the curated database."""

    name = "athena"

    def __init__(self) -> None:
        from pyathena import connect

        s = get_settings()
        kwargs: dict[str, Any] = {
            "region_name": s.aws_region,
            "work_group": s.athena_workgroup,
            "schema_name": s.athena_database,
        }
        if s.athena_output:
            kwargs["s3_staging_dir"] = s.athena_output
        self.conn = connect(**kwargs)

    def execute(self, sql: str, max_rows: int | None = None) -> QueryResult:
        max_rows = max_rows or get_settings().max_rows
        t0 = time.perf_counter()
        cur = self.conn.cursor()
        cur.execute(sql)
        rows = cur.fetchmany(max_rows + 1)
        cols = [d[0] for d in cur.description or []]
        elapsed = (time.perf_counter() - t0) * 1000
        truncated = len(rows) > max_rows
        rows = [[_jsonable(v) for v in r] for r in rows[:max_rows]]
        return QueryResult(
            cols,
            rows,
            elapsed,
            int(cur.data_scanned_in_bytes or 0),
            truncated,
            self.name,
            {"query_id": cur.query_id},
        )


@lru_cache
def get_engine() -> QueryEngine:
    return AthenaEngine() if get_settings().query_engine == "athena" else DuckDBEngine()
