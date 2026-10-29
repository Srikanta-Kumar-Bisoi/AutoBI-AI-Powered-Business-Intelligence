import re
from datetime import date, datetime
from decimal import Decimal
from numbers import Integral, Real
from typing import Literal

import numpy as np
import pandas as pd
from pandas.api import types as ptypes

MissingStrategy = Literal["keep", "mean", "median", "mode", "drop_rows"]
PREVIEW_ROWS = 10
MAX_SAFE_JSON_INTEGER = 2**53 - 1
MAX_EXCEL_SAFE_INTEGER = 999_999_999_999_999


def summarize_dataframe(frame: pd.DataFrame) -> dict[str, int]:
    """Return the four dataset-quality counts shown before and after cleaning."""
    return {
        "row_count": int(len(frame)),
        "column_count": int(len(frame.columns)),
        "missing_cells": int(frame.isna().sum().sum()),
        "duplicate_rows": int(frame.duplicated().sum()),
    }


def standardize_column_names(columns: list[object]) -> list[str]:
    """Convert labels to unique lowercase snake_case names without changing data."""
    standardized = []
    used_names = set()

    for label in columns:
        name = re.sub(r"[^\w]+", "_", str(label).strip().lower()).strip("_")
        name = name or "column"
        candidate = name
        suffix = 2
        while candidate in used_names:
            candidate = f"{name}_{suffix}"
            suffix += 1
        used_names.add(candidate)
        standardized.append(candidate)

    return standardized


def _is_categorical(dtype: object) -> bool:
    """Treat booleans and text-like columns as categorical, but not dates."""
    return (
        ptypes.is_bool_dtype(dtype)
        or ptypes.is_object_dtype(dtype)
        or ptypes.is_string_dtype(dtype)
        or isinstance(dtype, pd.CategoricalDtype)
    )


def _fill_numeric_missing_values(
    frame: pd.DataFrame, strategy: Literal["mean", "median"]
) -> pd.DataFrame:
    """Fill numeric nulls while keeping existing integer values exact."""
    for position in range(frame.shape[1]):
        series = frame.iloc[:, position]
        if (
            not ptypes.is_numeric_dtype(series.dtype)
            or ptypes.is_bool_dtype(series.dtype)
            or not series.isna().any()
        ):
            continue

        valid_values = series.dropna()
        if valid_values.empty:
            continue

        if ptypes.is_integer_dtype(series.dtype):
            integer_values = sorted(int(value) for value in valid_values)
            if strategy == "mean":
                fill_value = Decimal(sum(integer_values)) / Decimal(
                    len(integer_values)
                )
            else:
                middle = len(integer_values) // 2
                if len(integer_values) % 2:
                    fill_value = integer_values[middle]
                else:
                    fill_value = Decimal(
                        integer_values[middle - 1] + integer_values[middle]
                    ) / Decimal(2)
            decimal_fill = Decimal(fill_value)
            if decimal_fill == decimal_fill.to_integral_value():
                frame.isetitem(position, series.fillna(int(fill_value)))
                continue
            if all(abs(value) <= MAX_SAFE_JSON_INTEGER for value in integer_values):
                frame.isetitem(
                    position,
                    series.astype("Float64").fillna(float(fill_value)),
                )
                continue
        else:
            fill_value = (
                valid_values.mean()
                if strategy == "mean"
                else valid_values.median()
            )
            frame.isetitem(position, series.fillna(fill_value))
            continue
        # Preserve exact large integers when a fractional fill cannot fit safely
        # in a numeric dtype.
        filled = series.astype(object).where(series.notna(), fill_value)
        frame.isetitem(position, filled)

    return frame


def _fill_categorical_missing_values(frame: pd.DataFrame) -> pd.DataFrame:
    """Fill text and boolean nulls with each column's first most-common value."""
    for position in range(frame.shape[1]):
        series = frame.iloc[:, position]
        if not _is_categorical(series.dtype) or not series.isna().any():
            continue

        modes = series.mode(dropna=True)
        if modes.empty:
            continue
        filled = series.astype(object).where(series.notna(), modes.iloc[0])
        frame.isetitem(position, filled)

    return frame


def clean_dataframe(
    frame: pd.DataFrame,
    missing_strategy: str = "keep",
    remove_duplicates: bool = False,
    standardize_columns: bool = False,
) -> pd.DataFrame:
    """Apply only requested cleaning operations to a copy of the input data."""
    supported_strategies = {"keep", "mean", "median", "mode", "drop_rows"}
    if missing_strategy not in supported_strategies:
        raise ValueError(
            "Unsupported missing-value strategy. Choose keep, mean, median, "
            "mode or drop_rows."
        )

    cleaned = frame.copy(deep=True)

    if missing_strategy == "drop_rows":
        cleaned = cleaned.dropna(axis=0)
    elif missing_strategy in {"mean", "median"}:
        cleaned = _fill_numeric_missing_values(cleaned, missing_strategy)
    elif missing_strategy == "mode":
        cleaned = _fill_categorical_missing_values(cleaned)

    if remove_duplicates:
        cleaned = cleaned.drop_duplicates().reset_index(drop=True)

    if standardize_columns:
        cleaned.columns = standardize_column_names(list(cleaned.columns))

    return cleaned


def dataframe_preview(frame: pd.DataFrame) -> dict[str, list]:
    """Return the first ten rows as JSON-safe cells, preserving duplicate headers."""
    rows = []
    for values in frame.head(PREVIEW_ROWS).itertuples(index=False, name=None):
        rows.append([_json_safe_value(value) for value in values])
    return {
        "columns": [str(name) for name in frame.columns],
        "column_types": [
            {"name": str(name), "dtype": str(frame.dtypes.iloc[position])}
            for position, name in enumerate(frame.columns)
        ],
        "rows": rows,
    }


def prepare_excel_export(frame: pd.DataFrame) -> pd.DataFrame:
    """Write exact integers beyond Excel's 15-digit precision as text cells."""
    export = frame.copy(deep=True)
    for position in range(export.shape[1]):
        series = export.iloc[:, position]
        if ptypes.is_integer_dtype(series.dtype) or ptypes.is_object_dtype(
            series.dtype
        ):
            export.isetitem(
                position,
                series.astype(object).map(
                    _excel_safe_value, na_action="ignore"
                ),
            )
    return export


def _excel_safe_value(value: object) -> object:
    """Keep precision-sensitive integer and Decimal values exact in workbooks."""
    if isinstance(value, (Integral, np.integer)):
        integer = int(value)
        return (
            str(integer)
            if abs(integer) > MAX_EXCEL_SAFE_INTEGER
            else value
        )
    if isinstance(value, Decimal) and (
        (
            value == value.to_integral_value()
            and abs(value) > MAX_EXCEL_SAFE_INTEGER
        )
        or len(value.as_tuple().digits) > 15
    ):
        return format(value, "f")
    return value


def _json_safe_value(value: object) -> object:
    """Convert pandas and NumPy scalar values without losing large integer text."""
    if pd.isna(value):
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (Integral, np.integer)):
        integer = int(value)
        return str(integer) if abs(integer) > MAX_SAFE_JSON_INTEGER else integer
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            integer = int(value)
            return (
                str(integer)
                if abs(integer) > MAX_SAFE_JSON_INTEGER
                else integer
            )
        return float(value)
    if isinstance(value, (Real, np.floating)):
        number = float(value)
        return number if np.isfinite(number) else None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    return value
