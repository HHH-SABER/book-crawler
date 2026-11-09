# -*- coding: utf-8 -*-
"""远控服务安全中间件 (2026-11-09, 落地 10-26 安全体检的 R-M01/R-M02/R-M03)。

来源: `security_best_practices_report.md`（2026-10-26 体检，三项未修）
  R-M01 无安全响应头 (OWASP A05 安全配置错误)          → 安全头中间件
  R-M02 无 Host 校验 (DNS rebinding / Host 注入)       → 主机校验中间件
  R-M03 认证失败无限流 (token 爆破/资源耗尽)            → 失败限流中间件

**与体检报告原建议的两处偏离（都有实测理由）**:
  ① CSP 不能照抄 `script-src 'self'` —— `面板.html` 有 2 处 `onclick=` + 1 段
     内联 `<script>`、`阅读.html` 同理，11 处内联 `style=` ⇒ 严格 CSP 会直接
     打坏面板。改为 `'unsafe-inline'`（脚本/样式），保留真正有收益的部分:
     `frame-ancestors 'none'`(防点击劫持) + `nosniff` + `no-referrer`。
     后续若要收紧，需先把内联脚本外置成 .js（另立一项）。
  ② Host 校验不走 TrustedHostMiddleware 固定白名单 —— 外网走 Tailscale
     `*.ts.net`、局域网走任意私网 IP，固定白名单会打断用户既有通路。改为
     **按语义放行**: 回环/私网 IP 字面量 + localhost + *.ts.net + *.local，
     公网域名一律拒绝（DNS rebinding 用的正是公网域名）；需要自定义域名时
     在 远控配置.json 的 `允许主机` 里加，不用改代码。
"""
import ipaddress
import threading
import time
from typing import Dict, List

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# ---- R-M01 安全响应头 -------------------------------------------------
# 注: unsafe-inline 是本项目面板/阅读页的现状所需 (见模块 docstring ①)
_CSP = ("default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'none'; "
        "form-action 'self'")

_安全头 = {
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Referrer-Policy': 'no-referrer',
    'Content-Security-Policy': _CSP,
}


class 安全头中间件(BaseHTTPMiddleware):
    """给所有响应补安全头 (含 400/429 等异常响应)。"""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        for 名, 值 in _安全头.items():
            # setdefault 语义: 端点自己设了就尊重端点
            if 名 not in response.headers:
                response.headers[名] = 值
        return response


# ---- R-M02 Host 校验 --------------------------------------------------
_本机别名 = frozenset({'localhost', 'testserver', 'ip6-localhost'})
_放行后缀 = ('.ts.net', '.local', '.localhost')


def _取主机名(host头: str) -> str:
    """从 Host 头取主机名: 去端口、去 IPv6 方括号、小写。"""
    值 = (host头 or '').strip().lower()
    if not 值:
        return ''
    if 值.startswith('['):                      # [::1]:8760
        结束 = 值.find(']')
        return 值[1:结束] if 结束 > 0 else ''
    return 值.rsplit(':', 1)[0] if ':' in 值 else 值


def 主机是否允许(host头: str, 额外允许=()) -> bool:
    """Host 是否放行 (纯函数, 可单测)。规则见模块 docstring ②。"""
    主机 = _取主机名(host头)
    if not 主机:
        return False
    if 主机 in _本机别名 or 主机 in {str(h).strip().lower() for h in 额外允许}:
        return True
    try:                                        # IP 字面量: 回环/私网放行
        ip = ipaddress.ip_address(主机)
        return bool(ip.is_loopback or ip.is_private or ip.is_link_local)
    except ValueError:
        pass                                    # 非 IP → 按域名判定
    return any(主机.endswith(后缀) for 后缀 in _放行后缀)


def _额外允许主机() -> tuple:
    """远控配置里的 `允许主机` 列表 (自定义域名/反代时用)。"""
    try:
        from .配置 import 取配置
        值 = 取配置().get('允许主机') or ()
        return tuple(值) if isinstance(值, (list, tuple)) else ()
    except Exception:
        return ()                               # 刻意静默: 配置读不到就用默认放行集


class 主机校验中间件(BaseHTTPMiddleware):
    """非本机/私网/放行后缀的 Host → 400 (挡 DNS rebinding)。"""

    async def dispatch(self, request, call_next):
        host = request.headers.get('host', '')
        if not 主机是否允许(host, _额外允许主机()):
            return JSONResponse(
                {'detail': f'不被允许的 Host: {host or "(空)"}。'
                           f'如用自定义域名，请在 远控配置.json 的「允许主机」里添加。'},
                status_code=400)
        return await call_next(request)


# ---- R-M03 认证失败限流 -----------------------------------------------
_窗口秒 = 60
_失败上限 = 30          # 同 IP 每窗口允许的 401 次数
_跟踪IP上限 = 200       # 防无界增长


class 失败限流中间件(BaseHTTPMiddleware):
    """同 IP 每分钟 401 超限 → 429。

    只统计 **401 (认证失败)**: 正常浏览/轮询带对的 token, 不受影响;
    攻击者用错 token 扫站时才会被挡。
    """

    def __init__(self, app):
        super().__init__(app)
        self._记录: Dict[str, List[float]] = {}
        self._锁 = threading.Lock()

    def _客户端(self, request) -> str:
        return (request.client.host if request.client else '') or '未知'

    def _是否超限(self, 客户端: str, now: float) -> bool:
        with self._锁:
            最近 = [t for t in self._记录.get(客户端, ()) if now - t < _窗口秒]
            self._记录[客户端] = 最近
            return len(最近) >= _失败上限

    def _记失败(self, 客户端: str, now: float) -> None:
        with self._锁:
            表 = self._记录.setdefault(客户端, [])
            表.append(now)
            if len(self._记录) > _跟踪IP上限:
                # 上限保护: 先清过期项; 仍超限则淘汰"最近一次失败最早"的条目
                # (全是新记录时也能收敛 —— 早期写法只清过期项, 实测不收敛)
                for ip in [k for k, v in self._记录.items()
                           if not v or now - v[-1] >= _窗口秒]:
                    self._记录.pop(ip, None)
                while len(self._记录) > _跟踪IP上限:
                    最旧 = min(self._记录.items(), key=lambda kv: kv[1][-1] if kv[1] else 0)[0]
                    self._记录.pop(最旧, None)

    def 重置(self) -> None:
        with self._锁:
            self._记录.clear()

    async def dispatch(self, request, call_next):
        客户端 = self._客户端(request)
        now = time.monotonic()
        if self._是否超限(客户端, now):
            return JSONResponse({'detail': '认证失败次数过多，请稍后重试'},
                                status_code=429)
        response = await call_next(request)
        if response.status_code == 401:
            self._记失败(客户端, now)
        return response


def 安装(app) -> None:
    """按正确顺序装三个中间件到 FastAPI app。

    顺序 (后添加的在外层): 安全头 → 主机校验 → 限流
    这样 400/429 也带安全头, 且限流不会先于主机校验执行。
    """
    app.add_middleware(失败限流中间件)
    app.add_middleware(主机校验中间件)
    app.add_middleware(安全头中间件)
