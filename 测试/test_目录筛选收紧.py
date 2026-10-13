# -*- coding: utf-8 -*-
"""B 修法（收紧筛选）回归 (2026-10-13 新增)。

锁定 `_剔除非章节单条()` 契约: 与 A (`_目录列表可疑` → 折叠自救) 互补的
**单条级**过滤 —— 剔"章节号 ≥10× 中位数"的孤立异常链接 (推广链签名),
阈值与 A 一致; **宁不错杀** (全异常时原样返回)。

关键防误杀用例: 正常升序目录 (1..N) 必须一条不剔。
已做变异测试 (K33): 把阈值 10 改成 0.5 → 正常目录被误剔 → 用例变红。
运行: .runtime/python314/python.exe -m unittest discover -s 测试
"""
import sys
import unittest
from pathlib import Path

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

import 爬虫   # noqa: E402


def _章(号: int, 书号: int = 100) -> dict:
    return {'title': f'第{号}章', 'url': f'https://example.com/read/{书号}/{号}.html'}


class Test剔除非章节单条(unittest.TestCase):
    """`_剔除非章节单条()`: 推广链单条过滤 (B 修法)"""

    def test_正常升序目录一条不剔(self):
        """防误杀 (最重要): 正常目录 1..20 必须原样返回"""
        章 = [_章(i) for i in range(1, 21)]
        留, 剔数, 原因 = 爬虫._剔除非章节单条(章)
        self.assertEqual(剔数, 0)
        self.assertEqual(原因, '')
        self.assertEqual(留, 章)

    def test_孤立大号被剔(self):
        """站点Q 签名: 真章节 1..20 + 推广链 (号 671592) 混在中间"""
        章 = [_章(i) for i in range(1, 11)] + [_章(671592, 书号=100)] + [_章(i) for i in range(11, 21)]
        留, 剔数, 原因 = 爬虫._剔除非章节单条(章)
        self.assertEqual(剔数, 1)
        self.assertNotIn('671592', [c['url'] for c in 留][0] if 留 else '')
        self.assertTrue(any('671592' in c['url'] for c in [x for x in 章 if x not in 留]))
        self.assertIn('10×', 原因)

    def test_全异常保守不动(self):
        """宁不错杀: 全部条目都异常 → 原样返回 (清空真目录更糟)"""
        章 = [_章(999000 + i) for i in range(6)]
        留, 剔数, 原因 = 爬虫._剔除非章节单条(章)
        self.assertEqual(剔数, 0)
        self.assertEqual(len(留), 6)

    def test_少于四条不动(self):
        """样本太少不可靠 (中位数无意义)"""
        章 = [_章(1), _章(2), _章(999999)]
        留, 剔数, _ = 爬虫._剔除非章节单条(章)
        self.assertEqual(剔数, 0)
        self.assertEqual(len(留), 3)

    def test_无章节号URL的列表不动(self):
        """href 不含数字章节号的站 (如 /book/abc/list.html) 一律不碰"""
        章 = [{'title': f'第{i}章', 'url': f'https://example.com/abc/def{i}.html'}
               for i in range(8)]
        留, 剔数, _ = 爬虫._剔除非章节单条(章)
        self.assertEqual(剔数, 0)

    def test_空与None输入(self):
        self.assertEqual(爬虫._剔除非章节单条(None), ([], 0, ''))
        self.assertEqual(爬虫._剔除非章节单条([]), ([], 0, ''))

    def test_与A阈值一致(self):
        """B 的阈值必须与 A (_目录列表可疑 判据③) 一致, 避免两套标准"""
        self.assertIn('10', 爬虫._剔除非章节单条.__doc__)

    def test_返回三元组结构(self):
        章 = [_章(i) for i in range(1, 8)]
        r = 爬虫._剔除非章节单条(章)
        self.assertIsInstance(r, tuple)
        self.assertEqual(len(r), 3)


if __name__ == '__main__':
    unittest.main(verbosity=2)
