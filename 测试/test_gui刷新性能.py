# -*- coding: utf-8 -*-
"""GUI 刷新性能契约 (2026-11-10 卡顿修复)。

用户反馈「整体卡顿、有时点击没有反馈」。定位到的三个热路径问题：
  ① 每秒 tick 无条件 list_view.update() / log_list.update() 等 —— 数据没变
     也要把整棵子树序列化成 patch 发客户端，空闲期持续占用 UI 线程；
  ② 运行中的任务把 (elapsed // 5) 塞进表格签名 —— 每 5 秒 clear + 重建
     **所有行**，行内按钮与点击回调被销毁重建，点在那一瞬就丢事件；
  ③ 点击「开始」/切页时整页 page.update() + 同步读盘，反馈要等整树 diff。

本文件钉住修复后的行为契约，防止后续改动把性能退化带回来。
"""
import inspect
import pathlib
import time
import unittest
from unittest.mock import Mock

import _沙箱  # noqa: F401  (把 源码/ 挂进 sys.path)

from gui_components.detail_drawer import DetailDrawer
from gui_components.input_bar import InputBar
from gui_components.task_manager import TaskInfo, TaskManager
from gui_components.task_table import TaskTable

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_GUI_APP = _ROOT / '源码' / 'gui_app.py'


def _任务(tid, status='running', 起始=None):
    t = TaskInfo(task_id=tid, url=f'https://example.com/{tid}',
                 title=f'任务{tid}', status=status)
    t.metrics.start_time = 起始
    return t


class _假管理器:
    """只提供组件构建/刷新所需的最小读取接口, 不碰磁盘、不起线程。"""

    def __init__(self, tasks=None):
        self._tasks = list(tasks or [])
        self.selected_task_id = None

    def get_all_tasks(self):
        return list(self._tasks)

    def get_task(self, tid):
        return next((t for t in self._tasks if t.task_id == tid), None)

    def select_task(self, tid):
        self.selected_task_id = tid


class Test表格刷新契约(unittest.TestCase):

    def setUp(self):
        self.mgr = _假管理器([_任务('task_1')])
        self.t = TaskTable(self.mgr)
        self.t.build()                     # build 内已做过一次 _refresh
        self.t._list_view.update = Mock()
        self.t._count_text.update = Mock()

    def test_空闲tick零patch(self):
        """数据没变时连子树 update 都不能发 (旧实现每秒发 2 次)。"""
        self.t.refresh_ui()
        self.t.refresh_ui()
        self.t.refresh_ui()
        self.assertEqual(self.t._list_view.update.call_count, 0)
        self.assertEqual(self.t._count_text.update.call_count, 0)

    def test_数据变化才刷且只刷一次(self):
        self.mgr._tasks.append(_任务('task_2'))
        self.t.refresh_ui()
        self.assertEqual(self.t._list_view.update.call_count, 1)
        self.t.refresh_ui()
        self.assertEqual(self.t._list_view.update.call_count, 1)

    def test_耗时推进不重建行控件(self):
        """跨 5 秒桶只改那一个 Text, 整行(含按钮)不销毁重建 → 不丢点击。"""
        起始 = time.time() - 1
        task = _任务('task_1', 起始=起始)
        mgr = _假管理器([task])
        t = TaskTable(mgr)
        t.build()
        行 = list(t._list_view.controls)
        旧签名 = t._sig
        耗时文本 = t._行单元[5][0].content
        耗时文本.update = Mock()

        task.metrics.start_time = 起始 - 6      # 推进一个 5 秒桶
        t.refresh_ui()

        self.assertEqual(list(t._list_view.controls), 行,
                         '表格行不得因耗时推进被重建')
        self.assertEqual(t._sig, 旧签名, '耗时推进不得改变行渲染签名')
        self.assertGreater(耗时文本.update.call_count, 0,
                           '耗时列应由单控件局部更新刷出')

    def test_耗时不得再进表格签名(self):
        """静态护栏: 防止有人为省事把 5 秒桶塞回 _refresh 的签名里。"""
        源码 = inspect.getsource(TaskTable._refresh)
        签名段 = 源码.split('if sig == self._sig:')[0]
        self.assertNotIn('time.time()', 签名段,
                         '耗时进了签名就会周期性全表重建并丢点击')


class Test详情栏刷新契约(unittest.TestCase):

    def setUp(self):
        self.d = DetailDrawer(TaskManager(page=None))
        self.d.build()
        self.d.build_log_strip()
        self.d._log_list.update = Mock()
        self.d._detail_view.update = Mock()
        self.d._日志条标题.update = Mock()

    def test_无脏视图零patch(self):
        self.d._dirty = set()
        self.d.update_views()
        self.assertEqual(self.d._log_list.update.call_count, 0)
        self.assertEqual(self.d._detail_view.update.call_count, 0)
        self.assertEqual(self.d._日志条标题.update.call_count, 0)

    def test_脏视图只刷对应子树(self):
        self.d._dirty = {'log'}
        self.d.update_views()
        self.assertEqual(self.d._log_list.update.call_count, 1)
        self.assertEqual(self.d._detail_view.update.call_count, 0)
        self.assertEqual(self.d._dirty, set(), '脏集合须被消费清空')

    def test_日志无变化不重建(self):
        self.d._dirty = set()                # 清掉 build 阶段留下的脏标记
        self.assertFalse(self.d.refresh_log(),
                         '空态已建且日志无变化 → 应返回 False')
        self.assertFalse(self.d.refresh_log(),
                         '连续 tick 无变化应一直返回 False')
        self.assertNotIn('log', self.d._dirty,
                         '无变化不得登记脏, 否则空闲 tick 仍会 patch')

    def test_详情无变化不重建(self):
        self.d.refresh()                       # 未选中任务: 首次建空态
        self.assertFalse(self.d.refresh(),
                         '第二次仍无任务 → 空态已建, 不得再重建')


class Test点击反馈契约(unittest.TestCase):

    def test_开始按钮有忙碌态(self):
        b = InputBar(TaskManager(page=None))
        b.build()
        b.start_btn.update = Mock()
        b._设开始忙碌(True)
        self.assertTrue(b.start_btn.disabled)
        self.assertGreater(b.start_btn.update.call_count, 0)
        b._设开始忙碌(False)
        self.assertFalse(b.start_btn.disabled)

    def test_开始入口防重入(self):
        源码 = inspect.getsource(InputBar.on_start_click)
        self.assertIn('_提交中', 源码)
        self.assertIn('_设开始忙碌', 源码)
        self.assertIn('finally', 源码)

    def test_输入条内部变化走局部刷(self):
        源码 = inspect.getsource(InputBar._局部刷)
        self.assertIn('根.update()', 源码)

    def test_新建任务后走子树刷新(self):
        文本 = _GUI_APP.read_text(encoding='utf-8')
        self.assertIn('task_table.refresh_ui()', 文本,
                      '新建任务后应子树级刷新, 不再整页 page.update()')

    def test_切页重活延后到下一帧(self):
        文本 = _GUI_APP.read_text(encoding='utf-8')
        self.assertIn('page.run_task(_延迟刷新)', 文本,
                      '切页读盘/重建列表不得压在点击回调里')


if __name__ == '__main__':
    unittest.main(verbosity=2)
