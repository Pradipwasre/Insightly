from insightly.eval import metrics as M


def test_result_match_order_and_column_insensitive():
    gold = [["Women", 10.0], ["Men", 5.0]]
    pred = [[5.0, "Men"], [10.004, "Women"]]
    assert M.result_sets_match(pred, gold)


def test_result_mismatch_values():
    assert not M.result_sets_match([["Women", 11.0]], [["Women", 10.0]])


def test_result_extra_columns_allowed():
    assert M.result_sets_match([["Women", 10.0, 3]], [["Women", 10.0]])


def test_timestamps_normalised():
    assert M.result_sets_match([["2023-01-01T00:00:00", 1]], [["2023-01-01 00:00:00", 1]])


def test_empty_sets():
    assert M.result_sets_match([], [])
    assert not M.result_sets_match([[1]], [])


def test_prf_and_macro_f1():
    p, r, f = M.prf({"a", "b"}, {"a"})
    assert (p, r) == (0.5, 1.0) and round(f, 3) == 0.667
    assert M.macro_f1([("x", "x"), ("y", "y")]) == 1.0


def test_percentile():
    assert M.percentile([1, 2, 3, 4, 5], 0.5) == 3
    assert M.percentile([], 0.9) == 0.0


def test_component_match():
    a = "SELECT o.status, COUNT(*) FROM orders o GROUP BY 1"
    assert M.component_match(a, a) == 1.0
