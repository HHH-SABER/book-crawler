# -*- coding: utf-8 -*-
"""轻量更新检查 (C7 分发形态评估的落地项, 2026-10-17)。

**C7 评估结论** (文档/实施计划.md): 维持便携单文件分发, **不引入安装器** ——
安装器的传统三大收益里, 桌面快捷方式 (首启自建, 首次引导.py) 与"开始菜单
等价物"已被更轻的方案覆盖, 卸载条目对少数人分发场景价值低; 而安装器**不解决
唯一真痛点**: 290MB 新版本要手动去 GitHub 下载替换。本模块补这一环。

**边界 (保守设计, 对齐项目"公网请求最小化"基调)**:
  · **只读一次 GitHub API** (releases/latest), 不下载、不静默替换 —— 只告诉
    用户"有新版本", 用户自己点开 Release 页决定 (安全: 更新动作永远在人手里);
  · 任何失败 (离线/超时/限流/坏 JSON) → None + debug 日志, **绝不抛**;
  · 不在启动时自动检查 (零网络意外) —— 只由用户点侧栏版本按钮触发;
  · 比较按数字段元组 (2.5.10 > 2.5.9), 忽略 v 前缀与非数字尾巴。

依赖: requests (既有)。本模块 **不 import flet** (CLI/测试可直接用)。
"""
import ipaddress
import json
import re
import socket
import threading
from urllib.parse import urlparse

import 日志 as _app_log
_log = _app_log.get('更新检查')

_LOCK = threading.Lock()

# 公开仓库 (与 .github/workflows/release.yml、README 同一地址; 非站点/书名信息)
_仓库 = 'HHH-SABER/book-crawler'
_API = f'https://api.github.com/repos/{_仓库}/releases/latest'
_发布页 = f'https://github.com/{_仓库}/releases'


def 取当前版本() -> str:
    """当前版本: EXE 读版本资源 (ProductVersion), 源码读 脚本/版本.json。

    与 gui_app._读显示版本 同口径 (那边给窗口标题用, 这边给比对用; 两处各存
    一份是刻意的分层 —— 本模块不 import flet, CLI/测试环境可直接调)。
    失败返回 '' (调用方按"未知版本"处理: 不阻断检查)。
    """
    import os
    import sys
    try:
        if getattr(sys, 'frozen', False):
            import ctypes
            size = ctypes.windll.version.GetFileVersionInfoSizeW(
                sys.executable, None)
            if size:
                data = ctypes.create_string_buffer(size)
                if ctypes.windll.version.GetFileVersionInfoW(
                        sys.executable, 0, size, data):
                    ptr = ctypes.c_void_p()
                    ln = ctypes.c_uint()
                    if ctypes.windll.version.VerQueryValueW(
                            data, '\\VarFileInfo\\Translation',
                            ctypes.byref(ptr), ctypes.byref(ln)) and ln.value >= 4:
                        pair = ctypes.cast(
                            ptr, ctypes.POINTER(ctypes.c_uint16 * 2)).contents
                        key = (f'\\StringFileInfo\\{pair[0]:04x}{pair[1]:04x}'
                               f'\\ProductVersion')
                        if ctypes.windll.version.VerQueryValueW(
                                data, key, ctypes.byref(ptr), ctypes.byref(ln)):
                            return ctypes.wstring_at(ptr.value).strip()
        else:
            p = os.path.normpath(os.path.join(
                os.path.dirname(os.path.abspath(__file__)), '..', '脚本', '版本.json'))
            with open(p, encoding='utf-8') as f:
                return str(json.load(f).get('版本', '')).strip()
    except Exception as _e:
        _log.debug(f'裸 except 吞异常: {type(_e).__name__}: {_e} (取当前版本失败)')
    return ''


def _版本元组(标签: str) -> tuple:
    """'v2.5.40' / '2.5.40-beta' → (2, 5, 40); 无数字 → ()。"""
    数字 = re.findall(r'\d+', 标签 or '')
    return tuple(int(x) for x in 数字[:4]) if 数字 else ()


def 有新版本(当前: str, 最新: str) -> bool:
    """最新是否严格新于当前 (按数字段; 任一侧解析不出数字 → False 不打扰)。"""
    a, b = _版本元组(当前), _版本元组(最新)
    if not a or not b:
        return False
    return b > a


def 检查更新(超时秒: int = 10) -> dict | None:
    """查 GitHub 最新 Release, 与当前版本比对。

    Returns:
        {'当前版', '最新版', '发布页', '有新版'} 或 None (任何失败/无法判定)。
        永不抛异常。
    """
    try:
        import requests
        # 内联校验 (Mimosa 要求 URL 验证在函数内): 端点钉死本仓库 GitHub API;
        # 解析后 IP 落在私网/环回/链路本地即放弃 (防 DNS rebinding/内网指向);
        # 禁重定向 (releases/latest 本就 200 直回, 无需跟随)
        _u = urlparse(_API)
        if _u.scheme != 'https' or _u.hostname != 'api.github.com':
            _log.debug(f'更新检查端点异常, 放弃: {_API}')
            return None
        try:
            for _inf in socket.getaddrinfo(_u.hostname, 443):
                _a = ipaddress.ip_address(_inf[4][0])
                if (_a.is_private or _a.is_loopback or _a.is_link_local
                        or _a.is_reserved or _a.is_multicast):
                    _log.debug(f'更新检查端点解析到非公网 IP, 放弃: {_a}')
                    return None
        except OSError as _e:
            _log.debug(f'更新检查端点解析失败: {type(_e).__name__}')
            return None
        resp = requests.get(_API, timeout=(5, 超时秒),
                            allow_redirects=False,
                            headers={'Accept': 'application/vnd.github+json',
                                     'User-Agent': 'novel-crawler-update-check'})
        resp.raise_for_status()
        数据 = resp.json()
    except Exception as _e:
        _log.debug(f'裸 except 吞异常: {type(_e).__name__}: {_e} (更新检查失败, 静默)')
        return None
    try:
        if not isinstance(数据, dict):
            return None
        最新 = str(数据.get('tag_name', '') or '').strip()
        if not 最新:
            return None
        当前 = 取当前版本()
        return {
            '当前版': 当前 or '未知',
            '最新版': 最新.lstrip('vV'),
            '发布页': str(数据.get('html_url', '') or _发布页),
            '有新版': 有新版本(当前, 最新),
        }
    except Exception as _e:
        _log.debug(f'裸 except 吞异常: {type(_e).__name__}: {_e} (更新检查响应解析失败)')
        return None


def _自检():
    """模块自检: 版本比较逻辑 (不打网络)。"""
    assert 有新版本('2.5.9', '2.5.10') is True, '按数字段比, 不是按字符串'
    assert 有新版本('2.5.40', '2.5.40') is False
    assert 有新版本('2.5.41', '2.5.40') is False
    assert 有新版本('', '2.5.40') is False, '当前版本未知不打扰'
    assert 有新版本('2.5.40', '') is False
    assert _版本元组('v2.5.40') == (2, 5, 40)
    assert _版本元组('dev') == ()
    return True


if __name__ == '__main__':
    _自检()
    print('版本比较逻辑 OK; 当前版本:', 取当前版本() or '(未知)')
