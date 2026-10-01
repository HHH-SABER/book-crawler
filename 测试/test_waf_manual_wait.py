# -*- coding: utf-8 -*-
"""WAF 人工兜底"拦截页误判已通过"回归 (2026-10-02 弹窗秒关事故)。

## 为什么需要 (bug 根因)

solve_waf_captcha_manual 的轮询通过条件旧实现误写为:

    if '__wafcaptcha' not in src or '验证码' not in src:  → 判"已通过"

实测某"访问验证页"类站点命中 is_waf_captcha_page 的**第二类**形态 (HTTP 200 + '访问验证' +
'check_code', 正文并无 __wafcaptcha 字样)。对②型页, 首 poll '__wafcaptcha
not in src' 即为真 → 浏览器刚打开 2~3 秒就被误判"用户已通过验证" → 关窗 +
回灌无效 cookie → 下一请求仍被拦 → 再开一扇窗…… 实测日志 03:31:36→
03:31:57 循环 7+ 次, 用户完全来不及看验证码 (弹窗一闪即关)。

## 锁定的契约

1. _仍为拦截页: 两类拦截形态 (__wafcaptcha+验证码 / 访问验证+check_code)
   都判"仍在拦截"; 正常正文判 False; **空源码判 True** (刚 get 未加载完,
   绝不误判通过) — 与 is_waf_captcha_page 内容判定同源。
2. _人工等待通过: 拦截页变正常 → 'passed'; 始终拦截 → 'timeout';
   取源码异常 → 'error'。
3. ②型拦截页首 poll 绝不再被判通过 (旧 bug 反例锁定)。

离线: stub driver + 极短超时/间隔, 不联网, 不起真实浏览器。
"""
import sys
import time
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / '源码'))

import waf_captcha as wc  # noqa: E402

经典页 = '<html><body>__wafcaptcha 请输入验证码提交</body></html>'       # ①型(403系)
访问页 = ('<html><head><title>访问验证</title></head><body>'
          '<img src="/home/chapter/verify.html">'
          '<form action="/check_code.html"><input name="code"></form>'
          '</body></html>')                                          # ②型(200系)
正常页 = '<html><body><h1>第一章 雨夜</h1><p>正文正文正文</p></body></html>'


class _桩driver:
    """page_source 依次吐出序列里的值 (模拟等待期间页面变化)"""
    def __init__(self, 序列):
        self.序列 = list(序列)
        self.取用 = 0

    @property
    def page_source(self):
        v = self.序列[min(self.取用, len(self.序列) - 1)]
        self.取用 += 1
        if v == '_raise':
            raise RuntimeError('浏览器连接断开')
        return v


class Test仍为拦截页判定(unittest.TestCase):
    def test_两类拦截页都判在拦(self):
        self.assertTrue(wc._仍为拦截页(经典页))
        self.assertTrue(wc._仍为拦截页(访问页))

    def test_正常页判已通过(self):
        self.assertFalse(wc._仍为拦截页(正常页))

    def test_空源码保守判在拦(self):
        self.assertTrue(wc._仍为拦截页(''))
        self.assertTrue(wc._仍为拦截页('   '))

    def test_与状态码版判定同源(self):
        for 页, 码 in ((经典页, 403), (访问页, 200), (正常页, 200)):
            self.assertEqual(
                wc._仍为拦截页(页), wc.is_waf_captcha_page(码, 页),
                f'内容判定与 is_waf_captcha_page({码}) 不同源: {页[:24]}')


class Test人工等待通过(unittest.TestCase):
    def test_拦截变正常_passed(self):
        d = _桩driver([访问页, 访问页, 正常页])
        self.assertEqual(wc._人工等待通过(d, time.time() + 5, 0.01), 'passed')

    def test_始终拦截_timeout(self):
        d = _桩driver([访问页])
        self.assertEqual(wc._人工等待通过(d, time.time() + 0.05, 0.01), 'timeout')

    def test_旧bug反例_访问页首poll不得判通过(self):
        # 旧实现: '__wafcaptcha' not in 访问页 → or 短路判已通过 (弹窗秒关根因)
        self.assertNotIn('__wafcaptcha', 访问页, 'fixture: ②型确无 __wafcaptcha')
        self.assertTrue(wc._仍为拦截页(访问页),
                        '②型必须继续等待, 不得首poll判通过')

    def test_取源码异常_error(self):
        d = _桩driver(['_raise'])
        self.assertEqual(wc._人工等待通过(d, time.time() + 5, 0.01), 'error')


if __name__ == '__main__':
    unittest.main(verbosity=2)
