# -*- coding: utf-8 -*-
"""qiqishu.cc / yueliang.org 站点适配 + 质检事件首次发布 回归 (2026-09-13)。

背景 (用户实测两站整单失败):
  ① qiqishu.cc "深空彼岸": 章节链接 /read/{bid}/{cid}.html 不在通用 novel_path
     (/book/) 下, 通用过滤抓不到; 正文是 document.writeln(对象.方法('BASE64')),
     对象名每页随机, 通用 qsbs_bb 检测按固定函数名匹配也拿不到。
  ② yueliang.org "禁神之下": 目录 URL /txt{bid}.html 推导不出 novel_path,
     通用过滤只剩 1 个导航链接被当章节抓; 章内分页第2页是 _2.html 非 _1.html。
  ③ 任务列表"质检"列有时不显示: _fetch_with_qc 首次质检通过 (attempt==0) 时
     不发布 '质检' 事件, GUI 只能靠任务结束后的站点历史回填 (有 5s 防抖,
     或中途退出时无回填) → 列常空。修复后首过也发布。

运行 (项目根): python -m unittest discover -s 测试 -v
"""
import importlib.util
import sys
import unittest
from pathlib import Path

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

from bs4 import BeautifulSoup           # noqa: E402

_样本 = _根 / '测试样本'


def _载入适配器(name):
    spec = importlib.util.spec_from_file_location(
        name, str(_根 / '站点适配' / f'{name}.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestQiqishu站点适配(unittest.TestCase):
    """奇书网: 目录 /book/{bid}/mulu_N.html + BASE64 正文"""

    @classmethod
    def setUpClass(cls):
        cls.ad = _载入适配器('qiqishu')
        cls.soup = BeautifulSoup(
            (_样本 / 'qiqishu_dir.html').read_bytes(), 'lxml')
        cls.body = BeautifulSoup(
            (_样本 / 'qiqishu_content.html').read_bytes(), 'lxml')

    def test_目录提取100章(self):
        ch = self.ad.parse_catalog(
            self.soup, 'https://www.qiqishu.cc/book/47/mulu_1.html',
            'https://www.qiqishu.cc', sort_chapters=True, fetch=None)
        self.assertIsInstance(ch, list)
        self.assertGreaterEqual(len(ch), 90, f'qiqishu 目录应≥90章, 实际 {len(ch)}')
        self.assertEqual(ch[0]['title'], '第一章 旧土')
        self.assertTrue(ch[0]['url'].endswith('/read/47/3980.html'),
                        ch[0]['url'])
        # 章节链接必须是 /read/ 下, 且不含目录分页/导航
        self.assertTrue(all('/read/' in c['url'] for c in ch))

    def test_正文BASE64解码(self):
        txt = self.ad.extract_content(
            self.body, 'https://www.qiqishu.cc/read/47/3980.html',
            'https://www.qiqishu.cc')
        self.assertIsNotNone(txt)
        self.assertGreater(len(txt), 500, f'正文应>500字符, 实际 {len(txt)}')
        self.assertIn('红日西坠', txt)
        self.assertNotIn('<p>', txt, '解码后不应残留 HTML 标签')

    def test_章内分页(self):
        self.assertEqual(
            self.ad.paginate('https://www.qiqishu.cc/read/47/3980.html', 1),
            'https://www.qiqishu.cc/read/47/3980_1.html')
        self.assertEqual(
            self.ad.paginate('https://www.qiqishu.cc/read/47/3980_1.html', 2),
            'https://www.qiqishu.cc/read/47/3980_2.html')

    def test_章节页推导目录(self):
        self.assertEqual(
            self.ad.catalog_from_chapter(
                'https://www.qiqishu.cc/read/47/3980_1.html',
                'https://www.qiqishu.cc'),
            'https://www.qiqishu.cc/book/47/mulu_1.html')
        self.assertIsNone(self.ad.catalog_from_chapter('https://www.qiqishu.cc/book/47.html'))

    def test_书名(self):
        self.assertEqual(
            self.ad.get_title(self.soup, 'https://www.qiqishu.cc/book/47.html',
                              'https://www.qiqishu.cc'),
            '深空彼岸')


class TestYueliang站点适配(unittest.TestCase):
    """月亮小说网: 目录 /txt{bid}.html + #booktxt 明文"""

    @classmethod
    def setUpClass(cls):
        cls.ad = _载入适配器('yueliang')
        cls.soup = BeautifulSoup(
            (_样本 / 'yueliang_dir.html').read_bytes(), 'lxml')
        cls.body = BeautifulSoup(
            (_样本 / 'yueliang_content.html').read_bytes(), 'lxml')

    def test_目录提取全部章节(self):
        ch = self.ad.parse_catalog(
            self.soup, 'http://www.yueliang.org/txt108179.html',
            'http://www.yueliang.org', sort_chapters=True)
        self.assertIsInstance(ch, list)
        self.assertGreaterEqual(len(ch), 2000, f'yueliang 目录应≥2000章, 实际 {len(ch)}')
        self.assertIn('第1章', ch[0]['title'])
        self.assertTrue(ch[0]['url'].endswith('/read/108179/2769140.html'),
                        ch[0]['url'])
        # 只认 rel="chapter", 不含"马上阅读"等入口链接
        self.assertTrue(all('/read/' in c['url'] for c in ch))

    def test_正文明文提取(self):
        txt = self.ad.extract_content(
            self.body, 'http://www.yueliang.org/read/108179/2769140.html',
            'http://www.yueliang.org')
        self.assertIsNotNone(txt)
        self.assertGreater(len(txt), 500, f'正文应>500字符, 实际 {len(txt)}')
        self.assertIn('苏良贪生怕死', txt)
        self.assertNotIn('<p>', txt)

    def test_章内分页从2开始(self):
        self.assertEqual(
            self.ad.paginate('http://www.yueliang.org/read/108179/2769140.html', 1),
            '/read/108179/2769140_2.html')
        self.assertEqual(
            self.ad.paginate('http://www.yueliang.org/read/108179/2769140_2.html', 2),
            '/read/108179/2769140_3.html')

    def test_章节页推导目录(self):
        self.assertEqual(
            self.ad.catalog_from_chapter(
                'http://www.yueliang.org/read/108179/2769140_2.html',
                'http://www.yueliang.org'),
            'http://www.yueliang.org/txt108179.html')

    def test_书名(self):
        self.assertEqual(
            self.ad.get_title(self.soup, 'http://www.yueliang.org/txt108179.html',
                              'http://www.yueliang.org'),
            '禁神之下')


class Test质检事件首次通过发布(unittest.TestCase):
    """U19: _fetch_with_qc 首次质检通过 (attempt==0) 也必须发布 '质检' 事件。

    旧行为只在重试通过 / 失败时发布 → GUI 质检列靠结束后的站点历史回填
    (5s 防抖 + 中途退出无回填) → '有时显示有时不显示'。本测试锁定首过也发。
    """

    def test_首次通过即发布质检事件(self):
        import 爬虫 as spider_mod
        import 任务事件
        from unittest import mock

        class 记录器:
            def __init__(self):
                self.事件 = []

            def 处理任务事件(self, 类型, 数据):
                self.事件.append((类型, dict(数据)))

        蜘蛛 = mock.Mock()
        蜘蛛._质检记录 = []
        蜘蛛.get_chapter_content.return_value = '正文内容。' * 300

        r = 记录器()
        任务事件.订阅(r)
        try:
            with mock.patch('风控事件.add'), mock.patch('风控事件.flush'):
                结果 = spider_mod.NovelSpider._fetch_with_qc(
                    蜘蛛, {'title': '第1章', 'url': 'https://x.com/1.html'})
        finally:
            任务事件.退订(r)

        self.assertTrue(结果, '首过应返回正文')
        质检事件 = [d for t, d in r.事件 if t == '质检']
        self.assertEqual(len(质检事件), 1,
                         f'首过必须发布1条质检事件, 实际 {len(质检事件)}')
        self.assertEqual(质检事件[0]['通过'], True)
        self.assertGreater(质检事件[0]['得分'], 0)
        self.assertEqual(len(蜘蛛._质检记录), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)