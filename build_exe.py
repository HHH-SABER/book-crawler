# -*- coding: utf-8 -*-
"""
Novel Crawler EXE Build (Python -> flet pack)
UTF-8 encoded; no encoding ambiguity, runs flet pack via subprocess.
Double-click 打包EXE.bat  (or:  .venv\\Scripts\\python.exe build_exe.py)
"""
import os, sys, subprocess, shutil, time

ROOT = os.path.dirname(os.path.abspath(__file__))
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
with open(LOG, "w", encoding="utf-8") as f:
    f.write(f"==== BUILD STARTED {time.strftime('%Y-%m-%d %H:%M:%S')} ====\n")

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
    cache_script = os.path.join(ROOT, "ensure_flet_cache.py")
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

# --- 3) ensure output dir exists (required because of --add-data)
out_dir = os.path.join(ROOT, "抓取结果")
os.makedirs(out_dir, exist_ok=True)
log(f"[DIR] 抓取结果 dir ready")

# --- 4) clean previous dist/
dist = os.path.join(ROOT, "dist")
if os.path.isdir(dist):
    log("[CLEAN] Remove previous dist/")
    shutil.rmtree(dist, ignore_errors=True)

# --- 5) arguments (one list element = one argv token)
script_path = os.path.join(ROOT, "爬虫源码", "gui_app.py")
exe_name    = "小说爬虫"
add_data    = f"抓取结果:抓取结果"    # per flet pack --help: source:destination

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
    "--add-data", add_data,
    "-y",
    "-v",
]

log(f"[INFO] script = {script_path}")
log(f"[INFO] exe    = {exe_name}")
log(f"[INFO] data   = {add_data}")
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
final_exe_dir = os.path.join(dist, exe_name)
final_exe     = os.path.join(final_exe_dir, f"{exe_name}.exe")
log(f"  Output folder : {dist}")
log(f"  Executable    : {final_exe}")
log("")
log("Notes:")
log("  - Chrome must be installed on target machine (Selenium anti-bot bypass)")
log(f"  - Distribute the ENTIRE folder: {final_exe_dir}   (not only the .exe)")
log("  - Missing chromedriver? Place it next to .exe or on PATH")
