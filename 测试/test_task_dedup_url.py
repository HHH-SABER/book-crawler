# -*- coding: utf-8 -*-
"""同 URL 任务判重回归 (2026-10-02 EXE 批量残影事故)。

## 为什么需要

用户界面任务列表一度累积到 111 行, 但真实书目只有 40 本。根因:
`TaskManager.create_task` 每次都无条件 `self._counter += 1` 新建一行,
**完全不看同 URL 是否已存在任务**。批量脚本 (蓝屏恢复自动重提 + 驱动失败补交
+ 我手动重提) 对同一本书反复提交, 每次都留一条新展示记录, 旧记录既不合并
也不清理, 于是 completed×33 / interrupted×30 / failed×35 里绝大部分是同一
本书的历史残影。

## 锁定的契约

1. 同 URL **已有在跑/排队任务** (status∈{pending,running} 或线程存活)
   → `create_task` 幂等复用返回该 id, **绝不新建第二行**。
   (2026-10-04 Phase 3: 去掉幽灵状态 `queued` —— 全工程从未给 task.status 赋过该值。)
2. 同 URL **只有终态旧记录** (completed/failed/stopped/interrupted 且线程已死)
   → 新建本轮任务, 并把旧残影展示项清除 (delete_task, 不删输出文件)。
3. 不同 URL 互不影响, 各自的残影/新建独立处理。
4. 连续多次提交同一 URL, 任务表恒为该 URL 恰好 1 条。

测试用 mock 掉真实 Thread (create_task 里的 t.start() 不 spawn _run_task,
不联网), 状态根隔离到 tempfile, tearDown 还原, 不触碰项目产物。
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '源码'))
sys.path.insert(0, str(_PROJECT_ROOT / '源码' / 'gui_components'))

import _path_utils                    # noqa: E402
import task_manager as tm             # noqa: E402
from task_manager import TaskManager, TaskInfo   # noqa: E402


def _隔离状态根(case):
    tmp = tempfile.mkdtemp(prefix='dedup_test_')
    case._旧env = os.environ.get('LOCALAPPDATA')
    case._旧根 = getattr(_path_utils, '_STATE_ROOT', None)
    os.environ['LOCALAPPDATA'] = tmp
    _path_utils._STATE_ROOT = None

    def _还原():
        _path_utils._STATE_ROOT = case._旧根
        if case._旧env is None:
            os.environ.pop('LOCALAPPDATA', None)
        else:
            os.environ['LOCALAPPDATA'] = case._旧env
        shutil.rmtree(tmp, ignore_errors=True)
    case.addCleanup(_还原)
    return tmp


class Test同URL任务判重(unittest.TestCase):
    """#6: create_task 必须对同 URL 判重, 杜绝历史残影堆积"""

    def setUp(self):
        _隔离状态根(self)
        # mock 掉真实线程: create_task 内 Thread(...).start() 不再 spawn 抓取
        self._patch = mock.patch.object(tm.threading, 'Thread')
        MockThread = self._patch.start()
        MockThread.return_value = mock.MagicMock()
        self.addCleanup(self._patch.stop)
        self.mgr = TaskManager(page=None)
        self.url = 'https://example.com/book/42'

    def _注入(self, tid, url, status, alive):
        t = TaskInfo(task_id=tid, url=url, status=status)
        if alive:
            th = mock.MagicMock()
            th.is_alive.return_value = True
            t.thread = th
        self.mgr.tasks[tid] = t
        return t

    def test_活跃任务_幂等复用不新建(self):
        self._注入('task_5', self.url, 'running', alive=True)
        before = set(self.mgr.tasks)
        rid = self.mgr.create_task(self.url)
        self.assertEqual(rid, 'task_5', '活跃同URL必须复用原 id')
        self.assertEqual(set(self.mgr.tasks), before, '复用不得新增任务行')

    def test_终态残影_新建并清理(self):
        self._注入('task_6', self.url, 'completed', alive=False)
        self._注入('task_7', self.url, 'failed', alive=False)
        new = self.mgr.create_task(self.url)
        self.assertNotIn('task_6', self.mgr.tasks, 'completed 残影应清除')
        self.assertNotIn('task_7', self.mgr.tasks, 'failed 残影应清除')
        self.assertIn(new, self.mgr.tasks)
        # 2026-10-04 (Phase 3) 语义修正: 新建任务初始态是 `pending`「等待中」,
        # 因为线程启动后可能先在同域闸门排队; 拿到闸门才转 running。
        # 旧断言写 'running' —— 那时 pending 是个永远不会被赋值的死状态。
        self.assertEqual(self.mgr.tasks[new].status, 'pending')
        同URL = [x for x in self.mgr.tasks.values() if x.url == self.url]
        self.assertEqual(len(同URL), 1, '清理后同 URL 应恰好 1 条新任务')

    def test_连续多次提交_恒一条(self):
        a = self.mgr.create_task(self.url)
        b = self.mgr.create_task(self.url)
        c = self.mgr.create_task(self.url)
        self.assertEqual(len({a, b, c}), 1, '三次提交应收敛为同一活跃任务')
        self.assertEqual(len([x for x in self.mgr.tasks.values()
                              if x.url == self.url]), 1)

    def test_不同URL_互不影响(self):
        self._注入('task_8', self.url, 'completed', alive=False)
        other = self.mgr.create_task('https://example.com/book/99')
        self.assertIn('task_8', self.mgr.tasks,
                      '不同 URL 提交不得清理本 URL 的残影')
        self.assertIn(other, self.mgr.tasks)

    def test_停止态残影也被清理(self):
        self._注入('task_9', self.url, 'stopped', alive=False)
        new = self.mgr.create_task(self.url)
        self.assertNotIn('task_9', self.mgr.tasks)
        self.assertNotEqual(new, 'task_9')


class Test排队状态语义(unittest.TestCase):
    """2026-10-04 (Phase 3): `pending` 从死状态变成真实排队态。

    旧实现: create_task 直接写 `running`, 而同域闸门排队期间也保持 `running` ——
    于是 `pending`（状态徽章「等待中」）在整条链路上**从未被赋值过**; 界面把
    "在排队"谎报成"抓取中"。另外 `_同URL判重` 判活时引用了一个从未存在的
    `queued`, 属幽灵状态。
    """

    def setUp(self):
        self._根 = _隔离状态根(self)

    def test_排队提示把状态置为pending(self):
        from task_manager import TaskInfo, _排队提示
        t = TaskInfo(task_id='t1', url='https://example.com/b', title='书',
                     status='running')
        _排队提示(t)
        self.assertEqual(t.status, 'pending', '排队期间应显示「等待中」而非「抓取中」')

    def test_幽灵状态queued不再算活跃(self):
        """queued 从未被赋值: 只有 queued 且线程已死的任务不得判为活跃"""
        t = TaskInfo(task_id='ghost', url='https://example.com/b', title='书',
                     status='queued')
        mgr = TaskManager(page=None)
        mgr.tasks['ghost'] = t
        复用, _残影 = mgr._同URL判重('https://example.com/b')
        self.assertIsNone(复用, 'queued 是幽灵状态, 不得当作活跃任务')

    def test_重启后pending恢复为interrupted(self):
        """否则残留的 pending 会被判活 → 同 URL 再提交被静默复用成僵尸任务"""
        import json
        目录 = Path(_path_utils.get_state_root()) / '数据'
        目录.mkdir(parents=True, exist_ok=True)
        (目录 / '任务历史.json').write_text(json.dumps(
            [{'task_id': 'task_1', 'url': 'https://example.com/b', 'title': '书',
              'mode': 'full', 'status': 'pending', 'metrics': {}}],
            ensure_ascii=False), encoding='utf-8')
        mgr = TaskManager(page=None)
        恢复 = mgr.tasks.get('task_1')
        self.assertIsNotNone(恢复, '历史应被恢复')
        self.assertEqual(恢复.status, 'interrupted',
                         'restart 后 pending 必须转 interrupted (线程已死)')


if __name__ == '__main__':
    unittest.main(verbosity=2)
