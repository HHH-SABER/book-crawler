@echo off
REM Launch build_exe.py via venv Python (ASCII-only BAT, encoding safe)
setlocal
chcp 936 >nul 2>&1
cd /d "%~dp0"
title Novel Crawler EXE Build

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
    where python >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] Python not found. Create .venv or install Python 3.10+
        pause
        exit /b 1
    )
    for /f "tokens=*" %%i in ('where python') do set "PY=%%i"
)

"%PY%" "%~dp0build_exe.py"
set EXITCODE=%ERRORLEVEL%

if not "%EXITCODE%"=="0" (
    echo.
    echo [ERROR] Build failed. Exit code %EXITCODE%. Details in build_log.txt
    pause
    exit /b 1
)

echo.
echo Build SUCCESS. Details in build_log.txt
pause
endlocal
