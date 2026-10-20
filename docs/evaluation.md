# Evaluation

Insightly is evaluation-driven: prompts, models, retrieval settings, semantic-layer edits and
fine-tuned models are all accepted or rejected by the same measured gate. This document
defines the datasets, every metric, how the gate works and how to do error analysis.

## 1. Principles

1. **Measure results, not SQL text.** Many different SQL strings are correct. The primary metric
   executes both the generated and the reference query and compares result sets.
2. **Measure every node, not just the final answer.** A wrong answer can come from routing,
   retrieval, SQL generation, repair or the answer text. Each has its own metric so a failure
   can be located.
3. **Safety and cost are quality.** A correct answer that leaks PII or costs $1 fails.
4. **Always compare to a baseline.** The offline provider (no LLM, reuse of the nearest verified
   query) is the floor. The current production model's last accepted run is the bar.
5. **Test data never trains the model.** The fine-tuning dataset builder rejects golden questions
   and near-duplicates (Jaccard ≥ 0.8).

## 2. Datasets

| File | Size | Content |
|---|---|---|
| `evals/golden/golden_v1.yaml` | 35 | 30 analytics questions with analyst-verified Trino SQL, plus 5 routing cases (ambiguous, out of scope, small talk) |
| `evals/redteam/redteam_v1.yaml` | 10 | prompt injection, PII extraction, destructive SQL |

Each golden case carries `difficulty` (easy / medium / hard), `tags` (revenue, join,
time-series, chart, funnel, ...), `expected_tables`, `expected_metric` and `wants_chart`, so
reports can be sliced (`insightly eval run --tag join`).

Growing the set is part of the job: every analyst correction from `/v1/feedback` is a candidate
golden case. Target 300 cases for a company rollout, stratified roughly 40% easy, 40% medium,
20% hard.

## 3. Metric catalogue

All metrics are computed in `src/insightly/eval/` and written to `summary.json`.

### Correctness

| Metric | Definition | Why it matters |
|---|---|---|
| `execution_accuracy` | share of SQL cases whose result set matches the reference: multiset of rows, order-insensitive, column-order-insensitive (permutation search), numeric tolerance 0.5% relative / 0.011 absolute, timestamps normalised. Extra columns in the prediction are allowed. | the headline: is the number right? |
| `valid_sql_rate` | first attempt passes the SQL firewall and executes | prompt and schema quality; drives cost (repairs cost tokens) |
| `final_sql_success_rate` | question ends with status ok after repairs | user-visible reliability |
| `metric_fidelity` | `expected_metric` appears in the model's declared `metric_ids` | business definitions are respected |
| `component_match` | Spider-style agreement on tables, aggregate functions, GROUP BY arity and WHERE presence (diagnostic) | explains why a result differs |

### Retrieval and schema linking

| Metric | Definition |
|---|---|
| `table_recall_at_k` | share of required tables present in the top-k retrieved documents (k = `INSIGHTLY_RETRIEVAL_K`, default 8) |
| `mrr` | reciprocal rank of the first relevant document (the certified metric when one is expected, else a required table) |
| `context_precision` | share of retrieved table/metric documents actually used by the generated SQL (keeps prompts small and cheap) |
| `schema_precision / recall / f1` | tables used by the generated SQL vs. expected tables |

### Agent behaviour

| Metric | Definition |
|---|---|
| `intent_accuracy`, `intent_macro_f1` | router label vs. gold label (follow_up counts as analytics) |
| `clarification_precision` | of the questions where the agent asked to clarify, share that were truly ambiguous |
| `clarification_recall` | of the truly ambiguous questions, share where it asked |
| `repair_success_rate` | of cases whose first attempt failed, share that ended ok |
| `avg_sql_attempts`, `escalation_rate` | how often the loop runs and how often the strong model is needed (cost driver) |
| `chart_validity`, `chart_recall` | chart spec passes schema checks; a chart was produced when one was asked for |

### Answer quality

| Metric | Definition |
|---|---|
| `faithfulness` | programmatic: share of numbers in the answer that exist in the result rows (with rounding, %, thousands/millions tolerance). Years and small counting words are ignored. The graph itself replaces any answer scoring below 0.8 with a deterministic summary, so this metric also tracks how often that guard fires. |
| `empty_result_mismatch_rate` | the agent returned no rows when the reference has rows, or the opposite |
| `judge_score` | optional (`--judge`): `gpt-5.4-mini` rates the answer 1–5 against the question and result |

### Safety

| Metric | Definition |
|---|---|
| `safety_block_rate` | red-team prompts ending as refused / out of scope / failed |
| `pii_leak_rate` | red-team outputs containing an email or SQL touching PII columns |

### Performance and cost

| Metric | Definition |
|---|---|
| `latency_p50_ms`, `latency_p95_ms` | wall-clock per case |
| `cost_per_question_usd`, `total_cost_usd` | from the per-request cost ledger (tokens × `config/pricing.yaml` + Athena bytes) |
| `avg_input_tokens`, `avg_output_tokens` | |
| `prompt_cache_hit_ratio` | cached input tokens / input tokens (OpenAI prompt caching) |
| `error_rate` | cases that raised an exception |

## 4. Running

```bash
uv run insightly eval run                       # all cases, current provider and engine
uv run insightly eval run --tag join --limit 10 # a slice
uv run insightly eval run --judge               # add LLM-as-judge (costs a little)
INSIGHTLY_QUERY_ENGINE=athena uv run insightly eval run   # against AWS
```

Output: `reports/eval/<UTC timestamp>-<provider>/` and a `latest` symlink.

| File | Use |
|---|---|
| `report.md` | human report: metric tables, failed cases, intent confusion, red-team table |
| `summary.json` | metrics + run metadata (models, engine), consumed by the gate |
| `cases.jsonl` | one line per case: SQL, attempts, trace, cost, every per-case metric |
| `redteam.jsonl` | one line per adversarial prompt |

## 5. The release gate

`evals/thresholds.yaml` holds minimums and maximums per provider and allowed regressions.

```bash
uv run insightly eval gate                                 # thresholds only
uv run insightly eval gate --baseline reports/eval/<run>   # thresholds + regression vs. baseline
```

Exit code 1 fails the CI job. Rules:

* `offline` thresholds run on every pull request at zero model cost. They catch broken graph
  wiring, SQL firewall regressions, retrieval breakage and safety regressions.
* `openai` thresholds run nightly and on PRs labelled `run-llm-eval`. A run on `main` that
  passes becomes the new baseline.
* Regression rules: execution accuracy may not drop more than 1 point, valid SQL rate more than
  2 points; cost per question and p95 latency may not grow more than 10%.

## 6. LangSmith

With `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` set, every graph run is traced (each node,
prompt, model, token count). `uv run insightly eval langsmith` uploads the golden set as dataset
`insightly-golden-v1` and runs it as an experiment with the evaluators `execution_accuracy`,
`intent_correct`, `metric_fidelity` and `cost_usd`, so two prompt or model versions can be
compared side by side in the LangSmith UI.

## 7. Online evaluation

| Signal | Source |
|---|---|
| thumbs up / down, corrected SQL | `POST /v1/feedback` (Streamlit buttons) → `data/feedback.jsonl` |
| status mix, latency, cost, attempts | CloudWatch EMF metrics and the Insightly dashboard |
| traces of bad answers | LangSmith project, filter by `status` metadata |

Weekly loop: sample 20 thumbs-down traces → label the failure stage (routing, retrieval, SQL,
answer) → fix the stage (prompt, semantic layer, example) → add the question to the golden
set → re-run the gate.

## 8. Error analysis recipe

1. Open `report.md` → *Failed SQL cases*.
2. For each failure read its line in `cases.jsonl`: `trace`, `attempts`, `sql`, `table_recall`,
   `metric_ok`, `component`.
3. Classify:
   * `table_recall < 1` → retrieval problem: add synonyms or a verified example to the semantic layer.
   * `metric_ok == false` → metric definition not followed: improve the metric description.
   * component mismatch on WHERE → time interpretation: tighten prompt rule 6.
   * many attempts → dialect errors: add the failing function to prompt rule 4.
4. Re-run with `--tag` for the affected slice, then the full gate.

## 9. Interpreting the offline baseline

On synthetic data the offline baseline scores about 0.03 execution accuracy with 1.0 valid
SQL, 1.0 table recall and 1.0 safety. The baseline always produces runnable SQL (it reuses
verified queries) and finds the right tables, but it cannot adapt filters, groupings and time
ranges to the new question. The gap between this floor and the LLM run is the value the model
adds, and the number to quote.
