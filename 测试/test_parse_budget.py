# -*- coding: utf-8 -*-
"""U18 · 每章 HTML 解析预算 (离线, 不联网)。

背景: 审查台账怀疑"每章把同一页 HTML 解析 3~5 次", 并据此提出做"每章只解析一次"
的重构。2026-09-11 用无扰动探针 (只包 `bs4.BeautifulSoup.__init__`, 不替换任何模块
名字) 在 4 份真实样本上实测:

    样本                       解析次数   同串重复
    630wang_content.html          1           0
    ciyewk_content.html           1           0
    ltbook_content.html           2           0
    zhiruo_content.html           2           0
    —— 平均 1.50 次/章, 同串重复 0

结论: **不存在"同一字符串被反复解析"的重复**, 因此按字符串身份做记忆化没有任何
可消除的开销; 真实成本就是 1~2 次不可避免的 lxml 解析 (5~14 ms/次)。
本文件把该结论固化为**守卫**: 今后若有人改动提取链导致同一页被反复解析, 这里会红。

另注: 先前报告里"每章解析 4 次 ≈ 55 s/千章"的估算**偏高**, 按实测 1.5 次应为
≈20 s/千章 —— 该数字已在台账中更正。

运行方式 (项目根目录):
    python -m unittest discover -s 测试 -v
"""
import sys
import unittest
from collections import Counter
from pathlib import Path

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

import bs4                       # noqa: E402

# 每章解析预算 (实测 1~2 次; 留 1 次余量给不同站点的分支差异)
每章解析上限 = 3

_样本 = sorted((_根 / '测试样本').glob('*_content.html'))


class _计数:
    """临时把 BeautifulSoup.__init__ 包一层计数 (不改任何调用路径)"""

    def __init__(self):
        self.记录 = []

    def __enter__(self):
        self._真 = bs4.BeautifulSoup.__init__
        记录 = self.记录

        def 计数_init(self_, markup='', features=None, **kw):
            记录.append((str(features),
                         len(markup) if isinstance(markup, str) else -1,
                         id(markup)))
            self._真(self_, markup, features, **kw)

        bs4.BeautifulSoup.__init__ = 计数_init
        self.记录.clear()
        return self

    def __exit__(self, *a):
        bs4.BeautifulSoup.__init__ = self._真
        return False


class Test每章解析预算(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not _样本:
            raise unittest.SkipTest('测试样本/ 下没有 *_content.html')
        import 爬虫 as crawler
        cls.爬虫 = crawler
        cls.蜘蛛 = crawler.NovelSpider.__new__(crawler.NovelSpider)
        try:
            from 反爬检测器 import 反爬检测器 as 检测器类
            cls.检测器 = 检测器类()
        except Exception:
            cls.检测器 = None

    class _假响应:
        def __init__(self, html, url):
            self.content = html.encode('utf-8', errors='replace')
            self.encoding = 'utf-8'
            self.apparent_encoding = 'utf-8'
            self.url = url
            self.status_code = 200
            self.headers = {'Content-Type': 'text/html; charset=utf-8'}

        @property
        def text(self):
            return self.content.decode('utf-8', errors='replace')

    def _跑一章(self, 文件):
        html = 文件.read_text(encoding='utf-8', errors='replace')
        域名 = 文件.stem.split('_')[0]
        假URL = f'https://{域名}.com/book/1/2.html'
        响应 = self._假响应(html, 假URL)
        with _计数() as 计:
            soup = bs4.BeautifulSoup(html, 'lxml')      # 调用方那一次
            if self.检测器:
                self.检测器.识别(响应, 0)
            正文 = self.蜘蛛._extract_content_from_html(
                soup, 响应, 假URL, 假URL, text=html)
            self.蜘蛛.clean_content(正文 or '')
        return 计.记录, len(正文 or '')

    def test_每章解析次数不超预算(self):
        for f in _样本:
            记录, _ = self._跑一章(f)
            with self.subTest(样本=f.name):
                self.assertLessEqual(
                    len(记录), 每章解析上限,
                    f'{f.name} 解析 {len(记录)} 次, 超出预算 {每章解析上限}; '
                    f'明细 {[(p, n) for p, n, _ in 记录]}')

    def test_不存在同串重复解析(self):
        """核心回归: 同一字符串对象不得被解析两次 (有则说明可做记忆化/或链路失控)"""
        for f in _样本:
            记录, _ = self._跑一章(f)
            重复 = len(记录) - len({r[2] for r in 记录})
            with self.subTest(样本=f.name):
                self.assertEqual(
                    重复, 0,
                    f'{f.name} 有 {重复} 次同串重复解析: '
                    f'{[(p, n) for p, n, _ in 记录]}')

    def test_提取链仍然产出正文(self):
        """顺手守住功能: 样本必须仍能提出正文 (防"优化"把提取链改坏)"""
        产出 = {}
        for f in _样本:
            _, 长度 = self._跑一章(f)
            产出[f.name] = 长度
        self.assertGreater(sum(产出.values()), 1000,
                           f'各样本正文长度 {产出} —— 提取链疑似被改坏')


if __name__ == '__main__':
    unittest.main(verbosity=2)
