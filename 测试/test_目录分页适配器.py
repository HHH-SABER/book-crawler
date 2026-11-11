# -*- coding: utf-8 -*-
"""目录分页适配器的「同书号异前缀」契约护栏 (2026-11-11)。

背景: 一类移动版站点目录页是 `/book/<书号>/`，章节链接却是
`/html/<书号>/<章节号>/`（无扩展名），且目录按 `asc-N` 分页、章内按
`<章节号>_N` 分页。通用解析的 `novel_path in href` 前缀过滤会把**全部
章节拒掉** → 0 章 → 死书[目录无章节]。

本测试用**完全脱敏的占位域名与自造 HTML** 钉住适配器的四条关键契约：
  ① novel_paths 必须指向章节所在的 /html/ 前缀（改回 /book/ 即回归）；
  ② 目录能链式翻页、URL 去重、排除 asc-N 分页链接、按章号排序；
  ③ 正文容器抽取 + 章内「下—页」跟随，末页明确停止（不猜到 404）；
  ④ 章节页 URL 能反推目录页。

适配器本体在 gitignored 的本地适配目录（站点脱钩，公开仓库不含站点
专属逻辑）；公开形态下文件不存在 → 整组 skip，不影响 CI 门禁。
"""
import importlib.util
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

from bs4 import BeautifulSoup  # noqa: E402

_适配器文件 = _根 / '站点适配_本地' / 'kudushu.py'
_BASE = 'https://m.example.com'
_书号 = 123456
_目录 = f'{_BASE}/book/{_书号}/'


def _加载适配器():
    if not _适配器文件.is_file():
        return None
    spec = importlib.util.spec_from_file_location('_本地目录分页适配器', _适配器文件)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _第1页():
    """头部重复渲染「最新章」+ 功能按钮复用首章 URL + 正序目录 + 下一页。"""
    return f'''
    <html><body>
      <a href="/html/{_书号}/9002/">第40章 尾章</a>
      <a href="/html/{_书号}/9001/">第39章 倒数</a>
      <a href="/html/{_书号}/1000/">从头阅读</a>
      <a href="Javascript:void(0);">加入书架</a>
      <a href="/html/{_书号}/1000/">第1章 开局</a>
      <a href="/html/{_书号}/1001/">第2章 承接</a>
      <a href="/html/{_书号}/asc-2/">下一页</a>
      <a href="/">首页</a>
    </body></html>'''


def _第2页():
    return f'''
    <html><body>
      <a href="/html/{_书号}/9002/">第40章 尾章</a>
      <a href="/html/{_书号}/1002/">第3章 转折</a>
      <a href="/html/{_书号}/asc-3/">下一页</a>
      <a href="/html/{_书号}/asc-1/">上一页</a>
    </body></html>'''


def _带页表的首页(页数=3):
    """站点把全部分页 URL 直接列在分页下拉框里。"""
    选项 = [f'<option value="/book/{_书号}/" selected>第1 - 2章</option>']
    for i in range(2, 页数 + 1):
        选项.append(f'<option value="/html/{_书号}/asc-{i}/">第{i}页</option>')
    return f'''
    <html><body>
      <a href="/html/{_书号}/1000/">第1章 开局</a>
      <a href="/html/{_书号}/1001/">第2章 承接</a>
      <div class="listpage"><select name="pageselect">{''.join(选项)}</select></div>
    </body></html>'''


def _页(n, 章号=None):
    章号 = 章号 if 章号 is not None else (n + 1)
    return f'<html><body><a href="/html/{_书号}/{1000 + 章号}/">第{章号}章 正文</a></body></html>'


def _章节页(有无下一页=True):
    下一 = (f'<a href="/html/{_书号}/1000_2/">下—页</a>' if 有无下一页 else '')
    return f'''
    <html><body>
      <div id="novelcontent" class="novelcontent">
        <p>第1章 页眉标题 (第1/3页)<br/><br/>第一段正文内容。</p>
        <p>第二段正文内容。</p>
        <div id="content_tip"><b>本站网址占位</b></div>
      </div>
      <ul class="novelbutton"><li>{下一}</li></ul>
    </body></html>'''


@unittest.skipUnless(_适配器文件.is_file(), '本地站点适配器未部署 (公开仓库形态)')
class Test目录分页适配器(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = _加载适配器()
        if cls.m is None:
            raise unittest.SkipTest('适配器加载失败')
        cls.m.time = Mock()   # 失败重试的退避不真等，护栏保持毫秒级

    def test_路径前缀必须指向章节所在的html目录(self):
        """核心修复: 返回 /book/ 前缀就会把全部章节拒掉，退回 0 章死书。"""
        主, 备 = self.m.novel_paths(_目录)
        self.assertEqual(主, f'/html/{_书号}/')
        self.assertEqual(备, f'/book/{_书号}/')

    def test_章节正则排除asc分页链接(self):
        正则 = self.m.SITE['chapter_url_regex']
        self.assertTrue(re.search(正则, f'/html/{_书号}/1000/'))
        self.assertFalse(re.search(正则, f'/html/{_书号}/asc-2/'))
        self.assertFalse(re.search(正则, '/bookcase.php'))

    def test_链式翻页去重并按章号排序(self):
        页1 = BeautifulSoup(_第1页(), 'lxml')
        页2 = BeautifulSoup(_第2页(), 'lxml')
        抓取 = []

        def fetch(url, **kw):
            抓取.append(url)
            return 页2 if 'asc-2' in url else BeautifulSoup('', 'lxml')

        章 = self.m.parse_catalog(页1, _目录, _BASE, fetch=fetch,
                                clean_title=lambda t: t, sort_chapters=True)
        # 空页会重试一次，故不钉死总次数；只钉「翻到 asc-3 且不越界」
        self.assertEqual(抓取[0], f'{_BASE}/html/{_书号}/asc-2/')
        self.assertIn(f'{_BASE}/html/{_书号}/asc-3/', 抓取)
        self.assertFalse(any('asc-4' in u for u in 抓取))
        self.assertEqual(len(章), 5, '两页共 1/2/3/39/40 五个唯一章节')
        self.assertEqual([c['title'] for c in 章],
                         ['第1章 开局', '第2章 承接', '第3章 转折',
                          '第39章 倒数', '第40章 尾章'])
        self.assertTrue(all(c['url'].startswith(_BASE) for c in 章))
        self.assertFalse(any('asc-' in c['url'] for c in 章),
                         '目录分页链接不能被当成章节')

    def test_页表一次取全且单页失败不中断后续(self):
        """回归: 链式追下一页时第 2 页超时会丢掉后面全部页 (25/402 章)。

        下拉框页表把页 URL 一次给全，中间一页失败只损失该页。
        """
        首页 = BeautifulSoup(_带页表的首页(), 'lxml')
        抓取 = []

        def fetch(url, **kw):
            抓取.append(url)
            if 'asc-2' in url:
                return None                      # 模拟超时 / 空页面
            if 'asc-3' in url:
                return BeautifulSoup(_页(3, 章号=5), 'lxml')
            return BeautifulSoup('', 'lxml')

        章 = self.m.parse_catalog(首页, _目录, _BASE, fetch=fetch,
                                clean_title=lambda t: t, sort_chapters=True)
        self.assertIn(f'{_BASE}/html/{_书号}/asc-2/', 抓取)
        self.assertIn(f'{_BASE}/html/{_书号}/asc-3/', 抓取,
                      '前一页失败不得中断后续页')
        self.assertEqual([c['title'] for c in 章],
                         ['第1章 开局', '第2章 承接', '第5章 正文'])

    def test_页表连续失败有上限不空转(self):
        首页 = BeautifulSoup(_带页表的首页(页数=8), 'lxml')
        抓取 = []

        def fetch(url, **kw):
            抓取.append(url)
            return None

        self.m.parse_catalog(首页, _目录, _BASE, fetch=fetch,
                            clean_title=lambda t: t, sort_chapters=True)
        self.assertLess(len(抓取), 2 * 8,
                        '连续失败必须早停，不能把整张页表重试到天亮')

    def test_功能按钮复用首章URL时保留规范标题(self):
        """「从头阅读」排在首章前面，不能把首章标题顶成功能按钮文字。"""
        页1 = BeautifulSoup(_第1页(), 'lxml')
        章 = self.m.parse_catalog(页1, _目录, _BASE,
                                fetch=lambda u, **kw: BeautifulSoup('', 'lxml'),
                                clean_title=lambda t: t, sort_chapters=True)
        self.assertEqual(章[0]['title'], '第1章 开局')

    def test_翻页成环时不会无限循环(self):
        页1 = BeautifulSoup(_第1页(), 'lxml')
        自指 = Mock(side_effect=lambda u, **kw: BeautifulSoup(_第1页(), 'lxml'))
        章 = self.m.parse_catalog(页1, _目录, _BASE, fetch=自指,
                                clean_title=lambda t: t, sort_chapters=True)
        self.assertLess(自指.call_count, 40, '必须有硬上限 / 已访问页去重')
        self.assertTrue(章)

    def test_正文抽取剔除站点提示块(self):
        soup = BeautifulSoup(_章节页(), 'lxml')
        文本 = self.m.extract_content(soup, f'{_BASE}/html/{_书号}/1000/', _BASE)
        self.assertIn('第一段正文内容', 文本)
        self.assertNotIn('本站网址占位', 文本)
        self.assertNotIn('下—页', 文本)
        self.assertNotIn('页眉标题', 文本, '章内页眉不能混进正文')
        self.assertNotIn('第1/3页', 文本)

    def test_页眉与首句粘连时只删页眉保留正文(self):
        """实抓取证: 页眉和第一句挤在同一行，不能整行删掉丢正文。"""
        html = f'''<html><body><div id="novelcontent">
          <p>第1章 页眉标题 (第2/3页)这句是正文首句。</p>
          </div></body></html>'''
        文本 = self.m.extract_content(
            BeautifulSoup(html, 'lxml'), f'{_BASE}/html/{_书号}/1000_2/', _BASE)
        self.assertIn('这句是正文首句', 文本)
        self.assertNotIn('页眉标题', 文本)
        self.assertNotIn('第2/3页', 文本)

    def test_章内分页跟随页面真实下一页(self):
        url1 = f'{_BASE}/html/{_书号}/1000/'
        self.m.extract_content(BeautifulSoup(_章节页(), 'lxml'), url1, _BASE)
        self.assertEqual(self.m.paginate(url1, 1, base_url=_BASE),
                         f'{_BASE}/html/{_书号}/1000_2/')

    def test_末页明确停止不猜到404(self):
        url2 = f'{_BASE}/html/{_书号}/1000_2/'
        self.m.extract_content(BeautifulSoup(_章节页(有无下一页=False), 'lxml'),
                               url2, _BASE)
        self.assertIsNone(self.m.paginate(url2, 2, base_url=_BASE))

    def test_章节页可反推目录页(self):
        self.assertEqual(
            self.m.catalog_from_chapter(f'{_BASE}/html/{_书号}/1000_2/', _BASE),
            _目录)
        self.assertIsNone(self.m.catalog_from_chapter(_目录, _BASE))

    def test_分页上限有界(self):
        上限 = self.m.站点策略(_目录, '分页上限')
        self.assertIsInstance(上限, int)
        self.assertLessEqual(上限, 20)


if __name__ == '__main__':
    unittest.main()
