# -*- coding: utf-8 -*-
"""可折叠日志条：默认 130px 显示选中任务日志, 点击手柄放大/收起

上拉放大后占据主区大部分高度 (完整终端), 再点收回到紧凑条。
终端风格沿用 ui_theme (深底 + 等宽字体 + 级别着色)。
"""
import flet as ft

from .task_manager import TaskManager
from .ui_theme import (make_card, LOG_TERMINAL_BG, LOG_TERMINAL_FONT,
                       log_line_color)
from .ui_morandi import (FONT_STACK, SIZE_TINY, SIZE_SMALL, SIZE_BODY,
                         WEIGHT_BODY, MORANDI_SUCCESS, MORANDI_ERROR)

# 两种状态的高度
_HEIGHT_COLLAPSED = 130
_HEIGHT_EXPANDED = 460


class LogStrip:
    """可折叠日志条组件 (跟随选中任务的实时日志)"""

    def __init__(self, task_manager: TaskManager):
        self.task_manager = task_manager
        self.page = None
        self._expanded = False
        # UI 引用
        self.log_list = None
        self.container = None
        self.handle_btn = None
        self.title_text = None

    def build(self) -> ft.Control:
        """构建日志条"""
        self.log_list = ft.ListView(
            expand=True, spacing=1, auto_scroll=True,
        )
        self.title_text = ft.Text("实时日志 (选中任务)", size=SIZE_SMALL,
                                  weight=WEIGHT_BODY,
                                  color=ft.Colors.ON_SURFACE_VARIANT,
                                  font_family=FONT_STACK)
        self.handle_btn = ft.IconButton(
            icon=ft.Icons.KEYBOARD_ARROW_UP,
            icon_size=16,
            tooltip="放大/收起日志",
            on_click=self._toggle_expand,
            style=ft.ButtonStyle(
                padding=4, shape=ft.RoundedRectangleBorder(radius=6),
            ),
        )

        self.container = make_card(
            ft.Column([
                # 标题行: 手柄 + 标题 + 空状态提示
                ft.Row([
                    self.handle_btn,
                    self.title_text,
                ], spacing=4),
                # 终端风格日志面板
                ft.Container(
                    content=self.log_list,
                    expand=True,
                    bgcolor=LOG_TERMINAL_BG,
                    border_radius=8,
                    padding=8,
                ),
            ], spacing=4),
            padding=8,
        )
        self.container.height = _HEIGHT_COLLAPSED
        return self.container

    def _toggle_expand(self, e=None):
        """放大/收起切换"""
        self._expanded = not self._expanded
        self.container.height = (_HEIGHT_EXPANDED if self._expanded
                                 else _HEIGHT_COLLAPSED)
        self.handle_btn.icon = (ft.Icons.KEYBOARD_ARROW_DOWN if self._expanded
                                 else ft.Icons.KEYBOARD_ARROW_UP)
        self.handle_btn.tooltip = ("收起日志" if self._expanded else "放大日志")
        try:
            self.page.update()
        except Exception:
            pass

    # ----------------------------------------------------------- 刷新 (主线程)
    def refresh(self):
        """刷新选中任务的日志 (须在主线程调用, 由刷新 Timer 驱动)"""
        if self.log_list is None:
            return
        tid = self.task_manager.selected_task_id
        if not tid:
            if self.title_text.value != "实时日志 (选中任务)":
                self.title_text.value = "实时日志 (选中任务)"
            return
        task = self.task_manager.get_task(tid)
        if not task:
            return
        self.title_text.value = f"实时日志 · {task.title[:24]}"

        # 只显示最近 100 条, 终端风格着色
        self.log_list.controls.clear()
        for log in task.logs[-100:]:
            msg = log['msg']
            text_color = log_line_color(msg)
            if '[错误]' in msg or '失败' in msg:
                text_color = MORANDI_ERROR
            elif '成功' in msg or '完成' in msg:
                text_color = MORANDI_SUCCESS
            self.log_list.controls.append(
                ft.Text(f"[{log['time']}] {msg}",
                        size=SIZE_TINY,
                        font_family=LOG_TERMINAL_FONT,
                        color=text_color,
                        selectable=True)
            )
