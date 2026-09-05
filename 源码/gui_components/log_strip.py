# -*- coding: utf-8 -*-
"""可折叠日志条：默认 130px 显示选中任务日志, 点击手柄放大/收起

上拉放大后占据主区大部分高度 (完整终端), 再点收回到紧凑条。
终端风格沿用 ui_theme (深底 + 等宽字体 + 级别着色)。
"""
import flet as ft

from .task_manager import TaskManager
from .ui_theme import (make_card, LOG_TERMINAL_BG, LOG_TERMINAL_FONT,
                       log_line_color)
from .ui_morandi import (FONT_STACK, SIZE_TINY, SIZE_SMALL,
                         WEIGHT_BODY, MORANDI_SUCCESS, MORANDI_ERROR)

# 三档高度: 折叠默认 / 拖拽下限 / 拖拽上限 (防遮挡任务列表)
_HEIGHT_COLLAPSED = 130
_HEIGHT_MIN = 90
_HEIGHT_MAX = 380


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
        # 拖拽调高手柄 (P: 上边缘可竖向拖动, 约束 [_HEIGHT_MIN, _HEIGHT_MAX])
        drag_handle = ft.GestureDetector(
            content=ft.Container(
                content=ft.Row([], alignment=ft.MainAxisAlignment.CENTER),
                height=8, border_radius=4,
                bgcolor=ft.Colors.OUTLINE_VARIANT, margin=ft.margin.Margin(0, 0, 0, 2),
            ),
            mouse_cursor=ft.MouseCursor.RESIZE_ROW,
            on_pan_update=self._on_drag_resize,
            drag_interval=10,
        )

        self.container = make_card(
            ft.Column([
                drag_handle,
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

    def _on_drag_resize(self, e):
        """拖拽手柄调高度: 向上拖增大 (global_delta.y<0), 约束在 [MIN, MAX]"""
        try:
            dy = e.global_delta.y  # flet 0.86: DragUpdateEvent 无 delta_y
            h = float(self.container.height or _HEIGHT_COLLAPSED)
            new_h = max(_HEIGHT_MIN, min(_HEIGHT_MAX, h - dy))
            if abs(new_h - h) >= 1:
                self.container.height = new_h
                self._expanded = new_h > _HEIGHT_COLLAPSED + 5
                self.handle_btn.icon = (ft.Icons.KEYBOARD_ARROW_DOWN
                                        if self._expanded else ft.Icons.KEYBOARD_ARROW_UP)
                try:
                    self.container.update()
                except Exception:
                    pass
        except Exception:
            pass

    def _toggle_expand(self, e=None):
        """放大/收起切换"""
        self._expanded = not self._expanded
        self.container.height = (_HEIGHT_MAX if self._expanded
                                 else _HEIGHT_COLLAPSED)
        self.handle_btn.icon = (ft.Icons.KEYBOARD_ARROW_DOWN if self._expanded
                                 else ft.Icons.KEYBOARD_ARROW_UP)
        self.handle_btn.tooltip = ("收起日志" if self._expanded else "放大日志")
        try:
            self.page.update()
        except Exception:
            pass

    # ----------------------------------------------------------- 刷新 (主线程)
    # 设计稿语义色: [引擎]/[反爬]/[质检]/[增量]/[速度] 等前缀着不同颜色
    _SEMANTIC_COLORS = [
        ('[引擎]', '#4CC2FF'),      # 引擎: 亮蓝
        ('[反爬]', '#FCE100'),      # 反爬: 黄
        ('[质检]', '#6CCB5F'),      # 质检: 绿
        ('[增量]', '#9CD8F7'),      # 增量: 浅蓝
        ('[速度自适应]', '#4CC2FF'),
        ('[并发]', '#9CD8F7'),
        ('[缓存]', '#9D9D9D'),
    ]

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

        # 只显示最近 100 条, 终端风格着色 (级别色 + 设计稿语义前缀色)
        self.log_list.controls.clear()
        for log in task.logs[-100:]:
            msg = log['msg']
            text_color = log_line_color(msg)
            if '[错误]' in msg or '失败' in msg:
                text_color = MORANDI_ERROR
            elif '成功' in msg or '完成' in msg:
                text_color = MORANDI_SUCCESS
            else:
                for prefix, color in self._SEMANTIC_COLORS:
                    if prefix in msg:
                        text_color = color
                        break
            self.log_list.controls.append(
                ft.Text(f"[{log['time']}] {msg}",
                        size=SIZE_TINY,
                        font_family=LOG_TERMINAL_FONT,
                        color=text_color,
                        selectable=True)
            )
