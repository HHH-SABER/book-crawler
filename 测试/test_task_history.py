# -*- coding: utf-8 -*-
"""任务历史持久化回归 (2026-09-29, 用户反馈"更新程序后历史记录就没了")。

背景: GUI 任务表 (TaskManager.tasks) 曾是全工程唯一不落盘的对象,
重启即清零。修复后落盘 STATE_ROOT/数据/任务历史.json (tmp+os.replace
原子写, 保留最近 200 条), 启动恢复 (running→interrupted), 远控
_恢复中断任务 的 checkpoint 扫描同 URL 去重防双份。

锁定契约:
  ① 保存/恢复往返 (含 metrics/来源/创建参数)
  ② 序列化白名单: thread/stop_flag/selected/logs 不入库
  ③ resume_ 前缀展示项不入库 (其事实源是 checkpoint 文件)
  ④ running 恢复为 interrupted 且 end_time=0, 不误触发终态推送
  ⑤ _counter 续接存量最大 task_N
  ⑥ 200 条上限 (保留尾部)
  ⑦ 损坏 JSON 容错 (跳过不炸启动)
  ⑧ checkpoint 扫描同 URL 去重

运行 (项目根): python -m unittest discover -s 测试 -v
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '源码'))
sys.path.insert(0, str(_PROJECT_ROOT / '源码' / 'gui_components'))

import _path_utils                    # noqa: E402
import task_manager as tm             # noqa: E402
from task_manager import (TaskManager, TaskInfo,   # noqa: E402
                          TaskMetrics)
from 远控 import 服务                  # noqa: E402


def _隔离状态根(case):
    """重定向 STATE_ROOT 到临时目录 (范式同 test_path_utils)"""
    tmp = tempfile.mkdtemp(prefix='task_hist_')
    case._旧env = os.environ.get('LOCALAPPDATA')
    case._旧根 = getattr(_path_utils, '_STATE_ROOT', None)
    os.environ['LOCALAPPDATA'] = tmp
    _path_utils._STATE_ROOT = None
    case.addCleanup(lambda: (_path_utils._STATE_ROOT,
                             _恢复环境(case, tmp)))
    return tmp


def _恢复环境(case, tmp):
    _path_utils._STATE_ROOT = case._旧根
    if case._旧env is None:
        os.environ.pop('LOCALAPPDATA', None)
    else:
        os.environ['LOCALAPPDATA'] = case._旧env
    shutil.rmtree(tmp, ignore_errors=True)


def _造任务(tid, url=None, status='completed', **kw):
    t = TaskInfo(task_id=tid, url=url or f'https://example.com/b/{tid}',
                 status=status, **kw)
    return t


class Test任务历史持久化(unittest.TestCase):
    """保存/加载往返 + 白名单 + 上限 + 容错"""

    def setUp(self):
        self.tmp = _隔离状态根(self)
        self.历史路径 = os.path.join(self.tmp, '小说爬虫', '数据',
                                     '任务历史.json')

    def test_保存与恢复往返(self):
        mgr = TaskManager(page=None)
        t = _造任务('task_1', status='completed', title='某书',
                    progress_current=10, progress_total=10,
                    output_file='x/某书.txt', 来源='手机',
                    chapter_range=(3, 7), threads=4, delay=1.5,
                    resume=False, export_epub=True, incremental=True)
        t.metrics.quality_score = 100.0
        t.metrics.quality_passed = True
        t.metrics.engine = 'curl_cffi'
        t.metrics.engine_fallback_chain = ['requests']
        t.metrics.incremental_skipped = 3
        t.metrics.start_time = 1000.0
        t.metrics.end_time = 1060.0
        mgr.tasks['task_1'] = t
        mgr._保存任务历史()
        self.assertTrue(os.path.isfile(self.历史路径), '历史文件未落盘')

        mgr2 = TaskManager(page=None)          # 新实例 (模拟重启)
        self.assertIn('task_1', mgr2.tasks)
        r = mgr2.tasks['task_1']
        self.assertEqual(r.title, '某书')
        self.assertEqual(r.status, 'completed')
        self.assertEqual((r.progress_current, r.progress_total), (10, 10))
        self.assertEqual(r.output_file, 'x/某书.txt')
        self.assertEqual(r.来源, '手机')
        self.assertEqual(r.chapter_range, (3, 7))     # list 还原回 tuple
        self.assertEqual(r.threads, 4)
        self.assertEqual(r.delay, 1.5)
        self.assertFalse(r.resume)
        self.assertTrue(r.export_epub)
        self.assertTrue(r.incremental)
        self.assertEqual(r.metrics.quality_score, 100.0)
        self.assertTrue(r.metrics.quality_passed)
        self.assertEqual(r.metrics.engine, 'curl_cffi')
        self.assertEqual(r.metrics.engine_fallback_chain, ['requests'])
        self.assertEqual(r.metrics.incremental_skipped, 3)
        self.assertEqual(r.metrics.end_time, 1060.0)
        # 运行期对象由 dataclass 默认值重建
        self.assertIsNone(r.thread)
        self.assertIsNotNone(r.stop_flag)

    def test_序列化白名单(self):
        mgr = TaskManager(page=None)
        t = _造任务('task_1')
        t.logs.append({'time': '10:00:00', 'msg': '不应入库'})
        mgr.tasks['task_1'] = t
        mgr._保存任务历史()
        with open(self.历史路径, encoding='utf-8') as f:
            数据 = json.load(f)
        self.assertEqual(len(数据), 1)
        条 = 数据[0]
        for 禁 in ('thread', 'stop_flag', 'selected', 'logs'):
            self.assertNotIn(禁, 条, f'{禁} 不应入 JSON')

    def test_resume前缀展示项不入库(self):
        mgr = TaskManager(page=None)
        mgr.tasks['task_1'] = _造任务('task_1')
        mgr.tasks['resume_abcd1234'] = _造任务(
            'resume_abcd1234', url='https://example.com/b/resume',
            status='interrupted')
        mgr._保存任务历史()
        with open(self.历史路径, encoding='utf-8') as f:
            数据 = json.load(f)
        self.assertEqual([d['task_id'] for d in 数据], ['task_1'],
                         'checkpoint 扫描的 resume_ 展示项不应入库')

    def test_running恢复为interrupted且不误推(self):
        mgr = TaskManager(page=None)
        t = _造任务('task_1', status='running')
        t.metrics.start_time = 1000.0
        t.metrics.end_time = 0.0
        mgr.tasks['task_1'] = t
        mgr._保存任务历史()

        mgr2 = TaskManager(page=None)
        r = mgr2.tasks['task_1']
        self.assertEqual(r.status, 'interrupted')
        self.assertEqual(r.metrics.end_time, 0.0)
        self.assertTrue(r.error)
        # 恢复的终态不得触发完成推送 (_扫描终态 只推"本进程观察过 running"的翻转)
        with mock.patch.object(服务, '_task_manager', mgr2):
            self.assertEqual(服务._扫描终态(), [])

    def test_计数续接(self):
        mgr = TaskManager(page=None)
        mgr.tasks['task_7'] = _造任务('task_7')
        mgr._保存任务历史()
        mgr2 = TaskManager(page=None)
        self.assertEqual(mgr2._counter, 7, '计数应续接存量最大 task_N')
        self.assertNotIn('task_7', [None])  # noqa 占位保持行数稳定

    def test_200条上限保留尾部(self):
        mgr = TaskManager(page=None)
        for i in range(1, 251):
            mgr.tasks[f'task_{i}'] = _造任务(f'task_{i}')
        mgr._保存任务历史()
        with open(self.历史路径, encoding='utf-8') as f:
            数据 = json.load(f)
        self.assertEqual(len(数据), 200)
        ids = {d['task_id'] for d in 数据}
        self.assertNotIn('task_1', ids, '最老的应被裁掉')
        self.assertIn('task_250', ids, '最新的必须保留')

    def test_损坏文件容错(self):
        os.makedirs(os.path.dirname(self.历史路径), exist_ok=True)
        Path(self.历史路径).resolve().write_text('{这不是合法JSON', encoding='utf-8')
        mgr = TaskManager(page=None)     # 不应抛异常
        self.assertEqual(mgr.tasks, {})


class Test恢复中断去重(unittest.TestCase):
    """checkpoint 扫描 (_恢复中断任务) 与任务历史恢复的同 URL 去重"""

    def setUp(self):
        self.tmp = _隔离状态根(self)
        self.mgr = TaskManager(page=None)
        self._旧mgr = 服务._task_manager
        服务._task_manager = self.mgr
        self.addCleanup(lambda: setattr(服务, '_task_manager', self._旧mgr))

    def tearDown(self):
        服务._已扫中断 = True    # 还原一次性开关, 免污染其他用例

    def test_同URL已有任务则跳过注入(self):
        # 模拟: 任务历史恢复已把同 URL 的 interrupted 项放进表
        self.mgr.tasks['task_1'] = _造任务(
            'task_1', url='https://example.com/b/9', status='interrupted')
        with tempfile.TemporaryDirectory() as td:
            Path(td, '某书.txt.checkpoint.json').write_text(
                '{"catalog_url": "https://example.com/b/9", '
                '"completed": 7, "total": 20}', encoding='utf-8')
            with mock.patch.object(服务, 'get_default_output_dir',
                                   lambda: str(td)):
                服务._已扫中断 = False
                服务._恢复中断任务()
        self.assertNotIn('resume_9', ' '.join(self.mgr.tasks) + 'x')
        resume项 = [k for k in self.mgr.tasks if k.startswith('resume_')]
        self.assertEqual(resume项, [], '同 URL 已有任务不应再注入 resume_ 项')
        self.assertIn('task_1', self.mgr.tasks)

    def test_不同URL正常注入(self):
        self.mgr.tasks['task_1'] = _造任务(
            'task_1', url='https://example.com/b/9', status='interrupted')
        with tempfile.TemporaryDirectory() as td:
            Path(td, '另书.txt.checkpoint.json').write_text(
                '{"catalog_url": "https://example.com/b/42", '
                '"completed": 1, "total": 5}', encoding='utf-8')
            with mock.patch.object(服务, 'get_default_output_dir',
                                   lambda: str(td)):
                服务._已扫中断 = False
                服务._恢复中断任务()
        resume项 = [k for k in self.mgr.tasks if k.startswith('resume_')]
        self.assertEqual(len(resume项), 1, '不同 URL 的 checkpoint 应正常注入')


if __name__ == '__main__':
    unittest.main(verbosity=2)
