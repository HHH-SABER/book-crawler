# -*- coding: utf-8 -*-
"""任务列表超链接回归 (2026-10-09)

任务行书名下方的 URL 必须是可点击超链接:
  ① 视觉: PRIMARY 色 + 下划线 (明确可点击提示), tooltip 悬停可见完整网址
  ② 行为: 点击经 page.launch_url 在系统默认浏览器打开任务原始 URL
  ③ 兜底: page 未就绪 / launch_url 异常 → webbrowser 兜底, 绝不炸 UI
契约: 链接地址恒等于 task.url 本身 (数据驱动, 不允许硬编码或改写)。
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / '源码')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _沙箱  # noqa: F401,E402  import 即把状态根钉到临时目录

import flet as ft  # noqa: E402


def _遍历(控件):
    """深度优先遍历控件树 (Container.content / Row·Column.controls)。"""
    yield 控件
    content = getattr(控件, 'content', None)
    if content is not None:
        yield from _遍历(content)
    for c in (getattr(控件, 'controls', None) or []):
        yield from _遍历(c)


def _造任务(url='https://example.com/book/123', 标题='示例书名'):
    from gui_components.task_manager import TaskInfo
    return TaskInfo(task_id='t1', url=url, title=标题)


def _造行(任务):
    from gui_components.task_manager import TaskManager
    from gui_components.task_table import TaskTable
    表 = TaskTable(TaskManager(page=None))
    return 表, 表._build_row(任务)


class Test超链接构造(unittest.TestCase):
    """行内 URL 单元格必须是带可点击视觉提示的超链接。"""

    def setUp(self):
        self.url = 'https://example.com/book/123?from=task'
        self.task = _造任务(self.url)
        self.table, self.row = _造行(self.task)

    def _url文本(self):
        命中 = [c for c in _遍历(self.row)
                if isinstance(c, ft.Text) and c.value == self.url]
        self.assertTrue(命中, '行内必须存在 value==task.url 的文本控件')
        return 命中[0]

    def test_链接样式_主色下划线(self):
        t = self._url文本()
        self.assertEqual(t.color, ft.Colors.PRIMARY,
                         '链接须用 PRIMARY 色与正文区分 (可点击提示)')
        self.assertEqual(
            getattr(t.style, 'decoration', None), ft.TextDecoration.UNDERLINE,
            '链接须有下划线 (可点击提示)')

    def test_悬停显示完整网址(self):
        t = self._url文本()
        self.assertEqual(t.tooltip, self.url,
                         'tooltip 必须是完整 URL (列宽 200px 会省略号截断显示)')

    def test_点击处理已挂接(self):
        t = self._url文本()
        self.assertTrue(callable(t.on_tap), 'URL 文本必须挂 on_tap, 否则不可点击')

    def test_链接地址等于任务url(self):
        t = self._url文本()
        self.assertEqual(t.value, self.task.url,
                         '链接文本必须与任务 URL 一致 (防硬编码/改写)')


class Test打开链接行为(unittest.TestCase):
    """点击超链接 → 默认浏览器打开原网页; 兜底链路不炸 UI。"""

    def setUp(self):
        self.url = 'https://example.com/book/9'
        self.task = _造任务(self.url)
        self.table, self.row = _造行(self.task)

    def test_点击经launch_url打开原始url(self):
        打开的 = []

        class 假页:
            def launch_url(self, u, **k):
                打开的.append(u)

        self.table.page = 假页()
        self.table._打开链接(self.url)
        self.assertEqual(打开的, [self.url],
                         '必须原样打开 task.url, 不得改写或丢失参数')

    def test_无page时兜底webbrowser(self):
        self.table.page = None
        with mock.patch('webbrowser.open') as 假开:
            self.table._打开链接(self.url)
            假开.assert_called_once_with(self.url)

    def test_launch_url异常时兜底webbrowser(self):
        class 炸页:
            def launch_url(self, u, **k):
                raise RuntimeError('后端未就绪')

        self.table.page = 炸页()
        with mock.patch('webbrowser.open') as 假开:
            self.table._打开链接(self.url)
            假开.assert_called_once_with(self.url)

    def test_点击事件处理器不抛(self):
        打开的 = []

        class 假页:
            def launch_url(self, u, **k):
                打开的.append(u)

        self.table.page = 假页()
        命中 = [c for c in _遍历(self.row)
                if isinstance(c, ft.Text) and c.value == self.url][0]
        命中.on_tap(None)          # 不抛即通过
        self.assertEqual(打开的, [self.url])


if __name__ == '__main__':
    unittest.main()
