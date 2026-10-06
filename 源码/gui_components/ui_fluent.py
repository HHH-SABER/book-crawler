# -*- coding: utf-8 -*-
"""ui_fluent — 暖色设计系统: 字体 + 字号字重 + 主题生成 (M3 ColorScheme 桥)

设计规范来源: 界面设计预览/index.html (暖色三层令牌体系)
  - 日间: #F5F5F5 底 + 纯白卡片 + #D9781A 品牌橙 + #AD5710 主按钮
  - 夜间: #202020 底 + #2B2B2B 卡片 + #171717 侧栏 (比卡片更暗)
  - 字体: Segoe UI / 微软雅黑

======================================================================
职责边界 (与 ui_tokens 的分工 — 下一轮页面改造必读)
======================================================================
  ui_tokens  基础色板字典 + 取色() + 主题状态 + 尺寸圆角阴影等令牌
             —— 装不进 M3 槽位的颜色 (accent-fg / 各 status /
             focus-ring / 终端 / 远控 / GitHub) 全部走它
  ui_fluent  本文件。把令牌**映射进 M3 ColorScheme**, 让 Flet 原生
             控件 (FilledButton / Checkbox / Dialog …) 自动拿到暖色,
             并保留 FONT_STACK / txt() / open_dialog() 等公共 API

历史兼容: MORANDI_* 常量名为历代主题遗留, 全部保留 —— 但**值的语义
变了**: 以前是 ft.Colors.* M3 别名 (自动适配), 现在绝大多数改成
ui_tokens.取色() 的字面量 (跟随全局主题状态重算)。这是刻意的:
设计稿的 6 组状态色/焦点环/终端色在 M3 里没有对应槽位。
仍保留 M3 别名的那些 (MORANDI_ON_SURFACE 等) 依旧自动适配深浅。
"""
import dataclasses

import dataclasses

import flet as ft
from . import ui_tokens
from .ui_tokens import 取色, 状态色, 登记重刷, 设置主题, is_dark, 主题状态
try:
    import 日志 as _app_log          # 批2B: 统一留痕通道 (容错导入, 同 input_bar 桥模式)
except Exception:
    _app_log = None


def _dbg(source: str, message: str):
    """裸 except 吞异常留痕 (DEBUG 级: 只落盘不 console 镜像, 避免刷屏)"""
    if _app_log is not None:
        try:
            _app_log.debug(source, message)
        except Exception:
            pass  # 刻意静默: try 块本身在写日志, 再加日志会递归 (日志链路兜底)


# ====================================================================
# 一、统一字体规范 (Segoe UI 优先, 中文回退微软雅黑)
# ====================================================================

FONT_STACK = '"Segoe UI", "Microsoft YaHei", "微软雅黑", system-ui, "Noto Sans SC", sans-serif'
# 终端/日志等宽字体 (Cascadia Code 优先)
FONT_TERMINAL = '"Cascadia Code", "Cascadia Mono", Consolas, "Courier New", monospace'

# ---- 字号层级 ----
# 取值来自 ui_tokens (设计稿 --fs-* 单一真值源)。
# 注意: 这里刻意比设计稿少一档 —— SIZE_TITLE 沿用历史值 20 (页面大标题),
# 设计稿另有一个 22 的 --fs-title (弹窗/欢迎页大标题), 已作为
# ui_tokens.FS_TITLE=22 暴露, 需要时显式取用, 不改 SIZE_TITLE 以免
# 现有页面版式整体位移。
SIZE_TITLE = ui_tokens.FS_H1        # 20  页面大标题 (--fs-h1)
SIZE_SUBTITLE = ui_tokens.FS_H2     # 17  卡片标题 / 对话框标题 (--fs-h2)
SIZE_LABEL = ui_tokens.FS_H3        # 15  输入框 / 列表主标题 (--fs-h3)
SIZE_BODY = ui_tokens.FS_BODY       # 14  正文 (--fs-body)
SIZE_SMALL = ui_tokens.FS_SMALL     # 13  辅助文字 (--fs-small)
SIZE_TINY = ui_tokens.FS_CAPTION    # 12  时间戳 / 状态微字 (--fs-caption)
SIZE_MICRO = ui_tokens.FS_MICRO     # 11  徽章微字 (--fs-micro, 新增)

# ---- 字重规范 (设计稿只有 4 档) ----
WEIGHT_TITLE = ft.FontWeight.BOLD        # 700
WEIGHT_SUBTITLE = ft.FontWeight.W_600    # 600
WEIGHT_BODY = ft.FontWeight.NORMAL       # 400
WEIGHT_EMPHASIS = ft.FontWeight.W_500    # 500


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


def 主题色(键: str, 夜间: bool = None) -> str:
    """取暖色令牌 (ui_tokens.取色 的再导出, 页面侧单一入口)。"""
    return 取色(键, 夜间)


# ====================================================================
# 二、暖色板 (语义色别名)
# ====================================================================
# 【重要】设计稿的这些色 M3 无对应槽位, 必须走 ui_tokens 跟随主题重算。
#   页面直接 import 本模块的 MORANDI_* 即可, 无需改 import 语句。
#   仍为 M3 别名的项 (标了"自动适配") 保持原样, 切主题零成本。

# ---- 品牌 / 强调 ----
MORANDI_PRIMARY = 取色('btn-primary-bg')       # 主按钮底 日#AD5710/夜#E08A3C
MORANDI_ACCENT = 取色('accent-fg')             # 可读强调字 日#A6510E/夜#EAA261
MORANDI_ON_PRIMARY = 取色('btn-primary-fg')    # 主按钮字 (日白/夜近黑, 自动反色)

# ---- 状态色 (设计稿 6 组; 进行中 = 警告色) ----
MORANDI_SUCCESS = 取色('status-success')       # 成功 日#1E6B3C/夜#7FD472
MORANDI_ERROR = 取色('status-error')           # 错误 日#8E3428/夜#F0A99C
MORANDI_WARNING = 取色('status-warning')       # 警告 日#8A4310/夜#E8A96A
MORANDI_INFO = 取色('status-info')             # 信息 日#3F3FB0/夜#A5A5F0
MORANDI_RUNNING = 取色('status-warning')       # 进行中 = 警告色 (设计稿明文)
MORANDI_STOPPED = 取色('status-pending')       # 已停止/已忽略 中性灰
MORANDI_PENDING = 取色('status-pending')       # 等待中 中性灰

# ---- 停止 (设计稿是蓝紫 #5C5CD9, **不是红**) ----
MORANDI_STOP = 取色('accent-stop')
MORANDI_STOP_LIGHT = 取色('accent-stop-light')

# ---- 焦点环 / 远控 / GitHub (M3 无槽位, 只能走令牌) ----
MORANDI_FOCUS_RING = 取色('focus-ring')
MORANDI_REMOTE_BG = 取色('remote-bg')
MORANDI_REMOTE_TEXT = 取色('remote-text')
MORANDI_GH_LINK = 取色('gh-link')
MORANDI_GH_HOVER = 取色('gh-hover')
MORANDI_GH_HOVER_BG = 取色('gh-hover-bg')
MORANDI_GH_HINT = 取色('gh-hint')

# ---- 侧边栏专用色 (设计稿 --bg-sidebar-*) ----
MORANDI_SIDEBAR_BG = 取色('bg-sidebar')            # 日#F1F1F1 / 夜#171717
MORANDI_SIDEBAR_HOVER = 取色('bg-sidebar-hover')   # 日#E7E7E7 / 夜#2B2B2B
MORANDI_SIDEBAR_ACTIVE = 取色('bg-sidebar-active')  # 日#FAF1E7 / 夜#382614
MORANDI_SIDEBAR_ACTIVE_FG = 取色('text-sidebar-active')  # 日#9C4A0C / 夜#E8A96A

# ---- 表面/文字/边框 ----
# 文字与边框改走令牌 (设计稿的 rgba 边框 M3 outline_variant 能表达, 但为
# 与"边框三档"语义一致, 这里统一用令牌; 表面仍用 M3 别名自动适配)
# 注: ft.Colors 没有 BACKGROUND / SURFACE_VARIANT 别名 (本机 0.86.5 内省
#     确认, 只有 SURFACE + 5 个 CONTAINER 槽位), 故这两个历史名映射到
#     最接近的 SURFACE 槽位 —— 与改造前行为一致, 不断引用。
MORANDI_BACKGROUND = ft.Colors.SURFACE_CONTAINER           # ≈ --bg-primary 槽位
MORANDI_SURFACE = ft.Colors.SURFACE                        # = --bg-secondary (卡片)
MORANDI_SURFACE_CONTAINER = ft.Colors.SURFACE_CONTAINER    # ≈ --bg-tertiary
MORANDI_SURFACE_CONTAINER_HIGH = ft.Colors.SURFACE_CONTAINER_HIGH
MORANDI_SURFACE_CONTAINER_HIGHEST = ft.Colors.SURFACE_CONTAINER_HIGHEST
MORANDI_ON_SURFACE = ft.Colors.ON_SURFACE                  # 自动适配
MORANDI_ON_SURFACE_VARIANT = 取色('text-secondary')       # 日#5C5C5C/夜#C8C8C8
MORANDI_OUTLINE = 取色('border-strong')                    # 日 rgba(0,0,0,.22)
MORANDI_OUTLINE_VARIANT = 取色('border-subtle')            # 日 rgba(0,0,0,.08)
MORANDI_ON_SECONDARY = ft.Colors.ON_SECONDARY              # 自动适配
MORANDI_SECONDARY = 取色('status-success')                 # 历史名, 实为成功绿

# ---- 扩展色 (旧引用兼容, 全部指向暖色语义) ----
MORANDI_MAUVE = MORANDI_ACCENT       # 紫调 → 可读强调
MORANDI_GOLD = MORANDI_WARNING        # 金调 → 警告
MORANDI_TEAL = 取色('teal')           # 青调 → 青
MORANDI_CLAY = MORANDI_ERROR          # 陶土 → 错误
MORANDI_LILAC = MORANDI_INFO          # 淡紫 → 信息

# ---- 终端 (恒深, 日夜完全相同) ----
MORANDI_TERMINAL_BG = 取色('terminal-bg')        # #171717
MORANDI_TERMINAL_TEXT = 取色('terminal-text')    # #C8C8C8
MORANDI_TERMINAL_DIM = 取色('terminal-dim')      # #9A9A9A

# ---- 日志级别色 (恒深终端底上的着色, 设计稿终端色) ----
LOG_COLOR_INFO = 取色('terminal-text')            # #C8C8C8
LOG_COLOR_ERROR = 取色('terminal-red')            # #F09A8C (深底可读的浅红)
LOG_COLOR_WARN = 取色('terminal-yellow')          # #E8C57A
LOG_COLOR_DEBUG = 取色('terminal-dim')            # #9A9A9A
LOG_COLOR_SUCCESS = 取色('terminal-green')         # #5BD675
LOG_COLOR_ACCENT = 取色('terminal-cyan')          # #6FDCCC


# ====================================================================
# 三、主题生成 (M3 ColorScheme ← 暖色令牌)
# ====================================================================

# ---- 兼容常量热刷新 -------------------------------------------------
# 上面的 MORANDI_* / LOG_COLOR_* 在**模块导入时**求值一次。若不刷新,
# 切到夜间后它们仍是日间字面量 -> 页面 (detail_drawer/task_table 等
# 直接 import 这些名字) 会掉色。所以主题切换时按当前主题重算一遍,
# 用 globals().update 就地替换 —— import 到本地的引用是同一个 str
# 对象被换掉, 但**已经取值赋给控件字段的那些不会自动变**, 这部分靠
# 各组件自己登记重刷 (见 ui_tokens.登记重刷)。
def 刷新兼容常量():
    """按当前主题状态重算所有随主题变化的模块级常量 (主题切换时调用)"""
    g = globals()
    g.update({
        'MORANDI_PRIMARY': 取色('btn-primary-bg'),
        'MORANDI_ACCENT': 取色('accent-fg'),
        'MORANDI_ON_PRIMARY': 取色('btn-primary-fg'),
        'MORANDI_SUCCESS': 取色('status-success'),
        'MORANDI_ERROR': 取色('status-error'),
        'MORANDI_WARNING': 取色('status-warning'),
        'MORANDI_INFO': 取色('status-info'),
        'MORANDI_RUNNING': 取色('status-warning'),
        'MORANDI_STOPPED': 取色('status-pending'),
        'MORANDI_PENDING': 取色('status-pending'),
        'MORANDI_STOP': 取色('accent-stop'),
        'MORANDI_STOP_LIGHT': 取色('accent-stop-light'),
        'MORANDI_FOCUS_RING': 取色('focus-ring'),
        'MORANDI_REMOTE_BG': 取色('remote-bg'),
        'MORANDI_REMOTE_TEXT': 取色('remote-text'),
        'MORANDI_GH_LINK': 取色('gh-link'),
        'MORANDI_GH_HOVER': 取色('gh-hover'),
        'MORANDI_GH_HOVER_BG': 取色('gh-hover-bg'),
        'MORANDI_GH_HINT': 取色('gh-hint'),
        'MORANDI_SIDEBAR_BG': 取色('bg-sidebar'),
        'MORANDI_SIDEBAR_HOVER': 取色('bg-sidebar-hover'),
        'MORANDI_SIDEBAR_ACTIVE': 取色('bg-sidebar-active'),
        'MORANDI_SIDEBAR_ACTIVE_FG': 取色('text-sidebar-active'),
        'MORANDI_ON_SURFACE_VARIANT': 取色('text-secondary'),
        'MORANDI_OUTLINE': 取色('border-strong'),
        'MORANDI_OUTLINE_VARIANT': 取色('border-subtle'),
        'MORANDI_SECONDARY': 取色('status-success'),
        'MORANDI_MAUVE': 取色('accent-fg'),
        'MORANDI_GOLD': 取色('status-warning'),
        'MORANDI_TEAL': 取色('teal'),
        'MORANDI_CLAY': 取色('status-error'),
        'MORANDI_LILAC': 取色('status-info'),
        'MORANDI_TERMINAL_BG': 取色('terminal-bg'),
        'MORANDI_TERMINAL_TEXT': 取色('terminal-text'),
        'MORANDI_TERMINAL_DIM': 取色('terminal-dim'),
        'LOG_COLOR_INFO': 取色('terminal-text'),
        'LOG_COLOR_ERROR': 取色('terminal-red'),
        'LOG_COLOR_WARN': 取色('terminal-yellow'),
        'LOG_COLOR_DEBUG': 取色('terminal-dim'),
        'LOG_COLOR_SUCCESS': 取色('terminal-green'),
        'LOG_COLOR_ACCENT': 取色('terminal-cyan'),
    })


def _build_theme(cs_kwargs: dict) -> ft.Theme:
    """由 ColorScheme 属性字典生成 Flet Theme (控件圆角 6px = --radius-md)

    ⚠️ P0 修复 (2026-10-04): 旧实现是裸 `for k, v in cs_kwargs.items(): setattr(cs, k, v)`,
       而 Flet 0.86.5 的 ColorScheme 只有 46 个真实字段, **不存在** background /
       on_background / surface_variant。旧代码把 design 的 --bg-primary /
       --bg-tertiary 传进这三个不存在的键, 被 setattr **静默丢弃且不报错**,
       导致「页面底色与卡片底色分两档」这个设计从未真正生效 (页面底一直靠
       渲染层默认 surface 撑着)。现改为白名单校验 + 显式告警, 杜绝同类静默丢失。
    """
    cs = ft.ColorScheme()
    # Flet 真实字段白名单 (反射取一次即缓存, 避免每次建主题都遍历 dataclass)
    真实字段 = {f.name for f in dataclasses.fields(ft.ColorScheme)}
    被丢弃 = []
    for k, v in cs_kwargs.items():
        if k not in 真实字段:
            被丢弃.append(k)
            continue
        setattr(cs, k, v)
    if 被丢弃:
        # 只在 DEBUG 记留痕, 不阻断建主题 —— 历史键名传错不该让 GUI 起不来
        _dbg("主题", f'ColorScheme 不存在以下键, 已忽略: {被丢弃} '
                     f'(Flet 0.86.5 无此槽位; 页面底色请用主内容容器 bgcolor 显式赋值)')
    cs.surface_tint = '#00000000'   # 见下方「关闭 M3 染色」说明

    _body_ts = ft.TextStyle(size=SIZE_BODY, weight=WEIGHT_BODY, font_family=FONT_STACK)
    # 控件圆角: 按钮/输入 6px (设计稿 --radius-md)
    # 用 MD 而非 SM 的理由: .btn-sm 只有 28px 高, 4px 圆角在 28px 控件上
    # 视觉占比偏厚、显得"环"; 设计稿定稿值即 MD=6。
    _btn_shape = ft.RoundedRectangleBorder(radius=ui_tokens.RADIUS_MD)

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

    # 按钮内边距按设计稿规格表: 主/次 0 16
    filled_btn_theme = ft.FilledButtonTheme(style=ft.ButtonStyle(
        text_style=_body_ts, shape=_btn_shape,
        padding=ft.Padding.symmetric(horizontal=ui_tokens.BTN_PAD_X, vertical=0)))

    outline_btn_theme = ft.OutlinedButtonTheme(style=ft.ButtonStyle(
        text_style=_body_ts, shape=_btn_shape,
        side=ft.BorderSide(1, cs_kwargs.get('outline_variant', MORANDI_OUTLINE_VARIANT)),
        padding=ft.Padding.symmetric(horizontal=ui_tokens.BTN_PAD_X, vertical=0)))

    # .btn-icon 34x34 —— 方形图标按钮与文字按钮同用 --radius-md
    icon_btn_theme = ft.IconButtonTheme(style=ft.ButtonStyle(
        shape=ft.RoundedRectangleBorder(radius=ui_tokens.RADIUS_MD)))

    dialog_theme = ft.DialogTheme(
        bgcolor=cs_kwargs.get('surface', MORANDI_SURFACE),
        shape=ft.RoundedRectangleBorder(radius=ui_tokens.RADIUS_LG),   # 卡片同 8px
        elevation=8,
        title_text_style=ft.TextStyle(
            size=SIZE_SUBTITLE, weight=WEIGHT_SUBTITLE, font_family=FONT_STACK,
            # 显式给色: 文字样式缺 color 时, 打包环境 (EXE/Flutter 渲染) 下
            # 弹窗标题/正文/复选框文字会渲染成不可见, 只有自带主色的按钮可见
            color=cs_kwargs.get('on_surface', MORANDI_ON_SURFACE)),
        content_text_style=ft.TextStyle(
            size=SIZE_BODY, weight=WEIGHT_BODY, font_family=FONT_STACK,
            color=cs_kwargs.get('on_surface', MORANDI_ON_SURFACE)),
    )

    divider_theme = ft.DividerTheme(
        color=cs_kwargs.get('outline_variant', MORANDI_OUTLINE_VARIANT))

    # 提示条主题 (2026-10-06): 兜底 —— 若有人手写裸 ft.SnackBar 而没给色,
    # 至少保证"深底浅字/浅底深字"成对, 不会出现黑底黑字。
    # 正常路径请用 ui_fluent.提示条(), 它还会登记主题重刷。
    # ⚠️ 字段名是 flet 的 `snackbar_theme`(无下划线), 写成 snack_bar_theme 会在
    #    建主题时 TypeError 直接崩 (2026-10-06 被 test_提示条可读性 当场抓住)。
    snackbar_theme = ft.SnackBarTheme(
        bgcolor=cs_kwargs.get('inverse_surface', '#2B2B2B'),
        content_text_style=ft.TextStyle(
            size=SIZE_SMALL, weight=WEIGHT_BODY, font_family=FONT_STACK,
            color=cs_kwargs.get('on_inverse_surface', '#FFFFFF')),
    )

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
        snackbar_theme=snackbar_theme,
    )


def make_morandi_theme() -> ft.Theme:
    """日间主题: 暖色 —— #F5F5F5 底 + 纯白卡片 + #AD5710 主按钮 + #D9781A 品牌

    函数名历史兼容 (原莫兰迪主题入口), 现返回暖色日间主题。
    槽位映射说明见文件头; 装不进槽位的令牌在 ui_tokens 里取。
    """
    return _build_theme({
        # ---- 品牌层 (primary = 主按钮底色, 保证 FilledButton 免样式即合规) ----
        'primary': '#AD5710',                    # --btn-primary-bg
        'on_primary': '#FFFFFF',                 # --btn-primary-fg
        'primary_container': '#FAF1E7',          # --brand-subtle
        'on_primary_container': '#8A4310',       # --on-brand-subtle
        'primary_fixed': '#D9781A',              # --brand
        'primary_fixed_dim': '#A6510E',          # --accent-fg
        'on_primary_fixed': '#FFFFFF',
        'on_primary_fixed_variant': '#8A4310',
        'inverse_primary': '#D9781A',            # 反色主题下的品牌色
        # ---- 成功 (secondary 槽位复用为绿) ----
        'secondary': '#1E6B3C',                  # --status-success
        'on_secondary': '#FFFFFF',
        'secondary_container': '#DFF6E5',        # --status-success-bg
        'on_secondary_container': '#1E6B3C',
        'secondary_fixed': '#1E6B3C',
        'secondary_fixed_dim': '#237A47',
        'on_secondary_fixed': '#FFFFFF',
        'on_secondary_fixed_variant': '#1E6B3C',
        # ---- 警告 (tertiary 槽位) ----
        'tertiary': '#8A4310',                   # --status-warning
        'on_tertiary': '#FFFFFF',
        'tertiary_container': '#FAF1E7',         # --status-warning-bg
        'on_tertiary_container': '#8A4310',
        'tertiary_fixed': '#8A4310',
        'tertiary_fixed_dim': '#A6510E',
        'on_tertiary_fixed': '#FFFFFF',
        'on_tertiary_fixed_variant': '#8A4310',
        # ---- 错误 ----
        'error': '#8E3428',                      # --status-error
        'error_container': '#FBE9E7',            # --status-error-bg
        'on_error': '#FFFFFF',
        'on_error_container': '#8E3428',
        # ---- 中性面 ----
        # ⚠️ Flet 0.86.5 的 ColorScheme **没有** background / on_background /
        #    surface_variant 这三个槽位。旧稿把它们写在这里, 会被 setattr
        #    静默丢弃 —— 即「页面底 #F5F5F5 与卡片底 #FFFFFF 分两档」从未生效。
        #    现在: 卡片面走 surface / surface_container_low, 页面底色由主内容
        #    容器显式赋 bgcolor (见 gui_app main_row), 这里只保留真实槽位。
        'surface': '#FFFFFF',                    # --bg-secondary (卡片纯白)
        'on_surface': '#1B1B1B',                 # --text-primary
        'on_surface_variant': '#5C5C5C',         # --text-secondary
        'outline': '#6E6E6E',                    # --text-tertiary
        'outline_variant': '#14000000',   # --border-subtle
        'surface_container_lowest': '#FFFFFF',
        'surface_container_low': '#F1F1F1',      # --bg-sidebar (侧栏)
        'surface_container': '#F5F5F5',          # --bg-tertiary
        'surface_container_high': '#E7E7E7',     # --bg-sidebar-hover
        'surface_container_highest': '#FAFAF9',  # --bg-row-hover
        'surface_dim': '#E7E7E7',
        'surface_bright': '#FFFFFF',
        # surface_tint 故意不设品牌橙: M3 着色器会拿它给 Surface/SurfaceContainer
        # 系列叠 tonal overlay, 设橙会让所有卡片染上暖橙, 与设计稿的纯净白底冲突。
        # _build_theme 末尾统一置 '#00000000' 关闭染色。
        'inverse_surface': '#2B2B2B',
        'on_inverse_surface': '#FFFFFF',
        'shadow': '#29000000',
        'scrim': '#52000000',
    })


def make_morandi_dark_theme() -> ft.Theme:
    """夜间主题: 暖色 —— #202020 底 + #2B2B2B 卡片 + #171717 侧栏 + 反色主按钮

    主按钮反色: 亮橙底 #E08A3C 配近黑字 #1B1B1B (6.46:1, 过 AA)。
    """
    return _build_theme({
        'primary': '#E08A3C',                    # --btn-primary-bg
        'on_primary': '#1B1B1B',                 # 反色! 近黑字
        'primary_container': '#382614',          # --brand-subtle
        'on_primary_container': '#E8A96A',       # --on-brand-subtle
        'primary_fixed': '#E08A3C',
        'primary_fixed_dim': '#EAA261',          # --accent-fg
        'on_primary_fixed': '#1B1B1B',
        'on_primary_fixed_variant': '#E8A96A',
        'inverse_primary': '#AD5710',
        # ---- 成功 ----
        'secondary': '#7FD472',                  # --status-success
        'on_secondary': '#1B1B1B',
        'secondary_container': '#1B3D22',        # --status-success-bg
        'on_secondary_container': '#7FD472',
        'secondary_fixed': '#7FD472',
        'secondary_fixed_dim': '#7FD472',
        'on_secondary_fixed': '#1B1B1B',
        'on_secondary_fixed_variant': '#7FD472',
        # ---- 警告 ----
        'tertiary': '#E8A96A',                   # --status-warning
        'on_tertiary': '#1B1B1B',
        'tertiary_container': '#382614',
        'on_tertiary_container': '#E8A96A',
        'tertiary_fixed': '#E8A96A',
        'tertiary_fixed_dim': '#EAA261',
        'on_tertiary_fixed': '#1B1B1B',
        'on_tertiary_fixed_variant': '#E8A96A',
        # ---- 错误 ----
        'error': '#F0A99C',                      # --status-error
        'error_container': '#432723',            # --status-error-bg
        'on_error': '#1B1B1B',
        'on_error_container': '#F0A99C',
        # ---- 中性面 ----
        'surface': '#2B2B2B',                    # --bg-secondary (卡片)
        'on_surface': '#FFFFFF',
        'on_surface_variant': '#C8C8C8',         # --text-secondary
        'outline': '#A6A6A6',                    # --text-tertiary
        'outline_variant': '#17FFFFFF',  # --border-subtle
        'surface_container_lowest': '#171717',
        'surface_container_low': '#171717',      # --bg-sidebar (纯黑, 比卡片更暗)
        'surface_container': '#383838',          # --bg-tertiary (旧值 #202020 偏暗, 会与页面底撞色)
        'surface_container_high': '#2B2B2B',     # --bg-sidebar-hover
        'surface_container_highest': '#383838',  # --bg-row-hover
        'surface_dim': '#171717',
        'surface_bright': '#383838',
        'inverse_surface': '#F5F5F5',
        'on_inverse_surface': '#1B1B1B',
        'shadow': '#7A000000',
        'scrim': '#8F000000',
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


def 同步主题(是否夜间: bool):
    """主题切换后同步令牌层状态并重刷已登记控件。

    调用链: gui_app.toggle_theme() -> IconRail.toggle_theme_icon()
            -> 本函数 -> ui_tokens.设置主题()
    必须在 page.theme_mode 赋值之后、page.update() 之前调用。

    两件事都要做:
      1. 刷新模块级 MORANDI_*/LOG_COLOR_* (让"下一次" import/取值正确)
      2. 触发已登记控件的换色回调 (让"已经构建"的控件也换色)
    """
    设置主题(是否夜间)
    刷新兼容常量()


def make_morandi_card(content, **kwargs) -> ft.Container:
    """卡片 (复用 ui_theme.make_card)"""
    from .ui_theme import make_card as _make_card
    return _make_card(content, **kwargs)


def 提示条(文案: str, 时长: int = 4000, 图标=None) -> ft.SnackBar:
    """**统一** SnackBar 构造器 (2026-10-06 修复"黑底黑字看不见")。

    为什么必须由这里统一给色、而不能让调用方自己写:
    - Flutter 默认 SnackBar 底取自 `colorScheme.inverseSurface`(**深色**)、
      字取自 `onInverseSurface`(浅色) —— 本来可读;
    - 但本项目为修 v2.4.19「EXE 里弹窗文字不可见」, 多处把文字**显式**设成
      `ON_SURFACE`(深色)。显式色会覆盖主题默认色 → **深字压深底, 完全看不见**
      (用户 2026-10-06 报告: 死书清单页点「重新检测」后提示条不可读)。
    - 所以这里**同时**给 `bgcolor` 与文字色, 两者取自**同一对**令牌
      (`toast-bg` / `toast-fg`), 既满足"显式给色"的 EXE 契约, 又保证前后景配对;
      并登记重刷, 切主题后仍然成对换色。

    新增提示请一律用它, 不要再手写 `ft.SnackBar(ft.Text(..., color=ON_SURFACE))`。
    """
    前景 = 取色('toast-fg')
    正文 = txt(文案, size=SIZE_SMALL, weight=WEIGHT_BODY, color=前景,
              font_family=FONT_STACK)
    内容 = 正文
    if 图标 is not None:
        内容 = ft.Row([ft.Icon(图标, size=16, color=前景), 正文],
                      spacing=8, tight=True,
                      vertical_alignment=ft.CrossAxisAlignment.CENTER)
    条 = ft.SnackBar(content=内容, bgcolor=取色('toast-bg'), duration=时长)

    def _换色(c):
        # 只改属性, 不调 update() (项目硬约定: 由 page.update 兜底刷出)
        c.bgcolor = 取色('toast-bg')
        _前景 = 取色('toast-fg')
        正文.color = _前景
        if 图标 is not None and isinstance(c.content, ft.Row):
            for 子 in c.content.controls:
                if isinstance(子, ft.Icon):
                    子.color = _前景

    登记重刷(条, _换色)
    return 条


def open_dialog(page, ctrl):
    """打开对话框/SnackBar (flet 0.86 兼容: Page 无 .open, 用 show_dialog)"""
    try:
        page.show_dialog(ctrl)
    except Exception:
        try:
            page.overlay.append(ctrl)
            ctrl.open = True
            page.update()
        except Exception as _e:
            _dbg("UI", f'裸 except 吞异常: {type(_e).__name__}: {_e}')


def close_dialog(page, ctrl):
    """关闭对话框 (G-M1, GUI 专项审查): 与 open_dialog 的 show_dialog 对称,
    关闭必须走 pop_dialog —— 旧式 `ctrl.open=False` 对压入 dialog 栈的弹窗
    不生效, 会残留 overlay。overlay 兜底路径 (show_dialog 失败时) 仍走旧式。"""
    try:
        page.pop_dialog()
    except Exception as _e:
        _dbg("UI", f'裸 except 吞异常: {type(_e).__name__}: {_e}')
    try:
        if ctrl.open:
            ctrl.open = False
            page.update()
    except Exception as _e:
        _dbg("UI", f'裸 except 吞异常: {type(_e).__name__}: {_e}')
