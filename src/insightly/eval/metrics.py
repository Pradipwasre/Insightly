"""Evaluation metrics. Pure functions, unit-tested, no I/O."""

from __future__ import annotations

import itertools
import math
from collections import Counter
from typing import Any

import sqlglot
from sqlglot import exp


def _norm(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        f = float(v)
        if math.isnan(f):
            return None
        return round(f, 2)
    s = str(v).strip()
    # timestamps from different engines: '2023-01-01T00:00:00' vs '2023-01-01 00:00:00'
    return s.replace("T", " ")[:19] if len(s) >= 10 and s[4] == "-" and s[7] == "-" else s


def _rows_equal(a: list[Any], b: list[Any], rel_tol: float) -> bool:
    for x, y in zip(a, b, strict=True):
        if isinstance(x, float) and isinstance(y, float):
            if not math.isclose(x, y, rel_tol=rel_tol, abs_tol=0.011):
                return False
        elif x != y:
            return False
    return True


def result_sets_match(
    pred_rows: list[list[Any]], gold_rows: list[list[Any]], rel_tol: float = 0.005, max_perm_cols: int = 6
) -> bool:
    """Execution accuracy for one case.

    Order-insensitive multiset comparison, numeric tolerance, and column-order insensitive
    (tries column permutations, so ``SELECT a, b`` matches ``SELECT b, a``). Extra columns in
    the prediction are allowed if a subset of them matches the gold columns.
    """
    if not gold_rows:
        return not pred_rows
    if len(pred_rows) != len(gold_rows):
        return False
    g = sorted(([_norm(v) for v in r] for r in gold_rows), key=repr)
    n_gold, n_pred = len(g[0]), len(pred_rows[0])
    if n_pred < n_gold:
        return False
    p_norm = [[_norm(v) for v in r] for r in pred_rows]
    if n_pred > max_perm_cols:
        candidates = [tuple(range(n_gold))]
    else:
        candidates = itertools.permutations(range(n_pred), n_gold)
    for perm in candidates:
        p = sorted(([r[i] for i in perm] for r in p_norm), key=repr)
        if all(_rows_equal(a, b, rel_tol) for a, b in zip(p, g, strict=True)):
            return True
    return False


def sql_tables(sql: str | None) -> set[str]:
    if not sql:
        return set()
    try:
        tree = sqlglot.parse_one(sql, read="trino")
    except sqlglot.errors.ParseError:
        return set()
    ctes = {c.alias_or_name for c in tree.find_all(exp.CTE)}
    return {t.name.lower() for t in tree.find_all(exp.Table) if t.name not in ctes}


def structural_signature(sql: str | None) -> dict[str, Any]:
    """Spider-style component view used for diagnosis (not for pass/fail)."""
    if not sql:
        return {}
    try:
        tree = sqlglot.parse_one(sql, read="trino")
    except sqlglot.errors.ParseError:
        return {}
    group = tree.args.get("group")
    return {
        "tables": sorted(sql_tables(sql)),
        "aggregates": sorted({type(a).__name__ for a in tree.find_all(exp.AggFunc)}),
        "group_by": len(group.expressions) if group else 0,
        "has_where": tree.args.get("where") is not None,
        "has_order": tree.args.get("order") is not None,
        "has_limit": tree.args.get("limit") is not None,
    }


def component_match(pred_sql: str | None, gold_sql: str | None) -> float:
    a, b = structural_signature(pred_sql), structural_signature(gold_sql)
    if not a or not b:
        return 0.0
    keys = ["tables", "aggregates", "group_by", "has_where"]
    return sum(a[k] == b[k] for k in keys) / len(keys)


def prf(pred: set[str], gold: set[str]) -> tuple[float, float, float]:
    if not pred and not gold:
        return 1.0, 1.0, 1.0
    tp = len(pred & gold)
    p = tp / len(pred) if pred else 0.0
    r = tp / len(gold) if gold else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def recall_at_k(retrieved_tables: list[list[str]], gold: set[str]) -> float:
    if not gold:
        return 1.0
    seen = set().union(*retrieved_tables) if retrieved_tables else set()
    return len(gold & seen) / len(gold)


def reciprocal_rank(hit_ids: list[str], relevant: set[str]) -> float:
    for i, h in enumerate(hit_ids, 1):
        if h in relevant:
            return 1.0 / i
    return 0.0


def macro_f1(pairs: list[tuple[str, str]]) -> float:
    labels = sorted({g for g, _ in pairs} | {p for _, p in pairs})
    f1s = []
    for lab in labels:
        tp = sum(1 for g, p in pairs if g == lab and p == lab)
        fp = sum(1 for g, p in pairs if g != lab and p == lab)
        fn = sum(1 for g, p in pairs if g == lab and p != lab)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1s.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
    return sum(f1s) / len(f1s) if f1s else 0.0


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    v = sorted(values)
    k = (len(v) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return v[lo] if lo == hi else v[lo] + (v[hi] - v[lo]) * (k - lo)


def confusion(pairs: list[tuple[str, str]]) -> dict[str, dict[str, int]]:
    out: dict[str, Counter] = {}
    for g, p in pairs:
        out.setdefault(g, Counter())[p] += 1
    return {g: dict(c) for g, c in out.items()}
