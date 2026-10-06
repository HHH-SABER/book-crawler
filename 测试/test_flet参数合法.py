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
（无法静态判定）。**嵌套属性调用** `ft.<模块>.<成员>(…)`（如 `ft.padding.Padding(…)`）
另查该成员是否存在 —— 2026-10-07 加固：此前这类被整体跳过，漏掉了
`ft.padding.symmetric(…)` / `ft.margin.only(…)` 这种"模块在、成员根本不在"的错
（运行时弹窗一开即 TypeError，界面静默不出现）。非调用的模块成员（如 `ft.Icons.RED`）不参与检查。
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


def _解析ft链(fn) -> tuple:
    """把调用目标解析成 `ft` 之后的属性链, 如 `ft.padding.symmetric(…)` → ('padding','symmetric')。

    非 ft 根 (含 `getattr(ft, x)` 这类动态取) → 空元组 (静态判不了)。
    """
    if not isinstance(fn, ast.Attribute):
        return ()
    链 = [fn.attr]
    当前 = fn.value
    while isinstance(当前, ast.Attribute):
        链.append(当前.attr)
        当前 = 当前.value
    if not (isinstance(当前, ast.Name) and 当前.id == 'ft'):
        return ()
    return tuple(reversed(链))


def _扫树(路径, 树) -> list:
    """扫一棵 AST, 返回 [(路径, 行号, 描述, 类别)]。"""
    违规 = []
    for node in ast.walk(树):
        if not isinstance(node, ast.Call):
            continue
        if any(k.arg is None for k in node.keywords):
            continue        # 有 **kwargs 解包 → 静态判不了
        链 = _解析ft链(node.func)
        if not 链:
            continue

        # ① 浅层 ft.Xxx(…): Xxx 是 dataclass → 逐关键字查字段
        if len(链) == 1:
            类 = getattr(ft, 链[0], None)
            if not (isinstance(类, type) and dataclasses.is_dataclass(类)):
                continue
            字段 = {x.name for x in dataclasses.fields(类)}
            for kw in node.keywords:
                if kw.arg in 字段 or kw.arg in _允许例外:
                    continue
                违规.append((路径, node.lineno, f'ft.{链[0]}({kw.arg}=…)', '参数名'))
            continue

        # ② 嵌套 ft.<mod>.<成员>(…) —— 2026-10-07 新增。
        #    此前 docstring 明写"非类成员自动跳过", 于是
        #    `ft.padding.symmetric(…)` / `ft.margin.only(…)` 这类
        #    「模块本身在、成员根本不存在」的错**完全漏检** ——
        #    实测后果是弹窗一开即 TypeError, 界面静默不出现 (K46 同族)。
        父 = ft
        for i, 名 in enumerate(链):
            if not hasattr(父, 名):
                父名 = 'ft.' + '.'.join(链[:i]) if i else 'ft'
                违规.append((路径, node.lineno, f'{父名}.{名}(…)', '成员不存在'))
                break
            父 = getattr(父, 名)
    return 违规


def _扫描() -> list:
    违规 = []
    for f in sorted(_源码.rglob('*.py')):
        try:
            树 = ast.parse(f.read_text(encoding='utf-8'))
        except SyntaxError as e:
            违规.append((f, 0, f'语法错误: {e}', '解析'))
            continue
        违规.extend(_扫树(f, 树))
    return 违规


class TestFlet参数名合法(unittest.TestCase):

    def test_控件关键字参数都存在(self):
        违规 = _扫描()
        报 = '\n  '.join(f'{f.relative_to(_ROOT)}:{行}  {名}' for f, 行, 名, _ in 违规)
        self.assertEqual(违规, [],
                         'Flet 控件参数名不存在 —— 会在运行时 TypeError, 且常被静默吞掉:\n  ' + 报)

    def test_护栏自身有效_参数名(self):
        """负向自检: 塞一段已知非法的调用, 扫描器必须报出来。"""
        非法 = ast.parse("import flet as ft\nft.TextField(hint='x', definitely_not_a_field=1)\n")
        命中 = {描述 for _, _, 描述, 类别 in _扫树(Path('<自检>'), 非法) if 类别 == '参数名'}
        self.assertIn('ft.TextField(hint=…)', 命中, '扫描逻辑失效 —— 连 hint= 都抓不到')
        self.assertIn('ft.TextField(definitely_not_a_field=…)', 命中)

    def test_护栏自身有效_嵌套成员不存在(self):
        """负向自检 (2026-10-07 加固): `ft.padding.symmetric` 不存在, 必须被抓出来。

        这正是本次加固要拦的错：模块 `ft.padding` 存在、成员 `symmetric` 不存在，
        此前被"非类成员自动跳过"整体漏检，运行时弹窗一打开即 TypeError、
        界面静默不出现（K46 同族）。
        """
        非法 = ast.parse("import flet as ft\nft.padding.symmetric(vertical=1)\n")
        违规 = _扫树(Path('<自检>'), 非法)
        self.assertTrue(any(类别 == '成员不存在' and 'symmetric' in 描述
                            for _, _, 描述, 类别 in 违规),
                        '嵌套属性"成员不存在"的错没被抓住')
        # 反向自检: 真实存在的成员/关键字不得误报
        合法 = ast.parse("import flet as ft\n"
                         "ft.padding.Padding(0, 4, 0, 4)\n"
                         "ft.Padding(0, 4, 0, 4)\n"
                         "ft.IconButton(icon=ft.Icons.REFRESH, icon_size=16)\n")
        self.assertEqual(_扫树(Path('<自检>'), 合法), [], '存在的成员/关键字被误报')

    def test_不得靠白名单掩盖问题(self):
        self.assertEqual(_允许例外, {},
                         '例外清单不为空时必须写明原因并同步 文档/修改记录.md')