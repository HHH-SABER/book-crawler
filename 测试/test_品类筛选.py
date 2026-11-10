# -*- coding: utf-8 -*-
"""内容库品类筛选 (2026-11-10)。

品类是任务属性: 切「漫画」只应看到漫画行; 且品类必须进刷新签名,
否则切换后表格不重绘(与 dead 字段同款坑)。
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(根 / '源码'))

import _path_utils                                     # noqa: E402
from gui_components.task_manager import TaskInfo, TaskManager   # noqa: E402
from gui_components.task_table import TaskTable        # noqa: E402


def _隔离状态根(case):
    tmp = tempfile.mkdtemp(prefix='cat_filter_')
    case._旧env = os.environ.get('LOCALAPPDATA')
    case._旧根 = getattr(_path_utils, '_STATE_ROOT', None)
    os.environ['LOCALAPPDATA'] = tmp
    _path_utils._STATE_ROOT = None
    case.addCleanup(lambda: _还原(case, tmp))


def _还原(case, tmp):
    _path_utils._STATE_ROOT = case._旧根
    if case._旧env is None:
        os.environ.pop('LOCALAPPDATA', None)
    else:
        os.environ['LOCALAPPDATA'] = case._旧env
    shutil.rmtree(tmp, ignore_errors=True)


def _表格(品类s):
    """造一个装了若干任务的表格（不启动线程）。"""
    mgr = TaskManager(page=None)
    for i, 品 in enumerate(品类s, start=1):
        mgr.tasks[f'task_{i}'] = TaskInfo(
            task_id=f'task_{i}', url=f'https://a.invalid/{i}',
            title=f'第{i}本', status='completed', 品类=品)
    表 = TaskTable(mgr)
    表.build()
    return 表, mgr


class Test品类筛选(unittest.TestCase):

    def setUp(self):
        _隔离状态根(self)

    def test_默认全部(self):
        表, _ = _表格(['小说', '漫画'])
        self.assertEqual(表.品类筛选, '全部')
        self.assertEqual(len(表._list_view.controls), 2)

    def test_切漫画只剩漫画行(self):
        表, _ = _表格(['小说', '漫画', '小说'])
        表.设置品类筛选('漫画')
        self.assertEqual(len(表._list_view.controls), 1)
        表.设置品类筛选('小说')
        self.assertEqual(len(表._list_view.controls), 2)
        表.设置品类筛选('全部')
        self.assertEqual(len(表._list_view.controls), 3)

    def test_切换会强制重建(self):
        """_sig 必须被清空, 否则行集合变了但签名相同 → 不重绘。"""
        表, _ = _表格(['小说', '漫画'])
        表.设置品类筛选('漫画')
        self.assertEqual(len(表._list_view.controls), 1)
        表._sig = ('假签名',)
        表.设置品类筛选('小说')
        self.assertEqual(len(表._list_view.controls), 1)

    def test_品类进刷新签名(self):
        源码 = (根 / '源码' / 'gui_components' / 'task_table.py').read_text(
            encoding='utf-8')
        块 = 源码.split('def _refresh(self):')[1][:1500]
        self.assertIn('品类', 块, '_sig 未含品类 → 切筛选/品类变化不重绘')

    def test_筛选变化回调(self):
        记录 = []
        表, _ = _表格(['小说', '漫画'])
        表.on_品类变化 = 记录.append
        表.设置品类筛选('漫画')
        self.assertEqual(记录, ['漫画'])

    def test_同值不重复回调(self):
        记录 = []
        表, _ = _表格(['小说'])
        表.on_品类变化 = 记录.append
        表.设置品类筛选('全部')      # 已是全部
        self.assertEqual(记录, [])

    def test_计数文案随筛选变化(self):
        表, _ = _表格(['小说', '漫画', '漫画'])
        表.设置品类筛选('漫画')
        self.assertEqual(表._count_text.value, '共 2 个任务（全部 3）')
        表.设置品类筛选('全部')
        self.assertEqual(表._count_text.value, '共 3 个任务')


class Test标题前缀(unittest.TestCase):

    def setUp(self):
        _隔离状态根(self)

    def test_漫画标题带前缀(self):
        表, mgr = _表格(['漫画'])
        t = mgr.tasks['task_1']
        单元 = 表._单元格_标题(t, False)
        列 = 单元.content
        标题 = 列.controls[0].value
        self.assertTrue(标题.startswith('漫画 · '), f'实际={标题!r}')

    def test_小说标题无前缀(self):
        表, mgr = _表格(['小说'])
        t = mgr.tasks['task_1']
        单元 = 表._单元格_标题(t, False)
        self.assertFalse(单元.content.controls[0].value.startswith('小说 · '))

    def test_不改任务原字段(self):
        表, mgr = _表格(['漫画'])
        t = mgr.tasks['task_1']
        表._单元格_标题(t, False)
        self.assertEqual(t.title, '第1本', '前缀只用于显示, 不得污染 task.title')


if __name__ == '__main__':
    unittest.main(verbosity=2)
