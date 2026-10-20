# Teaching plan: build Insightly in 10 × 1 hour + one 3-hour Sunday

Each session ends with something running and one concept to explain to students.

| Session | Build and run | Concept to teach |
|---|---|---|
| Day 1 (1 h) | README §4: VS Code, uv, Python 3.12 venv, `pytest` green; `data synthetic` + `data curate` | reproducible environments, lockfiles; why curate data before AI touches it (PII split, category merge) |
| Day 2 (1 h) | read `semantic_layer/*.yaml`, run `insightly index`, query the retriever in a REPL | semantic layer vs. prompt rules; embeddings; hybrid search and RRF |
| Day 3 (1 h) | `agent/graph.py` + `nodes.py`; run offline `insightly ask` and read the `trace` | LangGraph state, nodes, conditional edges, why a graph beats a ReAct loop here |
| Day 4 (1 h) | `sql_guard.py`, `guards.py`, tests; run with OpenAI; show the repair loop on a hard question | defence in depth; structured outputs; self-repair; model cascade |
| Day 5 (1 h) | `insightly serve`, `/docs`, SSE stream, Streamlit UI, clarify flow | FastAPI, streaming, human-in-the-loop with `interrupt()` |
| Day 6 (1 h) | `insightly eval run` offline then OpenAI; read `report.md`; `eval gate` | execution accuracy vs. string match; per-node metrics; baselines; release gates |
| **Sunday (3 h)** | AWS guide steps 0–11: SSO, budget, CDK bootstrap, data stack, publish to Athena, network, Aurora, secret, service, Cognito, smoke test, dashboard | IaC; least privilege; serverless analytics; cost-aware architecture |
| Day 7 (1 h) | red-team set, PII controls across 3 layers, faithfulness guard | AI security: injection, exfiltration, hallucination controls |
| Day 8 (1 h) | `finetune build` + `submit --dry-run` (real job optional) | data flywheel, SFT vs. RFT, leakage, promotion through the gate |
| Day 9 (1 h) | `cost report`, CloudWatch dashboard, alarms, runbook | FinOps for LLM apps; observability with EMF; SLOs |
| Day 10 (1 h) | rehearse the demo and the interview pitch; `cdk destroy --all` | telling the architecture story; trade-offs (ADRs) |

Tip for class: run the offline provider first in every session. Students see the full system
working with no API key, then switch to OpenAI and compare the evaluation numbers.
