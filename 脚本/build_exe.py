# -*- coding: utf-8 -*-
"""
Novel Crawler EXE Build (Python -> flet pack)
UTF-8 encoded; no encoding ambiguity, runs flet pack via subprocess.
Double-click 打包EXE.bat  (or:  .venv\\Scripts\\python.exe build_exe.py)
"""
import os, sys, subprocess, shutil, time
from pathlib import Path

# 安全: 使用 Path.resolve() 规范化脚本所在目录, 再上溯到项目根,
# 保证 ROOT/LOG 均为规范化绝对路径, 不含 ../ 穿越
ROOT = str(Path(__file__).resolve().parent.parent)  # 脚本/ 的上级 = 项目根
os.chdir(ROOT)

LOG = os.path.join(ROOT, "build_log.txt")
log_lines = []

def log(msg=""):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    log_lines.append(line)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def banner(msg):
    log("=" * 60)
    log(msg)
    log("=" * 60)

# --- init log
from pathlib import Path as _Path
_Path(LOG).write_text(
    f"==== BUILD STARTED {time.strftime('%Y-%m-%d %H:%M:%S')} ====\n",
    encoding="utf-8")

banner("Novel Crawler EXE Build")

# --- 1) find flet.exe
flet_candidates = [
    os.path.join(ROOT, ".venv", "Scripts", "flet.exe"),
    shutil.which("flet"),
]
flet_exe = next((p for p in flet_candidates if p and os.path.isfile(p)), None)
if not flet_exe:
    log("[ERROR] flet.exe not found. Install deps first:")
    log("         .venv\\Scripts\\pip.exe install -r requirements.txt")
    sys.exit(1)
log(f"[OK] Flet CLI : {flet_exe}")

# --- 2) ensure Flet client is downloaded & extracted (sandbox can't write home dirs)
VIEW_DIR = os.path.join(ROOT, "_flet_client")
FLET_VIEW_EXE = os.path.join(VIEW_DIR, "flet.exe")
if not os.path.isfile(FLET_VIEW_EXE):
    log("[STEP] Flet client not pre-cached. Running ensure_flet_cache.py...")
    cache_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ensure_flet_cache.py")
    rc = subprocess.call([sys.executable, cache_script])
    if rc != 0 or not os.path.isfile(FLET_VIEW_EXE):
        log(f"[ERROR] Failed to provision Flet client (exit={rc}). See build_log.txt + console above.")
        sys.exit(2)
    log("[OK] Flet client provisioned.")
else:
    log(f"[OK] Flet client pre-cached @ {VIEW_DIR}")

# Inject FLET_VIEW_PATH so flet pack / flet_desktop never tries ~/.flet/client/
os.environ["FLET_VIEW_PATH"] = VIEW_DIR
log(f"[ENV] FLET_VIEW_PATH={VIEW_DIR}")

basic_env = {
    "FLUTTER_STORAGE_BASE_URL": "https://mirrors.tuna.tsinghua.edu.cn/flutter",
    "PIP_INDEX_URL":              "https://pypi.tuna.tsinghua.edu.cn/simple",
    "PYTHONUTF8":                 "1",
    "PYTHONIOENCODING":           "utf-8",
}
for k, v in basic_env.items():
    os.environ[k] = v
    log(f"[ENV] {k}={v}")

# --- 3) ensure output dir exists (required for runtime, not bundled)
out_dir = os.path.join(ROOT, "抓取结果")
os.makedirs(out_dir, exist_ok=True)
log(f"[DIR] 抓取结果 dir ready")

# --- 4) clean previous dist/ 和 build/
# 必须预先删掉 build/: 否则 flet pack 会交互询问 "Do you want to delete
# build directory? (y/n)", 子进程无 stdin 直接 EOFError 崩溃 (静默失败)
dist = os.path.join(ROOT, "dist")
if os.path.isdir(dist):
    log("[CLEAN] Remove previous dist/")
    shutil.rmtree(dist, ignore_errors=True)
build_dir = os.path.join(ROOT, "build")
if os.path.isdir(build_dir):
    log("[CLEAN] Remove previous build/")
    shutil.rmtree(build_dir, ignore_errors=True)

# --- 5) arguments (one list element = one argv token)
script_path = os.path.join(ROOT, "源码", "gui_app.py")
exe_name    = "小说爬虫"
# 关键：把 Flet client 打进 EXE（flet pack 不会自动做这件事）
# 同时把站点配置和验证码配置的默认模板打进去（首次运行时拷到 BASE_DIR）
flet_client_dir = os.path.join(ROOT, "_flet_client")
sites_config_src = os.path.join(ROOT, "源码", "站点配置.json")
captcha_config_src = os.path.join(ROOT, "配置", "captcha_config.json")

add_data_list = []
# Flet client（必须）
if os.path.isdir(flet_client_dir):
    add_data_list.append(f"{flet_client_dir}:flet_client")
    log(f"[OK] Bundling Flet client from {flet_client_dir}")
else:
    log("[ERROR] _flet_client/ not found! Run ensure_flet_cache.py first.")
    sys.exit(3)
# 站点配置默认模板（可选）
if os.path.isfile(sites_config_src):
    add_data_list.append(f"{sites_config_src}:.")
    log(f"[OK] Bundling 站点配置.json")
# 验证码配置默认模板（可选）
if os.path.isfile(captcha_config_src):
    add_data_list.append(f"{captcha_config_src}:.")
    log(f"[OK] Bundling captcha_config.json")
# ddddocr 模型（WAF 图片验证码识别必需；onnx 模型不会被 PyInstaller 自动收集，
# 缺包时 EXE 内报 模型文件不存在: common_old.onnx，识别失败导致 401 0章）
ddddocr_dir = os.path.join(ROOT, ".venv", "Lib", "site-packages", "ddddocr")
if os.path.isdir(ddddocr_dir):
    add_data_list.append(f"{ddddocr_dir}:ddddocr")
    log(f"[OK] Bundling ddddocr models from {ddddocr_dir}")
else:
    log("[ERROR] ddddocr not installed! Run .venv\\Scripts\\pip.exe install -r requirements.txt")
    sys.exit(4)

cmd = [
    flet_exe,
    "pack",
    script_path,
    "-n", exe_name,
    "--product-name", "NovelCrawlerGUI",
    "--file-description", "Novel Crawler GUI",
    "--company-name", "NovelCrawler",
    "--copyright", "2026 NovelCrawler",
    "--product-version", "1.0.0",
    "--file-version", "1.0.0.0",
]
# 应用图标 (存在时使用)
icon_path = os.path.join(ROOT, "脚本", "图标.ico")
if os.path.isfile(icon_path):
    cmd.extend(["-i", icon_path])
    log(f"[INFO] icon   = {icon_path}")
for ad in add_data_list:
    cmd.extend(["--add-data", ad])
# selenium 子模块为动态导入，PyInstaller 静态分析收集不全会导致 EXE 内报
# No module named 'selenium.webdriver.chrome.webdriver'（Selenium 兜底失效）
selenium_hidden_imports = [
    "selenium.webdriver.chrome.webdriver",
    "selenium.webdriver.chrome.service",
    "selenium.webdriver.chrome.options",
    "selenium.webdriver.common.by",
    "selenium.webdriver.common.action_chains",
    "selenium.webdriver.common.keys",
    "selenium.webdriver.support.ui",
    "selenium.webdriver.support.expected_conditions",
]
for hi in selenium_hidden_imports:
    cmd.extend(["--hidden-import", hi])
cmd.extend(["-y", "-v"])

log(f"[INFO] script = {script_path}")
log(f"[INFO] exe    = {exe_name}")
log(f"[INFO] data   = {', '.join(add_data_list)}")
log("[BUILD] flet pack starting. First build downloads ~100MB, expect 2-8 min...")
log("")

# --- 6) run, stream output to both console and log
proc = subprocess.Popen(
    cmd,
    cwd=ROOT,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    bufsize=1,
    universal_newlines=True,
    errors="replace",
    encoding="utf-8",
)
assert proc.stdout is not None
for line in proc.stdout:
    line = line.rstrip("\n")
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
proc.wait()
code = proc.returncode

log("")
log(f"==== BUILD FINISHED exit={code} {time.strftime('%Y-%m-%d %H:%M:%S')} ====")

if code != 0:
    log(f"[ERROR] Build FAILED (exit={code}). Full output saved to build_log.txt.")
    log("  Common fixes:")
    log("    - Missing deps   : .venv\\Scripts\\pip.exe install -r requirements.txt")
    log("    - Flet client download stuck  : reconnect network or set HTTP_PROXY env var")
    sys.exit(code)

log("[SUCCESS] Build finished OK!")
# flet pack 可能传 --onefile (旧默认 in 0.86) 或 onedir。
# 两处都查一下，把真实产物挑出来给用户看
onedir_exe = os.path.join(dist, exe_name, f"{exe_name}.exe")
onefile_exe = os.path.join(dist, f"{exe_name}.exe")
final_exe, final_exe_dir, mode = "", "", ""
if os.path.isfile(onefile_exe):
    final_exe, final_exe_dir, mode = onefile_exe, dist, "ONEFILE"
elif os.path.isfile(onedir_exe):
    final_exe, final_exe_dir, mode = onedir_exe, os.path.join(dist, exe_name), "ONEDIR"
else:
    final_exe, final_exe_dir, mode = onedir_exe, os.path.join(dist, exe_name), "UNKNOWN"
size_mb = (os.path.getsize(final_exe) / 1024 / 1024) if os.path.isfile(final_exe) else 0
log(f"  Mode          : {mode}")
log(f"  Output folder : {final_exe_dir}")
log(f"  Executable    : {final_exe}")
if size_mb:
    log(f"  Size          : {size_mb:.2f} MB")
log("")
log("Notes:")
log("  - Chrome must be installed on target machine (Selenium anti-bot bypass)")
if mode == "ONEFILE":
    log(f"  - SINGLE FILE distribution: copy {final_exe} directly")
    log("    First launch extracts ~200MB to %TEMP%\\_MEIxxxxxx (deleted on exit);")
    log("    抓取结果/ / 站点配置.json / captcha_config.json are placed NEXT TO the .exe.")
elif mode == "ONEDIR":
    log(f"  - Distribute the ENTIRE folder: {final_exe_dir}   (not only the .exe)")
log("  - Missing chromedriver? Place it next to .exe or on PATH")
log("  - Customize site configs: run the EXE once, edit 站点配置.json beside it")
