# -*- coding: utf-8 -*-
"""降级链层命中统计回归 (P8-C2, 2026-10-24)。

验收口径 (实施计划 §E): "日志里有层命中统计" —— 本套用例同时锁住行为
(计数/降级次数/域名分桶/上限/汇总节奏/报告格式), 全部离线 (打桩引擎方法,
不触网)。
"""
import logging
import sys
import unittest
from pathlib import Path
from unittest import mock

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

import 请求引擎 as R   # noqa: E402


def _响应(url: str, 成功: bool = True):
    return R.引擎响应(status_code=200 if 成功 else 500, headers={},
                    content=b'<html>ok</html>', url=url)


class Test层命中统计(unittest.TestCase):

    def setUp(self):
        # 打桩地址安全 (请求() 内函数级 import, 打模块属性即生效):
        # 真校验会对每个域名做 DNS 解析 (经 dns_doh 走网络), 离线测试必须绕开
        p1 = mock.patch('地址安全.校验URL', return_value=(True, ''))
        p2 = mock.patch('地址安全.校验响应', return_value=(True, ''))
        p1.start()
        p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)

    def _管理器(self) -> R.请求引擎管理器:
        管 = R.请求引擎管理器()
        # 打桩: 所有引擎请求都不触网, 直接返回 canned 响应
        管._请求_requests = lambda url, **kw: _响应(url)
        return 管

    def test_成功请求记层与域名(self):
        管 = self._管理器()
        管.请求('http://book.example.invalid/a', 引擎='requests')
        管.请求('http://www.book.example.invalid/b', 引擎='requests')
        self.assertEqual(管._统计['requests'], 2)
        self.assertEqual(管._域名统计['book.example.invalid'], {'requests': 2})

    def test_报告含引擎与降级(self):
        管 = self._管理器()
        管.请求('http://a.example.invalid/x', 引擎='requests')
        管._降级次数 = 2
        报告 = 管.报告()
        self.assertIn('requests×1', 报告)
        self.assertIn('降级 2 次', 报告)

    def test_降级计数在选择器触发时累加(self):
        管 = self._管理器()
        管.可用 = {'requests': True, 'curl_cffi': True, 'cloudscraper': True}
        管._失败计数['cloudscraper'] = 管._降级阈值
        引擎 = 管._选择引擎('waf_js_challenge')
        self.assertEqual(引擎, 'curl_cffi')
        self.assertEqual(管._降级次数, 1)
        管._选择引擎('waf_js_challenge')
        self.assertEqual(管._降级次数, 2, '每次真正降级都计数')

    def test_未达阈值不计数(self):
        管 = self._管理器()
        管.可用 = {'requests': True, 'curl_cffi': True, 'cloudscraper': True}
        管._失败计数['cloudscraper'] = 管._降级阈值 - 1
        self.assertEqual(管._选择引擎('waf_js_challenge'), 'cloudscraper')
        self.assertEqual(管._降级次数, 0)

    def test_域名桶上限保护(self):
        管 = self._管理器()
        for i in range(R._域名统计上限 + 20):
            管.请求(f'http://d{i}.example.invalid/x', 引擎='requests')
        self.assertLessEqual(len(管._域名统计), R._域名统计上限 + 1,
                             '上限 + "(其他)" 桶, 不得无界增长')
        self.assertIn('(其他)', 管._域名统计)

    def test_每五十次成功输出汇总(self):
        管 = self._管理器()
        行 = 管._输出汇总()
        self.assertIn('层命中统计#1', 行)
        self.assertIn('域名Top3', 行)
        self.assertIn('降级 0 次', 行)
        self.assertEqual(管._汇总输出次数, 1)

    def test_汇总间隔由成功请求自然触发(self):
        管 = self._管理器()
        for i in range(R._汇总间隔):
            管.请求(f'http://p{i % 3}.example.invalid/x', 引擎='requests')
        self.assertEqual(管._成功总数, R._汇总间隔)
        self.assertEqual(管._汇总输出次数, 1, '满 50 次自动汇总一次')

    def test_失败请求不进域名统计(self):
        管 = self._管理器()
        管._请求_requests = lambda url, **kw: _响应(url, 成功=False)
        管.请求('http://bad.example.invalid/x', 引擎='requests')
        self.assertEqual(管._成功总数, 0)
        self.assertEqual(管._域名统计, {})


if __name__ == '__main__':
    unittest.main(verbosity=2)
