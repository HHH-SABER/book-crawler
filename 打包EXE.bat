@echo off
rem =======================================================================
rem  小说爬虫 - Flet 打包为 Windows EXE
rem  用法：双击本脚本即可。输出目录：dist\
rem  打包前请确保已：1) .venv 装好了 flet 和所有爬虫依赖  2) 代码可正常运行
rem =======================================================================
chcp 936 >nul 2>&1
cd /d "%~dp0"
title 小说爬虫 EXE 打包

rem ---------- 1. 定位 Python ----------
set "PYTHON_EXE="
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
)
if not defined PYTHON_EXE (
    where python >nul 2>&1 && set "PYTHON_EXE=python"
)
if not defined PYTHON_EXE (
    echo [错误] 未找到 Python 环境。请先创建 .venv 或安装 Python。
    pause
    exit /b 1
)

rem ---------- 2. 环境变量（加速下载）----------
rem 使用清华镜像源作为 Flet 客户端的下载回退
set "FLUTTER_STORAGE_BASE_URL=https://mirrors.tuna.tsinghua.edu.cn/flutter"
rem pip 源加速（构建过程中可能缺包）
set "PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

rem ---------- 3. 确保输出目录存在 ----------
if not exist "抓取结果" mkdir "抓取结果"

rem ---------- 4. 清理上次打包产物 ----------
if exist "dist" (
    echo [清理] 删除上次 dist/ 目录...
    rmdir /s /q dist
)

rem ---------- 5. 执行 Flet Pack ----------
rem  参数说明：
rem    -n  生成的 EXE 名称
rem    --product-name  Windows 程序名
rem    --file-description  程序描述
rem    --company-name  公司名（随便写，用于文件属性）
rem    --copyright    版权信息
rem    --version      版本号
rem    --add-data "抓取结果;抓取结果"  把输出目录（占位）带进包
rem    --hidden-import  隐式导入模块（爬虫.py 内部动态 import 的要加上）
rem    最后必须是脚本文件的位置参数（放在所有 -- 选项之前）！

echo.
echo [打包] 开始执行 flet pack（首次会下载 Flet 客户端，约 100MB，请耐心等待 2~8 分钟）...
echo [提示] 若下载失败，请断网重连或配置代理后重试。
echo.

"%PYTHON_EXE%" -m flet pack "爬虫源码\gui_app.py" ^
    -n "小说爬虫" ^
    --product-name "NovelCrawlerGUI" ^
    --file-description "小说爬虫 - 多站点适配 Flet 图形版" ^
    --company-name "NovelCrawler" ^
    --copyright "2026 NovelCrawler" ^
    --version "1.0.0" ^
    --add-data "抓取结果;抓取结果" ^
    --hidden-import flet ^
    --hidden-import flet_core ^
    --hidden-import flet_desktop ^
    --hidden-import requests ^
    --hidden-import bs4 ^
    --hidden-import lxml ^
    --hidden-import fake_useragent ^
    --hidden-import selenium ^
    --hidden-import playwright ^
    --hidden-import PIL ^
    --hidden-import ddddocr ^
    --hidden-import cv2 ^
    --hidden-import numpy ^
    --hidden-import onnxruntime ^
    --hidden-import httpx ^
    --hidden-import httpcore ^
    --hidden-import 爬虫 ^
    --hidden-import sites_config ^
    --hidden-import browser_driver ^
    --hidden-import captcha_module ^
    --hidden-import content_decoder ^
    --hidden-import decrypt_utils ^
    --hidden-import tanmixs_xs ^
    --hidden-import gui_components.task_manager ^
    --hidden-import gui_components.crawl_tab ^
    --hidden-import gui_components.preview_tab ^
    --hidden-import gui_components.config_tab

if errorlevel 1 (
    echo.
    echo [错误] 打包失败！请检查上方日志。
    echo 常见原因：
    echo   1. 缺少依赖 - 请先运行：
    echo      .venv\Scripts\pip.exe install -r requirements.txt
    echo   2. Flet 客户端下载失败 - 可设置代理，或手动把 flet-windows.zip 放到 Flet 缓存目录
    pause
    exit /b 1
)

echo.
echo [完成] 打包成功！产物目录：%CD%\dist
echo        主程序：dist\小说爬虫\小说爬虫.exe
echo.
echo 注意事项：
echo   - 打包后的程序仍依赖系统已安装 Chrome 浏览器（用于 Selenium 渲染）
echo   - 请把整个 dist\小说爬虫\ 文件夹一起分发，不要只拷贝 EXE
echo   - 如缺少 chromedriver，请手动下载对应版本到 EXE 同目录或 PATH 中
pause
