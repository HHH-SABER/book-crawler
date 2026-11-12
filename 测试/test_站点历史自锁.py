# -*- coding: utf-8 -*-
"""站点历史 自锁死回归 (2026-11-12 生产事故)。

事故链: 记录任务 在持有 _io_lock (原 threading.Lock, 不可重入) 的状态下
调用 _落盘, 而 _落盘 内部再次 with self._io_lock → 同线程二次加锁永久
自锁死。实测 (py-spy dump 抓到双线程现场):
  · 任务线程卡死在 记录任务→_落盘 → 任务永远停在"抓取中/断流";
  · 用户点退出 → 退出流程收尾钩子里同步调 站点历史.flush() 等同一把锁
    → UI 事件循环冻结 → 整个程序关不掉, 只能任务管理器强杀。
修复: ① 记录任务 与 flush()/爬取历史.记录请求 同构 —— 快照锁内取、
     落盘放锁外 (U17 契约);
     ② _io_lock 升级 RLock (同类嵌套误用兜底);
     ③ 退出流程 收尾钩子改 worker 线程限时执行 (见 test_exit_flow.py)。
本文件固化 ①② 的行为契约: 记录任务 必须能在独立线程内完成, 且与并发
flush()/查站点() 互不卡死。

运行方式 (项目根目录):
    python -m unittest 测试.test_站点历史自锁 -v
"""
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '源码'))

import _path_utils  # noqa: E402
import 站点历史 as 站点历史模块  # noqa: E402


class 站点历史自锁回归(unittest.TestCase):
    """事故行为契约: 记录任务 绝不允许把调用线程永久卡住。"""

    def setUp(self):
        # 单例与状态根隔离: 每个用例一颗全新的 站点历史, 指向临时目录
        self._旧模块单例 = 站点历史模块._默认实例
        self._旧类单例 = 站点历史模块.站点历史._instance
        站点历史模块._默认实例 = None
        站点历史模块.站点历史._instance = None
        self.addCleanup(self._恢复单例)

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        # LIFO: 先注册 tmp.cleanup, 再注册 AppLogger().close → close 先执行。
        # 站点历史._加载 在新实例上会发 debug 日志, 全局 AppLogger 会按
        # 当时被 mock 的状态根把日志文件开进临时目录并持有句柄 —— 不先
        # close 释放句柄, cleanup 会 WinError 32 删不掉。close 置 _file=None,
        # 之后 (patcher 已 stop) 再写日志会在真实状态根重开, 不影响后续用例。
        from 日志 import AppLogger as _AppLogger
        self.addCleanup(_AppLogger().close)
        patcher = mock.patch.object(_path_utils, 'get_state_root',
                                    return_value=self._tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.历史 = 站点历史模块.取站点历史()

    def _恢复单例(self):
        站点历史模块._默认实例 = self._旧模块单例
        站点历史模块.站点历史._instance = self._旧类单例

    def _记录任务(self):
        # 占位域 (红线要求): 域名仅用于 取域名() 解析, 用什么值不影响行为
        self.历史.记录任务(
            'https://m.example.com/book/1092976/',
            '人在诡异，靠第四次灭雷顶至高',
            total=402, failed=[],
            反爬统计={'rate_limit': 3},
            质检摘要={'质检章数': 402, '通过': 402, '未通过': 0, '平均分': 100},
            output_file='人在诡异.txt')

    @staticmethod
    def _起线程(fn):
        """子线程执行 fn; 完成标记/异常存入 thread.result_ 容器。

        daemon=True + 限时 join —— 回归发生时测试 fail-fast, 而不是把
        整个测试进程一起卡死。
        """
        完成容器 = []

        def 目标():
            try:
                fn()
                完成容器.append('完成')
            except Exception as e:      # pragma: no cover — 异常也要可见
                完成容器.append(e)

        t = threading.Thread(target=目标, daemon=True)
        t.result_ = 完成容器
        t.start()
        return t

    def _等完成(self, t, 名字, 超时秒=5.0):
        t.join(超时秒)
        self.assertFalse(t.is_alive(), f'{名字} 线程 {超时秒:.0f}s 未返回 = 自锁死回归!')
        self.assertEqual(t.result_, ['完成'], f'{名字} 线程内出现异常')

    def test_记录任务_独立线程可完成_不再自锁死(self):
        """事故主现场: 记录任务 持 _io_lock 调 _落盘 → 同线程二次加锁卡死。
        修复后必须在调用线程内自行完成。"""
        self._等完成(self._起线程(self._记录任务), '记录任务')

    def test_记录任务_与并发flush和查询互不卡死(self):
        """事故次现场: 任务线程卡在 记录任务 里握着锁时, flush()/查站点()
        被同一把锁拖死 (退出流程冻住的直接原因)。修复后三方并发都能完成。"""
        t1 = self._起线程(self._记录任务)
        t2 = self._起线程(lambda: [self.历史.flush() for _ in range(5)])
        t3 = self._起线程(lambda: self.历史.查站点(
            'https://m.example.com/book/1092976/'))
        self._等完成(t1, '记录任务')
        self._等完成(t2, 'flush')
        self._等完成(t3, '查站点')

    def test_记录任务_数据正确落盘(self):
        """功能不回归: 锁重构后记录内容与防抖/合并语义保持不变。"""
        self._记录任务()
        self.历史.flush()      # 兜底强制刷盘 (新实例首写本就会落, 此处显式)
        文件 = Path(self._tmp.name) / '数据' / '站点历史.json'
        数据 = json.loads(文件.read_text(encoding='utf-8'))
        域 = 数据['m.example.com']
        self.assertEqual(域['任务数'], 1)
        self.assertEqual(域['书籍'][-1]['书名'], '人在诡异，靠第四次灭雷顶至高')
        self.assertEqual(域['书籍'][-1]['总章数'], 402)
        self.assertEqual(域['反爬统计']['rate_limit'], 3)
        self.assertEqual(域['书籍'][-1]['质检摘要']['平均分'], 100)

    def test_zz_持锁调用落盘_同线程嵌套也不再自锁死(self):
        """RLock 兜底契约: 即便回到事故形态 (持 _io_lock 调 _落盘) 也必须
        完成。方法名以 zz 结尾保证最后执行 —— 若回归, 本用例会留下持锁
        线程, 放最后避免污染前面用例。"""
        def 事故形态():
            with self.历史._io_lock:
                快照 = self.历史._快照(force=True)
                self.历史._落盘(快照)      # 旧事故调用序: 持锁调 _落盘

        self._等完成(self._起线程(事故形态), '持锁落盘')


if __name__ == '__main__':
    unittest.main(verbosity=2)
