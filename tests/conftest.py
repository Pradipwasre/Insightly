"""Test environment: offline provider, synthetic data in a temp dir, no network, no keys."""

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="insightly-test-"))
os.environ.update(
    INSIGHTLY_LLM_PROVIDER="offline",
    INSIGHTLY_QUERY_ENGINE="duckdb",
    INSIGHTLY_VECTOR_STORE="memory",
    INSIGHTLY_CHECKPOINTER="memory",
    INSIGHTLY_AUTH_MODE="disabled",
    INSIGHTLY_CURATED_DIR=str(_TMP / "curated"),
    INSIGHTLY_EMBEDDING_CACHE=str(_TMP / "emb.json"),
    INSIGHTLY_FEEDBACK_PATH=str(_TMP / "feedback.jsonl"),
)

from insightly.data.curate import curate  # noqa: E402
from insightly.data.synthetic import generate  # noqa: E402

generate(_TMP / "raw", n_users=800, seed=3)
curate(_TMP / "raw", _TMP / "curated")
