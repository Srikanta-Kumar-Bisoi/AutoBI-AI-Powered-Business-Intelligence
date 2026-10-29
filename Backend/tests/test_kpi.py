import numpy as np
import pandas as pd
import pytest

from app.kpi import build_kpi_dashboard


def sales_frame():
    return pd.DataFrame(
        {
            "order_id": [1, 1, 2, 3, 3, 4],
            "sales": [100.0, 50.0, 80.0, 40.0, 40.0, 200.0],
            "profit": [10.0, 5.0, 8.0, 4.0, 4.0, 20.0],
            "category": ["north", "north", "south", "south", "south", "north"],
            "customer": ["a", "b", "a", "c", "c", "b"],
            "date": [
                "2025-01-01",
                "2025-01-01",
                "2025-01-02",
                "2025-01-03",
                "2025-01-03",
                "2025-01-04",
            ],
        }
    )


def card_map(report):
    return {card["key"]: card for card in report["cards"]}


def test_sales_kpis_and_charts_match_pandas_aggregations():
    frame = sales_frame()

    report = build_kpi_dashboard(frame, dataset_label="sales.csv (original)")
    cards = card_map(report)

    assert cards["record_count"]["value"] == len(frame)
    assert cards["total_sales"]["value"] == pytest.approx(frame["sales"].sum())
    assert cards["total_profit"]["value"] == pytest.approx(frame["profit"].sum())
    assert cards["average_order_value"]["value"] == pytest.approx(
        frame["sales"].sum() / frame["order_id"].nunique()
    )
    assert cards["unique_customers"]["value"] == frame["customer"].nunique()

    by_category = next(
        chart for chart in report["charts"]
        if chart["key"] == "category_comparison"
    )
    expected = frame.groupby("category")["sales"].sum().sort_values(ascending=False)
    assert by_category["labels"] == expected.index.tolist()
    assert by_category["values"] == expected.tolist()

    trend = next(chart for chart in report["charts"] if chart["key"] == "date_trend")
    expected_trend = frame.groupby("date")["sales"].sum().sort_index()
    assert trend["y"] == expected_trend.tolist()


def test_general_dataset_uses_generic_numeric_and_category_kpis_not_sales():
    frame = pd.DataFrame(
        {"temperature": [10.0, 20.0, np.nan, 30.0], "region": ["n", "s", "n", "s"]}
    )

    report = build_kpi_dashboard(frame, dataset_label="weather.csv (original)")
    cards = card_map(report)

    assert "total_sales" not in cards
    assert cards["record_count"]["value"] == 4
    assert cards["average:temperature"]["value"] == pytest.approx(20.0)
    assert cards["minimum:temperature"]["value"] == 10
    assert cards["maximum:temperature"]["value"] == 30
    assert report["charts"][0]["y_label"] == "temperature"
    assert report["charts"][0]["values"] == [25.0, 10.0]


def test_semantic_kpis_support_snake_case_and_exclude_rows_without_order_ids():
    frame = pd.DataFrame(
        {
            "order_id": [1, None, 2],
            "total_sales": [10.0, 100.0, 20.0],
            "gross_profit": [2.0, 50.0, 4.0],
            "customer_id": ["a", "b", "c"],
            "product_id": ["x", "y", "x"],
            "sales_margin": [0.1, 0.2, 0.3],
            "profit_margin": [0.1, 0.2, 0.3],
        }
    )
    cards = card_map(
        build_kpi_dashboard(frame, dataset_label="snake-case.csv (original)")
    )

    assert cards["total_sales"]["value"] == 130
    assert cards["total_profit"]["value"] == 56
    assert cards["average_order_value"]["value"] == 15
    assert cards["unique_customers"]["value"] == 3
    assert cards["unique_products"]["value"] == 2


def test_date_and_category_filters_update_all_kpis_and_charts():
    frame = sales_frame()

    report = build_kpi_dashboard(
        frame,
        dataset_label="sales.csv (original)",
        date_column="date",
        date_from="2025-01-02",
        date_to="2025-01-03",
        category_column="category",
        category_value="south",
    )
    cards = card_map(report)

    assert report["row_count"] == 3
    assert cards["record_count"]["value"] == 3
    assert cards["total_sales"]["value"] == 160
    assert cards["total_profit"]["value"] == 16
    assert cards["average_order_value"]["value"] == 80
    category = next(chart for chart in report["charts"] if chart["type"] == "bar")
    assert category["labels"] == ["south"]
    assert category["values"] == [160.0]
    trend = next(chart for chart in report["charts"] if chart["type"] == "line")
    assert trend["y"] == [80.0, 80.0]


def test_missing_and_duplicate_rows_are_counted_without_silent_deduplication():
    frame = pd.DataFrame(
        {
            "sales": [10.0, 10.0, np.nan],
            "category": ["a", "a", "b"],
        }
    )
    report = build_kpi_dashboard(frame, dataset_label="dirty.csv (original)")

    cards = card_map(report)
    assert cards["record_count"]["value"] == 3
    assert cards["total_sales"]["value"] == 20
    assert report["charts"][0]["values"] == [20.0, 0.0] or report["charts"][0]["labels"] == ["a"]
    assert "duplicate" not in cards["record_count"]["definition"].lower()


def test_dataset_without_numeric_columns_and_empty_dataset_are_explained():
    categorical = build_kpi_dashboard(
        pd.DataFrame({"region": ["north", "south", "north"]}),
        dataset_label="regions.csv (original)",
    )
    assert [card["key"] for card in categorical["cards"]] == ["record_count"]
    assert any("No suitable numeric columns" in message for message in categorical["messages"])
    assert categorical["charts"][0]["values"] == [2, 1]

    empty = build_kpi_dashboard(
        pd.DataFrame(), dataset_label="empty.csv (original)"
    )
    assert empty["row_count"] == 0
    assert empty["cards"][0]["value"] == 0
    assert empty["charts"] == []
    assert empty["messages"]


@pytest.mark.parametrize(
    ("filters", "message"),
    [
        ({"date_column": "amount"}, "not a valid date column"),
        ({"category_column": "amount"}, "not a supported category column"),
        (
            {"category_column": "category", "category_value": "west"},
            "not an available value",
        ),
        (
            {"date_column": "date", "date_from": "2025-01-04", "date_to": "2025-01-02"},
            "on or before",
        ),
    ],
)
def test_invalid_filter_columns_and_ranges_are_rejected(filters, message):
    frame = sales_frame()
    with pytest.raises(ValueError, match=message):
        build_kpi_dashboard(frame, dataset_label="sales.csv (original)", **filters)
