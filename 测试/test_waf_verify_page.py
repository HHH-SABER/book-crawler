# -*- coding: utf-8 -*-
"""内容型 WAF"访问验证"页识别 (als1010 批次 2026-09-12 实锤样本)。

背景 (HANDOFF 待办 #1): als1010.space 把图片验证码页以 **HTTP 200** 返回
(1475 字符, 标题"访问验证", form action=/home/chapter/check_code.html,
图片 /home/chapter/verify.html); 旧判定 is_waf_captcha_page 要求 401/403/429
→ 拦截页被当正文, 清洗后落为空章 (批次 8 本书正文全空)。

本测试锁定两条防线都不再漏判, 且不误伤正常正文页:
  1. 反爬检测器 → 机制 waf_verify_page (自动记风控事件 + 即时降档);
  2. is_waf_captcha_page → True (进入爬虫既有 WAF 分支 → 人工兜底)。

离线运行: python -m unittest discover -s 测试 -v
"""

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / '源码'))

_样本 = (_ROOT / '测试样本' / 'als1010_访问验证页.html').read_text(encoding='utf-8')


class 假响应:
    """最小响应替身 (检测器只依赖 status_code/headers/text/url)"""

    def __init__(self, status, text):
        self.status_code = status
        self.text = text
        self.headers = {}
        self.url = 'https://xn--vcsx64d.als1010.space/book/50585/be101e8b60c8d.html'


class Test内容型验证页识别(unittest.TestCase):

    def test_检测器识别访问验证页(self):
        from 反爬检测器 import 取检测器
        r = 取检测器().识别(假响应(200, _样本))
        self.assertEqual(r.机制, 'waf_verify_page', r.证据)
        self.assertGreaterEqual(r.置信度, 0.85)
        self.assertTrue(r.建议策略.get('use_selenium'))

    def test_正常正文页不误判(self):
        from 反爬检测器 import 取检测器
        正常 = ('<html><head><title>第1章</title></head><body>'
                + '正文内容，正常小说段落。' * 200 + '</body></html>')
        self.assertEqual(取检测器().识别(假响应(200, 正常)).机制, 'none')

    def test_长页面含关键词不误判(self):
        """正文 >16KB 即使偶然出现 访问验证/check_code 也不判拦截"""
        from 反爬检测器 import 取检测器
        长文 = ('<html><body>访问验证 check_code ' + '正' * 20000 + '</body></html>')
        self.assertNotEqual(取检测器().识别(假响应(200, 长文)).机制,
                            'waf_verify_page')

    def test_waf求解链判定_两类形态(self):
        from waf_captcha import is_waf_captcha_page
        # 内容型 (200): 进入 WAF 分支 → 自动识别不适用 → 人工兜底
        self.assertTrue(is_waf_captcha_page(200, _样本))
        # 经典 __wafcaptcha (401/403/429): 回归不破坏
        self.assertTrue(is_waf_captcha_page(403, '__wafcaptcha 请输验证码'))
        # 负例: 正常页 / 空文本 / 200 状态但非验证页
        self.assertFalse(is_waf_captcha_page(
            200, '<html><title>第1章</title><body>' + '正文' * 500 + '</body></html>'))
        self.assertFalse(is_waf_captcha_page(200, ''))
        self.assertFalse(is_waf_captcha_page(404, _样本))

    def test_检测器不抛异常(self):
        """识别包装器容错: 异常响应对象也不得中断抓取主流程"""
        from 反爬检测器 import 取检测器
        class 坏响应:
            status_code = 200
            @property
            def text(self):
                raise RuntimeError('boom')
            headers = {}
        r = 取检测器().识别(坏响应())
        self.assertIn(r.机制, ('none', 'waf_verify_page'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
