# -*- coding: utf-8 -*-
"""折叠目录自救 (2026-10-12) 的回归用例 (离线)。

**背景** (真机实测倒逼): 折叠站只把**头尾若干章**放目录页, 中间章节收进"全部目录"
子页 —— 实测某站页面自述**另有约 126 章未展示**。此前程序只会 `_log.warn` 告警,
用户得自己去找入口并重跑; 现在会自动跳过去重新解析一次。

本文件守两件事:
  ① 纯函数 `_找完整目录链接()` 的判定与安全边界 (同域优先 / 跳过 js 与自指 / 找不到返回空);
  ② 自救编排 `_折叠自救()`: 变多了才采用、没变多保持原结果、**最多一层**(防死循环)。

运行方式 (项目根目录):
    python -m unittest discover -s 测试 -v
"""
import sys
import unittest
from pathlib import Path

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

from bs4 import BeautifulSoup              # noqa: E402
import 爬虫 as C                            # noqa: E402


def _汤(html: str):
    return BeautifulSoup(html, 'html.parser')


class Test找完整目录链接(unittest.TestCase):

    def test_按锚文本命中并绝对化(self):
        汤 = _汤('<a href="/book/1/all.html">全部章节</a>'
                '<a href="/book/1/2.html">第2章</a>')
        出 = C._找完整目录链接(汤, 'https://www.example.com/book/1/')
        self.assertEqual(出, 'https://www.example.com/book/1/all.html')

    def test_按href特征命中_文字很泛也能认(self):
        汤 = _汤('<a href="/book/1/indexlist.html">更多</a>')
        出 = C._找完整目录链接(汤, 'https://www.example.com/book/1/')
        self.assertTrue(出.endswith('indexlist.html'), 出)

    def test_跳过javascript与锚点与自指(self):
        汤 = _汤('<a href="javascript:void(0)">全部章节</a>'
                '<a href="#all">全部章节</a>'
                '<a href="https://www.example.com/book/1/">全部章节</a>')
        self.assertEqual(C._找完整目录链接(汤, 'https://www.example.com/book/1/'), '')

    def test_同域优先于跨域(self):
        汤 = _汤('<a href="https://other.com/all.html">全部章节</a>'
                '<a href="/book/1/all.html">全部章节</a>')
        出 = C._找完整目录链接(汤, 'https://www.example.com/book/1/')
        self.assertIn('example.com', 出)

    def test_只有跨域时也返回(self):
        汤 = _汤('<a href="https://other.com/book/1/all.html">全部章节</a>')
        出 = C._找完整目录链接(汤, 'https://www.example.com/book/1/')
        self.assertIn('other.com', 出)

    def test_找不到时返回空(self):
        for html in ('', '<a href="/book/1/2.html">第2章</a>',
                     '<p>没有链接</p>'):
            with self.subTest(html=html):
                self.assertEqual(
                    C._找完整目录链接(_汤(html), 'https://www.example.com/book/1/'), '')

    def test_相对上级路径也能绝对化(self):
        汤 = _汤('<a href="../all.html">完整目录</a>')
        出 = C._找完整目录链接(汤, 'https://www.example.com/book/1/')
        self.assertEqual(出, 'https://www.example.com/book/all.html')


class _假蜘蛛:
    """最小替身: 只提供 _折叠自救 需要的 get_chapter_list。"""

    def __init__(self, 第二轮结果):
        self.第二轮结果 = 第二轮结果
        self.调用 = []

    def get_chapter_list(self, url, sort_chapters=False, _折叠自救层=0):
        self.调用.append((url, _折叠自救层))
        return self.第二轮结果


class Test折叠自救编排(unittest.TestCase):

    _汤页 = None

    def setUp(self):
        self.汤 = _汤('<a href="/book/1/all.html">全部章节</a>')

    def test_变多了才采用(self):
        蛛 = _假蜘蛛([{'title': f'第{i}章', 'url': f'/c{i}'} for i in range(1, 51)])
        原 = [{'title': '第1章', 'url': '/c1'}]
        # 直接借用类方法 (不需要真实例状态)
        出 = C.NovelSpider._折叠自救(蛛, self.汤, 'https://www.example.com/book/1/', 原, False)
        self.assertEqual(len(出), 50, '更全的列表应被采用')
        self.assertEqual(蛛.调用, [('https://www.example.com/book/1/all.html', 1)],
                         '递归必须带 _折叠自救层=1 (防死循环)')

    def test_没变多则保持原结果(self):
        蛛 = _假蜘蛛([{'title': '第1章', 'url': '/c1'}])       # 没变多
        原 = [{'title': '第1章', 'url': '/c1'}, {'title': '第2章', 'url': '/c2'}]
        出 = C.NovelSpider._折叠自救(蛛, self.汤, 'https://www.example.com/book/1/', 原, False)
        self.assertEqual(出, 原)

    def test_第二轮抛异常也不炸_保持原结果(self):
        class _炸:
            def get_chapter_list(self, url, sort_chapters=False, _折叠自救层=0):
                raise RuntimeError('抓取失败')
        原 = [{'title': '第1章', 'url': '/c1'}]
        出 = C.NovelSpider._折叠自救(_炸(), self.汤,
                                'https://www.example.com/book/1/', 原, False)
        self.assertEqual(出, 原)

    def test_没有入口时不调用第二轮(self):
        蛛 = _假蜘蛛([{'title': 'x', 'url': '/x'}])
        原 = [{'title': '第1章', 'url': '/c1'}]
        无入口 = _汤('<a href="/book/1/2.html">第2章</a>')
        出 = C.NovelSpider._折叠自救(蛛, 无入口,
                                'https://www.example.com/book/1/', 原, False)
        self.assertEqual(出, 原)
        self.assertEqual(蛛.调用, [], '没有入口就不该发起第二次抓取')

    def test_签名带防重入参数(self):
        """防"空转通过": 自救靠 `_折叠自救层` 防递归, 参数名被改掉要响亮失败。"""
        import inspect
        参数 = inspect.signature(C.NovelSpider.get_chapter_list).parameters
        self.assertIn('_折叠自救层', 参数,
                      'get_chapter_list 必须保留 `_折叠自救层` 参数 (防自救递归死循环)')


if __name__ == '__main__':
    unittest.main(verbosity=2)
