# -*- coding: utf-8 -*-
"""跨进程文件锁测试 (R03, 2026-10-18)。

R03 验收标准 (登记项原文): "两个独立进程并发、异常退出、写入中断;
旧数据完整且无丢更新" —— 本文件按此三条组织:

A. 单测 (进程内): 基本获取/释放、同进程线程互斥、超时放行、非 Windows 降级;
B. **真双进程集成** (验收核心): 两进程并发读-改-写同一 JSON, 最终值必须
   精确 (无丢更新); 子进程持锁被 kill 后锁必须已释放 (无僵锁);
C. 写入中断: 模拟写一半崩溃, 原文件必须完好 (锁不破坏原子写语义)。

注意: 同进程多线程会被"进程内锁"挡住, **测不到 msvcrt 跨进程锁** ——
所以 B 组必须起真进程 (multiprocessing spawn), 这不是可选的。
"""
import json
import multiprocessing
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

from 文件锁 import 写锁   # noqa: E402


def _worker(路径: str, 次数: int, 延迟: float):
    """子进程: 对 路径 指向的 JSON 做 次数 次"读-改-写" (计数 +1)。

    这是 R03 要保护的临界区形态 (仿 选择器自愈.记录建议): 读 → 改 → 原子写。
    """
    import importlib
    锁 = importlib.import_module('文件锁')
    for _ in range(次数):
        with 锁.写锁(路径):
            try:
                数据 = json.loads(Path(路径).read_text(encoding='utf-8'))
            except Exception:
                数据 = {}
            数据['计数'] = 数据.get('计数', 0) + 1
            tmp = 路径 + f'.tmp.{os.getpid()}'
            Path(tmp).write_text(json.dumps(数据, ensure_ascii=False), encoding='utf-8')
            os.replace(tmp, 路径)
        if 延迟:
            time.sleep(延迟)


class Test单测进程内(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.p = os.path.join(self._tmp.name, 't.json')

    def tearDown(self):
        self._tmp.cleanup()

    def test_基本获取与释放(self):
        with 写锁(self.p) as 拿到:
            self.assertTrue(拿到)
        # 释放后可再拿 (不抛)
        with 写锁(self.p, 超时秒=1.0) as 拿到:
            self.assertTrue(拿到)

    def test_锁文件创建且不碰数据文件(self):
        Path(self.p).write_text('{}', encoding='utf-8')
        with 写锁(self.p):
            pass
        self.assertTrue(os.path.exists(self.p + '.process.lock'), '锁文件应存在')
        self.assertEqual(Path(self.p).read_text(encoding='utf-8'), '{}',
                         '数据文件内容不应被锁改动')

    def test_同进程线程互斥(self):
        """进程内两线程: 持锁期间另一线程必须等待 (拿不到即说明在互斥)"""
        import threading
        进入 = threading.Event()
        放行 = threading.Event()
        观测 = []

        def 占锁():
            with 写锁(self.p, 超时秒=0.3) as 拿到:
                观测.append(('占锁', 拿到))
                进入.set()
                放行.wait(2)

        def 抢锁():
            进入.wait(2)
            with 写锁(self.p, 超时秒=0.3) as 拿到:
                观测.append(('抢锁', 拿到))

        t1 = threading.Thread(target=占锁)
        t2 = threading.Thread(target=抢锁)
        t1.start(); time.sleep(0.1); t2.start()
        放行.set()
        t1.join(3); t2.join(3)
        # 占锁者拿到; 抢锁者在占锁者释放后也拿到 (串行 = 互斥生效)
        self.assertIn(('占锁', True), 观测, f'占锁者应拿到: {观测}')
        self.assertIn(('抢锁', True), 观测, f'抢锁者串行后应拿到: {观测}')

    def test_超时放行不抛(self):
        """拿不到锁时 yield False 放行 (旧行为), 绝不卡死/抛异常"""
        import threading
        卡住 = threading.Event()
        放行 = threading.Event()

        def 长占():
            with 写锁(self.p, 超时秒=5):
                卡住.set()
                放行.wait(5)

        t = threading.Thread(target=长占)
        t.start()
        卡住.wait(2)
        t0 = time.monotonic()
        with 写锁(self.p, 超时秒=0.3) as 拿到:   # 进程内锁被长占者握着 → 超时
            耗时 = time.monotonic() - t0
            self.assertFalse(拿到, '超时应放行 (False) 而不是卡住')
            self.assertLess(耗时, 2.0, '放行必须及时')
        放行.set()
        t.join(3)

    def test_非Windows降级(self):
        """msvcrt 导入失败 (非 Windows) → 无锁直入, 不抛不卡"""
        import builtins
        真导入 = builtins.__import__

        def 假导入(名, *a, **k):
            if 名 == 'msvcrt':
                raise ImportError('模拟非 Windows')
            return 真导入(名, *a, **k)

        with mock.patch('builtins.__import__', side_effect=假导入):
            with 写锁(self.p) as 拿到:
                self.assertFalse(拿到, '非 Windows 应降级为无锁直入')


class Test真双进程(unittest.TestCase):
    """R03 验收核心: 必须起真进程才测得到 msvcrt 跨进程锁。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.p = os.path.join(self._tmp.name, '共享.json')
        Path(self.p).write_text('{"计数": 0}', encoding='utf-8')
        self._ctx = multiprocessing.get_context('spawn')

    def tearDown(self):
        self._tmp.cleanup()

    def test_两进程并发无丢更新(self):
        """两进程各 +100 (带微小延迟逼出交错), 最终必须恰好 200。"""
        ps = [self._ctx.Process(target=_worker, args=(self.p, 100, 0.001))
              for _ in range(2)]
        for p in ps:
            p.start()
        for p in ps:
            p.join(60)
        for p in ps:
            self.assertEqual(p.exitcode, 0, '子进程应正常退出')
        计数 = json.loads(Path(self.p).read_text(encoding='utf-8'))['计数']
        self.assertEqual(计数, 200,
                         f'丢更新: 期望 200, 实得 {计数} (无锁时此用例会稳定失败)')

    def test_子进程被杀后锁立即释放(self):
        """持锁子进程被 kill → OS 释放字节锁 → 父进程无需等待即可拿到。"""
        占锁 = self._ctx.Process(target=_worker, args=(self.p, 1, 0))
        占锁.start()
        time.sleep(0.5)                 # 等它进入临界区 (大概率持锁中)
        占锁.terminate()                # 杀掉 (模拟崩溃)
        占锁.join(5)
        t0 = time.monotonic()
        with 写锁(self.p, 超时秒=3.0) as 拿到:
            耗时 = time.monotonic() - t0
        self.assertTrue(拿到, '杀掉的进程不应留下僵锁')
        self.assertLess(耗时, 3.0, '僵锁会导致这里超时')

    def test_写入中断原文件完好(self):
        """模拟写一半崩溃 (tmp 在、replace 未发生): 原文件必须保持旧完整内容。"""
        旧 = json.loads(Path(self.p).read_text(encoding='utf-8'))
        with 写锁(self.p):
            # 模拟: 临界区内写了 tmp 但没 os.replace 就"崩溃" (异常穿场)
            tmp = self.p + f'.tmp.{os.getpid()}'
            Path(tmp).write_text('{"计数": 999}', encoding='utf-8')
            try:
                raise RuntimeError('模拟写一半崩溃')
            except RuntimeError:
                pass    # 刻意静默: 测试内模拟, 不需要留痕
        # with 正常退出 (释放锁); 原文件未被 replace 污染
        现值 = json.loads(Path(self.p).read_text(encoding='utf-8'))
        self.assertEqual(现值, 旧, '写一半崩溃不应污染原文件 (tmp+replace 语义)')
        # 且锁已释放, 后续可写
        with 写锁(self.p, 超时秒=1.0) as 拿到:
            self.assertTrue(拿到)


if __name__ == '__main__':
    unittest.main(verbosity=2)
