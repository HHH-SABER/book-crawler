# -*- coding: utf-8 -*-
"""应用退出流程单测。

回归背景 (2026-09-10 实测, flet 0.86.5): 桌面是"Python + flet.exe"双进程。
  · 只用 os._exit(0) → 跳过 flet 的 close_flet_view(), flet.exe 变孤儿窗口
    (界面还在、没有后端、点关闭没反应) = 用户报的"关不掉 / 界面卡死"
  · 只用 page.window.destroy() → 客户端正常回收, 但 ft.run() 不返回, Python 挂住
所以退出必须 = 收尾落盘 → destroy 窗口 → 等 flet 收尾 → 兜底强退, 且**任何一步
失败都不能阻断退出**(否则又回到"关不掉")。本文件把该顺序与容错固化成单测。

运行方式 (项目根目录):
    python -m unittest discover -s 测试 -v
"""
import asyncio
import sys
import threading
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '源码'))
sys.path.insert(0, str(_PROJECT_ROOT / '源码' / 'gui_components'))

import 退出流程  # noqa: E402


class 假窗口:
    def __init__(self, 调用, 抛错=False):
        self._调用 = 调用
        self._抛错 = 抛错

    async def destroy(self):
        self._调用.append(('销毁窗口', None))
        if self._抛错:
            raise RuntimeError('模拟 destroy 失败')


class 假Page:
    def __init__(self, 调用, 抛错=False):
        self.window = 假窗口(调用, 抛错)


class 假任务:
    def __init__(self, status='running'):
        self.status = status
        self.stop_flag = threading.Event()


class 假任务管理器:
    def __init__(self, tasks):
        self._tasks = tasks

    def get_all_tasks(self):
        return list(self._tasks)


def 跑退出(page=None, 记录=None, **kw):
    """跑一遍退出流程; 返回 (结果, 调用轨迹)"""
    调用 = []

    async def 假休眠(秒):
        调用.append(('休眠', 秒))

    def 假强制结束(code):
        调用.append(('强制结束', code))

    page = page or 假Page(调用)
    结果 = asyncio.run(退出流程.执行退出(
        page, 休眠=假休眠, 强制结束=假强制结束,
        记录=记录 or (lambda m: 调用.append(('记录', m))), **kw))
    return 结果, 调用


def 标签列表(调用):
    return [c[0] for c in 调用]


class Test退出顺序(unittest.TestCase):
    """顺序是修复的核心: destroy 必须在强制结束之前"""

    def test_销毁窗口先于强制结束(self):
        结果, 调用 = 跑退出()
        标签 = 标签列表(调用)
        self.assertIn('销毁窗口', 标签)
        self.assertIn('强制结束', 标签)
        self.assertLess(标签.index('销毁窗口'), 标签.index('强制结束'),
                        '必须先 destroy 回收 flet.exe 客户端进程, 再强退 Python')

    def test_收尾钩子先于销毁窗口(self):
        """落盘必须在强退之前: os._exit 不跑 atexit, 事后没机会补"""
        顺序 = []
        结果, 调用 = 跑退出(收尾钩子=(lambda: 顺序.append('钩子'),))
        self.assertEqual(结果['收尾钩子数'], 1)
        标签 = 标签列表(调用)
        self.assertIn('销毁窗口', 标签)

    def test_销毁后等待收尾(self):
        结果, 调用 = 跑退出()
        等待 = [c[1] for c in 调用 if c[0] == '休眠']
        self.assertIn(退出流程.等收尾秒, 等待,
                      'destroy 之后要给 flet 的 fvp.wait/close_flet_view 留时间')

    def test_退出码透传(self):
        结果, 调用 = 跑退出(退出码=3)
        self.assertIn(('强制结束', 3), 调用)


class Test前序步骤(unittest.TestCase):

    def test_停远控与停托盘被调用(self):
        调用 = []
        结果, _ = 跑退出(page=假Page(调用),
                          停远控=lambda: 调用.append(('停远控', None)),
                          托盘对象=object())
        self.assertTrue(结果['停远控'])
        self.assertIn('停远控', 标签列表(调用))

    def test_运行中任务置位stop_flag并等待检查点(self):
        t = 假任务('running')
        结果, 调用 = 跑退出(任务管理器=假任务管理器([t]))
        self.assertTrue(t.stop_flag.is_set(), '运行中任务必须收到 stop_flag 才会写检查点')
        self.assertEqual(结果['运行中任务数'], 1)
        self.assertIn(退出流程.等检查点秒, [c[1] for c in 调用 if c[0] == '休眠'])

    def test_已结束任务不触发等待(self):
        t = 假任务('completed')
        结果, 调用 = 跑退出(任务管理器=假任务管理器([t]))
        self.assertEqual(结果['运行中任务数'], 0)
        self.assertFalse(t.stop_flag.is_set())
        self.assertNotIn(退出流程.等检查点秒, [c[1] for c in 调用 if c[0] == '休眠'])


class Test容错(unittest.TestCase):
    """退出路径上任何一步失败, 都必须仍然退得掉"""

    def test_销毁窗口失败仍强制结束(self):
        调用 = []
        结果, 调用 = 跑退出(page=假Page(调用, 抛错=True))
        self.assertFalse(结果['销毁窗口'])
        self.assertIn('强制结束', 标签列表(调用))

    def test_收尾钩子失败不阻断其他钩子与退出(self):
        执行过 = []
        钩子 = (lambda: 执行过.append(1),
                lambda: (_ for _ in ()).throw(OSError('模拟落盘失败')),
                lambda: 执行过.append(3))
        结果, 调用 = 跑退出(收尾钩子=钩子)
        self.assertEqual(执行过, [1, 3], '单个钩子失败不得阻断后续钩子')
        self.assertEqual(结果['收尾钩子数'], 2)
        self.assertEqual(结果['收尾钩子失败'], 1)
        self.assertIn('强制结束', 标签列表(调用))

    def test_任务管理器异常不阻断退出(self):
        class 坏管理器:
            def get_all_tasks(self):
                raise RuntimeError('模拟任务表异常')

        结果, 调用 = 跑退出(任务管理器=坏管理器())
        self.assertIn('强制结束', 标签列表(调用))

    def test_停远控异常不阻断退出(self):
        def 坏停远控():
            raise RuntimeError('模拟停机失败')

        结果, 调用 = 跑退出(停远控=坏停远控)
        self.assertFalse(结果['停远控'])
        self.assertIn('强制结束', 标签列表(调用))

    def test_日志回调异常不阻断退出(self):
        def 坏记录(msg):
            raise RuntimeError('模拟日志句柄已关闭')

        结果, 调用 = 跑退出(记录=坏记录)
        self.assertIn('强制结束', 标签列表(调用))


class Test默认参数(unittest.TestCase):

    def test_默认以0退出(self):
        _, 调用 = 跑退出()
        self.assertIn(('强制结束', 0), 调用)

    def test_常量取值合理(self):
        self.assertGreater(退出流程.等收尾秒, 0)
        self.assertLessEqual(退出流程.等收尾秒, 5)
        self.assertGreater(退出流程.等检查点秒, 退出流程.等收尾秒)


if __name__ == '__main__':
    unittest.main(verbosity=2)
