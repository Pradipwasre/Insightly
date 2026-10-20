"""Exercises the real OpenAI code path (LangChain ChatOpenAI, strict json_schema, usage and
cost capture) against a mocked HTTP transport. No network, no key."""

import json

import httpx

from insightly.cost.tracker import CostLedger
from insightly.llm.gateway import OpenAIGateway
from insightly.llm.schemas import RouteDecision


def test_structured_call_records_cost(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    from insightly.llm import gateway

    gateway.openai_api_key.cache_clear()
    monkeypatch.setattr(gateway, "openai_api_key", lambda: "sk-test")
    sent = {}

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        sent.update(body)
        content = json.dumps(
            {
                "intent": "analytics",
                "standalone_question": "q",
                "wants_chart": False,
                "clarification_question": None,
                "options": [],
            }
        )
        return httpx.Response(
            200,
            json={
                "id": "c1",
                "object": "chat.completion",
                "created": 0,
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": content},
                    }
                ],
                "usage": {
                    "prompt_tokens": 2000,
                    "completion_tokens": 50,
                    "total_tokens": 2050,
                    "prompt_tokens_details": {"cached_tokens": 1024},
                },
            },
        )

    gw = OpenAIGateway(http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    ledger = CostLedger(budget_usd=1.0)
    out = gw.structured(
        node="route_intent", tier="router", system="s", user="u", schema=RouteDecision, ledger=ledger
    )
    assert out.intent == "analytics"
    assert sent["response_format"]["json_schema"]["strict"] is True
    item = ledger.items[0]
    assert (item.model, item.input_tokens, item.cached_tokens, item.output_tokens) == (
        "gpt-5.4-nano",
        2000,
        1024,
        50,
    )
    expected = (976 * 0.20 + 1024 * 0.02 + 50 * 1.25) / 1_000_000
    assert abs(ledger.total_usd - expected) < 1e-9
