@echo off
chcp 936 >nul
setlocal

cd /d "%~dp0"
title 小说爬虫

rem ========== 检查 Python ==========
set "PYTHON_EXE="
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=.venv\Scripts\python.exe"
if not defined PYTHON_EXE (
    where python >nul 2>&1 && set "PYTHON_EXE=python"
)
if not defined PYTHON_EXE (
    where py >nul 2>&1 && set "PYTHON_EXE=py"
)
if not defined PYTHON_EXE (
    echo [错误] 未检测到 Python，请先安装或创建 .venv 虚拟环境
    pause
    endlocal & exit /b 1
)

rem ========== 确保输出目录存在 ==========
if not exist "抓取结果" mkdir "抓取结果"

rem ========== 判断运行模式 ==========
if "%~1"=="" goto INTERACTIVE

rem ========== 命令行模式：直接透传参数 ==========
rem   用法: 启动爬虫.bat <URL> [--list] [--test] [--output-dir <目录>]
echo [执行] 命令行模式
set "PYTHONIOENCODING=utf-8"
"%PYTHON_EXE%" "爬虫源码\爬虫.py" %*
goto DONE

:INTERACTIVE
echo.
echo   ============ 小说爬虫 ============
echo   Python: %PYTHON_EXE%
echo   输出:   抓取结果echo   ================================
echo.
set "PYTHONIOENCODING=utf-8"
"%PYTHON_EXE%" "爬虫源码\爬虫.py"
goto DONE

:DONE
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
    echo   [成功] 抓取完成！
    echo   [打开] 正在打开抓取结果文件夹...
    explorer "抓取结果"
) else (
    echo   [警告] 程序异常退出，退出码 %RC%
)
echo.
echo   按任意键继续爬取下一本小说，或关闭窗口退出...
pause >nul
goto INTERACTIVE
