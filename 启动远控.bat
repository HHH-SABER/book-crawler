@echo off
rem ---------- 远控服务启动 (常驻机用; 手机/外部设备经浏览器访问) ----------
setlocal
cd /d "%~dp0"
set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
    echo [ERROR] .venv not found. Run: python -m venv .venv ^&^& .venv\Scripts\pip.exe install -r requirements.txt
    pause
    exit /b 1
)

rem ---------- deps ----------
"%PYTHON_EXE%" -c "import fastapi, uvicorn" >nul 2>&1
if errorlevel 1 (
    echo [WARN] fastapi/uvicorn missing. Installing from requirements.txt...
    "%PYTHON_EXE%" -m pip install -r requirements.txt
)

rem ---------- env ----------
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set "PYTHONPATH=%~dp0源码"

"%PYTHON_EXE%" -m 远控
rem 守护模式 (脚本/远控守护.bat) 下免暂停, 便于自动重启循环
if not "%远控_无暂停%"=="1" pause
