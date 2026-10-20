"""Hybrid retrieval over the semantic layer: dense vectors + BM25, fused with RRF.

Two stores implement the same interface:
* ``MemoryStore``   numpy + in-process BM25 (local, CI)
* ``PgVectorStore`` Aurora PostgreSQL: pgvector cosine search + full-text ``ts_rank``
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import numpy as np

from insightly.config import get_settings
from insightly.semantic.embeddings import CachedEmbedder, get_embedder
from insightly.semantic.layer import Doc, load_semantic_layer

_TOK = re.compile(r"[a-z0-9_]+")
STOP = {
    "the",
    "a",
    "an",
    "of",
    "by",
    "in",
    "for",
    "and",
    "to",
    "what",
    "is",
    "show",
    "me",
    "how",
    "many",
    "which",
    "with",
    "per",
    "each",
    "was",
    "were",
    "are",
    "on",
    "from",
}


def tokenize(text: str) -> list[str]:
    return [t for t in _TOK.findall(text.lower()) if t not in STOP]


@dataclass
class Hit:
    doc: Doc
    score: float
    dense_rank: int | None = None
    sparse_rank: int | None = None


def rrf(rankings: list[list[str]], k: int = 60) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return scores


class VectorStore(Protocol):
    def upsert(self, docs: list[Doc], vectors: list[list[float]], version: str) -> None: ...
    def dense(self, qvec: list[float], k: int) -> list[str]: ...
    def sparse(self, query: str, k: int) -> list[str]: ...
    def get(self, ids: list[str]) -> list[Doc]: ...
    def version(self) -> str | None: ...


class MemoryStore:
    def __init__(self) -> None:
        self.docs: dict[str, Doc] = {}
        self.ids: list[str] = []
        self.matrix = np.zeros((0, 1), dtype=np.float32)
        self._version: str | None = None
        self._tf: list[Counter] = []
        self._df: Counter = Counter()
        self._avgdl = 1.0

    def upsert(self, docs: list[Doc], vectors: list[list[float]], version: str) -> None:
        self.docs = {d.id: d for d in docs}
        self.ids = [d.id for d in docs]
        self.matrix = np.asarray(vectors, dtype=np.float32)
        self._tf = [Counter(tokenize(d.text)) for d in docs]
        self._df = Counter(t for tf in self._tf for t in tf)
        self._avgdl = sum(sum(tf.values()) for tf in self._tf) / max(len(docs), 1)
        self._version = version

    def dense(self, qvec: list[float], k: int) -> list[str]:
        q = np.asarray(qvec, dtype=np.float32)
        sims = self.matrix @ q / (np.linalg.norm(self.matrix, axis=1) * np.linalg.norm(q) + 1e-9)
        return [self.ids[i] for i in np.argsort(-sims)[:k]]

    def sparse(self, query: str, k: int, k1: float = 1.5, b: float = 0.75) -> list[str]:
        q = tokenize(query)
        n = len(self.ids)
        scores = []
        for _i, tf in enumerate(self._tf):
            dl = sum(tf.values())
            s = 0.0
            for t in q:
                if t not in tf:
                    continue
                idf = math.log(1 + (n - self._df[t] + 0.5) / (self._df[t] + 0.5))
                s += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * dl / self._avgdl))
            scores.append(s)
        order = np.argsort(-np.asarray(scores))[:k]
        return [self.ids[i] for i in order if scores[i] > 0]

    def get(self, ids: list[str]) -> list[Doc]:
        return [self.docs[i] for i in ids if i in self.docs]

    def version(self) -> str | None:
        return self._version


class PgVectorStore:
    DDL = """
    CREATE EXTENSION IF NOT EXISTS vector;
    CREATE TABLE IF NOT EXISTS semantic_docs (
        id text PRIMARY KEY,
        kind text NOT NULL,
        title text NOT NULL,
        body text NOT NULL,
        tables text[] NOT NULL,
        payload jsonb NOT NULL,
        embedding vector({dims}) NOT NULL,
        tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', body)) STORED,
        layer_version text NOT NULL
    );
    CREATE INDEX IF NOT EXISTS semantic_docs_tsv ON semantic_docs USING gin (tsv);
    CREATE INDEX IF NOT EXISTS semantic_docs_hnsw ON semantic_docs
        USING hnsw (embedding vector_cosine_ops);
    """

    def __init__(self, dsn: str, dims: int) -> None:
        import psycopg
        from pgvector.psycopg import register_vector

        self.conn = psycopg.connect(dsn, autocommit=True)
        self.conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        register_vector(self.conn)
        self.conn.execute(self.DDL.format(dims=dims))

    def upsert(self, docs: list[Doc], vectors: list[list[float]], version: str) -> None:
        with self.conn.transaction():
            self.conn.execute("DELETE FROM semantic_docs")
            with self.conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO semantic_docs (id, kind, title, body, tables, payload, embedding,"
                    " layer_version) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    [
                        (
                            d.id,
                            d.kind,
                            d.title,
                            d.text,
                            d.tables,
                            json.dumps(d.payload),
                            np.asarray(v, dtype=np.float32),
                            version,
                        )
                        for d, v in zip(docs, vectors, strict=True)
                    ],
                )

    def dense(self, qvec: list[float], k: int) -> list[str]:
        rows = self.conn.execute(
            "SELECT id FROM semantic_docs ORDER BY embedding <=> %s LIMIT %s",
            (np.asarray(qvec, dtype=np.float32), k),
        ).fetchall()
        return [r[0] for r in rows]

    def sparse(self, query: str, k: int) -> list[str]:
        terms = " | ".join(tokenize(query)) or "x"
        rows = self.conn.execute(
            "SELECT id FROM semantic_docs WHERE tsv @@ to_tsquery('english', %s) "
            "ORDER BY ts_rank(tsv, to_tsquery('english', %s)) DESC LIMIT %s",
            (terms, terms, k),
        ).fetchall()
        return [r[0] for r in rows]

    def get(self, ids: list[str]) -> list[Doc]:
        rows = self.conn.execute(
            "SELECT id, kind, title, body, tables, payload FROM semantic_docs WHERE id = ANY(%s)",
            (ids,),
        ).fetchall()
        by_id = {r[0]: Doc(r[0], r[1], r[2], r[3], list(r[4]), r[5]) for r in rows}
        return [by_id[i] for i in ids if i in by_id]

    def version(self) -> str | None:
        row = self.conn.execute("SELECT max(layer_version) FROM semantic_docs").fetchone()
        return row[0] if row else None


class Retriever:
    def __init__(self, store: VectorStore, embedder: CachedEmbedder) -> None:
        self.store, self.embedder = store, embedder

    def ensure_index(self, force: bool = False) -> int:
        layer = load_semantic_layer()
        if not force and self.store.version() == layer.version:
            return 0
        docs = layer.docs()
        vectors = self.embedder.embed([d.text for d in docs])
        self.store.upsert(docs, vectors, layer.version)
        return len(docs)

    def search(self, query: str, k: int | None = None) -> list[Hit]:
        k = k or get_settings().retrieval_k
        dense = self.store.dense(self.embedder.embed_query(query), k * 2)
        sparse = self.store.sparse(query, k * 2)
        fused = rrf([dense, sparse])
        top = sorted(fused, key=fused.get, reverse=True)[:k]
        docs = self.store.get(top)
        return [
            Hit(
                d,
                fused[d.id],
                dense.index(d.id) if d.id in dense else None,
                sparse.index(d.id) if d.id in sparse else None,
            )
            for d in docs
        ]


@lru_cache
def get_retriever() -> Retriever:
    s = get_settings()
    embedder = get_embedder()
    if s.vector_store == "pgvector":
        from insightly.db import resolve_database_url

        dims = s.embedding_dims if s.llm_provider == "openai" else 512
        store: VectorStore = PgVectorStore(resolve_database_url(), dims)
    else:
        store = MemoryStore()
    r = Retriever(store, embedder)
    r.ensure_index()
    return r
