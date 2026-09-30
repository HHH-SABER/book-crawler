# -*- coding: utf-8 -*-
"""bookben5.org (书本网) 站点适配回归 (2026-10-01)。

背景 (用户给的 10 站测试):
  - 目录页 /txt/{bid}.html 内含 1,516 个 `/read/{bid}/{cid}.html` 章节链接,
    但**通用解析一条都识别不出** → 目录 0 章; 需专用适配器。
  - 1,516 条里混有导航链(开始阅读 / 下载TXT, 两者同一 URL)与顶部"最新章"链接;
  - 章号不可严格排序: 有 4 个重复号、2 个缺号, 且有 ~144 条番外型标题不含"第N章";
  - 正文在 div.content 内, 但同页 footer 另有 6 个 <p> → 必须限定容器。

样本 (2026-10-01 在线快照, 只发 2 个请求):
  测试样本/bookben5_catalog.html (目录页, 336 KB)
  测试样本/bookben5_chapter_1.html (章节页, 14.7 KB)

运行 (项目根): .runtime\\python314\\python.exe -m unittest discover -s 测试 -v
"""
import importlib.util
import re
import sys
import unittest
from pathlib import Path

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

from bs4 import BeautifulSoup           # noqa: E402

_样本 = _根 / '测试样本'
_目录URL = 'http://bookben5.org/txt/115657.html'
_章节URL = 'http://bookben5.org/read/115657/98170334.html'
_根URL = 'http://bookben5.org'

_章号RE = re.compile(r'第\s*(\d+)\s*章')


def _载入适配器():
    spec = importlib.util.spec_from_file_location(
        'bookben5', str(_根 / '站点适配' / 'bookben5.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _样本soup(name):
    return BeautifulSoup((_样本 / name).read_bytes(), 'lxml')


class TestBookben5适配器(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.m = _载入适配器()
        cls.目录soup = _样本soup('bookben5_catalog.html')
        cls.章soup = _样本soup('bookben5_chapter_1.html')
        cls.chaps = cls.m.parse_catalog(cls.目录soup, _目录URL, _根URL)

    # ---------- 目录 ----------
    def test_目录能解析且数量合理(self):
        self.assertIsNotNone(self.chaps, '目录解析返回 None')
        # 2026-10-01 快照实测 1504 章(与用户标注一致); 放宽下界防站点增章
        self.assertGreaterEqual(len(self.chaps), 1500,
                                f'章节数异常: {len(self.chaps)}')

    def test_目录无重复URL且标题非空(self):
        urls = [c['url'] for c in self.chaps]
        self.assertEqual(len(urls), len(set(urls)), '存在重复章节 URL')
        self.assertTrue(all(c['title'].strip() for c in self.chaps), '存在空标题')

    def test_导航链被过滤(self):
        titles = {c['title'] for c in self.chaps}
        for 名 in ('开始阅读', '下载TXT', '加入书架', '章节目录'):
            self.assertNotIn(名, titles, f'导航链未过滤: {名}')

    def test_章节URL形态正确(self):
        for c in self.chaps:
            self.assertRegex(c['url'], r'/read/115657/\d+\.html$')

    def test_编号章按章号升序且番外排在末尾(self):
        """排序键 = (章号, 文档序); 无章号的番外型标题全部排在末尾"""
        号s = [(i, _章号RE.search(c['title'])) for i, c in enumerate(self.chaps)]
        有号 = [(i, int(m.group(1))) for i, m in 号s if m]
        无号 = [i for i, m in 号s if not m]
        nums = [n for _, n in 有号]
        self.assertEqual(nums, sorted(nums), '编号章未按章号升序')
        if 无号:
            self.assertGreater(min(无号), max(i for i, _ in 有号),
                               '番外型(无章号)条目未排在编号章之后')

    def test_首章为第1章(self):
        self.assertIn('第1章', self.chaps[0]['title'],
                      f"首章标题异常: {self.chaps[0]['title']}")

    def test_站点原始编号瑕疵被如实保留(self):
        """站点自身有 2 个缺号(690/691)与重复号; 适配器不臆造, 如实反映"""
        nums = [int(m.group(1)) for c in self.chaps
                if (m := _章号RE.search(c['title']))]
        缺 = sorted(set(range(min(nums), max(nums) + 1)) - set(nums))
        self.assertIn(690, 缺, '站点缺号 690 未如实反映')

    def test_拿不到书ID时回退(self):
        self.assertIsNone(self.m.parse_catalog(self.目录soup, 'http://bookben5.org/', _根URL))

    def test_页面为空时不触网并回退(self):
        """离线约定: allow_self_fetch=False 时不得发起任何网络请求, 直接回退。

        背景: 主程序 inspect_page 因硬编码 Host 头 + 本站 www 跳转 → 30 次重定向
        耗尽后返回**空 soup**; 适配器为此加了"自主抓取"自愈。但自愈会触网,
        故提供 allow_self_fetch 开关, 单测关闭它以保证离线确定性。
        """
        self.assertIsNone(self.m.parse_catalog(None, _目录URL, _根URL,
                                               allow_self_fetch=False))
        self.assertIsNone(self.m.parse_catalog(BeautifulSoup('', 'lxml'), _目录URL,
                                               _根URL, allow_self_fetch=False))
        # 明确的空页面(有 <a> 但都不是本章章节) 也应回退
        无章节 = BeautifulSoup('<a href="http://bookben5.org/about.html">关于</a>', 'lxml')
        self.assertIsNone(self.m.parse_catalog(无章节, _目录URL, _根URL,
                                               allow_self_fetch=False))

    def test_不排序时保持文档顺序(self):
        原序 = self.m.parse_catalog(self.目录soup, _目录URL, _根URL, sort_chapters=False)
        self.assertIsNotNone(原序)
        self.assertEqual(len(原序), len(self.chaps), '排序前后条数不一致')

    # ---------- 正文 ----------
    def test_正文提取干净且不含页脚(self):
        正文 = self.m.extract_content(self.章soup, _章节URL, _根URL)
        self.assertIsNotNone(正文)
        self.assertGreater(len(正文), 800, f'正文过短: {len(正文)}')
        self.assertGreaterEqual(正文.count('\n\n') + 1, 30, '段落数异常偏少')
        # footer 里的站内链接不得混入 (这是必须限定 div.content 的原因)
        for 污染 in ('书本网', 'bookben5', '上一章', '下一章', 'footer'):
            self.assertNotIn(污染, 正文, f'正文混入页脚内容: {污染}')

    def test_正文无HTML残留(self):
        正文 = self.m.extract_content(self.章soup, _章节URL, _根URL)
        self.assertNotIn('<', 正文)
        self.assertNotIn('&nbsp;', 正文)

    def test_无容器时返回None走通用(self):
        self.assertIsNone(self.m.extract_content(BeautifulSoup('<p>裸</p>', 'lxml'),
                                                _章节URL, _根URL))
        self.assertIsNone(self.m.extract_content(None, _章节URL, _根URL))

    # ---------- 其它接口 ----------
    def test_书名(self):
        self.assertEqual(self.m.get_title(self.目录soup, _目录URL, _根URL), '十日终焉')

    def test_章内分页显式无(self):
        """单页直出: 必须返回 None 以免对每章多发无效请求"""
        self.assertIsNone(self.m.paginate(_章节URL, 2))

    def test_章节页反推目录页(self):
        self.assertEqual(
            self.m.catalog_from_chapter('http://www.bookben5.org/read/115657/63927321.html',
                                        _根URL),
            'http://bookben5.org/txt/115657.html')
        self.assertIsNone(self.m.catalog_from_chapter('http://bookben5.org/txt/1.html', _根URL))

    def test_SITE声明与加载所需字段(self):
        S = self.m.SITE
        self.assertEqual(S['domain'], 'bookben5.org')      # 子串匹配, 兼容 www
        self.assertIn('bookben5.org', 'http://www.bookben5.org/txt/115657.html')
        self.assertRegex('/read/115657/63927321.html', S['chapter_url_regex'])
        self.assertTrue(S['content_selectors'])
        for 名 in ('parse_catalog', 'extract_content', 'paginate', 'get_title'):
            self.assertTrue(callable(getattr(self.m, 名, None)), f'缺接口 {名}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
