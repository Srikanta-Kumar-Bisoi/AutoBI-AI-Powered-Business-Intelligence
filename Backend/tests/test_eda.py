import numpy as np
import pandas as pd
import pytest

from app.eda import (
    MAX_AUTOMATIC_CHARTS,
    MAX_CHART_POINTS,
    MAX_HISTOGRAM_BINS,
    build_dashboard_visualizations,
    build_eda_report,
    build_selected_chart,
)
from app.main import compute_eda_report
from app.eda import UnsuitableChartError, UnknownColumnError


def test_report_contains_stats_in_order_and_type_appropriate_charts():
    frame = pd.DataFrame(
        {
            "Amount": pd.Series([1, 2, None, 4], dtype="Int64"),
            "Label": pd.Series(["a", "b", "a", None], dtype="string"),
            "Flag": [True, False, True, None],
            "When": pd.to_datetime(
                ["2025-01-02", "2025-01-01", "2025-01-03", None]
            ),
        }
    )

    report = build_eda_report(frame)

    assert report["statistics"][0] == {
        "name": "Amount",
        "dtype": "Int64",
        "count": 3,
        "non_missing_values": 3,
        "finite_count": 3,
        "missing_values": 1,
        "non_finite_values": 0,
        "chart_supported": True,
        "mean": pytest.approx(7 / 3),
        "median": 2.0,
        "min": 1.0,
        "max": 4.0,
        "standard_deviation": pytest.approx(np.std([1, 2, 4], ddof=1)),
    }
    assert [chart["id"] for chart in report["charts"]] == [
        "histogram:Amount",
        "box:Amount",
        "bar:Label",
        "bar:Flag",
        "line:When:Amount",
    ]
    assert all(
        {
            "id",
            "type",
            "title",
            "explanation",
            "column",
            "columns",
            "x",
            "y",
            "labels",
            "values",
            "z",
            "customdata",
            "x_label",
            "y_label",
        }.issubset(set(chart))
        for chart in report["charts"]
    )


def test_correlation_heatmap_uses_pairwise_finite_numeric_values():
    frame = pd.DataFrame(
        {
            "x": [1.0, 2.0, 3.0, np.inf, 4.0],
            "y": [2.0, 4.0, 6.0, 8.0, np.nan],
            "constant": [5.0, 5.0, 5.0, 5.0, 5.0],
        }
    )

    report = compute_eda_report(frame)
    chart = next(
        item for item in report["charts"] if item["id"] == "correlation:pearson"
    )

    assert chart["labels"] == ["x", "y", "constant"]
    assert chart["z"][0][1] == pytest.approx(1.0)
    assert chart["z"][1][0] == pytest.approx(1.0)
    assert chart["z"][2][2] is None
    assert chart["z"][0][0] == pytest.approx(1.0)
    assert report["statistics"][0]["finite_count"] == 4
    assert report["statistics"][0]["count"] == 4
    assert report["statistics"][0]["non_finite_values"] == 1
    assert report["statistics"][0]["max"] == 4.0


def test_duplicate_numeric_headers_do_not_break_correlation_report():
    frame = pd.DataFrame(
        [[1, 2, 3, 6], [2, 4, 6, 12], [3, 6, 9, 18]],
        columns=["value", "value", "other", "third"],
    )

    report = build_eda_report(frame)
    heatmap = next(
        chart for chart in report["charts"] if chart["type"] == "heatmap"
    )

    assert heatmap["columns"] == ["other", "third"]
    assert heatmap["z"] == [[1.0, 1.0], [1.0, 1.0]]


def test_text_bar_is_skipped_above_cardinality_limit_but_category_is_included():
    many_values = [f"label-{number}" for number in range(25)]
    frame = pd.DataFrame(
        {
            "text": many_values,
            "category": pd.Series(many_values, dtype="category"),
        }
    )

    charts = build_eda_report(frame)["charts"]

    assert [chart["id"] for chart in charts] == ["bar:category"]
    assert len(charts[0]["labels"]) == 11
    assert charts[0]["values"][-1] == 15


def test_automatic_chart_limits_are_deterministic_and_bounded():
    frame = pd.DataFrame(
        {
            "value": np.arange(MAX_CHART_POINTS + 2, dtype=np.float64),
            "when": pd.date_range("2020-01-01", periods=MAX_CHART_POINTS + 2),
        }
    )

    first_report = build_eda_report(frame)
    second_report = build_eda_report(frame)
    histogram = next(
        chart for chart in first_report["charts"] if chart["type"] == "histogram"
    )
    line = next(
        chart for chart in first_report["charts"] if chart["type"] == "line"
    )

    assert len(histogram["x"]) <= MAX_HISTOGRAM_BINS
    assert sum(histogram["y"]) == MAX_CHART_POINTS + 2
    assert len(line["x"]) == MAX_CHART_POINTS
    assert line["x"][0] == "2020-01-01T00:00:00+00:00"
    assert line["x"][-1] == frame["when"].iloc[-1].tz_localize("UTC").isoformat()
    assert line["y"][0] == 0
    assert line["y"][-1] == MAX_CHART_POINTS + 1
    assert first_report == second_report

    many_columns = pd.DataFrame(
        np.vstack(
            [
                np.arange(MAX_AUTOMATIC_CHARTS + 5),
                np.arange(MAX_AUTOMATIC_CHARTS + 5) + 1,
            ]
        ),
        columns=[f"number_{index}" for index in range(MAX_AUTOMATIC_CHARTS + 5)],
    )
    assert len(build_eda_report(many_columns)["charts"]) == MAX_AUTOMATIC_CHARTS


def test_selected_scatter_uses_valid_pairs_and_caps_data():
    frame = pd.DataFrame(
        {"x": [1, 2, 3, np.inf, 4], "y": [10, 20, 30, 40, np.nan]}
    )

    chart = build_selected_chart(frame, "scatter", "y", "x")

    assert chart["data"][0]["x"] == [1.0, 2.0, 3.0]
    assert chart["data"][0]["y"] == [10.0, 20.0, 30.0]
    assert chart["data"][0]["mode"] == "markers"


def test_dashboard_recommends_category_line_and_pie_only_when_suitable():
    frame = pd.DataFrame(
        {
            "when": ["2025-01-03", "2025-01-01", "2025-01-02", "2025-01-02"],
            "revenue": [30, 10, 20, 40],
            "group": ["north", "south", "north", None],
        }
    )

    result = build_dashboard_visualizations(frame)
    assert [chart["type"] for chart in result["charts"]] == [
        "bar",
        "line",
        "pie",
    ]
    assert result["charts"][0]["values"] == [2, 1]
    assert result["charts"][2]["values"] == [2, 1]
    trend = result["charts"][1]
    assert trend["x"] == [
        "2025-01-01T00:00:00+00:00",
        "2025-01-02T00:00:00+00:00",
        "2025-01-03T00:00:00+00:00",
    ]
    assert trend["y"] == [10, 30, 30]
    assert trend["customdata"] == [1, 2, 1]


def test_invalid_dates_constant_values_and_empty_data_are_explained():
    frame = pd.DataFrame(
        {
            "date": ["2025-01-01", "not-a-date", "2025-01-03"],
            "constant": [7, 7, 7],
            "group": ["one", "one", "one"],
        }
    )

    eda = build_eda_report(frame)
    dashboard = build_dashboard_visualizations(frame)
    assert eda["charts"] == []
    assert any("invalid" in message for message in eda["messages"])
    assert any("two distinct" in message for message in eda["messages"])
    assert any("invalid" in message for message in dashboard["messages"])
    assert build_eda_report(pd.DataFrame())["charts"] == []


def test_histogram_and_box_summaries_match_pandas_values():
    values = pd.Series([1.0, 2.0, 3.0, 100.0, np.nan])
    report = build_eda_report(pd.DataFrame({"amount": values}))
    histogram = next(chart for chart in report["charts"] if chart["type"] == "histogram")
    box = next(chart for chart in report["charts"] if chart["type"] == "box")

    assert sum(histogram["y"]) == int(values.notna().sum())
    assert histogram["sample_count"] == int(values.notna().sum())
    assert box["box"]["q1"] == pytest.approx(values.quantile(0.25))
    assert box["box"]["median"] == pytest.approx(values.median())
    assert box["box"]["q3"] == pytest.approx(values.quantile(0.75))
    assert box["box"]["outlier_count"] == 1


def test_correlation_requires_three_pairwise_complete_rows_and_excludes_constants():
    report = build_eda_report(
        pd.DataFrame(
            {
                "a": [1, 2, 3, 4],
                "b": [2, 4, 6, np.nan],
                "constant": [2, 2, 2, 2],
            }
        )
    )
    correlation = next(chart for chart in report["charts"] if chart["type"] == "heatmap")
    assert correlation["z"][0][1] == pytest.approx(
        pd.DataFrame({"a": [1, 2, 3], "b": [2, 4, 6]}).corr().iloc[0, 1]
    )
    assert correlation["z"][2][2] is None

    too_few = build_eda_report(
        pd.DataFrame({"a": [1, 2, np.nan], "b": [2, 4, 6]})
    )
    assert not any(chart["type"] == "heatmap" for chart in too_few["charts"])


def test_automatic_scatter_uses_full_pair_count_and_reports_correlation():
    frame = pd.DataFrame(
        {
            "x": [1, 2, 3, np.nan, 5],
            "y": [2, 4, 6, 8, np.inf],
            "unused": [5, 5, 5, 5, 5],
        }
    )
    report = build_eda_report(frame)
    scatter = next(chart for chart in report["charts"] if chart["type"] == "scatter")
    expected = frame[["x", "y"]].replace([np.inf, -np.inf], np.nan).dropna().corr().iloc[0, 1]

    assert scatter["pair_count"] == 3
    assert scatter["pearson_r"] == pytest.approx(expected)
    assert len(scatter["x"]) == 3
    assert "not evidence of causation" in scatter["explanation"]


def test_mixed_categories_keep_type_distinct_values_and_ignore_unused_levels():
    mixed = pd.Series([1, "1", True, 1, "1", False], dtype=object)
    report = build_eda_report(pd.DataFrame({"mixed": mixed}))
    chart = next(item for item in report["charts"] if item["type"] == "bar")
    assert chart["labels"] == ["1 (int)", "1 (str)", "True", "False"]
    assert chart["values"] == [2, 2, 1, 1]

    categories = pd.Series(
        pd.Categorical(
            ["north", "south", "north"],
            categories=["north", "south", "unused"],
        )
    )
    categorical_chart = next(
        item
        for item in build_eda_report(pd.DataFrame({"group": categories}))["charts"]
        if item["type"] == "bar"
    )
    assert categorical_chart["labels"] == ["north", "south"]
    assert categorical_chart["values"] == [2, 1]


def test_large_integer_stats_preserve_exact_extrema_and_skip_inexact_charts():
    values = pd.Series([2**53 + 1, 2**53 + 3], dtype="int64")
    report = compute_eda_report(pd.DataFrame({"identifier": values}))
    statistics = report["statistics"][0]

    assert statistics["min"] == str(2**53 + 1)
    assert statistics["max"] == str(2**53 + 3)
    assert statistics["chart_supported"] is False
    assert report["charts"] == []
    assert any("cannot be represented exactly" in message for message in report["messages"])


def test_selected_line_sorts_timestamps_and_preserves_pairs():
    frame = pd.DataFrame(
        {
            "when": pd.to_datetime(
                [
                    "2025-01-03",
                    "2025-01-01",
                    "2025-01-02",
                ]
            ),
            "value": [30, 10, 20],
        }
    )

    chart = build_selected_chart(frame, "line", "value", "when")

    assert chart["data"][0]["x"] == [
        "2025-01-01T00:00:00+00:00",
        "2025-01-02T00:00:00+00:00",
        "2025-01-03T00:00:00+00:00",
    ]
    assert chart["data"][0]["y"] == [10.0, 20.0, 30.0]


def test_selected_charts_reject_unknown_or_unsuitable_columns():
    frame = pd.DataFrame(
        {
            "category": ["a", "b"],
            "text_date": ["2025-01-01", "2025-01-02"],
            "value": [1, 2],
        }
    )

    with pytest.raises(UnknownColumnError):
        build_selected_chart(frame, "histogram", "not-a-column")
    with pytest.raises(UnsuitableChartError, match="numeric"):
        build_selected_chart(frame, "histogram", "category")
    line = build_selected_chart(frame, "line", "value", "text_date")
    assert line["data"][0]["y"] == [1.0, 2.0]

    frame["text_date"] = ["2025-01-01", "not-a-date"]
    with pytest.raises(UnsuitableChartError, match="date/time"):
        build_selected_chart(frame, "line", "value", "text_date")


def test_boolean_is_not_counted_as_numeric_and_all_infinite_is_safe():
    frame = pd.DataFrame(
        {
            "flag": [True, False, True],
            "infinite": [np.inf, -np.inf, np.nan],
        }
    )

    report = compute_eda_report(frame)

    assert [item["name"] for item in report["statistics"]] == ["infinite"]
    assert report["statistics"][0]["finite_count"] == 0
    assert report["statistics"][0]["mean"] is None
    assert len(report["charts"]) == 1
    assert report["charts"][0]["id"] == "bar:flag"
    assert report["charts"][0]["values"] == [2, 1]
    assert report["charts"][0]["y_label"] == "Number of records"
