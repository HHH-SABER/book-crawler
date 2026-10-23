# -*- coding: utf-8 -*-
import 日志 as _app_log
_log = _app_log.get('请求引擎')

"""多引擎请求封装 (requests + curl_cffi + cloudscraper 自动降级)
============================================================

在自研反爬识别 (反爬检测器.py) 的基础上, 引入成熟反爬库作为请求引擎:

- requests      : 默认引擎 (现有 session, cookie/代理/验证码流程完全兼容)
- curl_cffi     : 模拟浏览器 TLS 指纹 + HTTP/2 (绕过基于 TLS 指纹的校验)
- cloudscraper  : 自动执行 Cloudflare / DDoS-Guard 等 JS 质询, 无需浏览器

自动降级链 (依据反爬识别结果选择引擎):
    JS质询类 (waf_js_challenge / js_cookie / dynamic_token)
        → cloudscraper → (连续失败) → curl_cffi → requests
    其它机制 → requests (交现有 WAF验证码/退避/UA轮换流程)

设计原则:
- 纯标准库 + 两个可选第三方库, 未安装时静默降级为 requests (不影响主流程)
- 统一 引擎响应 对象, 兼容调用方对 requests.Response 的属性访问
  (status_code/text/content/headers/encoding/apparent_encoding)
- 按域名缓存 curl_cffi / cloudscraper 会话 (避免跨站 cookie 混淆 + 提升性能)
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import urlparse
import json
import os
import threading

# ------------------------------------------------------------------
# 按域 Cookie 注入 (站点脱钩: 登录态凭证外置 站点适配_本地/域名cookies.json, 不入库)
# ------------------------------------------------------------------
# 数据形态: {"注册域": "k=v; k2=v2"} (如 {"siteI.example": "uid=1; sid=abc"})
# 注入规则: 请求 host 与键互为后缀匹配 (注册域语义, siteI.example ↔ www.siteI.example);
#          调用方显式传入的 Cookie 头不覆盖 (显式优先);
#          文件 mtime 热检 (30s) —— Cookie 更新后免重启生效。
_域COOKIE: Dict[str, str] = {}
_COOKIE文件状态 = {'mtime': None, '检查': 0.0}
_COOKIE热检间隔 = 30.0


def _加载域COOKIE():
    """惰性加载 + 30s 热检; 文件缺失 (公开形态) 即空表, 不影响请求"""
    import time as _time
    _now = _time.time()
    if _now - _COOKIE文件状态['检查'] < _COOKIE热检间隔:
        return
    _COOKIE文件状态['检查'] = _now
    try:
        from _path_utils import get_app_base_dir
        _p = os.path.join(get_app_base_dir(), '站点适配_本地', '域名cookies.json')
        if not os.path.isfile(_p):
            return
        _mtime = os.path.getmtime(_p)
        if _mtime == _COOKIE文件状态['mtime']:
            return
        with open(_p, 'r', encoding='utf-8') as f:
            _data = json.load(f)
        if isinstance(_data, dict):
            # 2026-10-24 审查 W2: **引用整体替换** (真正原子)。
            # 旧写法 clear()+update() 两步之间, 并发请求会看到空表 → 漏注入
            # Cookie (偶发一章 403)。改为先构造新表、再整体换引用: 读者
            # (注入COOKIE) 每次从全局取名, 要么拿到旧表要么新表, 不会看到空表。
            global _域COOKIE
            _域COOKIE = {str(k).strip().lower(): str(v)
                        for k, v in _data.items() if k and v}
        _COOKIE文件状态['mtime'] = _mtime
    except Exception as _e:
        try:
            _log.debug(f'[引擎] 域Cookie 加载失败 (不影响请求): {type(_e).__name__}')
        except Exception:
            pass  # 刻意静默: 极早期调用日志链路未就绪


def 注入COOKIE(headers, url):
    """按域名匹配注入登录 Cookie (返回新 headers; 不修改调用方的 dict)。

    匹配: URL host 与配置键互为后缀 (注册域语义)。调用方显式传了
    Cookie 头时不覆盖。公开形态 (无域名cookies.json) 恒等返回原 headers。
    """
    _加载域COOKIE()
    if not _域COOKIE:
        return headers
    if headers and any(str(k).lower() == 'cookie' for k in headers):
        return headers
    try:
        _host = (urlparse(url).netloc or '').split('@')[-1].split(':')[0].lower()
    except Exception:
        return headers
    if not _host:
        return headers
    for _域, _ck in _域COOKIE.items():
        if _host == _域 or _host.endswith('.' + _域) or _域.endswith('.' + _host):
            _merged = dict(headers) if headers else {}
            _merged['Cookie'] = _ck
            return _merged
    return headers

# ------------------------------------------------------------------
# 引擎可用性探测 (惰性, 不强制依赖)
# ------------------------------------------------------------------
def _探测_curl_cffi():
    try:
        from curl_cffi import requests as _cr
        return _cr
    except Exception:
        return None


def _探测_cloudscraper():
    try:
        import cloudscraper
        return cloudscraper
    except Exception:
        return None


_curl_cffi = _探测_curl_cffi()
_cloudscraper = _探测_cloudscraper()
# (U25) 原此处有 `_引擎顺序 = ('curl_cffi', 'cloudscraper')` —— 全仓库零引用,
# 已删除。降级链的实际顺序由 _选择引擎() 与各 _请求_* 实现决定。


@dataclass
class 引擎响应:
    """统一响应对象 (各引擎响应归一化, 兼容 requests.Response 常用属性)"""
    status_code: int = 0
    headers: Dict = field(default_factory=dict)
    text: str = ''
    content: bytes = b''
    url: str = ''
    引擎: str = 'requests'
    历史URL: List[str] = field(default_factory=list)   # R05: 重定向链每一跳

    def __post_init__(self):
        self._编码: Optional[str] = None
        self._text = self.text
        if self.content is None:
            self.content = b''

    @property
    def 成功(self) -> bool:
        return 200 <= self.status_code < 400

    # ---- requests.Response 兼容: encoding / apparent_encoding / text ----
    @property
    def encoding(self) -> str:
        return self._编码 or 'utf-8'

    @encoding.setter
    def encoding(self, value: str):
        self._编码 = value

    @property
    def apparent_encoding(self) -> str:
        """基于 content 字节猜测编码 (P8-C13, 2026-10-24)。

        判定链: chardet (装了就用) → 内置字符集探测 (零依赖统计法) → utf-8。
        内置探测解决"声明 utf-8 实际 GBK/Big5"的谎报页面 —— 旧实现在无
        chardet 时恒返回 utf-8, 谎报页解出乱码被质检误判降级。"""
        if self.content:
            try:
                import chardet
                结果 = chardet.detect(self.content)
                if 结果 and 结果.get('encoding'):
                    return 结果['encoding']
            except Exception as _e:
                _log.debug(f'裸 except 吞异常: {type(_e).__name__}: {_e}')
            try:
                import 字符集探测
                编码, 依据 = 字符集探测.探测(self.content)
                if 依据 != 'default':
                    _log.debug(f'[字符集] 探测: {编码} (依据={依据})')
                return 编码
            except Exception as _e:
                _log.debug(f'[字符集] 探测失败回落 utf-8: '
                           f'{type(_e).__name__}: {_e}')
        return 'utf-8'

    @property
    def text(self) -> str:
        """显式设置 encoding 后按该编码重新解码 content"""
        if self._编码 and self.content:
            try:
                return self.content.decode(self._编码, errors='replace')
            except (LookupError, UnicodeDecodeError) as _e:
                _log.debug(f'裸 except 吞异常: {type(_e).__name__}: {_e}')
        return self._text

    @text.setter
    def text(self, value: str):
        self._text = value or ''


def _统计域名(url: str) -> str:
    """取统计用域名 (小写、去 www 前缀); 失败返回 '(未知)'。"""
    try:
        from urllib.parse import urlparse
        主机 = (urlparse(str(url)).hostname or '').lower()
        if 主机.startswith('www.'):
            主机 = 主机[4:]
        return 主机 or '(未知)'
    except Exception:
        return '(未知)'


# P8-C2 (2026-10-24): 层命中统计参数
_域名统计上限 = 100        # 域名桶上限 (超出聚合到"(其他)", 防无界增长)
_汇总间隔 = 50             # 每 N 次成功请求输出一行汇总 (不逐请求刷屏)


class 请求引擎管理器:
    """多引擎管理器: 按反爬机制选择引擎, 支持连续失败自动降级"""

    def __init__(self):
        self.可用 = {
            'requests': True,
            'curl_cffi': _curl_cffi is not None,
            'cloudscraper': _cloudscraper is not None,
        }
        self._curl_cffi = _curl_cffi
        self._cloudscraper = _cloudscraper
        self._失败计数: Dict[str, int] = {}       # {引擎: 连续失败次数}
        self._降级阈值 = 3                          # 连续失败 N 次 → 降级到更高一级引擎
        # P8-C2 层命中统计 (2026-10-24)
        self._降级次数 = 0                          # 降级实际发生次数 (非阈值触发)
        self._域名统计: Dict[str, Dict[str, int]] = {}   # 域名 → {引擎: 成功次数}
        self._成功总数 = 0
        self._汇总输出次数 = 0
        self._curl_sessions: Dict[str, object] = {}        # host → curl_cffi.Session
        self._cloudscraper_sessions: Dict[str, object] = {}  # host → CloudScraper
        self._requests_sessions: Dict[str, object] = {}  # host → requests.Session
        # 共享 Session 的 CookieJar 非线程安全: 并发 worker 同时走引擎路径时
        # 可能丢 cookie (破坏 P1-8 的会话隔离)。引擎路径本身低频 (仅反爬机制命中),
        # 用进程级锁串行化, 保留连接复用同时消除竞态
        self._requests_lock = threading.Lock()
        # 修复(U15): 会话缓存曾"锁外建连" —— get 到 set 之间无保护, 并发 worker
        # 会各自 new 一个同 host 会话, 后被覆盖的那个永久泄漏 (无人 close)。
        # 单开一把锁保护三个缓存的读-改-写, 不与请求锁耦合。
        self._会话缓存锁 = threading.Lock()
        self._统计: Dict[str, int] = {}            # {引擎: 成功请求次数}

    def close(self):
        """释放全部缓存会话 (进程收尾/测试用; 管理器为进程级单例, 任务运行中勿调)"""
        for d in (self._requests_sessions, self._curl_sessions,
                  self._cloudscraper_sessions):
            for s in list(d.values()):
                try:
                    s.close()
                except Exception as _e:
                    _log.debug(f'裸 except 吞异常: {type(_e).__name__}: {_e}')
            d.clear()

    # ------------------------------------------------------------------
    # 对外 API
    # ------------------------------------------------------------------
    def 请求(self, url, headers=None, timeout=15, 引擎='auto', 机制='none',
             cookies=None, proxies=None, 支持重定向=True) -> Optional[引擎响应]:
        """按指定引擎 (或按反爬机制自动选择) 发起请求。

        Args:
            url: 目标 URL
            headers: 请求头 dict
            timeout: 超时秒数
            引擎: 'auto'=按机制自动选择, 或 'requests'/'curl_cffi'/'cloudscraper'
            机制: 反爬检测器识别出的机制 (用于 auto 选择)
            cookies: 附加 cookie dict
            proxies: 代理 dict
            支持重定向: 是否跟随重定向

        Returns:
            引擎响应; 引擎不可用或请求失败返回 None (调用方应保留原响应走现有流程)
        """
        # R05 地址安全预检: 目标 URL 私网/保留段/协议拦截 (fail-closed)
        from 地址安全 import 校验URL, 校验响应
        _安全, _理由 = 校验URL(url)
        if not _安全:
            _log.info(f"[地址安全] 拦截请求: {_理由} ({str(url)[:80]})")
            return None
        # 按域 Cookie 注入 (站点脱钩: 登录态外置; 调用方显式 Cookie 优先)
        headers = 注入COOKIE(headers, url)
        if 引擎 == 'auto':
            引擎 = self._选择引擎(机制)
        方法 = getattr(self, f'_请求_{引擎}', None)
        if 方法 is None or not self.可用.get(引擎):
            return None
        响应 = 方法(url, headers=headers, timeout=timeout,
                  cookies=cookies, proxies=proxies, 支持重定向=支持重定向)
        if 响应 is None:
            # 修复(U1): 引擎"抛异常→返回 None"也必须计入失败。
            # 旧实现只在 `响应 is not None` 分支里累计失败, 于是连接级失败
            # (超时/DNS 解析失败/拒绝连接) 永不触发降级 —— cloudscraper 一直失败,
            # 却永远轮不到 _选择引擎() 把它切到 curl_cffi。
            self._失败计数[引擎] = self._失败计数.get(引擎, 0) + 1
            _log.info(f"[引擎] {引擎} 请求未成功(连接级), 连续失败 "
                      f"{self._失败计数[引擎]}/{self._降级阈值}")
            return None
        # R05 地址安全终检: 最终 URL + 重定向链每一跳 (浏览器引擎无法逐跳, 终检兜底)
        _安全, _理由 = 校验响应(响应)
        if not _安全:
            _log.info(f"[地址安全] 拦截响应: {_理由} ({str(响应.url)[:80]})")
            self._失败计数[引擎] = self._失败计数.get(引擎, 0) + 1
            return None
        if 响应.成功:
            self._统计[引擎] = self._统计.get(引擎, 0) + 1
            self._失败计数[引擎] = 0
            self._记域名命中(url, 引擎)
        else:
            self._失败计数[引擎] = self._失败计数.get(引擎, 0) + 1
        return 响应

    def 报告(self) -> str:
        """引擎使用统计 + 降级次数 (P8-C2 扩展, 供汇总报告展示)"""
        行 = []
        if self._统计:
            行.append('引擎使用统计: ' + ', '.join(
                f'{k}×{v}' for k, v in sorted(self._统计.items())))
        if self._降级次数:
            行.append(f'降级 {self._降级次数} 次')
        return '; '.join(行)

    def _记域名命中(self, url: str, 引擎: str) -> None:
        """P8-C2: 记一次域名×引擎命中; 到间隔输出汇总行。"""
        self._成功总数 += 1
        域 = _统计域名(url)
        if 域 not in self._域名统计 and len(self._域名统计) >= _域名统计上限:
            域 = '(其他)'                # 上限保护: 长尾域名不再单独占桶
        表 = self._域名统计.setdefault(域, {})
        表[引擎] = 表.get(引擎, 0) + 1
        if self._成功总数 % _汇总间隔 == 0:
            self._输出汇总()

    def _输出汇总(self) -> str:
        """层命中统计汇总行 (每 _汇总间隔 次成功一次, INFO 级可检索)。"""
        self._汇总输出次数 += 1
        层 = ', '.join(f'{k}×{v}' for k, v in sorted(self._统计.items())) or '(无)'
        top = sorted(self._域名统计.items(),
                     key=lambda kv: -sum(kv[1].values()))[:3]
        域名 = ', '.join(
            f'{域}(' + '/'.join(f'{k}×{v}' for k, v in sorted(表.items())) + ')'
            for 域, 表 in top) or '(无)'
        行 = (f'[引擎] 层命中统计#{self._汇总输出次数}: {层}; '
              f'降级 {self._降级次数} 次; 域名Top3: {域名}')
        _log.info(行)
        return 行

    # ------------------------------------------------------------------
    # 引擎选择与降级
    # ------------------------------------------------------------------
    def _选择引擎(self, 机制: str) -> str:
        """反爬机制 → 引擎映射 (带连续失败降级)。

        JS 质询 / 动态令牌类 → cloudscraper 自动执行质询脚本;
        cloudscraper 连续失败 → curl_cffi (TLS 指纹模拟);
        仍失败 → requests (交现有 WAF/浏览器流程)。
        """
        if 机制 in ('waf_js_challenge', 'js_cookie', 'dynamic_token'):
            if self.可用.get('cloudscraper'):
                if self._失败计数.get('cloudscraper', 0) >= self._降级阈值:
                    if self.可用.get('curl_cffi') or self.可用.get('requests'):
                        self._降级次数 += 1
                        _log.info(f'[引擎] cloudscraper 连续失败 '
                                  f'≥{self._降级阈值} → 降级到 '
                                  f'{"curl_cffi" if self.可用.get("curl_cffi") else "requests"}'
                                  f' (第 {self._降级次数} 次)')
                    return 'curl_cffi' if self.可用.get('curl_cffi') else 'requests'
                return 'cloudscraper'
            if self.可用.get('curl_cffi'):
                return 'curl_cffi'
            return 'requests'
        # 其它机制 (waf_captcha/ua_block/rate_limit/none):
        # 交现有请求 + 验证码解决流程, 不切换引擎
        return 'requests'

    # ------------------------------------------------------------------
    # 各引擎请求实现
    # ------------------------------------------------------------------
    def _请求_requests(self, url, headers=None, timeout=30, cookies=None,
                       proxies=None, 支持重定向=True) -> Optional[引擎响应]:
        try:
            import requests
            host = self._取host(url)
            会话 = self._requests_sessions.get(host)
            if 会话 is None:
                with self._会话缓存锁:          # 双检: 并发下同 host 只建一个会话
                    会话 = self._requests_sessions.get(host)
                    if 会话 is None:
                        会话 = requests.Session()
                        会话.trust_env = False
                        self._requests_sessions[host] = 会话
            with self._requests_lock:
                resp = 会话.get(url, headers=headers, timeout=timeout, cookies=cookies,
                                proxies=proxies, allow_redirects=支持重定向)
            return 引擎响应(
                status_code=resp.status_code, headers=dict(resp.headers),
                text=resp.text, content=resp.content, url=resp.url, 引擎='requests',
                历史URL=[h.url for h in (getattr(resp, 'history', None) or [])])
        except Exception as e:
            _log.info(f"[引擎] requests 请求异常: {e}")
            return None

    def _请求_curl_cffi(self, url, headers=None, timeout=30, cookies=None,
                        proxies=None, 支持重定向=True) -> Optional[引擎响应]:
        if self._curl_cffi is None:
            return None
        try:
            host = self._取host(url)
            会话 = self._curl_sessions.get(host)
            if 会话 is None:
                with self._会话缓存锁:          # 双检: 并发下同 host 只建一个会话
                    会话 = self._curl_sessions.get(host)
                    if 会话 is None:
                        # impersonate 显式指定具体 Chrome 版本指纹 (P2-1): 泛 'chrome'
                        # 可能映射到较旧指纹被新站点识破; chrome124 为稳定档
                        会话 = self._curl_cffi.Session(impersonate='chrome124')
                        self._curl_sessions[host] = 会话
            resp = 会话.get(url, headers=headers, timeout=timeout, cookies=cookies,
                            proxies=proxies, allow_redirects=支持重定向)
            return 引擎响应(
                status_code=resp.status_code, headers=dict(resp.headers),
                text=resp.text, content=resp.content, url=str(resp.url), 引擎='curl_cffi')
        except Exception as e:
            _log.info(f"[引擎] curl_cffi 请求异常: {e}")
            return None

    def _请求_cloudscraper(self, url, headers=None, timeout=30, cookies=None,
                           proxies=None, 支持重定向=True) -> Optional[引擎响应]:
        if self._cloudscraper is None:
            return None
        try:
            host = self._取host(url)
            会话 = self._cloudscraper_sessions.get(host)
            if 会话 is None:
                with self._会话缓存锁:          # 双检: 并发下同 host 只建一个会话
                    会话 = self._cloudscraper_sessions.get(host)
                    if 会话 is None:
                        # create_scraper 自带 Cloudflare 质询求解能力
                        会话 = self._cloudscraper.create_scraper()
                        self._cloudscraper_sessions[host] = 会话
            resp = 会话.get(url, headers=headers, timeout=timeout, cookies=cookies,
                            proxies=proxies, allow_redirects=支持重定向)
            return 引擎响应(
                status_code=resp.status_code, headers=dict(resp.headers),
                text=resp.text, content=resp.content, url=resp.url, 引擎='cloudscraper')
        except Exception as e:
            _log.info(f"[引擎] cloudscraper 请求异常: {e}")
            return None

    # ------------------------------------------------------------------
    @staticmethod
    def _取host(url: str) -> str:
        try:
            return urlparse(url).netloc.lower()
        except Exception:
            return ''


_默认管理器 = None
_管理器锁 = threading.Lock()


def 获取引擎管理器() -> 请求引擎管理器:
    """获取全局单例 (线程安全; 首次创建时注册退出清理)"""
    global _默认管理器
    if _默认管理器 is None:
        with _管理器锁:
            if _默认管理器 is None:        # 双检: 并发首调只创建一个实例
                _默认管理器 = 请求引擎管理器()
                # 修复(U15b): close() 此前全项目零调用, 会话池只能等进程回收。
                # atexit 覆盖 CLI/测试路径; GUI 走 os._exit 不触发 atexit,
                # 故 gui_app 的退出流程里另有一处显式 close。
                try:
                    import atexit
                    atexit.register(_默认管理器.close)
                except Exception as _e:
                    _log.debug(f'裸 except 吞异常: {type(_e).__name__}: {_e}')
    return _默认管理器
