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
