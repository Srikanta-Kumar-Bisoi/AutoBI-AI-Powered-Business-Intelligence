from datetime import date, datetime
from decimal import Decimal
from numbers import Integral, Number
import re
from collections import Counter

import numpy as np
import pandas as pd
from pandas.api import types as ptypes

MAX_AUTOMATIC_CHARTS = 80
MAX_CHART_POINTS = 5_000
MAX_HISTOGRAM_BINS = 40
MAX_CATEGORICAL_VALUES = 20
MAX_BAR_VALUES = 10
MAX_AUTOMATIC_SCATTERS = 3
MAX_DASHBOARD_CHARTS = 3
MAX_PAIRWISE_NUMERIC_COLUMNS = 20
MAX_AUTOMATIC_TRENDS = 10
CHART_PALETTE = [
    "#4f8df7",
    "#ef8354",
    "#45c4a0",
    "#bd7cf6",
    "#f1c453",
    "#f06c9b",
    "#46b6d5",
    "#a3c85b",
    "#e788c8",
    "#8a9cf5",
]


def build_eda_report(frame: pd.DataFrame) -> dict:
    """Build statistics and only charts whose input types and sample sizes are valid."""
    numeric_columns = []
    categorical_columns = []
    datetime_columns = []
    statistics = []
    messages = []
    unsafe_numeric_positions = set()

    for position, name in enumerate(frame.columns):
        series = frame.iloc[:, position]
        dtype = series.dtype
        if series.dropna().empty:
            messages.append(
                f"{name}: charts are unavailable because the column has no "
                "non-missing observations."
            )
            if ptypes.is_numeric_dtype(dtype):
                statistics.append(_numeric_statistics(name, series, np.array([])))
            continue
        if ptypes.is_bool_dtype(dtype):
            if not series.dropna().empty:
                categorical_columns.append((position, name, series))
            continue
        if ptypes.is_numeric_dtype(dtype) or _is_numeric_object_series(series):
            finite_values = _finite_numeric_values(series)
            numeric_columns.append((position, name, finite_values))
            statistics.append(_numeric_statistics(name, series, finite_values))
            if not _is_plot_safe_numeric(series):
                unsafe_numeric_positions.add(position)
                messages.append(
                    f"{name}: numeric charts are omitted because integer "
                    "values cannot be represented exactly by browser charts."
                )
            if finite_values.size < 2 or np.unique(finite_values).size < 2:
                messages.append(
                    f"{name}: distribution and relationship charts need at "
                    "least two distinct finite numeric values."
                )
            continue

        timestamps = _coerce_datetime_series(series, name)
        if timestamps is not None:
            datetime_columns.append((position, name, timestamps))
            continue
        if _looks_like_datetime_column(name, series):
            messages.append(
                f"{name}: time-series charts skipped because one or more "
                "non-missing values are invalid or not consistently parseable "
                "ISO dates."
            )
            continue
        if isinstance(dtype, pd.CategoricalDtype):
            non_missing = series.dropna()
            if not non_missing.empty and not _is_numeric_object_series(series):
                categorical_columns.append((position, name, series))
        elif ptypes.is_string_dtype(dtype) and ptypes.is_object_dtype(dtype):
            non_missing = series.dropna()
            if (
                not non_missing.empty
                and int(non_missing.nunique(dropna=True)) <= MAX_CATEGORICAL_VALUES
            ):
                categorical_columns.append((position, name, series))
        elif ptypes.is_string_dtype(dtype):
            non_missing = series.dropna()
            if not non_missing.empty:
                categorical_columns.append((position, name, series))

    charts = []
    for position, name, values in numeric_columns:
        if position in unsafe_numeric_positions:
            continue
        if values.size < 2 or np.unique(values).size < 2:
            continue
        counts, edges = np.histogram(
            values, bins=min(MAX_HISTOGRAM_BINS, max(1, int(np.sqrt(values.size))))
        )
        centers = ((edges[:-1] + edges[1:]) / 2).tolist()
        chart = _chart_spec(
            chart_id=f"histogram:{name}",
            chart_type="histogram",
            title=f"Distribution of {name}",
            explanation=(
                f"Shows the exact finite-value frequency across "
                f"{values.size:,} observations; missing and infinite values "
                "are excluded."
            ),
            column=str(name),
            columns=[str(name)],
            x=centers,
            y=[int(count) for count in counts],
            x_label=str(name),
            y_label="Number of observations",
        )
        chart["bin_edges"] = [float(edge) for edge in edges]
        chart["sample_count"] = int(values.size)
        _append_chart(charts, chart)

        box_summary = _box_summary(values)
        if box_summary is not None:
            box_chart = _chart_spec(
                chart_id=f"box:{name}",
                chart_type="box",
                title=f"Spread and outliers in {name}",
                explanation=(
                    "Shows the median, interquartile range, Tukey whiskers, "
                    "and outlier count computed from every finite value."
                ),
                column=str(name),
                columns=[str(name)],
                x_label="",
                y_label=str(name),
            )
            box_chart["box"] = box_summary
            _append_chart(charts, box_chart)

    for _, name, series in categorical_columns:
        counts = _category_counts(series)
        if len(counts) < 2:
            messages.append(
                f"{name}: category comparisons need at least two observed "
                "categories."
            )
            continue
        labels, values = _limit_category_counts(counts)
        _append_chart(
            charts,
            _chart_spec(
                chart_id=f"bar:{name}",
                chart_type="bar",
                title=f"Records by {name}",
                explanation=(
                    "Compares observed category counts. Missing category "
                    "values are excluded; duplicate records remain included."
                ),
                column=str(name),
                columns=[str(name)],
                labels=labels,
                values=values,
                x_label=str(name),
                y_label="Number of records",
            ),
        )

    chartable_numeric = [
        item for item in numeric_columns
        if item[0] not in unsafe_numeric_positions
    ]
    unique_numeric = _unique_named_columns(chartable_numeric)
    if len(unique_numeric) > MAX_PAIRWISE_NUMERIC_COLUMNS:
        messages.append(
            "Correlation and automatic relationship charts use only the first "
            f"{MAX_PAIRWISE_NUMERIC_COLUMNS} unique numeric columns."
        )
        unique_numeric = unique_numeric[:MAX_PAIRWISE_NUMERIC_COLUMNS]
    if len(unique_numeric) >= 2:
        correlation_frame = pd.DataFrame(
            {
                str(name): _finite_numeric_series(frame.iloc[:, position]).reset_index(
                    drop=True
                )
                for position, name, _ in unique_numeric
            }
        )
        correlations = correlation_frame.corr(method="pearson", min_periods=3)
        labels = [str(name) for _, name, _ in unique_numeric]
        matrix = [
            [
                _safe_number(correlations.iloc[row, column])
                for column in range(len(labels))
            ]
            for row in range(len(labels))
        ]
        if any(
            matrix[row][column] is not None
            for row in range(len(labels))
            for column in range(row)
        ):
            _append_chart(
                charts,
                _chart_spec(
                    chart_id="correlation:pearson",
                    chart_type="heatmap",
                    title="Pairwise Pearson correlations",
                    explanation=(
                        "Measures linear association using at least three "
                        "pairwise-complete finite observations. Correlation "
                        "does not imply causation; constant columns and "
                        "insufficient pairs have no coefficient."
                    ),
                    column="",
                    columns=labels,
                    x=labels,
                    y=labels,
                    labels=labels,
                    z=matrix,
                    x_label="Numeric column",
                    y_label="Numeric column",
                ),
            )

    _append_automatic_scatter_charts(
        charts,
        frame,
        _unique_named_columns(chartable_numeric)[:MAX_PAIRWISE_NUMERIC_COLUMNS],
    )

    total_time_charts = 0
    for _, time_name, timestamps in datetime_columns[:MAX_PAIRWISE_NUMERIC_COLUMNS]:
        usable_time_charts = 0
        for value_position, value_name, _ in chartable_numeric[
            :MAX_PAIRWISE_NUMERIC_COLUMNS
        ]:
            values = _finite_numeric_series(frame.iloc[:, value_position])
            pair = pd.DataFrame({"timestamp": timestamps, "value": values})
            pair = pair.dropna(subset=["timestamp", "value"])
            if pair.empty:
                continue
            grouped = (
                pair.groupby("timestamp", as_index=False, sort=True)
                .agg(value=("value", "mean"), observations=("value", "size"))
                .sort_values("timestamp", kind="stable")
            )
            if len(grouped) < 2 or grouped["value"].nunique() < 2:
                continue
            sampled = _sample_frame(grouped, MAX_CHART_POINTS)
            _append_chart(
                charts,
                _chart_spec(
                    chart_id=f"line:{time_name}:{value_name}",
                    chart_type="line",
                    title=f"Mean {value_name} over {time_name}",
                    explanation=(
                        "Groups duplicate timestamps by the arithmetic mean; "
                        "the hover count shows observations per timestamp. "
                        "Missing or non-finite numeric values are excluded."
                    ),
                    column=str(value_name),
                    columns=[str(time_name), str(value_name)],
                    x=[
                        _timestamp_to_string(value)
                        for value in sampled["timestamp"].tolist()
                    ],
                    y=[
                        _safe_number(value)
                        for value in sampled["value"]
                    ],
                    customdata=[
                        int(value)
                        for value in sampled["observations"]
                    ],
                    x_label=str(time_name),
                    y_label=f"Mean {value_name}",
                ),
            )
            usable_time_charts += 1
            total_time_charts += 1
            if (
                usable_time_charts >= 5
                or total_time_charts >= MAX_AUTOMATIC_TRENDS
            ):
                break
        if total_time_charts >= MAX_AUTOMATIC_TRENDS:
            break
        if usable_time_charts == 0:
            messages.append(
                f"{time_name}: no time trend was generated; it needs at least "
                "two valid timestamps paired with a varying numeric column."
            )

    if not numeric_columns:
        messages.append(
            "Numerical histograms, box plots, correlations, and scatter plots "
            "are unavailable because no numeric columns were detected."
        )
    if not categorical_columns:
        messages.append(
            "Category comparison is unavailable because no category column "
            "with observations was detected."
        )
    if not datetime_columns:
        messages.append(
            "Time-series charts are unavailable because no strictly "
            "parseable date/time column was detected."
        )
    if len(_unique_named_columns(numeric_columns)) < 2:
        messages.append(
            "Correlation and scatter charts need at least two unique numeric "
            "columns with three or more finite observations."
        )

    return {
        "statistics": statistics,
        "charts": charts[:MAX_AUTOMATIC_CHARTS],
        "messages": messages,
        "datetime_columns": [
            str(name) for _, name, _ in datetime_columns
        ],
    }


def build_dashboard_visualizations(frame: pd.DataFrame) -> dict:
    """Recommend up to three truthful category, proportion, and time charts."""
    categorical_columns = []
    numeric_columns = []
    datetime_columns = []
    messages = []

    for position, name in enumerate(frame.columns):
        series = frame.iloc[:, position]
        if ptypes.is_bool_dtype(series.dtype):
            categorical_columns.append((position, name, series))
        elif ptypes.is_numeric_dtype(series.dtype) or _is_numeric_object_series(series):
            if _is_plot_safe_numeric(series):
                numeric_columns.append((position, name, series))
            else:
                messages.append(
                    f"Trend unavailable for {name}: integer values exceed "
                    "exact browser chart precision."
                )
        else:
            timestamps = _coerce_datetime_series(series, name)
            if timestamps is not None:
                datetime_columns.append((position, name, timestamps))
            elif _looks_like_datetime_column(name, series):
                messages.append(
                    f"Trend unavailable for {name}: invalid non-missing date values."
                )
            elif (
                ptypes.is_string_dtype(series.dtype)
                or ptypes.is_object_dtype(series.dtype)
                or isinstance(series.dtype, pd.CategoricalDtype)
            ) and not series.dropna().empty:
                if (
                    ptypes.is_object_dtype(series.dtype)
                    and int(series.nunique(dropna=True)) > MAX_CATEGORICAL_VALUES
                ):
                    continue
                categorical_columns.append((position, name, series))

    category_choice = None
    charts = []
    for _, name, series in categorical_columns:
        counts = _category_counts(series)
        if len(counts) >= 2:
            category_choice = (name, counts)
            break
    if category_choice:
        name, counts = category_choice
        labels, values = _limit_category_counts(counts)
        _append_dashboard_chart(
            charts,
            _chart_spec(
                chart_id=f"dashboard:category:{name}",
                chart_type="bar",
                title=f"Category comparison: {name}",
                explanation=(
                    "Exact record counts by category; missing category values "
                    "are excluded and duplicate records are counted."
                ),
                column=str(name),
                columns=[str(name)],
                labels=labels,
                values=values,
                x_label=str(name),
                y_label="Number of records",
            ),
        )
        charts[0]["colors"] = _category_colors(len(values))
    else:
        messages.append(
            "Category comparison unavailable: no category has at least two "
            "observed values."
        )

    trend_chart = None
    for time_position, time_name, timestamps in datetime_columns[
        :MAX_PAIRWISE_NUMERIC_COLUMNS
    ]:
        for value_position, value_name, _ in numeric_columns[
            :MAX_PAIRWISE_NUMERIC_COLUMNS
        ]:
            pair = pd.DataFrame(
                {
                    "timestamp": timestamps,
                    "value": _finite_numeric_series(
                        frame.iloc[:, value_position]
                    ),
                }
            ).dropna()
            grouped = (
                pair.groupby("timestamp", as_index=False, sort=True)
                .agg(value=("value", "mean"), observations=("value", "size"))
                .sort_values("timestamp", kind="stable")
            )
            if len(grouped) < 2 or grouped["value"].nunique() < 2:
                continue
            trend_chart = _chart_spec(
                chart_id=f"dashboard:trend:{time_name}:{value_name}",
                chart_type="line",
                title=f"Mean {value_name} over time",
                explanation=(
                    f"Valid timestamps are sorted; repeated {time_name} values "
                    "are averaged. Hover shows observations per timestamp."
                ),
                column=str(value_name),
                columns=[str(time_name), str(value_name)],
                x=[
                    _timestamp_to_string(value)
                    for value in grouped["timestamp"].tolist()
                ],
                y=[_safe_number(value) for value in grouped["value"]],
                customdata=[int(value) for value in grouped["observations"]],
                x_label=str(time_name),
                y_label=f"Mean {value_name}",
            )
            break
        if trend_chart is not None:
            break
    if trend_chart:
        _append_dashboard_chart(charts, trend_chart)
    else:
        messages.append(
            "Trend unavailable: a valid date/time column and a varying numeric "
            "column with at least two paired dates are required."
        )

    if category_choice:
        name, counts = category_choice
        if 2 <= len(counts) <= 8:
            total = int(counts.sum())
            labels = _display_category_labels(counts.index.tolist())
            values = [int(value) for value in counts.tolist()]
            pie = _chart_spec(
                chart_id=f"dashboard:proportion:{name}",
                chart_type="pie",
                title=f"Share of observed {name} categories",
                explanation=(
                    f"Each share uses the {total:,} non-missing records as its "
                    "denominator; this chart is omitted for high-cardinality "
                    "columns to avoid hiding categories."
                ),
                column=str(name),
                columns=[str(name)],
                labels=labels,
                values=values,
                x_label=str(name),
                y_label="Share of non-missing records",
            )
            pie["colors"] = _category_colors(len(values))
            charts.append(pie)
        else:
            messages.append(
                f"Proportion chart unavailable for {name}: it requires between "
                "2 and 8 categories so every share is visible."
            )

    return {
        "charts": charts[:MAX_DASHBOARD_CHARTS],
        "messages": messages,
    }


def _append_dashboard_chart(charts: list[dict], chart: dict) -> None:
    if len(charts) < MAX_DASHBOARD_CHARTS:
        charts.append(chart)


def _category_colors(count: int) -> list[str]:
    return [CHART_PALETTE[index % len(CHART_PALETTE)] for index in range(count)]


def _category_counts(series: pd.Series) -> pd.Series:
    keys = [
        (type(value).__name__, str(value))
        for value in series.dropna().tolist()
    ]
    counts = Counter(keys)
    ordered = sorted(counts.items(), key=lambda item: -item[1])
    display_counts = Counter(label for _, label in counts)
    repeated_labels = {
        label for label, count in display_counts.items() if count > 1
    }
    labels = [
        f"{label} ({kind})" if label in repeated_labels else label
        for (kind, label), _ in ordered
    ]
    return pd.Series(
        [count for _, count in ordered],
        index=labels,
        dtype="int64",
    )


def _limit_category_counts(counts: pd.Series) -> tuple[list[str], list[int]]:
    top = counts.head(MAX_BAR_VALUES)
    labels = _display_category_labels(top.index.tolist())
    values = [int(count) for count in top.tolist()]
    remainder = int(counts.iloc[MAX_BAR_VALUES:].sum())
    if remainder:
        labels.append("Other")
        values.append(remainder)
    return labels, values


def _display_category_labels(values: list[object]) -> list[str]:
    return [str(value) for value in values]


def _unique_named_columns(columns: list[tuple]) -> list[tuple]:
    name_counts = {}
    for _, name, _ in columns:
        key = str(name)
        name_counts[key] = name_counts.get(key, 0) + 1
    return [
        item
        for item in columns
        if name_counts[str(item[1])] == 1 and item[2].size >= 3
    ]


def _append_automatic_scatter_charts(
    charts: list[dict],
    frame: pd.DataFrame,
    numeric_columns: list[tuple],
) -> None:
    added = 0
    for left_index, (left_position, left_name, _) in enumerate(numeric_columns):
        for right_position, right_name, _ in numeric_columns[left_index + 1 :]:
            if str(left_name) == str(right_name):
                continue
            pair = pd.DataFrame(
                {
                    "x": _finite_numeric_series(frame.iloc[:, left_position]),
                    "y": _finite_numeric_series(frame.iloc[:, right_position]),
                }
            ).dropna()
            if (
                len(pair) < 3
                or pair["x"].nunique() < 2
                or pair["y"].nunique() < 2
            ):
                continue
            correlation = float(pair["x"].corr(pair["y"], method="pearson"))
            sampled = _sample_frame(pair, MAX_CHART_POINTS)
            chart = _chart_spec(
                chart_id=f"scatter:{left_name}:{right_name}",
                chart_type="scatter",
                title=f"Relationship between {left_name} and {right_name}",
                explanation=(
                    f"Shows {len(pair):,} pairwise-complete observations; "
                    f"Pearson r = {correlation:.4f}. Association is not "
                    "evidence of causation."
                ),
                column=str(right_name),
                columns=[str(left_name), str(right_name)],
                x=[_safe_number(value) for value in sampled["x"]],
                y=[_safe_number(value) for value in sampled["y"]],
                x_label=str(left_name),
                y_label=str(right_name),
            )
            chart["pair_count"] = int(len(pair))
            chart["pearson_r"] = correlation
            _append_chart(charts, chart)
            added += 1
            if added >= MAX_AUTOMATIC_SCATTERS:
                return


def build_selected_chart(
    frame: pd.DataFrame,
    chart_type: str,
    column: str,
    x_column: str | None = None,
) -> dict:
    """Build one selected chart from whitelisted dataframe columns."""
    column_position = _resolve_column(frame, column)
    series = frame.iloc[:, column_position]

    if chart_type == "histogram":
        values = _require_numeric_values(series, column)
        return _plotly_payload(
            chart_type,
            column,
            values,
            title=f"{column} distribution",
            x_label=column,
        )

    if chart_type == "bar":
        if not _is_categorical_column(series):
            raise UnsuitableChartError(
                "Bar charts require a categorical or text column."
            )
        values = series.dropna()
        if values.empty:
            raise UnsuitableChartError(
                "Bar charts require at least one non-missing category."
            )
        counts = _category_counts(series)
        labels, counts_values = _limit_category_counts(counts)
        return {
            "data": [
                {
                    "type": "bar",
                    "x": labels,
                    "y": counts_values,
                    "marker": {"color": _category_colors(len(labels))},
                    "hovertemplate": "%{x}: %{y:,} records<extra></extra>",
                }
            ],
            "layout": _plotly_layout(
                f"Records by {column}",
                column,
                "Number of records",
                explanation=(
                    "Exact category counts; missing values are excluded and "
                    "the Other bar aggregates categories beyond the top ten."
                ),
            ),
        }

    if chart_type == "pie":
        if not _is_categorical_column(series):
            raise UnsuitableChartError(
                "Pie charts require a categorical or text column."
            )
        counts = _category_counts(series)
        if not 2 <= len(counts) <= 8:
            raise UnsuitableChartError(
                "Pie charts require between 2 and 8 observed categories so no "
                "category share is hidden."
            )
        labels = _display_category_labels(counts.index.tolist())
        values = [int(value) for value in counts.tolist()]
        return {
            "data": [
                {
                    "type": "pie",
                    "labels": labels,
                    "values": values,
                    "marker": {"colors": _category_colors(len(values))},
                    "hole": 0.48,
                    "sort": False,
                    "hovertemplate": (
                        "%{label}: %{value:,} records (%{percent})<extra></extra>"
                    ),
                }
            ],
            "layout": _plotly_layout(
                f"Share of observed {column} categories",
                column,
                "Share of non-missing records",
                explanation=(
                    f"Percentages use all {sum(values):,} observed category "
                    "values as the denominator."
                ),
            ),
        }

    if chart_type == "box":
        values = _require_numeric_values(series, column)
        return {
            "data": [
                {
                    "type": "box",
                    "y": values,
                    "name": column,
                    "quartilemethod": "linear",
                    "boxpoints": "outliers",
                    "hovertemplate": (
                        f"{column}: %{{y:,.6g}}<extra></extra>"
                    ),
                }
            ],
            "layout": _plotly_layout(
                f"Distribution and outliers in {column}",
                "",
                column,
                explanation=(
                    "Plotly calculates quartiles from all finite numeric "
                    "values; missing and infinite values are excluded."
                ),
            ),
        }

    if chart_type not in {"scatter", "line"}:
        raise UnsuitableChartError(
            "Choose histogram, bar, pie, scatter, line or box."
        )
    if x_column is None:
        raise UnsuitableChartError(
            f"{chart_type.title()} charts require an x-axis column."
        )

    x_position = _resolve_column(frame, x_column)
    if x_position == column_position:
        raise UnsuitableChartError("Choose two different columns for this chart.")
    x_series = frame.iloc[:, x_position]

    if chart_type == "scatter":
        x_values = _finite_numeric_series(x_series)
        y_values = _finite_numeric_series(series)
        if x_values is None or y_values is None:
            raise UnsuitableChartError(
                "Scatter charts require two numeric columns."
            )
        pair = pd.DataFrame({"x": x_values, "y": y_values}).dropna()
        if len(pair) < 3:
            raise UnsuitableChartError(
                "Scatter charts require at least three rows with valid numeric pairs."
            )
        if pair["x"].nunique() < 2 or pair["y"].nunique() < 2:
            raise UnsuitableChartError(
                "Scatter charts are not informative when either selected "
                "numeric column is constant."
            )
        sampled = _sample_frame(pair, MAX_CHART_POINTS)
        correlation = float(pair["x"].corr(pair["y"], method="pearson"))
        return {
            "data": [
                {
                    "type": "scatter",
                    "mode": "markers",
                    "x": [_safe_number(value) for value in sampled["x"]],
                    "y": [_safe_number(value) for value in sampled["y"]],
                    "marker": {"color": "#4f8df7", "opacity": 0.75},
                    "customdata": [[len(pair), correlation]] * len(sampled),
                    "hovertemplate": (
                        f"{x_column}: %{{x:,.6g}}<br>{column}: %{{y:,.6g}}"
                        "<br>Valid pairs: %{customdata[0]:,}"
                        "<br>Pearson r: %{customdata[1]:.4f}<extra></extra>"
                    ),
                }
            ],
            "layout": _plotly_layout(
                f"Relationship between {x_column} and {column}",
                x_column,
                column,
                explanation=(
                    f"Pearson r = {correlation:.4f} across {len(pair):,} "
                    "pairwise-complete rows. Correlation does not imply causation."
                ),
            ),
        }

    timestamps = _coerce_datetime_series(x_series, x_column)
    if timestamps is None:
        raise UnsuitableChartError(
            "Line charts require a datetime column or consistently parseable "
            "date/time text; invalid dates are not plotted."
        )
    y_values = _finite_numeric_series(series)
    if y_values is None:
        raise UnsuitableChartError("Line charts require a numeric y-axis column.")
    pair = pd.DataFrame({"x": timestamps, "y": y_values}).dropna()
    if pair.empty:
        raise UnsuitableChartError(
            "Line charts require at least two valid datetime/numeric pairs."
        )
    pair = (
        pair.groupby("x", as_index=False, sort=True)
        .agg(y=("y", "mean"), observations=("y", "size"))
        .sort_values("x", kind="stable")
    )
    if len(pair) < 2 or pair["y"].nunique() < 2:
        raise UnsuitableChartError(
            "A time trend requires at least two distinct valid timestamps and "
            "varying numeric values."
        )
    sampled = _sample_frame(pair, MAX_CHART_POINTS)
    title = f"Mean {column} over {x_column}"
    return {
        "data": [
            {
                "type": "scatter",
                "mode": "lines",
                "x": [_timestamp_to_string(value) for value in sampled["x"]],
                "y": [_safe_number(value) for value in sampled["y"]],
                "customdata": [[int(value)] for value in sampled["observations"]],
                "line": {"color": "#45c4a0"},
                "hovertemplate": (
                    f"{x_column}: %{{x}}<br>Mean {column}: %{{y:,.6g}}"
                    "<br>Observations: %{customdata[0]:,}<extra></extra>"
                ),
            }
        ],
        "layout": _plotly_layout(
            title,
            x_column,
            f"Mean {column}",
            explanation=(
                f"Repeated timestamps are averaged over {len(pair):,} distinct "
                "times; missing and non-finite numbers are excluded."
            ),
        ),
    }


class UnknownColumnError(ValueError):
    """Raised when a selected column is not present in the uploaded dataset."""


class UnsuitableChartError(ValueError):
    """Raised when a valid dataset column does not suit the selected chart."""


def _resolve_column(frame: pd.DataFrame, name: str) -> int:
    positions = [
        position
        for position, column_name in enumerate(frame.columns)
        if str(column_name) == name
    ]
    if not positions:
        raise UnknownColumnError(f"Column '{name}' was not found in the dataset.")
    if len(positions) > 1:
        raise UnsuitableChartError(
            f"Column '{name}' is ambiguous because its name is duplicated."
        )
    return positions[0]


def _require_numeric_values(series: pd.Series, name: str) -> list[float]:
    values = _finite_numeric_series(series)
    if values is None:
        raise UnsuitableChartError(
            f"Chart column '{name}' must contain numeric values."
        )
    if not _is_plot_safe_numeric(series):
        raise UnsuitableChartError(
            f"Chart column '{name}' contains integers that cannot be "
            "represented exactly by browser charts."
        )
    finite_values = values.dropna()
    if finite_values.empty:
        raise UnsuitableChartError(
            f"Chart column '{name}' has no usable finite numeric values."
        )
    numeric_values = finite_values.to_numpy(dtype=np.float64)
    if np.unique(numeric_values).size < 2:
        raise UnsuitableChartError(
            f"Chart column '{name}' is constant; a distribution chart would "
            "not be informative."
        )
    return [float(value) for value in numeric_values]


def _finite_numeric_values(series: pd.Series) -> np.ndarray:
    values = pd.to_numeric(series, errors="coerce").to_numpy(
        dtype=np.float64, na_value=np.nan
    )
    return values[np.isfinite(values)]


def _finite_numeric_series(series: pd.Series) -> pd.Series | None:
    if not _is_numeric_series(series):
        return None
    numeric = pd.to_numeric(series, errors="coerce")
    return numeric.where(np.isfinite(numeric), np.nan)


def _is_numeric_series(series: pd.Series) -> bool:
    return (
        not ptypes.is_bool_dtype(series.dtype)
        and (
            ptypes.is_numeric_dtype(series.dtype)
            or _is_numeric_object_series(series)
        )
    )


def _is_numeric_object_series(series: pd.Series) -> bool:
    if not ptypes.is_object_dtype(series.dtype):
        return False
    values = series.dropna()
    return not values.empty and all(
        isinstance(value, (Number, Decimal, np.number))
        and not isinstance(value, (bool, np.bool_))
        for value in values
    )


def _coerce_datetime_series(
    series: pd.Series, name: object | None = None
) -> pd.Series | None:
    if not (
        ptypes.is_datetime64_any_dtype(series.dtype)
        or ptypes.is_string_dtype(series.dtype)
        or ptypes.is_object_dtype(series.dtype)
    ):
        return None
    values = series.dropna()
    if values.empty:
        return None
    name = series.name if name is None else name
    if not ptypes.is_datetime64_any_dtype(series.dtype):
        date_text = values.astype(str)
        iso_date_pattern = (
            r"\d{4}[-/]\d{1,2}(?:[-/]\d{1,2})?"
            r"(?:[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?"
            r"(?:Z|[+-]\d{2}:?\d{2})?)?"
        )
        if not date_text.map(
            lambda value: re.fullmatch(iso_date_pattern, value.strip()) is not None
        ).all():
            return None
        if not _looks_like_datetime_column(name, series):
            return None
    parsed = pd.to_datetime(series, format="mixed", errors="coerce", utc=True)
    if parsed[series.notna()].isna().any():
        return None
    if parsed.nunique(dropna=True) < 2:
        return parsed
    return parsed


def _looks_like_datetime_column(name: object, series: pd.Series) -> bool:
    if not (
        ptypes.is_string_dtype(series.dtype)
        or ptypes.is_object_dtype(series.dtype)
    ):
        return False
    values = series.dropna()
    if values.empty:
        return False
    name_hint = bool(
        re.search(
            r"(?:^|[_\s-])(date|time|timestamp)(?:$|[_\s-])",
            str(name).lower(),
        )
        or re.search(r"(created|updated|modified)_at$", str(name).lower())
    )
    sample_values = values.astype(str).head(20)
    value_hint = sample_values.str.contains(
        r"\d{1,4}[-/]\d{1,2}[-/]\d{1,4}|\d{4}-\d{2}|[Tt]\d{2}:\d{2}",
        regex=True,
    ).any()
    return name_hint or bool(value_hint)


def _numeric_statistics(
    name: object, series: pd.Series, finite_values: np.ndarray
) -> dict:
    stats_series = (
        series
        if ptypes.is_numeric_dtype(series.dtype)
        else pd.to_numeric(series, errors="coerce")
    )
    finite_mask = np.isfinite(
        stats_series.to_numpy(dtype=np.float64, na_value=np.nan)
    )
    valid_values = stats_series.iloc[np.flatnonzero(finite_mask)]
    if not valid_values.empty:
        mean = _safe_statistic(valid_values.mean())
        median = _safe_statistic(valid_values.median())
        minimum = _safe_statistic(valid_values.min())
        maximum = _safe_statistic(valid_values.max())
        standard_deviation = (
            _safe_statistic(valid_values.std(ddof=1))
            if len(valid_values) > 1
            else None
        )
    else:
        mean = median = minimum = maximum = standard_deviation = None
    return {
        "name": str(name),
        "dtype": str(series.dtype),
        "count": int(len(valid_values)),
        "non_missing_values": int(series.notna().sum()),
        "finite_count": int(len(valid_values)),
        "missing_values": int(series.isna().sum()),
        "non_finite_values": int(series.notna().sum() - len(valid_values)),
        "chart_supported": _is_plot_safe_numeric(series),
        "mean": mean,
        "median": median,
        "min": minimum,
        "max": maximum,
        "standard_deviation": standard_deviation,
    }


def _safe_statistic(value: object) -> float | int | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (Integral, np.integer)):
        return int(value)
    if isinstance(value, Decimal) and value == value.to_integral_value():
        return int(value)
    return _safe_number(value)


def _is_plot_safe_numeric(series: pd.Series) -> bool:
    if not (
        ptypes.is_integer_dtype(series.dtype)
        or _is_numeric_object_series(series)
    ):
        return True
    for value in series.dropna():
        if isinstance(value, Decimal):
            if value != value.to_integral_value():
                continue
            integer = int(value)
        elif isinstance(value, Integral):
            integer = int(value)
        else:
            continue
        try:
            if int(float(integer)) != integer:
                return False
        except (OverflowError, ValueError):
            return False
    return True


def _is_categorical_column(series: pd.Series) -> bool:
    dtype = series.dtype
    if _coerce_datetime_series(series) is not None:
        return False
    if (
        ptypes.is_bool_dtype(dtype)
        or isinstance(dtype, pd.CategoricalDtype)
        or ptypes.is_string_dtype(dtype)
    ):
        return True
    if ptypes.is_object_dtype(dtype):
        values = series.dropna()
        return (
            not _is_numeric_object_series(series)
            and not values.empty
            and int(values.nunique(dropna=True)) <= MAX_CATEGORICAL_VALUES
        )
    return False


def _sample_values(values: np.ndarray, limit: int) -> list[float]:
    if values.size <= limit:
        sampled = values
    else:
        indices = np.linspace(0, values.size - 1, num=limit, dtype=np.int64)
        sampled = values[indices]
    return [float(value) for value in sampled]


def _box_summary(values: np.ndarray) -> dict | None:
    if values.size < 2 or np.unique(values).size < 2:
        return None
    q1, median, q3 = np.quantile(values, [0.25, 0.5, 0.75], method="linear")
    spread = q3 - q1
    lower_limit = q1 - 1.5 * spread
    upper_limit = q3 + 1.5 * spread
    inliers = values[(values >= lower_limit) & (values <= upper_limit)]
    return {
        "q1": _safe_number(q1),
        "median": _safe_number(median),
        "q3": _safe_number(q3),
        "lower_fence": _safe_number(np.min(inliers)),
        "upper_fence": _safe_number(np.max(inliers)),
        "mean": _safe_number(np.mean(values)),
        "outlier_count": int(values.size - inliers.size),
        "count": int(values.size),
    }


def _sample_frame(frame: pd.DataFrame, limit: int) -> pd.DataFrame:
    if len(frame) <= limit:
        return frame
    indices = np.linspace(0, len(frame) - 1, num=limit, dtype=np.int64)
    return frame.iloc[indices]


def _chart_spec(
    *,
    chart_id: str,
    chart_type: str,
    title: str,
    explanation: str,
    column: str,
    columns: list[str],
    x_label: str,
    y_label: str,
    x: list | None = None,
    y: list | None = None,
    labels: list | None = None,
    values: list | None = None,
    z: list | None = None,
    customdata: list | None = None,
) -> dict:
    return {
        "id": chart_id,
        "type": chart_type,
        "title": title,
        "explanation": explanation,
        "column": column,
        "columns": columns,
        "x": x or [],
        "y": y or [],
        "labels": labels or [],
        "values": values or [],
        "z": z or [],
        "customdata": customdata or [],
        "x_label": x_label,
        "y_label": y_label,
    }


def _append_chart(charts: list[dict], chart: dict) -> None:
    if len(charts) < MAX_AUTOMATIC_CHARTS:
        charts.append(chart)


def _safe_number(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _timestamp_to_string(value: object) -> str:
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    return str(value)


def _plotly_payload(
    chart_type: str,
    column: str,
    values: list[float],
    *,
    title: str,
    x_label: str,
) -> dict:
    trace_type = "histogram"
    trace = {
        "type": trace_type,
        "x": values,
        "nbinsx": min(MAX_HISTOGRAM_BINS, max(1, int(np.sqrt(len(values))))),
        "marker": {"color": "#4f8df7"},
        "hovertemplate": (
            f"{column}: %{{x:,.6g}}<br>Bin count: %{{y:,}}<extra></extra>"
        ),
    }
    return {
        "data": [trace],
        "layout": _plotly_layout(
            title,
            x_label,
            "Number of observations",
            explanation=(
                f"Uses all {len(values):,} finite numeric values; missing and "
                "infinite values are excluded."
            ),
        ),
    }


def _plotly_layout(
    title: str,
    x_label: str,
    y_label: str,
    *,
    explanation: str = "",
) -> dict:
    return {
        "title": {"text": title},
        "xaxis": {"title": {"text": x_label}},
        "yaxis": {"title": {"text": y_label}},
        "margin": {"t": 50, "r": 20, "b": 55, "l": 60},
        "annotations": (
            [{"text": explanation, "showarrow": False, "xref": "paper",
              "yref": "paper", "x": 0, "y": 1.12, "xanchor": "left"}]
            if explanation
            else []
        ),
    }
