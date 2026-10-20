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

_支持 = ('chrome', 'edge')
_浏览器名 = {'chrome': 'Chrome', 'edge': 'Edge'}
_扩展页 = {'chrome': 'chrome://extensions', 'edge': 'edge://extensions'}

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
            f'1. 在打开的 {_浏览器名[浏览器]} 扩展页, 打开右上角「开发者模式」',
            '2. 点「加载已解压的扩展程序」',
            f'3. 粘贴并选择目录:  {目标}',
            '4. 点插件图标, 填入端口(8760)与 token (远控页可复制), 点「保存设置并测试连通」',
        ],
    }


def _浏览器exe(浏览器: str) -> Optional[str]:
    """定位浏览器主程序 (注册表 App Paths → 常见安装路径)。"""
    try:
        import winreg
        键s = ([r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe']
               if 浏览器 == 'chrome' else
               [r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe'])
        for 键 in 键s:
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
    常见 = ([
        r'C:\Program Files\Google\Chrome\Application\chrome.exe',
        r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
    ] if 浏览器 == 'chrome' else [
        r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
    ])
    本地 = Path(os.environ.get('LOCALAPPDATA', ''))
    常见.append(str(本地 / ('Google/Chrome/Application/chrome.exe' if 浏览器 == 'chrome'
                          else 'Microsoft/Edge/Application/msedge.exe')))
    for p in 常见:
        if p and os.path.isfile(p):
            return p
    return None


def 打开扩展页(浏览器: str) -> dict:
    """打开该浏览器的扩展管理页 (装完复制件后引导用户加载)。"""
    浏览器 = (浏览器 or '').lower()
    if 浏览器 not in _支持:
        return {'ok': False, '原因': f'不支持的浏览器: {浏览器}'}
    exe = _浏览器exe(浏览器)
    if not exe:
        return {'ok': False,
                '原因': f'没找到 {_浏览器名[浏览器]} 主程序 (未安装?) —— 可手动打开 {_扩展页[浏览器]}'}
    try:
        subprocess.Popen([exe, _扩展页[浏览器]],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {'ok': True, '原因': ''}
    except OSError as e:
        return {'ok': False, '原因': f'启动失败: {e}'}


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
