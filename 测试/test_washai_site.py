# -*- coding: utf-8 -*-
"""washai.net (书海阁) 站点适配回归 (2026-09-26)。

背景 (用户实测 "禁神之下" 目录收集 0 章):
  - 目录 URL /book/indexList-{bid}.html (连字符形态) 推导不出 novel_path,
    通用兜底拒收全部 /book/{bid}/{cid}.html 章节链接 → 21 页分页遍历完仍 0 章;
  - 站点章节链接无 rel="chapter" 标记, cid 不随章号单调 (第1章 cid 尾 415,
    第100章尾 222), 按 cid 排序会打乱全书 → 排序键必须用标题 "第N章";
  - 正文 #readcontent 内纯文本 <p>, 服务端直出无内部分页 ("1/1")。

样本 (2026-09-26 在线快照): 目录第1/2/21/22页 + 作品页 + 第1/901/2019章。

运行 (项目根): python -m unittest discover -s 测试 -v
"""
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

from bs4 import BeautifulSoup           # noqa: E402

_样本 = _根 / '测试样本'

_目录URL = 'https://book.washai.net/book/indexList-1262260513468564878.html'
_章节URL = 'https://book.washai.net/book/1262260513468564878/2039351400476667415.html'
_根URL = 'https://book.washai.net'


def _载入适配器():
    spec = importlib.util.spec_from_file_location(
        'washai', str(_根 / '站点适配' / 'washai.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _样本soup(name):
    return BeautifulSoup((_样本 / name).read_bytes(), 'lxml')


def _分页fetch(映射):
    """构造 fetch 回调: 按 URL 后缀映射到样本页"""
    def fetch(url):
        for 后缀, name in 映射.items():
            if 后缀 in url:
                return _样本soup(name)
        return None
    return fetch


# 目录分页链: 第1页(样本) -next→ 第2页 -next→ 第3页(用第21页样本模拟尾页)
# -next→ 第22页(溢出空页, 0 新章 → 停止)
_分页链 = {'/2.html': 'washai_目录_第2页.html',
           '/3.html': 'washai_目录_第21页.html',
           '/22.html': 'washai_目录_第22页.html'}


class TestWashai目录解析(unittest.TestCase):
    """目录: 逐页跟随"下一页" + 0 新章即停 + 禁止按 cid 排序"""

    @classmethod
    def setUpClass(cls):
        cls.ad = _载入适配器()

    def test_多页收集与停止(self):
        ch = self.ad.parse_catalog(
            _样本soup('washai_目录.html'), _目录URL, _根URL,
            sort_chapters=False, fetch=_分页fetch(_分页链))
        self.assertIsInstance(ch, list)
        # 第1页100 + 第2页100 + 尾页20 = 220; 第22页空目录 0 新章触发停止
        self.assertEqual(len(ch), 220, f'应收集 220 章, 实际 {len(ch)}')
        self.assertTrue(ch[0]['title'].startswith('第1章'), ch[0]['title'])
        self.assertTrue(all(c['url'].startswith(_根URL + '/book/1262260513468564878/')
                            for c in ch), '章节 URL 必须落在本书 /book/{bid}/ 下')

    def test_保持目录顺序_禁止按cid排序(self):
        """cid 不随章号单调: 第1章 cid 尾 415 > 第100章 cid 尾 222"""
        ch = self.ad.parse_catalog(
            _样本soup('washai_目录.html'), _目录URL, _根URL,
            sort_chapters=False, fetch=None)
        self.assertEqual(len(ch), 100)
        self.assertTrue(ch[0]['title'].startswith('第1章 '), ch[0]['title'])
        self.assertTrue(ch[99]['title'].startswith('第100章 '), ch[99]['title'])
        # 证实 cid 乱序: 若按 cid 排序第1章会被排到后面
        self.assertGreater(
            int(ch[0]['url'].rsplit('/', 1)[1].split('.')[0]),
            int(ch[99]['url'].rsplit('/', 1)[1].split('.')[0]))

    def test_按标题章号排序(self):
        ch = self.ad.parse_catalog(
            _样本soup('washai_目录.html'), _目录URL, _根URL,
            sort_chapters=True, fetch=None)
        self.assertTrue(ch[0]['title'].startswith('第1章 '), ch[0]['title'])
        self.assertTrue(ch[-1]['title'].startswith('第100章 '), ch[-1]['title'])

    def test_标题去免费标记(self):
        ch = self.ad.parse_catalog(
            _样本soup('washai_目录.html'), _目录URL, _根URL,
            sort_chapters=False, fetch=None)
        self.assertFalse(any('[免费]' in c['title'] or '免费]' in c['title']
                             for c in ch), f'标题残留免费标记: {ch[0]["title"]}')

    def test_作品页跳转目录页(self):
        """任务 URL 给成作品页 /book/{bid}.html 时应跳转 indexList 目录页"""
        ch = self.ad.parse_catalog(
            _样本soup('washai_作品页.html'),
            'https://book.washai.net/book/1262260513468564878.html', _根URL,
            sort_chapters=False, fetch=_分页fetch({'indexList-1262260513468564878':
                                                   'washai_目录.html'}))
        self.assertEqual(len(ch), 100)

    def test_无法提取书id回退None(self):
        self.assertIsNone(self.ad.parse_catalog(
            _样本soup('washai_目录.html'), 'https://book.washai.net/other.html',
            _根URL, fetch=None))


class TestWashai正文与辅助(unittest.TestCase):
    """正文: #readcontent 纯 <p>; 分页: 无; 目录/书名推导"""

    @classmethod
    def setUpClass(cls):
        cls.ad = _载入适配器()

    def test_正文p段落提取(self):
        txt = self.ad.extract_content(
            _样本soup('washai_章节.html'), _章节URL, _根URL)
        self.assertIsNotNone(txt)
        self.assertGreater(len(txt), 2500, f'正文应>2500字符, 实际 {len(txt)}')
        self.assertIn('苏良贪生怕死', txt)
        # 页头信息与 VIP 提示不是 <p>, 不得混入
        self.assertNotIn('字数：', txt)
        self.assertNotIn('此章为VIP章节', txt)
        self.assertNotIn('屋币', txt)

    def test_中间章与末章提取(self):
        for name in ('washai_章节_中间章.html', 'washai_章节_末章.html'):
            txt = self.ad.extract_content(_样本soup(name),
                                          _章节URL, _根URL)
            self.assertIsNotNone(txt, name)
            self.assertGreater(len(txt), 800, f'{name} 正文过短: {len(txt)}')

    def test_章内无分页(self):
        """免费章单页直出 ("1/1"): paginate 必须返回 None 干净停止,
        避免主循环落到通用 _{N}.html 规则对每章多发一次无效请求"""
        self.assertIsNone(self.ad.paginate(_章节URL, 1))
        self.assertIsNone(self.ad.paginate(_章节URL, 2))

    def test_章节页推导目录(self):
        self.assertEqual(
            self.ad.catalog_from_chapter(_章节URL, _根URL),
            'https://book.washai.net/book/indexList-1262260513468564878.html')
        # 目录页/作品页/外站 不推导
        self.assertIsNone(self.ad.catalog_from_chapter(_目录URL, _根URL))
        self.assertIsNone(self.ad.catalog_from_chapter(
            'https://book.washai.net/book/1262260513468564878.html', _根URL))
        self.assertIsNone(self.ad.catalog_from_chapter('https://x.com/a/b.html'))

    def test_书名(self):
        self.assertEqual(
            self.ad.get_title(_样本soup('washai_目录.html'), _目录URL, _根URL),
            '禁神之下')
        self.assertEqual(
            self.ad.get_title(_样本soup('washai_章节.html'), _章节URL, _根URL),
            '禁神之下')

    def test_书id提取各形态(self):
        f = self.ad._书ID
        self.assertEqual(f(_目录URL), '1262260513468564878')
        self.assertEqual(f('https://book.washai.net/book/indexList/1262260513468564878/5.html'),
                         '1262260513468564878')
        self.assertEqual(f('https://book.washai.net/book/1262260513468564878.html'),
                         '1262260513468564878')
        self.assertIsNone(f('https://book.washai.net/book/bookclass.html'))


class TestGetChapterList集成(unittest.TestCase):
    """回归锁定: get_chapter_list 走适配器必须返回章节 (修复前返回 0 章)"""

    def test_通用入口不再返回0章(self):
        import 爬虫 as spider_mod

        def fake_inspect(url, *a, **kw):
            for 后缀, name in _分页链.items():
                if 后缀 in url:
                    return _样本soup(name)
            if 'indexList' in url:
                return _样本soup('washai_目录.html')
            return None

        spider = mock.Mock()
        spider.base_url = _根URL
        spider.inspect_page.side_effect = fake_inspect
        # Mock 上挂真实方法: get_chapter_list → _parse_catalog_by_site → 适配器
        spider._parse_catalog_by_site = (
            lambda url, sort_ch, soup:
            spider_mod.NovelSpider._parse_catalog_by_site(spider, url, sort_ch, soup))
        result = spider_mod.NovelSpider.get_chapter_list(
            spider, _目录URL, sort_chapters=False)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 220,
                         f'get_chapter_list 应返回 220 章 (修复前 0), 实际 {len(result)}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
