# -*- coding: utf-8 -*-
"""地址安全测试 (R05, 2026-10-18)。

R05 验收要求: "覆盖解析变化、IPv4/IPv6、重定向与正常CDN, 避免破坏合法站点"。

全部 mock/字面量, 零真实网络:
· 拦截: 私网 IPv4 字面量、IPv6 (::1/fe80/fc00)、v4 映射、localhost 系、
  非 http 协议、DNS 解析失败 (fail-closed)、重定向链落私网;
· 放行: 公网 IP 字面量、公网域名 (mock 解析)、CDN 多 IP 全公网;
· 引擎接线: 请求() 预检拦截 / 终检拦截重定向链 / 正常放行计数不受影响。
"""
import ipaddress
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

from 地址安全 import 校验URL, 校验响应, _解析主机   # noqa: E402
import 请求引擎 as 引擎模块   # noqa: E402


class Test拦截(unittest.TestCase):

    def test_私网IP字面量(self):
        for url in ('http://127.0.0.1/x', 'http://10.0.0.5/x',
                    'http://192.168.1.1/x', 'http://172.16.0.9/x',
                    'http://169.254.169.254/meta',   # 云元数据
                    'http://100.64.0.1/x', 'http://0.0.0.0/x'):
            ok, 理由 = 校验URL(url)
            self.assertFalse(ok, f'{url} 应被拦截')
            self.assertIn('私网', 理由)

    def test_IPv6私网(self):
        for url in ('http://[::1]/x', 'http://[fe80::1]/x',
                    'http://[fc00::1]/x', 'http://[::ffff:192.168.1.1]/x'):
            ok, _ = 校验URL(url)
            self.assertFalse(ok, f'{url} 应被拦截 (IPv6)')

    def test_保留主机名(self):
        for url in ('http://localhost/x', 'http://api.localhost/x',
                    'http://nas.local/x'):
            ok, _ = 校验URL(url)
            self.assertFalse(ok, f'{url} 应被拦截 (保留主机名)')

    def test_非http协议(self):
        for url in ('ftp://example.com/x', 'file:///c:/win.ini'):
            ok, _ = 校验URL(url)
            self.assertFalse(ok, f'{url} 应被拦截 (协议)')

    def test_解析失败fail_closed(self):
        with mock.patch('socket.getaddrinfo', side_effect=OSError('DNS down')):
            ok, 理由 = 校验URL('http://example.com/x')
            self.assertFalse(ok, 'DNS 失败应 fail-closed')
            self.assertIn('fail-closed', 理由)

    def test_解析变化到私网(self):
        """R05 要求覆盖"解析变化": 公网域名改解析到私网 IP 必须被拦"""
        import 地址安全 as A
        A._解析缓存.clear()
        fake = [(2, 1, 6, '', ('192.168.1.7', 0))]
        with mock.patch('socket.getaddrinfo', return_value=fake):
            ok, 理由 = 校验URL('http://example.com/x')
            self.assertFalse(ok, '解析变化到私网必须被拦')
            self.assertIn('192.168.1.7', 理由)
        A._解析缓存.clear()


class Test放行(unittest.TestCase):

    def setUp(self):
        import 地址安全 as A
        A._解析缓存.clear()

    def test_公网IP字面量(self):
        ok, 理由 = 校验URL('http://93.184.216.34/x')
        self.assertTrue(ok, 理由)

    def test_公网域名mock解析(self):
        fake = [(2, 1, 6, '', ('93.184.216.34', 0)),
                (23, 1, 6, '', ('2606:2800:220:1:248:1893:25c8:1946', 0, 0, 0))]
        with mock.patch('socket.getaddrinfo', return_value=fake):
            ok, 理由 = 校验URL('https://example.com/x')
            self.assertTrue(ok, 理由)

    def test_CDN多IP全公网(self):
        fake = [(2, 1, 6, '', ('151.101.1.1', 0)),
                (2, 1, 6, '', ('151.101.65.1', 0)),
                (2, 1, 6, '', ('151.101.129.1', 0))]
        with mock.patch('socket.getaddrinfo', return_value=fake):
            ok, _ = 校验URL('https://cdn.example.com/x')
            self.assertTrue(ok)

    def test_解析缓存生效(self):
        calls = []

        def fake_gai(host, *a):
            calls.append(host)
            return [(2, 1, 6, '', ('93.184.216.34', 0))]

        with mock.patch('socket.getaddrinfo', side_effect=fake_gai):
            校验URL('http://example.com/x')
            校验URL('http://example.com/y')
        self.assertEqual(len(calls), 1, '60s 缓存内同主机只解析一次')


class Test响应链(unittest.TestCase):

    def _响应(self, url, 历史URL=None):
        return 引擎模块.引擎响应(status_code=200, url=url, 历史URL=历史URL or [])

    def test_直连公网放行(self):
        with mock.patch('socket.getaddrinfo',
                        return_value=[(2, 1, 6, '', ('93.184.216.34', 0))]):
            ok, _ = 校验响应(self._响应('http://example.com/book'))
        self.assertTrue(ok)

    def test_重定向落私网拦截(self):
        with mock.patch('socket.getaddrinfo',
                        side_effect=lambda h, *a, **k: [(2, 1, 6, '', ('93.184.216.34', 0))]):
            ok, 理由 = 校验响应(self._响应(
                'http://final.example.com/x',
                历史URL=['http://example.com/book', 'http://192.168.1.5/step']))
        self.assertFalse(ok, '重定向链落私网必须拦')
        self.assertIn('192.168.1.5', 理由)

    def test_正常重定向全公网放行(self):
        fake = [(2, 1, 6, '', ('93.184.216.34', 0))]
        with mock.patch('socket.getaddrinfo', return_value=fake):
            ok, _ = 校验响应(self._响应(
                'https://cdn.example.com/ch1.html',
                历史URL=['http://example.com/ch1.html',
                         'https://example.com/ch1.html']))
        self.assertTrue(ok, '正常 CDN 重定向链不应误伤')


class Test引擎接线(unittest.TestCase):
    """请求() 预检/终检接线: 全 mock, 零网络。"""

    def _管理器(self):
        m = 引擎模块.请求引擎管理器.__new__(引擎模块.请求引擎管理器)
        m.可用 = {'requests': True, 'curl_cffi': False, 'cloudscraper': False}
        m._失败计数 = {}
        m._统计 = {}
        m._requests_sessions = {}
        m._curl_sessions = {}
        m._会话缓存锁 = __import__('threading').Lock()
        m._requests_lock = __import__('threading').Lock()
        return m

    def test_预检拦截私网(self):
        m = self._管理器()
        r = m.请求('http://192.168.1.1/x')
        self.assertIsNone(r, '私网目标应被预检拦截')

    def test_终检拦截重定向落私网(self):
        m = self._管理器()
        响应 = 引擎模块.引擎响应(status_code=200, url='http://192.168.1.5/x',
                          历史URL=['http://example.com/a'])
        with mock.patch.object(m, '_请求_requests', return_value=响应):
            r = m.请求('http://example.com/a')
        self.assertIsNone(r, '重定向落私网应被终检拦截')

    def test_正常响应放行(self):
        m = self._管理器()
        响应 = 引擎模块.引擎响应(status_code=200, url='http://93.184.216.34/x')
        with mock.patch('地址安全.校验URL', return_value=(True, '')), \
                mock.patch('地址安全.校验响应', return_value=(True, '')), \
                mock.patch.object(m, '_请求_requests', return_value=响应):
            r = m.请求('http://93.184.216.34/x')
        self.assertIsNotNone(r, '正常响应不应被拦')
        self.assertEqual(m._统计.get('requests'), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
