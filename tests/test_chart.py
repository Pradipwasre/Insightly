from insightly.agent.chart import build_chart, validate_chart


def test_time_series_is_line():
    fig = build_chart(
        ["month", "revenue"], [["2023-01-01T00:00:00", 10.0], ["2023-02-01T00:00:00", 12.0]], "rev"
    )
    assert fig["data"][0]["type"] == "scatter" and validate_chart(fig)


def test_categories_are_bars_and_long_format_series():
    fig = build_chart(
        ["year", "department", "rev"], [[2022, "Men", 1.0], [2022, "Women", 2.0], [2023, "Men", 3.0]], "t"
    )
    assert len(fig["data"]) == 2 and validate_chart(fig)


def test_no_chart_for_scalar():
    assert build_chart(["n"], [[5]], "t") is None
