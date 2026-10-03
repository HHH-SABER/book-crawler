# -*- coding: utf-8 -*-
"""UI 主题系统: 卡片工厂 + 状态徽章 + 按钮工厂 (暖色设计系统)

设计稿真值来源: 界面设计预览/index.html, 色值全部走 ui_tokens 令牌,
本模块**不写死任何颜色字面量** (除终端色外, 终端恒定)。

======================================================================
双主题适配机制 (Flet 特性, 与 CSS 的根本差异)
======================================================================
Flet 不是 CSS, 没有"变量就地替换"。所以:
  轨道 A  用 ft.Colors.* M3 语义别名 (真实值是 'primary' 这类字符串,
         Flutter 渲染时按 page.theme_mode 解析) —— **自动适配, 零成本**。
         凡是能装进 ColorScheme 48 槽位的, 一律走这条。
  轨道 B  装不进槽位的 (状态色/焦点环/远控/GitHub/停止色) 用
         ui_tokens.取色() —— **构建期求值**, 所以构建后必须调
         ui_tokens.登记重刷(), 否则切主题会掉色。

交互四态实现口径 (设计稿要求每态都有, 不许只做 hover):
  hover    ButtonStyle.overlay_color[ControlState.HOVERED]   (Flet 原生, 免手绘)
  active   overlay_color[ControlState.PRESSED]
           ⚠️ 键必须是 ft.ControlState 成员(值是 'hovered'/'pressed'/'focused');
              写成字符串 'hover'/'focus' 会让客户端解析失败 → 按钮渲染成灰块
              (2026-10-04 P0 事故, 详见 _底色覆盖 的 docstring)
  focus    on_focus 加 FOCUS_RING_WIDTH 边框, on_blur 撤掉
           ⚠️ ft.Container 没有 on_focus/on_blur (已内省确认), 自绘
              控件 (侧栏项/表格行) 做不出键盘焦点环 —— 这是硬限制
  disabled 文字用 tertiary 实色 + MouseCursor.FORBIDDEN (不用降透明度,
           设计稿明文 opacity:1)
"""
import flet as ft

# 统一字体与字重规范 (来自 ui_fluent, 本模块所有文本必须遵守)
from .ui_fluent import (
    FONT_STACK, FONT_TERMINAL, SIZE_BODY, SIZE_TINY, SIZE_MICRO,
    SIZE_TITLE, SIZE_SMALL, WEIGHT_BODY, WEIGHT_EMPHASIS, WEIGHT_SUBTITLE,
    WEIGHT_TITLE,
)
from . import ui_tokens
from .ui_tokens import (
    取色, 状态色, 登记重刷, 徽章语义, 状态语义,
    FS_BODY, FS_SMALL, FS_CAPTION, FS_MICRO,
    FW_MEDIUM, FW_REGULAR, FW_SEMI,
    BTN_H, BTN_PAD_X, BTN_FS, BTN_FW, BTN_RADIUS,
    BTN_SM_H, BTN_SM_PAD_X, BTN_SM_FS, BTN_SM_FW,
    BTN_LG_H, BTN_LG_PAD_X, BTN_LG_FS, BTN_LG_FW,
    ICON_BTN_W, ICON_BTN_H, ICON_BTN_R,
    TBL_ICON_BTN_W, TBL_ICON_BTN_H, TBL_ICON_BTN_R,
    CHIP_H, CHIP_PAD_X, CHIP_FS, CHIP_FW, CHIP_RADIUS,
    BADGE_H, BADGE_PAD_X, BADGE_FS, BADGE_FW, BADGE_RADIUS,
    CARD_RADIUS, CARD_PADDING,
    RADIUS_SM, RADIUS_MD, RADIUS_LG, RADIUS_PILL,
    FOCUS_RING_WIDTH, 间距, 阴影,
)

# 统一留痕通道 (容错导入, 同 ui_fluent / input_bar 的桥模式):
# UI 层的异常一律记 DEBUG, 不弹窗、不打断交互。
try:
    import 日志 as _app_log
except Exception:
    _app_log = None


def _留痕(source: str, message: str):
    """写 DEBUG 留痕。日志模块不可用时静默 (留痕通道本身不该抛)"""
    if _app_log is None:
        return
    try:
        _app_log.debug(source, message)
    except Exception:
        return  # 刻意静默: 写日志失败时若再补日志会递归 (同 ui_fluent._dbg)

# 统一按钮文字样式 (所有按钮工厂函数必须引用, 保证字号/字重/字体族一致)
# 设计稿: 主/次按钮 14/500
BTN_TEXT_STYLE = ft.TextStyle(
    size=BTN_FS, weight=ft.FontWeight.W_500, font_family=FONT_STACK)
BTN_SM_TEXT_STYLE = ft.TextStyle(
    size=BTN_SM_FS, weight=ft.FontWeight.W_500, font_family=FONT_STACK)
BTN_LG_TEXT_STYLE = ft.TextStyle(
    size=BTN_LG_FS, weight=ft.FontWeight.W_500, font_family=FONT_STACK)
CHIP_TEXT_STYLE = ft.TextStyle(
    size=CHIP_FS, weight=ft.FontWeight.NORMAL, font_family=FONT_STACK)

# 终端色 (恒深, 日夜同值 —— 故可安全做模块级常量, 无需重刷)
LOG_TERMINAL_BG = 取色('terminal-bg', False)
LOG_TERMINAL_FONT = FONT_TERMINAL


# ====================================================================
# 一、焦点环 (四态之 focus)
# ====================================================================

def 焦点环样式(基础side=None, 聚焦: bool = False):
    """按聚焦与否返回边框: 聚焦时 2px 焦点环色, 否则原边框。

    设计稿: 焦点环 2px --focus-ring + 2px 偏移, 仅键盘焦点时出现。
    Flet 按钮没有 outline/box-shadow 的 focus 态, 用"加粗边框"近似 ——
    偏移量 2px 做不到, 只能靠边框变粗来表达聚焦 (已知差异, 见交付报告)。
    """
    if 聚焦:
        return ft.BorderSide(FOCUS_RING_WIDTH, 取色('focus-ring'))
    return 基础side


# ButtonStyle 实际存在的字段 (本机 Flet 0.86.5 内省结果)。
# ⚠️ 刻意白名单而非逐个写死: 早先写了 surface_tint_color, 但该属性在
#    0.86.5 的 ButtonStyle 上**不存在**, 访问即 AttributeError, 而换色
#    回调被 try/except 吞掉 -> 表现为"按钮切主题静默不掉色"。
#    改成"按存在性过滤"以后, 版本升级新增/删除字段都不会再静默失败。
_样式字段 = ('bgcolor', 'color', 'overlay_color', 'shadow_color',
              'elevation', 'animation_duration', 'enable_feedback',
              'alignment', 'padding', 'side', 'shape', 'text_style',
              'mouse_cursor', 'visual_density', 'icon_color', 'icon_size')


def _改样式(样式, **覆写):
    """复制一份 ButtonStyle 并覆写指定字段; 未指定字段原样保留。

    只传该版本真实存在的字段 (白名单过滤), 避免 AttributeError 被上层
    try/except 吞掉造成"静默不换色"。
    """
    参 = {}
    for 名 in _样式字段:
        if 名 in 覆写:
            参[名] = 覆写[名]
        elif 样式 is not None and hasattr(样式, 名):
            参[名] = getattr(样式, 名)
    return ft.ButtonStyle(**参)


def 装焦点环(控件, 基础side=None):
    """给按钮装上 on_focus/on_blur 焦点环。

    on_focus 加 2px 焦点环边框, on_blur 还原为原边框。
    """
    def _聚焦(e):
        控件.style = _改样式(控件.style, side=焦点环样式(基础side, True))
        try:
            控件.update()
        except Exception as _exc:
            # 未挂树时 update 必抛, 构建期常见, 不应中断焦点环设置
            _留痕("焦点环", f'聚焦刷新失败 (控件可能未挂树): {type(_exc).__name__}: {_exc}')

    def _失焦(e):
        控件.style = _改样式(控件.style, side=基础side)
        try:
            控件.update()
        except Exception as _exc:
            # 控件已离树时 update 必抛 (与 _聚焦 同因), 失焦路径不该因此报错
            _留痕("焦点环", f'失焦刷新失败 (控件可能已离树): {type(_exc).__name__}: {_exc}')

    控件.on_focus = _聚焦
    控件.on_blur = _失焦
    return 控件


# ====================================================================
# 二、页面底色 (重要: M3 槽位装不下 --bg-primary)
# ====================================================================
# Flet 0.86.5 的 ColorScheme **没有** background 槽位 (已用 dataclasses
# 内省确认, 只有 46 个字段)。而设计稿要求页面底与卡片底分两档:
#     页面底 --bg-primary  日 #F5F5F5 / 夜 #202020
#     卡片底 --bg-secondary 日 #FFFFFF / 夜 #2B2B2B
# M3 里 surface 已被卡片(--bg-secondary)占用, surface_container 被
# --bg-tertiary 占用 —— **--bg-primary 无槽位可放**。所以页面底不能靠
# ft.Colors.* 别名自动适配, 必须显式赋值。
#
# 用法 (gui_app 主内容区, 下一轮改):
#     ft.Container(..., bgcolor=ui_theme.页面底色())
# 不要用 ft.Colors.SURFACE: 夜间它等于 #2B2B2B, 与卡片同色, 两档糊掉。

def 页面底色(夜间: bool = None) -> str:
    """页面底色 = --bg-primary (日 #F5F5F5 / 夜 #202020)

    ⚠️ 这是**构建期求值**的色值, 直接赋给容器 bgcolor 后, 切主题不会
        自动跟随。构建完请紧跟一行 `登记页面底色(那个容器)`。
    """
    return 取色('bg-primary', 夜间)


def 登记页面底色(容器):
    """把主内容区容器登记为"跟随主题换页面底色", 构建时调一次即可。

    用法 (gui_app 下一轮改):
        主内容 = ft.Container(..., bgcolor=ui_theme.页面底色())
        ui_theme.登记页面底色(主内容)
    """
    return 登记重刷(容器, lambda c: setattr(c, 'bgcolor', 取色('bg-primary')))


# ====================================================================
# 三、卡片
# ====================================================================
# 圆角改 lg=8 (设计稿 --radius-lg), 阴影改克制版 sm
# (0 1px 2px rgba(0,0,0,.04)), 边框用 --border-subtle
#
# ⚠️ 注意: 本函数**故意不提供 scroll 形参** —— ft.Container 无 scroll
#    字段, 传了会直接抛异常。需要滚动请开在内容 Column/ListView 上。

def make_card(content, padding=CARD_PADDING, radius=CARD_RADIUS,
              expand=False, width=None, bgcolor=None,
              visible=None, border=None):
    """统一卡片: 表面色 + 8px 圆角 + 细边框(--border-subtle) + 克制阴影(sm)"""
    return ft.Container(
        content=content,
        width=width,
        expand=expand,
        padding=padding,
        bgcolor=bgcolor or ft.Colors.SURFACE,   # 轨道A: 自动适配日/夜
        border_radius=radius,
        border=border or ft.Border.all(1, 取色('border-subtle')),
        visible=visible,
        shadow=阴影('sm'),
    )


# ---------------------------------------------------------------- 页面标题
def page_header(title: str, subtitle: str = "", actions=None) -> ft.Control:
    """页面大标题 + 副标题 + 右侧动作区 (匹配设计稿 page-header)"""
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


# ====================================================================
# 三、状态徽章 (.badge: 高20 胶囊 11px/500)
# ====================================================================
# 任务状态 -> 语义状态键 (再经 徽章语义 映射到 6 组暖色)
# 注意: 设计稿 6 组 = 成功/警告/错误/等待/信息/进行中(=警告色),
#       停用色是蓝紫, 只用于"停止"按钮, 不用于徽章。

STATUS_STYLES = {
    'interrupted': ('已中断', 'interrupted'),
    'running':     ('抓取中', 'running'),       # 进行中 = 警告色
    'completed':   ('已完成', 'success'),
    'failed':      ('失败',   'error'),
    'pending':     ('等待中', 'pending'),
    'stopped':     ('已停止', 'stopped'),
    # 死书待确认(终态, 需用户裁决删记录/忽略) —— 警告色, 与"失败"红区分
    'dead_pending': ('书已删除', 'warning'),
}

# 状态文案 (显式字面量, 不从 STATUS_STYLES 推导:
# 测试 test_dead_book_status_display 用正则锁住本字典结构,
# 目的是「有人删掉 dead_pending 时立刻红」—— 推导式会让该护栏失效)
STATUS_LABELS = {
    'interrupted': '已中断',
    'running':     '抓取中',
    'completed':   '已完成',
    'failed':      '失败',
    'pending':     '等待中',
    'stopped':     '已停止',
    'dead_pending': '书已删除',
}


def _解析状态(status: str):
    """状态键 -> (文案, 语义键); 未知状态按 pending 处理 (不抛, 表格里容错)"""
    if status in STATUS_STYLES:
        return STATUS_STYLES[status]
    return (status, 'pending')


def status_chip(status: str) -> ft.Control:
    """状态徽章: 20px 高 · 胶囊圆角 · 11px/500 · 浅底+深字。

    设计稿明确"胶囊选中态用浅底+深字+描边, 不用实心块压白字",
    所以这里统一 浅容器底 + 语义前景字, 并加 1px 半透明描边增强可辨识。
    构建后已登记重刷 —— 切主题时色值会跟着换。
    """
    文案, 语义键 = _解析状态(status)
    前景, 底色 = 状态色(语义键)
    # 描边: 用前景色 20% 透明度, 保证浅底上边界依然可辨 (不抢主体)
    描边 = ft.Colors.with_opacity(0.22, 前景)

    徽章 = ft.Container(
        content=ft.Text(文案, size=BADGE_FS,
                        weight=ft.FontWeight.W_500, color=前景,
                        font_family=FONT_STACK),
        padding=ft.Padding.symmetric(horizontal=BADGE_PAD_X, vertical=0),
        height=BADGE_H,
        bgcolor=底色,
        border_radius=BADGE_RADIUS,
        border=ft.Border.all(1, 描边),
        alignment=ft.Alignment.CENTER,
    )

    def _换色(c):
        新前景, 新底 = 状态色(语义键)
        c.bgcolor = 新底
        c.border = ft.Border.all(1, ft.Colors.with_opacity(0.22, 新前景))
        c.content.color = 新前景

    return 登记重刷(徽章, _换色)


def status_color(status: str):
    """状态主色 (进度环/圆点用) —— 返回当前主题下的前景色

    经 _解析状态 查 STATUS_STYLES 语义键, 全 7 态 (含 dead_pending /
    interrupted / stopped) 都有映射, 未知状态回落 pending 灰。
    """
    _, 语义键 = _解析状态(status)
    return 状态色(语义键)[0]


# ====================================================================
# 四、按钮工厂
# ====================================================================
# 规格 (设计稿组件规格表, 单位 px):
#   主/次  高34 内距0 16  圆角4  14/500
#   sm     高28 内距0 12  圆角4  13/500
#   lg     高40 内距0 20  圆角4  14/500
#   icon   34x34  圆角4              (方形图标按钮)
#   表格用 36x32  圆角6              (.icon-btn)

def _底色覆盖(键: str, 按下键: str = None):
    """构造 overlay_color 三态表: hover / pressed / focused 各叠一层黑。

    ⚠️ 2026-10-04 **P0 修复**(抓取工作台一片空白的根因):
    `ButtonStyle.overlay_color` 的类型是 `dict[ControlState, 颜色]` ——
    **键必须是 `ft.ControlState` 成员**, 其枚举值是 `'hovered'/'focused'/'pressed'`。
    旧代码写的是字符串 `'hover'` / `'focus'`(少了 `ed`), 不是合法状态名 →
    客户端解析该 ButtonStyle 失败 → **按钮整体渲染失败**(Flutter release 下为灰块)
    → 连带整张卡片内容消失。当时注释里"Flet 原生支持 hover/pressed/focus 键"
    是**未经核实的假设**, 正是它把 bug 带进了 Phase 1+2。
    另: 不透明度不再用 `ft.Colors.with_opacity` 产出的 `"色,透明度"` 逗号串,
    改为显式 8 位 hex(官方文档明确支持的两种写法之一)。

    按下态用"黑色叠加"近似加深 (设计稿的 hover 色是独立令牌, 但 overlay 层
    只能算叠加, 无法直接指定纯色 —— 已知近似)。
    """
    def _半透明(a: float) -> str:
        """黑色 + 不透明度 → Flet 8 位 hex '#AARRGGBB' (alpha = round(a*255))"""
        return '#%02X000000' % max(0, min(255, round(a * 255)))
    return {
        ft.ControlState.HOVERED: _半透明(0.045),
        ft.ControlState.PRESSED: _半透明(0.10),
        ft.ControlState.FOCUSED: _半透明(0.045),
    }


def _禁用光标():
    """禁用态语义光标 (设计稿 not-allowed)。Flet 无 NOT_ALLOWED, 用 FORBIDDEN。"""
    return ft.MouseCursor.FORBIDDEN


def filled_btn(text, icon=None, on_click=None, disabled=False, tooltip=None,
               visible=None, autofocus=False):
    """主按钮 (设计稿 .btn--primary): 34px 高, 圆角4, 14/500。

    颜色: 日间 #AD5710 底白字 / 夜间 #E08A3C 底**近黑字** (自动反色),
    由 ui_tokens.取色 在构建期取当前主题值; 登记重刷保证切主题会换色。
    """
    底 = 取色('btn-primary-bg')
    字 = 取色('btn-primary-fg')

    按钮 = ft.FilledButton(
        text, icon=icon, on_click=on_click, disabled=disabled, tooltip=tooltip,
        visible=visible, autofocus=autofocus,
        height=BTN_H,
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=BTN_RADIUS),
            bgcolor=底, color=字,
            overlay_color=_底色覆盖('btn-primary-bg'),
            padding=ft.Padding.symmetric(horizontal=BTN_PAD_X, vertical=0),
            text_style=BTN_TEXT_STYLE,
            mouse_cursor=_禁用光标() if disabled else ft.MouseCursor.CLICK,
        ),
    )

    def _换色(c):
        c.style = _改样式(c.style, bgcolor=取色('btn-primary-bg'),
                          color=取色('btn-primary-fg'))

    登记重刷(按钮, _换色)
    装焦点环(按钮)
    return 按钮


def tonal_btn(text, icon=None, on_click=None, disabled=False, tooltip=None,
              visible=None, autofocus=False):
    """次按钮 (设计稿 .btn--secondary): 白底/深字 + 1px 边框, 34px 高。

    日间: #FFFFFF 底 #3A3A3A 字 / 边框 rgba(0,0,0,.16)
    夜间: #2B2B2B 底 #E4E4E4 字 / 边框 rgba(255,255,255,.18)
    """
    底 = 取色('btn-secondary-bg')
    字 = 取色('btn-secondary-fg')
    边 = 取色('btn-secondary-border')

    按钮 = ft.FilledTonalButton(
        text, icon=icon, on_click=on_click, disabled=disabled, tooltip=tooltip,
        visible=visible, autofocus=autofocus,
        height=BTN_H,
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=BTN_RADIUS),
            bgcolor=底, color=字,
            side=ft.BorderSide(1, 边),
            overlay_color=_底色覆盖('btn-secondary-bg'),
            padding=ft.Padding.symmetric(horizontal=BTN_PAD_X, vertical=0),
            text_style=BTN_TEXT_STYLE,
            mouse_cursor=_禁用光标() if disabled else ft.MouseCursor.CLICK,
        ),
    )

    def _换色(c):
        c.style = _改样式(c.style, bgcolor=取色('btn-secondary-bg'),
                          color=取色('btn-secondary-fg'),
                          side=ft.BorderSide(1, 取色('btn-secondary-border')))

    登记重刷(按钮, _换色)
    装焦点环(按钮)
    return 按钮


def outline_btn(text, icon=None, on_click=None, disabled=False, tooltip=None,
                visible=None, autofocus=False):
    """描边按钮 (次要操作): 透明底 + 边框, 文字用可读强调色。"""
    字 = 取色('accent-fg')
    边 = 取色('border-default')

    按钮 = ft.OutlinedButton(
        text, icon=icon, on_click=on_click, disabled=disabled, tooltip=tooltip,
        visible=visible, autofocus=autofocus,
        height=BTN_H,
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=BTN_RADIUS),
            bgcolor=ft.Colors.TRANSPARENT, color=字,
            side=ft.BorderSide(1, 边),
            overlay_color=_底色覆盖('brand'),
            padding=ft.Padding.symmetric(horizontal=BTN_PAD_X, vertical=0),
            text_style=BTN_TEXT_STYLE,
            mouse_cursor=_禁用光标() if disabled else ft.MouseCursor.CLICK,
        ),
    )

    def _换色(c):
        c.style = _改样式(c.style, color=取色('accent-fg'),
                          side=ft.BorderSide(1, 取色('border-default')))

    登记重刷(按钮, _换色)
    装焦点环(按钮)
    return 按钮


def text_btn(text, icon=None, on_click=None, disabled=False, tooltip=None,
             visible=None, autofocus=False):
    """文字按钮 (最弱强调, 如取消/辅助链接): 无边框无底, hover 才有底。"""
    字 = 取色('accent-fg')

    按钮 = ft.TextButton(
        text, icon=icon, on_click=on_click, disabled=disabled, tooltip=tooltip,
        visible=visible, autofocus=autofocus,
        height=BTN_H,
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=BTN_RADIUS),
            color=字, overlay_color=_底色覆盖('brand'),
            padding=ft.Padding.symmetric(horizontal=BTN_PAD_X, vertical=0),
            text_style=BTN_TEXT_STYLE,
            mouse_cursor=_禁用光标() if disabled else ft.MouseCursor.CLICK,
        ),
    )

    def _换色(c):
        c.style = _改样式(c.style, color=取色('accent-fg'))

    登记重刷(按钮, _换色)
    装焦点环(按钮)
    return 按钮


def danger_btn(text, icon=None, on_click=None, disabled=False, tooltip=None,
               visible=None, autofocus=False):
    """停止/危险按钮: **蓝紫** #5C5CD9 (设计稿 --accent-stop, 不是红!)

    夜间 #7B7BE0 底配近黑字。圆角4 高34。
    """
    底 = 取色('accent-stop')
    # 停止色是蓝紫/亮蓝紫, 两个主题下都要深字 —— 日间 #AD5710 级别的
    # 深色字在 #5C5CD9 上对比不足, 统一用近黑字 (与 btn-primary-fg 同源)
    字 = 取色('btn-primary-fg')

    按钮 = ft.FilledButton(
        text, icon=icon, on_click=on_click, disabled=disabled, tooltip=tooltip,
        visible=visible, autofocus=autofocus,
        height=BTN_H,
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=BTN_RADIUS),
            bgcolor=底, color=字,
            overlay_color=_底色覆盖('accent-stop'),
            padding=ft.Padding.symmetric(horizontal=BTN_PAD_X, vertical=0),
            text_style=BTN_TEXT_STYLE,
            mouse_cursor=_禁用光标() if disabled else ft.MouseCursor.CLICK,
        ),
    )

    def _换色(c):
        c.style = _改样式(c.style, bgcolor=取色('accent-stop'),
                          color=取色('btn-primary-fg'))

    登记重刷(按钮, _换色)
    装焦点环(按钮)
    return 按钮


# ---- 尺寸变体 (设计稿 btn-sm / btn-lg) ----

def sm_btn(text, icon=None, on_click=None, disabled=False, tooltip=None,
           visible=None, kind: str = 'primary'):
    """小号按钮 高28 内距0 12 圆角4 13/500。kind ∈ primary/secondary/outline"""
    工厂 = {'primary': filled_btn, 'secondary': tonal_btn,
            'outline': outline_btn}.get(kind, filled_btn)
    按钮 = 工厂(text, icon=icon, on_click=on_click, disabled=disabled,
                tooltip=tooltip, visible=visible)
    # 覆写为 sm 规格 (工厂已装好焦点环/重刷, 这里只改尺寸与字号)
    按钮.height = BTN_SM_H
    按钮.style = _改样式(
        按钮.style,
        padding=ft.Padding.symmetric(horizontal=BTN_SM_PAD_X, vertical=0),
        text_style=BTN_SM_TEXT_STYLE)
    return 按钮


def lg_btn(text, icon=None, on_click=None, disabled=False, tooltip=None,
           visible=None, kind: str = 'primary'):
    """大号按钮 高40 内距0 20 圆角4 14/500"""
    工厂 = {'primary': filled_btn, 'secondary': tonal_btn,
            'outline': outline_btn}.get(kind, filled_btn)
    按钮 = 工厂(text, icon=icon, on_click=on_click, disabled=disabled,
                tooltip=tooltip, visible=visible)
    按钮.height = BTN_LG_H
    按钮.style = _改样式(
        按钮.style,
        padding=ft.Padding.symmetric(horizontal=BTN_LG_PAD_X, vertical=0),
        text_style=BTN_LG_TEXT_STYLE)
    return 按钮


# ---- 图标按钮 ----

def icon_btn(icon, on_click=None, tooltip=None, disabled=False, visible=None,
             危险: bool = False, 表格用: bool = False, autofocus=False):
    """图标按钮。

    表格用=True  -> 36x32 圆角6 (设计稿 .icon-btn, 表格行内操作)
    表格用=False -> 34x34 圆角4 (设计稿 .btn-icon, 独立图标按钮) —— **默认**
    危险=True    -> 用停止蓝紫色 (非红)

    默认取独立规格: 表格行内请显式传 表格用=True。否则默认拿到 36x32 的
    横长方形, 放在 34px 高的标题栏/工具条里会显得扁。
    """
    宽 = TBL_ICON_BTN_W if 表格用 else ICON_BTN_W
    高 = TBL_ICON_BTN_H if 表格用 else ICON_BTN_H
    圆角 = TBL_ICON_BTN_R if 表格用 else ICON_BTN_R
    字色 = 取色('accent-stop' if 危险 else 'text-secondary')

    按钮 = ft.IconButton(
        icon=icon, on_click=on_click, tooltip=tooltip, disabled=disabled,
        visible=visible, autofocus=autofocus,
        width=宽, height=高, icon_size=16,
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=圆角),
            color=字色,
            overlay_color=_底色覆盖('brand'),
            mouse_cursor=_禁用光标() if disabled else ft.MouseCursor.CLICK,
        ),
    )

    def _换色(c):
        新色 = 取色('accent-stop' if 危险 else 'text-secondary')
        c.style = _改样式(c.style, color=新色)
        c.icon_color = 新色

    登记重刷(按钮, _换色)
    装焦点环(按钮)
    return 按钮


def chip_btn(text, icon=None, on_click=None, 选中: bool = False,
             disabled=False, tooltip=None, visible=None, on_状态变化=None):
    """胶囊按钮 (.chip-btn / .filter-chip): 高28 内距0 12 胶囊 13/400。

    选中态按设计稿: **浅底 + 深字 + 描边**, 不用实心块压白字。
    """
    def _配色(是否选中):
        if 是否选中:
            return 取色('brand-subtle'), 取色('on-brand-subtle'), 取色('brand')
        return ft.Colors.TRANSPARENT, 取色('text-secondary'), 取色('border-default')

    底, 字, 边 = _配色(选中)

    按钮 = ft.Container(
        content=ft.Row(
            ([ft.Icon(icon, size=14, color=字)] if icon else [])
            + [ft.Text(text, size=CHIP_FS, weight=ft.FontWeight.NORMAL,
                       color=字, font_family=FONT_STACK)],
            spacing=6, tight=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        height=CHIP_H,
        padding=ft.Padding.symmetric(horizontal=CHIP_PAD_X, vertical=0),
        bgcolor=底,
        border_radius=CHIP_RADIUS,
        border=ft.Border.all(1, 边),
        alignment=ft.Alignment.CENTER,
        on_click=on_click,
        tooltip=tooltip,
        visible=visible,
        ink=True,
        on_hover=lambda e: _hover处理(e, 按钮, 选中),
    )

    def _换色(c):
        新底, 新字, 新边 = _配色(选中)
        c.bgcolor = 新底
        c.border = ft.Border.all(1, 新边)
        for 子 in c.content.controls:
            子.color = 新字

    登记重刷(按钮, _换色)

    def _设选中(是否选中: bool):
        """运行时切换选中态 (筛选胶囊用) —— 需外部调 c.update()"""
        _换色(按钮)
        按钮.on_hover = lambda e: _hover处理(e, 按钮, 是否选中)
        if on_状态变化:
            on_状态变化(是否选中)

    按钮.设选中 = _设选中
    return 按钮


def _hover处理(e, 按钮, 选中: bool):
    """胶囊 hover: 未选中才显示 hover 底 (选中态保持自己的浅底)"""
    try:
        按钮.bgcolor = (取色('bg-sidebar-hover') if e.data == 'true' and not 选中
                        else (取色('brand-subtle') if 选中
                              else ft.Colors.TRANSPARENT))
        按钮.update()
    except Exception:
        pass   # 未挂树时忽略 (构建期调用 hover 是测试行为)


# ====================================================================
# 五、日志终端配色 (恒深, 日夜同值)
# ====================================================================

def log_line_color(line: str):
    """日志行着色 (终端风格, 恒深底上的 8 色)"""
    if '[ERROR]' in line:
        return 取色('terminal-red', False)
    if '[WARN]' in line:
        return 取色('terminal-yellow', False)
    if '[DEBUG]' in line:
        return 取色('terminal-dim', False)
    return 取色('terminal-text', False)
