# -*- coding: utf-8 -*-
"""通用表单式验证码自动求解 (als1010 类 200 状态"访问验证"页) 离线回归。

实网取证 (2026-09-12): 该站 WAF 为会话 cookie 制, 页面 code 输入框 +
/home/chapter/verify.html 图片 + check_code.html 表单; ddddocr 识别后按
原表单字段 POST 即放行 (28860 字符正文返回)。本测试用假会话+假 ddddocr
锁定: 求解成功路径 / 合规边界 (未开启识别必须拒绝) / 结构不匹配放弃。
"""
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / '源码'))

import waf_captcha as wc   # noqa: E402

_样本 = (_ROOT / '测试样本' / 'als1010_访问验证页.html').read_text(encoding='utf-8')
_正常页 = '<html><head><title>第1章</title></head><body>' + '正文。' * 400 + '</body></html>'
_目标 = 'https://example.com/book/50585/be101e8b60c8d.html'


class 假响应:
    def __init__(self, status, text='', content=b''):
        self.status_code = status
        self.text = text
        self.content = content or text.encode('utf-8')


class 假会话:
    """被拦 → 提交 → 放行 的状态机 (图片/提交路径均记录供断言)"""

    def __init__(self):
        self.放行 = False
        self.提交记录 = []

    def get(self, url, headers=None, timeout=None, **kw):
        if 'verify' in url:
            return 假响应(200, content=b'\x89PNG-fake-image')
        if url == _目标:
            return 假响应(200, _正常页 if self.放行 else _样本)
        return 假响应(200, '<html></html>')

    def post(self, url, data=None, headers=None, timeout=None, **kw):
        self.提交记录.append((url, dict(data or {})))
        self.放行 = True
        return 假响应(200, '<html></html>')


def _假ddddocr(答案='abcd'):
    模块 = types.ModuleType('ddddocr')
    class DdddOcr:
        def __init__(self, **kw):
            pass
        def classification(self, img):
            return 答案
    模块.DdddOcr = DdddOcr
    return 模块


class Test表单验证页求解(unittest.TestCase):

    def test_求解成功并沿用原表单字段(self):
        会话 = 假会话()
        with mock.patch.object(wc, '_ddddocr_enabled', return_value=True), \
                mock.patch.dict(sys.modules, {'ddddocr': _假ddddocr()}):
            ok = wc.solve_waf_captcha(会话, _目标, headers={'User-Agent': 'x'})
        self.assertTrue(ok, '应求解成功')
        self.assertEqual(len(会话.提交记录), 1)
        url, data = 会话.提交记录[0]
        self.assertTrue(url.endswith('/home/chapter/check_code.html'), url)
        self.assertEqual(data.get('code'), 'abcd', '验证码字段应沿用页面输入框名')
        self.assertIn('redirect', data, '隐藏域必须随表单提交')

    def test_识别未开启时拒绝_合规边界(self):
        会话 = 假会话()
        with mock.patch.object(wc, '_ddddocr_enabled', return_value=False):
            ok = wc.solve_waf_captcha(会话, _目标, headers={'User-Agent': 'x'})
        self.assertFalse(ok, '未开启自动识别必须拒绝 (合规边界)')
        self.assertEqual(会话.提交记录, [], '不得发起任何提交')

    def test_结构不匹配时放弃(self):
        无输入框样本 = _样本.replace('<input name="code"', '<input data-x="code"')
        会话 = 假会话()
        会话.放行 = False
        with mock.patch.object(wc, '_ddddocr_enabled', return_value=True), \
                mock.patch.dict(sys.modules, {'ddddocr': _假ddddocr()}):
            原get = 会话.get
            会话.get = lambda url, **kw: 假响应(200, 无输入框样本) \
                if url == _目标 else 原get(url, **kw)
            ok = wc._解_表单验证页(会话, _目标, 无输入框样本,
                                 {'User-Agent': 'x'}, 20, lambda m: None, 3)
        self.assertFalse(ok)
        self.assertEqual(会话.提交记录, [], '结构不匹配不得盲提交')


if __name__ == '__main__':
    unittest.main(verbosity=2)
