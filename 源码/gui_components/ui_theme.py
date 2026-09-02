# -*- coding: utf-8 -*-
"""UI 主题系统：卡片工厂 + 状态标签 + 按钮统一样式

双主题适配原则：颜色优先使用 Flet Material3 语义色
（SURFACE_CONTAINER_* / PRIMARY / ERROR_CONTAINER 等）自动适配深浅主题；
需要跨主题保持辨识度的状态色/日志色则使用 ui_morandi 定义的莫兰迪色相。
"""
import flet as ft

# 统一字体与字重规范 (来自 ui_morandi, 本模块所有文本必须遵守)
from .ui_morandi import (
    FONT_STACK, FONT_TERMINAL, SIZE_BODY, SIZE_TINY, WEIGHT_BODY,
    WEIGHT_EMPHASIS, MORANDI_TERMINAL_BG, LOG_COLOR_INFO,
    LOG_COLOR_ERROR, LOG_COLOR_WARN, LOG_COLOR_DEBUG,
)

# 统一按钮文字样式 (所有按钮工厂函数必须引用, 保证字号/字重/字体族一致)
BTN_TEXT_STYLE = ft.TextStyle(
    size=SIZE_BODY, weight=WEIGHT_BODY, font_family=FONT_STACK)

# ---------------------------------------------------------------- 卡片
CARD_RADIUS = 14
CARD_PADDING = 12

# 卡片双层阴影: 外层大模糊模拟环境光, 内层贴边模拟接触阴影 (更自然的悬浮感)
_CARD_SHADOW = [
    ft.BoxShadow(
        blur_radius=18,
        spread_radius=-2,
        offset=ft.Offset(0, 4),
        color=ft.Colors.with_opacity(0.06, ft.Colors.BLACK),
    ),
    ft.BoxShadow(
        blur_radius=4,
        spread_radius=0,
        offset=ft.Offset(0, 1),
        color=ft.Colors.with_opacity(0.08, ft.Colors.BLACK),
    ),
]


def make_card(content, padding=CARD_PADDING, radius=CARD_RADIUS,
              expand=False, width=None, bgcolor=None, scroll=None,
              visible=None, border=None):
    """统一卡片：M3 语义色表面 + 双层柔和阴影 + 大圆角"""
    return ft.Container(
        content=content,
        width=width,
        expand=expand,
        padding=padding,
        bgcolor=bgcolor or ft.Colors.SURFACE_CONTAINER_HIGHEST,
        border_radius=radius,
        border=border,
        visible=visible,
        shadow=_CARD_SHADOW,
    )


# ---------------------------------------------------------------- 状态标签
# 任务状态 -> (前景色, 背景色)
# 采用 ColorScheme 容器色 (主题感知): 白天=渲染图风格 (淡紫/淡青/淡红等),
# 夜间=莫兰迪深色主题容器色 (保持夜间观感不变)
STATUS_STYLES = {
    'running':   (ft.Colors.ON_PRIMARY_CONTAINER, ft.Colors.PRIMARY_CONTAINER),   # 紫: 进行中
    'completed': (ft.Colors.ON_SECONDARY_CONTAINER, ft.Colors.SECONDARY_CONTAINER),  # 蓝青: 完成
    'failed':    (ft.Colors.ON_ERROR_CONTAINER, ft.Colors.ERROR_CONTAINER),       # 红: 失败
    'pending':   (ft.Colors.ON_SURFACE_VARIANT, ft.Colors.SURFACE_CONTAINER),     # 灰: 等待中
    'stopped':   (ft.Colors.ON_SURFACE_VARIANT, ft.Colors.SURFACE_CONTAINER_HIGH),  # 灰: 已停止
}

STATUS_LABELS = {
    'running': '进行中',
    'completed': '完成',
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
    """统一按钮基础样式：圆角 + 规范字体"""
    return ft.ButtonStyle(
        shape=ft.RoundedRectangleBorder(radius=10),
        text_style=BTN_TEXT_STYLE,
    )


def filled_btn(text, icon=None, on_click=None, disabled=False, tooltip=None,
               visible=None):
    """填充按钮（主色派生，无手写 bgcolor）"""
    return ft.FilledButton(text, icon=icon, on_click=on_click,
                           disabled=disabled, tooltip=tooltip, visible=visible,
                           style=_btn_style())


def tonal_btn(text, icon=None, on_click=None, disabled=False, tooltip=None,
              visible=None):
    """次级填充按钮（次要容器色）"""
    return ft.FilledTonalButton(text, icon=icon, on_click=on_click,
                                disabled=disabled, tooltip=tooltip, visible=visible,
                                style=_btn_style())


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
    """危险操作按钮（错误色背景）"""
    return ft.FilledButton(
        text, icon=icon, on_click=on_click, disabled=disabled, tooltip=tooltip,
        visible=visible,
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=10),
            bgcolor=ft.Colors.ERROR_CONTAINER,
            color=ft.Colors.ON_ERROR_CONTAINER,
            text_style=BTN_TEXT_STYLE,
        ),
    )


# ---------------------------------------------------------------- 日志终端
# 莫兰迪深暖灰底 + 等宽字体 (深底上各级别用低饱和莫兰迪色着色)
LOG_TERMINAL_BG = MORANDI_TERMINAL_BG
LOG_TERMINAL_FONT = FONT_TERMINAL


def log_line_color(line: str):
    """日志行着色（终端风格, 莫兰迪低饱和色）"""
    if '[ERROR]' in line:
        return LOG_COLOR_ERROR
    if '[WARN]' in line:
        return LOG_COLOR_WARN
    if '[DEBUG]' in line:
        return LOG_COLOR_DEBUG
    return LOG_COLOR_INFO
