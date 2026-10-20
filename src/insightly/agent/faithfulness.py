"""Programmatic faithfulness: every number in the answer must come from the result set."""

from __future__ import annotations

import contextlib
import re
from typing import Any

NUM = re.compile(r"(?<![\w.])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])-?\d+(?:\.\d+)?")


def numbers_in_text(text: str) -> list[float]:
    out = []
    for m in NUM.findall(text):
        with contextlib.suppress(ValueError):
            out.append(float(m.replace(",", "")))
    return out


def _candidates(rows: list[list[Any]]) -> list[float]:
    vals: list[float] = [float(len(rows))]
    for r in rows:
        for v in r:
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                vals.append(float(v))
            elif isinstance(v, str):
                vals.extend(numbers_in_text(v))
    return vals


def _matches(x: float, vals: list[float]) -> bool:
    for v in vals:
        if v == x:
            return True
        tol = max(abs(v) * 0.005, 0.051 if abs(x) < 100 else 0.51)
        if abs(v - x) <= tol:
            return True
        # 0.123 rendered as 12.3%
        if abs(v * 100 - x) <= max(abs(v * 100) * 0.005, 0.051):
            return True
        # 12_345_678 rendered as 12.3 (million) / 12.3 (thousand)
        for scale in (1e3, 1e6, 1e9):
            if abs(v / scale - x) <= max(abs(v / scale) * 0.01, 0.051) and abs(v) >= scale:
                return True
    return False


def faithfulness(answer: str, rows: list[list[Any]]) -> tuple[float, list[float]]:
    """Return (score, ungrounded numbers). Years and small counting words are ignored."""
    nums = [
        n for n in numbers_in_text(answer) if not (n.is_integer() and (1900 <= n <= 2100 or 0 <= n <= 10))
    ]
    if not nums:
        return 1.0, []
    vals = _candidates(rows)
    bad = [n for n in nums if not _matches(n, vals)]
    return 1 - len(bad) / len(nums), bad
