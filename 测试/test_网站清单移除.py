# -*- coding: utf-8 -*-
"""网站清单.移除 回归 (2026-10-02 新增, 站点脱钩: 纯占位域 + NC_LEDGER_PATH 隔离)。

锁定: 命中移除/未命中 False/注释头保留(_重建 契约)/规范化兜底/文件缺失不生成模板。
运行: python -m unittest discover -s 测试
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))
sys.path.insert(0, str(_根 / '测试'))

# 清单落点隔离: NC_LEDGER_PATH 指向一次性目录, 绝不碰用户真实 网站清单.txt
沙箱 = tempfile.mkdtemp(prefix='nc_ledger_rm_')
os.environ['NC_LEDGER_PATH'] = os.path.join(沙箱, '网站清单.txt')

import _沙箱          # noqa: E402,F401  状态根沙箱
import 网站清单 as L   # noqa: E402


class Test网站清单移除(unittest.TestCase):

    def setUp(self):
        L.保存([]) if hasattr(L, '保存') else None
        # 造三行数据 (含注释头)
        p = L.文件路径()
        Path(p).write_text(
            '# 网站清单 — 程序自动维护\n'
            '# 第二行注释\n'
            'https://a.example.com/1\t站A\t书A\n'
            'https://b.example.com/2\t站B\t书B\n'
            'https://c.example.com/3\t站C\t书C\n', encoding='utf-8')

    def test_命中移除且其余行不变(self):
        self.assertTrue(L.移除('https://b.example.com/2'))
        条目 = L.读取()
        self.assertEqual(len(条目), 2)
        self.assertEqual([x['网址'] for x in 条目],
                         ['https://a.example.com/1', 'https://c.example.com/3'])

    def test_未命中返回False(self):
        self.assertFalse(L.移除('https://不存在.example.com/9'))
        self.assertEqual(len(L.读取()), 3, '未命中不得改动文件')

    def test_注释头保留(self):
        """移除走 _重建 → 表头注释不得被抹掉 (网站清单.py 契约)"""
        L.移除('https://b.example.com/2')
        内容 = Path(L.文件路径()).read_text(encoding='utf-8')
        self.assertTrue(内容.startswith('#'), '注释头必须保留')
        self.assertIn('第二行注释', 内容)

    def test_规范化兜底匹配(self):
        """尾斜杠差异视为同一条 (用户手改清单常见)"""
        self.assertTrue(L.移除('https://a.example.com/1/'))
        self.assertEqual(len(L.读取()), 2)

    def test_非http网址不入清单(self):
        self.assertFalse(L.记录('file:///D:/x.txt', '本地', '本地书'))
        self.assertEqual(len(L.读取()), 3)

    def test_文件不存在时移除不生成模板(self):
        p = L.文件路径()
        if os.path.isfile(p):
            os.remove(p)
        self.assertFalse(L.移除('https://a.example.com/1'))
        self.assertFalse(os.path.isfile(p), '对不存在的文件执行移除不得凭空生成模板')

    def test_空网址返回False(self):
        self.assertFalse(L.移除(''))
        self.assertFalse(L.移除(None))


if __name__ == '__main__':
    unittest.main(verbosity=2)
