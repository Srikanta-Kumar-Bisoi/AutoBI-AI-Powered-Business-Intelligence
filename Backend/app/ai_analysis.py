from numbers import Number

import numpy as np
import pandas as pd
from pandas.api import types as ptypes
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline

MIN_PREDICTION_ROWS = 8
MAX_PREDICTION_FEATURES = 20
MAX_INSIGHT_NUMERIC_COLUMNS = 20
MAX_GENERATED_INSIGHTS = 12


def build_ai_analysis(frame: pd.DataFrame, eda_report: dict) -> dict:
    insights = build_automatic_insights(frame, eda_report)
    targets = prediction_targets(frame)
    target = targets[0] if targets else None
    return {
        "summary": _insight_summary(frame, len(insights)),
        "insights": insights,
        "prediction_targets": targets,
        "prediction": build_prediction_report(frame, target),
    }


def build_automatic_insights(frame: pd.DataFrame, eda_report: dict) -> list[dict]:
    insights = []
    missing_count = int(frame.isna().sum().sum())
    if missing_count:
        missing_columns = [
            (str(name), int(frame.iloc[:, position].isna().sum()))
            for position, name in enumerate(frame.columns)
            if frame.iloc[:, position].isna().any()
        ]
        missing_columns.sort(key=lambda item: (-item[1], item[0]))
        detail = f"{missing_count:,} missing cells"
        if missing_columns:
            detail += "; most are in " + ", ".join(
                f"{name} ({count:,})" for name, count in missing_columns[:3]
            )
        insights.append(
            _insight(
                "data_quality",
                "Missing values",
                detail + ".",
                "Review whether the affected fields should be filled or excluded; "
                "cleaning is optional and leaves the source dataset unchanged.",
            )
        )

    for chart in eda_report.get("charts", []):
        if chart.get("id") != "correlation:pearson":
            continue
        labels = chart.get("labels", [])
        matrix = chart.get("z", [])
        pairs = []
        for row in range(len(labels)):
            for column in range(row):
                if row >= len(matrix) or column >= len(matrix[row]):
                    continue
                correlation = matrix[row][column]
                if correlation is not None and abs(correlation) >= 0.7:
                    pairs.append((abs(correlation), row, column, correlation))
        pairs.sort(reverse=True)
        for _, row, column, correlation in pairs[:3]:
            insights.append(
                _insight(
                    "correlation",
                    f"Strong relationship: {labels[column]} and {labels[row]}",
                    f"Pearson correlation is {correlation:.2f} across the available "
                    "pairwise observations.",
                    "Check whether this association is useful for planning and "
                    "validate possible drivers; correlation does not establish cause.",
                )
            )
        break

    trend_count = 0
    for chart in eda_report.get("charts", []):
        if chart.get("type") != "line":
            continue
        values = [
            value
            for value in chart.get("y", [])
            if isinstance(value, Number)
            and not isinstance(value, bool)
            and np.isfinite(value)
        ]
        if len(values) < 2:
            continue
        first = float(values[0])
        last = float(values[-1])
        change = last - first
        if change > 0:
            direction = "increased"
        elif change < 0:
            direction = "decreased"
        else:
            direction = "was stable"
        change_detail = f"from {first:,.4g} to {last:,.4g}"
        if first != 0:
            change_detail += f" ({change / abs(first):+.1%})"
        columns = chart.get("columns", [])
        metric = columns[-1] if columns else chart.get("column", "the measure")
        time_axis = columns[0] if len(columns) > 1 else "time"
        insights.append(
            _insight(
                "trend",
                f"{metric} {direction} over {time_axis}",
                f"The grouped series {direction} {change_detail} from its first "
                "to last plotted period.",
                "Compare this direction with operating targets and investigate "
                "periods that explain the change.",
            )
        )
        trend_count += 1
        if trend_count >= 3:
            break

    outlier_count = 0
    numeric_columns_checked = 0
    for position, name in enumerate(frame.columns):
        series = frame.iloc[:, position]
        if (
            not ptypes.is_numeric_dtype(series.dtype)
            or ptypes.is_bool_dtype(series.dtype)
        ):
            continue
        if numeric_columns_checked >= MAX_INSIGHT_NUMERIC_COLUMNS:
            break
        numeric_columns_checked += 1
        values = _finite_numeric_values(series)
        values = values[np.isfinite(values)]
        if values.size < 4:
            continue
        first_quartile, third_quartile = np.quantile(values, [0.25, 0.75])
        spread = third_quartile - first_quartile
        lower_bound = first_quartile - 1.5 * spread
        upper_bound = third_quartile + 1.5 * spread
        count = int(np.count_nonzero((values < lower_bound) | (values > upper_bound)))
        if not count:
            continue
        insights.append(
            _insight(
                "outlier",
                f"Potential outliers in {name}",
                f"{count:,} of {values.size:,} finite values fall outside the "
                f"1.5×IQR range ({lower_bound:,.4g} to {upper_bound:,.4g}).",
                "Check these records for data-entry issues or meaningful unusual "
                "events before changing or excluding them.",
            )
        )
        outlier_count += 1
        if outlier_count >= 3:
            break

    pattern_count = 0
    for position, name in enumerate(frame.columns):
        series = frame.iloc[:, position]
        if not (
            ptypes.is_bool_dtype(series.dtype)
            or ptypes.is_string_dtype(series.dtype)
            or ptypes.is_object_dtype(series.dtype)
            or isinstance(series.dtype, pd.CategoricalDtype)
        ):
            continue
        if series.dropna().empty:
            continue
        labels = series.dropna().astype(str)
        if labels.nunique() > 20:
            continue
        counts = labels.value_counts()
        if len(counts) < 2:
            continue
        top_label = str(counts.index[0])
        top_count = int(counts.iloc[0])
        share = top_count / int(counts.sum())
        if share < 0.5:
            continue
        insights.append(
            _insight(
                "pattern",
                f"{top_label} is the most common {name}",
                f"{top_count:,} of {int(counts.sum()):,} non-missing values "
                f"({share:.1%}) have this category.",
                "Use this as a baseline when comparing groups, and check whether "
                "smaller categories need separate attention.",
            )
        )
        pattern_count += 1
        if pattern_count >= 3:
            break

    if not insights:
        insights.append(
            _insight(
                "summary",
                "No strong patterns detected",
                "The available columns did not meet the minimum data needed for "
                "the current trend, correlation, outlier, or category checks.",
                "Add more observations or review the EDA charts for exploratory "
                "patterns.",
            )
        )
    return insights[:MAX_GENERATED_INSIGHTS]


def prediction_targets(frame: pd.DataFrame) -> list[str]:
    columns = _numeric_columns(frame)
    name_counts = _column_name_counts(frame)

    targets = []
    for position, name, values in columns:
        if name_counts[name] != 1:
            continue
        valid = np.isfinite(values)
        target_values = values[valid]
        if target_values.size < MIN_PREDICTION_ROWS or np.unique(target_values).size < 2:
            continue
        features, _ = _prediction_features(columns, position, valid)
        if features.shape[1] > 0:
            targets.append(name)
    return targets


def build_prediction_report(
    frame: pd.DataFrame, target_column: str | None = None
) -> dict:
    columns = _numeric_columns(frame)
    name_counts = _column_name_counts(frame)

    if target_column is None:
        candidates = prediction_targets(frame)
        if not candidates:
            return _unavailable_prediction(
                "No suitable numeric prediction target was found. Regression needs "
                f"at least {MIN_PREDICTION_ROWS} finite target values with variation "
                "and at least one other varying numeric feature."
            )
        target_column = candidates[0]

    matches = [
        (position, name, values)
        for position, name, values in columns
        if name == target_column
    ]
    if len(matches) != 1 or name_counts.get(target_column, 0) != 1:
        return _unavailable_prediction(
            f"{target_column} is not a unique numeric target column."
        )

    target_position, _, target_values = matches[0]
    valid_target = np.isfinite(target_values)
    target = target_values[valid_target]
    if target.size < MIN_PREDICTION_ROWS:
        return _unavailable_prediction(
            f"{target_column} has {target.size} finite target values; at least "
            f"{MIN_PREDICTION_ROWS} are needed for a holdout evaluation."
        )
    if np.unique(target).size < 2:
        return _unavailable_prediction(
            f"{target_column} is constant, so a regression model cannot learn "
            "a useful prediction."
        )

    features, feature_names = _prediction_features(
        columns, target_position, valid_target
    )
    if features.shape[1] == 0:
        return _unavailable_prediction(
            "No other varying numeric columns have usable values for predicting "
            f"{target_column}. Non-numeric columns are not used by this model."
        )

    row_positions = np.flatnonzero(valid_target)
    train_positions, test_positions = train_test_split(
        np.arange(target.size),
        test_size=0.25,
        random_state=42,
    )
    training_features = features[train_positions]
    usable_feature_mask = np.isfinite(training_features).any(axis=0)
    if not usable_feature_mask.any():
        return _unavailable_prediction(
            "The selected target has no usable numeric features in the training "
            "rows after missing values are checked."
        )

    feature_names = [
        name for name, usable in zip(feature_names, usable_feature_mask, strict=True)
        if usable
    ]
    model = make_pipeline(SimpleImputer(strategy="median"), LinearRegression())
    model.fit(training_features[:, usable_feature_mask], target[train_positions])
    predictions = model.predict(features[test_positions][:, usable_feature_mask])
    actual = target[test_positions]
    mae = float(mean_absolute_error(actual, predictions))
    rmse = float(np.sqrt(mean_squared_error(actual, predictions)))
    r_squared = (
        float(r2_score(actual, predictions))
        if np.unique(actual).size > 1
        else None
    )

    return {
        "available": True,
        "target": target_column,
        "algorithm": "Linear regression",
        "features": feature_names,
        "training_rows": int(train_positions.size),
        "validation_rows": int(test_positions.size),
        "metrics": {
            "mae": mae,
            "rmse": rmse,
            "r_squared": r_squared,
        },
        "chart": {
            "row_numbers": (row_positions[test_positions] + 1).tolist(),
            "actual": actual.tolist(),
            "predicted": predictions.tolist(),
        },
        "explanation": (
            "A linear regression model was trained on 75% of rows with known "
            "target values and evaluated on a deterministic, held-out 25%. "
            "Missing numeric features are filled with training-set medians. "
            f"At most {MAX_PREDICTION_FEATURES} numeric features are considered. "
            "This estimates performance on unseen rows; it is not a forecast "
            "of future periods."
        ),
    }


def _numeric_columns(frame: pd.DataFrame) -> list[tuple[int, str, np.ndarray]]:
    columns = []
    for position, name in enumerate(frame.columns):
        series = frame.iloc[:, position]
        if (
            not ptypes.is_numeric_dtype(series.dtype)
            or ptypes.is_bool_dtype(series.dtype)
        ):
            continue
        columns.append(
            (position, str(name), _finite_numeric_values(series))
        )
        if len(columns) > MAX_PREDICTION_FEATURES:
            break
    return columns


def _column_name_counts(frame: pd.DataFrame) -> dict[str, int]:
    name_counts: dict[str, int] = {}
    for name in frame.columns:
        string_name = str(name)
        name_counts[string_name] = name_counts.get(string_name, 0) + 1
    return name_counts


def _finite_numeric_values(series: pd.Series) -> np.ndarray:
    values = pd.to_numeric(series, errors="coerce").to_numpy(
        dtype=np.float64,
        na_value=np.nan,
        copy=True,
    )
    values[~np.isfinite(values)] = np.nan
    return values


def _prediction_features(
    columns: list[tuple[int, str, np.ndarray]],
    target_position: int,
    valid_target: np.ndarray,
) -> tuple[np.ndarray, list[str]]:
    selected = []
    selected_names = []
    for position, name, values in columns:
        if position == target_position:
            continue
        feature_values = values[valid_target]
        finite_values = feature_values[np.isfinite(feature_values)]
        if finite_values.size >= 2 and np.unique(finite_values).size >= 2:
            selected.append(feature_values)
            selected_names.append(name)
        if len(selected) >= MAX_PREDICTION_FEATURES:
            break
    features = (
        np.column_stack(selected)
        if selected
        else np.empty((int(valid_target.sum()), 0))
    )
    return features, selected_names


def _insight_summary(frame: pd.DataFrame, insight_count: int) -> str:
    return (
        f"Generated {insight_count} data-driven insight"
        f"{'s' if insight_count != 1 else ''} from "
        f"{len(frame):,} rows and {len(frame.columns):,} columns. "
        "These summaries are deterministic and use no external AI service."
    )


def _insight(
    insight_type: str, title: str, detail: str, action: str
) -> dict:
    return {
        "type": insight_type,
        "title": title,
        "detail": detail,
        "action": action,
    }


def _unavailable_prediction(message: str) -> dict:
    return {
        "available": False,
        "target": None,
        "message": message,
    }
