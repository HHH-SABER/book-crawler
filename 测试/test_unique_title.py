# -*- coding: utf-8 -*-
"""同名标题分配的唯一性 (离线)。

修复背景 (TOCTOU): `_resolve_unique_title` 原本"读进程级注册表"与"登记注册表"
分两次加锁。两个并发的同名任务会各自扫到相同的 used 集合、算出**同一个**
resolved 标题, 双双登记 → 后启动的任务写盘时覆盖前一个的输出文件 (进度全丢)。
现把"读注册表 + 决策 + 登记"合并进同一临界区。

运行方式 (项目根目录):
    python -m unittest discover -s 测试 -v
"""
import sys
import tempfile
import threading
import unittest
import uuid
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '源码'))

from 爬虫 import _resolve_unique_title  # noqa: E402


class TestResolveUniqueTitle(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.addCleanup(self._tmp.cleanup)
        # 注册表是进程级的, 用随机书名避免与其它用例/真实运行互相干扰
        self.书名 = '并发查重书' + uuid.uuid4().hex[:8]

    def test_首次调用不加序号(self):
        self.assertEqual(_resolve_unique_title(self.书名, self.dir), self.书名)

    def test_同名第二次加序号(self):
        first = _resolve_unique_title(self.书名, self.dir)
        second = _resolve_unique_title(self.书名, self.dir)
        self.assertEqual(first, self.书名)
        self.assertEqual(second, f'{self.书名}(1)')

    def test_已存在同名文件时加序号(self):
        (Path(self.dir) / f'{self.书名}.txt').write_text('x', encoding='utf-8')
        self.assertEqual(_resolve_unique_title(self.书名, self.dir),
                         f'{self.书名}(1)')

    def test_并发分配标题互不重复(self):
        """并发回归: 两个线程必须拿到不同标题 (旧实现此处会双双拿到同一个)"""
        结果 = []
        锁 = threading.Lock()
        开始 = threading.Barrier(8)

        def _分配():
            开始.wait(timeout=10)          # 尽量让 8 个线程同时冲进临界区
            t = _resolve_unique_title(self.书名, self.dir)
            with 锁:
                结果.append(t)

        ts = [threading.Thread(target=_分配) for _ in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=20)

        self.assertEqual(len(结果), 8)
        self.assertEqual(len(set(结果)), 8, f'出现重复标题: {sorted(结果)}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
