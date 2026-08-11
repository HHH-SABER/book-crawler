@echo off
rem =======================================================================
rem  Novel Crawler Launcher (CLI)
rem  IMPORTANT: pure ASCII only + CRLF. No Chinese characters allowed -
rem  cmd corrupts batch parsing with mixed encodings after "chcp 65001".
rem  Chinese filenames are handled by 源码\启动器.py (Python, UTF-8 safe).
rem  =======================================================================
chcp 65001 >nul
setlocal

cd /d "%~dp0"
title Novel Crawler

rem ---------- 1. Locate Python ----------
set "PYTHON_EXE="
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=.venv\Scripts\python.exe"
if not defined PYTHON_EXE (
    where python >nul 2>&1 && set "PYTHON_EXE=python"
)
if not defined PYTHON_EXE (
    where py >nul 2>&1 && set "PYTHON_EXE=py"
)
if not defined PYTHON_EXE (
    echo [ERROR] Python not found. Create .venv first:
    echo         python -m venv .venv
    pause
    endlocal & exit /b 1
)

rem ---------- 2. Mode dispatch (output dir is auto-created by Python) ----------
if "%~1"=="" goto INTERACTIVE

echo [EXEC] Command line mode
set "PYTHONIOENCODING=utf-8"
"%PYTHON_EXE%" "源码\启动器.py" %*
goto DONE

:INTERACTIVE
echo.
echo   ============ Novel Crawler ============
echo   Python: %PYTHON_EXE%
echo   Output: auto (project folder)
echo   =======================================
echo.
set "PYTHONIOENCODING=utf-8"
"%PYTHON_EXE%" "源码\启动器.py"
goto DONE

:DONE
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
    echo   [OK] Done. Output saved in project folder.
) else (
    echo   [WARN] Program exited with code %RC%
)
echo.
echo   Press any key to crawl the next book, or close this window to exit...
pause >nul
goto INTERACTIVE
