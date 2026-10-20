"""Load the semantic layer (tables, metrics, verified examples) into retrievable documents."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from insightly.config import get_settings


@dataclass
class Doc:
    id: str
    kind: str  # table | metric | example
    title: str
    text: str
    tables: list[str]
    payload: dict = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SemanticLayer:
    tables: dict[str, dict]
    joins: list[list[str]]
    metrics: dict[str, dict]
    examples: list[dict]
    version: str

    @property
    def allowed_tables(self) -> set[str]:
        return set(self.tables)

    def docs(self) -> list[Doc]:
        docs: list[Doc] = []
        for name, t in self.tables.items():
            cols = "\n".join(
                f"  - {c} ({m.get('type', '')}): {m.get('description', '')}"
                + (f" -> {m['references']}" if m.get("references") else "")
                for c, m in t["columns"].items()
            )
            joins = [j for j in self.joins if any(x.startswith(f"{name}.") for x in j)]
            join_txt = "\n".join(f"  - {a} = {b}" for a, b in joins)
            text = (
                f"TABLE {name}: {t['description']} Grain: {t.get('grain', '')}\n"
                f"Columns:\n{cols}\nJoins:\n{join_txt}"
            )
            docs.append(Doc(f"table:{name}", "table", name, text, [name], {"name": name}))
        for mid, m in self.metrics.items():
            text = (
                f"METRIC {m['name']} (id: {mid}). Synonyms: {', '.join(m.get('synonyms', []))}. "
                f"{m['description']}\nSQL expression: {m['sql']}\nFrom: {m.get('alias_hint', '')}"
                + (f"\nRequired filter: {m['filters']}" if m.get("filters") else "")
            )
            docs.append(Doc(f"metric:{mid}", "metric", m["name"], text, m["tables"], {"id": mid}))
        for i, ex in enumerate(self.examples):
            sql = ex["sql"].strip()
            text = f"EXAMPLE question: {ex['question']}\nSQL:\n{sql}"
            tables = sorted({t for t in self.tables if f" {t} " in f" {sql} " or f"{t} AS" in sql})
            docs.append(
                Doc(
                    f"example:{i}",
                    "example",
                    ex["question"],
                    text,
                    tables,
                    {"question": ex["question"], "sql": sql},
                )
            )
        return docs


@lru_cache
def load_semantic_layer(path: Path | None = None) -> SemanticLayer:
    path = Path(path or get_settings().semantic_dir)
    t = yaml.safe_load((path / "tables.yaml").read_text(encoding="utf-8"))
    m = yaml.safe_load((path / "metrics.yaml").read_text(encoding="utf-8"))
    e = yaml.safe_load((path / "examples.yaml").read_text(encoding="utf-8"))
    digest = hashlib.sha256(json.dumps([t, m, e], sort_keys=True, default=str).encode()).hexdigest()[:12]
    return SemanticLayer(
        tables={x["name"]: x for x in t["tables"]},
        joins=t.get("joins", []),
        metrics={x["id"]: x for x in m["metrics"]},
        examples=e["examples"],
        version=digest,
    )
