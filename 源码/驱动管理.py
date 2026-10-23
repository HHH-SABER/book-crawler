# -*- coding: utf-8 -*-
"""chromedriver 自动管理 (2026-10-13, 需求 #7): 程序内自包含, 用户零安装。

## 为什么需要这个模块

`webdriver.Chrome()` 依赖 Selenium 能找到**版本匹配**的 chromedriver。此前:
  · 打包说明只提示 "Missing chromedriver? Place it next to .exe or on PATH"
    —— 用户得自己知道 Chrome 版本、去对应站点下载、解压、放对位置;
  · Chrome 每自动升级一次, 驱动就可能失配 ⇒ 反复手动处理。

本模块把"检测 Chrome → 匹配驱动版本 → 下载 → 就位"全流程做进程序:
  ① 程序目录/PATH 已有可用驱动 → 直接用 (零网络);
  ② 没有 → 读 Chrome 版本 → 匹配 Chrome for Testing 驱动 → 下载解压到
     程序目录 → 之后复用。
  用户侧表现为"启动就能用", 无需任何手动安装 (需求 #7 原话)。

## 设计约束

· **不打包驱动文件**: 驱动体积 ~10MB 且与 Chrome 版本强绑定, 打进去只会
  在 Chrome 升级后失配 ⇒ 改为运行时按需下载 (用户 2026-10-13 选定方案);
· **下载源双路**: 官方 storage.googleapis.com 为主, npmmirror 镜像兜底
  (国内直连官方常超时), 任一成功即用;
· **版本匹配走官方 API**: Chrome for Testing 的 last-known-good-versions
  JSON 是唯一权威源, 本地不做"猜版本"逻辑 (猜错比不猜更糟);
· 所有 IO/网络集中在薄封装层, 上层逻辑是纯函数 ⇒ 可离线单测。
"""
import json
import os
import re
import shutil
import subprocess
import zipfile

try:
    import requests
except Exception:                                    # 独立环境退化
    requests = None

try:
    from _path_utils import get_state_root
except Exception:
    def get_state_root() -> str:
        return os.path.join(os.path.expanduser('~'), '.novelcrawler')

_日志 = None


def _log():
    global _日志
    if _日志 is None:
        try:
            import 日志 as _app_log
            _日志 = _app_log.get('驱动管理')
        except Exception:
            import logging
            _日志 = logging.getLogger('驱动管理')
    return _日志


驱动目录名 = 'chromedriver'
_驱动可执行名 = 'chromedriver.exe'

# Chrome for Testing 官方 API —— **必须是 per-milestone 版**, 不能用
# last-known-good-versions: 后者只保留 Stable/Beta/Dev/Canary 各一个最新版本,
# 用户 Chrome 只要落后 Stable 一两个主版本就被挤出列表 ⇒ 匹配为空、直接卡死
# (2026-10-13 实测: 本机 Chrome 154, last-known-good 的 Stable 已是 155 ⇒ 空)。
# per-milestone 按主版本列出该 milestone 的最新可用版本, 才是"匹配驱动"的正解。
_API_URL = ('https://googlechromelabs.github.io/chrome-for-testing/'
            'latest-versions-per-milestone-with-downloads.json')
_API镜像 = ('https://registry.npmmirror.com/-/binary/chrome-for-testing/'
            'latest-versions-per-milestone-with-downloads.json')
# 下载 URL 模板 (官方 + 镜像), {版本} 占位
_下载模板 = (
    'https://storage.googleapis.com/chrome-for-testing-public/'
    '{版本}/win64/chromedriver-win64.zip',
    'https://registry.npmmirror.com/-/binary/chrome-for-testing/'
    '{版本}/win64/chromedriver-win64.zip',
)
_UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                     'AppleWebKit/537.36 Chrome/126.0 Safari/537.36'}


# ============ 纯函数 (可单测, 无 IO) ============

def 解析主版本(版本串: str) -> int:
    """`120.0.6099.109` → `120`; 无法解析返回 0 (调用方据此走"不猜"分支)。"""
    m = re.match(r'\s*(\d+)\.', str(版本串 or ''))
    return int(m.group(1)) if m else 0


def 从API选版本(api数据: dict, 主版本: int) -> str:
    """从 per-milestone API 数据里按主版本选驱动完整版本号。

    返回 '' 表示没有匹配项 (调用方必须报清晰错误, **不猜**)。
    兼容两种结构: per-milestone (`milestones: [{milestone, version, downloads}]`)
    与旧的 channels 结构 (防御将来换源)。
    """
    if not isinstance(api数据, dict) or 主版本 <= 0:
        return ''
    里程碑们 = api数据.get('milestones')
    # 真实结构是 **dict**: {主版本号(str): {version, downloads}}
    # (2026-10-13 实测: 顶层 keys 只有 timestamp/milestones, 后者是 dict)
    if isinstance(里程碑们, dict):
        for 号, 项 in 里程碑们.items():
            try:
                if int(号) != 主版本:
                    continue
            except Exception:
                continue
            if isinstance(项, dict) and 项.get('downloads', {}).get('chromedriver'):
                return str(项.get('version', ''))
        return ''
    if isinstance(里程碑们, list):      # 兼容: 万一日后换成 list 结构
        for m in 里程碑们:
            if not isinstance(m, dict):
                continue
            try:
                号 = int(m.get('milestone'))
            except Exception:
                continue
            if 号 == 主版本 and m.get('downloads', {}).get('chromedriver'):
                return str(m.get('version', ''))
        return ''
    # 兼容结构: channels (只在其主版本与请求一致时可用)
    渠道们 = api数据.get('channels', {})
    for 项 in 渠道们.values():
        if isinstance(项, dict) and 解析主版本(str(项.get('version', ''))) == 主版本 \
                and 项.get('downloads', {}).get('chromedriver'):
            return str(项.get('version', ''))
    return ''


def 驱动目录(程序根: str = None) -> str:
    """驱动安装目录: 优先程序根 (EXE/脚本旁), 退回 state_root。"""
    if 程序根:
        return os.path.join(程序根, 驱动目录名)
    return os.path.join(get_state_root(), 驱动目录名)


def 本地驱动路径(目录: str) -> str:
    return os.path.join(目录, _驱动可执行名)


# ============ 薄 IO 封装 (测试可注入) ============

def 找本地驱动(目录: str, 路径们=()) -> str:
    """按优先级找已存在的驱动: 显式路径 > 目标目录 > PATH。"""
    for p in list(路径们) + [本地驱动路径(目录)]:
        if p and os.path.isfile(p):
            return p
    return ''


def _从安装目录读版本() -> str:
    """从 Chrome 安装目录的**版本子目录**读版本 (权威来源, 2026-10-15 加)。

    为什么必须加这条路 (实测踩坑): 注册表 BLBeacon 的值**可能是旧的** ——
    Chrome 自动更新后安装目录已换成新版本目录 (如 155.0.8059.40), 而
    BLBeacon 仍报上一版 (154.0.8037.99)。`取Chrome版本` 原实现"注册表拿到就
    直接返回", 于是**按旧版本去匹配驱动** ⇒ chromedriver 154 配 Chrome 155
    ⇒ selenium 报 "unhandled request" (驱动与浏览器主版本不一致的典型症状)。
    版本子目录名 (Application/<主>.<次>.<修>.<构建>) 始终反映真实安装的版本。

    覆盖三种安装位置: Program Files / Program Files (x86) / 用户级 (LocalAppData)。
    """
    import re
    候选根 = [
        os.path.join(os.environ.get('PROGRAMFILES') or '', 'Google', 'Chrome'),
        os.path.join(os.environ.get('PROGRAMFILES(X86)') or '', 'Google', 'Chrome'),
        os.path.join(os.environ.get('LOCALAPPDATA') or '', 'Google', 'Chrome'),
    ]
    目录名正则 = re.compile(r'^\d+\.\d+\.\d+\.\d+$')
    for 根 in 候选根:
        应用 = os.path.join(根, 'Application')
        try:
            if not os.path.isdir(应用):
                continue
            for 项 in os.listdir(应用):
                if 目录名正则.match(项) and os.path.isdir(os.path.join(应用, 项)):
                    return 项
        except OSError:
            continue    # 无权限/竞态 → 试下一个根
    return ''


def 取Chrome版本(读注册表=None, 跑命令=None) -> str:
    """三路取 Chrome 版本: 安装目录 (权威) → 注册表 (快但可能旧) → 命令行兜底。

    优先级说明 (2026-10-15 实测修正): 原实现只信注册表, 而 Chrome 自动更新后
    BLBeacon 可能滞后于真实安装版本 ⇒ 按旧版本装驱动 ⇒ 驱动与浏览器主版本不匹配
    (selenium "unhandled request")。安装目录的版本子目录名才是权威, 故提到最前。
    注册表降为第二路 (它在 Chrome 从未启动过时反而更准), 命令行兜底不变。
    Args:
        读注册表: () -> str 替身 (返回版本串或 '');
        跑命令: (argv) -> str 替身。
    """
    if 读注册表 is None:
        def 读注册表():
            try:
                import winreg
                for 根 in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                    for 子键 in (r'Software\Google\Chrome\BLBeacon',):
                        try:
                            with winreg.OpenKey(根, 子键) as k:
                                v, _ = winreg.QueryValueEx(k, 'version')
                                if v:
                                    return str(v)
                        except Exception:
                            continue
            except Exception:
                pass  # 刻意静默: 注册表整体读取失败(非Windows/无权限)时走返回值 ''
    # 第一路: 安装目录版本子目录 (权威; 见 _从安装目录读版本 的踩坑说明)
    v = _从安装目录读版本()
    if not v:
        v = 读注册表() or ''
    if not v and 跑命令 is None:
        def 跑命令(argv):
            try:
                r = subprocess.run(argv, capture_output=True, timeout=10)
                return (r.stdout or b'').decode('utf-8', errors='replace')
            except Exception:
                return ''
    if not v and 跑命令 is not None:
        v = 跑命令(['chrome', '--version'])
    return v.strip()


def 取API数据(下载器=None) -> dict:
    """拉 Chrome for Testing API (双源: 官方 → 镜像)。"""
    if 下载器 is None:
        def 下载器(url):
            if requests is None:
                raise RuntimeError('requests 不可用')
            s = requests.Session()
            s.trust_env = True                     # 走系统代理 (用户可能挂代理)
            r = s.get(url, headers=_UA, timeout=20)
            r.raise_for_status()
            return r.text
    last = None
    for url in (_API_URL, _API镜像):
        try:
            return json.loads(下载器(url))
        except Exception as e:
            last = e
            _log().info(f'[驱动] API 源失败 {url[:48]}: {type(e).__name__}')
    raise RuntimeError(f'无法获取 Chrome for Testing 版本数据: {last}')


def 下载并解压(版本: str, 目录: str, 下载器=None, 解压器=None) -> str:
    """下载驱动 zip 并解压到 `目录`, 返回驱动可执行路径。"""
    if 下载器 is None:
        def 下载器(url):
            if requests is None:
                raise RuntimeError('requests 不可用')
            s = requests.Session()
            s.trust_env = True      # 走系统代理 (用户可能挂代理); 连接/读取
            # 分离超时: 只给一个总超时会出现"连上了但读不动"卡死 10 分钟
            r = s.get(url, headers=_UA, timeout=(10, 90), stream=True)
            r.raise_for_status()
            return r.content
    os.makedirs(目录, exist_ok=True)
    目标 = 本地驱动路径(目录)
    last = None
    for 模板 in _下载模板:
        url = 模板.format(版本=版本)
        try:
            _log().info(f'[驱动] 下载 {url[:70]}')
            数据 = 下载器(url)
            if not 数据 or len(数据) < 1024:
                raise RuntimeError(f'响应过小 ({len(数据 or b"")} 字节), 疑似错误页')
            _落盘解压(数据, 目标, 解压器)
            return 目标
        except Exception as e:
            last = e
            _log().info(f'[驱动] 下载源失败 {url[:60]}: {type(e).__name__}: {e}')
    raise RuntimeError(f'chromedriver {版本} 下载失败: {last}')


def _落盘解压(zip字节: bytes, 目标: str, 解压器=None) -> None:
    """zip 字节 → 解出 chromedriver.exe 到 `目标` (zip 内是
    `chromedriver-win64/chromedriver.exe` 一层目录)。"""
    临时 = 目标 + f'.tmp.{os.getpid()}'
    with open(临时, 'wb') as f:
        f.write(zip字节)
    try:
        if 解压器 is not None:
            解压器(临时, 目标)
            return
        with zipfile.ZipFile(临时) as z:
            名 = next((n for n in z.namelist()
                       if n.endswith('/' + _驱动可执行名)
                       or n == _驱动可执行名), None)
            if not 名:
                raise RuntimeError(f'zip 内找不到 {_驱动可执行名}')
            with z.open(名) as src, open(目标, 'wb') as dst:
                shutil.copyfileobj(src, dst)
    finally:
        if os.path.isfile(临时):
            os.remove(临时)


# ============ 主编排 ============

def 确保可用(程序根: str = None, 提示回调=None,
           找=找本地驱动, 取版本=取Chrome版本, 取API=取API数据,
           下载=下载并解压) -> str:
    """确保有可用驱动并返回其路径 (需求 #7 主入口)。

    流程: 本地已有 → 直接用; 否则读 Chrome 版本 → 匹配 → 下载 → 返回。
    Raises:
        RuntimeError: Chrome 未安装 / 版本不匹配 / 下载失败 (消息面向用户)。
    """
    目录 = 驱动目录(程序根)
    已有 = 找(目录)
    if 已有:
        _log().info(f'[驱动] 使用本地驱动: {已有}')
        return 已有

    if 提示回调:
        提示回调('正在检测 Chrome 版本并准备浏览器驱动…')
    版本串 = 取版本() if callable(取版本) else ''
    主 = 解析主版本(版本串)
    if 主 <= 0:
        raise RuntimeError(
            '未检测到已安装的 Chrome 浏览器。请先安装 Chrome, 或手动把对应版本的 '
            'chromedriver.exe 放到程序目录后重试。')
    _log().info(f'[驱动] Chrome 版本 {版本串} (主版本 {主})')

    api = 取API() if callable(取API) else {}
    驱动版本 = 从API选版本(api, 主)
    if not 驱动版本:
        raise RuntimeError(
            f'没有找到与 Chrome {主}.x 匹配的 chromedriver 版本。'
            f'可能是 Chrome 刚升级、驱动源尚未收录, 请稍后重试或手动安装驱动。')
    if 提示回调:
        提示回调(f'正在下载 Chrome {主}.x 的浏览器驱动…')
    路径 = 下载(驱动版本, 目录) if callable(下载) else ''
    if not 路径 or not os.path.isfile(路径):
        raise RuntimeError('驱动下载后未找到可执行文件, 请重试。')
    _log().info(f'[驱动] 驱动就绪: {路径}')
    return 路径
