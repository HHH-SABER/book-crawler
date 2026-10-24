# -*- coding: utf-8 -*-
"""自定义协议唤起 (novelcrawler://) —— 让浏览器插件一键把任务交给程序 (2026-10-23)。

用户需求: 在插件里点「开始抓取」→ **自动唤起程序**并开始下载, 可选
「完整抓取 / 章节区间」。

为什么需要协议: 浏览器不能直接启动本地 exe; 唯一标准途径是注册一个自定义
URL 协议 (HKCU\\Software\\Classes\\<协议>), 之后任何页面/插件导航到
`novelcrawler://crawl?...` 都会由 Windows 拉起本程序。

流程:
  插件 POST 远控 API 建任务 (程序已在跑) —— 最快路径;
  失败(程序没开) → 插件打开 novelcrawler:// URL → 系统拉起程序 →
  本模块解析参数; 若发现已有实例在跑则**转发给它并退出**(不弹第二个窗口)。

协议格式:
  novelcrawler://crawl?url=<编码后的目录页>&mode=full|range&start=1&end=20
"""
import json
import os
import sys
import urllib.parse
import urllib.request

协议名 = 'novelcrawler'


# --------------------------------------------------------------------- 解析
def 取唤起参数(argv=None) -> dict:
    """从命令行参数里取唤醒指令; 没有则返回 {}。

    返回 {url, mode, start, end} (mode ∈ full/range; start/end 为 int 或 0)。
    """
    argv = list(sys.argv if argv is None else argv)
    for 参数 in argv[1:]:
        if not isinstance(参数, str) or not 参数.lower().startswith(协议名 + '://'):
            continue
        解析 = urllib.parse.urlsplit(参数)
        查询 = urllib.parse.parse_qs(解析.query)
        url = (查询.get('url') or [''])[0].strip()
        if not url:
            return {}
        mode = (查询.get('mode') or ['full'])[0].strip().lower()
        if mode not in ('full', 'range'):
            mode = 'full'

        def _整数(名):
            """未提供/非法 → 0 (= 未指定); 提供则夹到 >= 1。"""
            原始 = str((查询.get(名) or [''])[0]).strip()
            if not 原始:
                return 0
            try:
                return max(1, int(原始))
            except (TypeError, ValueError):
                return 0

        return {'url': url, 'mode': mode,
                'start': _整数('start'), 'end': _整数('end')}
    return {}


# --------------------------------------------------------------------- 注册
def 注册命令(协议: str = 协议名) -> dict:
    """返回要写入注册表的 (协议键, 启动命令) —— 纯函数, 便于测试。"""
    if getattr(sys, 'frozen', False):
        程序 = os.path.abspath(sys.executable)
        命令 = f'"{程序}" "%1"'
    else:
        启动器 = os.path.join(os.path.dirname(os.path.abspath(__file__)), '启动器.py')
        命令 = f'"{os.path.abspath(sys.executable)}" "{启动器}" "%1"'
    return {'键': rf'Software\Classes\{协议}', '命令': 命令}


def 注册协议() -> bool:
    """注册/刷新协议 (HKCU, 无需管理员)。已注册则幂等覆盖。"""
    try:
        import winreg
        info = 注册命令()
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, info['键']) as k:
            winreg.SetValueEx(k, '', 0, winreg.REG_SZ, f'URL:{协议名} Protocol')
            winreg.SetValueEx(k, 'URL Protocol', 0, winreg.REG_SZ, '')
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              info['键'] + r'\shell\open\command') as k:
            winreg.SetValueEx(k, '', 0, winreg.REG_SZ, info['命令'])
        return True
    except Exception:
        return False    # 刻意静默: 注册失败不影响程序本身, 只少了"唤起"能力


# --------------------------------------------------------------------- 转发
def 转发到已运行实例(参数: dict, 超时: float = 3.0) -> bool:
    """把任务转发给已运行的实例 (走远控 API)。成功返回 True。

    这是"程序已经在跑, 用户又从浏览器点了一次"的路径 —— 不弹第二个窗口,
    直接把任务塞进现有实例。
    """
    if not 参数.get('url'):
        return False
    try:
        from 远控.配置 import 取配置
        cfg = 取配置()
        端口 = int(cfg.get('端口') or 8760)
        token = str(cfg.get('token') or '')
    except Exception:
        return False
    if not token:
        return False
    主体 = {'url': 参数['url'], 'mode': 参数.get('mode', 'full'),
            'resume': True, 'unique_title': True}
    if 参数.get('mode') == 'range':
        起 = int(参数.get('start') or 1)
        终 = int(参数.get('end') or 0)
        if 终 < 起:
            return False
        主体['chapter_range'] = [起, 终]
    # 内联校验 (Mimosa 要求 URL 验证在函数内): 目标钉死本机环回远控端点
    # (客户端唤起本机已有实例, 环回即设计意图); 端口取自本机配置, 合法范围
    # 1-65535, 越界/被篡改直接拒绝
    if not (isinstance(端口, int) and 1 <= 端口 <= 65535):
        return False
    _u = urllib.parse.urlparse(f'http://127.0.0.1:{端口}/api/v1/tasks')
    if _u.scheme != 'http' or _u.hostname != '127.0.0.1' or _u.port != 端口:
        return False
    try:
        req = urllib.request.Request(
            f'{_u.scheme}://{_u.hostname}:{_u.port}/api/v1/tasks', method='POST',
            data=json.dumps(主体).encode('utf-8'),
            headers={'Content-Type': 'application/json',
                     'Authorization': f'Bearer {token}'})
        with urllib.request.urlopen(req, timeout=超时) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


def 有已运行实例(超时: float = 1.5) -> bool:
    """轻量探活: 远控 healthz 是否在监听 (不发任务)。"""
    try:
        from 远控.配置 import 取配置
        端口 = int(取配置().get('端口') or 8760)
    except Exception:
        return False
    try:
        with urllib.request.urlopen(
                f'http://127.0.0.1:{端口}/api/v1/healthz', timeout=超时) as r:
            return 200 <= r.status < 300
    except Exception:
        return False
