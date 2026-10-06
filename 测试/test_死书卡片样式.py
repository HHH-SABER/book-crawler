# -*- coding: utf-8 -*-
"""死书卡片对齐设计稿的回归（2026-10-06 批 3）。

设计稿（`界面设计预览/index.html`）：
  `.deadbook-card { border-left: 3px solid var(--status-*-line) }`  ← 左侧 3px 状态色条
  `.deadbook-meta` = 等宽 URL · 判定于 <时间> · （设计稿还有 HTTP 码/已抓章节）·
  font-size --fs-micro、色 text-tertiary。

程序侧记录里**没有** HTTP 码与已抓章节字段 → 不编造，只用真实字段。
本护栏钉住：① 左侧色条宽度与按三态取色（不是硬编码色值）；
② meta 行含 URL/判定于/尝试 N 次；③ 色条**随主题换色**（登记重刷，防半迁移）。
"""
import unittest

import _沙箱  # noqa: F401

import flet as ft

from gui_components import ui_tokens
from gui_components.pages.dead_book_page import DeadBookPage

_记录样板 = {
    '键': 'k1',
    '网址': 'https://siteA.example.com/novel/1001.html',
    '书名': '示例长篇甲',
    '域名': 'siteA.example.com',
    '类型': '书已删除或不可读',
    '原因': '目录页返回服务器错误页',
    '状态': '待确认',
    '首次时间': '2026-10-06 10:00',
    '最近时间': '2026-10-06 21:14',
    '次数': 2,
    '任务id': ['task_1'],
    '可询问删除': True,
}


def _收集文本(控件) -> str:
    出 = []

    def 走(c):
        if c is None:
            return
        v = getattr(c, 'value', None)
        if isinstance(v, str):
            出.append(v)
        for 属 in ('controls', 'content'):
            子 = getattr(c, 属, None)
            if isinstance(子, (list, tuple)):
                for x in 子:
                    走(x)
            elif 子 is not None:
                走(子)
    走(控件)
    return '\n'.join(出)


class Test死书卡片样式(unittest.TestCase):

    def setUp(self):
        ui_tokens.设置主题(False)
        self.addCleanup(lambda: ui_tokens.设置主题(False))
        self.页 = DeadBookPage()

    def _卡片(self, 状态: str):
        记录 = dict(_记录样板, 状态=状态)
        return self.页._行(记录), 记录

    def test_左侧色条宽度为3(self):
        卡片, _ = self._卡片('待确认')
        边框 = 卡片.border
        self.assertIsNotNone(边框, '卡片必须有边框 (设计稿的左侧状态色条)')
        self.assertIsNotNone(边框.left, '缺少左侧边框')
        self.assertEqual(边框.left.width, 3, '设计稿 .deadbook-card 的左侧色条是 3px')

    def test_色条按三态取色而不是硬编码(self):
        期望 = {'待确认': 'status-warning-line',
                '已删除': 'status-error-line',
                '已忽略': 'status-pending-line'}
        for 状态, 色键 in 期望.items():
            卡片, _ = self._卡片(状态)
            self.assertEqual(卡片.border.left.color, ui_tokens.取色(色键),
                             f'{状态} 的色条应取 {色键}')

    def test_色条随主题换色(self):
        """防半迁移: 只写取色()、不登记 登记重刷 的话, 切夜间色条不变。"""
        卡片, _ = self._卡片('已删除')
        日间 = 卡片.border.left.color
        self.assertEqual(日间, ui_tokens.取色('status-error-line', False))
        ui_tokens.设置主题(True)
        self.assertEqual(卡片.border.left.color, ui_tokens.取色('status-error-line', True),
                         '切夜间后左侧色条没换色 —— 说明没登记重刷')
        self.assertNotEqual(卡片.border.left.color, 日间, '日夜色值应不同 (否则本用例无意义)')

    def test_meta行含URL判定时间与尝试次数(self):
        卡片, 记录 = self._卡片('待确认')
        文本 = _收集文本(卡片)
        self.assertIn('https://siteA.example.com/novel/1001.html', 文本, 'meta 行缺 URL')
        self.assertIn('判定于 2026-10-06 21:14', 文本, 'meta 行缺「判定于 <时间>」')
        self.assertIn('尝试 2 次', 文本, 'meta 行缺「尝试 N 次」')
        self.assertIn('示例长篇甲', 文本, '标题缺失')

    def test_线条令牌日夜成对存在(self):
        for 键 in ('status-warning-line', 'status-error-line',
                  'status-pending-line', 'status-success-line'):
            日 = ui_tokens.取色(键, False)
            夜 = ui_tokens.取色(键, True)
            self.assertTrue(日 and 夜, f'{键} 缺日间或夜间值')
            self.assertNotEqual(日, 夜, f'{键} 日夜同值 = 该令牌不会换色')
            # 设计稿蓝本是 rgba 半透明 → Flet 用 #aarrggbb 表达 (8 位十六进制)
            self.assertRegex(日, r'^#[0-9A-Fa-f]{8}$', f'{日} 应是 #aarrggbb')


if __name__ == '__main__':
    unittest.main(verbosity=2)
