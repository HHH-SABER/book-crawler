# -*- coding: utf-8 -*-
"""筛选栏通用原语（2026-11-10，统一内容库改造）。

只提供**单选胶囊组**这一个原语，不抽"整条筛选栏"：
· 内容库的维度是"任务品类"（全部/小说/漫画）；
· 历史页是「站点 + 时间 + 结果 + 书名检索」，数据源是 URL 级历史（无 task_id、无品类）；
· 死书页是「状态 + 类型」，数据源是死书清单 JSON。
三者维度结构不同，硬统一只会让接口堆满可选参数或改变语义。故只共享最底层的
"一排单选胶囊"。

为什么不直接用 `ui_theme.chip_btn` 的 `设选中()`：该闭包捕获的是构建期的
`选中` 变量，运行时调用并不改变配色（只在 on_hover/回调里生效）。本组件改为
**重建按钮**来切换选中态 —— 三个胶囊的重建成本可忽略，且不触碰 chip_btn 的
既有调用方。
"""
from typing import Callable, Optional, Sequence, Tuple

import flet as ft

from .ui_theme import chip_btn


class 胶囊组:
    """一排互斥胶囊（单选）。

    选项: [(键, 标签)] 或 ['全部', '小说']（键即标签）。
    on_change(键) 在用户点击发生切换时调用；`设值(..., 触发回调=True)` 也会调用。
    """

    def __init__(self, 选项: Sequence, 当前: Optional[str] = None,
                 on_change: Optional[Callable[[str], None]] = None,
                 间距: int = 6):
        self.选项: list[Tuple[str, str]] = [
            (k, k) if isinstance(k, str) else (k[0], k[1]) for k in 选项
        ]
        if not self.选项:
            raise ValueError('胶囊组至少需要一个选项')
        self._当前 = 当前 if 当前 in dict(self.选项) else self.选项[0][0]
        self.on_change = on_change
        self._间距 = 间距
        self._row: Optional[ft.Row] = None

    # ---------------------------------------------------------------- 构建
    def build(self) -> ft.Control:
        self._row = ft.Row(spacing=self._间距, tight=True,
                           vertical_alignment=ft.CrossAxisAlignment.CENTER)
        self._重绘()
        return self._row

    def _重绘(self):
        if self._row is None:
            return
        self._row.controls.clear()
        for 键, 标签 in self.选项:
            self._row.controls.append(
                chip_btn(标签, 选中=(键 == self._当前),
                         on_click=lambda e, k=键: self._点击(k)))
        try:
            self._row.update()
        except Exception:
            pass    # 刻意静默: 组件未挂载(单测/构建期)时 update 必抛, 不影响状态

    # ---------------------------------------------------------------- 状态
    @property
    def 当前(self) -> str:
        return self._当前

    def _点击(self, 键: str):
        if 键 == self._当前:
            return
        self._当前 = 键
        self._重绘()
        if self.on_change:
            self.on_change(键)

    def 设值(self, 键: str, 触发回调: bool = False):
        """外部设置选中项（偏好恢复/新建任务后自动切筛选）。"""
        if 键 not in dict(self.选项) or 键 == self._当前:
            return
        self._当前 = 键
        self._重绘()
        if 触发回调 and self.on_change:
            self.on_change(键)
