# -*- coding: utf-8 -*-
"""验证码判定两道门的串联行为回归 (F4 真机验收 2026-10-13)。

**为什么有这份测试**: F4 原计划"起真站抓真验证码页", 但 (a) 本地无弹验证码的站,
(b) 本机 mock 站被 SSRF 红线拦住 (内网/回环禁止, 且不允许为测试放宽)。
于是改为锁住**两道门串联的真实行为** —— 这正是真机要验的东西:

    爬虫._像验证码页 (第一道门, 严格)  →  CaptchaManager.is_captcha_page
    (第二道门, 加固后强弱分级)          →  才进验证码流程

F4 验收中实测发现的脆弱点: `is_captcha_page` 原先对 `captcha`/`geetest`
**子串任意命中** ⇒ 正常小说页仅引 `captcha.js` 也会被判验证码页。当前调用链上
第一道门已拦住 (不构成现网缺陷), 但已做防御性收窄: 弱特征需 UI 佐证。

已做变异测试 (K33): 把强弱分级还原成"任意命中" → 用例变红。
运行: .runtime/python314/python.exe -m unittest discover -s 测试
"""
import re
import sys
import unittest
from pathlib import Path

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

import 爬虫 as C            # noqa: E402
import captcha_module as CM  # noqa: E402

# CaptchaManager.is_captcha_page 是实例方法(内部委托基类), 这里直接取基类的
# staticmethod 版本, 免造管理器实例
_判定 = CM.CaptchaHandler.__dict__['is_captcha_page']

真WAF页 = '<html><form action="/vfy"><input name="__wafcaptcha"></form></html>'
真访问频繁页 = '<html><body>访问频率太高，请稍后再试</body></html>'
正常页_引captcha脚本 = ('<html><head><script src="/static/js/captcha.js"></script>'
                        '</head><body><div id="content">第一章 正文</div></body></html>')
正常页_引geetest脚本 = '<html><script src="/js/geetest.js"></script><body>正文</body></html>'
正常页_评论框图 = '<html><body>评论需验证码 <img src="/captcha.jpg"> 正文</body></html>'
正常页_正文 = '<html><body><div id="content">第一章 内容</div></body></html>'
真验证码页_有输入框 = ('<html><form action="/verify"><input type="text" name="captcha_code">'
                       '<img src="/api/captcha.jpg"><input type="submit"></form></html>')


class Test两道门串联(unittest.TestCase):
    """真站要验的正是这条链: 第一道门拦不拦 + 第二道门判不判"""

    def _过两道门(self, src) -> bool:
        """模拟真实调用链: 第一道门放行 且 第二道门命中 → 会进验证码流程"""
        return bool(C._像验证码页(src)) and bool(_判定(src))

    def test_真WAF页进流程(self):
        self.assertTrue(self._过两道门(真WAF页), '真 WAF 验证码页必须进流程')

    def test_访问频繁页进流程(self):
        self.assertTrue(self._过两道门(真访问频繁页), 'WAF 频控页必须进流程')

    def test_有输入框的真验证码页被第二道门命中(self):
        """弱特征 + UI 佐证 ⇒ 第二道门仍须命中 (收窄不能漏判真页)"""
        self.assertTrue(_判定(真验证码页_有输入框),
                        '收窄后真验证码页仍必须命中')

    def test_正常页引脚本不判验证码(self):
        """★ 核心防误杀: 仅引 captcha.js/geetest.js 的正常页不得判验证码"""
        for 名, src in (('引captcha.js', 正常页_引captcha脚本),
                        ('引geetest.js', 正常页_引geetest脚本),
                        ('普通正文页', 正常页_正文)):
            with self.subTest(样本=名):
                self.assertFalse(_判定(src),
                                 f'{名} 被误判为验证码页 ⇒ 会误弹人工浏览器')

    def test_已知边界_评论框验证码图仍命中但被第一道门兜住(self):
        """**刻意决策**: 评论区验证码(有 img/input)语义上确实"含验证码 UI", 第二道门
        命中它是有意为之 —— 不做过度收窄, 因为要区分"整页被拦截"与"页面里带评论区
        验证码"需要判断正文是否存在 (各站容器差异大、易漏判真页)。
        真正的把关在**第一道门**: 实测 `_像验证码页` 对该页放行 ⇒ 不会进验证码流程。
        本用例把该决策写死, 防止后人误以为这是 bug 又去收窄。"""
        self.assertTrue(_判定(正常页_评论框图),
                        '第二道门对"页面内含验证码 UI"仍判中 (有意决策)')
        self.assertFalse(C._像验证码页(正常页_评论框图),
                         '第一道门必须放行它 —— 这才是实际把关点')

    def test_正常页两道门都不进流程(self):
        """端到端: 正常页既过不了第一道门, 也不该被第二道门判中"""
        for 名, src in (('引captcha.js', 正常页_引captcha脚本),
                        ('引geetest.js', 正常页_引geetest脚本),
                        ('普通正文页', 正常页_正文)):
            with self.subTest(样本=名):
                self.assertFalse(self._过两道门(src))

    def test_第一道门本身不误判(self):
        """第一道门(严格口径)对上述正常页本就应放行 —— 加固第二道门不改变它"""
        for src in (正常页_引captcha脚本, 正常页_引geetest脚本, 正常页_评论框图):
            self.assertFalse(C._像验证码页(src))

    def test_空与None不炸(self):
        self.assertFalse(_判定(None))
        self.assertFalse(_判定(''))


class Test分级结构(unittest.TestCase):
    """强弱特征分级是本轮加固的形态, 锁住它不被无声改回"""

    def test_实现含强弱两级(self):
        源码 = (_根 / '源码' / 'captcha_module.py').read_text(encoding='utf-8')
        self.assertIn('强特征', 源码)
        self.assertIn('弱特征', 源码)

    def test_强特征直接判定无需佐证(self):
        """WAF 专用标记即使没有 input 也必须判中 (否则真 WAF 页漏判)"""
        无输入框 = '<html><script>var x="__wafcaptcha";</script></html>'
        self.assertTrue(_判定(无输入框))


if __name__ == '__main__':
    unittest.main(verbosity=2)