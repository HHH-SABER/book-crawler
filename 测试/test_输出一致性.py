# -*- coding: utf-8 -*-
"""输出一致性自检 + 书名退化回退命名 回归 (2026-10-08 新增, 全离线)。

倒逼事故: `抓取结果/novel.txt` —— 一本书**缺「第 1 部分」**、且**混进了另一本书
的章节**, 全程零报警; 文件名还退化成了字面量 `novel`, 用户完全无法辨认。
用户是在浏览器里手动打开源站才发现的。本文件锁定两条防线:

  A. **文件名不再退化成字面量** (`_书名已退化` / `_从URL取书标识`), 且与
     `死书处理.书名退化集合` **同口径** (两处漂移会让"文件名回退"与"死书判定"对不上)。
  B. **抓完自检**: 缺头 / 断号 / 重号 / 混入其它书 必须被报出来
     (`_检查输出一致性`), 并随质检报告落盘。

运行: python -m unittest discover -s 测试
"""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))
sys.path.insert(0, str(_根 / '测试'))

import _沙箱              # noqa: E402,F401  状态根沙箱 (LOCALAPPDATA 隔离)
import 爬虫 as C           # noqa: E402
import 死书处理 as S        # noqa: E402


class Test书名退化口径(unittest.TestCase):

    def test_与死书处理的退化集合同口径(self):
        """两个集合必须一致 —— 一个决定"判死书", 一个决定"文件名回退"。"""
        这边 = {str(x).strip() for x in C.书名退化集合 if x is not None}
        那边 = {str(x).strip() for x in S.书名退化集合 if x is not None}
        self.assertEqual(这边, 那边,
                         '爬虫.书名退化集合 与 死书处理.书名退化集合 已漂移: '
                         f'{sorted(这边)} vs {sorted(那边)}')

    def test_退化判定真值表(self):
        for 真 in (None, '', '   ', 'novel', '小说',
                   'novel(1)', '小说(2)', ' 小说(3) '):
            with self.subTest(值=真):
                self.assertTrue(C._书名已退化(真), f'{真!r} 应判为退化')
        for 假 in ('示例书名甲', '示例书名乙', 'novel 外传', '小说集', 'novelx',
                   '示例书名丙',
                   # 大小写**刻意**不折叠: 死书处理 用的是精确匹配, 这里必须同口径,
                   # 否则就出现"文件名回退了但死书判定不认"的漂移 (本文件的第一个用例在守这条)。
                   'NOVEL'):
            with self.subTest(值=假):
                self.assertFalse(C._书名已退化(假), f'{假!r} 不该判为退化')


class Test从URL取书标识(unittest.TestCase):

    def test_取域名与路径段(self):
        表 = {
            'https://example.com/4y9k/index.html': 'example.com_4y9k',
            'https://m.example.com/abc/def.html': 'example.com_abc',
            # 末段是纯数字时它就是"书号", 比上一级目录更有辨识度 → 取它
            'http://www.site.example.org/book/123': 'site.example.org_123',
            'https://x.example.net/a/index.htm': 'x.example.net_a',
        }
        for url, 期望 in 表.items():
            with self.subTest(url=url):
                self.assertEqual(C._从URL取书标识(url), 期望)

    def test_去掉www与m前缀(self):
        self.assertTrue(C._从URL取书标识(
            'https://m.example.com/b/1.html').startswith('example.com_'))

    def test_只有域名时也能给标识(self):
        self.assertEqual(C._从URL取书标识('https://example.com'), 'example.com')

    def test_空URL不炸且返回空(self):
        for 空 in ('', None, '不是URL'):
            with self.subTest(值=空):
                self.assertEqual(C._从URL取书标识(空), '')


class Test输出一致性自检(unittest.TestCase):
    """用临时目录 + 合成标记行离线验证 (不碰任何真实抓取结果)。"""

    def setUp(self):
        self._目录 = tempfile.TemporaryDirectory(prefix='nc_consist_')
        self.目录 = Path(self._目录.name)
        # 只借实例方法用到的类属性, 不实例化 NovelSpider (那会建 session/读配置)
        self.替身 = types.SimpleNamespace(_章节号族=C.NovelSpider._章节号族)

    def tearDown(self):
        self._目录.cleanup()

    def _写(self, 名, 标记s):
        文本 = ''
        for t in 标记s:
            文本 += f'## {t}\n\n正文占位。\n\n'
        p = self.目录 / 名
        p.write_text(文本, encoding='utf-8')
        return p

    def _查(self, p, 书名为='某书'):
        return C.NovelSpider._检查输出一致性(self.替身, str(p), 书名为)

    def test_干净文件不报(self):
        p = self._写('干净.txt', [f'第{i}章 标题{i}' for i in range(1, 11)])
        self.assertEqual(self._查(p), [])

    def test_缺头被报出(self):
        """这起事故的直接症状: 从「第 2 部分」开始, 缺第 1 部分。"""
        p = self._写('缺头.txt', [f'第{i}部分' for i in range(2, 8)])
        问题 = self._查(p)
        self.assertTrue(any('缺头' in x and '第 1' in x for x in 问题), 问题)

    def test_断号被报出(self):
        p = self._写('断号.txt', ['第1章', '第2章', '第3章', '第9章'])
        问题 = self._查(p)
        self.assertTrue(any('断号' in x for x in 问题), 问题)

    def test_重号被报出(self):
        """同一章号出现两次 = 两份来源/两本书被写进同一文件的典型特征。"""
        p = self._写('重号.txt', ['第1章 a', '第2章 b', '第2章 c', '第3章 d'])
        问题 = self._查(p)
        self.assertTrue(any('重号' in x for x in 问题), 问题)

    def test_混入其它书被报出(self):
        p = self._写('甲书.txt', ['第1章 a', '第2章 b', '示例书名乙 第25章 分歧点'])
        self._写('示例书名乙（TXT+云书架）.txt', ['第1章 x'])
        问题 = self._查(p, '甲书')
        self.assertTrue(any('混入其它书' in x for x in 问题), 问题)

    def test_不把自身书名当混入(self):
        p = self._写('某书.txt', ['第1章 a', '第2章 b'])
        self.assertEqual(self._查(p, '某书'), [])

    def test_质检报告文件名不当词表(self):
        """`.质检报告.txt` 是程序自己写的报告, 不该被当成"别的书"。"""
        p = self._写('某书.txt', ['第1章 a', '第2章 b'])
        (self.目录 / '某书.txt.质检报告.txt').write_text('报告', encoding='utf-8')
        self.assertEqual(self._查(p, '某书'), [])

    def test_没有标记行时返回空(self):
        p = self._写('空书.txt', [])
        self.assertEqual(self._查(p), [])

    def test_文件不存在不抛异常(self):
        self.assertEqual(self._查(self.目录 / '不存在.txt'), [])


class Test质检报告接受一致性告警(unittest.TestCase):

    def test_一致性问题会写进报告(self):
        """有告警时必须落进 `.质检报告.txt`, 不能只在内存里过一遍。"""
        with tempfile.TemporaryDirectory(prefix='nc_report_') as d:
            替身 = types.SimpleNamespace(
                _质检记录=[], _反爬统计={}, _限频最大退避=0, _引擎统计={},
                _增量跳过数=0, _爬取历史统计={})
            out = os.path.join(d, '某书.txt')
            Path(out).write_text('## 第1章\n\n正文\n', encoding='utf-8')
            摘要 = C.NovelSpider._生成质检汇总报告(
                替身, out, 1, [], 一致性问题=['疑似缺头: 缺第 1 部分'])
            报告 = Path(out + '.质检报告.txt').read_text(encoding='utf-8')
            self.assertIn('输出一致性告警', 报告)
            self.assertIn('疑似缺头', 报告)
            self.assertIsInstance(摘要, dict)


class Test收尾汇总接线(unittest.TestCase):
    """接线用例: 组件各自绿 ≠ 接上了。

    上面只证明 `_检查输出一致性` 与 `_生成质检汇总报告` 各自能用;
    这里证明 **`_收尾汇总` 真的把自检结果传下去**(并只读不写用户数据: 所有
    落盘协作者全部打桩, 含项目根的 `网站清单.txt`)。
    """

    def test_自检结果会传给质检报告(self):
        with tempfile.TemporaryDirectory(prefix='nc_wire_') as d:
            out = os.path.join(d, '缺头.txt')
            Path(out).write_text('## 第2部分\n\n正文\n## 第3部分\n\n正文\n',
                                 encoding='utf-8')
            蜘蛛 = C.NovelSpider('https://example.com')
            捕获 = {}

            def 假报告(output_file, total, failed, 一致性问题=None):
                捕获['一致性问题'] = 一致性问题
                return {'质检章数': 0}

            try:
                with mock.patch.object(C, '_站点历史可用', False), \
                        mock.patch.object(蜘蛛, '_生成质检汇总报告', 假报告), \
                        mock.patch.object(蜘蛛, '_记录站点历史', lambda *a, **k: None), \
                        mock.patch.object(蜘蛛, '_captcha_manager', None), \
                        mock.patch.object(蜘蛛, '_爬取历史', None), \
                        mock.patch('网站清单.记录', lambda *a, **k: None), \
                        mock.patch('网站清单.域名网站名', lambda *a, **k: ''), \
                        mock.patch('风控事件.add', lambda *a, **k: None), \
                        mock.patch('风控事件.flush', lambda *a, **k: None):
                    蜘蛛._收尾汇总(out, 'https://example.com/book/1.html',
                                '某书', 2, [], False, 正常完成=True)
            finally:
                蜘蛛.close()

            self.assertIn('一致性问题', 捕获, '_收尾汇总 没把自检结果传给质检报告')
            告警 = 捕获['一致性问题'] or []
            self.assertTrue(any('缺头' in x for x in 告警),
                            f'缺头问题没被传下去: {告警}')

    def test_中断任务不做自检(self):
        """"停止/中断"时文件本就半截, 自检报警只会是噪声 → 必须跳过。"""
        with tempfile.TemporaryDirectory(prefix='nc_wire2_') as d:
            out = os.path.join(d, '半截.txt')
            Path(out).write_text('## 第5部分\n\n正文\n', encoding='utf-8')
            蜘蛛 = C.NovelSpider('https://example.com')
            捕获 = {}

            def 假报告(output_file, total, failed, 一致性问题=None):
                捕获['一致性问题'] = 一致性问题
                return {}

            try:
                with mock.patch.object(C, '_站点历史可用', False), \
                        mock.patch.object(蜘蛛, '_生成质检汇总报告', 假报告), \
                        mock.patch.object(蜘蛛, '_记录站点历史', lambda *a, **k: None), \
                        mock.patch.object(蜘蛛, '_captcha_manager', None), \
                        mock.patch.object(蜘蛛, '_爬取历史', None), \
                        mock.patch('网站清单.记录', lambda *a, **k: None), \
                        mock.patch('网站清单.域名网站名', lambda *a, **k: ''), \
                        mock.patch('风控事件.add', lambda *a, **k: None), \
                        mock.patch('风控事件.flush', lambda *a, **k: None):
                    蜘蛛._收尾汇总(out, 'https://example.com/book/1.html',
                                '某书', 1, [], False, 正常完成=False)
            finally:
                蜘蛛.close()

            self.assertEqual(捕获.get('一致性问题'), [],
                             '中断的任务不该报一致性告警 (文件本就是半截的)')


class Test续传计数与另起名(unittest.TestCase):
    """缺「第 1 部分」的机制 + 防"混书越写越混" (2026-10-08 补)。"""

    def setUp(self):
        self._目录 = tempfile.TemporaryDirectory(prefix='nc_count_')
        self.目录 = Path(self._目录.name)

    def tearDown(self):
        self._目录.cleanup()

    def _写(self, 名, 文本):
        p = self.目录 / 名
        p.write_text(文本, encoding='utf-8')
        return p

    def test_裸URL头不算章节(self):
        """`## <URL>` 是异常写入的头部残留; 算成 1 章会让续传位置偏 1 → 跳章。"""
        p = self._写('a.txt', '## https://example.com/book/index.html\n\n'
                             '## 第2部分\n\n正文\n\n## 第3部分\n\n正文\n')
        self.assertEqual(C.NovelSpider._count_written_chapters(None, str(p)), 2,
                         'URL 头被算成了章节 → 续传会跳章 (实证症状: 缺第 1 部分)')

    def test_正常章节照数(self):
        p = self._写('b.txt', ''.join(f'## 第{i}章 标题\n\n正文\n\n'
                                     for i in range(1, 6)))
        self.assertEqual(C.NovelSpider._count_written_chapters(None, str(p)), 5)

    def test_文件不存在返回0(self):
        self.assertEqual(
            C.NovelSpider._count_written_chapters(None, str(self.目录 / 'x.txt')), 0)

    def test_另起文件名避让既有文件(self):
        (self.目录 / '书.txt').write_text('x', encoding='utf-8')
        (self.目录 / '书(1).txt').write_text('x', encoding='utf-8')
        新 = C.NovelSpider._另起输出文件名(str(self.目录 / '书.txt'))
        self.assertEqual(os.path.basename(新), '书(2).txt')

    def test_另起名字不覆盖原文件(self):
        p = self._写('原.txt', '原始内容不能被毁')
        新 = C.NovelSpider._另起输出文件名(str(p))
        self.assertNotEqual(os.path.abspath(新), os.path.abspath(str(p)))
        self.assertEqual(p.read_text(encoding='utf-8'), '原始内容不能被毁')


if __name__ == '__main__':
    unittest.main(verbosity=2)
