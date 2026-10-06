# -*- coding: utf-8 -*-
"""截图钩子回归（2026-10-06 新增）。

## 为什么有这个钩子
做"设计稿 vs 程序"逐页对照要截 6 页 × 日夜 = 12 张图，而**鼠标坐标点击在 DPI 缩放下
不可靠**（实测点「死书清单」落到了「远控」页）→ 改为环境变量驱动：
  NC_START_PAGE=<页名>   启动直接切到该页
  NC_THEME=dark          启动即夜间主题

## 本护栏
① 解析是纯函数 `gui_app.解析启动钩子`，此处直接断言它的行为（含非法页名、缺省值）；
② 默认（不设环境变量）必须**一个都不动** —— 正常用户行为不能受钩子影响；
③ 钩子接入点必须存在且**受 try 保护**（钩子坏了绝不能拖垮启动）。
"""
import pathlib
import unittest

import _沙箱  # noqa: F401

import gui_app as G

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_GUI = _ROOT / '源码' / 'gui_app.py'
_全部页 = ['crawl', 'history', 'deadbook', 'sites', 'log', 'remote']


class Test启动钩子(unittest.TestCase):

    def test_缺省不动任何东西(self):
        """不设环境变量 = 不切页、不换主题（正常启动路径零影响）。"""
        r = G.解析启动钩子(_全部页, {})
        self.assertIsNone(r['页'])
        self.assertFalse(r['夜间'])
        self.assertEqual(r['警告'], '')

    def test_合法页名生效(self):
        for 页 in _全部页:
            with self.subTest(页=页):
                self.assertEqual(G.解析启动钩子(_全部页, {'NC_START_PAGE': 页})['页'], 页)

    def test_非法页名忽略并留原因(self):
        """非法值不能让启动失败：返回 None + 人话警告。"""
        r = G.解析启动钩子(_全部页, {'NC_START_PAGE': '不存在的页'})
        self.assertIsNone(r['页'])
        self.assertIn('无效', r['警告'])

    def test_夜间识别(self):
        for 值 in ('dark', 'DARK', ' night '):
            with self.subTest(值=值):
                self.assertTrue(G.解析启动钩子(_全部页, {'NC_THEME': 值})['夜间'])
        for 值 in ('', 'light', 'day'):
            with self.subTest(值=值):
                self.assertFalse(G.解析启动钩子(_全部页, {'NC_THEME': 值})['夜间'])

    def test_钩子接入点受保护(self):
        """接入点必须存在，且在 try 里 —— 钩子异常不得拖垮启动。"""
        文本 = _GUI.read_text(encoding='utf-8')
        self.assertIn('解析启动钩子(list(pages_map), os.environ)', 文本)
        块 = 文本.split('解析启动钩子(list(pages_map), os.environ)')[0][-400:]
        self.assertIn('try:', 块, '钩子接入点未包 try')
        self.assertIn('_switch_page', 文本.split('_钩子[')[1][:200] + 文本,
                      '钩子必须复用既有 _switch_page, 不得另造切页逻辑')


if __name__ == '__main__':
    unittest.main(verbosity=2)
