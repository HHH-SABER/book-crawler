# -*- coding: utf-8 -*-
"""Flet 颜色格式合法性护栏（2026-10-04 事故后新增）。

## 事故
暖色主题 Phase 1+2 把设计稿的 **CSS 变量值**（`rgba(0,0,0,0.08)` 等）原样搬进了
Flet 调色板（`ui_tokens`）与主题（`ui_fluent` 的 `outline_variant`/`shadow`/`scrim`）。
但 Flet 官方只认 `#rrggbb` / `#aarrggbb` / `0x...` / Material 命名色（
见 https://flet.dev/docs/cookbook/colors/ ："not arbitrary CSS-like color names"）。
CSS 的 `rgba()` 不是合法 Flet 色值 → **客户端解析失败** → 依赖该色的控件子树
整体渲染失败（Flutter release 模式表现为**纯灰块**）。
现象：**抓取工作台一片空白**（两张卡的内容全灭，而显式写色的侧栏/页头照常渲染）。
影响版本：v2.4.46–v2.4.55；v2.4.45 及之前正常。

## 本护栏
① 源码里不得出现 CSS 写法颜色字面量（注释/文档字符串不算）；
② 令牌表与阴影表里的每个色值必须是合法 Flet 色值。
"""
import re
import unittest
from pathlib import Path

import _沙箱  # noqa: F401

import flet as ft

_ROOT = Path(__file__).resolve().parents[1]
_GUI = _ROOT / '源码' / 'gui_components'

# 会被扫的源码（颜色字面量高发区）
_扫描文件 = [
    _GUI / 'ui_tokens.py',
    _GUI / 'ui_fluent.py',
    _GUI / 'ui_theme.py',
    _GUI / 'states.py',
    _ROOT / '源码' / 'gui_app.py',
] + sorted((_GUI / 'pages').glob('*.py'))

_CSS色 = re.compile(r'''(['"])(rgba?\(|hsla?\()''')
_合法hex = re.compile(r'^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$')
# Flet 认的少量命名色（Material 名）—— 出现新的就往这里加，别放 CSS 名
_合法命名 = {'transparent', 'white', 'black'}


def _去注释与文档串(文本: str) -> str:
    文本 = re.sub(r'"""(?:.|\n)*?"""', '', 文本)
    文本 = re.sub(r"'''(?:.|\n)*?'''", '', 文本)
    return '\n'.join(l for l in 文本.splitlines() if not l.strip().startswith('#'))


def _是合法Flet色(值) -> bool:
    if isinstance(值, ft.Colors):
        return True
    if not isinstance(值, str):
        return False
    v = 值.strip()
    if _合法hex.match(v):
        return True
    if v.lower() in _合法命名:
        return True
    # ft.Colors.with_opacity 产物形如 "red,0.5"
    if re.match(r'^[A-Za-z][A-Za-z0-9]*,\s*[0-9.]+$', v):
        return True
    return False


class Test颜色格式合法(unittest.TestCase):

    def test_源码里不得出现CSS写法颜色(self):
        违规 = []
        for f in _扫描文件:
            if not f.is_file():
                continue
            码 = _去注释与文档串(f.read_text(encoding='utf-8'))
            for m in _CSS色.finditer(码):
                行号 = 码[:m.start()].count('\n') + 1
                片段 = 码[m.start():m.start() + 40].split('\n')[0]
                违规.append(f'{f.name}:{行号} {片段}')
        self.assertEqual(违规, [], 'Flet 不认 CSS 的 rgb()/rgba()/hsl() 颜色写法 '
                                   '(官方仅支持 #rrggbb / #aarrggbb / 命名色):\n  '
                                   + '\n  '.join(违规))

    def test_令牌表每个色值都是合法Flet色(self):
        from gui_components import ui_tokens as t
        坏 = []
        for 表名, 表 in (('_日间', t._日间), ('_夜间色', t._夜间色)):
            for k, v in 表.items():
                if not _是合法Flet色(v):
                    坏.append(f'{表名}[{k}] = {v!r}')
        self.assertEqual(坏, [], '令牌表里存在 Flet 无法解析的色值:\n  ' + '\n  '.join(坏))

    def test_阴影色也是合法Flet色(self):
        from gui_components import ui_tokens as t
        坏 = []
        for 档 in ('sm', 'md', 'lg', 'xl'):
            try:
                阴影列表 = t.阴影(档)
            except Exception as e:      # 档位名变化时明确失败, 不静默
                self.fail(f'阴影({档!r}) 取值异常: {type(e).__name__}: {e}')
            for 影 in (阴影列表 if isinstance(阴影列表, (list, tuple)) else [阴影列表]):
                色 = getattr(影, 'color', None)
                if 色 is not None and not _是合法Flet色(色):
                    坏.append(f'阴影[{档}].color = {色!r}')
        self.assertEqual(坏, [], '阴影色不是合法 Flet 色值:\n  ' + '\n  '.join(坏))


if __name__ == '__main__':
    unittest.main(verbosity=2)
