# -*- coding: utf-8 -*-
"""死书判定回归 (2026-10-02 新增, 站点脱钩: 纯占位数据, 零 IO)。

锁定 死书处理.判定死书() 的三信号判定契约:
  页面为空 (inspect_page 重试耗尽 → 空 soup) → 站点不可达, 不可询问删除
  书名退化 (爬虫回退 novel/小说) + 0 章节    → 书已删除, 可询问删除
  书名正常 + 0 章节                          → 目录无章节, 不可询问删除
  章节数 > 0                                  → 不是死书
不变式: 可询问删除 ⟺ 类型 in 可询问删除类型 (UI 层的唯一分叉依据)
运行: python -m unittest discover -s 测试
"""
import sys
import unittest
from pathlib import Path

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

import 死书处理 as D   # noqa: E402


class Test判定死书(unittest.TestCase):

    def test_章节数大于零不是死书(self):
        self.assertIsNone(D.判定死书(页面为空=False, 书名='某书', 章节数=100))
        self.assertIsNone(D.判定死书(页面为空=True, 书名='某书', 章节数=1))

    def test_页面为空判站点不可达(self):
        r = D.判定死书(页面为空=True, 书名='某书', 章节数=0)
        self.assertEqual(r['类型'], D.类型_站点不可达)
        self.assertFalse(r['可询问删除'], '站点不可达不得询问删除 (删了可惜)')
        self.assertTrue(r['原因'])

    def test_书名退化判书已删除(self):
        for 书名 in D.书名退化集合:
            r = D.判定死书(页面为空=False, 书名=书名, 章节数=0)
            self.assertEqual(r['类型'], D.类型_书已删除, f'书名={书名!r}')
            self.assertTrue(r['可询问删除'], '书已删除应询问用户是否删除')

    def test_书名正常判目录无章节(self):
        r = D.判定死书(页面为空=False, 书名='正常书名', 章节数=0)
        self.assertEqual(r['类型'], D.类型_无章节)
        self.assertFalse(r['可询问删除'], '疑似选择器失效, 不应诱导用户删记录')

    def test_书名退化集合内容(self):
        """退化集合必须覆盖爬虫.py:5525-5531 的全部回退值 + None/空串"""
        for v in (None, '', 'novel', '小说'):
            self.assertIn(v, D.书名退化集合)

    def test_不变式_可询问删除等价类型(self):
        """可询问删除 ⟺ 类型在可询问删除类型里 (UI 不得自己判类型)"""
        for 页面为空 in (True, False):
            for 书名 in ('某书', 'novel', ''):
                r = D.判定死书(页面为空=页面为空, 书名=书名, 章节数=0)
                self.assertEqual(r['可询问删除'],
                                 r['类型'] in D.可询问删除类型)

    def test_优先级_页面为空优先于书名退化(self):
        """页面为空 + 书名退化 → 站点不可达 (而非书已删除)"""
        r = D.判定死书(页面为空=True, 书名='novel', 章节数=0)
        self.assertEqual(r['类型'], D.类型_站点不可达)

    def test_可询问删除类型只含书已删除(self):
        self.assertEqual(D.可询问删除类型, (D.类型_书已删除,))

    def test_死书错误三属性与文案(self):
        e = D.死书错误(D.类型_书已删除, '目录页无章节', 'https://example.com/book/1')
        self.assertIsInstance(e, RuntimeError)
        self.assertEqual(e.类型, D.类型_书已删除)
        self.assertEqual(e.原因, '目录页无章节')
        self.assertEqual(e.网址, 'https://example.com/book/1')
        self.assertIn(D.类型_书已删除, str(e))
        self.assertIn('目录页无章节', str(e))

    def test_死书错误网址可省(self):
        e = D.死书错误(D.类型_站点不可达, '页面为空')
        self.assertEqual(e.网址, '')

    def test_返回键完整(self):
        """三个返回分支的键集合必须一致 (UI 读键不会 KeyError)"""
        for 页面为空, 书名 in ((True, 'x'), (False, 'novel'), (False, 'x')):
            r = D.判定死书(页面为空=页面为空, 书名=书名, 章节数=0)
            self.assertEqual(set(r), {'类型', '原因', '可询问删除'})

    def test_章节数为零或负都判死书(self):
        for n in (0, -1):
            r = D.判定死书(页面为空=True, 书名='x', 章节数=n)
            self.assertIsNotNone(r)


if __name__ == '__main__':
    unittest.main(verbosity=2)
