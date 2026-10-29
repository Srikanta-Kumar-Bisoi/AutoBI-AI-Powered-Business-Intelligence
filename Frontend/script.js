
const fileInput = document.getElementById("fileInput");
const uploadBtn = document.getElementById("uploadBtn");
const fileName = document.getElementById("fileName");
const insightText = document.getElementById("insightText");
const analysisStatus = document.getElementById("analysisStatus");
const cleanBtn = document.getElementById("cleanBtn");
const downloadCsvBtn = document.getElementById("downloadCsvBtn");
const downloadExcelBtn = document.getElementById("downloadExcelBtn");
const chartType = document.getElementById("chartType");
const chartColumn = document.getElementById("chartColumn");
const chartXColumn = document.getElementById("chartXColumn");
const buildChartBtn = document.getElementById("buildChartBtn");
const insightList = document.getElementById("insightList");
const predictionTarget = document.getElementById("predictionTarget");
const runPredictionBtn = document.getElementById("runPredictionBtn");
const dashboardPage = document.getElementById("dashboardPage");
const edaPage = document.getElementById("edaPage");
const kpiPage = document.getElementById("kpiPage");
const reportsPage = document.getElementById("reportsPage");
const pageHeading = document.getElementById("pageHeading");
const pageContext = document.getElementById("pageContext");
const edaDataSource = document.getElementById("edaDataSource");
const kpiDataSource = document.getElementById("kpiDataSource");
const kpiDateColumn = document.getElementById("kpiDateColumn");
const kpiDateFrom = document.getElementById("kpiDateFrom");
const kpiDateTo = document.getElementById("kpiDateTo");
const kpiCategoryColumn = document.getElementById("kpiCategoryColumn");
const kpiCategoryValue = document.getElementById("kpiCategoryValue");
const pageLinks = [...document.querySelectorAll(".sidebar-nav [data-page]")];
const routeLinks = [...document.querySelectorAll("a[data-page]")];
const API_BASE_URL = document.body.dataset.apiBase ||
  (window.location.port === "5500"
    ? "http://127.0.0.1:8000"
    : window.location.port === "3002"
      ? "http://127.0.0.1:8001"
      : window.location.origin);
const STATIC_FRONTEND =
  window.location.port === "5500" || window.location.port === "3002";
const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
const WORKSPACE_DB_NAME = "autobi-workspace";
const WORKSPACE_STORE = "datasets";
const WORKSPACE_SESSION_KEY = "autobi-session-id";
const WORKSPACE_REVISION_KEY = "autobi-dataset-revision";
let selectedFile = null;
let lastCleaningOptions = null;
let originalColumnProfiles = [];
let originalEdaReport = null;
let cleanedEdaReport = null;
let originalAiAnalysis = null;
let cleanedAiAnalysis = null;
let currentKpiReport = null;
let kpiRequestVersion = 0;
let predictionRequestVersion = 0;

routeLinks.forEach(link => {
  if (STATIC_FRONTEND) {
    const staticHashes = {
      overview: "#overview",
      cleaning: "#cleaning",
      eda: "#eda-page",
      kpi: "#kpi-dashboard",
      reports: "#reports"
    };
    link.href = staticHashes[link.dataset.page] || "#overview";
  }
  link.addEventListener("click", event => {
    event.preventDefault();
    showPage(link.dataset.page);
    if (STATIC_FRONTEND) {
      window.location.hash = link.hash;
    } else {
      window.history.pushState(
        { page: link.dataset.page },
        "",
        link.getAttribute("href")
      );
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
});

window.addEventListener(STATIC_FRONTEND ? "hashchange" : "popstate", () => {
  showPage(pageFromPath(window.location.pathname));
});

const initialPage = document.body.dataset.initialPage;
showPage(
  ["overview", "cleaning", "eda", "kpi", "reports"].includes(initialPage)
    ? initialPage
    : pageFromPath(window.location.pathname)
);
void restoreWorkspaceOnStartup();

function pageFromPath(path) {
  if (path === "/cleaning") return "cleaning";
  if (path === "/eda") return "eda";
  if (path === "/kpi") return "kpi";
  if (path === "/reports") return "reports";
  if (window.location.hash === "#cleaning") return "cleaning";
  if (window.location.hash === "#eda-page") return "eda";
  if (window.location.hash === "#kpi-dashboard") return "kpi";
  if (window.location.hash === "#reports") return "reports";
  return "overview";
}

function openWorkspaceDatabase() {
  return new Promise((resolve, reject) => {
    if (!window.indexedDB) {
      reject(new Error("IndexedDB is unavailable."));
      return;
    }
    const request = window.indexedDB.open(WORKSPACE_DB_NAME, 1);
    request.onupgradeneeded = () => {
      request.result.createObjectStore(WORKSPACE_STORE);
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(
      request.error || new Error("Could not open browser dataset storage.")
    );
  });
}

async function saveWorkspaceState(state) {
  const sessionId = workspaceSessionId();
  const revision = createWorkspaceId();
  window.sessionStorage.removeItem(WORKSPACE_REVISION_KEY);
  const database = await openWorkspaceDatabase();
  await new Promise((resolve, reject) => {
    const transaction = database.transaction(WORKSPACE_STORE, "readwrite");
    transaction.objectStore(WORKSPACE_STORE).put(
      { ...state, revision },
      sessionId
    );
    transaction.oncomplete = resolve;
    transaction.onerror = () => reject(
      transaction.error || new Error("Could not save the current dataset.")
    );
    transaction.onabort = () => reject(
      transaction.error || new Error("Saving the current dataset was aborted.")
    );
  }).finally(() => database.close());
  window.sessionStorage.setItem(WORKSPACE_REVISION_KEY, revision);
}

async function readWorkspaceState() {
  const sessionId = window.sessionStorage.getItem(WORKSPACE_SESSION_KEY);
  const revision = window.sessionStorage.getItem(WORKSPACE_REVISION_KEY);
  if (!sessionId || !revision) return null;
  const database = await openWorkspaceDatabase();
  const record = await new Promise((resolve, reject) => {
    const transaction = database.transaction(WORKSPACE_STORE, "readonly");
    const request = transaction.objectStore(WORKSPACE_STORE).get(sessionId);
    request.onsuccess = () => resolve(request.result || null);
    request.onerror = () => reject(
      request.error || new Error("Could not read the saved dataset.")
    );
    transaction.oncomplete = () => database.close();
    transaction.onabort = () => {
      database.close();
      reject(transaction.error || new Error("Reading the saved dataset was aborted."));
    };
  });
  return record?.revision === revision ? record : null;
}

function workspaceSessionId() {
  let sessionId = window.sessionStorage.getItem(WORKSPACE_SESSION_KEY);
  if (!sessionId) {
    sessionId = createWorkspaceId();
    window.sessionStorage.setItem(WORKSPACE_SESSION_KEY, sessionId);
  }
  return sessionId;
}

function createWorkspaceId() {
  return window.crypto?.randomUUID
    ? window.crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

async function persistCurrentWorkspace() {
  if (!selectedFile) return;
  try {
    await saveWorkspaceState({
      file: selectedFile,
      cleaningOptions: lastCleaningOptions,
      dataSource: edaDataSource.value
    });
  } catch (error) {
    const message =
      `The selected dataset is active, but browser persistence failed: ${error.message}`;
    document.getElementById("analysisStatus").textContent = message;
    document.getElementById("cleanStatus").textContent = message;
  }
}

async function restoreWorkspaceOnStartup() {
  try {
    const saved = await readWorkspaceState();
    if (!saved?.file) return;
    const restored = await analyzeUploadedFile(saved.file, { persist: false });
    if (!restored) return;
    if (saved.cleaningOptions) {
      document.getElementById("missingStrategy").value =
        saved.cleaningOptions.missing_strategy;
      document.getElementById("removeDuplicates").checked =
        saved.cleaningOptions.remove_duplicates;
      document.getElementById("standardizeColumns").checked =
        saved.cleaningOptions.standardize_columns;
      await cleanDataset({ persist: false });
      if (!lastCleaningOptions) return;
    }
    if (saved.dataSource === "cleaned" && lastCleaningOptions) {
      changeDatasetSource("cleaned");
    }
  } catch (error) {
    document.getElementById("analysisStatus").textContent =
      `Could not restore the saved browser dataset: ${error.message}`;
  }
}

function showPage(page) {
  const showingEda = page === "eda";
  const showingKpi = page === "kpi";
  const showingOverview = page === "overview";
  const showingCleaning = page === "cleaning";
  const showingReports = page === "reports";
  dashboardPage.hidden = showingEda || showingKpi || showingReports;
  edaPage.hidden = !showingEda;
  kpiPage.hidden = !showingKpi;
  reportsPage.hidden = !showingReports;
  document.getElementById("upload").hidden = !showingOverview;
  document.getElementById("analytics").hidden = !showingOverview;
  document.getElementById("charts").hidden =
    !showingOverview ||
    document.getElementById("charts").dataset.hasContent !== "true";
  document.getElementById("preview").hidden =
    !showingOverview ||
    document.getElementById("preview").dataset.hasContent !== "true";
  document.getElementById("cleaning").hidden = !showingCleaning;
  document.getElementById("cleanedPreview").hidden =
    !showingCleaning ||
    document.getElementById("cleanedPreview").dataset.hasContent !== "true";
  document.getElementById("insights").hidden = !showingOverview;
  document.getElementById("predictions").hidden = !showingOverview;
  document.getElementById("overviewActions").hidden = !showingOverview;
  document.getElementById("cleaningActions").hidden = !showingCleaning;
  document.getElementById("edaActions").hidden = !showingEda;
  document.getElementById("kpiActions").hidden = !showingKpi;
  const pageDetails = {
    overview: ["Overview", "WORKSPACE / OVERVIEW"],
    cleaning: ["Data Cleaning", "WORKSPACE / CLEANING"],
    eda: ["Exploratory Data Analysis", "WORKSPACE / EXPLORATION"],
    kpi: ["Dynamic KPI Dashboard", "WORKSPACE / PERFORMANCE"],
    reports: ["Reports", "WORKSPACE / REPORTING"]
  }[page] || ["Overview", "WORKSPACE / OVERVIEW"];
  pageHeading.textContent = pageDetails[0];
  pageContext.textContent = pageDetails[1];
  pageLinks.forEach(link => {
    const active = link.dataset.page === page;
    link.classList.toggle("active", active);
    if (active) {
      link.setAttribute("aria-current", "page");
    } else {
      link.removeAttribute("aria-current");
    }
  });
  resizeVisibleCharts();
}

function chartHeightForViewport() {
  if (window.innerWidth <= 420) return 320;
  if (window.innerWidth <= 768) return 360;
  return 440;
}

function resizeVisibleCharts() {
  if (!window.Plotly) return;
  window.requestAnimationFrame(() => {
    window.requestAnimationFrame(() => {
      document.querySelectorAll(".dataset-chart.js-plotly-plot").forEach(plot => {
        if (plot.getClientRects().length === 0) return;
        window.Plotly.relayout(plot, {
          height: chartHeightForViewport(),
          width: plot.clientWidth
        });
        window.Plotly.Plots.resize(plot);
      });
    });
  });
}

let chartResizeTimer;
window.addEventListener("resize", () => {
  window.clearTimeout(chartResizeTimer);
  chartResizeTimer = window.setTimeout(resizeVisibleCharts, 120);
});

[kpiDateColumn, kpiDateFrom, kpiDateTo, kpiCategoryColumn, kpiCategoryValue]
  .forEach(control => control.addEventListener("change", refreshKpiDashboard));

uploadBtn.addEventListener("click", () => {
  fileInput.click();
});

fileInput.addEventListener("change", async () => {
  const [file] = fileInput.files;
  if (file) await analyzeUploadedFile(file);
});

async function analyzeUploadedFile(file, { persist = true } = {}) {
  const supportedFile = /\.(csv|xlsx|xls)$/i.test(file.name);
  if (!supportedFile) {
    reportUploadRejection(
      file,
      "Unsupported file type. Choose a CSV, XLSX or XLS file."
    );
    document.getElementById("cleanStatus").textContent =
      "Upload rejected: unsupported file type. The previously analyzed dataset remains selected.";
    fileInput.value = "";
    return;
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    reportUploadRejection(
      file,
      "Choose a file smaller than or equal to 25 MiB."
    );
    document.getElementById("cleanStatus").textContent =
      "Upload rejected: file exceeds 25 MiB. The previously analyzed dataset remains selected.";
    fileInput.value = "";
    return;
  }

  const previousFileLabel = fileName.textContent;
  const formData = new FormData();
  formData.append("file", file);
  let serverAcceptedUpload = false;
  let analyzedFilename = file.name;
  uploadBtn.disabled = true;
  cleanBtn.disabled = true;
  fileName.textContent = `Uploading: ${file.name}`;
  analysisStatus.textContent = "Analyzing dataset…";
  insightText.textContent = "Analysis is in progress.";
  let persistenceWarning = "";

  try {
    const response = await fetch(`${API_BASE_URL}/api/analyze`, {
      method: "POST",
      body: formData
    });
    const result = await readJsonResponse(response, "dataset analysis");
    if (!response.ok) {
      throw new Error(
        result.detail || `The server rejected this upload (HTTP ${response.status}).`
      );
    }

    serverAcceptedUpload = true;
    analyzedFilename = result.filename || file.name;
    selectedFile = file;
    resetCleaningResults();
    resetEdaResults();
    if (persist) {
      try {
        await saveWorkspaceState({
          file,
          cleaningOptions: null,
          dataSource: "original"
        });
      } catch (error) {
        persistenceWarning =
          `Analysis succeeded, but browser persistence failed: ${error.message}`;
      }
    }
    document.getElementById("records").textContent =
      result.records.toLocaleString();
    document.getElementById("columns").textContent =
      result.column_count.toLocaleString();
    document.getElementById("missing").textContent =
      result.missing_values.toLocaleString();
    document.getElementById("duplicates").textContent =
      result.duplicate_rows.toLocaleString();

    fileName.textContent = `Analyzed: ${result.filename}`;
    insightText.textContent = result.summary;
    analysisStatus.textContent = result.storage_persisted
      ? "Analysis complete · metadata saved to MySQL."
      : result.storage_warning
        ? `Analysis complete · ${result.storage_warning}`
        : "Analysis complete · database storage is optional and not configured.";
    renderDashboardVisualizations(result.dashboard_visualizations);
    renderPreview(result.preview, result.columns);
    originalColumnProfiles = result.columns;
    originalEdaReport = result.eda;
    originalAiAnalysis = result.ai_analysis;
    renderAiAnalysis(originalAiAnalysis);
    renderEdaReport(result.eda, "eda");
    document.getElementById("edaDataControls").hidden = false;
    edaDataSource.value = "original";
    showEdaDataset("original");
    document.getElementById("chartBuilder").hidden = false;
    document.getElementById("edaEmptyState").hidden = true;
    updateChartOptions();
    document.getElementById("cleanStatus").textContent =
      persistenceWarning || "Choose optional cleaning operations, then select Clean.";
    if (persist && !window.indexedDB) {
      document.getElementById("cleanStatus").textContent =
        "Analysis succeeded, but IndexedDB is unavailable. Keep this tab open to retain the selected dataset.";
    }
    cleanBtn.disabled = false;
    await refreshKpiDashboard();
    return true;
  } catch (error) {
    const message = error instanceof TypeError
      ? `Could not reach the analysis API at ${API_BASE_URL}. Start the backend and try again.`
      : error.message;
    fileName.textContent = serverAcceptedUpload
      ? `Analyzed: ${analyzedFilename}`
      : selectedFile
        ? previousFileLabel
        : `Upload failed: ${message}`;
    analysisStatus.textContent = serverAcceptedUpload
      ? `Upload succeeded, but dashboard rendering failed: ${message}`
      : selectedFile
        ? `Upload failed: ${message} The previously analyzed dataset remains selected.`
        : `Upload failed: ${message}`;
    insightText.textContent = selectedFile
      ? `${message} The previously analyzed dataset remains selected.`
      : message;
    document.getElementById("cleanStatus").textContent = selectedFile
      ? `${message} The previously analyzed dataset remains selected.`
      : message;
    return false;
  } finally {
    uploadBtn.disabled = false;
    cleanBtn.disabled = !selectedFile;
    fileInput.value = "";
  }
}

async function readJsonResponse(response, operation) {
  const body = await response.text();
  let result;
  try {
    result = body ? JSON.parse(body) : null;
  } catch {}

  if (result && typeof result === "object") {
    return result;
  }
  if (response.ok) {
    throw new Error(
      `The server returned an invalid response while ${operation} (HTTP ${response.status}).`
    );
  }
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("text/html")) {
    const url = new URL(response.url);
    return {
      detail:
        `The server returned an HTML error (HTTP ${response.status}) from ${url.origin}${url.pathname}. ` +
        "Check that the API base URL points to AutoBI's FastAPI server and that the route is registered."
    };
  }
  const detail = body.trim().slice(0, 300);
  return {
    detail: detail
      ? `The server returned HTTP ${response.status}: ${detail}`
      : `The server rejected the request while ${operation} (HTTP ${response.status}) without a readable error message.`
  };
}

function reportUploadRejection(file, reason) {
  const hasSelectedDataset = Boolean(selectedFile);
  if (!hasSelectedDataset) {
    fileName.textContent = reason;
  }
  analysisStatus.textContent = hasSelectedDataset
    ? `Upload rejected · ${reason} The previously analyzed dataset remains selected.`
    : "Upload rejected.";
  insightText.textContent = hasSelectedDataset
    ? `${reason} The previously analyzed dataset remains selected.`
    : `${reason} File rejected: ${file.name}`;
}

cleanBtn.addEventListener("click", () => cleanDataset());
runPredictionBtn.addEventListener("click", runPrediction);
downloadCsvBtn.addEventListener("click", () => downloadCleanedDataset("csv"));
downloadExcelBtn.addEventListener("click", () => downloadCleanedDataset("xlsx"));
chartType.addEventListener("change", () => {
  document.getElementById("selectedChart").hidden = true;
  document.getElementById("selectedChartStatus").textContent = "";
  updateChartOptions();
});
chartColumn.addEventListener("change", updateChartOptions);
chartXColumn.addEventListener("change", updateChartOptions);
buildChartBtn.addEventListener("click", buildSelectedChart);
edaDataSource.addEventListener("change", () =>
  changeDatasetSource(edaDataSource.value)
);
kpiDataSource.addEventListener("change", () =>
  changeDatasetSource(kpiDataSource.value)
);

function changeDatasetSource(source) {
  edaDataSource.value = source;
  kpiDataSource.value = source;
  kpiDateColumn.value = "";
  kpiDateFrom.value = "";
  kpiDateTo.value = "";
  kpiCategoryColumn.value = "";
  kpiCategoryValue.value = "";
  kpiCategoryValue.disabled = true;
  showEdaDataset(source);
  showAiAnalysis(source);
  refreshKpiDashboard();
  void persistCurrentWorkspace();
}

function currentCleaningOptions() {
  return {
    missing_strategy: document.getElementById("missingStrategy").value,
    remove_duplicates: document.getElementById("removeDuplicates").checked,
    standardize_columns: document.getElementById("standardizeColumns").checked
  };
}

function cleaningFormData(file, options) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("missing_strategy", options.missing_strategy);
  formData.append("remove_duplicates", String(options.remove_duplicates));
  formData.append("standardize_columns", String(options.standardize_columns));
  return formData;
}

async function runPrediction() {
  if (!selectedFile || !predictionTarget.value) return;

  const source = edaDataSource.value;
  const formData = source === "cleaned"
    ? cleaningFormData(selectedFile, lastCleaningOptions)
    : new FormData();
  if (source !== "cleaned") formData.append("file", selectedFile);
  formData.append("target_column", predictionTarget.value);
  formData.append("data_source", source);

  const requestVersion = ++predictionRequestVersion;
  runPredictionBtn.disabled = true;
  document.getElementById("predictionResults").hidden = true;
  document.getElementById("predictionStatus").textContent =
    `Training and evaluating a model for ${predictionTarget.value}…`;
  try {
    const response = await fetch(`${API_BASE_URL}/api/predictions`, {
      method: "POST",
      body: formData
    });
    const result = await readJsonResponse(response, "prediction");
    if (!response.ok) {
      throw new Error(
        result.detail || `The server rejected this prediction (HTTP ${response.status}).`
      );
    }
    if (requestVersion !== predictionRequestVersion) return;
    renderPrediction(result);
  } catch (error) {
    if (requestVersion !== predictionRequestVersion) return;
    const message = error instanceof TypeError
      ? `Could not reach the analysis API at ${API_BASE_URL}. Start the backend and try again.`
      : error.message;
    document.getElementById("predictionStatus").textContent =
      `Prediction failed: ${message}`;
  } finally {
    if (requestVersion === predictionRequestVersion) {
      runPredictionBtn.disabled =
        !selectedFile || predictionTarget.disabled || !predictionTarget.value;
    }
  }
}

async function responseError(response) {
  const result = await response.json();
  return result.detail || "The server could not process this request.";
}

async function cleanDataset({ persist = true } = {}) {
  if (!selectedFile) return;

  const options = currentCleaningOptions();
  cleanBtn.disabled = true;
  downloadCsvBtn.disabled = true;
  downloadExcelBtn.disabled = true;
  document.getElementById("cleanStatus").textContent = "Cleaning dataset…";

  try {
    const response = await fetch(`${API_BASE_URL}/api/clean`, {
      method: "POST",
      body: cleaningFormData(selectedFile, options)
    });
    if (!response.ok) {
      throw new Error(await responseError(response));
    }
    const result = await response.json();
    renderCleaningSummary("before", result.before);
    renderCleaningSummary("after", result.after);
    renderTable(
      result.preview,
      "cleanedPreviewHead",
      "cleanedPreviewBody",
      "cleanedPreviewCount",
      "cleanedPreviewSchemaHead",
      "cleanedPreviewSchemaBody"
    );
    document.getElementById("cleaningResults").hidden = false;
    document.getElementById("cleanedPreview").dataset.hasContent = "true";
    document.getElementById("cleanedPreview").hidden =
      pageFromPath(window.location.pathname) !== "cleaning";
    document.getElementById("removedDuplicates").textContent =
      `Duplicate rows removed: ${result.removed_duplicate_rows.toLocaleString()}.`;
    document.getElementById("cleanStatus").textContent =
      "Cleaning complete. Download buttons use these exact options.";
    lastCleaningOptions = options;
    if (persist) await persistCurrentWorkspace();
    downloadCsvBtn.disabled = false;
    downloadExcelBtn.disabled = false;
    try {
      const edaResponse = await fetch(`${API_BASE_URL}/api/eda/cleaned`, {
        method: "POST",
        body: cleaningFormData(selectedFile, options)
      });
      if (!edaResponse.ok) {
        throw new Error(await responseError(edaResponse));
      }
      const cleanedEda = await edaResponse.json();
      renderEdaReport(cleanedEda, "cleanedEda");
      cleanedAiAnalysis = cleanedEda.ai_analysis;
      const cleanedOption = edaDataSource.querySelector(
        'option[value="cleaned"]'
      );
      cleanedOption.disabled = false;
      cleanedOption.hidden = false;
      const kpiCleanedOption = kpiDataSource.querySelector(
        'option[value="cleaned"]'
      );
      kpiCleanedOption.disabled = false;
      kpiCleanedOption.hidden = false;
      showEdaDataset(edaDataSource.value);
      showAiAnalysis(edaDataSource.value);
      await refreshKpiDashboard();
    } catch (error) {
      document.getElementById("cleanStatus").textContent =
        `Cleaning succeeded, but refreshed EDA failed: ${error.message}`;
      clearCleanedEdaReport();
    }
  } catch (error) {
    const message = error instanceof TypeError
      ? `Could not reach the analysis API at ${API_BASE_URL}. Start the backend and try again.`
      : error.message;
    document.getElementById("cleanStatus").textContent =
      `Cleaning failed: ${message}`;
  } finally {
    cleanBtn.disabled = !selectedFile;
  }
}

function renderCleaningSummary(prefix, summary) {
  document.getElementById(`${prefix}Rows`).textContent =
    summary.row_count.toLocaleString();
  document.getElementById(`${prefix}Columns`).textContent =
    summary.column_count.toLocaleString();
  document.getElementById(`${prefix}Missing`).textContent =
    summary.missing_cells.toLocaleString();
  document.getElementById(`${prefix}Duplicates`).textContent =
    summary.duplicate_rows.toLocaleString();
}

async function downloadCleanedDataset(format) {
  if (!selectedFile || !lastCleaningOptions) return;

  const button = format === "csv" ? downloadCsvBtn : downloadExcelBtn;
  button.disabled = true;
  document.getElementById("cleanStatus").textContent =
    `Preparing cleaned ${format.toUpperCase()} download…`;

  try {
    const response = await fetch(
      `${API_BASE_URL}/api/clean/download/${format}`,
      {
        method: "POST",
        body: cleaningFormData(selectedFile, lastCleaningOptions)
      }
    );
    if (!response.ok) {
      throw new Error(await responseError(response));
    }
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const baseName = selectedFile.name.replace(/\.[^.]+$/, "");
    link.href = objectUrl;
    link.download = `${baseName}_cleaned.${format}`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    document.getElementById("cleanStatus").textContent =
      `Cleaned ${format.toUpperCase()} downloaded.`;
  } catch (error) {
    const message = error instanceof TypeError
      ? `Could not reach the analysis API at ${API_BASE_URL}. Start the backend and try again.`
      : error.message;
    document.getElementById("cleanStatus").textContent =
      `Download failed: ${message}`;
  } finally {
    button.disabled = false;
  }
}

function resetCleaningResults() {
  lastCleaningOptions = null;
  document.getElementById("cleaningResults").hidden = true;
  document.getElementById("cleanedPreview").hidden = true;
  document.getElementById("cleanedPreview").dataset.hasContent = "false";
  document.getElementById("cleanedEda").hidden = true;
  document.getElementById("cleanedPreviewHead").replaceChildren();
  document.getElementById("cleanedPreviewBody").replaceChildren();
  document.getElementById("cleanedPreviewSchemaHead").replaceChildren();
  document.getElementById("cleanedPreviewSchemaBody").replaceChildren();
  document.getElementById("removedDuplicates").textContent = "";
  document.getElementById("cleanStatus").textContent =
    "Preparing dataset for cleaning…";
  downloadCsvBtn.disabled = true;
  downloadExcelBtn.disabled = true;
}

function resetEdaResults() {
  originalColumnProfiles = [];
  originalEdaReport = null;
  cleanedEdaReport = null;
  resetAiAnalysis();
  document.getElementById("edaDataControls").hidden = true;
  edaDataSource.value = "original";
  kpiDataSource.value = "original";
  const cleanedOption = edaDataSource.querySelector('option[value="cleaned"]');
  cleanedOption.disabled = true;
  cleanedOption.hidden = true;
  const kpiCleanedOption = kpiDataSource.querySelector(
    'option[value="cleaned"]'
  );
  kpiCleanedOption.disabled = true;
  kpiCleanedOption.hidden = true;
  document.getElementById("edaDataSourceDescription").textContent =
    "Statistics and charts use the original uploaded data.";
  document.getElementById("eda").hidden = true;
  document.getElementById("chartBuilder").hidden = true;
  document.getElementById("selectedChart").hidden = true;
  document.getElementById("selectedChart").replaceChildren();
  document.getElementById("selectedChartStatus").textContent = "";
  document.getElementById("edaStatsHead").replaceChildren();
  document.getElementById("edaStatsBody").replaceChildren();
  document.getElementById("edaChartGrid").replaceChildren();
  document.getElementById("chartGrid").replaceChildren();
  document.getElementById("dashboardChartMessages").replaceChildren();
  document.getElementById("charts").hidden = true;
  document.getElementById("charts").dataset.hasContent = "false";
  document.getElementById("cleanedEda").hidden = true;
  document.getElementById("edaEmptyState").hidden = false;
  resetKpiDashboard();
}

function clearCleanedEdaReport() {
  cleanedEdaReport = null;
  cleanedAiAnalysis = null;
  const cleanedOption = edaDataSource.querySelector('option[value="cleaned"]');
  cleanedOption.disabled = true;
  cleanedOption.hidden = true;
  const kpiCleanedOption = kpiDataSource.querySelector(
    'option[value="cleaned"]'
  );
  kpiCleanedOption.disabled = true;
  kpiCleanedOption.hidden = true;
  edaDataSource.value = "original";
  kpiDataSource.value = "original";
  document.getElementById("cleanedEda").hidden = true;
  if (originalEdaReport) {
    showEdaDataset("original");
    showAiAnalysis("original");
  }
}

function showEdaDataset(source) {
  const useCleaned = source === "cleaned" && Boolean(cleanedEdaReport);
  const activeReport = useCleaned ? cleanedEdaReport : originalEdaReport;
  document.getElementById("eda").hidden = useCleaned || !originalEdaReport;
  document.getElementById("cleanedEda").hidden = !useCleaned;
  document.getElementById("edaEmptyState").hidden = Boolean(activeReport);
  document.getElementById("edaDataSourceDescription").textContent = useCleaned
    ? describeAppliedCleaningOptions()
    : "Statistics and charts use the original uploaded data.";
  updateChartOptions(activeReport?.datetime_columns || []);
  resizeVisibleCharts();
}

function showAiAnalysis(source) {
  predictionRequestVersion += 1;
  const report = source === "cleaned" && cleanedAiAnalysis
    ? cleanedAiAnalysis
    : originalAiAnalysis;
  renderAiAnalysis(report);
}

function resetAiAnalysis() {
  originalAiAnalysis = null;
  cleanedAiAnalysis = null;
  predictionRequestVersion += 1;
  insightText.textContent = "Upload a dataset to see data-driven insights.";
  insightList.replaceChildren();
  predictionTarget.replaceChildren();
  const option = document.createElement("option");
  option.value = "";
  option.textContent = "Upload a dataset to find suitable targets";
  predictionTarget.appendChild(option);
  predictionTarget.disabled = true;
  runPredictionBtn.disabled = true;
  document.getElementById("predictionStatus").textContent =
    "Regression is available when the dataset has enough numeric observations and features.";
  document.getElementById("predictionResults").hidden = true;
  document.getElementById("predictionMetrics").replaceChildren();
  document.getElementById("predictionExplanation").textContent = "";
  const predictionChart = document.getElementById("predictionChart");
  predictionChart.replaceChildren();
  predictionChart.hidden = true;
}

function renderAiAnalysis(report) {
  insightList.replaceChildren();
  if (!report) {
    insightText.textContent =
      "Automatic insights are unavailable for this dataset.";
    renderPrediction({
      available: false,
      message: "No prediction report was returned by the analysis API."
    });
    predictionTarget.replaceChildren();
    predictionTarget.disabled = true;
    runPredictionBtn.disabled = true;
    return;
  }

  insightText.textContent = report.summary || "Dataset insights are ready.";
  (report.insights || []).forEach(insight => {
    const item = document.createElement("li");
    item.className = "insight-item";
    const heading = document.createElement("h6");
    heading.textContent = insight.title;
    const detail = document.createElement("p");
    detail.className = "muted";
    detail.textContent = insight.detail;
    const action = document.createElement("p");
    action.className = "muted";
    action.textContent = `Suggested action: ${insight.action}`;
    item.append(heading, detail, action);
    insightList.appendChild(item);
  });

  const targets = report.prediction_targets || [];
  fillSelect(predictionTarget, targets, report.prediction?.target || "");
  if (!targets.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No suitable numeric target";
    predictionTarget.appendChild(option);
  }
  predictionTarget.disabled = targets.length === 0;
  runPredictionBtn.disabled = !selectedFile || targets.length === 0;
  renderPrediction(report.prediction);
}

function renderPrediction(report) {
  const status = document.getElementById("predictionStatus");
  const results = document.getElementById("predictionResults");
  const metrics = document.getElementById("predictionMetrics");
  const explanation = document.getElementById("predictionExplanation");
  const chart = document.getElementById("predictionChart");
  metrics.replaceChildren();
  chart.replaceChildren();
  chart.hidden = true;

  if (!report?.available) {
    results.hidden = true;
    status.textContent = report?.message ||
      "A prediction is unavailable for this dataset.";
    return;
  }

  const metricValues = [
    ["Mean absolute error", report.metrics.mae],
    ["Root mean squared error", report.metrics.rmse],
    ["R²", report.metrics.r_squared],
    ["Validation rows", report.validation_rows]
  ];
  metricValues.forEach(([label, value], index) => {
    const card = document.createElement("article");
    card.className = `kpi-card kpi-accent-${(index % 5) + 1}`;
    const heading = document.createElement("p");
    heading.className = "kpi-label";
    heading.textContent = label;
    const display = document.createElement("strong");
    display.className = "kpi-value";
    display.textContent = value === null
      ? "Not defined"
      : Number(value).toLocaleString(undefined, { maximumFractionDigits: 4 });
    card.append(heading, display);
    metrics.appendChild(card);
  });
  explanation.textContent =
    `${report.algorithm} for ${report.target}, using ${report.features.join(", ")}. ` +
    report.explanation;
  results.hidden = false;
  status.textContent =
    `Prediction complete: ${report.validation_rows} held-out rows were evaluated.`;

  if (!window.Plotly) {
    status.textContent += " Metrics are available, but Plotly did not load for the chart.";
    return;
  }
  const actual = report.chart.actual;
  const predicted = report.chart.predicted;
  const minimum = Math.min(...actual, ...predicted);
  const maximum = Math.max(...actual, ...predicted);
  chart.hidden = false;
  window.Plotly.newPlot(
    chart,
    [
      {
        x: actual,
        y: predicted,
        mode: "markers",
        type: "scatter",
        name: "Held-out rows",
        text: report.chart.row_numbers.map(row => `Source row ${row}`),
        marker: { color: "#638bff", size: 10 }
      },
      {
        x: [minimum, maximum],
        y: [minimum, maximum],
        mode: "lines",
        type: "scatter",
        name: "Ideal prediction",
        line: { color: "#45c4a0", dash: "dash" }
      }
    ],
    {
      ...plotlyLayout("Actual vs. predicted", "Actual target", "Predicted target"),
      showlegend: true,
      hovermode: "closest"
    },
    { responsive: true, displayModeBar: false }
  ).catch(error => {
    chart.hidden = true;
    status.textContent =
      `Prediction metrics are available, but the chart could not be rendered: ${error.message}`;
  });
}

function resetKpiDashboard() {
  currentKpiReport = null;
  kpiRequestVersion += 1;
  document.getElementById("kpiWorkspace").hidden = true;
  document.getElementById("kpiEmptyState").hidden = false;
  document.getElementById("kpiCards").replaceChildren();
  document.getElementById("kpiCharts").replaceChildren();
  document.getElementById("kpiMessages").replaceChildren();
  document.getElementById("kpiMessages").hidden = true;
  document.getElementById("kpiStatus").textContent = "";
  fillSelect(kpiDateColumn, [], "");
  kpiDateColumn.insertAdjacentHTML(
    "afterbegin",
    '<option value="">No date filter</option>'
  );
  fillSelect(kpiCategoryColumn, [], "");
  kpiCategoryColumn.insertAdjacentHTML(
    "afterbegin",
    '<option value="">All categories</option>'
  );
  fillSelect(kpiCategoryValue, [], "");
  kpiCategoryValue.insertAdjacentHTML(
    "afterbegin",
    '<option value="">All values</option>'
  );
  kpiDateFrom.value = "";
  kpiDateTo.value = "";
  kpiDateFrom.disabled = true;
  kpiDateTo.disabled = true;
  kpiCategoryValue.disabled = true;
}

async function refreshKpiDashboard() {
  if (!selectedFile) {
    resetKpiDashboard();
    return;
  }

  const requestVersion = ++kpiRequestVersion;
  const source = kpiDataSource.value;
  const formData = new FormData();
  formData.append("file", selectedFile);
  formData.append("data_source", source);
  if (source === "cleaned") {
    if (!lastCleaningOptions) {
      document.getElementById("kpiStatus").textContent =
        "Clean the dataset before selecting the cleaned version.";
      return;
    }
    formData.append("missing_strategy", lastCleaningOptions.missing_strategy);
    formData.append(
      "remove_duplicates",
      String(lastCleaningOptions.remove_duplicates)
    );
    formData.append(
      "standardize_columns",
      String(lastCleaningOptions.standardize_columns)
    );
  }
  if (kpiDateColumn.value) {
    formData.append("date_column", kpiDateColumn.value);
    if (kpiDateFrom.value) formData.append("date_from", kpiDateFrom.value);
    if (kpiDateTo.value) formData.append("date_to", kpiDateTo.value);
  }
  if (kpiCategoryColumn.value) {
    formData.append("category_column", kpiCategoryColumn.value);
    formData.append("category_value", kpiCategoryValue.value);
  }

  document.getElementById("kpiEmptyState").hidden = true;
  document.getElementById("kpiWorkspace").hidden = false;
  document.getElementById("kpiStatus").textContent =
    `Calculating KPIs for the ${source} dataset…`;
  document.getElementById("kpiCards").replaceChildren();
  document.getElementById("kpiCharts").replaceChildren();
  try {
    const response = await fetch(`${API_BASE_URL}/api/kpi/dashboard`, {
      method: "POST",
      body: formData
    });
    if (!response.ok) throw new Error(await responseError(response));
    const report = await response.json();
    if (requestVersion !== kpiRequestVersion) return;
    currentKpiReport = report;
    populateKpiFilters(report);
    renderKpiDashboard(report);
  } catch (error) {
    if (requestVersion !== kpiRequestVersion) return;
    const message = error instanceof TypeError
      ? `Could not reach the analysis API at ${API_BASE_URL}. Start the backend and try again.`
      : error.message;
    document.getElementById("kpiStatus").textContent =
      `KPI calculation failed: ${message}`;
    document.getElementById("kpiCards").replaceChildren();
    document.getElementById("kpiCharts").replaceChildren();
    document.getElementById("kpiMessages").replaceChildren();
  }
}

function populateKpiFilters(report) {
  const filters = report.filters;
  const currentDate = kpiDateColumn.value;
  const dateNames = filters.date_columns;
  const selectedDate = dateNames.includes(currentDate)
    ? currentDate
    : dateNames[0] || "";
  fillSelect(kpiDateColumn, dateNames, selectedDate);
  kpiDateColumn.insertAdjacentHTML(
    "afterbegin",
    '<option value="">No date filter</option>'
  );
  kpiDateColumn.value = selectedDate;

  const dateRange = filters.date_ranges[selectedDate];
  kpiDateFrom.disabled = !dateRange;
  kpiDateTo.disabled = !dateRange;
  kpiDateFrom.min = dateRange?.min || "";
  kpiDateFrom.max = dateRange?.max || "";
  kpiDateTo.min = dateRange?.min || "";
  kpiDateTo.max = dateRange?.max || "";
  if (
    !dateRange ||
    kpiDateFrom.value < dateRange.min ||
    kpiDateFrom.value > dateRange.max
  ) {
    kpiDateFrom.value = "";
  }
  if (
    !dateRange ||
    kpiDateTo.value < dateRange.min ||
    kpiDateTo.value > dateRange.max
  ) {
    kpiDateTo.value = "";
  }

  const categoryOptions = filters.category_columns;
  const categoryNames = categoryOptions.map(option => option.name);
  const selectedCategory = categoryNames.includes(kpiCategoryColumn.value)
    ? kpiCategoryColumn.value
    : "";
  fillSelect(kpiCategoryColumn, categoryNames, selectedCategory);
  kpiCategoryColumn.insertAdjacentHTML(
    "afterbegin",
    '<option value="">All categories</option>'
  );
  kpiCategoryColumn.value = selectedCategory;
  const selectedCategoryOptions = categoryOptions.find(
    option => option.name === selectedCategory
  );
  const priorValue = kpiCategoryValue.value;
  fillSelect(
    kpiCategoryValue,
    selectedCategoryOptions?.values || [],
    priorValue
  );
  kpiCategoryValue.insertAdjacentHTML(
    "afterbegin",
    '<option value="">All values</option>'
  );
  if (
    selectedCategoryOptions?.values.includes(priorValue)
  ) {
    kpiCategoryValue.value = priorValue;
  } else {
    kpiCategoryValue.value = "";
  }
  kpiCategoryValue.disabled = !selectedCategoryOptions;
}

function renderKpiDashboard(report) {
  const cardContainer = document.getElementById("kpiCards");
  const messageContainer = document.getElementById("kpiMessages");
  const chartContainer = document.getElementById("kpiCharts");
  cardContainer.replaceChildren();
  messageContainer.replaceChildren();
  chartContainer.replaceChildren();

  report.cards.forEach((metric, index) => {
    const card = document.createElement("article");
    card.className = `kpi-card kpi-accent-${index % 6}`;
    card.title = metric.definition;
    const label = document.createElement("p");
    label.className = "kpi-label";
    label.textContent = metric.label;
    const value = document.createElement("strong");
    value.className = "kpi-value";
    value.textContent = formatKpiValue(metric.value);
    const definition = document.createElement("p");
    definition.className = "kpi-definition muted";
    definition.textContent = metric.definition;
    card.append(label, value, definition);
    cardContainer.appendChild(card);
  });

  (report.messages || []).forEach(text => {
    const message = document.createElement("p");
    message.className = "mb-1";
    message.textContent = text;
    messageContainer.appendChild(message);
  });
  messageContainer.hidden = report.messages.length === 0;
  document.getElementById("kpiStatus").textContent =
    `${report.dataset_label} · ${report.row_count.toLocaleString()} rows after active filters.`;

  if (!window.Plotly && report.charts.length) {
    const message = document.createElement("p");
    message.textContent = "Plotly did not load, so KPI charts cannot be rendered.";
    messageContainer.appendChild(message);
    messageContainer.hidden = false;
    return;
  }
  report.charts.forEach((spec, index) =>
    renderKpiChart(chartContainer, spec, `kpi-chart-${index}`)
  );
}

function formatKpiValue(value) {
  if (typeof value === "string") return value;
  if (!Number.isFinite(Number(value))) return "—";
  return Number(value).toLocaleString(undefined, {
    maximumFractionDigits: Number.isInteger(Number(value)) ? 0 : 2
  });
}

function renderKpiChart(container, spec, id) {
  const card = document.createElement("article");
  card.className = "chart-card";
  const title = document.createElement("h4");
  title.className = "chart-title";
  title.textContent = spec.title;
  const explanation = document.createElement("p");
  explanation.className = "chart-explanation muted";
  explanation.textContent = spec.explanation;
  const plot = document.createElement("div");
  plot.className = "dataset-chart";
  plot.id = id;
  card.append(title, explanation, plot);
  container.appendChild(card);

  const trace = spec.type === "bar"
    ? {
        type: "bar",
        x: spec.labels,
        y: spec.values,
        marker: { color: spec.colors },
        hovertemplate: `${spec.x_label}: %{x}<br>${spec.y_label}: %{y:,.6g}<extra></extra>`
      }
    : {
        type: "scatter",
        mode: "lines+markers",
        x: spec.x,
        y: spec.y,
        line: { color: "#45c4a0", width: 3 },
        marker: { color: "#45c4a0" },
        hovertemplate: `${spec.x_label}: %{x}<br>${spec.y_label}: %{y:,.6g}<extra></extra>`
      };
  window.Plotly.newPlot(
    plot,
    [trace],
    {
      ...plotlyLayout("", spec.x_label, spec.y_label, spec.type),
      hovermode: "x unified",
      showlegend: false
    },
    { responsive: true, displayModeBar: false }
  );
}

function describeAppliedCleaningOptions() {
  const options = lastCleaningOptions;
  const missingStrategies = {
    keep: "missing values kept unchanged",
    mean: "numeric missing values filled with mean",
    median: "numeric missing values filled with median",
    mode: "categorical missing values filled with mode",
    drop_rows: "rows with missing values dropped"
  };
  const duplicateHandling = options.remove_duplicates
    ? "duplicate rows removed"
    : "duplicate rows retained";
  const columnHandling = options.standardize_columns
    ? "column names standardized"
    : "column names unchanged";
  return `Cleaned data: ${missingStrategies[options.missing_strategy]}, ` +
    `${duplicateHandling}, ${columnHandling}. The original upload is unchanged.`;
}

function renderPreview(rows, columnProfiles) {
  const columns = rows.length ? Object.keys(rows[0]) : [];
  renderTable(
    {
      columns,
      column_types: columnProfiles.map(column => ({
        name: column.name,
        dtype: column.dtype
      })),
      rows: rows.map(row => columns.map(column => row[column]))
    },
    "previewHead",
    "previewBody",
    "previewCount",
    "previewSchemaHead",
    "previewSchemaBody"
  );
  const previewSection = document.getElementById("preview");
  previewSection.dataset.hasContent = String(rows.length > 0);
  previewSection.hidden = rows.length === 0 ||
    pageFromPath(window.location.pathname) !== "overview";
}

function renderTable(
  preview,
  headId,
  bodyId,
  countId,
  schemaHeadId,
  schemaBodyId
) {
  const head = document.getElementById(headId);
  const body = document.getElementById(bodyId);
  const schemaHead = document.getElementById(schemaHeadId);
  const schemaBody = document.getElementById(schemaBodyId);
  head.replaceChildren();
  body.replaceChildren();
  schemaHead.replaceChildren();
  schemaBody.replaceChildren();

  const headerRow = document.createElement("tr");
  preview.columns.forEach(column => {
    const cell = document.createElement("th");
    cell.scope = "col";
    cell.textContent = column;
    headerRow.appendChild(cell);
  });
  head.appendChild(headerRow);

  preview.rows.forEach(row => {
    const tableRow = document.createElement("tr");
    row.forEach(value => {
      const cell = document.createElement("td");
      cell.textContent = value === null ? "" : String(value);
      tableRow.appendChild(cell);
    });
    body.appendChild(tableRow);
  });

  if (preview.column_types) {
    const schemaHeader = document.createElement("tr");
    ["Column", "Pandas dtype"].forEach(label => {
      const cell = document.createElement("th");
      cell.scope = "col";
      cell.textContent = label;
      schemaHeader.appendChild(cell);
    });
    schemaHead.appendChild(schemaHeader);

    preview.column_types.forEach(column => {
      const tableRow = document.createElement("tr");
      [column.name, column.dtype].forEach(value => {
        const cell = document.createElement("td");
        cell.textContent = value;
        tableRow.appendChild(cell);
      });
      schemaBody.appendChild(tableRow);
    });
  }

  document.getElementById(countId).textContent =
    `(first ${preview.rows.length} rows)`;
}

function renderDashboardVisualizations(report) {
  const chartGrid = document.getElementById("chartGrid");
  const messages = document.getElementById("dashboardChartMessages");
  chartGrid.replaceChildren();
  messages.replaceChildren();
  const charts = report?.charts || [];
  const reasons = report?.messages || [];
  if (charts.length && window.Plotly) {
    charts.slice(0, 3).forEach((spec, index) => {
      renderChartCard(chartGrid, spec, `dashboard-chart-${index}`);
    });
  } else if (charts.length) {
    reasons.unshift("Plotly did not load, so dashboard charts cannot be rendered.");
  }
  reasons.forEach(reason => {
    const message = document.createElement("p");
    message.className = "muted mb-1";
    message.textContent = reason;
    messages.appendChild(message);
  });
  messages.hidden = reasons.length === 0;
  const chartSection = document.getElementById("charts");
  const hasContent = charts.length > 0 || reasons.length > 0;
  chartSection.dataset.hasContent = String(hasContent);
  chartSection.hidden = !hasContent ||
    pageFromPath(window.location.pathname) !== "overview";
}

function renderEdaReport(report, prefix) {
  const section = document.getElementById(prefix);
  const statsHead = document.getElementById(`${prefix}StatsHead`);
  const statsBody = document.getElementById(`${prefix}StatsBody`);
  const chartGrid = document.getElementById(`${prefix}ChartGrid`);
  const chartMessage = document.getElementById(`${prefix}ChartMessage`);
  statsHead.replaceChildren();
  statsBody.replaceChildren();
  chartGrid.replaceChildren();
  chartMessage.hidden = true;

  const statistics = report?.statistics || [];
  const charts = report?.charts || [];
  const datetimeColumns = report?.datetime_columns || [];
  const messages = report?.messages || [];
  chartMessage.textContent = "";
  if (statistics.length) {
    const header = document.createElement("tr");
    [
      "Column",
      "Pandas dtype",
      "Finite n",
      "Missing",
      "Non-finite",
      "Mean",
      "Median",
      "Minimum",
      "Maximum",
      "Std. deviation"
    ].forEach(label => {
      const cell = document.createElement("th");
      cell.scope = "col";
      cell.textContent = label;
      header.appendChild(cell);
    });
    statsHead.appendChild(header);

    statistics.forEach(statistic => {
      const row = document.createElement("tr");
      [
        statistic.name,
        statistic.dtype,
        formatStatistic(statistic.count),
        formatStatistic(statistic.missing_values),
        formatStatistic(statistic.non_finite_values),
        formatStatistic(statistic.mean),
        formatStatistic(statistic.median),
        formatStatistic(statistic.min),
        formatStatistic(statistic.max),
        formatStatistic(statistic.standard_deviation)
      ].forEach(value => {
        const cell = document.createElement("td");
        cell.textContent = value;
        row.appendChild(cell);
      });
      statsBody.appendChild(row);
    });
  }

  if (charts.length && window.Plotly) {
    const visibleCharts = charts.slice(0, 16);
    visibleCharts.forEach((spec, index) => {
      renderChartCard(chartGrid, spec, `${prefix}-chart-${index}`);
    });
    const chartNotes = messages.slice();
    if (charts.length > visibleCharts.length) {
      chartNotes.push(
        `Showing ${visibleCharts.length} of ${charts.length} automatic charts. ` +
        "Use Build a chart to explore other columns."
      );
    }
    chartMessage.textContent = chartNotes.join(" ");
    chartMessage.hidden = chartNotes.length === 0;
  } else if (charts.length) {
    chartMessage.textContent =
      "Charts are unavailable because the Plotly visualization library did not load.";
    chartMessage.hidden = false;
  } else if (messages.length) {
    chartMessage.textContent = messages.join(" ");
    chartMessage.hidden = false;
  } else {
    chartMessage.textContent =
      "No suitable automatic charts were found for this dataset.";
    chartMessage.hidden = false;
  }

  section.hidden =
    statistics.length === 0 && charts.length === 0 && messages.length === 0;
  if (prefix === "eda") {
    originalEdaReport = report;
  } else if (prefix === "cleanedEda") {
    cleanedEdaReport = report;
  }
}

function formatStatistic(value) {
  if (typeof value === "string") return value;
  if (value === null || value === undefined || !Number.isFinite(Number(value))) {
    return "—";
  }
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: 6 });
}

function plotlyTraceFromSpec(spec) {
  if (spec.type === "histogram") {
    const width = spec.bin_edges?.length > 1
      ? spec.bin_edges[1] - spec.bin_edges[0]
      : undefined;
    return {
      type: "bar",
      x: spec.x,
      y: spec.y,
      width,
      marker: {
        color: spec.x.map((_, index) =>
          dashboardPalette[index % dashboardPalette.length]
        )
      },
      hovertemplate:
        `${spec.x_label}: %{x:,.6g}<br>Observations: %{y:,}<extra></extra>`
    };
  }
  if (spec.type === "bar") {
    return {
      type: "bar",
      x: spec.labels,
      y: spec.values,
      marker: { color: spec.colors || chartPalette(spec.values.length) },
      hovertemplate: "%{x}: %{y:,} records<extra></extra>"
    };
  }
  if (spec.type === "pie") {
    return {
      type: "pie",
      labels: spec.labels,
      values: spec.values,
      hole: 0.48,
      sort: false,
      marker: { colors: spec.colors || chartPalette(spec.values.length) },
      hovertemplate: "%{label}: %{value:,} records (%{percent})<extra></extra>"
    };
  }
  if (spec.type === "heatmap") {
    return {
      type: "heatmap",
      x: spec.x,
      y: spec.y,
      z: spec.z,
      colorscale: "Blues",
      zmin: -1,
      zmax: 1,
      hovertemplate: "%{y} × %{x}<br>Pearson r: %{z:.3f}<extra></extra>"
    };
  }
  if (spec.type === "box") {
    const box = spec.box;
    return {
      type: "box",
      x: [spec.column],
      q1: [box.q1],
      median: [box.median],
      q3: [box.q3],
      lowerfence: [box.lower_fence],
      upperfence: [box.upper_fence],
      mean: [box.mean],
      customdata: [[box.count, box.outlier_count]],
      boxpoints: false,
      name: spec.column,
      hovertemplate:
        `${spec.column}<br>Q1: %{q1:,.6g}<br>Median: %{median:,.6g}` +
        "<br>Q3: %{q3:,.6g}<br>n: %{customdata[0]:,}" +
        "<br>Outliers: %{customdata[1]:,}<extra></extra>"
    };
  }
  if (spec.type === "scatter") {
    return {
      type: "scatter",
      mode: "markers",
      name: spec.columns.join(" vs "),
      x: spec.x,
      y: spec.y,
      marker: { color: "#bd7cf6", opacity: 0.7 },
      hovertemplate:
        `${spec.x_label}: %{x:,.6g}<br>${spec.y_label}: %{y:,.6g}` +
        "<extra></extra>"
    };
  }
  return {
    type: "scatter",
    mode: "lines+markers",
    name: spec.y_label,
    x: spec.x,
    y: spec.y,
    customdata: spec.customdata,
    line: { color: "#45c4a0" },
    hovertemplate:
      `${spec.x_label}: %{x}<br>${spec.y_label}: %{y:,.6g}` +
      "<br>Observations: %{customdata:,}<extra></extra>"
  };
}

const dashboardPalette = [
  "#4f8df7", "#ef8354", "#45c4a0", "#bd7cf6", "#f1c453",
  "#f06c9b", "#46b6d5", "#a3c85b", "#e788c8", "#8a9cf5"
];

function chartPalette(count) {
  return Array.from({ length: count }, (_, index) =>
    dashboardPalette[index % dashboardPalette.length]
  );
}

function renderChartCard(grid, spec, id) {
  const card = document.createElement("article");
  card.className = "chart-card";
  const heading = document.createElement("h6");
  heading.className = "chart-title";
  heading.textContent = spec.title;
  const explanation = document.createElement("p");
  explanation.className = "chart-explanation muted";
  explanation.textContent = spec.explanation || "";
  const plot = document.createElement("div");
  plot.className = "dataset-chart";
  plot.id = id;
  card.append(heading, explanation, plot);
  grid.appendChild(card);
  window.Plotly.newPlot(
    plot,
    [plotlyTraceFromSpec(spec)],
    plotlyLayout("", spec.x_label, spec.y_label, spec.type),
    { responsive: true, displayModeBar: false }
  );
}

function plotlyLayout(title, xLabel, yLabel, chartType = "") {
  return {
    title: { text: title, font: { color: "#f1f5f9" } },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { color: "#9ba9c1" },
    margin: { t: 48, r: 20, b: 55, l: 55 },
    height: chartHeightForViewport(),
    autosize: true,
    showlegend: chartType === "pie",
    legend: { orientation: "h", font: { color: "#9ba9c1" } },
    xaxis: { title: xLabel, gridcolor: "#28334b" },
    yaxis: { title: yLabel, gridcolor: "#28334b" }
  };
}

function updateChartOptions(reportedDateColumns = null) {
  const chartKind = chartType.value;
  const selectedReport = edaDataSource.value === "cleaned" && cleanedEdaReport
    ? cleanedEdaReport
    : originalEdaReport;
  const numericColumns = (selectedReport?.statistics || [])
    .filter(statistic => statistic.finite_count > 0 && statistic.chart_supported)
    .map(statistic => statistic.name);
  const categoricalColumns = (selectedReport?.charts || [])
    .filter(spec => spec.type === "bar")
    .map(spec => spec.column);
  const datetimeColumns = reportedDateColumns ||
    selectedReport?.datetime_columns ||
    originalColumnProfiles
      .filter(profile => /datetime64|^date/i.test(profile.dtype))
      .map(profile => profile.name);
  const isPairChart = chartKind === "scatter" || chartKind === "line";
  const primaryOptions = chartKind === "bar" || chartKind === "pie"
    ? categoricalColumns
    : numericColumns;
  const previousColumn = chartColumn.value;
  fillSelect(chartColumn, primaryOptions, previousColumn);
  document.getElementById("chartColumnLabel").textContent =
    isPairChart ? "Y-axis / value" : "Column";

  const xGroup = document.getElementById("chartXColumnGroup");
  xGroup.hidden = !isPairChart;
  if (isPairChart) {
    const xOptions = chartKind === "line"
      ? datetimeColumns
      : numericColumns.filter(name => name !== chartColumn.value);
    fillSelect(chartXColumn, xOptions, chartXColumn.value);
    document.getElementById("chartXColumnLabel").textContent =
      chartKind === "line" ? "Time (X-axis)" : "X-axis";
  } else {
    chartXColumn.replaceChildren();
  }

  const hasSelection = Boolean(chartColumn.value) &&
    (!isPairChart || Boolean(chartXColumn.value));
  buildChartBtn.disabled = !selectedFile || !hasSelection;
  if (!hasSelection) {
    document.getElementById("selectedChartStatus").textContent =
      "No compatible columns are available for this chart type.";
  } else if (
    document.getElementById("selectedChartStatus").textContent.startsWith(
      "No compatible columns"
    )
  ) {
    document.getElementById("selectedChartStatus").textContent = "";
  }
}

function fillSelect(select, values, preferredValue) {
  select.replaceChildren();
  values.forEach(value => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  });
  if (values.includes(preferredValue)) {
    select.value = preferredValue;
  } else if (values.length) {
    select.value = values[0];
  }
}

async function buildSelectedChart() {
  if (!selectedFile || !chartColumn.value) return;

  const formData = new FormData();
  formData.append("file", selectedFile);
  formData.append("chart_type", chartType.value);
  formData.append("column", chartColumn.value);
  const source = edaDataSource.value;
  formData.append("data_source", source);
  if (source === "cleaned") {
    const options = lastCleaningOptions;
    formData.append("missing_strategy", options.missing_strategy);
    formData.append("remove_duplicates", String(options.remove_duplicates));
    formData.append("standardize_columns", String(options.standardize_columns));
  }
  if (chartType.value === "scatter" || chartType.value === "line") {
    formData.append("x_column", chartXColumn.value);
  }
  buildChartBtn.disabled = true;
  document.getElementById("selectedChartStatus").textContent =
    "Generating chart…";
  try {
    const response = await fetch(`${API_BASE_URL}/api/eda/chart`, {
      method: "POST",
      body: formData
    });
    if (!response.ok) {
      throw new Error(await responseError(response));
    }
    const result = await response.json();
    const container = document.getElementById("selectedChart");
    container.hidden = false;
    if (!window.Plotly) {
      throw new Error("Plotly did not load, so this chart cannot be rendered.");
    }
    await window.Plotly.newPlot(
      container,
      result.chart.data,
      {
        ...plotlyLayout(
          result.chart.layout.title?.text || "Selected chart",
          result.chart.layout.xaxis?.title?.text || "",
          result.chart.layout.yaxis?.title?.text || ""
        ),
        ...result.chart.layout
      },
      { responsive: true, displayModeBar: false }
    );
    document.getElementById("selectedChartStatus").textContent =
      source === "cleaned"
        ? "Chart generated from the selected cleaned dataset; the original upload remains unchanged."
        : "Chart generated from the original uploaded dataset.";
  } catch (error) {
    document.getElementById("selectedChart").hidden = true;
    document.getElementById("selectedChartStatus").textContent =
      `Could not generate chart: ${error.message}`;
  } finally {
    updateChartOptions();
  }
}
