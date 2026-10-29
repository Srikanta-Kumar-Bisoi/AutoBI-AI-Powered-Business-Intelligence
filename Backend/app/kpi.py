import re
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from pandas.api import types as ptypes

MAX_KPI_CATEGORIES = 100
MAX_CHART_CATEGORIES = 10
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

_SALES_NAME = re.compile(
    r"(?<![a-z0-9])(sales?|revenue|turnover)(?![a-z0-9])", re.IGNORECASE
)
_PROFIT_NAME = re.compile(
    r"(?<![a-z0-9])(profit|earnings)(?![a-z0-9])", re.IGNORECASE
)
_CUSTOMER_NAME = re.compile(
    r"(?<![a-z0-9])customers?(?![a-z0-9])", re.IGNORECASE
)
_PRODUCT_NAME = re.compile(
    r"(?<![a-z0-9])(products?|items?)(?![a-z0-9])", re.IGNORECASE
)
_ORDER_ID_NAME = re.compile(
    r"(?<![a-z0-9])(order|invoice|transaction)[ _-]*(id|number|no)(?![a-z0-9])",
    re.IGNORECASE,
)
_NON_ADDITIVE_NAME = re.compile(
    r"(?<![a-z0-9])(tax|margin|rate|percent|percentage|ratio)(?![a-z0-9])",
    re.IGNORECASE,
)


def _is_sales_metric(name: str) -> bool:
    return bool(_SALES_NAME.search(name) and not _NON_ADDITIVE_NAME.search(name))


def _is_profit_metric(name: str) -> bool:
    return bool(_PROFIT_NAME.search(name) and not _NON_ADDITIVE_NAME.search(name))


def build_kpi_dashboard(
    frame: pd.DataFrame,
    *,
    dataset_label: str,
    date_column: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    category_column: str | None = None,
    category_value: str | None = None,
) -> dict[str, Any]:
    """Calculate filter-consistent KPI cards and charts from one request's data."""
    date_columns = _date_columns(frame)
    category_columns = _category_columns(frame, set(date_columns))
    category_columns.sort(key=lambda item: _category_priority(item[0]))
    _validate_filter_columns(
        date_column,
        category_column,
        category_value,
        date_columns,
        category_columns,
    )
    if date_from and date_to and date_from > date_to:
        raise ValueError("The start date must be on or before the end date.")

    filters = frame.copy(deep=False)
    if date_column:
        dates = _parsed_dates(filters[date_column])
        if date_from:
            start = pd.Timestamp(date.fromisoformat(date_from), tz="UTC")
            filters = filters.loc[dates >= start]
            dates = dates.loc[filters.index]
        if date_to:
            filters = filters.loc[
                dates.dt.date <= date.fromisoformat(date_to)
            ]
            dates = dates.loc[filters.index]
    else:
        dates = None

    if category_column and category_value is not None and category_value != "":
        filters = filters.loc[
            filters[category_column].notna()
            & filters[category_column].astype(str).eq(category_value)
        ]
        if dates is not None:
            dates = dates.loc[filters.index]

    trend_date_column = date_column or (date_columns[0] if date_columns else None)
    if trend_date_column and dates is None:
        dates = _parsed_dates(filters[trend_date_column])

    filtered_numeric = _numeric_columns(filters)
    cards = _build_kpi_cards(filters, filtered_numeric)
    charts = _build_kpi_charts(
        filters,
        filtered_numeric,
        date_column=trend_date_column,
        dates=dates,
        category_columns=category_columns,
    )

    filter_options = _filter_options(frame, date_columns, category_columns)
    messages = []
    if not filtered_numeric:
        messages.append(
            "No suitable numeric columns are available for numeric KPIs. "
            "Record count and category breakdowns are still based on the selected data."
        )
    if not cards:
        messages.append("No KPI cards can be calculated for this dataset.")
    if len(cards) < 4:
        messages.append(
            f"Only {len(cards)} suitable KPI(s) were found; no additional metrics "
            "are invented for this dataset."
        )
    if not charts:
        messages.append(
            "No reliable category or time-series chart can be generated from "
            "the selected columns."
        )

    return {
        "dataset_label": dataset_label,
        "row_count": int(len(filters)),
        "cards": cards[:6],
        "charts": charts[:3],
        "filters": filter_options,
        "selected_filters": {
            "date_column": date_column,
            "date_from": date_from,
            "date_to": date_to,
            "category_column": category_column,
            "category_value": category_value,
        },
        "messages": messages,
    }


def _numeric_columns(frame: pd.DataFrame) -> list[tuple[str, pd.Series]]:
    result = []
    for position, name in enumerate(frame.columns):
        series = frame.iloc[:, position]
        if ptypes.is_bool_dtype(series.dtype) or not ptypes.is_numeric_dtype(
            series.dtype
        ):
            continue
        values = pd.to_numeric(series, errors="coerce")
        if not ptypes.is_integer_dtype(values.dtype):
            values = values.astype("float64")
            values = values.where(np.isfinite(values), np.nan)
        if values.notna().any():
            result.append((str(name), values))
    return result


def _date_columns(frame: pd.DataFrame) -> list[str]:
    result = []
    for position, name in enumerate(frame.columns):
        series = frame.iloc[:, position]
        if series.dropna().empty:
            continue
        if ptypes.is_datetime64_any_dtype(series.dtype):
            result.append(str(name))
            continue
        if not (
            ptypes.is_string_dtype(series.dtype)
            or ptypes.is_object_dtype(series.dtype)
        ):
            continue
        non_missing = series.dropna().astype(str)
        if not non_missing.str.match(
            r"^\d{4}-\d{2}-\d{2}(?:[Tt ].*)?$"
        ).all():
            continue
        parsed = pd.to_datetime(series, format="ISO8601", errors="coerce", utc=True)
        if parsed.loc[series.notna()].notna().all():
            result.append(str(name))
    return result


def _parsed_dates(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", format="ISO8601", utc=True)


def _category_columns(
    frame: pd.DataFrame, date_columns: set[str]
) -> list[tuple[str, list[str]]]:
    result = []
    for position, raw_name in enumerate(frame.columns):
        name = str(raw_name)
        if name in date_columns:
            continue
        series = frame.iloc[:, position]
        if not (
            ptypes.is_bool_dtype(series.dtype)
            or ptypes.is_string_dtype(series.dtype)
            or ptypes.is_object_dtype(series.dtype)
            or isinstance(series.dtype, pd.CategoricalDtype)
        ):
            continue
        values = series.dropna().astype(str)
        if values.nunique() < 2:
            continue
        counts = values.value_counts()
        if len(counts) > MAX_KPI_CATEGORIES:
            continue
        result.append((name, counts.index.tolist()))
    return result


def _validate_filter_columns(
    date_column: str | None,
    category_column: str | None,
    category_value: str | None,
    date_columns: list[str],
    category_columns: list[tuple[str, list[str]]],
) -> None:
    if date_column and date_column not in date_columns:
        raise ValueError(
            f"'{date_column}' is not a valid date column for this dataset."
        )
    category_names = {name for name, _ in category_columns}
    if category_column and category_column not in category_names:
        raise ValueError(
            f"'{category_column}' is not a supported category column for this dataset."
        )
    if category_column:
        allowed_values = dict(category_columns)[category_column]
        if category_value and category_value not in allowed_values:
            raise ValueError(
                f"'{category_value}' is not an available value in "
                f"'{category_column}'."
            )


def _filter_options(
    frame: pd.DataFrame,
    date_columns: list[str],
    category_columns: list[tuple[str, list[str]]],
) -> dict[str, Any]:
    date_ranges = {}
    for name in date_columns:
        dates = _parsed_dates(frame[name]).dropna()
        if not dates.empty:
            date_ranges[name] = {
                "min": dates.min().date().isoformat(),
                "max": dates.max().date().isoformat(),
            }
    return {
        "date_columns": date_columns,
        "date_ranges": date_ranges,
        "category_columns": [
            {"name": name, "values": values}
            for name, values in category_columns
        ],
    }


def _build_kpi_cards(
    frame: pd.DataFrame, numeric_columns: list[tuple[str, pd.Series]]
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = [
        _card("record_count", "Records", int(len(frame)), "number", "Rows in the selected dataset after active filters.")
    ]
    sales_columns = [
        (name, series)
        for name, series in numeric_columns
        if _is_sales_metric(name)
    ]
    profit_columns = [
        (name, series)
        for name, series in numeric_columns
        if _is_profit_metric(name)
    ]
    if sales_columns:
        name, series = sales_columns[0]
        cards.append(
            _card(
                "total_sales",
                f"Total {name}",
                _sum(series),
                "number",
                f"Sum of finite values in '{name}' after active filters; missing and non-finite values are excluded.",
            )
        )
    if profit_columns:
        name, series = profit_columns[0]
        cards.append(
            _card(
                "total_profit",
                f"Total {name}",
                _sum(series),
                "number",
                f"Sum of finite values in '{name}' after active filters; missing and non-finite values are excluded.",
            )
        )

    order_columns = [
        name for name in frame.columns if _ORDER_ID_NAME.search(str(name))
    ]
    if sales_columns and order_columns:
        order_series = frame[order_columns[0]]
        order_mask = order_series.notna()
        order_count = int(order_series.loc[order_mask].nunique())
        if order_count:
            associated_sales = sales_columns[0][1].loc[order_mask]
            cards.append(
                _card(
                    "average_order_value",
                    "Average Order Value",
                    _sum(associated_sales) / order_count,
                    "number",
                    f"Sum of '{sales_columns[0][0]}' on rows with an order ID, "
                    f"divided by {order_count:,} distinct non-missing "
                    f"'{order_columns[0]}' values.",
                )
            )

    customer_columns = [
        name for name in frame.columns if _CUSTOMER_NAME.search(str(name))
    ]
    if customer_columns:
        cards.append(
            _card(
                "unique_customers",
                "Unique Customers",
                int(frame[customer_columns[0]].dropna().nunique()),
                "number",
                f"Distinct non-missing values in '{customer_columns[0]}'.",
            )
        )
    product_columns = [
        name for name in frame.columns if _PRODUCT_NAME.search(str(name))
    ]
    if product_columns:
        cards.append(
            _card(
                "unique_products",
                "Unique Products",
                int(frame[product_columns[0]].dropna().nunique()),
                "number",
                f"Distinct non-missing values in '{product_columns[0]}'.",
            )
        )

    for name, series in numeric_columns:
        if _ORDER_ID_NAME.search(name):
            continue
        if any(name == metric[0] for metric in sales_columns + profit_columns):
            continue
        finite = series.dropna()
        if finite.empty:
            continue
        cards.append(
            _card(
                f"average:{name}",
                f"Average {name}",
                float(finite.mean()),
                "decimal",
                f"Arithmetic mean of finite '{name}' values after active filters.",
            )
        )
        if len(cards) < 6:
            cards.append(
                _card(
                    f"minimum:{name}",
                    f"Minimum {name}",
                    float(finite.min()),
                    "decimal",
                    f"Minimum finite '{name}' value after active filters.",
                )
            )
        if len(cards) < 6:
            cards.append(
                _card(
                    f"maximum:{name}",
                    f"Maximum {name}",
                    float(finite.max()),
                    "decimal",
                    f"Maximum finite '{name}' value after active filters.",
                )
            )
        break
    return cards[:6]


def _sum(series: pd.Series) -> int | float:
    finite = series.dropna()
    if finite.empty:
        return 0
    if ptypes.is_integer_dtype(finite.dtype):
        return sum(int(value) for value in finite.tolist())
    total = float(finite.sum())
    if total.is_integer() and abs(total) <= 2**53 - 1:
        return int(total)
    return total


def _card(
    key: str, label: str, value: int | float, format_kind: str, definition: str
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "value": value,
        "format": format_kind,
        "definition": definition,
    }


def _build_kpi_charts(
    frame: pd.DataFrame,
    numeric_columns: list[tuple[str, pd.Series]],
    *,
    date_column: str | None,
    dates: pd.Series | None,
    category_columns: list[tuple[str, list[str]]],
) -> list[dict[str, Any]]:
    charts = []
    measure = next(
        (
            (name, series)
            for name, series in numeric_columns
            if _is_sales_metric(name) or _is_profit_metric(name)
        ),
        numeric_columns[0] if numeric_columns else None,
    )
    if category_columns:
        category_name, _ = category_columns[0]
        category_values = frame[category_name].astype("string")
        if measure:
            measure_name, measure_values = measure
            joined = pd.DataFrame(
                {"category": category_values, "measure": measure_values}
            ).dropna()
            if _is_sales_metric(measure_name) or _is_profit_metric(measure_name):
                grouped = joined.groupby("category", observed=True)["measure"].sum()
                aggregation = "sum"
            else:
                grouped = joined.groupby("category", observed=True)["measure"].mean()
                aggregation = "mean"
            metric_label = measure_name
        else:
            grouped = category_values.dropna().value_counts()
            aggregation = "count"
            metric_label = "records"
        grouped = grouped.sort_values(ascending=False).head(MAX_CHART_CATEGORIES)
        if len(grouped):
            charts.append(
                _bar_chart(
                    "category_comparison",
                    f"{aggregation.title()} {metric_label} by {category_name}",
                    f"Compares {aggregation} {metric_label} for each observed category after active filters.",
                    category_name,
                    metric_label if aggregation != "count" else "Number of records",
                    grouped.index.astype(str).tolist(),
                    [float(value) for value in grouped.tolist()],
                )
            )

    if date_column and dates is not None:
        date_frame = pd.DataFrame({"date": dates})
        if measure:
            date_frame["measure"] = measure[1]
            date_frame = date_frame.dropna()
            grouped_dates = date_frame.groupby("date", observed=True)["measure"]
            if _is_sales_metric(measure[0]) or _is_profit_metric(measure[0]):
                grouped = grouped_dates.sum()
                aggregation = "sum"
            else:
                grouped = grouped_dates.mean()
                aggregation = "mean"
            y_label = f"{aggregation.title()} {measure[0]}"
            explanation = (
                f"Shows {aggregation} {measure[0]} by date after active filters; "
                "this is an association over time, not a causal explanation."
            )
        else:
            grouped = date_frame.groupby("date", observed=True).size()
            y_label = "Number of records"
            explanation = "Shows record counts by valid date after active filters."
        grouped = grouped.sort_index()
        if len(grouped) > 1:
            charts.append(
                {
                    "key": "date_trend",
                    "type": "line",
                    "title": f"{y_label} over time",
                    "explanation": explanation,
                    "x_label": date_column,
                    "y_label": y_label,
                    "x": [stamp.isoformat() for stamp in grouped.index],
                    "y": [float(value) for value in grouped.tolist()],
                }
            )

    return charts


def _bar_chart(
    key: str,
    title: str,
    explanation: str,
    x_label: str,
    y_label: str,
    labels: list[str],
    values: list[float],
) -> dict[str, Any]:
    return {
        "key": key,
        "type": "bar",
        "title": title,
        "explanation": explanation,
        "x_label": x_label,
        "y_label": y_label,
        "labels": labels,
        "values": values,
        "colors": [
            CHART_PALETTE[index % len(CHART_PALETTE)]
            for index in range(len(labels))
        ],
    }


def _category_priority(name: str) -> int:
    lowered = name.lower()
    if re.search(
        r"(?<![a-z0-9])(category|segment|region|type|class)(?![a-z0-9])",
        lowered,
    ):
        return 0
    if _PRODUCT_NAME.search(name):
        return 1
    if _CUSTOMER_NAME.search(name):
        return 2
    return 3
