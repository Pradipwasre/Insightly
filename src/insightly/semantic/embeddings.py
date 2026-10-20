"""Embeddings with a content-hash cache.

Re-indexing an unchanged semantic layer costs $0: only new or edited documents are sent to
the OpenAI embeddings API. The offline embedder (feature hashing) needs no network and keeps
CI deterministic.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np

from insightly.config import get_settings

_TOKEN = re.compile(r"[a-z0-9_]+")


class HashingEmbedder:
    """Deterministic bag-of-words feature hashing. Good enough for CI and the offline mode."""

    model = "offline-hashing"

    def __init__(self, dims: int = 512) -> None:
        self.dims = dims

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = np.zeros(self.dims, dtype=np.float32)
            toks = _TOKEN.findall(t.lower())
            grams = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:], strict=False)]
            for g in grams:
                h = int(hashlib.md5(g.encode()).hexdigest(), 16)
                v[h % self.dims] += 1.0 if (h >> 64) & 1 else -1.0
            n = np.linalg.norm(v)
            out.append((v / n if n else v).tolist())
        return out


class OpenAIEmbedder:
    def __init__(self) -> None:
        from langchain_openai import OpenAIEmbeddings

        from insightly.llm.gateway import openai_api_key

        s = get_settings()
        self.model = s.embedding_model
        self.dims = s.embedding_dims
        self._client = OpenAIEmbeddings(
            model=s.embedding_model,
            dimensions=s.embedding_dims,
            api_key=openai_api_key(),
            max_retries=s.openai_max_retries,
        )
        self.tokens_used = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.tokens_used += sum(len(t) // 4 for t in texts)  # estimate for the cost ledger
        return self._client.embed_documents(texts)


class CachedEmbedder:
    def __init__(self, inner, cache_path: Path | None = None) -> None:
        self.inner = inner
        self.model = inner.model
        self.path = cache_path or get_settings().embedding_cache
        self._cache: dict[str, list[float]] = {}
        if self.path.exists():
            self._cache = json.loads(self.path.read_text(encoding="utf-8"))
        self.misses = 0

    def _key(self, text: str) -> str:
        return f"{self.model}:{hashlib.sha256(text.encode()).hexdigest()}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        missing = [t for t in texts if self._key(t) not in self._cache]
        if missing:
            self.misses += len(missing)
            for t, v in zip(missing, self.inner.embed(missing), strict=True):
                self._cache[self._key(t)] = v
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._cache), encoding="utf-8")
        return [self._cache[self._key(t)] for t in texts]

    def embed_query(self, text: str) -> list[float]:
        # Queries are not cached on disk (high cardinality); call the model directly.
        return self.inner.embed([text])[0]


def get_embedder() -> CachedEmbedder:
    s = get_settings()
    inner = OpenAIEmbedder() if s.llm_provider == "openai" else HashingEmbedder()
    return CachedEmbedder(inner)
