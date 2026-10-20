# syntax=docker/dockerfile:1.7
# Multi-stage, non-root, works on linux/amd64 and linux/arm64 (Graviton on Fargate).
FROM public.ecr.aws/docker/library/python:3.12-slim AS build
RUN pip install --no-cache-dir uv==0.11.32
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

FROM public.ecr.aws/docker/library/python:3.12-slim AS runtime
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY --from=build /app/src /app/src
COPY semantic_layer ./semantic_layer
COPY config ./config
COPY evals ./evals
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 \
    INSIGHTLY_LOG_JSON=true INSIGHTLY_SEMANTIC_DIR=/app/semantic_layer \
    INSIGHTLY_PRICING_FILE=/app/config/pricing.yaml INSIGHTLY_EMBEDDING_CACHE=/tmp/emb.json
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
CMD ["uvicorn", "insightly.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
