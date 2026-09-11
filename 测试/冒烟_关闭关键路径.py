# -*- coding: utf-8 -*-
"""GUI 关键路径冒烟: 关闭确认弹窗 / 最小化到托盘 / 直接退出 (黑盒 E2E)。

v2.4.19 教训: 弹窗文字不可见 / 托盘最小化不隐藏 / 退出孤儿进程, 三个事故
全是"打包成功≠能启动"启动冒烟覆盖不到的 **OS 集成层** bug —— 控件级测试台
(flet-testing) 抓不住这类问题, 必须用真实 GUI 进程把关闭链路完整驱动一遍。

四重断言通道:
  1. 日志行    — 临时状态根 日志/*.log (弹窗/托盘/退出埋点)
  2. 窗口可见性 — Win32 IsWindowVisible (托盘分支必须隐藏窗口)
  3. 进程树    — tasklist PID 差分 (退出分支必须 Python + flet.exe 双进程回收,
                 直接回归"关不掉/孤儿 flet.exe"事故)
  4. 配置文件  — 客户端配置.json 的 关闭行为 三态 (询问/托盘/退出)

用法 (手写 __main__ 脚本, 不进 unittest discover):
    python 测试\\冒烟_关闭关键路径.py                     # 源码模式 (默认)
    python 测试\\冒烟_关闭关键路径.py --exe dist\\小说爬虫.exe   # 打包模式

原理:
  · LOCALAPPDATA 重定向到临时状态根 —— 被测实例与真实数据完全隔离;
    预建 数据/日志 空目录可跳过 _path_utils 的一次性迁移 (2026-09-11 加固后语义)。
  · PostMessage WM_CLOSE 等价用户点标题栏 X: prevent_close=True 时 flet 把
    关闭事件转交 Python 侧 _处理关闭。
  · 三个场景共用一个 GUI 实例 (S1 弹窗保持打开不影响 S2/S3 —— 配置驱动分支
    在 _处理关闭 里读文件, 不经过弹窗按钮), 全程无需 UI 点击。
  · 覆盖缺口 (需人工): 弹窗内按钮点击、勾选"记住我的选择"、托盘双击恢复 ——
    Flutter 无障碍树自动化不可靠, 留给发版人工双验。
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import os
import shutil
import subprocess
import sys
import tempfile
import time

项目根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WM_CLOSE = 0x0010
等窗口秒 = 90          # 与 build_exe.py 启动冒烟同口径
等响应秒 = 20
轮询间隔 = 0.5


# ---------------------------------------------------------------- Win32 辅助
def _枚举窗口():
    """返回 (hwnd, pid, 标题) 列表 (全部顶层窗口)。"""
    user32 = ctypes.windll.user32
    结果 = []
    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def _回调(hwnd, _l):
        pid = wt.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        结果.append((hwnd, pid.value, buf.value))
        return True
    user32.EnumWindows(_回调, 0)
    return 结果


def 找主窗(flet_pids, 标题前缀="小说爬虫"):
    """在 flet 客户端进程的窗口里找可见的主窗口 (标题 = "小说爬虫 vX.Y.Z")。"""
    for hwnd, pid, 标题 in _枚举窗口():
        if str(pid) in flet_pids and 标题.startswith(标题前缀):
            if ctypes.windll.user32.IsWindowVisible(hwnd):
                return hwnd
    return None


def 发关闭(hwnd):
    """PostMessage WM_CLOSE ≈ 用户点标题栏 X (不阻塞、不等待)。"""
    ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


# ---------------------------------------------------------------- 进程辅助
def _取pid集(tasklist输出, 进程名小写):
    """tasklist 文本 → 指定进程名的 PID 集合 (PID 是 ASCII, 不受代码页影响)。"""
    pids = set()
    for line in (tasklist输出 or "").splitlines():
        parts = line.split()
        if len(parts) > 1 and parts[0].lower() == 进程名小写:
            pids.add(parts[1])
    return pids


def _tasklist():
    r = subprocess.run(["tasklist"], capture_output=True, text=True,
                       errors="replace")
    return r.stdout or ""


def 全部活着(watch_pids):
    tl = _tasklist()
    return {p for p in watch_pids if p in tl}


# ---------------------------------------------------------------- 状态根辅助
class 临时状态根:
    """LOCALAPPDATA 重定向 + 预建 数据/日志 (跳过迁移, 完全隔离)。"""

    def __init__(self):
        self.父目录 = tempfile.mkdtemp(prefix="novel_smoke_")
        self.根 = os.path.join(self.父目录, "小说爬虫")
        os.makedirs(os.path.join(self.根, "数据"), exist_ok=True)
        os.makedirs(os.path.join(self.根, "日志"), exist_ok=True)

    @property
    def 日志目录(self):
        return os.path.join(self.根, "日志")

    @property
    def 配置路径(self):
        return os.path.join(self.根, "数据", "客户端配置.json")

    def 日志全文(self):
        pieces = []
        for name in os.listdir(self.日志目录):
            if name.endswith(".log"):
                try:
                    with open(os.path.join(self.日志目录, name),
                              "r", encoding="utf-8", errors="replace") as f:
                        pieces.append(f.read())
                except OSError:
                    pass
        return "\n".join(pieces)

    def 写关闭行为(self, v):
        """与 gui_app._写关闭行为 同构: tmp + os.replace 原子写。"""
        tmp = self.配置路径 + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write('{"关闭行为": "%s"}' % v)
        os.replace(tmp, self.配置路径)

    def 清理(self):
        shutil.rmtree(self.父目录, ignore_errors=True)


# ---------------------------------------------------------------- 被测实例
class 被测实例:
    """拉起一个 GUI (源码或 EXE), 跟踪它的全部进程 PID。"""

    def __init__(self, exe路径=None, 状态根=None):
        self.状态根 = 状态根
        self.proc = None
        self.watch_pids = set()      # 我们拉起来的全部进程 (GUI 侧 + flet 侧)
        self.flet_pids = set()
        self.基线flet = set()
        self.基线 = set()
        self.hwnd = None

        env = dict(os.environ)
        env["LOCALAPPDATA"] = 状态根.父目录
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"

        tl0 = _tasklist()
        self.基线flet = _取pid集(tl0, "flet.exe")
        基线exe = _取pid集(tl0, "小说爬虫.exe")
        self.基线 = self.基线flet | 基线exe

        if exe路径:
            exe路径 = os.path.abspath(exe路径)
            if not os.path.isfile(exe路径):
                raise FileNotFoundError(f"EXE 不存在: {exe路径}")
            self.proc = subprocess.Popen([exe路径],
                                         cwd=os.path.dirname(exe路径), env=env)
            self.被测exe = True
        else:
            py = os.path.join(项目根, ".venv", "Scripts", "python.exe")
            if not os.path.isfile(py):
                py = sys.executable
            self.proc = subprocess.Popen(
                [py, os.path.join(项目根, "源码", "gui_app.py")],
                cwd=项目根, env=env)
            self.被测exe = False
        self.watch_pids.add(str(self.proc.pid))

    def 等窗口(self):
        """等 flet 客户端 + 主窗口出现 (PID 差分, 防残留假通过)。"""
        截止 = time.time() + 等窗口秒
        while time.time() < 截止:
            tl = _tasklist()
            self.flet_pids = _取pid集(tl, "flet.exe") - self.基线flet
            if self.flet_pids:
                self.watch_pids |= self.flet_pids
                if self.被测exe:
                    # EXE 是 onefile 引导 + 子进程两段, 把新增的本体 PID 一并盯住
                    self.watch_pids |= (_取pid集(tl, "小说爬虫.exe")
                                        - self.基线)
                self.hwnd = 找主窗(self.flet_pids)
                if self.hwnd:
                    time.sleep(3)   # 等 Python 侧会话/事件接线稳定
                    return True
            if str(self.proc.pid) not in tl:
                return False        # GUI 侧先死了
            time.sleep(1.5)
        return False

    def 还活着(self):
        return bool(全部活着(self.watch_pids))

    def 杀掉(self):
        for pid in list(self.watch_pids):
            subprocess.run(["taskkill", "/F", "/PID", pid],
                           capture_output=True)


# ---------------------------------------------------------------- 断言
class 失败(Exception):
    pass


def 断言(条件, 消息):
    if not 条件:
        raise 失败(消息)
    print(f"    ✓ {消息}")


def 等日志行(状态根, 子串, 超时秒, 实例=None):
    截止 = time.time() + 超时秒
    while time.time() < 截止:
        if 子串 in 状态根.日志全文():
            print(f"    ✓ 日志含 [{子串}]")
            return True
        time.sleep(轮询间隔)
    诊断 = ""
    if 实例 is not None:
        活 = 实例.还活着()
        诊断 += f"\n存活 PID: {活 or '无'}"
        if 实例.hwnd:
            可见 = ctypes.windll.user32.IsWindowVisible(实例.hwnd)
            诊断 += f"; 主窗口可见={可见}"
    raise 失败(f"{超时秒}s 内日志未出现 [{子串}]{诊断}\n--- 日志尾部 ---\n"
              + "\n".join(状态根.日志全文().splitlines()[-25:]))


def 等窗口不可见(hwnd, 超时秒):
    截止 = time.time() + 超时秒
    while time.time() < 截止:
        if not ctypes.windll.user32.IsWindowVisible(hwnd):
            print("    ✓ 主窗口已隐藏 (IsWindowVisible=False)")
            return True
        time.sleep(轮询间隔)
    raise 失败(f"{超时秒}s 内主窗口未隐藏 (v2.4.19 '缺 page.update 不隐藏' 回归?)")


def 等进程退出(实例, 超时秒):
    截止 = time.time() + 超时秒
    while time.time() < 截止:
        if not 实例.还活着():
            print("    ✓ 进程树已全部回收 (GUI 侧 + flet 客户端, 无孤儿)")
            return True
        time.sleep(轮询间隔)
    残留 = 实例.还活着()
    raise 失败(f"{超时秒}s 内进程未退出, 残留 PID: {残留} "
              "(v2.4.19 '孤儿 flet.exe' 回归?)")


# ---------------------------------------------------------------- 场景
def 场景1_默认询问(实例, 状态根):
    print("\n[S1] 关闭行为=询问 (默认): WM_CLOSE → 确认弹窗, 不做任何副作用")
    发关闭(实例.hwnd)
    等日志行(状态根, "弹出关闭确认弹窗", 等响应秒)
    time.sleep(2)
    断言(ctypes.windll.user32.IsWindowVisible(实例.hwnd),
         "主窗口仍可见 (弹窗是应用内 AlertDialog, 不隐藏窗口)")
    断言(实例.还活着(), "进程保持存活 (未选任何分支, 不退出)")
    全文 = 状态根.日志全文()
    断言("[托盘]" not in 全文, "未触发托盘分支")
    断言("[退出]" not in 全文, "未触发退出分支")


def 场景2_托盘(实例, 状态根):
    print("\n[S2] 关闭行为=托盘 (记住我的选择等效): WM_CLOSE → 建托盘 + 隐藏窗口")
    状态根.写关闭行为("托盘")
    发关闭(实例.hwnd)
    等日志行(状态根, "已最小化到托盘", 等响应秒)
    等窗口不可见(实例.hwnd, 等响应秒)
    断言(实例.还活着(), "进程保持存活 (托盘模式远控/后端继续运行)")


def 场景3_退出(实例, 状态根):
    print("\n[S3] 关闭行为=退出: WM_CLOSE → 7 步退出流程, 双进程干净回收")
    状态根.写关闭行为("退出")
    发关闭(实例.hwnd)
    # 断言①: 退出流程确实启动 (区分 "事件未送达" 与 "启动后挂死")
    try:
        等日志行(状态根, "开始退出流程", 10, 实例)
    except 失败:
        print("    ⚠ 首次 WM_CLOSE 未触发退出, 重发一次...")
        发关闭(实例.hwnd)
        等日志行(状态根, "开始退出流程", 等响应秒, 实例)
    # 断言② (核心): 双进程全部回收, 无孤儿 —— v2.4.19 "关不掉"事故的直接回归。
    # 注意: "退出流程完成" 摘要行存在固有竞态 (destroy 后 ft.run() 偶尔直接返回,
    # 进程在兜底强退前正常退出, 摘要行来不及写), 不能作为硬断言。
    等进程退出(实例, 等响应秒)
    if "退出流程完成" in 状态根.日志全文():
        print("    ✓ (附) 退出摘要行已落盘")


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser(description="GUI 关键路径冒烟 (关闭弹窗/托盘/退出)")
    ap.add_argument("--exe", default=None,
                    help="打包模式: 被测 EXE 路径 (缺省跑源码模式)")
    args = ap.parse_args()

    if sys.platform != "win32":
        print("仅支持 Windows (Win32 驱动)")
        return 2

    状态根 = 临时状态根()
    实例 = None
    try:
        实例 = 被测实例(exe路径=args.exe, 状态根=状态根)
        模式 = f"EXE {args.exe}" if args.exe else "源码"
        print(f"[启动] {模式}; 临时状态根: {状态根.根}")
        if not 实例.等窗口():
            raise 失败(f"{等窗口秒}s 内主窗口未出现 (启动冒烟已覆盖的层? "
                      "先跑 build_exe.py 冒烟排除启动问题)")
        print(f"    ✓ 主窗口出现 (flet PID: {', '.join(sorted(实例.flet_pids))})")

        场景1_默认询问(实例, 状态根)
        场景2_托盘(实例, 状态根)
        场景3_退出(实例, 状态根)

        print("\n✅ 冒烟通过: 关闭关键路径 (询问弹窗/托盘隐藏/干净退出) 全部符合预期")
        return 0
    except 失败 as e:
        print(f"\n❌ 冒烟失败: {e}")
        return 1
    finally:
        if 实例 is not None:
            实例.杀掉()
        time.sleep(1)
        状态根.清理()


if __name__ == "__main__":
    sys.exit(main())
