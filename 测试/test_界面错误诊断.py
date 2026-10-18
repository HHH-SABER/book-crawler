# -*- coding: utf-8 -*-
"""客户端界面错误诊断的离线用例 (灰页排查, 2026-10-18)。

覆盖: 事件取值的多种形态 / 容错不许抛 / 提示文案不泄露异常栈。
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / '源码'))

from gui_components.ui_error import 界面错误文本, 自愈提示  # noqa: E402


class _事件:
    def __init__(self, data=None, message=None):
        self.data = data
        self.message = message


class 界面错误文本用例(unittest.TestCase):
    def test_事件data优先(self):
        self.assertEqual(界面错误文本(_事件(data='RangeError: value 9')), 'RangeError: value 9')

    def test_message兜底(self):
        self.assertEqual(界面错误文本(_事件(message='bad widget')), 'bad widget')

    def test_字符串事件(self):
        self.assertEqual(界面错误文本('直接是字符串'), '直接是字符串')

    def test_None与空(self):
        self.assertEqual(界面错误文本(None), '')
        self.assertEqual(界面错误文本(_事件()), '')

    def test_异常对象转文本(self):
        文本 = 界面错误文本(ValueError('boom'))
        self.assertIn('boom', 文本)

    def test_从不抛异常(self):
        class 坏:
            @property
            def data(self):
                raise RuntimeError('属性炸了')

            def __str__(self):
                raise RuntimeError('str 也炸了')

        self.assertEqual(界面错误文本(坏()), '')

    def test_超长截断(self):
        self.assertEqual(len(界面错误文本(_事件(data='x' * 5000))), 2000)


class 自愈提示用例(unittest.TestCase):
    def test_有文本时提示已记录(self):
        文本 = 自愈提示('RangeError')
        self.assertIn('界面渲染出错', 文本)
        self.assertIn('日志', 文本)

    def test_无文本时不硬塞日志指引(self):
        self.assertNotIn('详情已写入', 自愈提示(''))

    def test_不泄露异常原文(self):
        原文 = 'RangeError: Index out of range at widget.dart:123'
        self.assertNotIn('widget.dart', 自愈提示(原文))


if __name__ == '__main__':
    unittest.main()
