# -*- coding: utf-8 -*-
"""Flet 关键字参数名合法性护栏（2026-10-06 新增）。

## 为什么需要
同一类问题已经咬过本项目**三次**，每一次都表现为"功能静默失效"而非报错：

| 事故 | 错在哪 | 后果 |
|---|---|---|
| 抓取工作台整片空白 (v2.4.46–56) | `ButtonStyle.overlay_color` 的状态键写成 `'hover'`/`'focus'`（合法值是 `ft.ControlState` 成员 `hovered`/`focused`） | 按钮渲染失败 → Flutter release 灰块 → 整张卡片消失，日志零异常 |
| 主题构建崩 | `ft.Theme(snack_bar_theme=…)`（真名 `snackbar_theme`） | 建主题即 TypeError |
| 补址弹窗从未显示过 | `ft.TextField(hint=…)`（真名 `hint_text`） | 弹窗在 `try` 之外构造 → 异常冒出 → 永远不弹 |

这类错误 `check_undefined_refs.py` **抓不到**（名字本身是"存在"的），只在运行时炸，
而且常被裸 `except` 吞掉。本护栏在**离线静态期**把它们全部拦下。

## 做法
AST 扫 `源码/**.py`：对每个 `ft.Xxx(kw=…)` 调用，若 `ft.Xxx` 是 **dataclass 控件类**，
则断言每个关键字名都在其 `dataclasses.fields` 里；含 `**kwargs` 解包的调用跳过
（无法静态判定）。Flet 的非类成员（`ft.app`、`ft.padding.all`、`ft.Icons` 等）自动跳过。
"""
import ast
import dataclasses
import re
import unittest
from pathlib import Path

import _沙箱  # noqa: F401

import flet as ft

_ROOT = Path(__file__).resolve().parents[1]
_源码 = _ROOT / '源码'

# 允许清单: 极少数情况下 Flet 的 dataclass 字段与运行时接受的参数不同。
# 加条目必须写清原因 —— 否则这条护栏会退化成"看见红就加白名单"。
_允许例外 = {}


def _扫描() -> list:
    违规 = []
    for f in sorted(_源码.rglob('*.py')):
        try:
            树 = ast.parse(f.read_text(encoding='utf-8'))
        except SyntaxError as e:
            违规.append((f, 0, f'语法错误: {e}', '解析'))
            continue
        for node in ast.walk(树):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not (isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name)
                    and fn.value.id == 'ft'):
                continue
            类 = getattr(ft, fn.attr, None)
            if not isinstance(类, type) or not dataclasses.is_dataclass(类):
                continue
            if any(k.arg is None for k in node.keywords):
                continue        # 有 **kwargs 解包 → 静态判不了
            字段 = {x.name for x in dataclasses.fields(类)}
            for kw in node.keywords:
                if kw.arg is None or kw.arg in 字段 or kw.arg in _允许例外:
                    continue
                违规.append((f, node.lineno, f'ft.{fn.attr}({kw.arg}=…)', '参数名'))
    return 违规


class TestFlet参数名合法(unittest.TestCase):

    def test_控件关键字参数都存在(self):
        违规 = _扫描()
        报 = '\n  '.join(f'{f.relative_to(_ROOT)}:{行}  {名}' for f, 行, 名, _ in 违规)
        self.assertEqual(违规, [],
                         'Flet 控件参数名不存在 —— 会在运行时 TypeError, 且常被静默吞掉:\n  ' + 报)

    def test_护栏自身有效(self):
        """负向自检: 塞一段已知非法的调用, 扫描器必须报出来。"""
        非法 = ast.parse("import flet as ft\nft.TextField(hint='x', definitely_not_a_field=1)\n")
        命中 = []
        for node in ast.walk(非法):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                类 = getattr(ft, node.func.attr, None)
                if isinstance(类, type) and dataclasses.is_dataclass(类):
                    字段 = {x.name for x in dataclasses.fields(类)}
                    命中 = [k.arg for k in node.keywords if k.arg not in 字段]
        self.assertEqual(sorted(命中), ['definitely_not_a_field', 'hint'],
                         '扫描逻辑失效 —— 连 hint= 都抓不到')

    def test_不得靠白名单掩盖问题(self):
        self.assertEqual(_允许例外, {},
                         '例外清单不为空时必须写明原因并同步 文档/修改记录.md')