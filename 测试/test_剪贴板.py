# -*- coding: utf-8 -*-
"""剪贴板统一模块回归 (2026-10-23 用户实测"复制按钮没用")。

背景:
  · 远控页旧实现 `Clipboard().set(...)` —— 实例没挂到 page, 协程内抛
    `RuntimeError: Control must be added to the page first`, 被吞 → 点了无反应;
  · 日志页用 clip.exe + locale 编码 (中文可能乱码);
  · 插件安装自己写了一份。
本模块收敛为一条链路 (系统剪贴板命令 → clip → tkinter), 这里守住行为与接线。
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

import 剪贴板 as C   # noqa: E402


class Test复制(unittest.TestCase):

    def test_空文本直接失败(self):
        self.assertFalse(C.复制(''))

    def test_第一实现成功即用(self):
        with mock.patch.object(C, '_系统剪贴板命令', return_value=True) as a, \
                mock.patch.object(C, '_clip命令', return_value=True) as b:
            self.assertTrue(C.复制('abc'))
        self.assertEqual(a.call_count, 1)
        self.assertEqual(b.call_count, 0, '成功就不该再降级')

    def test_逐级降级到最后(self):
        with mock.patch.object(C, '_系统剪贴板命令', return_value=False), \
                mock.patch.object(C, '_clip命令', return_value=False), \
                mock.patch.object(C, '_tkinter', return_value=True):
            self.assertTrue(C.复制('abc'))

    def test_全失败返回False且不抛(self):
        with mock.patch.object(C, '_系统剪贴板命令', return_value=False), \
                mock.patch.object(C, '_clip命令', return_value=False), \
                mock.patch.object(C, '_tkinter', return_value=False):
            self.assertFalse(C.复制('abc'))

    def test_实现抛异常也不向外冒(self):
        with mock.patch.object(C, '_系统剪贴板命令', side_effect=OSError('boom')), \
                mock.patch.object(C, '_clip命令', return_value=False), \
                mock.patch.object(C, '_tkinter', return_value=True):
            self.assertTrue(C.复制('abc'))

    def test_读取永不抛(self):
        self.assertIsInstance(C.读取(), str)


class Test远控页复制取值(unittest.TestCase):
    """2026-10-23 用户实测: 点复制 token, 剪贴板里是
    "<bound method RemotePage._取当前token of ...>" —— 信息行的 `取值` 是函数,
    旧代码直接把函数对象当文本复制。"""

    def _页(self):
        import gui_components.pages.remote_page as R
        页 = object.__new__(R.RemotePage)
        页._提示 = []
        页._toast = lambda msg: 页._提示.append(msg)
        return 页

    def test_取值函数会被调用(self):
        捕获 = []
        页 = self._页()
        with mock.patch('剪贴板.复制', side_effect=lambda t: 捕获.append(t) or True):
            页._复制(lambda: 'token-abc-123')
        self.assertEqual(捕获, ['token-abc-123'])
        self.assertIn('已复制', 页._提示[-1])

    def test_字符串照旧(self):
        捕获 = []
        页 = self._页()
        with mock.patch('剪贴板.复制', side_effect=lambda t: 捕获.append(t) or True):
            页._复制('http://127.0.0.1:8760/')
        self.assertEqual(捕获, ['http://127.0.0.1:8760/'])

    def test_空值与取值失败都不写剪贴板(self):
        页 = self._页()

        def 炸():
            raise RuntimeError('boom')

        捕获 = []
        with mock.patch('剪贴板.复制', side_effect=lambda t: 捕获.append(t) or True):
            页._复制('—')
            页._复制(炸)
        self.assertEqual(捕获, [], '空/异常值不应写剪贴板')
        self.assertTrue(any('没有可复制' in m for m in 页._提示))


class Test接线护栏(unittest.TestCase):
    """防止再回到"没挂 page 的 flet Clipboard 服务"。"""

    def test_远控页改用统一模块(self):
        源 = (_根 / '源码' / 'gui_components' / 'pages' / 'remote_page.py').read_text(
            encoding='utf-8')
        self.assertIn('剪贴板.复制', 源)
        self.assertNotIn('from flet.controls.services.clipboard import Clipboard', 源)
        self.assertNotIn('Clipboard()', 源)

    def test_日志页改用统一模块(self):
        源 = (_根 / '源码' / 'gui_components' / 'log_tab.py').read_text(encoding='utf-8')
        self.assertIn('剪贴板.复制', 源)

    def test_插件安装复用统一模块(self):
        源 = (_根 / '源码' / '插件安装.py').read_text(encoding='utf-8')
        self.assertIn('剪贴板.复制', 源)


if __name__ == '__main__':
    unittest.main(verbosity=2)
