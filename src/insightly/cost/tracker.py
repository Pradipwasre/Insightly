"""Per-request cost ledger and budget enforcement.

Every LLM call, embedding call and Athena query records a line item. The graph checks the
running total before each expensive step, so a runaway repair loop cannot burn credits.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from insightly.config import get_settings
from insightly.cost.pricing import load_pricebook


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class LineItem:
    kind: str  # "llm" | "embedding" | "athena"
    node: str
    model: str
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    bytes_scanned: int = 0
    usd: float = 0.0


@dataclass
class CostLedger:
    budget_usd: float
    items: list[LineItem] = field(default_factory=list)

    @property
    def total_usd(self) -> float:
        return round(sum(i.usd for i in self.items), 8)

    def add_llm(self, node: str, model: str, usage: dict | None) -> LineItem:
        usage = usage or {}
        details = usage.get("input_token_details") or {}
        item = LineItem(
            kind="llm",
            node=node,
            model=model,
            input_tokens=int(usage.get("input_tokens", 0)),
            cached_tokens=int(details.get("cache_read", 0) or 0),
            output_tokens=int(usage.get("output_tokens", 0)),
        )
        item.usd = load_pricebook().llm_cost(model, item.input_tokens, item.output_tokens, item.cached_tokens)
        self.items.append(item)
        return item

    def add_athena(self, node: str, bytes_scanned: int) -> LineItem:
        item = LineItem(
            kind="athena",
            node=node,
            model="athena",
            bytes_scanned=bytes_scanned,
            usd=load_pricebook().athena_cost(bytes_scanned),
        )
        self.items.append(item)
        return item

    def check(self, upcoming_node: str) -> None:
        if self.total_usd >= self.budget_usd:
            raise BudgetExceeded(
                f"Request budget ${self.budget_usd:.3f} reached before '{upcoming_node}' "
                f"(spent ${self.total_usd:.4f})."
            )

    def summary(self) -> dict:
        by_model: dict[str, float] = defaultdict(float)
        for i in self.items:
            by_model[i.model] += i.usd
        return {
            "total_usd": self.total_usd,
            "input_tokens": sum(i.input_tokens for i in self.items),
            "cached_tokens": sum(i.cached_tokens for i in self.items),
            "output_tokens": sum(i.output_tokens for i in self.items),
            "bytes_scanned": sum(i.bytes_scanned for i in self.items),
            "by_model": {k: round(v, 6) for k, v in by_model.items()},
            "items": [asdict(i) for i in self.items],
        }


class DailySpend:
    """In-process per-user daily spend. On ECS each task keeps its own counter; the AWS
    Budgets alarm in the infra stack is the account-level backstop."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._spend: dict[tuple[str, str], float] = defaultdict(float)

    @staticmethod
    def _day() -> str:
        return datetime.now(UTC).strftime("%Y-%m-%d")

    def remaining(self, user: str) -> float:
        with self._lock:
            return get_settings().daily_budget_usd - self._spend[(user, self._day())]

    def add(self, user: str, usd: float) -> None:
        with self._lock:
            self._spend[(user, self._day())] += usd


class TTLCache:
    """Small answer cache: the same question from the same role within the TTL costs $0."""

    def __init__(self, ttl_s: int, max_items: int = 512) -> None:
        self.ttl_s, self.max_items = ttl_s, max_items
        self._data: dict[str, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> dict | None:
        with self._lock:
            hit = self._data.get(key)
            if not hit or time.time() - hit[0] > self.ttl_s:
                self._data.pop(key, None)
                return None
            return hit[1]

    def set(self, key: str, value: dict) -> None:
        with self._lock:
            if len(self._data) >= self.max_items:
                oldest = min(self._data, key=lambda k: self._data[k][0])
                self._data.pop(oldest, None)
            self._data[key] = (time.time(), value)


daily_spend = DailySpend()
