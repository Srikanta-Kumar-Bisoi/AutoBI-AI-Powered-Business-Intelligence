@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo AutoBI virtual environment is missing.
    echo Create it and install dependencies with:
    echo   py -3.14 -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -r Backend\requirements-lock.txt
    pause
    exit /b 1
)

"%PYTHON%" -c "import pytest, ruff"
if errorlevel 1 (
    echo Test tools are missing from .venv.
    echo Install the pinned environment with:
    echo   .venv\Scripts\python.exe -m pip install -r Backend\requirements-lock.txt
    pause
    exit /b 1
)

pushd "%~dp0Backend"
echo Checking backend imports...
"%PYTHON%" -c "import app.main"
if errorlevel 1 goto fail

echo Checking dependency consistency...
"%PYTHON%" -m pip check
if errorlevel 1 goto fail

echo Running Python syntax checks...
"%PYTHON%" -m compileall -q app tests
if errorlevel 1 goto fail

echo Running Ruff checks...
"%PYTHON%" -m ruff check --select E4,E7,E9,F app tests
if errorlevel 1 goto fail

where node >nul 2>nul
if not errorlevel 1 (
    echo Checking frontend JavaScript syntax...
    node --check ..\Frontend\script.js
    if errorlevel 1 goto fail
) else (
    echo SKIP: Node.js is not installed; frontend syntax was not checked.
)

echo Running pytest...
"%PYTHON%" -m pytest tests -q
if errorlevel 1 goto fail

popd
echo PASS: syntax, Ruff, and all tests succeeded.
exit /b 0

:fail
set "TEST_EXIT=%ERRORLEVEL%"
popd
echo FAIL: checks stopped with exit code %TEST_EXIT%.
pause
exit /b %TEST_EXIT%
