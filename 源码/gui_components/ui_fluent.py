# -*- coding: utf-8 -*-
"""ui_fluent — Windows 11 Fluent 设计令牌体系：色板 + 字体 + 字号 + 字重

设计规范来源: 界面设计预览/index.html (Windows 11 Fluent Design Tokens):
  - 日间: #F3F3F3 底 + 纯白卡片 + #0067C0 强调蓝 + 4/8px 小圆角
  - 夜间: #202020 底 + #2B2B2B 卡片 + #4CC2FF 提亮蓝
  - 字体: Segoe UI / 微软雅黑

历史兼容: MORANDI_* 常量名为历代主题遗留, 全部保留 (值已映射到 Fluent 色板);
组件应逐步改用 ui_theme 的语义封装, 避免直接引用色值常量。
"""
import flet as ft

# ====================================================================
# 一、统一字体规范 (Fluent: Segoe UI 优先, 中文回退微软雅黑)
# ====================================================================

FONT_STACK = '"Segoe UI", "Microsoft YaHei", "微软雅黑", system-ui, "Noto Sans SC", sans-serif'
# 终端/日志等宽字体 (Fluent: Cascadia Code 优先)
FONT_TERMINAL = '"Cascadia Code", "Cascadia Mono", Consolas, "Courier New", monospace'

# ---- 字号层级 (匹配 --fs-*) ----
SIZE_TITLE = 20        # 页面大标题 (--fs-h1)
SIZE_SUBTITLE = 17     # 卡片标题 / 对话框标题 (--fs-h2)
SIZE_LABEL = 15        # 输入框 / 列表主标题 (--fs-h3)
SIZE_BODY = 14         # 正文 (--fs-body)
SIZE_SMALL = 13        # 辅助文字 (--fs-small)
SIZE_TINY = 12         # 时间戳 / 状态微字 (--fs-caption)

# ---- 字重规范 ----
WEIGHT_TITLE = ft.FontWeight.BOLD
WEIGHT_SUBTITLE = ft.FontWeight.W_600
WEIGHT_BODY = ft.FontWeight.NORMAL
WEIGHT_EMPHASIS = ft.FontWeight.W_500


def txt(value, size=SIZE_BODY, weight=WEIGHT_BODY, color=None,
        italic=False, opacity=None, selectable=False,
        font_family=None, **kwargs):
    """统一文本工厂: 强制全局字体族 + 规范字号字重, 杜绝散落硬编码。"""
    text_kwargs = dict(
        value=value, size=size, weight=weight,
        color=color, italic=italic,
        selectable=selectable,
        font_family=font_family or FONT_STACK,
    )
    if opacity is not None:
        text_kwargs['opacity'] = opacity
    text_kwargs.update(kwargs)
    return ft.Text(**text_kwargs)


# ====================================================================
# 二、Fluent 色板 (语义色别名, 全部映射 M3 槽位自动适配深浅主题)
# ====================================================================

MORANDI_PRIMARY = ft.Colors.PRIMARY
MORANDI_SECONDARY = ft.Colors.SECONDARY
MORANDI_TERTIARY = ft.Colors.TERTIARY
MORANDI_ACCENT = ft.Colors.PRIMARY
MORANDI_SUCCESS = ft.Colors.SECONDARY
MORANDI_ERROR = ft.Colors.ERROR
MORANDI_WARNING = ft.Colors.TERTIARY
MORANDI_INFO = ft.Colors.PRIMARY
MORANDI_RUNNING = ft.Colors.PRIMARY
MORANDI_STOPPED = ft.Colors.ON_SURFACE_VARIANT
MORANDI_PENDING = ft.Colors.ON_SURFACE_VARIANT

# ---- 侧边栏专用色 (匹配 --bg-sidebar: 日间 #F1F1F1 / 夜间 #171717) ----
MORANDI_SIDEBAR_BG = ft.Colors.SURFACE_CONTAINER_LOW
MORANDI_SIDEBAR_HOVER = ft.Colors.SURFACE_CONTAINER_HIGH
MORANDI_SIDEBAR_ACTIVE = ft.Colors.PRIMARY_CONTAINER

# ---- 表面/文字/边框 (主题感知别名) ----
MORANDI_BACKGROUND = ft.Colors.SURFACE
MORANDI_SURFACE = ft.Colors.SURFACE
MORANDI_SURFACE_CONTAINER = ft.Colors.SURFACE_CONTAINER
MORANDI_SURFACE_CONTAINER_HIGH = ft.Colors.SURFACE_CONTAINER_HIGH
MORANDI_SURFACE_CONTAINER_HIGHEST = ft.Colors.SURFACE_CONTAINER_HIGHEST
MORANDI_ON_PRIMARY = ft.Colors.ON_PRIMARY
MORANDI_ON_SECONDARY = ft.Colors.ON_SECONDARY
MORANDI_ON_SURFACE = ft.Colors.ON_SURFACE
MORANDI_ON_SURFACE_VARIANT = ft.Colors.ON_SURFACE_VARIANT
MORANDI_OUTLINE = ft.Colors.OUTLINE
MORANDI_OUTLINE_VARIANT = ft.Colors.OUTLINE_VARIANT

# ---- 扩展色 (旧引用兼容) ----
MORANDI_MAUVE = ft.Colors.PRIMARY
MORANDI_GOLD = ft.Colors.TERTIARY
MORANDI_TEAL = ft.Colors.PRIMARY
MORANDI_CLAY = ft.Colors.TERTIARY
MORANDI_LILAC = ft.Colors.ON_SURFACE_VARIANT

# ---- 终端背景 (日志条深底, 跨主题保持) ----
MORANDI_TERMINAL_BG = '#1F1F1F'

# ---- 日志级别色 (深底上可读, Fluent 语义) ----
LOG_COLOR_INFO = '#F3F3F3'
LOG_COLOR_ERROR = '#FF99A4'          # 浅红 (深底可读)
LOG_COLOR_WARN = '#FCE100'           # Fluent 黄
LOG_COLOR_DEBUG = '#9D9D9D'


# ====================================================================
# 三、主题生成 (Material3 ColorScheme — Windows 11 Fluent)
# ====================================================================

def _build_theme(cs_kwargs: dict) -> ft.Theme:
    """由 ColorScheme 属性字典生成 Flet Theme (Fluent 控件圆角 4px)"""
    cs = ft.ColorScheme()
    for k, v in cs_kwargs.items():
        setattr(cs, k, v)

    _body_ts = ft.TextStyle(size=SIZE_BODY, weight=WEIGHT_BODY, font_family=FONT_STACK)
    # Fluent 控件圆角: 按钮/输入 4px (--radius-md)
    _btn_shape = ft.RoundedRectangleBorder(radius=4)

    nav_rail_style = ft.NavigationRailTheme(
        indicator_color=cs_kwargs.get('primary_container', MORANDI_PRIMARY),
        selected_label_text_style=ft.TextStyle(
            size=SIZE_BODY, weight=WEIGHT_SUBTITLE, font_family=FONT_STACK,
            color=MORANDI_ON_SURFACE),
        unselected_label_text_style=ft.TextStyle(
            size=SIZE_BODY, weight=WEIGHT_BODY, font_family=FONT_STACK,
            color=MORANDI_ON_SURFACE),
    )

    text_btn_theme = ft.TextButtonTheme(style=ft.ButtonStyle(
        text_style=_body_ts, shape=_btn_shape))

    filled_btn_theme = ft.FilledButtonTheme(style=ft.ButtonStyle(
        text_style=_body_ts, shape=_btn_shape,
        padding=ft.Padding.symmetric(horizontal=16, vertical=10)))

    outline_btn_theme = ft.OutlinedButtonTheme(style=ft.ButtonStyle(
        text_style=_body_ts, shape=_btn_shape,
        padding=ft.Padding.symmetric(horizontal=16, vertical=10)))

    icon_btn_theme = ft.IconButtonTheme(style=ft.ButtonStyle(
        shape=ft.RoundedRectangleBorder(radius=4)))

    dialog_theme = ft.DialogTheme(
        bgcolor=cs_kwargs.get('surface', MORANDI_SURFACE),
        shape=ft.RoundedRectangleBorder(radius=8),
        elevation=8,
        title_text_style=ft.TextStyle(
            size=SIZE_SUBTITLE, weight=WEIGHT_SUBTITLE, font_family=FONT_STACK),
        content_text_style=_body_ts,
    )

    divider_theme = ft.DividerTheme(
        color=cs_kwargs.get('outline_variant', MORANDI_OUTLINE_VARIANT))

    return ft.Theme(
        color_scheme=cs,
        use_material3=True,
        font_family=FONT_STACK,
        navigation_rail_theme=nav_rail_style,
        text_button_theme=text_btn_theme,
        filled_button_theme=filled_btn_theme,
        outlined_button_theme=outline_btn_theme,
        icon_button_theme=icon_btn_theme,
        dialog_theme=dialog_theme,
        divider_theme=divider_theme,
    )


def make_morandi_theme() -> ft.Theme:
    """日间主题: Windows 11 Fluent — #F3F3F3 底 + 纯白卡片 + #0067C0 强调蓝

    函数名历史兼容 (原莫兰迪主题入口), 现返回 Fluent 日间主题。
    """
    return _build_theme({
        # Fluent accent-blue
        'primary': '#0067C0',
        'on_primary': '#FFFFFF',
        'primary_container': '#E7F1FA',                  # accent-blue-light
        'on_primary_container': '#00549B',
        # accent-green
        'secondary': '#0F7B0F',
        'on_secondary': '#FFFFFF',
        'secondary_container': '#DFF6DD',
        'on_secondary_container': '#0B5A0B',
        # accent-orange
        'tertiary': '#9D5D00',
        'on_tertiary': '#FFFFFF',
        'tertiary_container': '#FFF4CE',
        'on_tertiary_container': '#6D4703',
        # accent-red
        'error': '#C42B1C',
        'error_container': '#FDE7E9',
        'on_error': '#FFFFFF',
        'on_error_container': '#8F1A0E',
        # Fluent 中性面
        'background': '#F3F3F3',
        'on_background': '#1B1B1B',
        'surface': '#FFFFFF',
        'on_surface': '#1B1B1B',
        'surface_variant': '#F5F5F5',
        'on_surface_variant': '#5C5C5C',
        'outline': '#8A8A8A',
        'outline_variant': 'rgba(0,0,0,0.08)',
        'surface_container_low': '#F1F1F1',              # 侧边栏
        'surface_container': '#F5F5F5',
        'surface_container_high': '#E7E7E7',             # hover
        'surface_container_highest': '#DEDEDE',          # active
    })


def make_morandi_dark_theme() -> ft.Theme:
    """夜间主题: Windows 11 Fluent Dark — #202020 底 + #2B2B2B 卡片 + 提亮蓝"""
    return _build_theme({
        'primary': '#4CC2FF',                            # Fluent dark accent
        'on_primary': '#003A5C',
        'primary_container': '#1D3A4F',
        'on_primary_container': '#9CD8F7',
        'secondary': '#6CCB5F',
        'on_secondary': '#0B2E08',
        'secondary_container': '#1E3A1A',
        'on_secondary_container': '#A5E4A0',
        'tertiary': '#FCE100',
        'on_tertiary': '#2E2A00',
        'tertiary_container': '#3B3700',
        'on_tertiary_container': '#F5EE8C',
        'error': '#FF99A4',
        'error_container': '#5C1A22',
        'on_error': '#FFFFFF',
        'on_error_container': '#FFB3BC',
        # Fluent Dark 中性面
        'background': '#202020',
        'on_background': '#FFFFFF',
        'surface': '#2B2B2B',                            # 卡片
        'on_surface': '#FFFFFF',
        'surface_variant': '#323232',
        'on_surface_variant': '#CACACA',
        'outline': '#9D9D9D',
        'outline_variant': 'rgba(255,255,255,0.08)',
        'surface_container_low': '#171717',              # 侧边栏
        'surface_container': '#1F1F1F',
        'surface_container_high': '#2D2D2D',
        'surface_container_highest': '#383838',
    })


# ====================================================================
# 四、工具函数 (兼容旧引用)
# ====================================================================

def get_font_stack() -> str:
    """获取统一字体栈"""
    return FONT_STACK


def get_terminal_font() -> str:
    """获取终端字体"""
    return FONT_TERMINAL


def get_terminal_bg() -> str:
    """获取终端背景色"""
    return MORANDI_TERMINAL_BG


def make_morandi_card(content, **kwargs) -> ft.Container:
    """卡片 (复用 ui_theme.make_card)"""
    from .ui_theme import make_card as _make_card
    return _make_card(content, **kwargs)


def open_dialog(page, ctrl):
    """打开对话框/SnackBar (flet 0.86 兼容: Page 无 .open, 用 show_dialog)"""
    try:
        page.show_dialog(ctrl)
    except Exception:
        try:
            page.overlay.append(ctrl)
            ctrl.open = True
            page.update()
        except Exception:
            pass


def close_dialog(page, ctrl):
    """关闭对话框 (flet 0.86 兼容: Page 无 .close)"""
    try:
        ctrl.open = False
        page.update()
    except Exception:
        pass
