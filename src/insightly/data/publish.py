"""Publish curated Parquet to S3 and register tables in Glue through Athena DDL.

Two layers:
* ``insightly_raw``     external Hive tables over the uploaded Parquet (staging)
* ``insightly_curated`` Apache Iceberg tables created with CTAS (what the agent queries)
"""

from __future__ import annotations

import time
from pathlib import Path

import boto3
import pyarrow.parquet as pq

from insightly.config import get_settings
from insightly.data.curate import AGENT_TABLES, RESTRICTED_TABLES

ARROW_TO_ATHENA = {
    "int64": "bigint",
    "int32": "int",
    "double": "double",
    "float": "float",
    "bool": "boolean",
    "string": "string",
    "large_string": "string",
    "timestamp[ns]": "timestamp",
    "timestamp[us]": "timestamp",
}
PARTITIONS = {"events": "ARRAY['month(created_at)']", "order_items": "ARRAY['year(created_at)']"}


def _athena_type(arrow_type: str) -> str:
    return ARROW_TO_ATHENA.get(arrow_type, "string")


def _run(athena, sql: str, workgroup: str) -> None:
    qid = athena.start_query_execution(QueryString=sql, WorkGroup=workgroup)["QueryExecutionId"]
    while True:
        st = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
        if st["State"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        time.sleep(1)
    if st["State"] != "SUCCEEDED":
        raise RuntimeError(f"Athena failed: {st.get('StateChangeReason')}\n{sql}")


def publish(curated_dir: Path, bucket: str) -> list[str]:
    s = get_settings()
    s3 = boto3.client("s3", region_name=s.aws_region)
    athena = boto3.client("athena", region_name=s.aws_region)
    wg, raw_db, cur_db = s.athena_workgroup, "insightly_raw", s.athena_database
    _run(athena, f"CREATE DATABASE IF NOT EXISTS {raw_db}", wg)
    _run(athena, f"CREATE DATABASE IF NOT EXISTS {cur_db}", wg)
    done = []
    for table in [*AGENT_TABLES, *RESTRICTED_TABLES]:
        local = curated_dir / table / "part-000.parquet"
        key = f"staging/{table}/part-000.parquet"
        s3.upload_file(str(local), bucket, key)
        schema = pq.read_schema(local)
        cols = ",\n  ".join(f"`{f.name}` {_athena_type(str(f.type))}" for f in schema)
        _run(athena, f"DROP TABLE IF EXISTS {raw_db}.{table}", wg)
        _run(
            athena,
            f"""CREATE EXTERNAL TABLE {raw_db}.{table} (
  {cols}
) STORED AS PARQUET LOCATION 's3://{bucket}/staging/{table}/'""",
            wg,
        )
        _run(athena, f"DROP TABLE IF EXISTS {cur_db}.{table}", wg)
        part = f", partitioning = {PARTITIONS[table]}" if table in PARTITIONS else ""
        _run(
            athena,
            f"""CREATE TABLE {cur_db}.{table}
WITH (table_type = 'ICEBERG', is_external = false,
      location = 's3://{bucket}/curated/{table}/'{part})
AS SELECT * FROM {raw_db}.{table}""",
            wg,
        )
        done.append(table)
    return done
