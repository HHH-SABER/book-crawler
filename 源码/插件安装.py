# -*- coding: utf-8 -*-
"""浏览器插件内置安装 (2026-10-20)。

把 插件/dist/<浏览器>/ 复制到本机稳定目录 (状态根/插件/<浏览器>), 并打开
对应浏览器的扩展管理页 —— 用户只需「开发者模式 → 加载已解压」两步。

为什么不是"静默安装": Chromium 系浏览器的扩展安装必须经扩展管理页/商店,
任何"绕过"手段都要改注册表策略或重打包浏览器, 对个人工具而言风险远大于收益。
本模块做到**能自动的都自动** (定位源 → 复制 → 打开页面 → 给出目录与步骤),
把剩下的两步压缩成点两下鼠标。

纯逻辑与视图分层: 本文件不碰 Flet, 离线可测。
"""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

import 日志 as _app_log

_log = _app_log.get('插件安装')

# 支持集 = Chromium 内核浏览器 (MV3 插件通用); firefox 仅探测供"不支持"明示
_支持 = ('chrome', 'edge', 'brave', 'vivaldi', '360', 'qq', 'quark')
_浏览器名 = {'chrome': 'Chrome', 'edge': 'Edge', 'brave': 'Brave',
          'vivaldi': 'Vivaldi', '360': '360极速浏览器', 'qq': 'QQ浏览器',
          'quark': '夸克浏览器'}
_扩展页 = {'chrome': 'chrome://extensions', 'edge': 'edge://extensions',
          'brave': 'brave://extensions', 'vivaldi': 'vivaldi://extensions',
          '360': 'chrome://extensions', 'qq': 'chrome://extensions',
          'quark': 'quark://extensions'}
# 扫描探测表 (2026-10-20 需求: 先扫描本机浏览器再让用户选择)
# 值可为单个 exe 名或元组 (夸克 exe 名不唯一: QuarkBrowser.exe / Quark.exe)
_探测键 = {'chrome': 'chrome.exe', 'edge': 'msedge.exe', 'firefox': 'firefox.exe',
          'brave': 'brave.exe', 'vivaldi': 'vivaldi.exe',
          '360': '360chrome.exe', 'qq': 'QQBrowser.exe',
          'quark': ('QuarkBrowser.exe', 'Quark.exe')}
_展示名 = {'chrome': 'Google Chrome', 'edge': 'Microsoft Edge',
          'firefox': 'Mozilla Firefox', 'brave': 'Brave',
          'vivaldi': 'Vivaldi', '360': '360 极速浏览器', 'qq': 'QQ 浏览器',
          'quark': '夸克浏览器'}
_不支持原因 = {
    'firefox': 'Firefox 非 Chromium 内核，本插件仅支持 Chromium 系浏览器',
}
# 已支持但需要额外步骤的浏览器 (扫描列表明示, 免得用户卡在"扩展页空白")
_备注 = {
    'quark': ('扩展支持默认关闭：先在「关于夸克」连点版本号 7 次 → 夸克实验室 → '
              '开启「扩展支持」，否则 quark://extensions 会空白'),
}
_排序 = ('chrome', 'edge', 'brave', 'vivaldi', '360', 'qq', 'quark', 'firefox')

_心跳新鲜秒 = 360          # 插件每 5 分钟自动同步一次, 6 分钟内算"已连接"


def _基目录() -> Path:
    try:
        from _path_utils import get_app_base_dir
        return Path(get_app_base_dir())
    except Exception:
        return Path(__file__).resolve().parent.parent


def _状态根() -> Path:
    try:
        from _path_utils import get_state_root
        return Path(get_state_root())
    except Exception:
        return Path(os.environ.get('LOCALAPPDATA', '.')) / '小说爬虫'


def 安装源(浏览器: str) -> Optional[Path]:
    """找到该版本插件的源目录 (源码运行 / 打包后 / EXE 旁 三种形态)。"""
    浏览器 = 浏览器.lower()
    if 浏览器 not in _支持:
        return None
    基 = _基目录()
    候选 = [
        基 / '插件' / 'dist' / 浏览器,      # 源码运行 (构建产物)
        基 / '插件' / 浏览器,               # 打包内 (build 时收进去的形态)
        基 / 'dist' / '插件' / 浏览器,      # EXE 旁 (便携发布形态)
        基 / 'dist' / '插件' / 'dist' / 浏览器,
    ]
    for p in 候选:
        if (p / 'manifest.json').is_file():
            return p
    return None


def 安装(浏览器: str) -> dict:
    """复制插件到稳定目录。返回 {ok, 目录, 浏览器, 步骤, 原因}。"""
    浏览器 = (浏览器 or '').lower()
    if 浏览器 not in _支持:
        return {'ok': False, '原因': f'不支持的浏览器: {浏览器}', '目录': '', '步骤': []}
    if _浏览器exe(浏览器) is None:
        return {'ok': False,
                '原因': f'未检测到 {_浏览器名[浏览器]}（请先安装该浏览器，或点「重新扫描」）',
                '目录': '', '步骤': []}
    源 = 安装源(浏览器)
    if 源 is None:
        return {'ok': False,
                '原因': f'找不到 {_浏览器名[浏览器]} 版插件源 (先运行 插件/构建两版.py 或重新构建 EXE)',
                '目录': '', '步骤': []}
    目标 = _状态根() / '插件' / 浏览器
    try:
        if 目标.exists():
            shutil.rmtree(目标)
        目标.mkdir(parents=True)
        for p in 源.rglob('*'):
            if p.is_file():
                相对 = p.relative_to(源)
                (目标 / 相对).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, 目标 / 相对)
    except OSError as e:
        _log.info(f'[插件安装] 复制失败: {type(e).__name__}: {e}')
        return {'ok': False, '原因': f'复制失败: {e}', '目录': '', '步骤': []}
    _log.info(f'[插件安装] {_浏览器名[浏览器]} 版已复制到 {目标}')
    return {
        'ok': True, '目录': str(目标), '浏览器': _浏览器名[浏览器], '原因': '',
        '步骤': [
            '1. 切到浏览器, 地址栏 Ctrl+V 粘贴扩展页地址后回车, 打开右上角「开发者模式」',
            '2. 点「加载已解压的扩展程序」',
            f'3. 粘贴并选择目录:  {目标}',
            '4. 点插件图标, 填入端口(8760)与 token (远控页可复制), 点「保存设置并测试连通」',
        ],
    }


def _浏览器exe(浏览器: str) -> Optional[str]:
    """定位浏览器主程序 (注册表 App Paths → 常见安装路径)。

    _探测键 的值可为单个 exe 名或元组 (夸克 exe 名不唯一); firefox 仅用于
    "已装但不支持"的明确提示。
    """
    exe键 = _探测键.get((浏览器 or '').lower())
    if not exe键:
        return None
    exe名s = (exe键,) if isinstance(exe键, str) else tuple(exe键)
    try:
        import winreg
        for exe名 in exe名s:
            键 = 'SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\' + exe名
            for 根 in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(根, 键) as k:
                        p = winreg.QueryValue(k, None)
                        if p and os.path.isfile(p):
                            return p
                except OSError:
                    continue
    except Exception:
        pass    # 刻意静默: winreg 不可用/键不存在时降级到常见路径探测, 无需留痕

    _常见表 = {
        'chrome.exe': [r'C://Program Files\Google\Chrome\Application\chrome.exe',
                       r'C://Program Files (x86)\Google\Chrome\Application\chrome.exe'],
        'msedge.exe': [r'C://Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
                       r'C://Program Files\Microsoft\Edge\Application\msedge.exe'],
        'firefox.exe': [r'C://Program Files\Mozilla Firefox\firefox.exe',
                        r'C://Program Files (x86)\Mozilla Firefox\firefox.exe'],
        'brave.exe': [r'C://Program Files\BraveSoftware\Brave-Browser\Application\brave.exe'],
        'vivaldi.exe': [r'C://Program Files\Vivaldi\Application\vivaldi.exe',
                        r'C://Program Files (x86)\Vivaldi\Application\vivaldi.exe'],
        '360chrome.exe': [r'C://Program Files (x86)\360\360Chrome\Chrome\Application\360chrome.exe',
                          r'C://Program Files\360\360Chrome\Chrome\Application\360chrome.exe'],
        'QQBrowser.exe': [r'C://Program Files (x86)\Tencent\QQBrowser\Application\QQBrowser.exe',
                          r'C://Program Files\Tencent\QQBrowser\Application\QQBrowser.exe'],
        'QuarkBrowser.exe': [r'C://Program Files\Quark\QuarkBrowser.exe',
                             r'C://Program Files (x86)\Quark\QuarkBrowser.exe'],
        'Quark.exe': [r'C://Program Files\Quark\Quark.exe',
                      r'C://Program Files (x86)\Quark\Quark.exe'],
    }
    常见 = []
    for exe名 in exe名s:
        常见.extend(_常见表.get(exe名, []))

    本地 = os.environ.get('LOCALAPPDATA', '')
    _用户级 = {
        'chrome.exe': ['Google/Chrome/Application/chrome.exe'],
        'msedge.exe': ['Microsoft/Edge/Application/msedge.exe'],
        'brave.exe': ['BraveSoftware/Brave-Browser/Application/brave.exe'],
        'vivaldi.exe': ['Vivaldi/Application/vivaldi.exe'],
        '360chrome.exe': ['360Chrome/Chrome/Application/360chrome.exe'],
        'QQBrowser.exe': ['Tencent/QQBrowser/Application/QQBrowser.exe'],
        'QuarkBrowser.exe': ['Quark/Application/QuarkBrowser.exe',
                             'Programs/Quark/QuarkBrowser.exe'],
        'Quark.exe': ['Quark/Application/Quark.exe', 'Programs/Quark/Quark.exe'],
    }
    if 本地:
        for exe名 in exe名s:
            for 相对 in _用户级.get(exe名, []):
                常见.append(os.path.join(本地, *相对.split('/')))
    for p in 常见:
        if p and os.path.isfile(p):
            return p
    return None


def _文件版本(exe: str) -> str:
    """读 exe 的产品/文件版本 (供安装列表展示); 失败返回空串。"""
    try:
        import ctypes
        size = ctypes.windll.version.GetFileVersionInfoSizeW(exe, None)
        if not size:
            return ''
        data = ctypes.create_string_buffer(size)
        if not ctypes.windll.version.GetFileVersionInfoW(exe, 0, size, data):
            return ''
        ptr = ctypes.c_void_p()
        ln = ctypes.c_uint()
        if not (ctypes.windll.version.VerQueryValueW(
                data, '\\VarFileInfo\\Translation', ctypes.byref(ptr),
                ctypes.byref(ln)) and ln.value >= 4):
            return ''
        pair = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_uint16 * 2)).contents
        键 = f'\\StringFileInfo\\{pair[0]:04x}{pair[1]:04x}\\FileVersion'
        if not ctypes.windll.version.VerQueryValueW(
                data, 键, ctypes.byref(ptr), ctypes.byref(ln)):
            return ''
        return ctypes.wstring_at(ptr.value).strip()
    except Exception:
        return ''


def 扫描() -> list:
    """扫描本机浏览器: 供安装弹窗列出目标 (2026-10-20 需求)。

    返回按"已装且支持 → 已装不支持 → 未装支持"排序的列表:
        [{浏览器, 名称, 支持, 已安装, 路径, 版本, 说明}]
    不支持的浏览器也列出 (说明为什么不能装), 未装的给出明确提示 ——
    "扫描、列表、选择、安装" 四个环节的入口都靠这份数据。
    """
    结果 = []
    for 键 in _排序:
        exe = _浏览器exe(键)
        支持 = 键 in _支持
        结果.append({
            '浏览器': 键,
            '名称': _展示名.get(键, 键),
            '支持': 支持,
            '已安装': bool(exe),
            '路径': exe or '',
            '版本': _文件版本(exe) if exe else '',
            '说明': ('' if 支持 else _不支持原因.get(键, '不支持的浏览器'))
                    or _备注.get(键, ''),
        })
    结果.sort(key=lambda x: (not (x['已安装'] and x['支持']),      # 已装且支持优先
                             not x['支持'],                        # 支持优先于不支持
                             _排序.index(x['浏览器'])))
    return 结果


def _复制剪贴板(文本: str) -> bool:
    """把文本放进系统剪贴板 (PowerShell → tkinter 双路兜底)。"""
    try:
        subprocess.run(
            ['powershell', '-NoProfile', '-Command', 'Set-Clipboard -Value $env:NC_CLIP'],
            env={**os.environ, 'NC_CLIP': 文本}, timeout=10,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return True
    except Exception:
        pass    # 刻意静默: 降级到 tkinter
    try:
        import tkinter
        r = tkinter.Tk()
        r.withdraw()
        r.clipboard_clear()
        r.clipboard_append(文本)
        r.update()
        r.destroy()
        return True
    except Exception:
        return False


def 打开扩展页(浏览器: str) -> dict:
    """唤起浏览器 + 把**扩展页地址复制到剪贴板** (装完复制件后引导用户加载)。

    ⚠️ 为什么不是直接用命令行打开扩展页 (2026-10-20 用户实测"点了没反应"):
    Chromium 自 M76 起**禁止命令行传入 chrome:// 地址** (安全策略) —— 浏览器
    已在运行时, 参数被转发给现有实例后直接忽略, 用户什么都看不到。可靠路径:
    ① 启动/唤起浏览器; ② 地址已在剪贴板; ③ 用户 Ctrl+L → Ctrl+V → 回车,
    一次粘贴就落在扩展页, 再点「加载已解压」。

    Returns: {ok, 原因, 已复制, 提示}
    """
    浏览器 = (浏览器 or '').lower()
    if 浏览器 not in _支持:
        return {'ok': False, '原因': f'不支持的浏览器: {浏览器}', '已复制': False, '提示': ''}
    名 = _浏览器名[浏览器]
    网址 = _扩展页[浏览器]
    已复制 = _复制剪贴板(网址)
    粘贴提示 = (f'扩展页地址已复制到剪贴板：{网址}\n切到浏览器按 Ctrl+L 再 Ctrl+V 回车即可打开。'
              if 已复制 else f'请在浏览器地址栏输入：{网址}')
    exe = _浏览器exe(浏览器)
    if not exe:
        return {'ok': False, '原因': f'没找到 {名} 主程序（未安装？）', '已复制': 已复制,
                '提示': 粘贴提示}
    try:
        subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        return {'ok': False, '原因': f'启动 {名} 失败: {e}', '已复制': 已复制, '提示': 粘贴提示}
    return {'ok': True, '原因': '', '已复制': 已复制, '提示': 粘贴提示}


def 心跳路径() -> str:
    return str(_状态根() / '数据' / '插件心跳.json')


def 记心跳(来源: str = '') -> None:
    """插件每次调用接口时由服务端调用 (插件在线证据)。"""
    try:
        p = Path(心跳路径())
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({'ts': time.time(), '来源': 来源}, ensure_ascii=False),
                     encoding='utf-8')
    except OSError as e:
        _log.debug(f'[插件安装] 心跳写入失败: {type(e).__name__}: {e}')


def 心跳状态() -> dict:
    """{已连接: bool, 秒前: int, 时间: 'HH:MM'} —— 供 GUI 状态行显示。"""
    try:
        d = json.loads(Path(心跳路径()).read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return {'已连接': False, '秒前': -1, '时间': ''}
    ts = float(d.get('ts') or 0)
    秒前 = max(0, int(time.time() - ts)) if ts else -1
    return {'已连接': 0 <= 秒前 <= _心跳新鲜秒, '秒前': 秒前,
            '时间': time.strftime('%H:%M', time.localtime(ts)) if ts else ''}


def 状态文案() -> str:
    s = 心跳状态()
    if s['已连接']:
        if s['秒前'] < 60:
            return f'✅ 插件已连接（刚刚同步过）'
        return f'✅ 插件已连接（{s["秒前"] // 60} 分钟前同步）'
    if s['秒前'] >= 0:
        return f'⚠️ 插件最后活跃于 {s["时间"]}，可能已关闭或未安装'
    return '⬜ 插件未安装（点下面按钮安装）'
