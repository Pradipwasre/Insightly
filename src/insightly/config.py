"""Typed runtime configuration.

Every setting is read from environment variables prefixed with ``INSIGHTLY_`` (or from a
local ``.env`` file). The same image runs on a laptop and on ECS; only the environment
changes. See ``.env.example`` for the full list.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="INSIGHTLY_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- runtime ---------------------------------------------------------------------------
    env: Literal["local", "dev", "prod"] = "local"
    log_level: str = "INFO"
    log_json: bool = False

    # --- LLM provider ----------------------------------------------------------------------
    # "openai"   : paid OpenAI models (production path)
    # "offline"  : no LLM at all; nearest verified example + rules. Used by CI and as the
    #              retrieval-only baseline the LLM must beat in evaluation.
    llm_provider: Literal["openai", "offline"] = "openai"
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    # Name of an AWS Secrets Manager secret holding the key (used on ECS instead of the env var)
    openai_secret_name: str | None = None
    openai_timeout_s: float = 30.0
    openai_max_retries: int = 2

    # Model tiers. Keep IDs in config so a model upgrade is a config change plus an eval run.
    model_router: str = "gpt-5.4-nano"  # intent + follow-up rewrite
    model_sql: str = "gpt-5.4-mini"  # first SQL attempt
    model_sql_strong: str = "gpt-5.4"  # escalation after a failed attempt
    model_answer: str = "gpt-5.4-nano"  # answer summary
    model_judge: str = "gpt-5.4-mini"  # LLM-as-judge in evaluation
    embedding_model: str = "text-embedding-3-small"
    embedding_dims: int = 1536
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high"] | None = "low"
    use_moderation: bool = False  # OpenAI moderation endpoint (free) on user input

    # --- query engine ----------------------------------------------------------------------
    query_engine: Literal["duckdb", "athena"] = "duckdb"
    duckdb_path: Path = ROOT_DIR / "data" / "insightly.duckdb"
    curated_dir: Path = ROOT_DIR / "data" / "curated"
    aws_region: str = Field(default="ap-south-1", validation_alias="AWS_REGION")
    athena_workgroup: str = "insightly"
    athena_database: str = "insightly_curated"
    athena_output: str | None = None  # s3://bucket/prefix/ ; workgroup default when unset
    data_bucket: str | None = None
    max_rows: int = 1000
    query_timeout_s: int = 60

    # --- semantic layer / vectors ----------------------------------------------------------
    semantic_dir: Path = ROOT_DIR / "semantic_layer"
    vector_store: Literal["memory", "pgvector"] = "memory"
    database_url: str | None = None  # postgresql://user:pass@host:5432/insightly
    database_secret_arn: str | None = None  # RDS-managed secret (ECS)
    retrieval_k: int = 8
    embedding_cache: Path = ROOT_DIR / ".cache" / "embeddings.json"

    # --- agent -----------------------------------------------------------------------------
    checkpointer: Literal["memory", "postgres"] = "memory"
    max_sql_attempts: int = 3  # first try + 2 repairs
    escalate_after_attempts: int = 1  # switch to model_sql_strong after N failed attempts
    history_turns: int = 3

    # --- cost controls ---------------------------------------------------------------------
    pricing_file: Path = ROOT_DIR / "config" / "pricing.yaml"
    request_budget_usd: float = 0.05  # hard stop per question
    daily_budget_usd: float = 5.0  # soft stop per user per day
    athena_usd_per_tb: float = 5.0
    answer_cache_ttl_s: int = 900  # identical question + role within TTL is served from cache

    # --- API / auth ------------------------------------------------------------------------
    auth_mode: Literal["disabled", "cognito"] = "disabled"
    cognito_user_pool_id: str | None = None
    cognito_client_id: str | None = None
    cors_origins: list[str] = ["http://localhost:8501"]
    feedback_path: Path = ROOT_DIR / "data" / "feedback.jsonl"

    # --- observability ---------------------------------------------------------------------
    emit_cloudwatch_emf: bool = False  # CloudWatch Embedded Metric Format in logs
    metrics_namespace: str = "Insightly"


@lru_cache
def get_settings() -> Settings:
    return Settings()
