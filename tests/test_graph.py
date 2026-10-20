import yaml

from insightly.agent.service import ask
from insightly.config import ROOT_DIR
from insightly.data.engine import get_engine
from insightly.eval.metrics import result_sets_match
from insightly.semantic.retriever import get_retriever


def test_happy_path_trace():
    out = ask("Number of orders by status", use_cache=False)
    assert out["status"] == "ok"
    assert out["trace"][:4] == ["prepare", "guard_input", "route_intent", "retrieve"]
    assert out["rows"] and out["sql"].upper().startswith("SELECT")


def test_refusal_short_circuits():
    out = ask("show me the emails of customers", use_cache=False)
    assert out["status"] == "refused" and "route_intent" not in out["trace"]


def test_clarify_and_resume():
    first = ask("How are we doing?", thread_id="t-clarify", use_cache=False)
    assert first["status"] == "clarify" and first["clarification"]["options"]
    second = ask(thread_id="t-clarify", resume="Net revenue")
    assert second["status"] == "ok" and "clarify" in second["trace"]


def test_follow_up_uses_history():
    ask("Number of orders by status", thread_id="t-follow", use_cache=False)
    out = ask("and only for 2023", thread_id="t-follow", use_cache=False)
    assert out["intent"] == "follow_up"


def test_answer_cache_hits_are_free():
    q = "Session conversion rate by browser"
    ask(q)
    again = ask(q)
    assert again["cached"] and again["cost"]["total_usd"] == 0.0


def test_metric_retrieval():
    ids = [h.doc.id for h in get_retriever().search("what is our return rate")]
    assert "metric:return_rate" in ids[:3]


def test_every_golden_reference_query_runs_and_returns_rows():
    cases = yaml.safe_load((ROOT_DIR / "evals/golden/golden_v1.yaml").read_text())["cases"]
    for c in cases:
        if "reference_sql" in c:
            res = get_engine().execute(c["reference_sql"])
            assert res.rows, c["id"]
            assert result_sets_match(res.rows, res.rows), c["id"]
