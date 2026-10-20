"""Database URL resolution: env var locally, RDS-managed secret on ECS."""

from __future__ import annotations

import json
from functools import lru_cache
from urllib.parse import quote_plus

from insightly.config import get_settings


@lru_cache
def resolve_database_url() -> str:
    s = get_settings()
    if s.database_url:
        return s.database_url
    if s.database_secret_arn:
        import boto3

        sm = boto3.client("secretsmanager", region_name=s.aws_region)
        sec = json.loads(sm.get_secret_value(SecretId=s.database_secret_arn)["SecretString"])
        return (
            f"postgresql://{sec['username']}:{quote_plus(sec['password'])}@{sec['host']}:"
            f"{sec.get('port', 5432)}/{sec.get('dbname', 'insightly')}?sslmode=require"
        )
    raise RuntimeError("Set INSIGHTLY_DATABASE_URL or INSIGHTLY_DATABASE_SECRET_ARN")
