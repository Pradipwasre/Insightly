"""Token and query pricing, loaded from ``config/pricing.yaml``."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from insightly.config import get_settings


@dataclass(frozen=True)
class Price:
    input: float
    cached_input: float
    output: float


@dataclass(frozen=True)
class PriceBook:
    models: dict[str, Price]
    default: Price
    athena_usd_per_tb: float

    def for_model(self, model: str) -> Price:
        if model in self.models:
            return self.models[model]
        # Dated snapshots ("gpt-5.4-mini-2026-03-17") and fine-tunes ("ft:gpt-5.4-mini:...")
        # fall back to their base model's price.
        base = model.removeprefix("ft:").split(":")[0]
        for name in sorted(self.models, key=len, reverse=True):
            if base.startswith(name):
                return self.models[name]
        return self.default

    def llm_cost(self, model: str, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float:
        p = self.for_model(model)
        uncached = max(input_tokens - cached_tokens, 0)
        return (uncached * p.input + cached_tokens * p.cached_input + output_tokens * p.output) / 1_000_000

    def athena_cost(self, bytes_scanned: int) -> float:
        if bytes_scanned <= 0:
            return 0.0
        # Athena bills a 10 MB minimum per query.
        billable = max(bytes_scanned, 10 * 1024 * 1024)
        return billable / 1024**4 * self.athena_usd_per_tb


@lru_cache
def load_pricebook(path: Path | None = None) -> PriceBook:
    path = path or get_settings().pricing_file
    raw = yaml.safe_load(Path(path).read_text())
    models = {name: Price(**vals) for name, vals in raw["models"].items()}
    return PriceBook(
        models=models,
        default=Price(**raw["default"]),
        athena_usd_per_tb=float(raw.get("athena_usd_per_tb_scanned", 5.0)),
    )
