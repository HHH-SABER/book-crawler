# -*- coding: utf-8 -*-
"""内容品类契约 (2026-11-10, 统一内容库改造阶段 A)。

品类是**任务属性**, 不是页面维度。本文件钉住四件事:
① 默认值为「小说」(旧数据/旧调用方零迁移);
② 序列化白名单必须落 `品类/品类参数`(漏了 → 重启后漫画任务变小说并去跑小说爬虫);
③ 旧 JSON 无该字段 → 加载后回落「小说」;
④ 判重必须带品类(同一 URL 的小说与漫画是两个任务)。
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / '源码'))

import _path_utils                                   # noqa: E402
from gui_components.task_manager import (            # noqa: E402
    TaskInfo, TaskManager, 已知品类)


def _隔离状态根(case):
    tmp = tempfile.mkdtemp(prefix='cat_contract_')
    case._旧env = os.environ.get('LOCALAPPDATA')
    case._旧根 = getattr(_path_utils, '_STATE_ROOT', None)
    os.environ['LOCALAPPDATA'] = tmp
    _path_utils._STATE_ROOT = None
    case.addCleanup(lambda: _恢复(case, tmp))


def _恢复(case, tmp):
    _path_utils._STATE_ROOT = case._旧根
    if case._旧env is None:
        os.environ.pop('LOCALAPPDATA', None)
    else:
        os.environ['LOCALAPPDATA'] = case._旧env
    shutil.rmtree(tmp, ignore_errors=True)


class Test品类字段(unittest.TestCase):

    def test_默认品类为小说(self):
        t = TaskInfo(task_id='t1', url='https://a.invalid/x')
        self.assertEqual(t.品类, '小说')
        self.assertIsNone(t.品类参数)

    def test_已知品类白名单(self):
        self.assertEqual(已知品类, ('小说', '漫画'))

    def test_序列化含品类键(self):
        """静态护栏: 显式白名单漏写 → 重启后品类丢失。"""
        源码 = (Path(__file__).resolve().parent.parent / '源码' /
                'gui_components' / 'task_manager.py').read_text(encoding='utf-8')
        块 = 源码.split('白名单序列化')[1][:1200]
        self.assertRegex(块, r"['\"]品类['\"]", '序列化未落 品类 键')
        self.assertRegex(块, r"['\"]品类参数['\"]", '序列化未落 品类参数 键')
        # 死书字段必须仍在同一窗口内（历史护栏, 不能被新字段挤出去）
        self.assertRegex(块, r"['\"]dead['\"]", 'dead 键被挤出白名单窗口')


class Test品类持久化(unittest.TestCase):

    def setUp(self):
        _隔离状态根(self)
        self.历史路径 = os.path.join(os.environ['LOCALAPPDATA'], '拾卷',
                                     '数据', '任务历史.json')

    def test_漫画任务往返(self):
        mgr = TaskManager(page=None)
        t = TaskInfo(task_id='task_1', url='https://a.invalid/m', status='completed',
                     品类='漫画', 品类参数={'导出格式': 'cbz', '卷界': '8,16'})
        mgr.tasks['task_1'] = t
        mgr._保存任务历史()

        mgr2 = TaskManager(page=None)
        r = mgr2.tasks['task_1']
        self.assertEqual(r.品类, '漫画')
        self.assertEqual(r.品类参数, {'导出格式': 'cbz', '卷界': '8,16'})

    def test_旧JSON无品类回落小说(self):
        """旧版本落盘的历史没有 品类 键 → 加载后必须是小说, 且不能报错。"""
        os.makedirs(os.path.dirname(self.历史路径), exist_ok=True)
        旧 = [{
            'task_id': 'task_9', 'url': 'https://a.invalid/old', 'title': '旧书',
            'mode': 'full', 'progress_current': 3, 'progress_total': 3,
            'status': 'completed', 'output_file': 'x/旧书.txt', 'error': '',
            'dead': None, 'chapter_range': [1, 3], 'threads': None, 'delay': None,
            'resume': True, 'output_dir': None, 'export_epub': False,
            'incremental': False, '来源': '本机',
            'metrics': {'engine': 'requests', 'anti_spider_type': '',
                        'quality_score': -1.0, 'quality_passed': False,
                        'incremental_skipped': 0, 'engine_fallback_chain': [],
                        'start_time': 1.0, 'end_time': 2.0, 'clean_summary': {}},
        }]
        Path(self.历史路径).write_text(json.dumps(旧, ensure_ascii=False),
                                       encoding='utf-8')
        mgr = TaskManager(page=None)
        self.assertIn('task_9', mgr.tasks)
        self.assertEqual(mgr.tasks['task_9'].品类, '小说')
        self.assertIsNone(mgr.tasks['task_9'].品类参数)


class Test品类判重(unittest.TestCase):

    def setUp(self):
        _隔离状态根(self)

    def test_同URL跨品类不判重(self):
        mgr = TaskManager(page=None)
        # 不真起线程: 只验证判重/建任务这一段
        with mock.patch.object(TaskManager, '_run_task', lambda *a, **k: None):
            a = mgr.create_task('https://a.invalid/same', 品类='小说')
            b = mgr.create_task('https://a.invalid/same', 品类='漫画')
        self.assertNotEqual(a, b, '同一 URL 的小说/漫画必须是两个任务')
        self.assertEqual(mgr.tasks[a].品类, '小说')
        self.assertEqual(mgr.tasks[b].品类, '漫画')

    def test_同品类同URL仍复用(self):
        mgr = TaskManager(page=None)
        with mock.patch.object(TaskManager, '_run_task', lambda *a, **k: None):
            a = mgr.create_task('https://a.invalid/same', 品类='漫画')
            b = mgr.create_task('https://a.invalid/same', 品类='漫画')
        self.assertEqual(a, b, '同品类同 URL 应幂等复用')

    def test_未知品类报错(self):
        mgr = TaskManager(page=None)
        with self.assertRaises(ValueError):
            mgr.create_task('https://a.invalid/x', 品类='网页')


class Test重下参数(unittest.TestCase):

    def setUp(self):
        _隔离状态根(self)

    def test_重下参数带品类(self):
        mgr = TaskManager(page=None)
        t = TaskInfo(task_id='task_1', url='https://a.invalid/m', 品类='漫画',
                     品类参数={'导出格式': 'pdf'})
        mgr.tasks['task_1'] = t
        参数 = mgr.get_task_params('task_1')
        self.assertEqual(参数['品类'], '漫画')
        self.assertEqual(参数['品类参数'], {'导出格式': 'pdf'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
