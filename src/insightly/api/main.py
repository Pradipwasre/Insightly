"""Insightly HTTP API.

POST /v1/ask          answer a question (or resume a clarification)
POST /v1/ask/stream   same, streamed as Server-Sent Events (node progress, then the result)
POST /v1/feedback     thumbs up/down + optional corrected SQL (feeds evals and fine-tuning)
GET  /v1/cost/today   the caller's spend today
GET  /healthz         liveness for the ALB
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from insightly import __version__
from insightly.agent.graph import get_graph
from insightly.agent.service import ask
from insightly.api.auth import User, current_user
from insightly.api.schemas import AskRequest, AskResponse, FeedbackRequest
from insightly.config import get_settings
from insightly.cost.tracker import daily_spend
from insightly.observability.logging import configure_logging, log
from insightly.semantic.retriever import get_retriever


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    # Warm up the semantic index and the graph. A failure here (e.g. the OpenAI key is not
    # set yet, or Aurora is resuming from pause) must not crash the task: /healthz stays up
    # and the first request retries the warm-up.
    try:
        indexed = await asyncio.to_thread(lambda: get_retriever().ensure_index())
        await asyncio.to_thread(get_graph)
        log.info("startup", version=__version__, indexed_docs=indexed, env=get_settings().env)
    except Exception as e:
        log.error("warmup_failed", error=str(e)[:300])
    yield


app = FastAPI(title="Insightly API", version=__version__, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=get_settings().cors_origins, allow_methods=["*"], allow_headers=["*"]
)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "version": __version__}


@app.post("/v1/ask", response_model=AskResponse)
async def ask_endpoint(req: AskRequest, user: User = Depends(current_user)) -> dict:
    if not req.question and req.resume is None:
        raise HTTPException(400, "Provide a question, or thread_id + resume")
    return await asyncio.to_thread(
        ask, req.question, thread_id=req.thread_id, user_id=user.id, role=user.role, resume=req.resume
    )


@app.post("/v1/ask/stream")
async def ask_stream(req: AskRequest, user: User = Depends(current_user)):
    """Streams ``progress`` events per graph node, then one ``result`` event."""
    import uuid

    from langgraph.types import Command

    from insightly.agent.state import RunContext
    from insightly.cost.tracker import CostLedger

    s = get_settings()
    thread_id = req.thread_id or str(uuid.uuid4())
    ledger = CostLedger(budget_usd=min(s.request_budget_usd, daily_spend.remaining(user.id)))
    ctx = RunContext(user_id=user.id, role=user.role, ledger=ledger)
    config = {"configurable": {"thread_id": thread_id}}
    payload = Command(resume=req.resume) if req.resume is not None else {"question": req.question}
    graph = get_graph()

    async def events():
        final: dict = {}
        async for chunk in graph.astream(payload, config=config, context=ctx, stream_mode="updates"):
            for node_name, update in chunk.items():
                if node_name == "__interrupt__":
                    final["clarification"] = update[0].value
                    final["status"] = "clarify"
                    continue
                final.update(update or {})
                yield {"event": "progress", "data": json.dumps({"node": node_name})}
        daily_spend.add(user.id, ledger.total_usd)
        keys = AskResponse.model_fields.keys()
        result = {k: final.get(k) for k in keys if k in final}
        result.update(thread_id=thread_id, cost=ledger.summary())
        yield {"event": "result", "data": json.dumps(result, default=str)}

    return EventSourceResponse(events())


@app.post("/v1/feedback")
def feedback(req: FeedbackRequest, user: User = Depends(current_user)) -> dict:
    s = get_settings()
    record = {**req.model_dump(), "user_id": user.id, "ts": datetime.now(UTC).isoformat()}
    s.feedback_path.parent.mkdir(parents=True, exist_ok=True)
    with s.feedback_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    log.info("feedback", rating=req.rating, has_correction=bool(req.corrected_sql))
    return {"stored": True}


@app.get("/v1/cost/today")
def cost_today(user: User = Depends(current_user)) -> dict:
    s = get_settings()
    remaining = daily_spend.remaining(user.id)
    return {
        "user": user.id,
        "daily_budget_usd": s.daily_budget_usd,
        "spent_usd": round(s.daily_budget_usd - remaining, 6),
        "remaining_usd": round(remaining, 6),
    }
