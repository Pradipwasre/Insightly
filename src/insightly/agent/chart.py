"""Deterministic Plotly figure specs.

Charts are JSON (Plotly figure dicts) rendered by the client. No generated code is executed
anywhere, which removes the ``exec()`` risk of the original prototype and costs no tokens.
"""

from __future__ import annotations

import re
from typing import Any

ISO_DATE = re.compile(r"^\d{4}-\d{2}(-\d{2})?([T ]\d{2}:\d{2}(:\d{2})?)?")
PALETTE = ["#0b6e79", "#d9822b", "#5b8def", "#9c6ade", "#3a9d5d"]


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def build_chart(columns: list[str], rows: list[list[Any]], title: str) -> dict | None:
    if not rows or len(columns) < 2:
        return None
    sample = rows[0]
    num_idx = [i for i, v in enumerate(sample) if _is_num(v)]
    cat_idx = [i for i, v in enumerate(sample) if not _is_num(v)]
    if not num_idx:
        return None
    if not cat_idx:  # e.g. year as integer + value
        if len(columns) >= 2 and len(num_idx) >= 2:
            cat_idx, num_idx = [num_idx[0]], num_idx[1:]
        else:
            return None
    x_i = cat_idx[0]
    xs = [r[x_i] for r in rows]
    temporal = all(isinstance(x, str) and ISO_DATE.match(x) for x in xs) or (
        all(_is_num(x) for x in xs) and all(1900 <= x <= 2100 for x in xs)
    )
    traces = []
    if len(cat_idx) >= 2 and len(num_idx) == 1:  # long format: x, series, value
        s_i, y_i = cat_idx[1], num_idx[0]
        for k, series in enumerate(dict.fromkeys(r[s_i] for r in rows)):
            sub = [r for r in rows if r[s_i] == series]
            traces.append(
                {
                    "type": "scatter" if temporal else "bar",
                    "name": str(series),
                    "x": [r[x_i] for r in sub],
                    "y": [r[y_i] for r in sub],
                    "marker": {"color": PALETTE[k % len(PALETTE)]},
                    **({"mode": "lines+markers"} if temporal else {}),
                }
            )
    else:
        for k, y_i in enumerate(num_idx[:3]):
            traces.append(
                {
                    "type": "scatter" if temporal else "bar",
                    "name": columns[y_i],
                    "x": xs,
                    "y": [r[y_i] for r in rows],
                    "marker": {"color": PALETTE[k % len(PALETTE)]},
                    **({"mode": "lines+markers"} if temporal else {}),
                }
            )
    horizontal = not temporal and len(rows) > 8 and len(traces) == 1
    if horizontal:
        t = traces[0]
        t["x"], t["y"], t["orientation"] = t["y"], t["x"], "h"
    return {
        "data": traces,
        "layout": {
            "title": {"text": title[:90]},
            "xaxis": {"title": {"text": columns[num_idx[0]] if horizontal else columns[x_i]}},
            "yaxis": {
                "title": {"text": columns[x_i] if horizontal else columns[num_idx[0]]},
                **({"autorange": "reversed"} if horizontal else {}),
            },
            "barmode": "group",
            "margin": {"l": 60, "r": 20, "t": 50, "b": 50},
        },
    }


def validate_chart(fig: dict | None) -> bool:
    if fig is None:
        return True
    try:
        data = fig["data"]
        return bool(data) and all(
            t.get("type") in {"bar", "scatter"} and len(t["x"]) == len(t["y"]) > 0 for t in data
        )
    except (KeyError, TypeError):
        return False
