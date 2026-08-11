# Novel Crawler EXE Build (PowerShell 5 compatible)
$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot

Write-Host "==================== Novel Crawler EXE Build ====================" -ForegroundColor Cyan

# 1) Find Flet CLI (flet.exe)
$FLET = $null
if (Test-Path ".venv\Scripts\flet.exe") {
    $FLET = (Resolve-Path ".venv\Scripts\flet.exe").Path
} else {
    $c = Get-Command flet -ErrorAction SilentlyContinue
    if ($c) { $FLET = $c.Source }
}
if (-not $FLET) {
    Write-Host "[ERROR] flet.exe not found. Install with:  .venv\Scripts\pip.exe install flet" -ForegroundColor Red
    Read-Host "Enter to exit"
    Pop-Location
    exit 1
}
Write-Host ("[OK] Flet CLI: " + $FLET) -ForegroundColor Green

# 2) Env (mirror)
$env:FLUTTER_STORAGE_BASE_URL = "https://mirrors.tuna.tsinghua.edu.cn/flutter"
$env:PIP_INDEX_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

# 3) Output dir
if (-not (Test-Path "抓取结果")) { New-Item -ItemType Directory -Path "抓取结果" | Out-Null }

# 4) Clean previous
if (Test-Path "dist") {
    Write-Host "[CLEAN] Removing previous dist/..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force "dist"
}

# 5) Args (each element = one argv token)
$packArgs = @(
    "pack",
    "爬虫源码\gui_app.py",
    "-n", "小说爬虫",
    "--product-name", "NovelCrawlerGUI",
    "--file-description", "Novel Crawler GUI",
    "--company-name", "NovelCrawler",
    "--copyright", "2026 NovelCrawler",
    "--version", "1.0.0",
    "--add-data", "抓取结果;抓取结果"
)

Write-Host ""
Write-Host "[BUILD] flet pack started. First build downloads Flet client (~100MB, 2-8 min)." -ForegroundColor Cyan
Write-Host ""

& $FLET @packArgs
$code = $LASTEXITCODE

if ($code -ne 0) {
    Write-Host ""
    Write-Host ("[ERROR] Build failed. Exit code " + $code) -ForegroundColor Red
    Write-Host "  Missing deps ->  .venv\Scripts\pip.exe install -r requirements.txt"
    Write-Host "  Flet download stuck -> reconnect network / set HTTP_PROXY"
    Read-Host "Enter to exit"
    Pop-Location
    exit 1
}

Write-Host ""
Write-Host "[SUCCESS] Build finished!" -ForegroundColor Green
Write-Host ("  Folder : " + (Join-Path $PWD "dist"))
Write-Host ("  Exe    : " + (Join-Path $PWD "dist\小说爬虫\小说爬虫.exe"))
Write-Host ""
Write-Host "Notes:"
Write-Host "  - Program still requires Chrome installed (Selenium anti-bot bypass)"
Write-Host "  - Distribute the ENTIRE  dist\小说爬虫\  folder, not only the .exe"
Write-Host "  - Missing chromedriver? Place it next to the .exe or on PATH"
Write-Host ""
Pop-Location
Read-Host "Enter to exit"
