@echo off
rem =======================================================================
rem  小说爬虫 GUI 启动脚本（Flet 桌面应用）
rem  功能：检测 Python 环境 → 设置编码 → 创建输出目录 → 启动 GUI
rem =======================================================================
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title 小说爬虫 GUI

rem ---------- 1. 定位 Python ----------
set "PYTHON_EXE="
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
)
if not defined PYTHON_EXE (
    where python >nul 2>&1 && set "PYTHON_EXE=python"
)
if not defined PYTHON_EXE (
    echo [错误] 未检测到 Python 环境。
    echo         请先安装 Python 3.10+，或在项目根创建 .venv 虚拟环境并安装依赖。
    echo.
    echo 如需快速安装：
    echo   python -m venv .venv
    echo   .venv\Scripts\pip.exe install -r requirements.txt
    pause
    exit /b 1
)

rem ---------- 2. 检查 Flet 依赖 ----------
"%PYTHON_EXE%" -c "import flet" >nul 2>&1
if errorlevel 1 (
    echo [警告] 未检测到 Flet 依赖，正在自动安装（首次安装请耐心等待约1~3分钟）...
    "%PYTHON_EXE%" -m pip install flet requests beautifulsoup4 lxml fake-useragent selenium playwright pillow ddddocr opencv-python numpy onnxruntime urllib3 certifi httpx httpcore
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请手动执行：
        echo   .venv\Scripts\pip.exe install -r requirements.txt
        pause
        exit /b 1
    )
)

rem ---------- 3. 环境变量 ----------
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
rem 使用清华镜像作为 Flet 客户端下载回退（国内网络友好）
set "FLUTTER_STORAGE_BASE_URL=https://mirrors.tuna.tsinghua.edu.cn/flutter"

rem ---------- 4. 确保输出目录存在 ----------
if not exist "抓取结果" mkdir "抓取结果"

rem ---------- 5. 启动 GUI ----------
echo [启动] 正在启动小说爬虫 GUI（首次启动 Flet 会下载客户端约10~30秒）...
"%PYTHON_EXE%" "src\gui_app.py"

rem 若异常退出，显示 exit code
echo.
echo [提示] 程序已退出，退出码=%ERRORLEVEL%
pause
