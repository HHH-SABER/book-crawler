# -*- coding: utf-8 -*-
"""阶段覆盖检查的用例（S1 等价护栏的一部分）。"""
import pathlib
import sys
import unittest
from unittest import mock

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '源码'))
sys.path.insert(0, str(_PROJECT_ROOT / '脚本'))
sys.path.insert(0, str(_PROJECT_ROOT / '测试'))

import _沙箱  # noqa: E402,F401  状态根沙箱
import 检查阶段覆盖 as 检查  # noqa: E402


def _站点策略_未知阶段(url, 阶段, **kw):
    """夹具：声明一个代码里根本不存在的阶段（模块级 + 字面量，才能被 AST 提取）。"""
    if 阶段 == '这个阶段不存在':
        return None
    return None


def _站点策略_已知阶段(url, 阶段, **kw):
    if 阶段 == '正文清理':
        return None
    return None


class 检查用例(unittest.TestCase):
    def test_空适配器表_无未知阶段(self):
        结果 = 检查.检查({})
        self.assertGreaterEqual(结果['阶段总数'], 8)
        self.assertEqual(结果['适配器数'], 0)
        self.assertEqual(结果['未知阶段'], [])

    def test_未知阶段被抓出(self):
        表 = {'siteX': {'域名': 'x.example.com', '站点策略': _站点策略_未知阶段},
              'siteY': {'域名': 'y.example.com', '站点策略': _站点策略_已知阶段}}
        结果 = 检查.检查(表)
        未知 = {(项['适配器'], 项['阶段']) for 项 in 结果['未知阶段']}
        self.assertIn(('siteX', '这个阶段不存在'), 未知)
        self.assertNotIn(('siteY', '正文清理'), 未知, '存在的阶段不该被误报')

    def test_未声明阶段单独列出且不影响通过(self):
        结果 = 检查.检查({})
        self.assertEqual(结果['未声明阶段'], sorted(set(结果['未声明阶段'])))
        self.assertIsInstance(结果['未声明阶段'], list)

    def test_结果结构稳定(self):
        结果 = 检查.检查({})
        for 键 in ('阶段总数', '适配器数', '有声明阶段的适配器数', '未声明阶段', '未知阶段'):
            self.assertIn(键, 结果)


class main用例(unittest.TestCase):
    def test_信息模式恒0(self):
        self.assertEqual(检查.main([]), 0)

    def test_严格模式_有未知阶段时1(self):
        假 = {'阶段总数': 3, '适配器数': 1, '有声明阶段的适配器数': 1,
              '未声明阶段': [], '未知阶段': [{'适配器': 'a', '阶段': 'b'}]}
        with mock.patch.object(检查, '检查', lambda *_a, **_k: 假):
            self.assertEqual(检查.main(['--严格']), 1)

    def test_严格模式_无未知阶段时0(self):
        假 = {'阶段总数': 3, '适配器数': 0, '有声明阶段的适配器数': 0,
              '未声明阶段': ['x'], '未知阶段': []}
        with mock.patch.object(检查, '检查', lambda *_a, **_k: 假):
            self.assertEqual(检查.main(['--严格']), 0)


if __name__ == '__main__':
    unittest.main()
