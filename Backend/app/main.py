import logging
import re
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Literal
from urllib.parse import quote

import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from openpyxl.utils.exceptions import InvalidFileException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import StreamingResponse
from xlrd.compdoc import CompDocError
from xlrd.biffh import XLRDError

from app.ai_analysis import build_ai_analysis, build_prediction_report
from app.analysis import analyze_dataframe
from app.cleaning import (
    clean_dataframe,
    dataframe_preview,
    prepare_excel_export,
    summarize_dataframe,
)
from app.eda import (
    MAX_AUTOMATIC_CHARTS,
    UnsuitableChartError,
    UnknownColumnError,
    build_dashboard_visualizations,
    build_eda_report,
    build_selected_chart,
)
from app.kpi import build_kpi_dashboard
from app.database import database_url, persist_analysis

logger = logging.getLogger(__name__)
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "Frontend"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_ROWS = 100_000
SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls"}
MAX_COLUMN_NAME_LENGTH = 255
COLUMN_NAME_PATTERN = r"^[^/\\\x00-\x1f\x7f]+$"

app = FastAPI(title="AutoBI API", version="0.1.0")


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    request: Request, error: StarletteHTTPException
) -> JSONResponse:
    if (
        error.status_code == 404
        and request.url.path.startswith("/api/")
        and request.scope.get("route") is None
    ):
        detail = (
            f"No API route matches {request.method} {request.url.path}."
        )
    else:
        detail = error.detail
    return JSONResponse(
        status_code=error.status_code,
        content={"detail": detail},
        headers=error.headers,
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:3002",
        "http://127.0.0.1:3002",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
templates = Jinja2Templates(directory=str(FRONTEND_DIR))
app.mount(
    "/assets",
    StaticFiles(directory=str(FRONTEND_DIR)),
    name="frontend-assets",
)


@app.get("/", include_in_schema=False)
@app.get("/overview", include_in_schema=False)
def overview_page(request: Request):
    return _render_page(request, "overview")


@app.get("/cleaning", include_in_schema=False)
def cleaning_page(request: Request):
    return _render_page(request, "cleaning")


@app.get("/eda", include_in_schema=False)
def eda_page(request: Request):
    return _render_page(request, "eda")


@app.get("/kpi", include_in_schema=False)
def kpi_page(request: Request):
    return _render_page(request, "kpi")


@app.get("/reports", include_in_schema=False)
def reports_page(request: Request):
    return _render_page(request, "reports")


def _render_page(request: Request, initial_page: str):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"initial_page": initial_page},
    )


class ChartSelection(BaseModel):
    """Allow only a chart kind and exact uploaded column names."""

    model_config = ConfigDict(extra="forbid")

    chart_type: Literal["histogram", "bar", "pie", "scatter", "line", "box"]
    column: str = Field(
        min_length=1,
        max_length=MAX_COLUMN_NAME_LENGTH,
        pattern=COLUMN_NAME_PATTERN,
    )
    x_column: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_COLUMN_NAME_LENGTH,
        pattern=COLUMN_NAME_PATTERN,
    )

    @model_validator(mode="after")
    def validate_axis_columns(self):
        if self.chart_type in {"scatter", "line"} and self.x_column is None:
            raise ValueError(f"{self.chart_type} charts require x_column.")
        if self.chart_type in {"histogram", "bar", "pie", "box"} and self.x_column is not None:
            raise ValueError(
                f"{self.chart_type} charts accept only one column."
            )
        return self


@app.get("/health")
@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "mysql_configured": database_url is not None,
    }


@app.post("/api/kpi/dashboard")
def kpi_dashboard(
    file: UploadFile = File(...),
    data_source: Literal["original", "cleaned"] = Form("original"),
    missing_strategy: Literal["keep", "mean", "median", "mode", "drop_rows"] = Form(
        "keep"
    ),
    remove_duplicates: bool = Form(False),
    standardize_columns: bool = Form(False),
    date_column: str | None = Form(None),
    date_from: str | None = Form(None),
    date_to: str | None = Form(None),
    category_column: str | None = Form(None),
    category_value: str | None = Form(None),
) -> dict:
    """Calculate request-scoped KPIs and charts from the chosen dataset version."""
    frame, filename = read_dataset(file)
    if data_source == "cleaned":
        frame = clean_dataframe(
            frame,
            missing_strategy=missing_strategy,
            remove_duplicates=remove_duplicates,
            standardize_columns=standardize_columns,
        )
    try:
        report = build_kpi_dashboard(
            frame,
            dataset_label=f"{filename} ({data_source})",
            date_column=date_column or None,
            date_from=date_from or None,
            date_to=date_to or None,
            category_column=category_column or None,
            category_value=category_value,
        )
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _sanitize_json_value(report)


def read_dataset(file: UploadFile) -> tuple[pd.DataFrame, str]:
    """Validate and parse one bounded CSV or Excel upload."""
    filename = re.split(r"[\\/]", file.filename or "dataset")[-1]
    extension = (
        "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    )
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Upload a CSV, XLSX or XLS file.",
        )

    content = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail="The upload exceeds the 25 MiB file size limit.",
        )
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    try:
        buffer = BytesIO(content)
        frame = (
            pd.read_csv(
                buffer, dtype_backend="numpy_nullable", nrows=MAX_ROWS + 1
            )
            if extension == ".csv"
            else pd.read_excel(
                buffer, dtype_backend="numpy_nullable", nrows=MAX_ROWS + 1
            )
        )
    except (
        UnicodeDecodeError,
        pd.errors.EmptyDataError,
        pd.errors.ParserError,
        ValueError,
        zipfile.BadZipFile,
        InvalidFileException,
        XLRDError,
        CompDocError,
        EOFError,
    ) as error:
        raise HTTPException(
            status_code=400,
            detail=f"Could not parse the uploaded dataset: {error}",
        ) from error

    if frame.empty:
        raise HTTPException(
            status_code=400,
            detail="The uploaded dataset has no data rows or columns.",
        )
    if len(frame) > MAX_ROWS:
        raise HTTPException(
            status_code=413,
            detail=f"The upload exceeds the {MAX_ROWS:,}-row limit.",
        )
    return frame, filename


def compute_eda_report(frame: pd.DataFrame) -> dict:
    """Build a bounded EDA report and make every non-finite value JSON-safe."""
    report = build_eda_report(frame)
    report["charts"] = report["charts"][:MAX_AUTOMATIC_CHARTS]
    return _sanitize_json_value(report)


def _sanitize_json_value(value):
    if isinstance(value, dict):
        return {key: _sanitize_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_json_value(item) for item in value]
    if (
        isinstance(value, int)
        and not isinstance(value, bool)
        and abs(value) > 2**53 - 1
    ):
        return str(value)
    if isinstance(value, float):
        return value if pd.notna(value) and abs(value) != float("inf") else None
    if hasattr(value, "item"):
        return _sanitize_json_value(value.item())
    return value


def _column_profiles(frame: pd.DataFrame) -> list[dict]:
    """Return the profile details used to populate interactive chart selectors."""
    profiles = []
    for position, name in enumerate(frame.columns):
        series = frame.iloc[:, position]
        profiles.append(
            {
                "name": str(name),
                "dtype": str(series.dtype),
                "missing_values": int(series.isna().sum()),
            }
        )
    return profiles


@app.post("/api/analyze")
def analyze(file: UploadFile = File(...)) -> dict:
    frame, filename = read_dataset(file)
    result = analyze_dataframe(frame, filename)
    result["eda"] = compute_eda_report(frame)
    result["ai_analysis"] = _sanitize_json_value(
        build_ai_analysis(frame, result["eda"])
    )
    result["dashboard_visualizations"] = _sanitize_json_value(
        build_dashboard_visualizations(frame)
    )
    try:
        result["storage_persisted"] = persist_analysis(result)
    except SQLAlchemyError:
        logger.exception("Could not persist dataset analysis to MySQL")
        result["storage_persisted"] = False
        result["storage_warning"] = (
            "MySQL metadata could not be saved. Check DATABASE_URL and confirm "
            "the MySQL server is available."
        )
    return result


@app.post("/api/eda")
def eda(file: UploadFile = File(...)) -> dict:
    """Return numeric summaries and at most 80 sampled automatic chart specs."""
    frame, _ = read_dataset(file)
    return compute_eda_report(frame)


@app.post("/api/eda/cleaned")
def cleaned_eda(
    file: UploadFile = File(...),
    missing_strategy: Literal["keep", "mean", "median", "mode", "drop_rows"] = Form(
        "keep"
    ),
    remove_duplicates: bool = Form(False),
    standardize_columns: bool = Form(False),
) -> dict:
    """Recompute EDA from the uploaded data after applying selected clean options."""
    frame, _ = read_dataset(file)
    cleaned = clean_dataframe(
        frame,
        missing_strategy=missing_strategy,
        remove_duplicates=remove_duplicates,
        standardize_columns=standardize_columns,
    )
    report = compute_eda_report(cleaned)
    return {
        **report,
        "columns": _column_profiles(cleaned),
        "ai_analysis": _sanitize_json_value(build_ai_analysis(cleaned, report)),
    }


@app.post("/api/predictions")
def predictions(
    file: UploadFile = File(...),
    target_column: str = Form(...),
    data_source: Literal["original", "cleaned"] = Form("original"),
    missing_strategy: Literal["keep", "mean", "median", "mode", "drop_rows"] = Form(
        "keep"
    ),
    remove_duplicates: bool = Form(False),
    standardize_columns: bool = Form(False),
) -> dict:
    """Evaluate a numeric target with a bounded, held-out linear regression."""
    frame, _ = read_dataset(file)
    if data_source == "cleaned":
        frame = clean_dataframe(
            frame,
            missing_strategy=missing_strategy,
            remove_duplicates=remove_duplicates,
            standardize_columns=standardize_columns,
        )
    return _sanitize_json_value(build_prediction_report(frame, target_column))


@app.post("/api/eda/chart")
async def selected_eda_chart(
    request: Request,
    file: UploadFile = File(...),
    chart_type: Literal["histogram", "bar", "pie", "scatter", "line", "box"] = Form(...),
    column: str = Form(...),
    x_column: str | None = Form(None),
    data_source: Literal["original", "cleaned"] = Form("original"),
    missing_strategy: Literal["keep", "mean", "median", "mode", "drop_rows"] = Form(
        "keep"
    ),
    remove_duplicates: bool = Form(False),
    standardize_columns: bool = Form(False),
) -> dict:
    """Return a validated chart from the original or requested cleaned dataset."""
    form = await request.form()
    allowed_fields = {
        "file",
        "chart_type",
        "column",
        "x_column",
        "data_source",
        "missing_strategy",
        "remove_duplicates",
        "standardize_columns",
    }
    unexpected_fields = set(form.keys()) - allowed_fields
    if unexpected_fields:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported chart field(s): {', '.join(sorted(unexpected_fields))}.",
        )

    try:
        selection = ChartSelection.model_validate(
            {
                "chart_type": chart_type,
                "column": column,
                "x_column": x_column,
            }
        )
    except ValidationError as error:
        messages = "; ".join(
            item["msg"] for item in error.errors(include_context=False)
        )
        raise HTTPException(status_code=422, detail=messages) from error

    frame, _ = read_dataset(file)
    if data_source == "cleaned":
        frame = clean_dataframe(
            frame,
            missing_strategy=missing_strategy,
            remove_duplicates=remove_duplicates,
            standardize_columns=standardize_columns,
        )
    try:
        chart = build_selected_chart(
            frame,
            selection.chart_type,
            selection.column,
            selection.x_column,
        )
    except UnknownColumnError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except UnsuitableChartError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"chart": _sanitize_json_value(chart)}


def _clean_upload(
    file: UploadFile,
    missing_strategy: str,
    remove_duplicates: bool,
    standardize_columns: bool,
) -> tuple[pd.DataFrame, dict]:
    """Clean one validated upload and prepare counts and preview for the UI."""
    original, filename = read_dataset(file)
    before = summarize_dataframe(original)
    cleaned = clean_dataframe(
        original,
        missing_strategy=missing_strategy,
        remove_duplicates=False,
        standardize_columns=standardize_columns,
    )
    removed_duplicate_rows = (
        int(cleaned.duplicated().sum()) if remove_duplicates else 0
    )
    if remove_duplicates:
        cleaned = cleaned.drop_duplicates().reset_index(drop=True)
    result = {
        "filename": filename,
        "before": before,
        "after": summarize_dataframe(cleaned),
        "removed_duplicate_rows": removed_duplicate_rows,
        "options": {
            "missing_strategy": missing_strategy,
            "remove_duplicates": remove_duplicates,
            "standardize_columns": standardize_columns,
        },
        "preview": dataframe_preview(cleaned),
    }
    return cleaned, result


@app.post("/api/clean")
def clean(
    file: UploadFile = File(...),
    missing_strategy: Literal["keep", "mean", "median", "mode", "drop_rows"] = Form(
        "keep"
    ),
    remove_duplicates: bool = Form(False),
    standardize_columns: bool = Form(False),
) -> dict:
    """Return before/after quality counts and a preview of the cleaned data."""
    _, result = _clean_upload(
        file, missing_strategy, remove_duplicates, standardize_columns
    )
    return result


@app.post("/api/clean/download/{output_format}")
def download_cleaned_dataset(
    output_format: Literal["csv", "xlsx"],
    file: UploadFile = File(...),
    missing_strategy: Literal["keep", "mean", "median", "mode", "drop_rows"] = Form(
        "keep"
    ),
    remove_duplicates: bool = Form(False),
    standardize_columns: bool = Form(False),
) -> StreamingResponse:
    """Reapply the selected options and stream a CSV or Excel download."""
    cleaned, _ = _clean_upload(
        file, missing_strategy, remove_duplicates, standardize_columns
    )
    stem = re.sub(
        r"[^A-Za-z0-9._-]+",
        "_",
        _clean_upload_filename(file.filename or "dataset"),
    ).strip("._-")
    stem = stem or "dataset"

    if output_format == "csv":
        content = cleaned.to_csv(index=False).encode("utf-8-sig")
        media_type = "text/csv; charset=utf-8"
        filename = f"{stem}_cleaned.csv"
    else:
        output = BytesIO()
        prepare_excel_export(cleaned).to_excel(
            output, index=False, engine="openpyxl"
        )
        content = output.getvalue()
        media_type = (
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        )
        filename = f"{stem}_cleaned.xlsx"

    headers = {
        "Content-Disposition": (
            f"attachment; filename=\"{filename}\"; "
            f"filename*=UTF-8''{quote(filename)}"
        )
    }
    return StreamingResponse(BytesIO(content), media_type=media_type, headers=headers)


def _clean_upload_filename(filename: str) -> str:
    """Keep only the upload's basename before constructing a download name."""
    return re.split(r"[\\/]", filename)[-1].rsplit(".", 1)[0]


app.mount(
    "/",
    StaticFiles(directory=str(FRONTEND_DIR)),
    name="frontend-files",
)
