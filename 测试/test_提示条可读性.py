# -*- coding: utf-8 -*-
"""提示条可读性护栏（2026-10-06）。

## 事故
死书清单页点「重新检测」后, 底部提示条**黑底黑字完全看不见**。
原因: Flutter 默认 SnackBar 底 = `colorScheme.inverseSurface`(**深色**)、字 = 浅色;
但本项目为修 v2.4.19「EXE 里弹窗文字不可见」, 多处把文字**显式**设成
`ON_SURFACE`(深色 #1B1B1B) —— 显式色覆盖主题默认 → **深字压深底**。

## 本护栏
① 令牌对 `toast-bg`/`toast-fg` 在日夜两种主题下 **WCAG 对比度 ≥ 4.5:1**;
② `ui_fluent.提示条()` 必须**同时**给出底色与字色, 且取自同一对令牌; 切主题后仍成对;
③ 全库不得再出现裸 `ft.SnackBar(`（唯一构造点是 `ui_fluent.提示条`）,
   否则又会有人只改字色不改底色。
"""
import re
import unittest
from pathlib import Path

import _沙箱  # noqa: F401

from gui_components import ui_tokens

_ROOT = Path(__file__).resolve().parents[1]
_源码 = _ROOT / '源码'
_UI_FLUENT = _源码 / 'gui_components' / 'ui_fluent.py'


def _去注释与文档串(文本: str) -> str:
    文本 = re.sub(r'"""(?:.|\n)*?"""', '', 文本)
    文本 = re.sub(r"'''(?:.|\n)*?'''", '', 文本)
    return '\n'.join(l for l in 文本.splitlines() if not l.strip().startswith('#'))


def _相对亮度(色: str) -> float:
    assert re.match(r'^#[0-9a-fA-F]{6}$', 色), f'只支持 6 位 hex, 收到 {色!r}'
    r, g, b = (int(色[i:i + 2], 16) / 255 for i in (1, 3, 5))

    def _线性(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * _线性(r) + 0.7152 * _线性(g) + 0.0722 * _线性(b)


def _对比度(前景: str, 背景: str) -> float:
    亮 = _相对亮度(前景)
    暗 = _相对亮度(背景)
    高, 低 = max(亮, 暗), min(亮, 暗)
    return (高 + 0.05) / (低 + 0.05)


class Test提示条可读性(unittest.TestCase):

    def test_toast令牌日夜对比度都够(self):
        for 夜间 in (False, True):
            bg = ui_tokens.取色('toast-bg', 夜间)
            fg = ui_tokens.取色('toast-fg', 夜间)
            比 = _对比度(fg, bg)
            self.assertGreaterEqual(
                比, 4.5,
                f'{"夜" if 夜间 else "日"}间提示条对比度仅 {比:.1f}:1 '
                f'(底色 {bg} / 字色 {fg}) —— 低于 WCAG AA 4.5:1')

    def test_主题默认提示条底色字色也成对(self):
        """主题里 snackbar_theme 用的 inverse_surface/on_inverse_surface 也要够对比

        注意字段名是 flet 的 `snackbar_theme`（无下划线）；写成 `snack_bar_theme`
        会在建主题时 TypeError 直接崩（2026-10-06 本护栏当场抓过一次）。
        """
        from gui_components import ui_fluent
        for 造 in (ui_fluent.make_morandi_theme, ui_fluent.make_morandi_dark_theme):
            主题 = 造()
            提示 = getattr(主题, 'snackbar_theme', None)
            self.assertIsNotNone(提示, '主题未设 snackbar_theme (裸 SnackBar 会退回默认深底)')
            bg = getattr(提示, 'bgcolor', None)
            字 = getattr(getattr(提示, 'content_text_style', None), 'color', None)
            self.assertTrue(bg and 字, 'snack_bar_theme 必须同时给出底色与字色')
            if re.match(r'^#[0-9a-fA-F]{6}$', bg) and re.match(r'^#[0-9a-fA-F]{6}$', 字):
                self.assertGreaterEqual(_对比度(字, bg), 4.5,
                                        f'主题默认提示条对比度不足: {bg} / {字}')

    def test_提示条构造器同时给底色与字色(self):
        from gui_components import ui_fluent
        ui_tokens.清空重刷表()
        ui_tokens.设置主题(False, 立即重刷=False)
        条 = ui_fluent.提示条('测试文案')
        self.assertEqual(条.bgcolor, ui_tokens.取色('toast-bg', False),
                         '提示条底色必须取自 toast-bg 令牌')
        内容 = 条.content
        self.assertEqual(内容.color, ui_tokens.取色('toast-fg', False),
                         '提示条文字色必须取自 toast-fg 令牌')
        # 切夜间 → 两者一起换 (登记重刷生效)
        ui_tokens.设置主题(True)
        self.assertEqual(条.bgcolor, ui_tokens.取色('toast-bg', True))
        self.assertEqual(内容.color, ui_tokens.取色('toast-fg', True))
        ui_tokens.清空重刷表()
        ui_tokens.设置主题(False, 立即重刷=False)

    def test_全库只有一处构造SnackBar(self):
        违规 = []
        for f in list(_源码.rglob('*.py')):
            if f.resolve() == _UI_FLUENT.resolve():
                continue     # 唯一允许的构造点
            码 = _去注释与文档串(f.read_text(encoding='utf-8'))
            for m in re.finditer(r'ft\.SnackBar\(', 码):
                行号 = 码[:m.start()].count('\n') + 1
                违规.append(f'{f.relative_to(_ROOT)}:{行号}')
        self.assertEqual(违规, [], '请改用 ui_fluent.提示条() —— 裸 ft.SnackBar 容易'
                                   '出现"只给字色不给底色"的深压深:\n  ' + '\n  '.join(违规))


if __name__ == '__main__':
    unittest.main(verbosity=2)
