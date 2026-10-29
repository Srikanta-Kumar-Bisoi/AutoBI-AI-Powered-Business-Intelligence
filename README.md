# AutoBI

AutoBI is a browser-based business intelligence workspace built with FastAPI,
Pandas, NumPy, scikit-learn, Plotly.js, Bootstrap, HTML, CSS, and JavaScript.
Days 1–5 cover profiling, optional data cleaning, EDA and visualizations,
dynamic KPI dashboards, and dataset-driven predictions and insights. No paid
AI service or database is required.

## Beginner-friendly project structure

```text
Backend/
  app/
    analysis.py       # Day 1 dataset metrics, summaries, and chart data
    ai_analysis.py    # Day 5 dataset-driven insights and evaluated regression
    cleaning.py       # Optional, type-conscious dataframe cleaning
    eda.py            # Day 3 numeric statistics and bounded chart specifications
    kpi.py            # Day 4 selected-dataset KPI and chart calculations
    database.py       # Optional Day 1 MySQL metadata persistence
    main.py           # FastAPI routes, upload validation, and downloads
  tests/
    test_cleaning.py  # Cleaning behavior and edge-case tests
    test_api.py       # FastAPI/TestClient uploads, limits, and downloads
    test_eda.py       # EDA statistics, suitability, sampling, and chart limits
    test_kpi.py       # Day 4 KPI math, filters, and unsuitable-data handling
    test_ai_analysis.py # Day 5 insight and prediction edge cases
  requirements.txt
  requirements-dev.txt
  requirements-lock.txt # Exact dependency versions for the verified environment
Frontend/
  index.html          # Shared Jinja2 layout and Overview, Cleaning, EDA, KPI, Reports
  script.js           # Session-aware dataset flow, filters, Plotly, and downloads
  style.css           # Shared responsive analytics design
run.bat               # Checked Windows application startup
test.bat              # Python compile, Ruff, and pytest checks
```

FastAPI serves the multi-page Jinja2 application and its static assets. Reports
is an explicitly marked future feature; report generation is not implemented.

## Supported Python and Windows setup

The application source requires Python 3.10 or newer. The pinned environment
in `Backend/requirements-lock.txt` was generated and verified with Python
3.14.7 on Windows; use Python 3.14 for a repeatable locked setup.

Run once from the project root in PowerShell:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r Backend\requirements-lock.txt
```

The lock includes the verified runtime and test tools. If you intentionally
manage package versions yourself, use `Backend/requirements.txt` for runtime
packages and `Backend/requirements-dev.txt` for test and lint tools.

## Daily startup

Double-click `run.bat` or run it from PowerShell in the project root:

```cmd
run.bat
```

It uses the root `.venv`, checks Python and required runtime imports, checks
whether the selected port is occupied, then runs the existing FastAPI app with
reload enabled. It does not install or upgrade packages at startup. The
default URL is `http://127.0.0.1:8000/`. To select another port:

```powershell
$env:AUTOBI_PORT = "8001"
.\run.bat
```

The application pages are `/` (Overview),
`/cleaning`, `/eda`, `/kpi`, and `/reports`. FastAPI documentation is at
`http://127.0.0.1:8000/docs`; its health check is `/health`.

## Tests and quality checks

Run these checks before making changes:

```cmd
test.bat
```

The script checks backend imports and installed dependency consistency,
compiles Python files, runs Ruff correctness checks, checks frontend JavaScript
syntax when Node.js is installed, and runs the full pytest suite. Tests use
FastAPI TestClient and temporary/in-memory upload data; they do not overwrite
real uploaded datasets. To run pytest alone:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

For the earlier static-frontend workflow, the frontend can also be served
separately while the FastAPI backend is running:

```powershell
python -m http.server 5500 --directory Frontend
```

Open `http://127.0.0.1:5500/`. Styles/scripts use relative asset paths and the
frontend keeps hash-based navigation in this mode while sending API requests
to `http://127.0.0.1:8000`.

When serving `Frontend` through the VS Code preview on port `3002`, open
`http://127.0.0.1:3002/Frontend/index.html` and run the FastAPI backend on
port `8001`; the frontend is configured to send API requests there.

## Troubleshooting

- **Missing virtual environment:** run the one-time setup commands above from
  the project root.
- **Missing dependency:** install the verified environment with
  `.\.venv\Scripts\python.exe -m pip install -r Backend\requirements-lock.txt`.
  Startup reports the failed imports instead of silently reinstalling packages.
- **Port already in use:** stop the other process or choose another
  `AUTOBI_PORT`. `run.bat` prints a `netstat` command to identify the process.
- **Optional MySQL warning:** uploads and analysis work without MySQL. Configure
  `DATABASE_URL` in `Backend/.env` only if metadata persistence is needed; do
  not commit credentials.
- **Offline chart/style assets:** Plotly.js and Bootstrap are loaded from
  external CDNs, so those browser assets require network access.

## Upload and cleaning workflow

Upload a CSV, XLSX, or XLS file from Overview. The Overview first runs the original Day 1
profiling route, which reports row count, column count, missing cells, duplicate
rows, column names/types, and a ten-row preview. Day 1's dashboard recommends
up to three dataset-derived charts: a multicolor category comparison, a
datetime/numeric trend, and a donut chart only when every category fits on it.
It explains when a chart is unsuitable rather than substituting unrelated data.

Day 3 adds numerical descriptive statistics and automatic EDA charts for
numerical distributions, categorical counts, correlations, numeric
relationships, and suitable datetime/numeric series. The **Build a chart**
controls request a compatible histogram, bar, donut, scatter, time-series, or
box chart from FastAPI and render it interactively with Plotly.js. The EDA page
lets the user choose **Original uploaded dataset** or **Cleaned
dataset**. Cleaned becomes selectable only after cleaning succeeds; statistics,
automatic charts, and selected charts then use the exact saved cleaning options.
The original upload and its profiling preview remain unchanged.
Use the sidebar or workflow buttons to move through Overview, Data Cleaning,
EDA, and KPI Dashboard. Each page has its own URL, while client navigation
retains the active dataset without a reload. The browser also saves the upload
and last successful cleaning options in IndexedDB, keyed by a per-tab session
identifier; reloading a page reanalyzes that browser-held file through the
existing FastAPI validation endpoints. The backend does not keep uploaded
datasets in process-global memory or shared server storage.
Visualizations are stacked vertically at full content width with responsive
plot heights, keeping axis labels, hover details, and legends readable on
desktop and mobile. A new upload replaces the previous charts; unsuitable
chart types show an explanation instead of an empty or misleading plot.

From Data Cleaning, choose any optional Day 2 operations and press
**Clean Data** to view before/after metrics, a cleaned-data preview, and EDA
computed again from the cleaned result. The EDA and KPI pages share the
original/cleaned dataset selection; navigating among Overview, Data Cleaning,
EDA, and KPI Dashboard does not discard either version.
CSV and Excel download buttons export that same cleaned data. Cleaning never
modifies the uploaded source. If another upload is rejected or cannot be parsed,
the last successfully analyzed dataset stays selected and usable.
If optional MySQL metadata persistence fails, dataset analysis still succeeds
and the Overview displays a warning; the failure is also logged by the backend.

## Day 4 dynamic KPI dashboard

Open **KPI Dashboard** in the sidebar after uploading a dataset. It starts with
the original file and shares the EDA source selector: selecting Original or
Cleaned updates both EDA and KPI analysis. Cleaned is available only after a
successful cleaning request; the browser re-sends the uploaded file and the
exact cleaning options for each calculation. The FastAPI service does not keep
user datasets in module-level/global state.

KPI cards are data-driven: row count is always available; totals are shown only
for numeric columns whose names identify sales/revenue or profit; average order
value appears only when both a sales/revenue column and an order/invoice ID
column exist and is calculated as sales on rows with a non-missing order ID
divided by the number of distinct non-missing order IDs; unique customer/product
counts require matching columns. For general datasets, average/minimum/maximum
are shown for the first suitable numeric measure. Missing and infinite numeric
values are excluded from numeric calculations, while duplicate rows remain
included unless removal is selected. Each card describes its calculation. No
currency or other unit is inferred.

Category and date controls apply to KPI cards and charts through the same
request. Category charts aggregate identified sales/profit values by sum, or a
general numeric measure by mean; time charts aggregate the selected business
measure by sum and generic measures by mean. If no numeric measure is present,
category and time charts use record counts. Date detection accepts datetime
columns and consistently parseable ISO date strings. Category filter options
are bounded to 100 distinct values and chart categories to the top 10.

All cleaning is opt-in:

| Control | Behavior |
| --- | --- |
| Missing values: Keep unchanged | Default; does not fill or drop anything. |
| Mean | Fills nulls in numeric columns only. Numeric values are not parsed from text. |
| Median | Fills nulls in numeric columns only. |
| Mode | Fills nulls in text/boolean columns using the first most-common value; dates and numeric columns are left alone. |
| Drop rows | Drops rows containing one or more missing cells. |
| Remove duplicate rows | Unchecked by default; drops exact duplicate rows when selected. |
| Standardize column names | Unchecked by default; e.g. `Order Date` becomes `order_date`. Name collisions get a numbered suffix. |

Mean, median, or mode leaves a column unchanged when it has no non-missing
values from which to calculate a fill value; the after-summary makes remaining
missing cells visible.

The app does not request conversion of column values or change their types to
guess what they mean. The parser uses pandas nullable dtypes so CSV integer
columns with missing rows are not first converted to floating point. Mean/median
filling may store a filled numeric column as objects so fractional fills fit
nullable integer columns without rounding existing large integers; source
values themselves are preserved. Excel has limited numeric precision, so
precision-sensitive large integers are written as text cells in Excel
downloads; for exact values already stored in a source workbook, store long
identifiers as text there too. The source upload is not overwritten. The
downloadable file is generated from the same cleaning options shown in the
preview.

Uploads are limited to 25 MiB and 100,000 parsed rows. Larger files are rejected
with an explicit error. Preview tables show the first ten rows.

EDA charts are bounded to at most 80 automatic specifications per report.
Histograms aggregate all finite values into at most 40 bins (the counts sum to
the full number of plotted observations); box summaries and statistics use all
finite values. Scatter and time-series charts use up to 5,000 plotted points,
but their reported correlations and counts use all eligible pairs. Pairwise
correlation/scatter work is limited to the first 20 eligible numeric columns.
The browser displays up to 16 automatic charts per report. The dashboard shows
up to three summary charts. Selected charts are independently validated by the
API; numeric charts omit integers that cannot be represented exactly in the
browser. Numeric summaries exclude infinities, identify finite/non-finite
counts, and preserve exact integer extrema when serializing. String dates are
used for charts only when every non-missing value has an unambiguous ISO-style
date/time representation; source values are not rewritten. Duplicate rows are
counted as uploaded unless the user opts to remove them. Category percentages
exclude missing categories and use all observed categories as their
denominator. Correlation measures association, not causation. Units are not
inferred; labels are taken from column names.

## Day 5: ML predictions and AI insights

The Overview generates deterministic, dataset-based insight cards for
date/numeric trends, strong Pearson correlations, numeric 1.5×IQR outliers,
dominant low-cardinality categories, and missing-value concentrations. Each
card includes a suggested action. These explanations are computed locally
from the uploaded dataframe; no external AI service is called, and
correlation is not presented as causation.

When at least eight finite, varying target values and another varying numeric
feature are available, the Machine Learning panel evaluates a scikit-learn
linear regression. Choose a numeric target; other numeric columns are the
features, missing feature values are imputed from the training rows, and
non-numeric columns are intentionally excluded. The deterministic 75/25
holdout reports MAE, RMSE, and R² (when defined), with an actual-versus-
predicted chart. This is an unseen-row evaluation, not a future-period
forecast. Small, constant, non-numeric-only, or single-numeric-column datasets
show an explanation rather than a misleading model result. Prediction and
insight requests use the same original/cleaned dataset choice and cleaning
options as EDA; uploaded rows are not saved to MySQL.

## FastAPI routes

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/health` | API status; MySQL is optional. |
| POST | `/api/analyze` | Day 1 dataset analysis plus Day 5 `ai_analysis`, dashboard visualizations, and default prediction. |
| POST | `/api/clean` | JSON before/after summaries and a clean-data preview. |
| POST | `/api/clean/download/csv` | Apply the submitted options and stream a CSV. |
| POST | `/api/clean/download/xlsx` | Apply the submitted options and stream an Excel workbook. |
| POST | `/api/eda` | Return numeric statistics and bounded automatic chart specifications. |
| POST | `/api/eda/cleaned` | Return EDA after applying the submitted optional cleaning choices. |
| POST | `/api/eda/chart` | Validate a chart selection and return a Plotly-compatible chart payload. |
| POST | `/api/kpi/dashboard` | Return selected-version KPIs, chart specs, and valid date/category filters. |
| POST | `/api/predictions` | Evaluate a selected numeric target with a held-out linear-regression model. |

The cleaning routes accept multipart fields `file`, `missing_strategy`
(`keep`, `mean`, `median`, `mode`, or `drop_rows`),
`remove_duplicates` (boolean), and `standardize_columns` (boolean). Options
default to `keep`, `false`, and `false`. Invalid extensions, malformed files,
invalid cleaning choices, and limit violations are rejected; upload bytes are
processed in memory and not persisted.

## Important functions

- `read_dataset` validates the filename and size, parses CSV/Excel without an
  extra numeric conversion, and rejects empty or over-limit datasets.
- `analyze` keeps the Day 1 profiling and optional metadata-persistence route.
- `clean_dataframe` copies the input, applies only the selected missing-value
  strategy, optionally removes duplicate rows, and optionally renames columns.
- `summarize_dataframe` computes the row, column, missing-cell, and duplicate
  counts displayed for each version of the dataset.
- `dataframe_preview` creates a JSON-safe ten-row table while retaining
  duplicate headers and exact large-integer display values.
- `prepare_excel_export` writes precision-sensitive large integers as text so
  opening the workbook cannot silently round those exported values.
- `_clean_upload` is shared by the preview and download routes so both apply
  the same cleaning steps to the original upload.
- `clean` returns the before/after report and preview; `download_cleaned_dataset`
  re-applies those options and streams a CSV or XLSX file without saving it.
- `_clean_upload` also reports `removed_duplicate_rows` for the exact number
  removed after the selected missing-value operation.
- `build_eda_report` identifies numeric, categorical, and datetime columns,
  computes finite-value numeric summaries, exact-count histogram bins, Tukey
  box summaries, pairwise correlations and bounded numeric/date charts.
- `build_dashboard_visualizations` selects truthful category counts,
  datetime/numeric trends, and low-cardinality proportions for the main
  dashboard; it returns suitability messages for unavailable chart types.
- `build_selected_chart` checks the selected chart type and exact column names,
  filters unusable values, and returns a safe Plotly.js trace and layout.
- `build_kpi_dashboard` detects supported columns, applies date/category
  filters, and builds explainable KPI cards and bounded chart data from the
  current request's dataframe.
- `build_ai_analysis` summarizes trends, associations, outliers, common
  categories, and missing-value patterns; `build_prediction_report` uses
  scikit-learn with a reproducible holdout and numeric-feature imputation.
- `/api/kpi/dashboard` re-reads each upload and reapplies the submitted cleaning
  options for cleaned-data requests; no uploaded dataframe is stored globally.
- `compute_eda_report` sanitizes the automatic report for JSON responses;
  `/api/eda/cleaned` applies the same optional cleaning settings before building
  a fresh report.
- In the browser, `currentCleaningOptions` and `cleaningFormData` gather the
  user's choices; `cleanDataset` posts them to FastAPI; `renderCleaningSummary`
  and `renderTable` update the page; `downloadCleanedDataset` requests and saves
  the result. `renderEdaReport` builds safe statistics tables and Plotly charts;
  `showPage` switches the dashboard and dedicated EDA views while preserving
  the selected upload; `resizeVisibleCharts` reflows Plotly charts after view or
  viewport changes. `updateChartOptions` offers compatible axes;
  `buildSelectedChart` sends the validated selection to `/api/eda/chart`.
  `refreshKpiDashboard` sends the selected file version and active filters to
  `/api/kpi/dashboard`; `renderKpiDashboard` formats the resulting cards and
  draws responsive Plotly charts.

## Tests

From the project root, run the complete checks with:

```cmd
test.bat
```

Expected results include:

| Test case | Expected result |
| --- | --- |
| Default options | Missing values and input column names remain unchanged. |
| Mean/median | Numeric missing cells are filled; nonnumeric values are not coerced. |
| Mode | Text values are filled; numeric and date values stay as they were. |
| Drop rows | Rows with any missing cells are removed. |
| Duplicate option | Duplicate removal occurs only when selected. |
| Standardize option | Names become unique snake_case only when selected. |
| Large integer preview | Exact display text is preserved beyond JavaScript's safe integer range. |
| Excel integer export | Integers beyond Excel's precision limit are text cells and retain their exact digits. |
| Invalid strategy | The cleaning function rejects unsupported strategy names. |
| Invalid file/options | Unsupported files return HTTP 400; invalid strategies return HTTP 422. |
| Upload limits | Uploads above 25 MiB or 100,000 rows return HTTP 413. |
| Export endpoints | CSV and XLSX downloads contain the selected cleaning result. |
| Numeric statistics | Mean, median, min/max, and sample standard deviation match finite numeric input values; infinite values are called out separately. |
| Dashboard charts | Category bars, exact-share donut charts, and trends appear only when data types and values qualify. |
| Automatic EDA | Exact-count histograms, Tukey box summaries, low-cardinality category counts, Pearson correlation, scatter and time series are generated when reliable. |
| Original/cleaned EDA | The user selects the analyzed version; selected charts apply the same last-successful cleaning options as the cleaned summary and downloads. |
| Selected EDA | Histogram, bar, pie, scatter, line, and box payloads validate the selected dataset, column types, non-finite values, and minimum data counts. |
| EDA limits | Bounded chart counts and point counts; duplicate columns, mixed-type categories, large integers, empty and constant columns are handled explicitly. |
| Cleaned-data EDA | Statistics, charts, and insight cards are recomputed from the requested cleaned dataset. |
| Day 5 insights | Trends, correlations, outliers, category patterns, and missing-value concentrations include suggested actions. |
| ML predictions | Numeric targets are evaluated only with enough varying observations and features; missing values and unsupported targets are handled explicitly. |
| KPI dashboard | Sales, profit, AOV, customer/product counts, and generic numeric stats are included only when supported by column names and values. |
| KPI filters | Date/category filters update metrics and charts using the same filtered rows; unsupported columns/ranges are rejected. |
| KPI source selection | Original/cleaned data is selected in the UI and sent per request; no server-global dataset state is used. |

The Day 1 `DATABASE_URL`/MySQL integration remains optional and is not used by
the Day 2 cleaning routes.

To refresh the exact lock after deliberately changing dependencies, activate
the verified virtual environment and regenerate it from the project root:

```powershell
.\.venv\Scripts\python.exe -m pip freeze | Set-Content Backend\requirements-lock.txt -Encoding ascii
```

Review the diff and rerun `test.bat` after updating the lock.
