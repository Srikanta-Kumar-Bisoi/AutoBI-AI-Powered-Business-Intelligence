import numpy as np
import pandas as pd

from app.ai_analysis import (
    build_ai_analysis,
    build_automatic_insights,
    build_prediction_report,
    prediction_targets,
)
from app.eda import build_eda_report


def test_automatic_insights_cover_trends_correlations_outliers_and_patterns():
    values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 100]
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2025-01-01", periods=len(values)),
            "amount": values,
            "related": [value * 2 for value in values],
            "segment": ["main"] * 9 + ["other"] * 3,
        }
    )
    report = build_automatic_insights(frame, build_eda_report(frame))

    kinds = {insight["type"] for insight in report}
    assert {"trend", "correlation", "outlier", "pattern"} <= kinds
    assert all(insight["title"] and insight["detail"] and insight["action"] for insight in report)
    assert any("correlation does not establish cause" in item["action"] for item in report)


def test_prediction_uses_missing_numeric_features_and_is_deterministic():
    inputs = np.arange(1, 17, dtype=float)
    target = inputs * 4 + 3
    inputs[[2, 11]] = np.nan
    frame = pd.DataFrame(
        {
            "quantity": inputs,
            "sales": target,
            "category": ["north", "south"] * 8,
        }
    )

    first = build_prediction_report(frame, "sales")
    second = build_prediction_report(frame, "sales")

    assert first == second
    assert first["available"] is True
    assert first["algorithm"] == "Linear regression"
    assert first["target"] == "sales"
    assert first["features"] == ["quantity"]
    assert first["training_rows"] == 12
    assert first["validation_rows"] == 4
    assert len(first["chart"]["actual"]) == len(first["chart"]["predicted"]) == 4
    assert np.isfinite(first["chart"]["predicted"]).all()
    assert first["metrics"]["mae"] >= 0


def test_small_single_numeric_and_non_numeric_datasets_are_not_modeled():
    small = pd.DataFrame(
        {"measure": [1, 2, 3], "category": ["a", "b", "a"]}
    )
    only_one_numeric = pd.DataFrame(
        {"measure": np.arange(12), "category": ["a", "b"] * 6}
    )

    assert prediction_targets(small) == []
    assert build_prediction_report(small)["available"] is False
    assert prediction_targets(only_one_numeric) == []
    assert "numeric" in build_prediction_report(
        only_one_numeric, "measure"
    )["message"]


def test_ai_report_handles_missing_values_and_exposes_prediction_candidates():
    frame = pd.DataFrame(
        {
            "feature": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            "target": [2, 4, 6, 8, 10, 12, 14, 16, 18, 20],
            "empty": [None] * 10,
        }
    )
    report = build_ai_analysis(frame, build_eda_report(frame))

    assert report["prediction_targets"] == ["feature", "target"]
    assert report["prediction"]["target"] == "feature"
    assert report["insights"]
    assert "deterministic" in report["summary"]
