# -*- coding: utf-8 -*-
"""去重界面接入回归 (2026-10-07 新增, 全离线: 假页 + 桩, 零真实文件 IO)。

锁定 源码/gui_components/detail_drawer.py 的查重入口契约:
  - 「查重」走工作线程扫描, 扫描中重复点击不重入
  - 结果弹窗分支: 无重复 / 得检测错误 / 有多组
  - **只有存在「可自动清理」项时** "移入隔离区并清理" 才可点
  - 清理只作用于各组 可自动清理 项, 且恒用 '隔离' 模式 (可反悔)
  - 弹窗文字显式带 color (v2.4.19 G-H1: EXE 缺色渲染成不可见)
运行: python -m unittest discover -s 测试
"""
import asyncio
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))
sys.path.insert(0, str(_根 / '测试'))

import _沙箱          # noqa: E402,F401  状态根沙箱 (LOCALAPPDATA 隔离)
import flet as ft     # noqa: E402
from gui_components.detail_drawer import DetailDrawer   # noqa: E402
from gui_components.task_manager import TaskManager      # noqa: E402


class _假页:
    """最小 flet Page 替身: 记录弹窗与 update 次数, run_task 同步跑完协程。"""

    def __init__(self):
        self.dialogs = []
        self.updates = 0

    def show_dialog(self, ctrl):
        self.dialogs.append(ctrl)

    def pop_dialog(self):
        if self.dialogs:
            self.dialogs.pop()

    def update(self):
        self.updates += 1

    def run_task(self, coro):
        asyncio.run(coro)


def _收集文本(ctrl) -> str:
    """递归收集控件树里所有 Text.value。"""
    片段 = []

    def _走(c):
        if c is None:
            return
        v = getattr(c, 'value', None)
        if isinstance(v, str) and v:
            片段.append(v)
        for 属性 in ('content', 'title', 'text'):
            子 = getattr(c, 属性, None)
            if 子 is not None and not isinstance(子, str):
                _走(子)
        for 属性 in ('controls', 'actions'):
            子列表 = getattr(c, 属性, None)
            if isinstance(子列表, (list, tuple)):
                for x in 子列表:
                    _走(x)
    _走(ctrl)
    return ' '.join(片段)


def _造组(键='k1', 名='保留书.txt', 字数=1000, 可清理=(), 待确认=()):
    return {
        '键': 键,
        '代表': {'路径': f'X:/{名}', '名': 名, '字数': 字数, '字节': 1},
        '可自动清理': [{'路径': f'X:/{n}', '名': n, '字数': w, '字节': 1,
                    '判定': '同一本', '理由': 'r', '指标': {}} for n, w in 可清理],
        '待确认': [{'路径': f'X:/{n}', '名': n, '字数': w, '字节': 1,
                 '判定': '疑似(待人工确认)', '理由': 'r', '指标': {}} for n, w in 待确认],
        '剔除': [],
        '组成员数': 1 + len(可清理) + len(待确认),
    }


class Test查重入口(unittest.TestCase):

    def setUp(self):
        self.d = DetailDrawer(TaskManager(page=None))
        self.页 = _假页()
        self.d.page = self.页

    def test_无重复时弹窗提示且清理按钮禁用(self):
        self.d._显示查重结果([], '')
        self.assertEqual(len(self.页.dialogs), 1)
        文本 = _收集文本(self.页.dialogs[0])
        self.assertIn('未发现重复文件', 文本)
        self.assertTrue(self.页.dialogs[0].actions[1].disabled,
                        '无重复时"移入隔离区并清理"应禁用')

    def test_检测错误时显示错误文案(self):
        self.d._显示查重结果([], 'PermissionError: 拒绝访问')
        self.assertEqual(len(self.页.dialogs), 1)
        文本 = _收集文本(self.页.dialogs[0])
        self.assertIn('检测失败', 文本)
        self.assertIn('PermissionError', 文本)

    def test_有多组时可清理按钮可用且列出保留项(self):
        组 = [_造组(名='保留书.txt', 可清理=[('副本.txt', 900)])]
        self.d._显示查重结果(组, '')
        dlg = self.页.dialogs[0]
        文本 = _收集文本(dlg)
        self.assertIn('保留书.txt', 文本)
        self.assertIn('副本.txt', 文本)
        self.assertIn('发现 1 组重复', 文本)
        self.assertFalse(dlg.actions[1].disabled, '有可清理项时按钮应可点')

    def test_只有待确认项时清理按钮禁用(self):
        组 = [_造组(待确认=[('疑似.txt', 800)])]
        self.d._显示查重结果(组, '')
        dlg = self.页.dialogs[0]
        self.assertIn('疑似.txt', _收集文本(dlg))
        self.assertTrue(dlg.actions[1].disabled,
                        '全是待确认项时不该给"清理"入口 (灰区不自动处理)')

    def test_弹窗文字显式带颜色(self):
        """v2.4.19 G-H1: EXE 里缺 color 的文字渲染成不可见。"""
        组 = [_造组(可清理=[('副本.txt', 900)])]
        self.d._显示查重结果(组, '')
        dlg = self.页.dialogs[0]

        def _查(c):
            if isinstance(c, ft.Text):
                self.assertIsNotNone(c.color, f'Text 缺 color: {c.value!r}')
            for 属性 in ('content', 'title'):
                子 = getattr(c, 属性, None)
                if 子 is not None and not isinstance(子, str):
                    _查(子)
            for 属性 in ('controls', 'actions'):
                子列表 = getattr(c, 属性, None)
                if isinstance(子列表, (list, tuple)):
                    for x in 子列表:
                        _查(x)
        _查(dlg)

    def test_扫描走线程并写入清单(self):
        组 = [_造组()]
        调 = {'写出': 0}

        def _假扫描(目录=None):
            return 组

        def _假写出(列表):
            调['写出'] += 1
            self.assertEqual(列表, 组)
            return 1

        with mock.patch('去重处理.扫描重复', _假扫描), \
                mock.patch('去重处理.写出清单', _假写出):
            self.d._检测重复()
            for _ in range(200):          # 等扫描线程结束 (最长 ~4s)
                if not self.d._查重中:
                    break
                time.sleep(0.02)
            self.assertFalse(self.d._查重中, '扫描应已结束')
            time.sleep(0.05)              # 让 _dispatch 的 run_task 跑完
        self.assertEqual(调['写出'], 1, '扫描结果应写入去重清单')
        self.assertTrue(self.页.dialogs, '应弹出结果弹窗')

    def test_扫描中重复点击不重入(self):
        self.d._查重中 = True
        with mock.patch('去重处理.扫描重复') as m:
            self.d._检测重复()
            m.assert_not_called()
        self.d._查重中 = False

    def test_清理只作用于可自动清理项且恒用隔离模式(self):
        组甲 = _造组(键='ka', 可清理=[('a1.txt', 9)])
        组乙 = _造组(键='kb', 待确认=[('b1.txt', 9)])   # 无可清理
        调用 = []

        def _假清理(键, 模式='隔离', 隔离目录=None):
            调用.append((键, 模式))
            return {'清理': ['x'], '失败': [], '模式': 模式, '隔离目录': ''}

        with mock.patch('去重处理.执行清理', _假清理):
            self.d._执行查重清理([组甲, 组乙], ft.AlertDialog())
            time.sleep(0.2)               # 等清理线程跑完
        self.assertEqual(调用, [('ka', '隔离')],
                         '只有含可自动清理项的组才执行, 且模式必须是 隔离')

    def test_无页面时不抛(self):
        self.d.page = None
        self.d._显示查重结果([_造组()], '')     # 应静默返回
        self.d._执行查重清理([_造组()], ft.AlertDialog())


if __name__ == '__main__':
    unittest.main()
