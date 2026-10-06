# -*- coding: utf-8 -*-
"""Phase 4 批 2 回归：工作台三区（底部常驻日志条 + 右侧常驻栏）。

设计稿（`界面设计预览/index.html`）工作台是三区：
  左列 = 页头 + 输入卡 + 任务表 + **底部常驻深色日志条(.log-strip, 带 ▲ 折叠)**
  右侧 = **常驻栏**（任务详情 ↔ 抓取结果文件）
此前两者挤在一个"点行才开"的抽屉里（`open(view)` 切可见性）。

本文件钉住：
  ① 右栏默认显示详情；② 日志条常驻且可折叠/展开（含箭头图标与提示语）；
  ③ 两个构建入口**共用同一套视图控件**（幂等，不重复造）；④ 历史 API `open("log")`
     语义兼容（选中任务 + 展开日志条，不再切可见性）；⑤ 两侧刷新都不抛。
"""
import pathlib
import unittest

import _沙箱  # noqa: F401

import flet as ft

from gui_components.detail_drawer import DetailDrawer
from gui_components.task_manager import TaskManager

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_GUI = _ROOT / '源码' / 'gui_app.py'


class Test工作台三区(unittest.TestCase):

    def setUp(self):
        self.d = DetailDrawer(TaskManager(page=None))

    def test_右栏默认显示详情(self):
        self.d.build()
        self.assertEqual(self.d._view, 'detail')
        self.assertTrue(self.d._detail_view.visible, '右栏应默认显示任务详情')
        self.assertFalse(self.d._preview_view.visible)
        self.assertEqual(self.d._title_text.value, '任务详情')

    def test_日志条常驻且可折叠(self):
        self.d.build_log_strip()
        self.assertTrue(self.d._日志条体.visible, '日志条默认展开')
        self.d.切换日志条()
        self.assertFalse(self.d._日志条体.visible, '折叠后日志体应隐藏')
        self.assertEqual(self.d._日志条箭头.icon, ft.Icons.KEYBOARD_ARROW_UP)
        self.assertIn('展开', self.d._日志条箭头.tooltip)
        self.d.切换日志条()
        self.assertTrue(self.d._日志条体.visible, '再点应重新展开')
        self.assertEqual(self.d._日志条箭头.icon, ft.Icons.KEYBOARD_ARROW_DOWN)

    def test_两个入口共用同一套视图控件(self):
        self.d.build()
        日志 = self.d._log_view
        self.d.build_log_strip()
        self.assertIs(self.d._log_view, 日志, '不得重复构建日志视图 (幂等)')
        self.assertTrue(self.d._视图已建)

    def test_open_log语义兼容(self):
        """历史调用方用 open("log") 选任务看日志 —— 现在日志条常驻, 语义不变。"""
        self.d.build()
        self.d.build_log_strip()
        self.d.切换日志条()          # 先折叠
        self.d.open('log')            # 应自动展开并刷新
        self.assertEqual(self.d._view, 'detail', '右栏不应因看日志而被切走')
        self.assertTrue(self.d._日志条体.visible, 'open("log") 应确保日志条展开')

    def test_open_preview与返回详情(self):
        self.d.build()
        self.d.open('preview')
        self.assertTrue(self.d._preview_view.visible)
        self.assertFalse(self.d._detail_view.visible)
        self.assertEqual(self.d._title_text.value, '文件预览')
        self.d._on_toggle_click()
        self.assertEqual(self.d._view, 'detail', '右栏按钮应在 详情/预览 间切换')
        self.assertTrue(self.d._detail_view.visible)

    def test_两侧刷新都不抛(self):
        self.d.build()
        self.d.build_log_strip()
        self.d.refresh()
        self.d.refresh_log()
        self.d.update_views()      # 两区都常驻 → 内部两条分支都要走

    def test_工作台已接底部日志条(self):
        文本 = _GUI.read_text(encoding='utf-8')
        self.assertIn('drawer.build_log_strip()', 文本,
                      '工作台未接底部常驻日志条 (批 2 的核心改动)')
        self.assertIn('_底部日志条', 文本)


if __name__ == '__main__':
    unittest.main(verbosity=2)
