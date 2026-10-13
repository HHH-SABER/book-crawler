# -*- coding: utf-8 -*-
"""内容分页续猜（C 修法）回归 (2026-10-13 新增)。

背景: `<站点Q>` 类站点键盘翻页 (无 <a> 分页链接), 第 1 页清洗后仅 37 字节。
旧逻辑 `len(page_text) < 50 → break` 把分页截断误判为末页。C 修法: 仅第 1 页
内容过短时给一次后续页机会, 让循环按内置 `_N.html` 规则试探。

本文件锁 `_过短给后续页机会()` 纯函数契约; 已做变异测试 (K33): 把判定改成
`页序 == 1` 后本文件用例全部变红 (护栏非装饰)。
运行: .runtime/python314/python.exe -m unittest discover -s 测试
"""
import sys
import unittest
from pathlib import Path

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

import 爬虫   # noqa: E402


class Test过短给后续页机会(unittest.TestCase):
    """`_过短给后续页机会()`: 分页截断与真末页的区分策略"""

    def test_第一页过短给机会(self):
        """站点Q 案例: 第 1 页 37 字节 → 必须给后续页机会 (分页截断)"""
        self.assertTrue(爬虫._过短给后续页机会(0))

    def test_第二页起过短不再给(self):
        """真末页场景: 第 2 页仍过短 → 停止, 避免空抓满 20 页"""
        self.assertFalse(爬虫._过短给后续页机会(1))
        self.assertFalse(爬虫._过短给后续页机会(2))
        self.assertFalse(爬虫._过短给后续页机会(19))

    def test_负页号防御(self):
        """页序不应为负 (防御性: 负值一律不给机会)"""
        self.assertFalse(爬虫._过短给后续页机会(-1))

    def test_返回值是布尔(self):
        """契约: 严格布尔 (if 判断依赖, 不接受 None/0 等模糊真值)"""
        self.assertIs(爬虫._过短给后续页机会(0), True)
        self.assertIs(爬虫._过短给后续页机会(5), False)


if __name__ == '__main__':
    unittest.main(verbosity=2)
