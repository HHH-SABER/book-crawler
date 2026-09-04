# -*- coding: utf-8 -*-
"""苹果风格主题系统：Apple Human Interface Guidelines 配色 + 统一字体规范

设计原则:
  1. 日间模式: 洁净明亮的浅灰白底 + 系统蓝主色 + 高饱和强调色
  2. 夜间模式: 纯黑底 + 提亮强调色 (OLED 友好, 对比度更高)
  3. 语义色映射到 Flet Material3 ColorScheme 槽位, 自动适配深浅主题
  4. 字体栈优先系统原生中文字体, 逐级回退

本文件替换原莫兰迪主题 (ui_morandi.py), 保持所有常量名/函数名兼容,
其他 GUI 组件直接 import 即可生效, 无需修改引用。
"""
import flet as ft

# ====================================================================
# 一、统一字体规范 (所有页签必须引用本节常量, 不得硬编码)
# ====================================================================

# 字体栈：优先系统原生中文字体, 逐级回退
FONT_STACK = '-apple-system, BlinkMacSystemFont, "SF Pro Display", "PingFang SC", "Microsoft YaHei", "Noto Sans SC", sans-serif'
# 终端/日志等宽字体
FONT_TERMINAL = '"SF Mono", Consolas, "JetBrains Mono", monospace'

# ---- 字号层级 (六级, 从大到小) ----
SIZE_TITLE = 22        # 应用标题 / 页签卡片标题
SIZE_SUBTITLE = 17     # 对话框标题 / 分组小标题
SIZE_LABEL = 15        # 输入框 / 下拉框 / 列表主标题
SIZE_BODY = 14         # 正文内容 / 预览区 / 说明文字
SIZE_SMALL = 13        # 辅助文字 / 日志说明
SIZE_TINY = 12         # 进度数值 / 状态微字 / 时间戳

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
    # 只在有值时传 opacity, 避免 flet 校验报错
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
# 二、苹果风格色板 (语义色别名)
# ====================================================================

# ---- 主色/语义色: 主题感知别名 ----
# 直接映射到 Flet 语义色槽位 (ft.Colors.*), 由 ColorScheme 按当前 theme_mode 解析:
#   白天 (LIGHT)  → 洁净明亮的浅灰白底 + 系统蓝主色
#   夜间 (DARK)   → 纯黑底 + 提亮强调色
MORANDI_PRIMARY = ft.Colors.PRIMARY
MORANDI_SECONDARY = ft.Colors.SECONDARY
MORANDI_TERTIARY = ft.Colors.TERTIARY
MORANDI_ACCENT = ft.Colors.TERTIARY          # 配置/强调区: 橙
MORANDI_SUCCESS = ft.Colors.SECONDARY        # 成功/完成: 绿
MORANDI_ERROR = ft.Colors.ERROR              # 失败/错误: 红
MORANDI_WARNING = ft.Colors.TERTIARY         # 警告: 橙
MORANDI_INFO = ft.Colors.SECONDARY           # 信息: 绿
MORANDI_RUNNING = ft.Colors.PRIMARY          # 进行中: 蓝
MORANDI_STOPPED = ft.Colors.ON_SURFACE_VARIANT
MORANDI_PENDING = ft.Colors.ON_SURFACE_VARIANT

# ---- 侧边栏专用色 (精确匹配 HTML 预览) ----
# 日间: #F0F0F3, 夜间: #161617
MORANDI_SIDEBAR_BG = ft.Colors.SURFACE_CONTAINER_LOW
# 侧边栏 hover: 日间 #E5E5EA, 夜间 #2C2C2E
MORANDI_SIDEBAR_HOVER = ft.Colors.SURFACE_CONTAINER_HIGH
# 侧边栏选中: 日间 #D1D1D6, 夜间 #3A3A3C
MORANDI_SIDEBAR_ACTIVE = ft.Colors.SURFACE_CONTAINER_HIGHEST

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

# ---- 终端背景 (日志区深底) ----
MORANDI_TERMINAL_BG = '#1C1C1E'

# ---- 日志级别色 (终端深底上可读) ----
LOG_COLOR_INFO = '#F5F5F7'           # 浅灰白 (默认)
LOG_COLOR_ERROR = '#FF453A'          # 系统红
LOG_COLOR_WARN = '#FFD60A'           # 系统黄
LOG_COLOR_DEBUG = '#8E8E93'          # 系统灰 (调试)


# ====================================================================
# 三、主题生成 (Material3 ColorScheme — 苹果风格)
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

    # 导航栏标签统一字体规范
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

    # 分割线: 用 outline_variant
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
    """日间主题: 苹果风格 — 洁净浅灰白底 + 系统蓝主色 + 绿/橙/红强调色

    替换原莫兰迪日间主题 (渲染图风格), 保持函数名兼容。
    """
    return _build_theme({
        # 系统蓝 (主按钮 / 高亮 / 进行中)
        'primary': '#007AFF',
        'on_primary': '#FFFFFF',
        'primary_container': '#E8F1FF',                  # 淡蓝容器
        'on_primary_container': '#0040A0',
        # 系统绿 (成功 / 完成 / 质检通过)
        'secondary': '#34C759',
        'on_secondary': '#FFFFFF',
        'secondary_container': '#E8F9ED',                # 淡绿容器
        'on_secondary_container': '#0B6E25',
        # 系统橙 (警告 / 强调 / 配置区)
        'tertiary': '#FF9500',
        'on_tertiary': '#FFFFFF',
        'tertiary_container': '#FFF4E5',                 # 淡橙容器
        'on_tertiary_container': '#7A3D00',
        # 系统红 (失败 / 错误)
        'error': '#FF3B30',
        'error_container': '#FFE5E3',
        'on_error': '#FFFFFF',
        'on_error_container': '#B3261E',
        # 明亮中性面 (苹果风格: 浅灰白背景 + 纯白卡片)
        'background': '#F5F5F7',                         # 系统灰6组背景
        'on_background': '#1D1D1F',                      # 近乎纯黑文字
        'surface': '#FFFFFF',                            # 卡片纯白
        'on_surface': '#1D1D1F',
        'surface_variant': '#E5E5EA',
        'on_surface_variant': '#6E6E73',                 # 系统灰
        'outline': '#C6CCD4',
        'outline_variant': '#E5E5EA',                    # 细分隔线
        'surface_container_low': '#F0F0F3',              # 侧边栏背景 (匹配 --bg-sidebar)
        'surface_container': '#F2F2F7',                  # 标准容器
        'surface_container_high': '#E5E5EA',             # 高强调容器
        'surface_container_highest': '#D1D1D6',          # 最高强调容器
    })


def make_morandi_dark_theme() -> ft.Theme:
    """夜间主题: 苹果风格 — 纯黑底 + 高饱和强调色 (OLED 友好)

    替换原莫兰迪深色主题, 保持函数名兼容。
    """
    return _build_theme({
        'primary': '#0A84FF',                             # 亮蓝
        'on_primary': '#FFFFFF',
        'primary_container': '#1C2A44',                   # 深蓝灰容器
        'on_primary_container': '#9EC8FF',
        'secondary': '#30D158',                           # 亮绿
        'on_secondary': '#FFFFFF',
        'secondary_container': '#1C3B25',                 # 深绿容器
        'on_secondary_container': '#A0E5B0',
        'tertiary': '#FF9F0A',                            # 亮橙
        'on_tertiary': '#FFFFFF',
        'tertiary_container': '#3D2A0E',                  # 深橙容器
        'on_tertiary_container': '#FFD7A0',
        'error': '#FF453A',
        'error_container': '#3D1C1A',
        'on_error': '#FFFFFF',
        'on_error_container': '#FFB4AF',
        'background': '#000000',                          # 纯黑背景
        'on_background': '#F5F5F7',
        'surface': '#1C1C1E',                             # 深灰卡片
        'on_surface': '#F5F5F7',
        'surface_variant': '#2C2C2E',
        'on_surface_variant': '#8E8E93',                  # 系统灰
        'outline': '#48484A',
        'outline_variant': '#38383A',
        'surface_container_low': '#161617',               # 侧边栏背景 (匹配 --bg-sidebar dark)
        'surface_container': '#1C1C1E',                   # 标准容器
        'surface_container_high': '#2C2C2E',              # 高强调容器
        'surface_container_highest': '#3A3A3C',           # 最高强调容器
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
    """卡片 (复用 ui_theme.make_card, M3 语义色自动适配主题)"""
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
