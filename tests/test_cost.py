import pytest

from insightly.cost.pricing import load_pricebook
from insightly.cost.tracker import BudgetExceeded, CostLedger, TTLCache


def test_llm_cost_with_cache():
    pb = load_pricebook()
    # 1M input of which 500k cached, 100k output on gpt-5.4-mini
    cost = pb.llm_cost("gpt-5.4-mini", 1_000_000, 100_000, 500_000)
    assert cost == pytest.approx(0.5 * 0.75 + 0.5 * 0.075 + 0.1 * 4.50)


def test_snapshot_and_finetune_fallback_to_base_price():
    pb = load_pricebook()
    assert pb.for_model("gpt-5.4-mini-2026-03-17") == pb.models["gpt-5.4-mini"]
    assert pb.for_model("ft:gpt-5.4-nano:org:insightly:abc") == pb.models["gpt-5.4-nano"]


def test_athena_minimum_charge():
    pb = load_pricebook()
    assert pb.athena_cost(1) == pytest.approx(10 * 1024**2 / 1024**4 * 5.0)
    assert pb.athena_cost(0) == 0.0


def test_budget_stop():
    led = CostLedger(budget_usd=0.001)
    led.add_llm("x", "gpt-5.4", {"input_tokens": 1000, "output_tokens": 1000})
    with pytest.raises(BudgetExceeded):
        led.check("next")


def test_ttl_cache():
    c = TTLCache(ttl_s=60, max_items=1)
    c.set("a", {"v": 1})
    c.set("b", {"v": 2})
    assert c.get("a") is None and c.get("b") == {"v": 2}
