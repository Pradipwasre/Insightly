"""Run the golden set as a LangSmith experiment (datasets, per-example traces, comparisons).

Requires LANGSMITH_API_KEY. Tracing itself is enabled with LANGSMITH_TRACING=true and needs no
code: LangGraph and LangChain emit traces automatically.
"""

from __future__ import annotations

import yaml
from langsmith import Client, evaluate

from insightly.agent.service import ask
from insightly.data.engine import get_engine
from insightly.eval import metrics as M
from insightly.eval.runner import GOLDEN

DATASET = "insightly-golden-v1"


def sync_dataset(client: Client) -> str:
    cases = [c for c in yaml.safe_load(GOLDEN.read_text())["cases"]]
    if client.has_dataset(dataset_name=DATASET):
        return DATASET
    ds = client.create_dataset(DATASET, description="Insightly golden questions (analyst verified)")
    client.create_examples(
        dataset_id=ds.id,
        examples=[
            {
                "inputs": {"question": c["question"]},
                "outputs": {
                    "intent": c["intent"],
                    "reference_sql": c.get("reference_sql"),
                    "expected_metric": c.get("expected_metric"),
                },
                "metadata": {"id": c["id"], "difficulty": c.get("difficulty")},
            }
            for c in cases
        ],
    )
    return DATASET


def target(inputs: dict) -> dict:
    out = ask(inputs["question"], user_id="langsmith-eval", use_cache=False)
    return {k: out.get(k) for k in ("intent", "status", "sql", "rows", "answer", "metric_ids", "cost")}


def execution_accuracy(outputs: dict, reference_outputs: dict) -> dict:
    ref = reference_outputs.get("reference_sql")
    if not ref:
        return {"key": "execution_accuracy", "score": None}
    gold = get_engine().execute(ref).rows
    ok = outputs.get("status") == "ok" and M.result_sets_match(outputs.get("rows") or [], gold)
    return {"key": "execution_accuracy", "score": float(ok)}


def intent_correct(outputs: dict, reference_outputs: dict) -> dict:
    pred = "analytics" if outputs.get("intent") == "follow_up" else outputs.get("intent")
    return {"key": "intent_correct", "score": float(pred == reference_outputs["intent"])}


def metric_fidelity(outputs: dict, reference_outputs: dict) -> dict:
    m = reference_outputs.get("expected_metric")
    if not m:
        return {"key": "metric_fidelity", "score": None}
    return {"key": "metric_fidelity", "score": float(m in (outputs.get("metric_ids") or []))}


def cost_usd(outputs: dict) -> dict:
    return {"key": "cost_usd", "score": (outputs.get("cost") or {}).get("total_usd", 0.0)}


def run_experiment(prefix: str = "insightly") -> str:
    client = Client()
    name = sync_dataset(client)
    res = evaluate(
        target,
        data=name,
        evaluators=[execution_accuracy, intent_correct, metric_fidelity, cost_usd],
        experiment_prefix=prefix,
        max_concurrency=4,
        client=client,
    )
    return res.experiment_name
