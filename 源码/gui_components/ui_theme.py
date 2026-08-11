# -*- coding: utf-8 -*-
"""UI 主题系统：卡片工厂 + 状态标签 + 按钮统一样式

双主题适配原则：所有颜色使用 Flet Material3 语义色
（SURFACE_CONTAINER_* / PRIMARY / ERROR_CONTAINER 等），
深浅主题下自动适配，不写死浅色专用色值。
"""
import flet as ft

# ---------------------------------------------------------------- 卡片
CARD_RADIUS = 12
CARD_PADDING = 12


def make_card(content, padding=CARD_PADDING, radius=CARD_RADIUS,
              expand=False, width=None, bgcolor=None, scroll=None,
              visible=None):
    """统一卡片：M3 语义色表面 + 柔和阴影 + 大圆角"""
    return ft.Container(
        content=content,
        width=width,
        expand=expand,
        padding=padding,
        bgcolor=bgcolor or ft.Colors.SURFACE_CONTAINER_HIGHEST,
        border_radius=radius,
        visible=visible,
        shadow=ft.BoxShadow(
            blur_radius=10,
            spread_radius=0,
            offset=ft.Offset(0, 2),
            color=ft.Colors.with_opacity(0.08, ft.Colors.BLACK),
        ),
    )


# ---------------------------------------------------------------- 状态标签
# 任务状态 -> (前景色, 背景色)  均为 M3 语义色
STATUS_STYLES = {
    'running':   (ft.Colors.ON_PRIMARY, ft.Colors.PRIMARY),
    'completed': (ft.Colors.ON_PRIMARY_CONTAINER, ft.Colors.PRIMARY_CONTAINER),
    'failed':    (ft.Colors.ON_ERROR_CONTAINER, ft.Colors.ERROR_CONTAINER),
    'pending':   (ft.Colors.ON_SURFACE_VARIANT, ft.Colors.SURFACE_CONTAINER_HIGH),
    'stopped':   (ft.Colors.ON_SURFACE_VARIANT, ft.Colors.SURFACE_CONTAINER_HIGH),
}

STATUS_LABELS = {
    'running': '进行中',
    'completed': '完成',
    'failed': '失败',
    'pending': '等待中',
    'stopped': '已停止',
}


def status_chip(status: str) -> ft.Control:
    """状态胶囊标签（圆角背景 + 加粗文字）"""
    fg, bg = STATUS_STYLES.get(status, STATUS_STYLES['pending'])
    return ft.Container(
        content=ft.Text(STATUS_LABELS.get(status, status), size=9,
                        weight=ft.FontWeight.BOLD, color=fg),
        padding=ft.Padding.symmetric(horizontal=8, vertical=2),
        bgcolor=bg,
        border_radius=10,
    )


def status_color(status: str):
    """状态主色（进度环/圆点用）"""
    return STATUS_STYLES.get(status, STATUS_STYLES['pending'])[1]


# ---------------------------------------------------------------- 按钮
def _btn_style():
    return ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10))


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
        ),
    )


# ---------------------------------------------------------------- 日志终端
LOG_TERMINAL_BG = ft.Colors.BLACK87          # 终端深底
LOG_TERMINAL_FONT = "Consolas"               # 等宽字体


def log_line_color(line: str):
    """日志行着色（终端风格）"""
    if '[ERROR]' in line:
        return ft.Colors.RED_300
    if '[WARN]' in line:
        return ft.Colors.AMBER_300
    if '[DEBUG]' in line:
        return ft.Colors.GREY_400
    return ft.Colors.GREY_200
