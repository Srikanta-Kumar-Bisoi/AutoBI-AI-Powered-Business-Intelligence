import json

import numpy as np
import pandas as pd

MAX_PROFILE_CHART_POINTS = 500


def analyze_dataframe(frame: pd.DataFrame, filename: str) -> dict:
    if frame.empty and len(frame.columns) == 0:
        raise ValueError("The uploaded dataset has no columns.")

    if not isinstance(frame.columns, pd.Index) or len(frame.columns) == 0:
        raise ValueError("The uploaded dataset is missing column headers.")

    record_count, column_count = frame.shape
    missing_values = int(frame.isna().sum().sum())
    duplicate_rows = int(frame.duplicated().sum())
    columns = []

    for name in frame.columns:
        values = frame[name].dropna()
        column = {
            "name": str(name),
            "dtype": str(frame[name].dtype),
            "missing_values": int(frame[name].isna().sum()),
            "non_null_values": int(frame[name].notna().sum()),
            "chart": None,
        }

        if pd.api.types.is_numeric_dtype(frame[name]) and not values.empty:
            numeric_values = values.to_numpy(dtype=np.float64)
            numeric_values = numeric_values[np.isfinite(numeric_values)]
            if numeric_values.size:
                column["statistics"] = {
                    "mean": float(np.mean(numeric_values)),
                    "median": float(np.median(numeric_values)),
                    "min": float(np.min(numeric_values)),
                    "max": float(np.max(numeric_values)),
                }
                if numeric_values.size > MAX_PROFILE_CHART_POINTS:
                    indices = np.linspace(
                        0,
                        numeric_values.size - 1,
                        num=MAX_PROFILE_CHART_POINTS,
                        dtype=np.int64,
                    )
                    chart_values = numeric_values[indices]
                else:
                    chart_values = numeric_values
                column["chart"] = {
                    "type": "histogram",
                    "values": chart_values.tolist(),
                }
        elif not values.empty:
            counts = values.astype(str).value_counts().head(10)
            column["chart"] = {
                "type": "bar",
                "labels": counts.index.tolist(),
                "values": [int(count) for count in counts.tolist()],
            }

        columns.append(column)

    validation = {
        "is_valid": True,
        "issues": [],
    }
    if record_count == 0:
        validation["is_valid"] = False
        validation["issues"].append("The dataset has no rows.")
    if missing_values > 0:
        validation["issues"].append(f"{missing_values} missing values detected.")
    if duplicate_rows > 0:
        validation["issues"].append(f"{duplicate_rows} duplicate rows detected.")
    if column_count == 0:
        validation["is_valid"] = False
        validation["issues"].append("No columns were detected in the dataset.")

    summary = (
        f"{filename} contains {record_count:,} records across {column_count:,} "
        f"columns. It has {missing_values:,} missing values and "
        f"{duplicate_rows:,} duplicate rows."
    )
    preview = frame.head(10).copy().astype(object)
    preview = preview.where(pd.notna(preview), "NaN")
    preview_rows = json.loads(preview.to_json(orient="records", date_format="iso"))

    return {
        "filename": filename,
        "records": int(record_count),
        "column_count": int(column_count),
        "missing_values": missing_values,
        "duplicate_rows": duplicate_rows,
        "validation": validation,
        "preview": preview_rows,
        "summary": summary,
        "columns": columns,
        "column_details": [
            {
                "name": column["name"],
                "dtype": column["dtype"],
                "missing_values": column["missing_values"],
                "non_null_values": column["non_null_values"],
            }
            for column in columns
        ],
    }
