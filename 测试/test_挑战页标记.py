# -*- coding: utf-8 -*-
"""C9 WAF 挑战页标记外置的回归用例 (离线)。

背景: `_solve_waf_js_challenge` 的"等待挑战页解析完成"循环里**写死了某站的名字**
(`'loading <站名>' not in src`) —— 那是公开仓库不该出现的站点信息, 也把"某站的
挑战页特征"硬编码进了通用解析代码。

改法: 站点专属标记改从**站点配置**的 `挑战页标记` 字段读 (本地站点表, 不入库);
通用标记 (`@wafjs` / `Loading...`) 仍在代码里。配置缺失 → 只用通用标记。

⚠️ 本文件**不含任何真实站点名/域名** (公开仓库红线):
  - 纯函数用**合成标记**测;
  - 守护用例用**通用正则**判断源码里有没有写死的 `loading <token>` 形态。

运行方式 (项目根目录):
    python -m unittest discover -s 测试 -v
"""
import re
import sys
import unittest
from pathlib import Path

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

import 爬虫 as C                # noqa: E402

_爬虫源码 = _根 / '源码' / '爬虫.py'


class Test挑战页标记纯函数(unittest.TestCase):

    def test_无配置只用通用标记(self):
        """公开形态 (站点表缺失) 的兜底 —— 只保留通用标记, 且不抛。"""
        self.assertEqual(C.挑战页标记(None), C.挑战页通用标记)
        self.assertEqual(C.挑战页标记({}), C.挑战页通用标记)
        self.assertTrue(C.挑战页通用标记, '通用标记不该为空')

    def test_配置里的站点专属标记载入(self):
        配置 = {'domain': 'example.com', '挑战页标记': ['loading 示例站']}
        标记 = C.挑战页标记(配置)
        self.assertIn('loading 示例站', 标记)
        for 通用 in C.挑战页通用标记:
            self.assertIn(通用, 标记, '通用标记必须仍在')

    def test_多个标记与字符串写法都支持(self):
        self.assertEqual(
            C.挑战页标记({'挑战页标记': ['a标记', 'b标记']})[-2:], ('a标记', 'b标记'))
        self.assertIn('单条标记', C.挑战页标记({'挑战页标记': '单条标记'}),
                      '字段写成字符串也要能用 (配置手写常见)')

    def test_异常配置不抛(self):
        for 坏 in ({'挑战页标记': 12345}, {'挑战页标记': None}, '不是字典', []):
            with self.subTest(坏=repr(坏)):
                self.assertEqual(C.挑战页标记(坏), C.挑战页通用标记)


class Test不得写死站点标记(unittest.TestCase):
    """C9 的脱钩守护: 通用解析代码里不得再出现 `'loading <某站>'` 这种写死标记。

    ⚠️ 用**通用正则**而不是具体站名 —— 否则这条守护本身就把站名写进了公开仓库。
    """

    def test_源码里没有写死的站点专属挑战页标记(self):
        源码 = _爬虫源码.read_text(encoding='utf-8')
        坏 = [x for x in re.findall(r"['\"][^'\"]{0,40}loading\s+[a-z0-9]{3,}[^'\"]{0,40}['\"]",
                                    源码, re.IGNORECASE)
              if '...' not in x]          # 'Loading...' 是通用标记, 不算
        self.assertEqual(
            坏, [],
            'C9: 通用代码里又出现了写死的站点挑战页标记, 应改为站点配置的 '
            f'`挑战页标记` 字段 (见 挑战页标记()) —— 检出: {坏}')

    def test_等待循环确实用上了配置化标记(self):
        """防"空转通过": 若 loop 被改回硬编码, 本用例要响亮失败。"""
        源码 = _爬虫源码.read_text(encoding='utf-8')
        起 = 源码.index('def _solve_waf_js_challenge')
        余 = 源码[起:]
        末 = 余.index('\n    def ', 1)        # 下一个同级方法
        函数体 = 余[:末]
        self.assertIn('挑战页标记(', 函数体,
                      '_solve_waf_js_challenge 应使用 挑战页标记() 取标记')
        self.assertIn('get_site_pattern', 函数体,
                      '标记应从站点配置读 (get_site_pattern)')

    def test_纯函数存在且被导出(self):
        self.assertTrue(callable(C.挑战页标记))
        self.assertTrue(hasattr(C, '挑战页通用标记'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
