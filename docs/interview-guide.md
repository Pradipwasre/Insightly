# Interview guide

## 60-second pitch
"Insightly is a governed text-to-SQL analytics service for an e-commerce company. Business users
ask questions in English; a LangGraph agent on AWS routes the question, retrieves certified metric
definitions from a pgvector semantic layer, writes Trino SQL with OpenAI models, passes it through
a sqlglot firewall, runs it on Athena over Iceberg tables with the service's least-privilege role,
and returns a grounded answer, the SQL and a chart. I evaluate it with execution accuracy, retrieval
recall, faithfulness, safety and cost metrics behind a CI release gate, and I control spend with a
per-request cost ledger, a model cascade and caching. A feedback loop builds leak-checked datasets
for OpenAI fine-tuning."

## Resume bullets (fill numbers from your own `reports/eval/latest/report.md`)
- Architected and deployed Insightly, an end-to-end GenAI analytics platform on AWS (ECS Fargate,
  Athena/Iceberg, Glue, Aurora pgvector, Cognito, CDK) that answers business questions with governed
  SQL, results and charts, served as a streaming FastAPI service.
- Designed a LangGraph agent with intent routing, hybrid retrieval over a certified semantic layer,
  sqlglot SQL firewall, bounded self-repair with model escalation and human-in-the-loop
  clarification, exposed also as MCP tools; execution accuracy [X]% vs. [Y]% retrieval-only baseline.
- Built a 30+ metric evaluation framework (execution accuracy, schema recall@k, faithfulness,
  red-team block rate, p95 latency, cost per question) with LangSmith experiments and a CI gate that
  blocks regressions.
- Implemented cost controls (per-request budget ledger, nano/mini/full model cascade, prompt, answer
  and embedding caching, Athena scan caps, AWS Budgets) keeping cost per question at [$Z], plus an
  SFT/RFT fine-tuning pipeline fed by analyst corrections.

## Questions you should be ready for
| Question | Short answer (details in docs) |
|---|---|
| How do you know the SQL is correct? | execution accuracy on a golden set: run both queries, compare result sets with tolerance; string match is wrong because equivalent SQL differs |
| How do you stop destructive or PII queries? | input guard → sqlglot firewall → PII table absent from layer → IAM deny → output scan |
| Why a graph instead of an agent? | predictable cost and latency, per-node metrics, bounded loop |
| Why not put the whole schema in the prompt? | it is in the cached static prefix for 7 tables; retrieval is what scales to 700 and adds certified metrics |
| How do you control cost? | ledger + budgets, cascade, caching, deterministic charts, Athena caps; gate fails if cost rises 10% |
| When would you fine-tune? | when evals plateau after semantic-layer and prompt work, or to distil into a cheaper model; promote only through the gate |
| What breaks first at scale? | OpenAI rate limits (raise tier, cache), Athena concurrency (workgroup limits), semantic-layer ownership |
| What would you change for production in a bank? | HTTPS + WAF, private ALB, Lake Formation row filters, zero-retention agreement, interface endpoints |
