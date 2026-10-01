# -*- coding: utf-8 -*-
"""请求引擎按域 Cookie 注入回归 (站点脱钩: 登录态凭证外置, 不入库)。

锁定 注入COOKIE() 的行为契约:
  ① 后缀匹配注入 (sitead.example.net ↔ www.sitead.example.net); ② 调用方显式 Cookie 不覆盖;
  ③ 无匹配/空表不注入; ④ 不修改调用方原 dict; ⑤ 公开形态恒等返回。

全程离线 (不加载真实 域名cookies.json, 直接操作内存 dict)。
运行: python -m unittest discover -s 测试 -v
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '源码'))

import 请求引擎 as re_mod


class Test按域Cookie注入(unittest.TestCase):
    """注入COOKIE(): 登录态按域附加的机制契约"""

    def setUp(self):
        # 备份真实域Cookie表, 用受控表隔离 (不读磁盘上的域名cookies.json)
        self._旧表 = dict(re_mod._域COOKIE)
        re_mod._域COOKIE.clear()
        re_mod._域COOKIE.update({'sitead.example.net': 'uid=1; sid=abc'})

    def tearDown(self):
        re_mod._域COOKIE.clear()
        re_mod._域COOKIE.update(self._旧表)

    def test_后缀匹配注入(self):
        h = {'User-Agent': 'UA'}
        out = re_mod.注入COOKIE(h, 'https://www.sitead.example.net/html/4520268/mulu_1.html')
        self.assertEqual(out['Cookie'], 'uid=1; sid=abc')
        self.assertEqual(out['User-Agent'], 'UA', '原头必须保留')
        self.assertNotIn('Cookie', h, '不得修改调用方原 dict')

    def test_裸域与子域互为后缀(self):
        out1 = re_mod.注入COOKIE({}, 'https://sitead.example.net/a.html')
        self.assertIn('Cookie', out1)
        out2 = re_mod.注入COOKIE({}, 'https://x.sitead.example.net/a.html')
        self.assertIn('Cookie', out2)

    def test_调用方显式Cookie不覆盖(self):
        h = {'Cookie': 'mine=1'}
        out = re_mod.注入COOKIE(h, 'https://www.sitead.example.net/a.html')
        self.assertEqual(out['Cookie'], 'mine=1', '显式 Cookie 优先')

    def test_无匹配不注入(self):
        h = {'User-Agent': 'UA'}
        out = re_mod.注入COOKIE(h, 'https://example.org/a.html')
        self.assertNotIn('Cookie', out)
        self.assertEqual(out, h)

    def test_空表恒等返回(self):
        re_mod._域COOKIE.clear()
        h = {'User-Agent': 'UA'}
        out = re_mod.注入COOKIE(h, 'https://www.sitead.example.net/a.html')
        self.assertEqual(out, h, '空表 (公开形态) 必须恒等返回原 headers')

    def test_headers为None时创建(self):
        out = re_mod.注入COOKIE(None, 'https://www.sitead.example.net/a.html')
        self.assertEqual(out, {'Cookie': 'uid=1; sid=abc'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
