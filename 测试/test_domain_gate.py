# -*- coding: utf-8 -*-
"""同域闸门单测: GUI 批量/远控多任务同站串行。

背景 (HANDOFF 待办 #1 后半): als1010 事故触发链之一 = GUI 批量 11 URL 同站
并发 (run_batch 有"同站最多 1 本并行", GUI 逐 URL create_task 无此保护)。
本测试锁定闸门五个行为: 同域同对象 / 异域隔离 / 无域名放行 / 同域串行+排队
提示一次 / 排队中 stop 可打断且不误 release。

离线运行: python -m unittest discover -s 测试 -v
"""
import sys
import threading
import time
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / '源码' / 'gui_components'))

import task_manager as tm   # noqa: E402


class Test同域闸门(unittest.TestCase):

    def test_同域同对象_异域不同对象(self):
        g1 = tm._取域闸门('https://a.example/book/1')
        g2 = tm._取域闸门('https://a.example/book/2')
        g3 = tm._取域闸门('https://b.example/book/1')
        self.assertIs(g1, g2, '同域必须复用同一闸门')
        self.assertIsNot(g1, g3, '异域必须互不干扰')

    def test_无域名放行(self):
        self.assertIsNone(tm._取域闸门('不是URL'), '解析不出域名应放行')
        self.assertTrue(tm._获取域闸门(None), 'None 闸门视为已获得')

    def test_同域串行_第二者排队且提示一次(self):
        g = tm._取域闸门('https://c.example/x')
        self.assertTrue(tm._获取域闸门(g))
        结果 = {}
        提示 = []

        def 第二者():
            ok = tm._获取域闸门(g, None, lambda: 提示.append(1))
            结果['ok'] = ok
            if ok:
                g.release()

        t = threading.Thread(target=第二者, daemon=True)
        t.start()
        time.sleep(1.5)
        self.assertNotIn('ok', 结果, '闸门未释放时第二者必须排队')
        g.release()
        t.join(5)
        self.assertTrue(结果.get('ok'), '释放后第二者应获得')
        self.assertEqual(提示, [1], '排队提示恰好一次')

    def test_排队中stop可打断(self):
        g = tm._取域闸门('https://d.example/x')
        self.assertTrue(tm._获取域闸门(g))
        stop = threading.Event()
        结果 = {}

        def 排队者():
            结果['ok'] = tm._获取域闸门(g, stop)

        t = threading.Thread(target=排队者, daemon=True)
        t.start()
        time.sleep(1.2)
        stop.set()
        t.join(4)
        self.assertIs(结果.get('ok'), False,
                      'stop 后应放弃等待 (False, 未获得故不 release)')
        # 主线程持有的闸门仍可用: 再获取一次证明未被误放
        g.release()
        self.assertTrue(tm._获取域闸门(g))
        g.release()

    def test_异域并行互不阻塞(self):
        g1 = tm._取域闸门('https://e.example/x')
        g2 = tm._取域闸门('https://f.example/x')
        t0 = time.time()
        self.assertTrue(tm._获取域闸门(g1))
        self.assertTrue(tm._获取域闸门(g2))
        self.assertLess(time.time() - t0, 0.5, '异域获取不应有等待')
        g1.release()
        g2.release()


if __name__ == '__main__':
    unittest.main(verbosity=2)
