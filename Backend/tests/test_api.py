from io import BytesIO

import pandas as pd
import pytest
import xlwt
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.main import MAX_ROWS, app

client = TestClient(app)

PROFILE_CSV = (
    b"Order Date,Amount,Category,Empty,No Mode\n"
    b"2025-01-01,10,north,,\n"
    b"2025-01-02,,north,,\n"
    b"2025-01-02,,north,,\n"
)


def _make_excel(frame):
    output = BytesIO()
    frame.to_excel(output, index=False, engine="openpyxl")
    return output.getvalue()


def _make_xls():
    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Data")
    sheet.write(0, 0, "Order Date")
    sheet.write(0, 1, "Amount")
    sheet.write(1, 0, "2025-01-01")
    sheet.write(1, 1, 12)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_health_and_docs():
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/docs").status_code == 200
    openapi = client.get("/openapi.json").json()
    chart_request = openapi["paths"]["/api/eda/chart"]["post"]["requestBody"]
    assert "multipart/form-data" in chart_request["content"]


def test_analysis_endpoint_and_unknown_api_routes_return_json():
    openapi = client.get("/openapi.json").json()
    assert "post" in openapi["paths"]["/api/analyze"]

    response = client.get("/api/not-a-route")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "detail": "No API route matches GET /api/not-a-route."
    }


def test_vscode_frontend_origin_can_call_fastapi():
    for origin in ("http://127.0.0.1:3002", "http://localhost:3002"):
        response = client.options(
            "/api/analyze",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin


@pytest.mark.parametrize(
    ("path", "page"),
    [
        ("/", "overview"),
        ("/cleaning", "cleaning"),
        ("/eda", "eda"),
        ("/kpi", "kpi"),
        ("/reports", "reports"),
    ],
)
def test_web_pages_render_shared_jinja_layout_and_initial_page(path, page):
    response = client.get(path)

    assert response.status_code == 200
    assert f'data-initial-page="{page}"' in response.text
    assert 'href="style.css"' in response.text
    assert 'src="script.js?v=20261027-1"' in response.text
    assert 'href="/cleaning"' in response.text
    assert 'href="/eda"' in response.text
    assert 'href="/kpi"' in response.text
    assert 'href="/reports"' in response.text
    assert "Exportable report generation is not implemented yet." in response.text


def test_web_assets_are_served_from_the_fastapi_app():
    stylesheet = client.get("/style.css")
    script = client.get("/script.js")
    assert stylesheet.status_code == 200
    assert "workflow-actions" in stylesheet.text
    assert script.status_code == 200
    assert "restoreWorkspaceOnStartup" in script.text
    assert 'window.location.port === "3002"' in script.text
    assert 'http://127.0.0.1:8001' in script.text
    assert 'window.location.port === "3002";' in script.text

    stylesheet = client.get("/assets/style.css")
    script = client.get("/assets/script.js")

    assert stylesheet.status_code == 200
    assert "workflow-actions" in stylesheet.text
    assert script.status_code == 200
    assert "restoreWorkspaceOnStartup" in script.text


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("orders.csv", PROFILE_CSV),
        (
            "orders.xlsx",
            _make_excel(
                pd.DataFrame(
                    {
                        "Order Date": ["2025-01-01", "2025-01-02"],
                        "Amount": [10, 20],
                    }
                )
            ),
        ),
        ("orders.xls", _make_xls()),
    ],
    ids=["csv", "xlsx", "xls"],
)
def test_day_one_analysis_accepts_supported_formats(filename, content):
    response = client.post(
        "/api/analyze", files={"file": (filename, content)}
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["records"] > 0
    assert result["column_count"] > 0
    assert "preview" in result
    assert "columns" in result
    assert set(result["eda"]) == {
        "statistics",
        "charts",
        "messages",
        "datetime_columns",
    }
    assert set(result["dashboard_visualizations"]) == {"charts", "messages"}
    assert all("name" in column and "dtype" in column for column in result["columns"])


def test_csv_profiling_counts_values_and_limits_preview_to_ten_rows():
    content = (
        "Order Date,Amount,Category\n"
        "2025-01-01,10,north\n"
        "2025-01-02,,south\n"
        "2025-01-02,,south\n"
    ).encode()
    response = client.post(
        "/api/analyze", files={"file": ("orders.csv", content)}
    )

    assert response.status_code == 200
    result = response.json()
    assert (result["records"], result["column_count"]) == (3, 3)
    assert result["missing_values"] == 2
    assert result["duplicate_rows"] == 1
    assert len(result["preview"]) == 3
    assert result["preview"][0]["Order Date"] == "2025-01-01"

    twelve_rows = "id\n" + "".join(f"{row}\n" for row in range(12))
    response = client.post(
        "/api/analyze",
        files={"file": ("twelve.csv", twelve_rows.encode())},
    )
    assert response.status_code == 200
    assert len(response.json()["preview"]) == 10


def test_penguins_csv_upload_accepts_numeric_columns_and_missing_values():
    content = (
        b"species,island,bill_length_mm,bill_depth_mm,flipper_length_mm,"
        b"body_mass_g,sex\n"
        b"Adelie,Torgersen,39.1,18.7,181,3750,MALE\n"
        b"Adelie,Torgersen,,,,,\n"
        b"Gentoo,Biscoe,46.5,14.5,213,4400,FEMALE\n"
    )

    response = client.post(
        "/api/analyze", files={"file": ("penguins.csv", content)}
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert (result["records"], result["column_count"]) == (3, 7)
    assert result["missing_values"] == 5
    assert result["columns"][2]["name"] == "bill_length_mm"
    assert result["columns"][2]["chart"]["type"] == "histogram"


def test_analysis_histogram_samples_are_bounded_but_metrics_use_all_rows():
    response = client.post(
        "/api/analyze",
        files={
            "file": (
                "large-profile.csv",
                ("value\n" + "".join(f"{number}\n" for number in range(1200))).encode(),
            )
        },
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["records"] == 1200
    assert len(result["columns"][0]["chart"]["values"]) == 500
    assert result["columns"][0]["statistics"]["min"] == 0
    assert result["columns"][0]["statistics"]["max"] == 1199


def test_analysis_succeeds_when_optional_mysql_persistence_fails(monkeypatch):
    def fail_persistence(_result):
        raise SQLAlchemyError("database unavailable")

    monkeypatch.setattr("app.main.persist_analysis", fail_persistence)
    response = client.post(
        "/api/analyze",
        files={"file": ("orders.csv", b"amount\n10\n20\n")},
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["records"] == 2
    assert result["storage_persisted"] is False
    assert "MySQL metadata could not be saved" in result["storage_warning"]


def test_invalid_empty_and_malformed_uploads_are_rejected():
    for filename, content, expected_message in (
        ("data.exe", b"data", "Unsupported file type"),
        ("empty.csv", b"", "empty"),
        ("header-only.csv", b"first,second\n", "no data rows or columns"),
        ("broken.xlsx", b"not an Excel workbook", "parse"),
    ):
        response = client.post(
            "/api/analyze", files={"file": (filename, content)}
        )
        assert response.status_code == 400
        assert expected_message in response.json()["detail"]


@pytest.mark.parametrize("route", ["/api/analyze", "/api/clean"])
def test_upload_byte_and_row_limits_are_enforced(route):
    too_large = client.post(
        route,
        files={
            "file": (
                "too-large.csv",
                b"x" * (25 * 1024 * 1024 + 1),
            )
        },
    )
    assert too_large.status_code == 413
    assert "25 MiB" in too_large.json()["detail"]

    over_row_limit = b"id\n" + b"1\n" * (MAX_ROWS + 1)
    too_many_rows = client.post(
        route,
        files={"file": ("too-many.csv", over_row_limit)},
    )
    assert too_many_rows.status_code == 413
    assert "row limit" in too_many_rows.json()["detail"]


def test_clean_default_keeps_input_missing_values_and_reports_duplicate_count():
    response = client.post(
        "/api/clean", files={"file": ("orders.csv", PROFILE_CSV)}
    )

    assert response.status_code == 200
    result = response.json()
    assert result["before"] == {
        "row_count": 3,
        "column_count": 5,
        "missing_cells": 8,
        "duplicate_rows": 1,
    }
    assert result["after"] == result["before"]
    assert result["removed_duplicate_rows"] == 0
    assert result["preview"]["columns"] == [
        "Order Date",
        "Amount",
        "Category",
        "Empty",
        "No Mode",
    ]


@pytest.mark.parametrize(
    ("strategy", "expected_missing", "expected_middle_value"),
    [
        ("mean", 6, 10),
        ("median", 6, 10),
        ("mode", 8, None),
        ("keep", 8, None),
        ("drop_rows", 0, None),
    ],
)
def test_missing_strategies_are_independent_and_empty_modes_are_safe(
    strategy, expected_missing, expected_middle_value
):
    response = client.post(
        "/api/clean",
        files={"file": ("orders.csv", PROFILE_CSV)},
        data={"missing_strategy": strategy},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["after"]["missing_cells"] == expected_missing
    if strategy in {"mean", "median"}:
        assert result["preview"]["rows"][1][1] == expected_middle_value
    if strategy == "mode":
        assert result["preview"]["rows"][0][3] is None
        assert result["preview"]["rows"][0][4] is None
    if strategy == "drop_rows":
        assert result["after"]["row_count"] == 0


def test_categorical_mode_fills_only_categorical_columns():
    content = b"Label,Amount,Empty\nA,1,\nA,,\n,3,\n"
    response = client.post(
        "/api/clean",
        files={"file": ("mode.csv", content)},
        data={"missing_strategy": "mode"},
    )

    assert response.status_code == 200
    result = response.json()
    assert [row[0] for row in result["preview"]["rows"]] == ["A", "A", "A"]
    assert result["after"]["missing_cells"] == 4


def test_duplicate_removal_reports_rows_removed_and_name_collisions():
    response = client.post(
        "/api/clean",
        files={"file": ("orders.csv", PROFILE_CSV)},
        data={
            "missing_strategy": "mean",
            "remove_duplicates": "true",
            "standardize_columns": "true",
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["before"]["duplicate_rows"] == 1
    assert result["removed_duplicate_rows"] == 1
    assert result["after"]["row_count"] == 2
    assert result["after"]["duplicate_rows"] == 0
    assert result["preview"]["columns"] == [
        "order_date",
        "amount",
        "category",
        "empty",
        "no_mode",
    ]

    collision_csv = b"Order Date,order-date\nfirst,second\n"
    response = client.post(
        "/api/clean",
        files={"file": ("collision.csv", collision_csv)},
        data={"standardize_columns": "true"},
    )
    assert response.status_code == 200
    assert response.json()["preview"]["columns"] == [
        "order_date",
        "order_date_2",
    ]


def test_invalid_cleaning_options_are_rejected_by_fastapi():
    response = client.post(
        "/api/clean",
        files={"file": ("orders.csv", PROFILE_CSV)},
        data={"missing_strategy": "guess"},
    )

    assert response.status_code == 422


def test_csv_and_excel_downloads_contain_cleaned_data_and_keep_source():
    options = {
        "missing_strategy": "mean",
        "remove_duplicates": "true",
        "standardize_columns": "true",
    }
    original = PROFILE_CSV
    csv_response = client.post(
        "/api/clean/download/csv",
        files={"file": ("orders.csv", original)},
        data=options,
    )
    excel_response = client.post(
        "/api/clean/download/xlsx",
        files={"file": ("orders.csv", original)},
        data=options,
    )

    assert csv_response.status_code == 200
    assert b"order_date,amount,category,empty,no_mode" in csv_response.content
    csv_frame = pd.read_csv(BytesIO(csv_response.content))
    assert csv_frame.shape == (2, 5)
    assert csv_frame["amount"].tolist() == [10.0, 10.0]

    assert excel_response.status_code == 200
    excel_frame = pd.read_excel(BytesIO(excel_response.content))
    assert excel_frame.shape == (2, 5)
    assert excel_frame["amount"].tolist() == [10, 10]

    assert original == PROFILE_CSV
    assert client.post(
        "/api/analyze", files={"file": ("orders.csv", original)}
    ).json()["records"] == 3


def test_eda_is_included_in_analysis_and_available_from_dedicated_endpoint():
    content = b"Amount,Category\n1,north\n2,south\n3,north\n"
    analyze_response = client.post(
        "/api/analyze", files={"file": ("eda.csv", content)}
    )
    eda_response = client.post(
        "/api/eda", files={"file": ("eda.csv", content)}
    )

    assert analyze_response.status_code == 200
    assert eda_response.status_code == 200
    assert analyze_response.json()["eda"] == eda_response.json()
    report = eda_response.json()
    assert report["statistics"][0]["mean"] == 2
    assert [chart["id"] for chart in report["charts"]] == [
        "histogram:Amount",
        "box:Amount",
        "bar:Category",
    ]
    assert sum(report["charts"][0]["y"]) == 3
    assert "preview" not in report
    dashboard = analyze_response.json()["dashboard_visualizations"]
    assert [chart["type"] for chart in dashboard["charts"]] == ["bar", "pie"]
    assert dashboard["charts"][0]["colors"][0] != dashboard["charts"][0]["colors"][1]
    assert sum(dashboard["charts"][1]["values"]) == 3


def test_analysis_returns_insights_and_prediction_endpoint_evaluates_numeric_target():
    content = (
        "quantity,sales,category\n"
        + "".join(
            f"{quantity},{4 * quantity + 3},"
            f"{'north' if quantity < 12 else 'south'}\n"
            for quantity in range(1, 17)
        )
    ).encode()
    analysis = client.post(
        "/api/analyze", files={"file": ("sales.csv", content)}
    )
    prediction = client.post(
        "/api/predictions",
        files={"file": ("sales.csv", content)},
        data={"target_column": "sales"},
    )

    assert analysis.status_code == 200, analysis.text
    ai_analysis = analysis.json()["ai_analysis"]
    assert ai_analysis["prediction_targets"] == ["quantity", "sales"]
    assert ai_analysis["prediction"]["available"] is True
    assert any(item["type"] == "pattern" for item in ai_analysis["insights"])
    assert prediction.status_code == 200, prediction.text
    result = prediction.json()
    assert result["available"] is True
    assert result["target"] == "sales"
    assert result["features"] == ["quantity"]
    assert result["validation_rows"] == 4
    assert len(result["chart"]["actual"]) == len(result["chart"]["predicted"]) == 4


def test_prediction_route_handles_cleaned_datasets_and_unsupported_targets():
    content = (
        "quantity,sales,category\n"
        "1,5,north\n"
        "2,10,south\n"
        "3,15,north\n"
        "4,20,south\n"
        "5,25,north\n"
        "6,30,south\n"
        "7,35,north\n"
        "8,,south\n"
        "9,45,north\n"
        "10,50,south\n"
        "11,55,north\n"
        "12,60,south\n"
    ).encode()
    cleaned = client.post(
        "/api/predictions",
        files={"file": ("sales.csv", content)},
        data={
            "target_column": "sales",
            "data_source": "cleaned",
            "missing_strategy": "mean",
        },
    )
    unsupported = client.post(
        "/api/predictions",
        files={"file": ("sales.csv", content)},
        data={"target_column": "category"},
    )

    assert cleaned.status_code == 200, cleaned.text
    assert cleaned.json()["available"] is True
    assert unsupported.status_code == 200, unsupported.text
    assert unsupported.json()["available"] is False
    assert "numeric target" in unsupported.json()["message"]


def test_kpi_dashboard_calculates_metrics_and_filters_the_selected_dataset():
    content = (
        b"order_id,sales,profit,category,customer,date\n"
        b"1,100,10,north,a,2025-01-01\n"
        b"1,50,5,north,b,2025-01-01\n"
        b"2,80,8,south,a,2025-01-02\n"
        b"3,40,4,south,c,2025-01-03\n"
        b"3,40,4,south,c,2025-01-03\n"
    )
    original = client.post(
        "/api/kpi/dashboard",
        files={"file": ("sales.csv", content)},
    )
    filtered_cleaned = client.post(
        "/api/kpi/dashboard",
        files={"file": ("sales.csv", content)},
        data={
            "data_source": "cleaned",
            "remove_duplicates": "true",
            "category_column": "category",
            "category_value": "south",
            "date_column": "date",
            "date_from": "2025-01-02",
            "date_to": "2025-01-03",
        },
    )

    assert original.status_code == 200, original.text
    original_result = original.json()
    original_cards = {
        card["key"]: card["value"] for card in original_result["cards"]
    }
    assert original_cards["record_count"] == 5
    assert original_cards["total_sales"] == 310
    assert original_cards["total_profit"] == 31
    assert original_cards["average_order_value"] == pytest.approx(310 / 3)
    assert original_result["charts"][1]["key"] == "date_trend"
    assert original_result["filters"]["date_columns"] == ["date"]
    assert original_result["filters"]["category_columns"][0]["name"] == "category"

    assert filtered_cleaned.status_code == 200, filtered_cleaned.text
    cleaned_result = filtered_cleaned.json()
    cleaned_cards = {
        card["key"]: card["value"] for card in cleaned_result["cards"]
    }
    assert cleaned_result["dataset_label"] == "sales.csv (cleaned)"
    assert cleaned_result["row_count"] == 2
    assert cleaned_cards["record_count"] == 2
    assert cleaned_cards["total_sales"] == 120
    assert cleaned_cards["average_order_value"] == 60
    assert cleaned_result["charts"][0]["labels"] == ["south"]
    assert cleaned_result["charts"][0]["values"] == [120]


def test_kpi_filters_accept_standardized_columns_for_cleaned_dataset():
    content = (
        b"Order Date,Sales Amount,Region\n"
        b"2025-01-01,120,North\n"
        b"2025-01-02,200,South\n"
        b"2025-01-03,80,North\n"
    )
    response = client.post(
        "/api/kpi/dashboard",
        files={"file": ("sales.csv", content)},
        data={
            "data_source": "cleaned",
            "standardize_columns": "true",
            "date_column": "order_date",
            "date_from": "2025-01-01",
            "date_to": "2025-01-01",
            "category_column": "region",
            "category_value": "North",
        },
    )

    assert response.status_code == 200, response.text
    result = response.json()
    cards = {card["key"]: card["value"] for card in result["cards"]}
    assert result["row_count"] == 1
    assert cards["record_count"] == 1
    assert cards["total_sales"] == 120


@pytest.mark.parametrize(
    ("filename", "content", "expected"),
    [
        ("general.csv", b"temperature,region\n10,north\n20,south\n", 200),
        ("categories.csv", b"region\nnorth\nsouth\n", 200),
        ("invalid.exe", b"not a dataset", 400),
        ("empty.csv", b"", 400),
    ],
)
def test_kpi_dashboard_handles_general_and_invalid_uploads(filename, content, expected):
    response = client.post(
        "/api/kpi/dashboard",
        files={"file": (filename, content)},
    )
    assert response.status_code == expected, response.text
    if expected == 200:
        result = response.json()
        assert all(card["key"] != "total_sales" for card in result["cards"])
        if filename == "categories.csv":
            assert any(
                "No suitable numeric columns" in message
                for message in result["messages"]
            )
        else:
            assert any(card["key"] == "average:temperature" for card in result["cards"])


def test_cleaned_kpi_keeps_median_filled_sales_as_a_numeric_measure():
    content = (
        b"Order Date,Order ID,Region,Sales,Profit\n"
        b"2026-01-01,1001,North,100,30\n"
        b"2026-01-02,1002,South,,15\n"
        b"2026-01-03,1003,North,150,45\n"
        b"2026-01-01,1001,North,100,30\n"
        b"2026-01-04,1004,West,80,20\n"
    )

    response = client.post(
        "/api/kpi/dashboard",
        files={"file": ("sales.csv", content)},
        data={
            "data_source": "cleaned",
            "missing_strategy": "median",
            "remove_duplicates": "true",
        },
    )

    assert response.status_code == 200, response.text
    result = response.json()
    cards = {card["key"]: card["value"] for card in result["cards"]}
    assert result["row_count"] == 4
    assert cards["total_sales"] == 430


def test_kpi_dashboard_rejects_invalid_filter_columns_and_date_ranges():
    content = b"amount,category,date\n1,north,2025-01-01\n2,south,2025-01-02\n"
    invalid_category = client.post(
        "/api/kpi/dashboard",
        files={"file": ("data.csv", content)},
        data={"category_column": "amount", "category_value": "1"},
    )
    invalid_dates = client.post(
        "/api/kpi/dashboard",
        files={"file": ("data.csv", content)},
        data={
            "date_column": "date",
            "date_from": "2025-01-03",
            "date_to": "2025-01-01",
        },
    )

    assert invalid_category.status_code == 422
    assert "not a supported category column" in invalid_category.json()["detail"]
    assert invalid_dates.status_code == 422
    assert "on or before" in invalid_dates.json()["detail"]


def test_eda_selected_chart_validates_fields_columns_and_suitability():
    content = b"Amount,Category\n1,north\n2,south\n3,north\n"
    good = client.post(
        "/api/eda/chart",
        files={"file": ("eda.csv", content)},
        data={"chart_type": "histogram", "column": "Amount"},
    )
    unknown = client.post(
        "/api/eda/chart",
        files={"file": ("eda.csv", content)},
        data={"chart_type": "histogram", "column": "Missing"},
    )
    unsuitable = client.post(
        "/api/eda/chart",
        files={"file": ("eda.csv", content)},
        data={"chart_type": "histogram", "column": "Category"},
    )
    extra = client.post(
        "/api/eda/chart",
        files={"file": ("eda.csv", content)},
        data={
            "chart_type": "histogram",
            "column": "Amount",
            "expression": "Amount",
        },
    )
    missing_axis = client.post(
        "/api/eda/chart",
        files={"file": ("eda.csv", content)},
        data={"chart_type": "scatter", "column": "Amount"},
    )
    unknown_source = client.post(
        "/api/eda/chart",
        files={"file": ("eda.csv", content)},
        data={
            "chart_type": "bar",
            "column": "Category",
            "data_source": "sample",
        },
    )

    assert good.status_code == 200
    assert good.json()["chart"]["data"][0]["type"] == "histogram"
    assert len(good.json()["chart"]["data"][0]["x"]) == 3
    assert unknown.status_code == 404
    assert unsuitable.status_code == 400
    assert extra.status_code == 422
    assert missing_axis.status_code == 422
    assert unknown_source.status_code == 422


@pytest.mark.parametrize(
    ("chart_type", "column", "expected_trace"),
    [
        ("bar", "Category", "bar"),
        ("box", "Amount", "box"),
    ],
)
def test_eda_selected_bar_and_box_charts(chart_type, column, expected_trace):
    response = client.post(
        "/api/eda/chart",
        files={
            "file": (
                "selected.csv",
                b"Amount,Category\n1,north\n2,south\n3,north\n",
            )
        },
        data={"chart_type": chart_type, "column": column},
    )

    assert response.status_code == 200, response.text
    assert response.json()["chart"]["data"][0]["type"] == expected_trace


def test_eda_selected_pie_has_correct_non_missing_denominator_and_colors():
    response = client.post(
        "/api/eda/chart",
        files={
            "file": (
                "pie.csv",
                b"category\nnorth\nsouth\nnorth\n\n",
            )
        },
        data={"chart_type": "pie", "column": "category"},
    )

    assert response.status_code == 200, response.text
    trace = response.json()["chart"]["data"][0]
    assert sum(trace["values"]) == 3
    assert trace["marker"]["colors"][0] != trace["marker"]["colors"][1]
    assert "%{percent}" in trace["hovertemplate"]


def test_selected_chart_uses_the_user_selected_original_or_cleaned_dataset():
    content = b"category,amount\nnorth,2\nnorth,\nsouth,4\nsouth,4\n"
    original = client.post(
        "/api/eda/chart",
        files={"file": ("workflow.csv", content)},
        data={"chart_type": "bar", "column": "category"},
    )
    cleaned = client.post(
        "/api/eda/chart",
        files={"file": ("workflow.csv", content)},
        data={
            "chart_type": "bar",
            "column": "category",
            "data_source": "cleaned",
            "missing_strategy": "mean",
            "remove_duplicates": "true",
        },
    )

    assert original.status_code == 200, original.text
    assert cleaned.status_code == 200, cleaned.text
    assert original.json()["chart"]["data"][0]["x"] == ["north", "south"]
    assert original.json()["chart"]["data"][0]["y"] == [2, 2]
    assert cleaned.json()["chart"]["data"][0]["x"] == ["north", "south"]
    assert cleaned.json()["chart"]["data"][0]["y"] == [2, 1]


def test_eda_scatter_and_line_endpoints_preserve_valid_pairs():
    scatter = client.post(
        "/api/eda/chart",
        files={
            "file": (
                "scatter.csv",
                b"x,y\n1,10\n2,20\n3,30\ninf,40\n4,\n",
            )
        },
        data={"chart_type": "scatter", "column": "y", "x_column": "x"},
    )
    assert scatter.status_code == 200, scatter.text
    assert scatter.json()["chart"]["data"][0]["x"] == [1, 2, 3]
    assert scatter.json()["chart"]["data"][0]["y"] == [10, 20, 30]

    excel = BytesIO()
    pd.DataFrame(
        {
            "when": pd.to_datetime(["2025-01-03", "2025-01-01", "2025-01-02"]),
            "value": [30, 10, 20],
        }
    ).to_excel(excel, index=False)
    line = client.post(
        "/api/eda/chart",
        files={"file": ("line.xlsx", excel.getvalue())},
        data={"chart_type": "line", "column": "value", "x_column": "when"},
    )
    assert line.status_code == 200, line.text
    assert line.json()["chart"]["data"][0]["y"] == [10, 20, 30]


def test_cleaned_eda_recomputes_report_from_cleaning_options():
    response = client.post(
        "/api/eda/cleaned",
        files={"file": ("orders.csv", PROFILE_CSV)},
        data={
            "missing_strategy": "mean",
            "remove_duplicates": "true",
            "standardize_columns": "true",
        },
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert [column["name"] for column in result["columns"]] == [
        "order_date",
        "amount",
        "category",
        "empty",
        "no_mode",
    ]
    assert result["statistics"][0]["name"] == "amount"
    assert result["statistics"][0]["count"] == 2
    assert result["charts"] == []
    assert any("two distinct" in message for message in result["messages"])
    assert result["ai_analysis"]["prediction"]["available"] is False
    assert result["ai_analysis"]["insights"]
