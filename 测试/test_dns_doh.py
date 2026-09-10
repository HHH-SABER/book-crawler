# -*- coding: utf-8 -*-
"""dns_doh 离线单测: IP 字面量/localhost 快速通道与污染注入路径, 全程不联网。

运行方式 (项目根目录):
    python -m unittest discover -s 测试 -v
    python 测试/test_dns_doh.py

覆盖范围:
    1. IP 字面量 (127.0.0.1 等) 快速通道 — 绝不触发 DoH 查询 (回归: 旧实现
       会把环回地址当污染, 对 name=127.0.0.1 发起最坏 16s 的 DoH 查询)
    2. localhost / *.localhost 快速通道 — 同上
    3. 污染域名 (系统解析 0.0.0.0) → DoH 结果注入
    4. DoH 查询失败 → 回退系统原始解析结果 (不破坏现有流程)
    5. 负缓存: DoH 失败后 30s 内不重复查询
"""

import socket
import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '源码'))

import dns_doh


def _polluted_result(port):
    """模拟系统 DNS 把域名污染到 0.0.0.0 的 getaddrinfo 返回结构"""
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('0.0.0.0', port))]


class TestIpLiteralFastPath(unittest.TestCase):
    """IP 字面量 / localhost 快速通道: 直连环回/本机是合法场景, 不走 DoH"""

    def setUp(self):
        # 不调用 install() (避免全局 patch 泄漏进其他测试), 仅设置等效状态。
        # 必须用 dns_doh 备份的"真原函数": 若此前已有测试或模块 import 过 爬虫
        # (导入期会调用 install()), socket.getaddrinfo 已是 _patched_getaddrinfo,
        # 拿它当原函数会让补丁函数调用自己 → RecursionError。
        self._orig = getattr(dns_doh, '_orig_getaddrinfo', None)
        dns_doh._orig_getaddrinfo = dns_doh._真实_getaddrinfo
        dns_doh._doh_cache.clear()

    def tearDown(self):
        # 还原而非 del: del 会把模块属性整个删掉, 之后 install() 读它会
        # AttributeError, 污染同进程的后续用例。
        dns_doh._orig_getaddrinfo = self._orig
        dns_doh._doh_cache.clear()

    def _forbid_doh(self):
        def _boom(host):
            raise AssertionError(f'host={host!r} 不应触发 DoH 查询')
        self._old_doh = dns_doh._doh_query
        dns_doh._doh_query = _boom
        self.addCleanup(setattr, dns_doh, '_doh_query', self._old_doh)

    def test_ip_literal_loopback_no_doh(self):
        self._forbid_doh()
        results = dns_doh._patched_getaddrinfo(
            '127.0.0.1', 8550, socket.AF_INET, socket.SOCK_STREAM)
        self.assertTrue(results, '环回地址应原样返回系统解析结果')

    def test_ip_literal_private_no_doh(self):
        self._forbid_doh()
        results = dns_doh._patched_getaddrinfo('192.168.1.10', 80)
        self.assertTrue(results)

    def test_localhost_no_doh(self):
        self._forbid_doh()
        results = dns_doh._patched_getaddrinfo('localhost', 80)
        self.assertTrue(results)

    def test_doh_source_host_no_recursion(self):
        """H3 回归: DoH 服务器自身域名绝不能再走 DoH 查询。

        旧实现对 dns.alidns.com 不设防 — alidns 解析失败时 urlopen 内部
        getaddrinfo(已 patch) 再次 DoH 查询同一域名, 无限递归空转。"""
        self._forbid_doh()
        results = dns_doh._patched_getaddrinfo('dns.alidns.com', 443)
        self.assertTrue(results)

    def test_is_ip_literal(self):
        self.assertTrue(dns_doh._is_ip_literal('127.0.0.1'))
        self.assertTrue(dns_doh._is_ip_literal('::1'))
        self.assertFalse(dns_doh._is_ip_literal('zhiruo.org'))
        self.assertFalse(dns_doh._is_ip_literal('300.1.1.1'))


class TestPollutionFallback(unittest.TestCase):
    """污染域名 → DoH 注入; DoH 失败 → 回退原结果; 负缓存去重"""

    def setUp(self):
        # install() 未必已执行 (直接 import 本模块时该属性不存在):
        # 无则设为未安装等效态 (原函数); 有则保存原值用于还原
        self._orig = getattr(dns_doh, '_orig_getaddrinfo', None)
        if self._orig is None:
            # 用备份的真原函数, 不用 socket.getaddrinfo (可能已被 install() 打过补丁)
            dns_doh._orig_getaddrinfo = dns_doh._真实_getaddrinfo
        self._doh = dns_doh._doh_query
        dns_doh._doh_cache.clear()

    def tearDown(self):
        if self._orig is not None:
            dns_doh._orig_getaddrinfo = self._orig
        dns_doh._doh_query = self._doh
        dns_doh._doh_cache.clear()

    def test_polluted_host_gets_doh_result(self):
        dns_doh._orig_getaddrinfo = lambda host, port, *a, **k: _polluted_result(port)
        dns_doh._doh_query = lambda host: '93.184.216.34'
        results = dns_doh._patched_getaddrinfo('polluted.example.com', 443)
        self.assertEqual(results[0][4][0], '93.184.216.34',
                         '污染域名应注入 DoH 解析的真实 IP')
        self.assertEqual(results[0][4][1], 443)

    def test_doh_failure_falls_back_to_original(self):
        dns_doh._orig_getaddrinfo = lambda host, port, *a, **k: _polluted_result(port)
        dns_doh._doh_query = lambda host: None   # DoH 双源均失败
        results = dns_doh._patched_getaddrinfo('polluted.example.com', 443)
        self.assertEqual(results[0][4][0], '0.0.0.0',
                         'DoH 失败应回退系统原始结果, 不破坏现有流程')

    def test_negative_cache_avoids_repeat_query(self):
        dns_doh._orig_getaddrinfo = lambda host, port, *a, **k: _polluted_result(port)
        calls = []

        def fake_doh(host):
            calls.append(host)
            return None
        dns_doh._doh_query = fake_doh
        dns_doh._patched_getaddrinfo('dead.example.com', 80)
        dns_doh._patched_getaddrinfo('dead.example.com', 80)
        self.assertEqual(len(calls), 1, 'DoH 失败后 30s 负缓存内不应重复查询')

    def test_healthy_host_untouched(self):
        # 正常域名: 系统解析有效 → 不查 DoH, 原样返回
        def fake_orig(host, port, *a, **k):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('1.2.3.4', port))]

        def _boom(host):
            raise AssertionError(f'健康域名 {host!r} 不应触发 DoH 查询')
        dns_doh._orig_getaddrinfo = fake_orig
        dns_doh._doh_query = _boom
        results = dns_doh._patched_getaddrinfo('healthy.example.com', 443)
        self.assertEqual(results[0][4][0], '1.2.3.4')


class TestInstallRobustness(unittest.TestCase):
    """install() 必须备份"真原函数", 而不是"调用那一刻的 socket.getaddrinfo"。

    回归背景: 只要有模块 import 过 爬虫 (它会在导入期调用 install()),
    socket.getaddrinfo 就已经是 _patched_getaddrinfo。若此时仍拿
    socket.getaddrinfo 当原函数, 补丁函数就会调用自己 → 每次解析 RecursionError。
    该缺陷此前被"测试文件的导入顺序"掩盖。
    """

    def setUp(self):
        self._原_orig = getattr(dns_doh, '_orig_getaddrinfo', None)
        self._原_socket = socket.getaddrinfo
        self.addCleanup(self._还原现场)

    def _还原现场(self):
        dns_doh._orig_getaddrinfo = self._原_orig
        socket.getaddrinfo = self._原_socket

    def test_已被打补丁时安装仍备份真原函数(self):
        socket.getaddrinfo = dns_doh._patched_getaddrinfo   # 模拟已被打过补丁
        dns_doh._orig_getaddrinfo = None                    # 模拟未安装
        dns_doh.install()
        self.assertIs(dns_doh._orig_getaddrinfo, dns_doh._真实_getaddrinfo)
        self.assertIsNot(dns_doh._orig_getaddrinfo, dns_doh._patched_getaddrinfo)

    def test_备份的真原函数可正常解析(self):
        """真原函数必须真的能解析, 否则打补丁后所有网络操作都会炸"""
        infos = dns_doh._真实_getaddrinfo('localhost', 80)
        self.assertTrue(infos)


if __name__ == '__main__':
    unittest.main(verbosity=2)
