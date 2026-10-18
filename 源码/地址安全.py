# -*- coding: utf-8 -*-
"""地址安全边界 (C6 Roadmap R05, 2026-10-18)。

**解决的问题**: 请求引擎此前只校验字面 URL, 不解析 DNS、不拦私网段 ——
恶意/被污染的目录页一个 302 就能把抓取请求导向内网地址 (SSRF 类风险;
R05 登记项)。本模块在 请求引擎.请求() 的唯一汇聚点做两道检查:
  · **预检**: 请求前校验目标 URL (scheme + 主机解析结果的全部 IP);
  · **终检**: 响应后校验最终 URL + 重定向链上每一跳。

**拦截范围** (用户 2026-10-18 确认: 抓取不走代理, 标准私网/保留段全拦):
  IPv4: 0.0.0.0/8, 10/8, 100.64/10 (CGN), 127/8, 169.254/16 (含云元数据
        169.254.169.254), 172.16/12, 192.0.0.0/24, 192.0.2.0/24,
        192.168/16, 198.18/15, 198.51.100/24, 203.0.113/24,
        224/4 (组播), 240/4 (保留);
  IPv6: ::/128, ::1/128, fc00::/7 (ULA), fe80::/10 (链路本地), ff00::/8,
        ::ffff:0:0/96 (v4 映射 —— 映射内的 v4 按私网规则再查一遍);
  主机名: localhost / *.localhost / *.local;
  **fail-closed**: DNS 解析失败按拦截处理 (正常站点解析不会失败;
        离线时请求本来就会失败, 不算误伤)。

**性能**: 主机解析结果缓存 60s (线程安全) —— 每章请求只查一次 DNS/分钟;
  60s 内若解析被改写仍能在缓存过期后拦住 (R05 要求覆盖"解析变化")。

**语义一致**: 预检+终检对 requests/curl_cffi/cloudscraper 三引擎同效;
  浏览器引擎 (selenium/playwright) 无法逐跳拦截, 由终检 (最终 URL) 兜底 ——
  已在 docstring 与测试中如实标注。
"""
import ipaddress
import socket
import threading
import time
from urllib.parse import urlparse

_私网网段 = [ipaddress.ip_network(n) for n in (
    '0.0.0.0/8', '10.0.0.0/8', '100.64.0.0/10', '127.0.0.0/8',
    '169.254.0.0/16', '172.16.0.0/12', '192.0.0.0/24', '192.0.2.0/24',
    '192.168.0.0/16', '198.18.0.0/15', '198.51.100.0/24', '203.0.113.0/24',
    '224.0.0.0/4', '240.0.0.0/4',
    '::/128', '::1/128', 'fc00::/7', 'fe80::/10', 'ff00::/8', '::ffff:0:0/96',
)]

_保留主机后缀 = ('.localhost', '.local')
_保留主机精确 = {'localhost'}

_解析缓存: dict = {}           # 主机 → (过期时刻, [ip, ...] / None=解析失败)
_缓存锁 = threading.Lock()
_缓存TTL秒 = 60


def _是私网(ip) -> bool:
    """IP 是否落在私网/保留段; v4 映射的 v6 拆出内层 v4 再查一遍。"""
    try:
        v6 = ip if ip.version == 6 else None
        if v6 is not None and v6.ipv4_mapped is not None:
            v4 = v6.ipv4_mapped
            if any(v4 in n for n in _私网网段 if n.version == 4):
                return True
    except Exception:
        pass    # 刻意静默: v4 映射拆解失败则落回下一行的常规网段匹配, 无需留痕
    return any(ip in n for n in _私网网段 if n.version == ip.version)


def _解析主机(主机: str):
    """主机名 → 全部解析 IP (缓存 60s); 失败/超时返回 None (fail-closed)。"""
    now = time.monotonic()
    with _缓存锁:
        条 = _解析缓存.get(主机)
        if 条 and 条[0] > now:
            return 条[1]
    try:
        infos = socket.getaddrinfo(主机, None)
        ips = []
        for info in infos:
            try:
                ip = ipaddress.ip_address(info[4][0])
            except ValueError:
                continue
            if ip not in ips:
                ips.append(ip)
        结果 = ips or None
    except Exception:
        结果 = None
    with _缓存锁:
        _解析缓存[主机] = (now + _缓存TTL秒, 结果)
    return 结果


def 校验URL(url: str):
    """校验一个 URL 是否安全可请求。返回 (True, '') 或 (False, 拦截理由)。"""
    try:
        parsed = urlparse(str(url or ''))
    except Exception as e:
        return False, f'URL 解析异常: {type(e).__name__}'
    if parsed.scheme not in ('http', 'https'):
        return False, f'非 http/https 协议: {parsed.scheme or "(空)"}'
    主机 = (parsed.hostname or '').strip().lower()
    if not 主机:
        return False, 'URL 无主机名'
    if 主机 in _保留主机精确 or any(主机.endswith(s) for s in _保留主机后缀):
        return False, f'保留主机名: {主机}'
    try:
        ip = ipaddress.ip_address(主机)          # 主机本身是 IP 字面量
    except ValueError:
        ip = None
    if ip is not None:
        if _是私网(ip):
            return False, f'IP 落在私网/保留段: {ip}'
        return True, ''
    ips = _解析主机(主机)
    if ips is None:
        return False, f'DNS 解析失败 (fail-closed): {主机}'
    for ip in ips:
        if _是私网(ip):
            return False, f'{主机} 解析到私网/保留段: {ip}'
    return True, ''


def 校验响应(响应):
    """校验引擎响应: 最终 URL + 重定向链每一跳。返回 (True, '') 或 (False, 理由)。"""
    ok, 理由 = 校验URL(getattr(响应, 'url', ''))
    if not ok:
        return False, 理由
    for u in (getattr(响应, '历史URL', None) or []):
        ok, 理由 = 校验URL(u)
        if not ok:
            return False, f'重定向链经过不安全地址 ({u[:60]}): {理由}'
    return True, ''


def _自检():
    """无网络自检 (IP 字面量/主机名规则; DNS 部分由单测 mock)。"""
    for url in ('http://127.0.0.1/x', 'http://10.0.0.5/x', 'http://192.168.1.1/x',
                'http://169.254.169.254/meta', 'http://[::1]/x',
                'http://localhost/x', 'ftp://example.com/x', 'file:///c:/'):
        ok, 理由 = 校验URL(url)
        assert not ok, f'{url} 应被拦截'
    ok, _ = 校验URL('http://93.184.216.34/x')     # 公网字面量 (解析不触发)
    assert ok, '公网 IP 字面量不应被拦截'
    return True


if __name__ == '__main__':
    _自检()
    print('地址安全自检 OK (私网/保留段/协议/主机名规则)')
