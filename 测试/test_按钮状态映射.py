# -*- coding: utf-8 -*-
"""按钮状态映射键合法性护栏（2026-10-04 P0 事故后新增）。

## 事故
`ui_theme._底色覆盖()` 给**每个按钮**塞了 `overlay_color={'hover': …, 'focus': …}`。
但 `ButtonStyle.overlay_color` 的类型是 `dict[ControlState, 颜色]` ——
**键必须是 `ft.ControlState` 成员**，其枚举值是 `'hovered'/'focused'/'pressed'`。
字符串 `'hover'`/`'focus'` 不是合法状态名 → 客户端解析该 ButtonStyle 失败 →
**按钮整体渲染失败**（Flutter release 下为灰块）→ 连带整张卡片内容消失。
现象：**抓取工作台一片空白**（v2.4.46–v2.4.56），而不用按钮的页头/侧栏正常。

## 本护栏
① 真构建各工厂按钮，断言 overlay 映射的每个键都是 `ft.ControlState`；
② 源码里不得再出现 `'hover':` / `'focus':` 这类小写状态字符串键。
"""
import re
import unittest
from pathlib import Path

import _沙箱  # noqa: F401

import flet as ft

_ROOT = Path(__file__).resolve().parents[1]
_UI_THEME = _ROOT / '源码' / 'gui_components' / 'ui_theme.py'

_错键 = ("'hover':", "'focus':", '"hover":', '"focus":',
         "'hovered':", "'pressed':", "'focused':")   # 字符串写法一律不认，要枚举


def _去注释与文档串(文本: str) -> str:
    文本 = re.sub(r'"""(?:.|\n)*?"""', '', 文本)
    文本 = re.sub(r"'''(?:.|\n)*?'''", '', 文本)
    return '\n'.join(l for l in 文本.splitlines() if not l.strip().startswith('#'))


class Test按钮状态映射键合法(unittest.TestCase):

    def test_工厂按钮的overlay键都是ControlState(self):
        from gui_components import ui_theme
        按钮们 = [
            ('filled_btn', ui_theme.filled_btn('按钮')),
            ('tonal_btn', ui_theme.tonal_btn('按钮')),
            ('outline_btn', ui_theme.outline_btn('按钮')),
            ('text_btn', ui_theme.text_btn('按钮')),
            ('danger_btn', ui_theme.danger_btn('按钮')),
        ]
        for 名, b in 按钮们:
            样式 = getattr(b, 'style', None)
            覆盖 = getattr(样式, 'overlay_color', None) if 样式 is not None else None
            if 覆盖 is None:
                continue
            self.assertIsInstance(覆盖, dict, f'{名} 的 overlay_color 应是 ControlState→色 的映射')
            for k in 覆盖:
                self.assertIsInstance(
                    k, ft.ControlState,
                    f'{名} 的 overlay_color 键 {k!r} 不是 ft.ControlState 成员 '
                    f'(枚举值形如 hovered/focused/pressed) —— 客户端会因此解析失败并'
                    f'把按钮渲染成灰块')
            for v in 覆盖.values():
                self.assertIsInstance(v, str, f'{名} 的 overlay 颜色应是字符串色值')

    def test_源码不再出现小写状态字符串键(self):
        码 = _去注释与文档串(_UI_THEME.read_text(encoding='utf-8'))
        违规 = [坏 for 坏 in _错键 if 坏 in 码]
        self.assertEqual(违规, [], f'ui_theme.py 里仍用字符串状态键 {违规} —— '
                                   f'必须用 ft.ControlState 枚举成员')


if __name__ == '__main__':
    unittest.main(verbosity=2)
