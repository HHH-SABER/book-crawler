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
from typing import Dict, Optional
from urllib.parse import urlparse
import threading

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

# 建议的引擎请求顺序 (降级链尾)
_引擎顺序 = ('curl_cffi', 'cloudscraper')


@dataclass
class 引擎响应:
    """统一响应对象 (各引擎响应归一化, 兼容 requests.Response 常用属性)"""
    status_code: int = 0
    headers: Dict = field(default_factory=dict)
    text: str = ''
    content: bytes = b''
    url: str = ''
    引擎: str = 'requests'

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
        """基于 content 字节猜测编码 (chardet 可用时)"""
        if self.content:
            try:
                import chardet
                结果 = chardet.detect(self.content)
                if 结果 and 结果.get('encoding'):
                    return 结果['encoding']
            except Exception:
                pass
        return 'utf-8'

    @property
    def text(self) -> str:
        """显式设置 encoding 后按该编码重新解码 content"""
        if self._编码 and self.content:
            try:
                return self.content.decode(self._编码, errors='replace')
            except (LookupError, UnicodeDecodeError):
                pass
        return self._text

    @text.setter
    def text(self, value: str):
        self._text = value or ''


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
        self._curl_sessions: Dict[str, object] = {}        # host → curl_cffi.Session
        self._cloudscraper_sessions: Dict[str, object] = {}  # host → CloudScraper
        self._requests_sessions: Dict[str, object] = {}  # host → requests.Session
        # 共享 Session 的 CookieJar 非线程安全: 并发 worker 同时走引擎路径时
        # 可能丢 cookie (破坏 P1-8 的会话隔离)。引擎路径本身低频 (仅反爬机制命中),
        # 用进程级锁串行化, 保留连接复用同时消除竞态
        self._requests_lock = threading.Lock()
        self._统计: Dict[str, int] = {}            # {引擎: 成功请求次数}

    def close(self):
        """释放全部缓存会话 (进程收尾/测试用; 管理器为进程级单例, 任务运行中勿调)"""
        for d in (self._requests_sessions, self._curl_sessions,
                  self._cloudscraper_sessions):
            for s in list(d.values()):
                try:
                    s.close()
                except Exception:
                    pass
            d.clear()

    # ------------------------------------------------------------------
    # 对外 API
    # ------------------------------------------------------------------
    def 请求(self, url, headers=None, timeout=30, 引擎='auto', 机制='none',
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
        if 引擎 == 'auto':
            引擎 = self._选择引擎(机制)
        方法 = getattr(self, f'_请求_{引擎}', None)
        if 方法 is None or not self.可用.get(引擎):
            return None
        响应 = 方法(url, headers=headers, timeout=timeout,
                  cookies=cookies, proxies=proxies, 支持重定向=支持重定向)
        if 响应 is not None:
            if 响应.成功:
                self._统计[引擎] = self._统计.get(引擎, 0) + 1
                self._失败计数[引擎] = 0
            else:
                self._失败计数[引擎] = self._失败计数.get(引擎, 0) + 1
        return 响应

    def 报告(self) -> str:
        """引擎使用统计 (供汇总报告展示)"""
        if not self._统计:
            return ''
        return '引擎使用统计: ' + ', '.join(
            f'{k}×{v}' for k, v in sorted(self._统计.items()))

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
                会话 = requests.Session()
                会话.trust_env = False
                self._requests_sessions[host] = 会话
            with self._requests_lock:
                resp = 会话.get(url, headers=headers, timeout=timeout, cookies=cookies,
                                proxies=proxies, allow_redirects=支持重定向)
            return 引擎响应(
                status_code=resp.status_code, headers=dict(resp.headers),
                text=resp.text, content=resp.content, url=resp.url, 引擎='requests')
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
                # impersonate 显式指定具体 Chrome 版本指纹 (P2-1): 泛 'chrome' 可能
                # 映射到较旧指纹被新站点识破; chrome124 为 curl_cffi 内置的稳定档
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


def 获取引擎管理器() -> 请求引擎管理器:
    """获取全局单例"""
    global _默认管理器
    if _默认管理器 is None:
        _默认管理器 = 请求引擎管理器()
    return _默认管理器
