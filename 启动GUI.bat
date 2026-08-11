@echo off
rem =======================================================================
rem  Novel Crawler GUI Launcher (Flet desktop app)
rem  IMPORTANT: This file must stay pure ASCII.
rem  Chinese text BEFORE "chcp 65001" breaks cmd's UTF-8 batch parsing
rem  (line offset corruption -> commands get split into fragments).
rem  =======================================================================
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title Novel Crawler GUI

rem ---------- 1. Locate Python ----------
set "PYTHON_EXE="
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
)
if not defined PYTHON_EXE (
    where python >nul 2>&1 && set "PYTHON_EXE=python"
)
if not defined PYTHON_EXE (
    where py >nul 2>&1 && set "PYTHON_EXE=py"
)
if not defined PYTHON_EXE (
    echo [ERROR] Python not found. Install Python 3.10+ or create .venv first.
    echo         python -m venv .venv
    echo         .venv\Scripts\pip.exe install -r requirements.txt
    pause
    exit /b 1
)

rem ---------- 2. Check Flet dependency ----------
"%PYTHON_EXE%" -c "import flet" >nul 2>&1
if errorlevel 1 (
    echo [WARN] Flet not found. Installing dependencies, first run may take 1-3 minutes...
    "%PYTHON_EXE%" -m pip install flet requests beautifulsoup4 lxml fake-useragent selenium playwright pillow ddddocr opencv-python numpy onnxruntime urllib3 certifi httpx httpcore
    if errorlevel 1 (
        echo [ERROR] Dependency install failed. Run manually:
        echo         .venv\Scripts\pip.exe install -r requirements.txt
        pause
        exit /b 1
    )
)

rem ---------- 3. Environment ----------
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "FLUTTER_STORAGE_BASE_URL=https://mirrors.tuna.tsinghua.edu.cn/flutter"

rem ---------- 4. Output dir is auto-created by Python ----------

rem ---------- 5. Launch GUI ----------
echo [START] Launching GUI...
"%PYTHON_EXE%" "源码\gui_app.py"

echo.
echo [INFO] Program exited, code=%ERRORLEVEL%
pause
