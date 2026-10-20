"""LLM gateway: one place for model selection, structured output, retries and cost capture.

Nodes never instantiate a model directly. They ask the gateway for a *tier*:

=============  ==================  ==========================================
tier           default model       used by
=============  ==================  ==========================================
router         gpt-5.4-nano        intent classification + follow-up rewrite
sql            gpt-5.4-mini        first SQL attempt
sql_strong     gpt-5.4             escalation after a failed attempt
answer         gpt-5.4-nano        final answer text
judge          gpt-5.4-mini        LLM-as-judge (evaluation only)
=============  ==================  ==========================================
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, TypeVar

from pydantic import BaseModel

from insightly.config import get_settings
from insightly.cost.tracker import CostLedger

T = TypeVar("T", bound=BaseModel)

TIERS = {
    "router": "model_router",
    "sql": "model_sql",
    "sql_strong": "model_sql_strong",
    "answer": "model_answer",
    "judge": "model_judge",
}


def model_for(tier: str) -> str:
    return getattr(get_settings(), TIERS[tier])


@lru_cache
def openai_api_key() -> str:
    s = get_settings()
    if s.openai_api_key:
        return s.openai_api_key.get_secret_value()
    if s.openai_secret_name:
        import boto3

        sm = boto3.client("secretsmanager", region_name=s.aws_region)
        value = sm.get_secret_value(SecretId=s.openai_secret_name)["SecretString"]
        try:
            return json.loads(value)["OPENAI_API_KEY"]
        except (ValueError, KeyError):
            return value.strip()
    raise RuntimeError(
        "No OpenAI key. Set OPENAI_API_KEY in .env (local) or INSIGHTLY_OPENAI_SECRET_NAME (AWS)."
    )


class OpenAIGateway:
    provider = "openai"

    def __init__(self, http_client: Any = None) -> None:
        self._models: dict[str, Any] = {}
        self._http_client = http_client  # injectable for tests

    def _chat(self, model: str):
        if model not in self._models:
            from langchain_openai import ChatOpenAI

            s = get_settings()
            kwargs: dict[str, Any] = {
                "model": model,
                "api_key": openai_api_key(),
                "timeout": s.openai_timeout_s,
                "max_retries": s.openai_max_retries,
            }
            if s.reasoning_effort:
                kwargs["reasoning_effort"] = s.reasoning_effort
            if self._http_client is not None:
                kwargs["http_client"] = self._http_client
            self._models[model] = ChatOpenAI(**kwargs)
        return self._models[model]

    def structured(
        self,
        *,
        node: str,
        tier: str,
        system: str,
        user: str,
        schema: type[T],
        ledger: CostLedger,
        context: dict | None = None,
    ) -> T:
        model = model_for(tier)
        ledger.check(node)
        runnable = self._chat(model).with_structured_output(
            schema, method="json_schema", include_raw=True, strict=True
        )
        out = runnable.invoke(
            [("system", system), ("human", user)],
            config={
                "run_name": f"{node}:{model}",
                "tags": [node, tier],
                "metadata": {"model": model, "tier": tier},
            },
        )
        raw = out.get("raw")
        ledger.add_llm(node, model, getattr(raw, "usage_metadata", None))
        if out.get("parsing_error") or out.get("parsed") is None:
            raise ValueError(f"{node}: model returned unparseable output: {out.get('parsing_error')}")
        return out["parsed"]

    def moderate(self, text: str) -> bool:
        """True when OpenAI moderation flags the text. The moderation endpoint is free."""
        from openai import OpenAI

        res = OpenAI(api_key=openai_api_key()).moderations.create(model="omni-moderation-latest", input=text)
        return bool(res.results[0].flagged)


@lru_cache
def get_gateway():
    if get_settings().llm_provider == "openai":
        return OpenAIGateway()
    from insightly.llm.offline import OfflineGateway

    return OfflineGateway()
