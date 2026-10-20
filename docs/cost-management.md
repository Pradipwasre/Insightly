# Cost management

Two cost pools: **variable** (OpenAI tokens, Athena scans, per question) and **fixed**
(AWS infrastructure that runs whether or not anyone asks). Both are measured, capped and alarmed.

## 1. Variable cost per question

```
cost(question) =  Σ_llm_calls [ (input − cached) × p_in + cached × p_cached + output × p_out ] / 1e6
                + query_embedding_tokens × p_embed / 1e6
                + max(bytes_scanned, 10 MB) / 1 TB × $5        (Athena)
```

Prices live in `config/pricing.yaml` (USD per 1M tokens, from OpenAI model pages on 2026-10-20;
re-check before quoting):

| Model | Role | Input | Cached input | Output |
|---|---|---|---|---|
| gpt-5.4-nano | router, answer | 0.20 | 0.02 | 1.25 |
| gpt-5.4-mini | SQL (first attempt), judge | 0.75 | 0.075 | 4.50 |
| gpt-5.4 | SQL escalation only | 2.50 | 0.25 | 15.00 |
| text-embedding-3-small | retrieval | 0.02 | | |

A typical successful question makes three calls (route, SQL, answer). Measure your real
numbers instead of estimating:

```bash
uv run insightly eval run
uv run insightly cost report --questions-per-day 500
```

`cost report` uses the measured tokens of the last evaluation run and prints average tokens,
cached tokens, cost by outcome and a monthly projection.

## 2. Levers implemented in the code

| Lever | Where | Effect |
|---|---|---|
| **Model cascade** | `llm/gateway.py`, `agent/nodes.py::generate_sql` | mini writes SQL; `gpt-5.4` is used only after a failed attempt (`INSIGHTLY_ESCALATE_AFTER_ATTEMPTS`) |
| **Tiny models for easy work** | router and answer tiers | nano costs about a quarter of mini |
| **Prompt caching** | `agent/prompts.py` puts the static rules + full schema first | repeated prefix billed at the cached rate (90% less) |
| **Answer cache** | `agent/service.py` `TTLCache` | the same question from the same role within 15 min costs $0 |
| **Embedding cache** | `semantic/embeddings.py` | re-indexing an unchanged semantic layer costs $0; only edited docs are embedded |
| **Deterministic chart builder** | `agent/chart.py` | charts cost 0 tokens (the prototype paid an LLM to write Plotly code) |
| **Bounded repair loop** | `INSIGHTLY_MAX_SQL_ATTEMPTS=3` | no runaway loops |
| **Per-request hard budget** | `cost/tracker.py::CostLedger.check` before every LLM call and query | stops with a clear message at `INSIGHTLY_REQUEST_BUDGET_USD` |
| **Per-user daily budget** | `DailySpend` | `INSIGHTLY_DAILY_BUDGET_USD` per user per UTC day |
| **Reasoning effort** | `INSIGHTLY_REASONING_EFFORT=low` | fewer hidden reasoning tokens on GPT-5.x |
| **Offline CI** | `.github/workflows/ci.yml` | every PR runs the full pipeline with $0 model spend |
| **Batch-friendly evals** | nightly, not per commit | real-model evaluation cost is bounded and predictable |
| **Fine-tuned small model** | `finetune/` | distil the SQL tier into a cheaper model once it passes the gate |

## 3. Athena levers

* Workgroup **bytes-scanned cutoff 1 GB per query**: a bad query is cancelled, not billed for TBs.
* **Iceberg + Parquet + ZSTD** with partitioning (`events` by month, `order_items` by year).
* SQL firewall rejects `SELECT *` on `events` and adds `LIMIT`.
* Query results expire after 7 days (S3 lifecycle).

## 4. Fixed infrastructure cost

Approximate on-demand prices (verify in the AWS Pricing Calculator for your region; ap-south-1
is close to us-east-1 for these services):

| Component | Configuration | Approx. per month (always on) | Lever used |
|---|---|---|---|
| NAT gateway | 1, plus data processing | $33–40 + $0.045/GB | one NAT, S3 gateway endpoint |
| Application Load Balancer | 1 | $17–20 | |
| ECS Fargate | 1 task, 1 vCPU / 2 GB, ARM64 | $28–30 | Graviton, scale 1→3 on CPU |
| Aurora Serverless v2 | 0–2 ACU, auto-pause 15 min | storage + I/O when idle; about $0.12 per ACU-hour when active | min capacity 0 |
| Secrets Manager | 2 secrets | $0.80 | |
| CloudWatch | logs 14 days, EMF metrics, 1 dashboard, 3 alarms | $3–8 | short retention, no custom PutMetricData |
| S3 + Glue | small data | < $1 | lifecycle rules |

About $85–100 per month if left running 24/7 at low traffic, or about $3 per day. For demos and
teaching, deploy, demo, then `cdk destroy --all`.

## 5. Guardrails and alarms

| Level | Mechanism |
|---|---|
| Question | `CostLedger` hard stop |
| User | daily budget, returns `budget_exceeded` |
| Service | CloudWatch alarm: > $2 model spend in one hour (EMF `CostUSD`) |
| OpenAI project | usage limit and email alerts in the OpenAI dashboard |
| AWS account | AWS Budgets 80% actual / 100% forecast on tag `project=insightly` |

## 6. FinOps practices

* Every AWS resource is tagged `project=insightly`, `cost-center=analytics-ai`. Activate the tags
  in Billing to see the project alone in Cost Explorer.
* Model prices are configuration, not code. Update `config/pricing.yaml` when prices change; the
  ledger, the evaluation and the dashboard all follow.
* A model change is a cost change: the gate fails if cost per question rises more than 10%
  against the baseline.
