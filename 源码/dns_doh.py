# -*- coding: utf-8 -*-
"""DNS 污染回退 (DoH 解析): 自动识别被污染域名并用 DoH 获取真实 IP

背景: 部分小说站域名被本地 DNS 污染 (解析到 0.0.0.0 / 127.0.0.1 / ::),
而站点本身在线 (如 zhiruo.org → ceracdn CDN)。requests 走系统 DNS,
导致连接失败 (getaddrinfo failed / 连不上)。

方案: 进程内 patch socket.getaddrinfo —
  1. 正常解析结果有效 → 原样返回 (零开销)
  2. 解析失败或命中污染地址 (0.0.0.0/127.0.0.1/::) → 用 DoH (DNS over HTTPS)
     查询真实 A 记录, 注入返回
  3. DoH 失败 → 回退原结果 (不破坏现有流程)

DoH 源白名单 (仅 https 固定服务器): 1.1.1.1 (Cloudflare JSON API) /
dns.alidns.com (阿里), 双源容错。查询参数经 urlencode 编码。
结果缓存 10 分钟 (域名 IP 变化时自动刷新)。
"""
import ipaddress
import json
import socket
import ssl
import threading
import time
import urllib.request
from urllib.parse import urlencode, urlparse

# DoH 服务器白名单: 仅允许向这些固定主机发起 DNS 查询
_DOH_ALLOWED_HOSTS = {'1.1.1.1', 'dns.alidns.com'}
_DOH_SOURCES = [
    'https://1.1.1.1/dns-query',
    'https://dns.alidns.com/resolve',
]
_CACHE_TTL = 600  # DoH 结果缓存 10 分钟

_doh_cache = {}          # host -> (ip, ts)
_polluted_hosts = set()  # 已确认污染的域名 (避免重复打印)
# 修复(U3): 缓存的读-改-写加锁。getaddrinfo 会被任意线程调用, 无锁时并发首查
# 会重复发起 DoH 查询 (惊群), "_polluted_hosts 判断-添加-打印"也会重复刷屏。
# 锁的获取开销 (~百纳秒) 相对一次 DoH 查询 (毫秒级) 可忽略。
_缓存锁 = threading.Lock()
_orig_getaddrinfo = None
# 模块导入时的真·原函数备份 (打补丁前的快照)。
# 修复: install() 原实现备份"调用那一刻的 socket.getaddrinfo", 若此前已有代码
# 把 socket.getaddrinfo 换成 _patched_getaddrinfo (例如任何模块 import 了 爬虫,
# 它会在导入期调用 install()), 备份就会指向打补丁后的函数 → 每次解析无限递归。
_真实_getaddrinfo = socket.getaddrinfo

_CTX = ssl.create_default_context()


def _doh_query(host: str):
    """依次尝试各 DoH 白名单源, 返回 A 记录 IP 或 None"""
    for base in _DOH_SOURCES:
        try:
            # 安全校验 (内联): DoH 源必须是白名单内 https 主机
            _u = urlparse(base)
            if _u.scheme != 'https' or (_u.hostname or '') not in _DOH_ALLOWED_HOSTS:
                continue
            url = base + '?' + urlencode({'name': host, 'type': 'A'})
            req = urllib.request.Request(
                url,
                headers={'accept': 'application/dns-json',
                         'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=8, context=_CTX) as r:
                data = json.loads(r.read().decode('utf-8'))
            for ans in data.get('Answer', []):
                if ans.get('type') == 1 and ans.get('data'):
                    return ans['data']  # A 记录
        except Exception:
            continue
    return None


def _looks_polluted(addrs) -> bool:
    """判断解析结果是否为污染地址"""
    for r in addrs:
        if r[0] == socket.AF_INET and r[4]:
            ip = r[4][0]
            if ip in ('0.0.0.0', '127.0.0.1', '10.0.0.0') or ip.startswith('127.'):
                return True
        elif r[0] == socket.AF_INET6 and r[4]:
            if r[4][0] in ('::', '::1'):
                return True
    return False


def _is_ip_literal(host: str) -> bool:
    """host 本身是 IP 字面量 (无需 DNS 解析, 也绝不该被当成污染去 DoH '纠偏')"""
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _patched_getaddrinfo(host, port, *args, **kwargs):
    # 快速通道: IP 字面量 / localhost 直连环回或本机是合法场景 (flet 本地端口、
    # 本地代理、本地 ollama 等)。旧实现会把解析结果里的 127.0.0.1 当污染,
    # 对 name=127.0.0.1 发起 DoH 查询 (两个源超时 8s 串行, 最坏卡 16 秒)。
    # H3: DoH 服务器自身域名必须走原函数 — 否则 alidns 解析失败时,
    # urlopen→getaddrinfo(已 patch)→再次 DoH 查询同一域名, 无限递归空转。
    if _is_ip_literal(host) or host in _DOH_ALLOWED_HOSTS \
            or host == 'localhost' or host.endswith('.localhost'):
        return _orig_getaddrinfo(host, port, *args, **kwargs)
    results = None
    try:
        try:
            results = _orig_getaddrinfo(host, port, *args, **kwargs)
            if results and not _looks_polluted(results):
                return results
            # 结果为空/被污染 → 走下方 DoH 回退
        except OSError:
            results = None  # 解析失败 (如 Errno 11004) → 走下方 DoH 回退

        # 系统解析失败或被污染 → DoH 回退
        now = time.time()
        with _缓存锁:
            cached = _doh_cache.get(host)
        if cached and now - cached[1] < _CACHE_TTL:
            ip = cached[0]
        else:
            ip = _doh_query(host)          # 网络调用, 不持锁 (勿把 ms 级 IO 放进临界区)
            with _缓存锁:
                _doh_cache[host] = (ip, now) if ip else (None, now - _CACHE_TTL + 30)
        if ip:
            # 仅首次污染时打印提示 (避免刷屏)
            # 修复(U3): "判断-添加-打印"必须在锁内原子完成, 否则并发首查会重复打印
            首次污染 = False
            with _缓存锁:
                if host not in _polluted_hosts:
                    _polluted_hosts.add(host)
                    首次污染 = True
            if 首次污染:
                try:
                    import 日志 as _app_log
                    _app_log.get('DNS').info(
                        f"检测到 DNS 污染: {host} → DoH 解析 {ip}")
                except Exception:
                    print(f"[DNS] 检测到污染: {host} → DoH 解析 {ip}")
            family = socket.AF_INET
            return [(family, socket.SOCK_STREAM, 6, '', (ip, port))]
        if results:
            return results
        # DoH 也失败且系统解析本就抛异常 → 还原系统行为
        return _orig_getaddrinfo(host, port, *args, **kwargs)
    except OSError:
        raise
    except Exception:
        try:
            return _orig_getaddrinfo(host, port, *args, **kwargs)
        except OSError:
            raise


def install():
    """安装 DNS 污染回退 (幂等, 进程内全局生效)

    修复: 原实现用 `socket.getaddrinfo` 当原函数备份 —— 若 install() 之前
    socket.getaddrinfo 已被替换为 _patched_getaddrinfo (例如 import 爬虫 时
    已经装过一次, 或测试直接改过), 备份就会指向补丁自身, 导致每次解析无限
    递归 (RecursionError)。改为固定引用模块导入时快照的真原函数。
    另外用 globals().get 读状态: 有测试会 del 掉该全局, 直接读会 AttributeError。
    """
    global _orig_getaddrinfo
    if globals().get('_orig_getaddrinfo') is not None:
        return
    _orig_getaddrinfo = _真实_getaddrinfo
    socket.getaddrinfo = _patched_getaddrinfo
