# -*- coding: utf-8 -*-
"""死书自动清理（阶段5）回归护栏 —— 2026-10-06 修的真 bug。

## 事故
用户问："这本书不是在死书清单上吗，为什么我再次爬取还能爬取/清单里还在？"
- **能再次爬取**是设计如此（「目录无章节」只是**疑似**判定，状态=待确认，不封锁抓取）；
- **但清单里没自动清掉是真 bug**：收尾代码（清死书记录 + 记网站清单）原先嵌在
  `if ... and task.status == "running":` 分支**内部**，而抓取过程中的"完成"事件通路
  `_应用完成终态()`（task_manager.py:367）与正则通路(:226) **早已**把 status 置成
  'completed' → 进不了那个分支 → **收尾永不执行**（同类于"代码存在但不可达"）。
  实测证据：①历史日志里从未出现 `已移除死书记录`；②三条 10-03 的死书记录在对应任务
  早已 completed 的情况下仍留在清单里。

## 本护栏
① 行为：状态已被"完成事件"先置为 completed 时，收尾必须真的把死书记录清掉；
② 结构：收尾调用**不得**再被嵌进 `status == "running"` 分支（否则又会静默失效）；
③ 边界：未成功、无记录、已删除态、重复调用都不得报错或越权清理。
"""
import threading
import unittest
from pathlib import Path

import _沙箱  # noqa: F401  沙箱: 状态根 → 一次性临时目录

_ROOT = Path(__file__).resolve().parents[1]
_TM = _ROOT / '源码' / 'gui_components' / 'task_manager.py'


class Test死书自动清理(unittest.TestCase):
    """⚠️ 造任务时必须把 `task.thread` 指到**当前线程**。

    收尾前还有一道 `_is_task_thread_owner`(重启保护: 旧线程不得改写新运行的终态),
    它比对 `task.thread is threading.current_thread()`。真实场景里收尾就发生在
    任务自己的登记线程上; 测试若不设, 那道守卫会先短路 —— 断言会因**错误的原因**
    通过 (状态判定根本没被检验)。
    """

    def setUp(self):
        from gui_components.task_manager import TaskManager, TaskInfo
        self.mgr = TaskManager(page=None)
        self.TaskInfo = TaskInfo

    def _造任务(self, url: str, 状态: str, tid: str = 't1'):
        task = self.TaskInfo(task_id=tid, url=url, title='测试书', status=状态)
        task.thread = threading.current_thread()   # 见类 docstring
        return task

    def _造死书(self, url: str, 书名: str = '测试书'):
        from 死书处理 import 记录死书
        记录死书(url, 书名, '目录无章节', '目录页可访问且书名正常, 但未解析出章节')
        return 记录死书

    def _还有记录(self, url: str) -> bool:
        from 死书处理 import _键, 载入
        键 = _键(url)
        return any(r.get('键') == 键 for r in 载入())

    def test_完成事件先置状态时仍会清死书记录(self):
        """核心回归: "完成"事件通路会把 status 先置成 completed, 收尾仍必须执行。"""
        url = 'https://auto-clean-1.example.com/book/1'
        self._造死书(url)
        self.assertTrue(self._还有记录(url), '前置: 死书记录应已写入')
        # 模拟真实顺序: 事件通路先置完成态 (status 不再是 running)
        task = self._造任务(url, 'completed', 't1')
        self.assertTrue(self.mgr._该收尾成功(task),
                        '按最终状态判定时, 已 completed 的任务应当收尾 '
                        '(旧实现要求 status=="running", 于是收尾永不执行)')
        self.mgr._收尾成功(task, url)
        self.assertFalse(self._还有记录(url), '抓取成功后死书记录应被移除')
        self.assertIsNone(task.dead, '任务上的死书标记也应同步清掉')

    def test_未成功不收尾(self):
        """失败/停止/未完成/死书态都不该触发"成功收尾"。"""
        url = 'https://auto-clean-2.example.com/book/2'
        self._造死书(url)
        for 状态 in ('running', 'failed', 'stopped', 'interrupted', 'dead_pending', 'pending'):
            task = self._造任务(url, 状态, 't2')
            self.assertFalse(self.mgr._该收尾成功(task), f'{状态} 不该收尾')
        self.assertTrue(self._还有记录(url), '未成功时不得清掉死书记录')

    def test_无记录时收尾不报错且幂等(self):
        url = 'https://auto-clean-3.example.com/book/3'
        task = self._造任务(url, 'completed', 't3')
        self.mgr._收尾成功(task, url)      # 无记录: 静默
        self.mgr._收尾成功(task, url)      # 再来一次: 仍不报错
        self.assertFalse(self._还有记录(url))

    def test_已删除态不被收尾改写(self):
        """刻意不动"已删除": 那是用户已处置的终态账目 (标记载体 标记已恢复 的设计取舍)。"""
        from 死书处理 import 设状态, _键
        url = 'https://auto-clean-4.example.com/book/4'
        self._造死书(url)
        设状态(_键(url), '已删除')
        task = self._造任务(url, 'completed', 't4')
        self.mgr._收尾成功(task, url)
        self.assertTrue(self._还有记录(url), '已删除的历史账目不该被"抓回来"抹掉')

    def test_收尾调用不得再嵌进running分支(self):
        """结构护栏: 旧 bug 就是把收尾嵌在 `status == "running"` 分支里。"""
        行s = _TM.read_text(encoding='utf-8').splitlines()
        起点 = None
        for k, l in enumerate(行s):
            if 'if ' in l and 'task.status == "running"' in l and '_is_task_thread_owner' in l:
                起点 = k
                break
        self.assertIsNotNone(起点, '找不到完成态判定分支 (代码结构变了? 请更新本护栏)')
        缩进 = len(行s[起点]) - len(行s[起点].lstrip())
        体内 = []
        for l in 行s[起点 + 1:]:
            if not l.strip():
                continue
            if (len(l) - len(l.lstrip())) <= 缩进:
                break
            体内.append(l)
        self.assertFalse(any('_收尾成功(' in l for l in 体内),
                         '成功收尾又被嵌进 `status == "running"` 分支了 —— '
                         '"完成"事件通路会先把状态置成 completed, 收尾将永不执行')
        self.assertTrue(any('_该收尾成功(' in l for l in 行s),
                        '缺少按最终状态判定的收尾调用')


if __name__ == '__main__':
    unittest.main(verbosity=2)
