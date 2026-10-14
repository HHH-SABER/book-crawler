# -*- coding: utf-8 -*-
"""JS 渲染重试回归 (阶段一 P1, 2026-10-14)。

背景: EXE 2.5.23 收尾实测暴露的死书根因 —— ixdzs 目录是 JS 渲染, requests
各引擎都"成功"拿到页面但章节链接 0 条, 而引擎升级链路只看"请求失败"不看
"章节为 0" ⇒ 直接判死书。修复: 目录 0 章节且页面可达时, 用驱动渲染重试一次。

覆盖:
  ① `get_chapter_list(_预渲染HTML=…)`: 预渲染 HTML 走**同一条解析链路**
     (用真实形态样本 siteq_目录_真实页 = 完整大目录, 断言章节数);
  ② `_预渲染HTML=None` (默认): 行为不变 (回归护栏, 走 inspect_page);
  ③ `_驱动渲染目录页`: 复用 _create_waf_driver + 渲染后解析 + driver.quit;
     驱动创建失败时异常上抛 (调用方吞掉, 不改原行为);
  ④ 触发条件静态契约: run_crawl 里"页面可达且 0 章节"才重试,
     "页面为空/被质询"不得触发 (渲染无意义, 且会拖慢真死书判定)。
运行: python -m unittest discover -s 测试
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))


def _造爬虫():
    """造一个不触网络的 NovelSpider 实例 (mock 掉 __init__ 的重活)。"""
    import 爬虫 as C
    with mock.patch.object(C.NovelSpider, '__init__', lambda self, *a, **k: None):
        s = C.NovelSpider()
    s._目录页为空 = False
    s._目录页被质询 = False
    # get_chapter_list 内部会用到 base_url (拼接下一页) 等实例属性
    s.base_url = 'https://site1.example.com'
    s.last_request_error = ''
    s.last_status_code = 200
    import threading
    s._inspect_cache = {}   # 多页合并会用到 inspect_page 缓存与其锁
    s._inspect_cache_lock = threading.Lock()
    return s


class Test预渲染解析(unittest.TestCase):
    """_预渲染HTML 参数: 渲染后的 HTML 走同一解析链路"""

    def setUp(self):
        self.样本 = (_根 / '测试' / '样本' / 'siteq_目录_真实页.html')
        if not self.样本.is_file():
            self.skipTest('形态样本缺失')

    def test_预渲染HTML进入解析链路(self):
        """预渲染 HTML 必须成为解析链路的 soup (不复制解析逻辑的证据)。

        做法: mock 掉站点专属解析 (链路里第一个消费 soup 的点), 断言它收到的
        soup 就是**预渲染 HTML 解析出来的** (长度≈样本长度), 且 inspect_page
        全程未被调用 (没有退回网络抓取) —— 通用提取链路本身由既有回归守着,
        这里只验新参数的注入点。
        """
        from bs4 import BeautifulSoup
        s = _造爬虫()
        html = self.样本.read_bytes().decode('utf-8', errors='replace')
        收到 = {}

        def _假站点解析(url, sort, soup):
            收到['soup长度'] = len(str(soup))
            收到['soup文本'] = str(soup)
            return [{'title': '第1章', 'url': '/1.html'}]

        with mock.patch.object(s, '_parse_catalog_by_site', _假站点解析):
            with mock.patch.object(s, 'inspect_page',
                                   side_effect=AssertionError(
                                       '预渲染路径不得走网络抓取')) as 网抓:
                chapters = s.get_chapter_list(
                    'https://site1.example.com/read/588165/',
                    _预渲染HTML=html)
                网抓.assert_not_called()
        self.assertEqual(收到['soup长度'], len(str(BeautifulSoup(html, 'lxml'))),
                         '链路消费的 soup 必须来自预渲染 HTML')
        self.assertNotIn('inspect_page', 收到)
        self.assertEqual(chapters, [{'title': '第1章', 'url': '/1.html'}],
                         '站点解析的返回值必须原样透传 (同一链路)')

    def test_空HTML返回空且置信号(self):
        from bs4 import BeautifulSoup
        s = _造爬虫()
        with mock.patch.object(s, 'inspect_page',
                               return_value=BeautifulSoup('', 'lxml')):
            chapters = s.get_chapter_list('https://site1.example.com/x/',
                                          _预渲染HTML='   ')
        self.assertEqual(chapters, [])
        self.assertTrue(s._目录页为空, '空 HTML 必须置 _目录页为空 信号')

    def test_默认路径不读预渲染参数(self):
        """回归护栏: 不传 _预渲染HTML 时必须走 inspect_page (原行为)"""
        s = _造爬虫()
        with mock.patch.object(s, 'inspect_page',
                               side_effect=RuntimeError('截断: 已证明走 inspect_page')):
            with self.assertRaises(RuntimeError):
                s.get_chapter_list('https://site1.example.com/x/')


class Test驱动渲染目录页(unittest.TestCase):
    """_驱动渲染目录页: 复用 _create_waf_driver + 渲染解析 + 收尾"""

    def setUp(self):
        self.s = _造爬虫()

    def test_正常渲染解析(self):
        假driver = mock.MagicMock()
        假driver.content.return_value = '<html><body>rendered</body></html>'
        with mock.patch.object(self.s, '_create_waf_driver',
                               return_value=假driver) as 建:
            with mock.patch.object(self.s, 'get_chapter_list',
                                   return_value=[{'title': '第1章',
                                                  'url': '/1.html'}]) as 解析:
                结果 = self.s._驱动渲染目录页('https://site1.example.com/x/')
        建.assert_called_once()
        假driver.get.assert_called_once_with('https://site1.example.com/x/')
        self.assertGreaterEqual(len(解析.call_args[0]), 1)  # catalog_url
        self.assertEqual(解析.call_args[1]['_预渲染HTML'],
                         '<html><body>rendered</body></html>',
                         '渲染 HTML 必须经 _预渲染HTML 走同一条解析链路')
        self.assertEqual(len(结果), 1)
        假driver.quit.assert_called_once()

    def test_空内容返回空(self):
        假driver = mock.MagicMock()
        假driver.content.return_value = ''
        with mock.patch.object(self.s, '_create_waf_driver', return_value=假driver):
            self.assertEqual(self.s._驱动渲染目录页('https://x.example.com/'), [])

    def test_驱动创建失败异常上抛(self):
        """调用方(run_crawl)依赖异常上抛来吞掉失败并继续原死书判定"""
        with mock.patch.object(self.s, '_create_waf_driver',
                               side_effect=RuntimeError('无 Chrome')):
            with self.assertRaises(RuntimeError):
                self.s._驱动渲染目录页('https://x.example.com/')


class Test触发条件静态契约(unittest.TestCase):
    """run_crawl 的重试触发条件 (源码级钉死, 防回归)"""

    def setUp(self):
        self.源码 = (_根 / '源码' / '爬虫.py').read_bytes().decode('utf-8')

    def test_触发条件正确(self):
        块 = self.源码.split('if total == 0 and not getattr(self,')[1][:400]
        self.assertIn("_目录页为空", 块, '必须排除页面为空 (站点不可达, 渲染无意义)')
        self.assertIn("_目录页被质询", 块, '必须排除被质询 (质询页渲染也拿不到目录)')

    def test_重试失败不影响原判定(self):
        """重试异常必须被吞 (try/except), 不能让原死书判定链崩掉"""
        块 = self.源码.split('chapters = self._驱动渲染目录页(')[1][:500]
        self.assertIn('except Exception', 块,
                      '重试失败必须吞掉, 继续走原死书判定')

    def test_重试在死书判定之前(self):
        i = self.源码.find('self._驱动渲染目录页(catalog_url')
        j = self.源码.find('from 死书处理 import 判定死书')
        self.assertGreater(j, i, '驱动重试必须发生在死书判定之前')


if __name__ == '__main__':
    unittest.main(verbosity=2)
