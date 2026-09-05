# -*- coding: utf-8 -*-
"""UI 主题系统：卡片工厂 + 状态标签 + 按钮统一样式 (Windows 11 Fluent 风格)

双主题适配原则：颜色优先使用 Flet Material3 语义色
（SURFACE / PRIMARY_CONTAINER / ERROR_CONTAINER 等）自动适配深浅主题；
需要跨主题保持辨识度的状态色/日志色则使用 ui_morandi 定义的 Fluent 色相。

Fluent 规范 (界面设计预览/index.html):
  - 卡片: 纯白面 (夜间 #2B2B2B) + 8px 圆角 + 细边框 + 轻阴影
  - 按钮/输入: 4px 圆角
  - 危险按钮: 实心红 (ON_ERROR 文字)
"""
import flet as ft

# 统一字体与字重规范 (来自 ui_morandi, 本模块所有文本必须遵守)
from .ui_morandi import (
    FONT_STACK, FONT_TERMINAL, SIZE_BODY, SIZE_TINY, WEIGHT_BODY,
    WEIGHT_EMPHASIS, WEIGHT_TITLE, MORANDI_TERMINAL_BG, LOG_COLOR_INFO,
    LOG_COLOR_ERROR, LOG_COLOR_WARN, LOG_COLOR_DEBUG,
    SIZE_TITLE, SIZE_SMALL,
)

# 统一按钮文字样式 (所有按钮工厂函数必须引用, 保证字号/字重/字体族一致)
BTN_TEXT_STYLE = ft.TextStyle(
    size=SIZE_BODY, weight=WEIGHT_BODY, font_family=FONT_STACK)

# ---------------------------------------------------------------- 卡片
CARD_RADIUS = 8       # Fluent --radius-lg
CARD_PADDING = 12

# Fluent 卡片阴影: 低模糊低透明度 (Win11 卡片浮起感克制)
_CARD_SHADOW = [
    ft.BoxShadow(
        blur_radius=10,
        spread_radius=-2,
        offset=ft.Offset(0, 2),
        color=ft.Colors.with_opacity(0.05, ft.Colors.BLACK),
    ),
]


def make_card(content, padding=CARD_PADDING, radius=CARD_RADIUS,
              expand=False, width=None, bgcolor=None, scroll=None,
              visible=None, border=None):
    """统一卡片：纯白表面 (夜间深灰) + 8px 圆角 + 细边框 + 轻阴影"""
    return ft.Container(
        content=content,
        width=width,
        expand=expand,
        padding=padding,
        bgcolor=bgcolor or ft.Colors.SURFACE,
        border_radius=radius,
        border=border or ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        visible=visible,
        shadow=_CARD_SHADOW,
    )


# ---------------------------------------------------------------- 页面标题
def page_header(title: str, subtitle: str = "", actions=None) -> ft.Control:
    """Fluent 页面大标题 + 副标题 + 右侧动作区 (匹配设计稿 page-header)"""
    left = ft.Column(
        [
            ft.Text(title, size=SIZE_TITLE, weight=WEIGHT_TITLE,
                    color=ft.Colors.ON_SURFACE, font_family=FONT_STACK),
            *([ft.Text(subtitle, size=SIZE_SMALL, weight=WEIGHT_BODY,
                       color=ft.Colors.ON_SURFACE_VARIANT,
                       font_family=FONT_STACK)] if subtitle else []),
        ],
        spacing=2,
    )
    row_controls = [left]
    if actions:
        row_controls.append(ft.Container(expand=True))
        row_controls.extend(actions)
    return ft.Row(row_controls,
                  vertical_alignment=ft.CrossAxisAlignment.CENTER)


# ---------------------------------------------------------------- 状态标签
# 任务状态 -> (前景色, 背景色) — Fluent badge: 浅色底 + 深语义字
STATUS_STYLES = {
    'running':   (ft.Colors.ON_PRIMARY_CONTAINER, ft.Colors.PRIMARY_CONTAINER),   # 蓝: 抓取中
    'completed': (ft.Colors.ON_SECONDARY_CONTAINER, ft.Colors.SECONDARY_CONTAINER),  # 绿: 已完成
    'failed':    (ft.Colors.ON_ERROR_CONTAINER, ft.Colors.ERROR_CONTAINER),       # 红: 失败
    'pending':   (ft.Colors.ON_SURFACE_VARIANT, ft.Colors.SURFACE_CONTAINER),     # 灰: 等待中
    'stopped':   (ft.Colors.ON_SURFACE_VARIANT, ft.Colors.SURFACE_CONTAINER_HIGH),  # 灰: 已停止
}

STATUS_LABELS = {
    'running': '抓取中',
    'completed': '已完成',
    'failed': '失败',
    'pending': '等待中',
    'stopped': '已停止',
}


def status_chip(status: str) -> ft.Control:
    """状态胶囊标签（圆角背景 + 统一字重小字）"""
    fg, bg = STATUS_STYLES.get(status, STATUS_STYLES['pending'])
    return ft.Container(
        content=ft.Text(STATUS_LABELS.get(status, status), size=SIZE_TINY,
                        weight=WEIGHT_EMPHASIS, color=fg,
                        font_family=FONT_STACK),
        padding=ft.Padding.symmetric(horizontal=8, vertical=2),
        bgcolor=bg,
        border_radius=10,
    )


def status_color(status: str):
    """状态主色（进度环/圆点用）"""
    return STATUS_STYLES.get(status, STATUS_STYLES['pending'])[1]


# ---------------------------------------------------------------- 按钮
def _btn_style():
    """统一按钮基础样式：Fluent 4px 圆角 + 规范字体"""
    return ft.ButtonStyle(
        shape=ft.RoundedRectangleBorder(radius=4),
        text_style=BTN_TEXT_STYLE,
    )


def filled_btn(text, icon=None, on_click=None, disabled=False, tooltip=None,
               visible=None):
    """填充按钮（主操作: Fluent 强调蓝）"""
    return ft.FilledButton(text, icon=icon, on_click=on_click,
                           disabled=disabled, tooltip=tooltip, visible=visible,
                           style=_btn_style())


def tonal_btn(text, icon=None, on_click=None, disabled=False, tooltip=None,
              visible=None):
    """次级按钮（Fluent 中性 chip: 浅灰面 + 细边框, 匹配设计稿 chip-btn）"""
    return ft.FilledTonalButton(text, icon=icon, on_click=on_click,
                                disabled=disabled, tooltip=tooltip, visible=visible,
                                style=ft.ButtonStyle(
                                    shape=ft.RoundedRectangleBorder(radius=4),
                                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
                                    color=ft.Colors.ON_SURFACE,
                                    side=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT),
                                    text_style=BTN_TEXT_STYLE,
                                ))


def outline_btn(text, icon=None, on_click=None, disabled=False, tooltip=None,
                visible=None):
    """描边按钮（次要操作）"""
    return ft.OutlinedButton(text, icon=icon, on_click=on_click,
                             disabled=disabled, tooltip=tooltip, visible=visible,
                             style=_btn_style())


def text_btn(text, icon=None, on_click=None, disabled=False, tooltip=None,
             visible=None):
    """文字按钮（最弱强调，如取消/辅助链接）"""
    return ft.TextButton(text, icon=icon, on_click=on_click,
                         disabled=disabled, tooltip=tooltip, visible=visible,
                         style=_btn_style())


def danger_btn(text, icon=None, on_click=None, disabled=False, tooltip=None,
               visible=None):
    """危险操作按钮（Fluent 实心红 + 白字, 匹配设计稿"停止"按钮）"""
    return ft.FilledButton(
        text, icon=icon, on_click=on_click, disabled=disabled, tooltip=tooltip,
        visible=visible,
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=4),
            bgcolor=ft.Colors.ERROR,
            color=ft.Colors.ON_ERROR,
            text_style=BTN_TEXT_STYLE,
        ),
    )


# ---------------------------------------------------------------- 日志终端
# Fluent 深底日志条 + 等宽字体 (各级别着色)
LOG_TERMINAL_BG = MORANDI_TERMINAL_BG
LOG_TERMINAL_FONT = FONT_TERMINAL


def log_line_color(line: str):
    """日志行着色（终端风格）"""
    if '[ERROR]' in line:
        return LOG_COLOR_ERROR
    if '[WARN]' in line:
        return LOG_COLOR_WARN
    if '[DEBUG]' in line:
        return LOG_COLOR_DEBUG
    return LOG_COLOR_INFO
