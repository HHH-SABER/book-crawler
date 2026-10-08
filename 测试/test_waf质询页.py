# -*- coding: utf-8 -*-
"""WAF 质询页不得被当成目录页 (2026-10-08 新增, 全离线)。

倒逼事故: 命中 WAF 图片验证码质询页时, **页面自身的链接被当章节收下**
(实抓日志: `找到 2 个链接` → `链接 1: …/1.html?from=…`), 标题退化成 URL 写进正文
= 历史上的 `## <URL>` 头部残留 → 让续传计数偏 1 → **跳过第 1 章/部分**。

本文件锁两条:
  A. `waf_captcha.looks_like_waf_captcha` —— 状态码无关的质询页特征判定
     (解析层手上只有 HTML, 没有状态码);
  B. `NovelSpider.get_chapter_list` 命中质询页时 **返回空且置标志**,
     **并且普通目录页必须照常解析**(防空转通过)。

运行: python -m unittest discover -s 测试
"""
import sys
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))
sys.path.insert(0, str(_根 / '测试'))

import _沙箱              # noqa: E402,F401  状态根沙箱
import 爬虫 as C           # noqa: E402
import waf_captcha as W    # noqa: E402

# 测试用 URL 形状必须让 `_resolve_novel_paths` 解析出路径 —— 路径为空时解析器
# **刻意禁用路径过滤**(防全页链接被当章节), 于是任何样本都 0 章, 会写出假绿的用例。
# `/book/<数字>/` 是能解析出的形状之一 (实测 novel_path='/book/12345/')。
_URL = 'https://example.com/book/12345/1.html'
_前缀 = '/book/12345/'

# 实抓取证到的质询页形态 (1007 字节, 只有自身链接 + 站点首页)。
# ⚠️ 其中的链接**刻意放在 _前缀 下**: 若无本防线, 通用链接选择会把它们当章节收下 ——
# 这条用例才算真正的对照 (否则改样本让它"本来就解析不出"就成了假绿)。
_质询页 = ('<html><head><meta charset="utf-8"></head><body>'
         '<style>input{}</style>'
         '<form id="_waform">__wafcaptcha 请输入验证码</form>'
         f'<a href="{_前缀}2.html">第 2 章</a>'
         f'<a href="{_前缀}3.html">第 3 章</a>'
         '<a href="https://example.com">example.com</a>'
         '</body></html>')


class Test质询页特征判定(unittest.TestCase):

    def test_经典形态(self):
        self.assertTrue(W.looks_like_waf_captcha(
            '<html><body>__wafcaptcha 请输入验证码</body></html>'))

    def test_内容型形态(self):
        self.assertTrue(W.looks_like_waf_captcha(
            '<html><body>访问验证 <img src="/check_code.html"></body></html>'))

    def test_实抓取证样本(self):
        self.assertTrue(W.looks_like_waf_captcha(_质询页))

    def test_空与正常页不误判(self):
        for html in ('', None,
                     '<html><body><a href="/book/12345/1.html">第 1 部分</a></body></html>',
                     '验证码', '访问验证', '__wafcaptcha', 'check_code'):
            with self.subTest(html=str(html)[:40]):
                self.assertFalse(W.looks_like_waf_captcha(html))

    def test_与请求层判定分工不冲突(self):
        """解析层是并集(宽)、请求层要状态码(严) —— 后者不得被前者替代。

        内容型样本配上 401 时, 请求层判定应为 False (原条件要求 200+短页),
        而解析层仍要认出它 —— 这正是"两层各司其职"的意思。
        """
        内容型 = '访问验证 check_code'
        self.assertTrue(W.looks_like_waf_captcha(内容型))
        self.assertFalse(W.is_waf_captcha_page(401, 内容型))


class Test质询页不产出章节(unittest.TestCase):

    def setUp(self):
        self.蜘蛛 = C.NovelSpider('https://example.com')

    def tearDown(self):
        self.蜘蛛.close()

    def _打桩页面(self, html):
        self.蜘蛛.inspect_page = lambda url, polite_delay=True: BeautifulSoup(
            html, 'html.parser')

    def test_质询页返回空且置标志(self):
        self._打桩页面(_质询页)
        章 = self.蜘蛛.get_chapter_list(_URL)
        self.assertEqual(章, [], '质询页里的链接被当成章节收下了 (正是本次事故)')
        self.assertTrue(getattr(self.蜘蛛, '_目录页被质询', False),
                        '未置 _目录页被质询 标志 → 上层无法给出"过验证码"的指引')

    def test_同样的链接在正常目录页会被解析(self):
        """**对照(阳性)**: 同一批链接, 只要页面不是质询页, 就必须被解析成章节。

        与上一条合起来才说明"是质询页判定挡住的", 而不是样本本来就解析不出。
        """
        self._打桩页面('<html><body>' + ''.join(
            f'<a href="{_前缀}{i}.html">第 {i} 章</a>' for i in range(1, 8))
            + '</body></html>')
        章 = self.蜘蛛.get_chapter_list(_URL)
        self.assertGreaterEqual(len(章), 3, f'普通目录页没解析出章节: {章}')
        self.assertFalse(getattr(self.蜘蛛, '_目录页被质询', True))

    def test_空页不误判成质询(self):
        """空页应走"页面为空"信号(死书判定用), 不该被当成质询页。"""
        self._打桩页面('')
        章 = self.蜘蛛.get_chapter_list(_URL)
        self.assertEqual(章, [])
        self.assertTrue(getattr(self.蜘蛛, '_目录页为空', False))
        self.assertFalse(getattr(self.蜘蛛, '_目录页被质询', True))
        self.assertFalse(getattr(self.蜘蛛, '_目录页被质询', True))


if __name__ == '__main__':
    unittest.main(verbosity=2)
