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

# ---- 四个主色 ----
MORANDI_PRIMARY = '#A88E8E'          # 灰粉 Dusty Rose (抓取区主色)
MORANDI_PRIMARY_LIGHT = '#C4A9A9'
MORANDI_PRIMARY_DARK = '#8C7A7A'
MORANDI_SECONDARY = '#8EA89E'        # 灰绿 Sage (预览区主色)
MORANDI_SECONDARY_LIGHT = '#A9B8A8'
MORANDI_SECONDARY_DARK = '#7A8C7A'
MORANDI_TERTIARY = '#C49A7C'         # 陶土 Terracotta (日志区主色)
MORANDI_TERTIARY_LIGHT = '#D4B8A9'
MORANDI_TERTIARY_DARK = '#A97A6B'
MORANDI_ACCENT = '#7C9CA8'           # 灰蓝 Dusty Blue (配置区主色)

# ---- 扩展色 (丰富化: 保持同档低饱和, 增加色相多样性) ----
MORANDI_MAUVE = '#9E8AA0'            # 藕荷紫 (已停止状态 / 点缀)
MORANDI_GOLD = '#B3A26E'             # 芥末金 (警告 / 强调点缀)
MORANDI_TEAL = '#7FA3A0'             # 雾霾青 (信息 / 链接感)
MORANDI_CLAY = '#A98467'             # 陶土棕 (辅助暖色)
MORANDI_LILAC = '#A9A0B8'            # 灰丁香紫 (调试级日志)

# ---- 语义状态色 (各状态色相独立, 一眼可辨) ----
MORANDI_SUCCESS = '#6B8E6B'          # 低饱和绿: 完成/成功
MORANDI_ERROR = '#A86B6B'            # 低饱和红: 失败/错误
MORANDI_WARNING = '#B3A26E'          # 芥末金: 警告
MORANDI_INFO = '#7C9CA8'             # 灰蓝: 信息
MORANDI_RUNNING = '#7C9CA8'          # 灰蓝: 进行中
MORANDI_STOPPED = '#9E8AA0'          # 藕荷紫: 已停止
MORANDI_PENDING = '#A09488'          # 暖沙灰: 等待中

# ---- 表面色 (浅暖灰层级, 浅色主题) ----
MORANDI_BACKGROUND = '#FAF7F4'               # 极浅暖白 (页面底)
MORANDI_SURFACE = '#F8F4F0'                  # 暖白 (卡片)
MORANDI_SURFACE_CONTAINER = '#F0EBE5'        # 浅暖灰 (次级容器)
MORANDI_SURFACE_CONTAINER_HIGH = '#E8E0D8'   # 暖灰 (输入框底)
MORANDI_SURFACE_CONTAINER_HIGHEST = '#E0D8D0'

# ---- 文字色 ----
MORANDI_ON_PRIMARY = '#FFFFFF'
MORANDI_ON_SECONDARY = '#FFFFFF'
MORANDI_ON_SURFACE = '#3D3530'               # 深暖灰 (非纯黑)
MORANDI_ON_SURFACE_VARIANT = '#6B5E55'       # 中暖灰

# ---- 边框/分割线 ----
MORANDI_OUTLINE = '#D8D0C8'
MORANDI_OUTLINE_VARIANT = '#C0B8B0'

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
    """莫兰迪浅色主题: 暖白底 + 四主色容器分区"""
    return _build_theme({
        'primary': MORANDI_PRIMARY,
        'on_primary': MORANDI_ON_PRIMARY,
        'primary_container': '#EAD9D6',                  # 淡灰粉容器
        'on_primary_container': '#5A4442',
        'secondary': MORANDI_SECONDARY,
        'on_secondary': MORANDI_ON_SECONDARY,
        'secondary_container': '#DDE6DE',                # 淡灰绿容器
        'on_secondary_container': '#3D4F45',
        'tertiary': MORANDI_TERTIARY,
        'on_tertiary': MORANDI_ON_PRIMARY,
        'tertiary_container': '#EFDFD0',                 # 淡陶土容器
        'on_tertiary_container': '#5C4634',
        'error': MORANDI_ERROR,
        'error_container': '#EAD5D2',
        'on_error': MORANDI_ON_PRIMARY,
        'on_error_container': '#6E4040',
        'background': MORANDI_BACKGROUND,
        'on_background': MORANDI_ON_SURFACE,
        'surface': MORANDI_SURFACE,
        'on_surface': MORANDI_ON_SURFACE,
        'surface_variant': MORANDI_SURFACE_CONTAINER,
        'on_surface_variant': MORANDI_ON_SURFACE_VARIANT,
        'outline': MORANDI_OUTLINE,
        'outline_variant': MORANDI_OUTLINE_VARIANT,
        'surface_container_low': '#F5F1EC',               # 导航/工具栏底
        'surface_container': MORANDI_SURFACE_CONTAINER,   # 卡片底
        'surface_container_high': MORANDI_SURFACE_CONTAINER_HIGH,
        'surface_container_highest': MORANDI_SURFACE_CONTAINER_HIGHEST,
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
