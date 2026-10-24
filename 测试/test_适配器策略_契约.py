# -*- coding: utf-8 -*-
"""站点策略分发契约（S1 等价护栏，2026-10-24）。

为什么需要这个用例
------------------
`站点脱钩机制` 的公共入口是 `sites_config.适配器策略(url, 阶段, **上下文)`，
25 个阶段、每个站点的专属行为都从这一个函数进出。改动 `爬虫.py`（S1 拆模块）
或有新适配器接入时，**最容易坏的就是这条分发语义**，而它原先**零测试覆盖**。

本用例把契约钉死（只测分发，不测任何具体站点规则）：
1. 无适配器 / 未实现该阶段 / 钩子抛异常 ⇒ **一律 None**（交回通用规则，不崩）；
2. 钩子返回 True / False / 任意其它值 ⇒ **原样透传**；
3. `阶段` 与 `**上下文` **完整**送达钩子（不许吞参数、不许改名）。
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '源码'))
sys.path.insert(0, str(_PROJECT_ROOT / '测试'))

import _沙箱  # noqa: E402,F401  状态根沙箱
import sites_config  # noqa: E402


def _带适配器(钩子):
    """把 get_adapter 打桩成"这个 url 有适配器且带 站点策略 钩子"。"""
    return mock.patch.object(sites_config, 'get_adapter',
                             lambda url: {'站点策略': 钩子} if 钩子 else {})


def _无适配器():
    return mock.patch.object(sites_config, 'get_adapter', lambda url: None)


class 分发契约用例(unittest.TestCase):
    def setUp(self):
        # load_adapters 会去读本地目录；契约测试不需要真实适配器
        p = mock.patch.object(sites_config, 'load_adapters', lambda: None)
        p.start()
        self.addCleanup(p.stop)

    def test_无适配器返回None(self):
        with _无适配器():
            self.assertIsNone(sites_config.适配器策略('https://a.example.com/x', '目录'))

    def test_适配器无站点策略返回None(self):
        with mock.patch.object(sites_config, 'get_adapter', lambda url: {'别的': 1}):
            self.assertIsNone(sites_config.适配器策略('https://a.example.com/x', '目录'))

    def test_未实现该阶段返回None(self):
        with _带适配器(lambda url, 阶段, **ctx: None):
            self.assertIsNone(sites_config.适配器策略('https://a.example.com/x', '未实现阶段'))

    def test_True原样透传(self):
        with _带适配器(lambda url, 阶段, **ctx: True):
            self.assertTrue(sites_config.适配器策略('https://a.example.com/x', '目录'))

    def test_False原样透传(self):
        with _带适配器(lambda url, 阶段, **ctx: False):
            self.assertFalse(sites_config.适配器策略('https://a.example.com/x', '目录'))

    def test_专用结果原样透传(self):
        结果 = {'章节': [1, 2, 3]}
        with _带适配器(lambda url, 阶段, **ctx: 结果):
            self.assertIs(sites_config.适配器策略('https://a.example.com/x', '目录'), 结果)

    def test_钩子抛异常返回None且不崩(self):
        def _炸(url, 阶段, **ctx):
            raise RuntimeError('适配器缺陷')
        with _带适配器(_炸):
            self.assertIsNone(sites_config.适配器策略('https://a.example.com/x', '目录'),
                              '适配器抛异常必须吞掉并退回通用规则')

    def test_阶段与上下文完整送达(self):
        收到 = {}

        def 钩子(url, 阶段, **上下文):
            收到['url'] = url
            收到['阶段'] = 阶段
            收到['上下文'] = 上下文
            return 'ok'
        with _带适配器(钩子):
            sites_config.适配器策略('https://a.example.com/book/1', '正文',
                                   html='<p>x</p>', 章节号=3, 标题='第一章')
        self.assertEqual(收到['阶段'], '正文')
        self.assertEqual(收到['url'], 'https://a.example.com/book/1')
        self.assertEqual(收到['上下文'], {'html': '<p>x</p>', '章节号': 3, '标题': '第一章'})

    def test_上下文为空时也调用(self):
        """无上下文阶段（如 目录）必须照常调用，不能被 `if 上下文` 拦住。"""
        调用 = []

        def 钩子(url, 阶段, **上下文):
            调用.append(阶段)
            return True
        with _带适配器(钩子):
            self.assertTrue(sites_config.适配器策略('https://a.example.com/x', '目录'))
        self.assertEqual(调用, ['目录'])


class 站点代号匹配契约(unittest.TestCase):
    """`站点匹配()` 是域名判定的唯一入口（子串匹配 + 代号映射）。"""

    def test_映射缺失时安全返回False(self):
        with mock.patch.object(sites_config, '_站点代号映射', {}):
            self.assertFalse(sites_config.站点匹配('https://a.example.com/x', 'siteA'))

    def test_空参数安全返回False(self):
        self.assertFalse(sites_config.站点匹配('', 'siteA'))
        self.assertFalse(sites_config.站点匹配('https://a.example.com/x'))

    def test_命中代号返回True_大小写不敏感(self):
        with mock.patch.object(sites_config, '_站点代号映射', {'sitea': 'a.example.com'}):
            self.assertTrue(sites_config.站点匹配('https://A.EXAMPLE.COM/x', 'siteA'))

    def test_未登记代号返回False(self):
        with mock.patch.object(sites_config, '_站点代号映射', {'sitea': 'a.example.com'}):
            self.assertFalse(sites_config.站点匹配('https://a.example.com/x', 'siteZ'))


if __name__ == '__main__':
    unittest.main()
