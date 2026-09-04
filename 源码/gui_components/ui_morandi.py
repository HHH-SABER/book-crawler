# -*- coding: utf-8 -*-
"""莫兰迪主题系统：低饱和度柔和配色 + 统一字体规范

莫兰迪配色特点：低饱和度、中亮度、暖调，给人柔和高级的感觉。
适用于小说阅读器类应用，长时间阅读不刺眼。

本版改进：
  1. 字体规范体系：统一字体族 + 六级字号层级 + 四级字重规范,
     所有页签控件一律引用本模块常量, 禁止散落硬编码
  2. 配色丰富化：在原灰粉/灰绿/陶土/灰蓝四主色基础上,
     新增藕荷紫/芥末金/雾霾青/陶土棕四个扩展色, 并为任务状态、
     功能区域、日志级别分配各自独立的莫兰迪色相,
     在保持低饱和的前提下显著提升色彩区分度
"""
import flet as ft

# ====================================================================
# 一、统一字体规范 (所有页签必须引用本节常量, 不得硬编码)
# ====================================================================

# 字体栈：优先系统原生中文字体, 逐级回退
FONT_STACK = 'Noto Sans SC, PingFang SC, Microsoft YaHei, sans-serif'
# 终端/日志等宽字体
FONT_TERMINAL = 'Consolas, monospace'

# ---- 字号层级 (六级, 从大到小) ----
SIZE_TITLE = 17        # 应用标题 / 页签卡片标题
SIZE_SUBTITLE = 14     # 对话框标题 / 分组小标题
SIZE_LABEL = 13        # 输入框 / 下拉框 / 列表主标题
SIZE_BODY = 12         # 正文内容 / 预览区 / 说明文字
SIZE_SMALL = 11        # 辅助文字 / 日志说明
SIZE_TINY = 10         # 进度数值 / 状态微字 / 时间戳

# ---- 字重规范 (四级, 同层级必须一致) ----
WEIGHT_TITLE = ft.FontWeight.BOLD      # 标题层: 加粗
WEIGHT_SUBTITLE = ft.FontWeight.W_600  # 次标题/列表项标题: 半粗
WEIGHT_BODY = ft.FontWeight.NORMAL     # 正文/辅助: 常规
WEIGHT_EMPHASIS = ft.FontWeight.W_500  # 状态标签等强调小字: 中等


def txt(value, size=SIZE_BODY, weight=WEIGHT_BODY, color=None,
        italic=False, opacity=None, selectable=False,
        font_family=None, **kwargs):
    """统一文本工厂: 强制全局字体族 + 规范字号字重, 杜绝散落硬编码。

    除 font_family 显式传入 (如日志区用等宽字体) 外一律用 FONT_STACK。
    kwargs 透传 ft.Text 其余参数 (max_lines / overflow / tooltip 等)。
    """
    return ft.Text(
        value, size=size, weight=weight,
        color=color, italic=italic, opacity=opacity,
        selectable=selectable,
        font_family=font_family or FONT_STACK,
        **kwargs,
    )


# ====================================================================
# 二、莫兰迪色板 (低饱和度、中亮度、暖调)
# ====================================================================

# ---- 主色/语义色: 主题感知别名 ----
# 直接映射到 Flet 语义色槽位 (ft.Colors.*), 由 ColorScheme 按当前 theme_mode 解析:
#   白天 (LIGHT)  → 渲染图风格 (紫/蓝青/琥珀/红, 见 make_morandi_theme)
#   夜间 (DARK)   → 莫兰迪深色主题 (make_morandi_dark_theme), 保持夜间观感不变
MORANDI_PRIMARY = ft.Colors.PRIMARY
MORANDI_SECONDARY = ft.Colors.SECONDARY
MORANDI_TERTIARY = ft.Colors.TERTIARY
MORANDI_ACCENT = ft.Colors.TERTIARY          # 配置/强调区: 琥珀橙
MORANDI_SUCCESS = ft.Colors.SECONDARY        # 成功/完成: 蓝青
MORANDI_ERROR = ft.Colors.ERROR              # 失败/错误: 红
MORANDI_WARNING = ft.Colors.TERTIARY         # 警告: 琥珀
MORANDI_INFO = ft.Colors.SECONDARY           # 信息: 蓝青
MORANDI_RUNNING = ft.Colors.PRIMARY          # 进行中: 紫
MORANDI_STOPPED = ft.Colors.ON_SURFACE_VARIANT
MORANDI_PENDING = ft.Colors.ON_SURFACE_VARIANT

# ---- 表面/文字/边框: 主题感知别名 (旧常量名保持兼容) ----
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

# ---- 扩展色 (主题感知别名, 旧引用兼容) ----
MORANDI_MAUVE = ft.Colors.PRIMARY
MORANDI_GOLD = ft.Colors.TERTIARY
MORANDI_TEAL = ft.Colors.SECONDARY
MORANDI_CLAY = ft.Colors.TERTIARY
MORANDI_LILAC = ft.Colors.ON_SURFACE_VARIANT

# ---- 终端背景 (日志区深底, 深暖灰黑比纯黑柔和) ----
MORANDI_TERMINAL_BG = '#2C2825'

# ---- 日志级别色 (终端深底上可读的低饱和色) ----
LOG_COLOR_INFO = '#D6CDC4'           # 暖浅灰 (默认)
LOG_COLOR_ERROR = '#D49090'          # 柔和珊瑚红
LOG_COLOR_WARN = '#D4B87E'           # 柔和芥末金
LOG_COLOR_DEBUG = '#A89FB0'          # 灰丁香 (调试)


# ====================================================================
# 三、主题生成 (Material3 ColorScheme)
# ====================================================================

def _build_theme(cs_kwargs: dict) -> ft.Theme:
    """由 ColorScheme 属性字典生成 Flet Theme (统一字体族 + 导航/文字按钮字体 + 质感细节)"""
    cs = ft.ColorScheme()
    for k, v in cs_kwargs.items():
        setattr(cs, k, v)

    # 统一正文文字样式 (按钮/对话框内容共用)
    _body_ts = ft.TextStyle(size=SIZE_BODY, weight=WEIGHT_BODY, font_family=FONT_STACK)
    # 统一按钮圆角
    _btn_shape = ft.RoundedRectangleBorder(radius=10)

    # 导航栏标签统一字体规范：未选中常规，选中半粗；强制深色保证浅色底可读
    nav_rail_style = ft.NavigationRailTheme(
        indicator_color=cs_kwargs.get('primary_container', MORANDI_PRIMARY),
        selected_label_text_style=ft.TextStyle(
            size=SIZE_BODY, weight=WEIGHT_SUBTITLE, font_family=FONT_STACK,
            color=MORANDI_ON_SURFACE),
        unselected_label_text_style=ft.TextStyle(
            size=SIZE_BODY, weight=WEIGHT_BODY, font_family=FONT_STACK,
            color=MORANDI_ON_SURFACE),
    )

    # 文字按钮 (如对话框取消/删除): 统一字体 + 圆角
    text_btn_theme = ft.TextButtonTheme(style=ft.ButtonStyle(
        text_style=_body_ts, shape=_btn_shape))

    # 填充按钮 (主操作): 统一字体 + 圆角 + 舒适内边距
    filled_btn_theme = ft.FilledButtonTheme(style=ft.ButtonStyle(
        text_style=_body_ts, shape=_btn_shape,
        padding=ft.Padding.symmetric(horizontal=16, vertical=10)))

    # 描边按钮: 同上
    outline_btn_theme = ft.OutlinedButtonTheme(style=ft.ButtonStyle(
        text_style=_body_ts, shape=_btn_shape,
        padding=ft.Padding.symmetric(horizontal=16, vertical=10)))

    # 图标按钮 (小图标操作): 圆角适中
    icon_btn_theme = ft.IconButtonTheme(style=ft.ButtonStyle(
        shape=ft.RoundedRectangleBorder(radius=8)))

    # 对话框: 大圆角 + 柔和阴影 + 统一字体
    dialog_theme = ft.DialogTheme(
        bgcolor=cs_kwargs.get('surface', MORANDI_SURFACE),
        shape=ft.RoundedRectangleBorder(radius=16),
        elevation=8,
        title_text_style=ft.TextStyle(
            size=SIZE_SUBTITLE, weight=WEIGHT_SUBTITLE, font_family=FONT_STACK),
        content_text_style=_body_ts,
    )

    # 分割线: 用 outline_variant, 比默认更细腻
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
    """白天主题: 渲染图风格 (紫色品牌 + 蓝青次级 + 琥珀强调 + 明亮中性面)"""
    return _build_theme({
        # 品牌紫 (导航/高亮/主按钮)
        'primary': '#7C5CFF',
        'on_primary': '#FFFFFF',
        'primary_container': '#EBE7FF',                  # 淡紫容器
        'on_primary_container': '#3C2F86',
        # 蓝青 (次级/成功/信息)
        'secondary': '#3AA6B9',
        'on_secondary': '#FFFFFF',
        'secondary_container': '#DEF4F8',                # 淡青容器
        'on_secondary_container': '#13505C',
        # 琥珀橙 (强调/警告)
        'tertiary': '#E8A33D',
        'on_tertiary': '#FFFFFF',
        'tertiary_container': '#FCEDDA',                 # 淡橙容器
        'on_tertiary_container': '#67430A',
        # 红 (失败/错误)
        'error': '#E0625F',
        'error_container': '#FCE5E3',
        'on_error': '#FFFFFF',
        'on_error_container': '#7C2220',
        # 明亮中性面 (渲染图 surface 体系)
        'background': '#F8F9FC',                         # 极浅蓝灰白
        'on_background': '#1F2330',
        'surface': '#FFFFFF',                            # 卡片纯白
        'on_surface': '#1F2330',
        'surface_variant': '#ECEFF2',
        'on_surface_variant': '#6B7280',
        'outline': '#C6CCD4',
        'outline_variant': '#DCE1E8',
        'surface_container_low': '#F6F7F9',              # 导航/工具栏底
        'surface_container': '#F1F3F6',                  # 卡片底
        'surface_container_high': '#ECEEF2',
        'surface_container_highest': '#E4E7EC',
    })


def make_morandi_dark_theme() -> ft.Theme:
    """莫兰迪深色主题: 深暖灰底 + 提亮四主色 (低饱和不刺眼)"""
    return _build_theme({
        'primary': '#B8A0A0',                             # 浅灰粉
        'on_primary': '#2C2020',
        'primary_container': '#4A3A3A',                   # 深灰粉容器
        'on_primary_container': '#E8D5D2',
        'secondary': '#9EB8AE',                           # 浅灰绿
        'on_secondary': '#1E2A24',
        'secondary_container': '#38473F',                 # 深灰绿容器
        'on_secondary_container': '#D4E0D6',
        'tertiary': '#D4AA8C',                            # 浅陶土
        'on_tertiary': '#301F14',
        'tertiary_container': '#4C3A2C',                  # 深陶土容器
        'on_tertiary_container': '#EBD9C8',
        'error': '#C08484',
        'error_container': '#4A302E',
        'on_error': '#2C1414',
        'on_error_container': '#EBCFCB',
        'background': '#1E1A17',
        'on_background': '#E0D8D0',
        'surface': '#262220',
        'on_surface': '#E0D8D0',
        'surface_variant': '#3D3530',
        'on_surface_variant': '#A89E95',
        'outline': '#5A5048',
        'outline_variant': '#453D37',
        'surface_container_low': '#2C2825',               # 导航/工具栏底
        'surface_container': '#332E2A',                   # 卡片底
        'surface_container_high': '#3A342F',
        'surface_container_highest': '#453D37',
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
    """莫兰迪风格卡片 (复用 ui_theme.make_card, M3 语义色自动适配主题)"""
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
