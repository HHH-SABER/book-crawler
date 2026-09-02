# -*- coding: utf-8 -*-
"""
Novel Crawler EXE Build (Python -> PyInstaller, 自动版本号)
UTF-8 encoded; no encoding ambiguity.
Double-click 打包EXE.bat  (or:  .venv\\Scripts\\python.exe build_exe.py)

版本号自动管理:
  - 默认: 每次打包自动递增修订号 (2.0.0 -> 2.0.1 -> ...), 并同步更新
    CHANGELOG.md 顶部最新条目的版本号与日期
  - 可选参数 (见 --help):
      --bump=minor|major  递增次版本/主版本 (--bump 无值=patch)
      --version=2.1.0     手动指定版本号 (不递增)
      --no-bump           保持当前版本号不变 (重跑修复时使用)
  版本状态保存在: 脚本/版本.json
"""
import os, sys, subprocess, shutil, time, re, json, argparse
from pathlib import Path

# 安全: 使用 Path.resolve() 规范化脚本所在目录, 再上溯到项目根,
# 保证 ROOT/LOG 均为规范化绝对路径, 不含 ../ 穿越
ROOT = str(Path(__file__).resolve().parent.parent)  # 脚本/ 的上级 = 项目根
os.chdir(ROOT)

# ---- 版本号: 自动管理 ----
VERSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "版本.json")
_DEFAULT_VERSION = "1.0.0"   # 首次打包 (无状态文件) 时的初始版本


def _读版本() -> str:
    """读取上次打包版本号, 无状态文件时返回默认初始版本"""
    try:
        with open(VERSION_FILE, encoding="utf-8") as f:
            return str(json.load(f).get("版本", _DEFAULT_VERSION))
    except Exception:
        return _DEFAULT_VERSION


def _写版本(ver: str, date: str):
    """持久化当前版本状态 (供下次打包递增)"""
    try:
        with open(VERSION_FILE, "w", encoding="utf-8") as f:
            json.dump({"版本": ver, "最近发布日期": date},
                      f, ensure_ascii=False, indent=2)
    except OSError as e:
        log(f"[WARN] 版本状态写入失败: {e}")


def _递增(ver: str, 级别: str) -> str:
    """按级别递增语义化版本号: 2.0.0 +patch -> 2.0.1, +minor -> 2.1.0, +major -> 3.0.0"""
    parts = [int(x) for x in ver.split(".")]
    while len(parts) < 3:
        parts.append(0)
    if 级别 == "major":
        parts = [parts[0] + 1, 0, 0]
    elif 级别 == "minor":
        parts = [parts[0], parts[1] + 1, 0]
    else:  # patch
        parts[2] += 1
    return ".".join(str(x) for x in parts[:3])


def _同步CHANGELOG(ver: str, date: str) -> str:
    """把 CHANGELOG.md 顶部最新条目的版本号与日期更新为本次版本, 返回提示

    兼容两种标题形式 (部分编辑器会把 [ 转义为 \\[ ):
        ## [2.0.0] - 2026-09-02   /   ## \\[2.0.0] - 2026-09-02
    """
    changelog = os.path.join(ROOT, "CHANGELOG.md")
    try:
        with open(changelog, encoding="utf-8") as f:
            文本 = f.read()
    except OSError as e:
        return f"CHANGELOG 读取失败: {e}"
    模式 = re.compile(r'^(## )(\\?)(\[[\d.]+\])(\\?) - [\d-]+', flags=re.M)
    m = 模式.search(文本)
    if m:
        bs1, bs2 = m.group(2), m.group(4)   # 保留原转义样式
        新文本 = 模式.sub(
            lambda mm: f"{mm.group(1)}{bs1}[{ver}]{bs2} - {date}",
            文本, count=1)
    else:
        # 无最新条目 (首次): 在文档开头插入空模板
        新文本 = (f"## [{ver}] - {date}\n\n### 新增功能\n\n- (待补充本次改进内容)\n\n"
                  f"---\n\n" + 文本)
    try:
        with open(changelog, "w", encoding="utf-8") as f:
            f.write(新文本)
    except OSError as e:
        return f"CHANGELOG 写入失败: {e}"
    return f"CHANGELOG 顶部条目 → [{ver}] {date}"


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


def 生成版本文件(path: str) -> str:
    """根据 PRODUCT_VERSION / FILE_VERSION 生成 PyInstaller version file"""
    def _元组(ver: str, n: int = 4):
        parts = [int(x) for x in ver.split('.') if x.isdigit()]
        parts += [0] * (n - len(parts))
        return tuple(parts[:n])

    filevers = _元组(FILE_VERSION)      # (2,0,0,0)
    prodvers = _元组(PRODUCT_VERSION)   # (2,0,0,0)
    内容 = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={filevers},
    prodvers={prodvers},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '080404b0',
          [
            StringStruct('CompanyName', 'NovelCrawler'),
            StringStruct('FileDescription', 'Novel Crawler GUI'),
            StringStruct('FileVersion', '{FILE_VERSION}'),
            StringStruct('InternalName', 'novel_crawler'),
            StringStruct('LegalCopyright', '2026 NovelCrawler'),
            StringStruct('OriginalFilename', 'novel_crawler.exe'),
            StringStruct('ProductName', 'NovelCrawlerGUI'),
            StringStruct('ProductVersion', '{PRODUCT_VERSION}')
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
"""
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(内容)
        log(f"[OK] Version file : {path}")
        return path
    except OSError as e:
        log(f"[ERROR] 生成版本文件失败: {e}")
        sys.exit(5)


def main():
    """主流程: 版本解析/递增 → 环境准备 → PyInstaller 打包 → 产物报告"""
    # --- init log
    Path(LOG).write_text(
        f"==== BUILD STARTED {time.strftime('%Y-%m-%d %H:%M:%S')} ====\n",
        encoding="utf-8")

    # ---- 版本号解析与递增 (默认自动递增修订号) ----
    _parser = argparse.ArgumentParser(description="小说爬虫 EXE 打包 (自动版本号)")
    _g = _parser.add_mutually_exclusive_group()
    _g.add_argument("--bump", nargs="?", const="patch", choices=["patch", "minor", "major"],
                    help="递增版本: --bump(默认patch) / --bump=minor / --bump=major")
    _g.add_argument("--version", dest="指定版本", help="手动指定版本号 (不递增)")
    _g.add_argument("--no-bump", action="store_true", help="保持当前版本号不变")
    _args = _parser.parse_args()

    _上次版本 = _读版本()
    if _args.指定版本:
        _新版本 = str(_args.指定版本).strip()
    elif _args.no_bump:
        _新版本 = _上次版本
    else:
        _级别 = _args.bump or "patch"
        _新版本 = _递增(_上次版本, _级别)
    _今天 = time.strftime("%Y-%m-%d")
    _写版本(_新版本, _今天)

    global PRODUCT_VERSION, FILE_VERSION
    PRODUCT_VERSION = _新版本
    FILE_VERSION = _新版本 + ".0"

    banner(f"Novel Crawler EXE Build  v{PRODUCT_VERSION}")
    log(f"[版本] 上次={_上次版本} → 本次={PRODUCT_VERSION} ({FILE_VERSION})")
    log(_同步CHANGELOG(_新版本, _今天))
    log("")

    # --- 1) find pyinstaller.exe
    # 说明: 直接调用 PyInstaller 而非 flet pack, 以便传入 --version-file
    # 嵌入 EXE 属性中的版本号 (flet pack 0.86 会静默忽略 --product-version 参数)
    pyinstaller_candidates = [
        os.path.join(ROOT, ".venv", "Scripts", "pyinstaller.exe"),
        shutil.which("pyinstaller"),
    ]
    pyinstaller_exe = next((p for p in pyinstaller_candidates if p and os.path.isfile(p)), None)
    if not pyinstaller_exe:
        log("[ERROR] pyinstaller.exe not found. Install deps first:")
        log("         .venv\\Scripts\\pip.exe install -r requirements.txt")
        sys.exit(1)
    log(f"[OK] PyInstaller : {pyinstaller_exe}")

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
    # 必须预先删掉 build/: 否则 PyInstaller 会交互询问 "Do you want to delete
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

    # --- 4.5) 生成 PyInstaller 版本资源文件 (EXE 属性中的版本号/公司/产品等)
    version_file = 生成版本文件(os.path.join(ROOT, "_version_info.txt"))

    # 注意: 用 `python -m PyInstaller` 而非 pyinstaller.exe 引导程序 ——
    # Python 3.14 + PyInstaller 6.22 下 pyinstaller.exe 只输出版本号即退出 (引导兼容问题)
    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        script_path,
        "--noconfirm",
        "--noconsole",
        "--name", exe_name,
        "--distpath", os.path.join(ROOT, "dist"),
        "--onefile",
        "--version-file", version_file,
        "--clean",
    ]
    # 应用图标 (存在时使用)
    icon_path = os.path.join(ROOT, "脚本", "图标.ico")
    if os.path.isfile(icon_path):
        cmd.extend(["--icon", icon_path])
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

    log(f"[INFO] script = {script_path}")
    log(f"[INFO] exe    = {exe_name}")
    log(f"[INFO] data   = {', '.join(add_data_list)}")
    log(f"[INFO] version= {PRODUCT_VERSION} ({FILE_VERSION})")
    log("[BUILD] PyInstaller starting (onefile + version-file). First build downloads ~100MB, expect 2-8 min...")
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
    # 清理临时版本文件 (避免污染项目根目录)
    try:
        os.remove(version_file)
        log("[CLEAN] Removed temp version file")
    except OSError:
        pass
    # PyInstaller 可能 --onefile 或 onedir, 两处都查一下，把真实产物挑出来给用户看
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


if __name__ == "__main__":
    main()
