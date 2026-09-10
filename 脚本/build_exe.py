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

# CI (GitHub Actions) 下 stdout 可能落到 cp1252 导致中文 print 崩溃, 强制 UTF-8
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

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
        p = Path(VERSION_FILE).resolve()   # pathlib 锚定, 防路径穿越
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"版本": ver, "最近发布日期": date},
                                ensure_ascii=False, indent=2), encoding="utf-8")
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
        Path(changelog).resolve().write_text(新文本, encoding="utf-8")
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
        Path(path).resolve().write_text(内容, encoding='utf-8')  # 防路径穿越
        log(f"[OK] Version file : {path}")
        return path
    except OSError as e:
        log(f"[ERROR] 生成版本文件失败: {e}")
        sys.exit(5)


def _flet_pids(tasklist_output: str) -> set:
    """从 tasklist 输出里取出 flet.exe 的 PID 集合。

    冒烟的强验证判据是"启动 EXE 之后**新出现**的 flet.exe", 所以必须按 PID 做差分:
    源码方式运行的 GUI、历史崩溃残留都会留下 flet.exe, 只按进程名判断会让冒烟假通过。
    PID 是纯 ASCII 数字, 不受控制台代码页影响 (中文进程名在 CI 英文系统会变 '???')。
    """
    pids = set()
    for line in (tasklist_output or "").splitlines():
        parts = line.split()
        if len(parts) > 1 and parts[0].lower() == "flet.exe":
            pids.add(parts[1])
    return pids


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
    _g.add_argument("--skip-smoke", action="store_true",
                    help="跳过构建后的 EXE 启动冒烟测试 (默认开启: 打包成功≠能启动)")
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

    global PRODUCT_VERSION, FILE_VERSION
    PRODUCT_VERSION = _新版本
    FILE_VERSION = _新版本 + ".0"

    banner(f"Novel Crawler EXE Build  v{PRODUCT_VERSION}")
    log(f"[版本] 上次={_上次版本} → 本次={PRODUCT_VERSION} ({FILE_VERSION})")
    log("[版本] 版本.json/CHANGELOG 在构建成功后写入 (M4: 失败不消耗版本号)")
    log("")

    # --- 1) find pyinstaller.exe (或回退 python -m PyInstaller)
    # 说明: 直接调用 PyInstaller 而非 flet pack, 以便传入 --version-file
    # 嵌入 EXE 属性中的版本号 (flet pack 0.86 会静默忽略 --product-version 参数)
    pyinstaller_candidates = [
        os.path.join(ROOT, ".venv", "Scripts", "pyinstaller.exe"),
        shutil.which("pyinstaller"),
    ]
    pyinstaller_exe = next((p for p in pyinstaller_candidates if p and os.path.isfile(p)), None)
    if not pyinstaller_exe:
        # console script 缺失时回退到 `python -m PyInstaller` (下方执行路径即是)
        try:
            import PyInstaller  # noqa: F401
            pyinstaller_exe = sys.executable  # 实际以 -m PyInstaller 执行
            log("[INFO] pyinstaller.exe 缺失, 回退 python -m PyInstaller")
        except ImportError:
            log("[ERROR] PyInstaller not found. Install deps first:")
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
    # 环境变量 WBC_SKIP_CLEAN=1 时跳过目录删除 (dist 被进程占用/沙箱拦截时用;
    # PyInstaller --noconfirm 会覆盖 dist 内同名 EXE)
    dist = os.path.join(ROOT, "dist")
    if os.path.isdir(dist) and not os.environ.get("WBC_SKIP_CLEAN"):
        log("[CLEAN] Remove previous dist/")
        shutil.rmtree(dist, ignore_errors=True)
    build_dir = os.path.join(ROOT, "build")
    if os.path.isdir(build_dir) and not os.environ.get("WBC_SKIP_CLEAN"):
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
    # Rust 加速扩展 rust_core.pyd（内容质检/码点流解码的 PyO3 abi3 扩展）。
    # 放到 bundle 根 (.): onefile 解压后 _MEIPASS 在 sys.path 上, `import rust_core`
    # 可直接命中; .pyd 缺失时自动回退纯 Python (可选, 非致命)
    rust_core_pyd = os.path.join(ROOT, "源码", "rust_core.pyd")
    if os.path.isfile(rust_core_pyd):
        add_data_list.append(f"{rust_core_pyd}:.")
        log(f"[OK] Bundling rust_core.pyd (Rust 加速)")
    else:
        log("[INFO] rust_core.pyd 不存在, 跳过 (运行时间退纯 Python)")

    # flet 包内纯数据文件 (material/icons.json 等): flet 0.86 的图标枚举经
    # importlib.resources 在运行时读取 (controls/material/icons.py::_load),
    # PyInstaller 没有 flet hook 不会自动收集纯数据 — 缺失时 GUI 启动即崩
    # (FileNotFoundError: _MEIxxx/flet/controls/material/icons.json, v2.4.0 实测)。
    # 全量收集 flet 包内的 .json 数据文件 (共 <600KB), 覆盖 material/cupertino 两套
    try:
        import flet as _flet
        _flet_dir = os.path.dirname(_flet.__file__)
        for _root, _dirs, _files in os.walk(_flet_dir):
            if "__pycache__" in _root:
                continue
            for _fn in _files:
                if os.path.splitext(_fn)[1].lower() != ".json":
                    continue
                _full = os.path.join(_root, _fn)
                _rel_dir = os.path.relpath(_root, _flet_dir)
                add_data_list.append(f"{_full}:{os.path.join('flet', _rel_dir)}")
                log(f"[OK] Bundling flet data: {_rel_dir}\\{_fn}")
    except Exception as e:
        log(f"[ERROR] 收集 flet 数据文件失败 (EXE 将缺图标元数据): {e}")
        sys.exit(5)
    # H1: playwright 反检测引擎的 driver/ (node.exe + 驱动包, ~100MB) 是运行时
    # 动态调用的二进制资源。实测 playwright 自带 hook-playwright.sync_api 通常
    # 已收集 driver (v2.4.1 构建体积未因本条变化可证), 此处显式 add-data 兜底,
    # 防上游 hook 行为变化导致静默回退裸 Selenium (stealth 反指纹全丢)
    try:
        import playwright as _pw
        _pw_driver = os.path.join(os.path.dirname(_pw.__file__), "driver")
        if os.path.isdir(_pw_driver):
            add_data_list.append(f"{_pw_driver}:playwright/driver")
            log("[OK] playwright driver 显式入库 (自带 hook 之外的兜底)")
        else:
            log("[WARN] playwright/driver 不存在, EXE 将回退 Selenium (无 stealth)")
    except ImportError:
        log("[INFO] playwright 未安装, 跳过 (EXE 内回退 Selenium)")

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
    # ebooklib (EPUB 导出) 在 epub_exporter.py 中 try/except 引入, 显式收集确保
    # onefile EXE 内可用; 其依赖 lxml 由 PyInstaller 自带 hook 处理。
    # flet_desktop: flet.app.run() 运行时才动态 import 的纯 py 启动模块 (客户端
    # 二进制本体由 _flet_client + FLET_VIEW_PATH 提供, 见 gui_app.py 头部),
    # 静态分析收不到 → EXE 启动到 ft.run 即 ModuleNotFoundError (v2.4.0 实测)
    for hi in ("ebooklib", "flet_desktop", "pystray"):
        cmd.extend(["--hidden-import", hi])
    # 内嵌远控 (GUI 内导 远控.服务): uvicorn 为惰性导入且自身动态加载子模块,
    # 必须整包收集; fastapi/pydantic 由静态分析覆盖
    cmd.extend(["--collect-submodules", "uvicorn"])

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
    # M4: 版本号/CHANGELOG 在构建成功后才落盘 — 旧实现在 PyInstaller 之前就写,
    # 打包失败后 版本.json 已消耗、CHANGELOG 顶部已被改写 → 下次成功打包跳号
    _写版本(_新版本, _今天)
    log(_同步CHANGELOG(_新版本, _今天))
    # 清理临时版本文件 (避免污染项目根目录)
    try:
        os.remove(version_file)
        log("[CLEAN] Removed temp version file")
    except OSError:
        pass
    # 自动清理 PyInstaller 编译中间产物 build/ (打包过程中重新生成, 无保留价值)
    if os.path.isdir(build_dir) and not os.environ.get("WBC_SKIP_CLEAN"):
        try:
            shutil.rmtree(build_dir, ignore_errors=True)
            log("[CLEAN] Removed build/ (PyInstaller temp artifacts)")
        except OSError as e:
            log(f"[WARN] 清理 build/ 失败: {e}")
    # 把 站点适配/ 插件目录 (外部适配器, 免重新打包扩展新站) 复制进便携目录
    adapters_src = os.path.join(ROOT, "站点适配")
    adapters_dst = os.path.join(dist, "站点适配")
    if os.path.isdir(adapters_src):
        try:
            if os.path.isdir(adapters_dst):
                shutil.rmtree(adapters_dst, ignore_errors=True)
            shutil.copytree(adapters_src, adapters_dst)
            log(f"[OK] Copied 站点适配/ → {adapters_dst}")
        except OSError as e:
            log(f"[WARN] 复制 站点适配/ 失败: {e}")
    else:
        log("[INFO] 站点适配/ 不存在, 跳过 (可选外部适配器目录)")
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

    # --- EXE 启动冒烟测试 (v2.4.0 教训: 打包成功 ≠ 能启动 — flet icons.json
    # 与 flet_desktop 两个缺口都靠真实启动才暴露; CI 发布前必须过此关) ---
    def _dump_crash_log(dist):
        """冒烟失败时把 EXE 首启日志尾部打进构建输出 (日志.py 的全局
        excepthook 会把 traceback 写文件, CI 上拿不到对话框内容, 靠这个诊断)"""
        import glob as _glob
        try:
            log_dir = os.path.join(dist, "日志")
            files = sorted(_glob.glob(os.path.join(log_dir, "*.log")),
                           key=os.path.getmtime)
            if not files:
                log("[SMOKE] 无 EXE 首启日志 — 崩溃发生在 日志 模块初始化之前")
                return
            with open(files[-1], "r", encoding="utf-8", errors="replace") as f:
                tail = f.readlines()[-40:]
            log(f"[SMOKE] ===== EXE 首启日志尾部 ({os.path.basename(files[-1])}) =====")
            for ln in tail:
                log("    " + ln.rstrip())
        except Exception as e:
            log(f"[SMOKE] 读取首启日志失败: {e}")

    if _args.skip_smoke:
        log("[INFO] --skip-smoke: 跳过启动冒烟测试")
    else:
        # 基线: 只把"打包产物本身在跑"视为冲突 (否则会误杀用户会话)。
        # 修复两点 (2026-09-10):
        #   1) 不能因存在 flet.exe 就跳过 —— 源码方式运行的 GUI、历史崩溃残留都会
        #      留下 flet.exe, 那会让冒烟永远跑不起来 (实测踩到过一次)。
        #   2) 循环里原先用 "tasklist 出现 flet.exe" 判成功, 残留进程会让冒烟
        #      **假通过**。改为 PID 差分: 只认"启动 EXE 之后新出现的 flet.exe"。
        _base_tl = subprocess.run(["tasklist"], capture_output=True, text=True,
                                  errors="replace").stdout or ""
        _基础flet = _flet_pids(_base_tl)
        if "小说爬虫.exe" in _base_tl:
            log("[WARN] 检测到 小说爬虫.exe 已在运行, 冒烟测试跳过 (避免干扰现有会话)")
        elif mode != "ONEFILE" or not os.path.isfile(final_exe):
            log(f"[WARN] 产物为 {mode}, 冒烟测试仅支持 ONEFILE, 跳过")
        else:
            log("[SMOKE] 启动 EXE 验证 (最长 90s; 新出现 flet 客户端=强通过; "
                "CI 无 GPU/桌面环境降级为'无报错对话框+进程存活'弱验证)")
            if _基础flet:
                log(f"[INFO] 基线已有 {len(_基础flet)} 个 flet.exe (非本产物), "
                    "按 PID 差分排除, 不影响判定")
            _on_ci = os.environ.get("GITHUB_ACTIONS") == "true"
            _smoke_ok = False
            _diag = ""
            _本次flet = set()
            try:
                # 进程存活用 PID 匹配 (纯 ASCII 数字) — 中文进程名在 tasklist
                # 重定向输出里受代码页影响 (CI 英文系统会变 '???') 不可靠
                _proc = subprocess.Popen([final_exe], cwd=final_exe_dir)
                for _ in range(60):
                    time.sleep(1.5)
                    _tl = subprocess.run(["tasklist"], capture_output=True,
                                         text=True, errors="replace").stdout or ""
                    _本次flet = _flet_pids(_tl) - _基础flet
                    if _本次flet:
                        _smoke_ok = True   # 强验证: 本产物真把 flet 客户端拉起来了
                        break
                    # 快速失败: PyInstaller 启动即崩会弹出 "Unhandled exception
                    # in script" 对话框 (v2.4.0 的缺口就是这类)
                    if "Unhandled exception" in subprocess.run(
                        ["powershell", "-NoProfile", "-Command",
                         "Get-Process | Where-Object { $_.MainWindowTitle } | "
                         "Select-Object -ExpandProperty MainWindowTitle"],
                        capture_output=True, text=True, errors="replace").stdout or "":
                        _diag = "检测到启动报错对话框 (Unhandled exception in script)"
                        break
                    if str(_proc.pid) not in _tl:
                        _diag = ("EXE 进程在 flet 客户端出现前退出 (若期间有人手动"
                                 "关闭了弹出的窗口请重跑构建, 否则疑似静默崩溃)")
                        break
            finally:
                # 只回收本次冒烟拉起来的进程 —— 旧实现 taskkill /IM flet.exe 会
                # 连用户正在用的 GUI 一起杀掉
                subprocess.run(["taskkill", "/F", "/PID", str(_proc.pid)],
                               capture_output=True)
                for _pid in _本次flet:
                    subprocess.run(["taskkill", "/F", "/PID", _pid],
                                   capture_output=True)
            if _smoke_ok:
                log("[OK] 冒烟通过 (强验证): EXE 拉起主窗口成功")
            elif not _diag and _on_ci:
                log("[WARN] 冒烟弱验证通过: CI 无 GPU/桌面 90s 未拉起 flet 客户端, "
                    "但 EXE 存活且无启动报错对话框")
            else:
                log(f"[ERROR] 冒烟失败: {_diag or '90s 内未见新 flet 客户端进程'} "
                    "(手动运行 dist\\小说爬虫.exe 查看报错对话框)")
                _dump_crash_log(dist)
                sys.exit(5)


if __name__ == "__main__":
    main()
