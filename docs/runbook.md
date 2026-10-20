# Runbook

## Alarms

| Alarm | First checks | Typical fix |
|---|---|---|
| `LatencyP95` | dashboard: which node is slow (LangSmith trace timings, `timings_ms` in responses) | OpenAI latency → lower reasoning effort; Athena → check bytes scanned; Aurora resume → raise min ACU |
| `FailedAnswers` | `/insightly/api` logs, filter `status=failed` | dialect error pattern → prompt rule; schema change → update `semantic_layer/tables.yaml` |
| `CostSpike` | dashboard cost + `escalation_rate`; logs `cost_usd` by user | abusive user → lower daily budget; loop → check `max_sql_attempts`; model price change → `config/pricing.yaml` |
| ALB 5xx | ECS service events, task logs | roll back (below) |

## Common operations

Rotate the OpenAI key:
```bash
aws secretsmanager put-secret-value --secret-id insightly/openai-api-key --secret-string "$NEW_KEY"
aws ecs update-service --cluster <cluster> --service <service> --force-new-deployment
```

Roll back a deployment: ECS rolls back automatically on failed health checks. For a bad model
or prompt that is healthy but wrong, revert the commit and run the **deploy** workflow, or set
the previous model id in `service_stack.py` and `cdk deploy InsightlyService`.

Change a model: edit `INSIGHTLY_MODEL_*` (env / `service_stack.py`) → `insightly eval run` →
`insightly eval gate --baseline <prod run>` → deploy.

Add a certified metric: edit `semantic_layer/metrics.yaml` → add 1–2 verified examples → add a
golden case → `pytest` + `eval run` → merge. The service re-indexes automatically on startup when
the layer version changes (only changed documents are embedded).

Find a user's bad answer: LangSmith project → filter metadata `user_id`, or CloudWatch Logs
Insights:
```
fields @timestamp, status, intent, attempts, cost_usd, latency_ms
| filter event = "ask" and status != "ok" | sort @timestamp desc | limit 50
```
