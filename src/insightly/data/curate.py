"""Raw CSV -> curated Parquet.

Applies the business rules from the data catalog once, at ingestion time, so the agent never
has to remember them:

* timestamps parsed as UTC
* duplicate category labels merged into ``category_group``
* ``events.traffic_source`` mapped onto the ``users.traffic_source`` vocabulary (``channel``)
* $0.02 test prices flagged with ``is_test_price``
* PII split out of ``users`` into the restricted ``users_pii`` table
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

TS_COLS = {
    "users": ["created_at"],
    "orders": ["created_at", "returned_at", "shipped_at", "delivered_at"],
    "order_items": ["created_at", "shipped_at", "delivered_at", "returned_at"],
    "inventory_items": ["created_at", "sold_at"],
    "events": ["created_at"],
}
CATEGORY_GROUPS = {
    "Socks & Hosiery": "Socks",
    "Pants & Capris": "Pants",
    "Suits & Sport Coats": "Suits",
}
EVENT_CHANNEL = {"Adwords": "Search", "YouTube": "Display"}
PII_COLUMNS = ["first_name", "last_name", "email", "street_address", "postal_code", "latitude", "longitude"]
TABLES = ["distribution_centers", "products", "users", "orders", "order_items", "inventory_items", "events"]
# Tables the agent may query. users_pii is deliberately absent.
AGENT_TABLES = TABLES
RESTRICTED_TABLES = ["users_pii"]


def _parse_ts(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for c in cols:
        s = df[c].astype("string").str.replace(" UTC", "", regex=False)
        df[c] = pd.to_datetime(s, errors="coerce", format="mixed").dt.tz_localize(None)
        df[c] = df[c].astype("datetime64[us]")
    return df


def curate(raw_dir: Path, out_dir: Path) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for name in TABLES:
        df = pd.read_csv(raw_dir / f"{name}.csv", low_memory=False)
        df = _parse_ts(df, TS_COLS.get(name, []))
        if name == "products":
            df["category_group"] = df["category"].map(CATEGORY_GROUPS).fillna(df["category"])
            df["is_test_price"] = df["retail_price"] < 1.0
        if name == "events":
            df["user_id"] = df["user_id"].astype("Int64")
            df["channel"] = df["traffic_source"].map(EVENT_CHANNEL).fillna(df["traffic_source"])
        if name == "users":
            df["country"] = df["country"].replace({"Brasil": "Brazil"})
            pii = df[["id", *PII_COLUMNS]]
            _write(pii, out_dir, "users_pii")
            counts["users_pii"] = len(pii)
            df = df.drop(columns=PII_COLUMNS)
        _write(df, out_dir, name)
        counts[name] = len(df)
    return counts


def _write(df: pd.DataFrame, out_dir: Path, name: str) -> None:
    target = out_dir / name
    target.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    # INT96 timestamps are read correctly by both Athena (Hive tables) and DuckDB.
    pq.write_table(
        table, target / "part-000.parquet", compression="zstd", use_deprecated_int96_timestamps=True
    )
