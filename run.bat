@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    where py >nul 2>nul
    if errorlevel 1 (
        echo Python Launcher was not found. Install Python 3.14 and enable the py command.
        pause
        exit /b 1
    )
    echo AutoBI virtual environment is missing.
    echo From this folder, run:
    echo   py -3.14 -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -r Backend\requirements-lock.txt
    pause
    exit /b 1
)

"%PYTHON%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
    echo The .venv Python could not run or is older than Python 3.10.
    echo Recreate it with: py -3.14 -m venv .venv
    pause
    exit /b 1
)

"%PYTHON%" -c "import fastapi, uvicorn, pandas, numpy, sklearn, multipart, jinja2, openpyxl, xlrd, sqlalchemy, pymysql, dotenv"
if errorlevel 1 (
    echo Required application packages are missing from .venv.
    echo Install the pinned environment with:
    echo   .venv\Scripts\python.exe -m pip install -r Backend\requirements-lock.txt
    pause
    exit /b 1
)

if not defined AUTOBI_PORT set "AUTOBI_PORT=8000"
"%PYTHON%" -c "import socket,sys; s=socket.socket(); s.bind(('127.0.0.1',int(sys.argv[1]))); s.close()" "%AUTOBI_PORT%"
if errorlevel 1 (
    echo Port %AUTOBI_PORT% is already in use.
    echo Close the application using that port, or choose another port with:
    echo   set AUTOBI_PORT=8001
    echo   run.bat
    echo To identify the process, run: netstat -ano ^| findstr :%AUTOBI_PORT%
    pause
    exit /b 1
)

echo Starting AutoBI at http://127.0.0.1:%AUTOBI_PORT%/
echo Press Ctrl+C to stop the server.
pushd "%~dp0Backend"
"%PYTHON%" -m uvicorn app.main:app --reload --host 127.0.0.1 --port "%AUTOBI_PORT%"
set "APP_EXIT=%ERRORLEVEL%"
popd
if not "%APP_EXIT%"=="0" (
    echo AutoBI stopped with exit code %APP_EXIT%. Review the error above.
    pause
)
exit /b %APP_EXIT%
