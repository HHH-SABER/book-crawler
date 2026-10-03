# -*- coding: utf-8 -*-
"""220px 侧边导航栏 + 顶栏 (还原界面设计预览/index.html 的暖色侧栏)

布局结构 (与 index.html 一致):
  ┌────────────────────────┐
  │  主功能                  │  ← 分区标题
  │  ⬇  抓取工作台           │  ← 选中态: 浅橙底 + 橙字
  │  📊  爬取历史            │
  │  📦  死书清单            │
  │  🌐  站点管理            │
  │  📝  运行日志            │
  │  ⚙  远控                 │
  │  (弹性留白)              │
  └────────────────────────┘

宽度 220px, 背景 #F1F1F1 (日间) / #171717 (夜间, 比卡片更暗)
导航项: icon(18px) + 文字(14px), 圆角 4px, 选中态浅橙底 #FAF1E7 + 橙字 #9C4A0C

======================================================================
⚠️ 本模块承担一个额外职责: 主题状态同步 (别删!)
======================================================================
gui_app.toggle_theme() 的调用顺序是:
    page.theme_mode = DARK/LIGHT   ← 先改 Flutter 侧
    rail.toggle_theme_icon(夜间)   ← 再调这里 (本模块)
    page.update()
IconRail.toggle_theme_icon() 是**本轮唯一不需要改 gui_app.py 就能挂上
的同步点**。它在这里调 ui_fluent.同步主题(), 把 ui_tokens 的主题状态
改过来并触发所有已登记控件换色。没有这一步, 用了 ui_tokens.取色()
的组件切主题后会掉色。

⚠️ 硬契约: NAV_PAGES 的顺序与内容**不得改动** —— gui_app.pages_map
   依赖 dict 插入序 == 本列表序, 两处不同序会导致首屏静默显示错页。
"""
import flet as ft

from .ui_fluent import (
    txt, SIZE_TINY, SIZE_SMALL, SIZE_BODY,
    WEIGHT_SUBTITLE, WEIGHT_BODY, WEIGHT_EMPHASIS,
)
from . import ui_tokens
from .ui_tokens import 取色, 登记重刷
from .ui_fluent import 同步主题
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
# 一、导航页定义
# ====================================================================
NAV_PAGES = [
    ('crawl',   ft.Icons.DOWNLOADING_OUTLINED,   '抓取工作台', 0),
    ('history', ft.Icons.HISTORY,                '爬取历史',   1),
    # 死书清单 (死书机制 阶段4): 插在 history 与 sites 之间。
    # ⚠️ 顺序是**契约** —— gui_app.pages_map 依赖 dict 插入序 == 本列表序,
    #    content_stack 按 [pages_map[k] for k,_,_,_ in NAV_PAGES] 建 Stack,
    #    且首屏可见性按索引 0 判定。**两处不同序 = 首屏显示错页**。
    ('deadbook', ft.Icons.INVENTORY_2_OUTLINED,  '死书清单',   2),
    ('sites',   ft.Icons.LANGUAGE,               '站点管理',   3),
    ('log',     ft.Icons.SPEED,                  '运行日志',   4),
    ('remote',  ft.Icons.SETTINGS_REMOTE,        '远控',       5),
]


# ====================================================================
# 二、主题切换按钮 (顶栏用 — 胶囊形 + 图标 + 文字)
# ====================================================================

def build_theme_toggle(page, current_mode: str, on_toggle) -> ft.Container:
    """构建主题切换按钮 (胶囊形, 还原设计稿: 浅底 + 图标 + 文字)

    样式: 高 28 (--chip-btn 规格) 内距 0 12, 圆角 999 胶囊,
          背景 brand-subtle, 文字 on-brand-subtle
    """
    is_dark = current_mode == 'dark'
    icon_name = ft.Icons.DARK_MODE_ROUNDED if is_dark else ft.Icons.LIGHT_MODE_ROUNDED
    label = '夜间' if is_dark else '日间'

    icon = ft.Icon(icon_name, size=16, color=取色('on-brand-subtle'))
    label_text = txt(label, size=SIZE_TINY, color=取色('on-brand-subtle'),
                     weight=WEIGHT_EMPHASIS)

    btn = ft.Container(
        content=ft.Row(
            [icon, label_text],
            spacing=8,
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        height=ui_tokens.CHIP_H,
        padding=ft.Padding.symmetric(horizontal=ui_tokens.CHIP_PAD_X, vertical=0),
        bgcolor=取色('brand-subtle'),
        border_radius=ui_tokens.CHIP_RADIUS,
        border=ft.Border.all(1, 取色('brand-subtle')),
        on_click=lambda e: on_toggle(),
        tooltip='切换日间/夜间模式',
        ink=True,
    )

    btn._icon_ref = icon
    btn._label_ref = label_text

    def update_theme_state(is_dark_now: bool):
        btn._icon_ref.icon = ft.Icons.DARK_MODE_ROUNDED if is_dark_now else ft.Icons.LIGHT_MODE_ROUNDED
        btn._label_ref.value = '夜间' if is_dark_now else '日间'
        try:
            btn.update()
        except Exception as _e:
            _dbg("导航栏", f'裸 except 吞异常: {type(_e).__name__}: {_e}')

    btn.update_theme_state = update_theme_state

    # 主题切换后胶囊配色跟随 (底/字/图标/边框)
    def _换色(c):
        c.bgcolor = 取色('brand-subtle')
        c.border = ft.Border.all(1, 取色('brand-subtle'))
        c.content.controls[0].color = 取色('on-brand-subtle')
        c.content.controls[1].color = 取色('on-brand-subtle')

    登记重刷(btn, _换色)
    return btn


# ====================================================================
# 三、顶栏 (Fluent: 应用图标 + 标题居左 + 右侧主题切换)
# ====================================================================

def build_remote_toggle(on_click):
    """顶栏远控开关 (胶囊按钮, 与主题切换同款形态)。

    返回 (控件, 更新状态函数): 更新(启用: bool) 刷新文案/配色/提示。
    默认启用 — 与 数据/远控配置.json 的 "启用" 一致。

    配色按设计稿远控层: --remote-bg 底 + --remote-text 字。"""
    def _外观(启用: bool):
        btn.bgcolor = (取色('remote-bg') if 启用 else 取色('bg-tertiary'))
        lab.color = (取色('remote-text') if 启用 else 取色('text-tertiary'))
        dot.color = (取色('status-success') if 启用 else 取色('text-tertiary'))
        lab.value = "远控 开" if 启用 else "远控 关"
        btn.tooltip = ("手机/外部设备可访问 (Tailscale)"
                       if 启用 else
                       "远控已停用——手机端将无法访问, 点击启用")

    lab = txt("远控 开", size=SIZE_SMALL, weight=WEIGHT_SUBTITLE)
    dot = ft.Icon(ft.Icons.CIRCLE, size=8, color=取色('status-success'))
    btn = ft.Container(
        content=ft.Row(
            [ft.Icon(ft.Icons.WIFI_TETHERING, size=14), dot, lab],
            spacing=6, tight=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        height=ui_tokens.CHIP_H,
        padding=ft.Padding.symmetric(horizontal=ui_tokens.CHIP_PAD_X, vertical=0),
        border_radius=ui_tokens.CHIP_RADIUS,
        on_click=on_click,
        ink=True,
    )
    _外观(True)
    return btn, _外观


def build_top_bar(page, title_text: str, theme_toggle_btn, extra_controls=None) -> ft.Container:
    """构建顶栏 (48px 高, 匹配设计稿 titlebar)

    布局: [📖 小说爬虫] ──────────────────── [🌙 夜间]
    """
    # 左侧: 应用图标 (品牌橙底圆角 4) + 应用名
    app_icon = ft.Container(
        content=ft.Icon(ft.Icons.MENU_BOOK_OUTLINED, size=14,
                        color=取色('on-brand')),
        width=24, height=24,
        border_radius=ui_tokens.RADIUS_SM,
        bgcolor=取色('btn-primary-bg'),
        alignment=ft.Alignment.CENTER,
    )
    app_title = txt(title_text, size=SIZE_BODY, weight=WEIGHT_SUBTITLE,
                    color=取色('text-primary'))

    bar = ft.Container(
        content=ft.Row(
            [app_icon, app_title, ft.Container(expand=True)]
            + list(extra_controls or []) + [theme_toggle_btn],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        height=48,
        padding=ft.Padding.symmetric(horizontal=16, vertical=0),
        bgcolor=ft.Colors.SURFACE,
        border=ft.Border.only(
            bottom=ft.BorderSide(1, 取色('border-subtle'))
        ),
    )
    登记重刷(app_icon, lambda c: (
        setattr(c, 'bgcolor', 取色('btn-primary-bg')),
        setattr(c.content, 'color', 取色('on-brand')),
    ))
    登记重刷(app_title, lambda c: setattr(c, 'color', 取色('text-primary')))
    return bar


# ====================================================================
# 四、IconRail 类 (220px 宽侧边栏 — 精确还原预览)
# ====================================================================

class IconRail:
    """220px 宽侧边导航栏 — 苹果风格, 自定义按钮

    API:
      - IconRail(on_nav=..., on_theme_toggle=...)
      - .toggle_theme_icon(is_dark)
      - .set_active(key)
      - .build()
    """

    def __init__(self, on_nav=None, on_theme_toggle=None):
        self._on_nav = on_nav
        self._on_theme_toggle = on_theme_toggle
        self._active_key = 'crawl'
        self._is_dark = False
        self._nav_buttons = {}
        self._control = None
        self.page = None
        # 状态摘要显示已移至窗口底部全局状态条 (gui_app status_bar),
        # 侧边栏不再重复渲染状态指示器

    def set_active(self, key: str):
        self._active_key = key
        for k, btn in self._nav_buttons.items():
            self._update_btn_style(btn, k == key)
        try:
            if self._control:
                self._control.update()
        except Exception as _e:
            _dbg("导航栏", f'裸 except 吞异常: {type(_e).__name__}: {_e}')

    def toggle_theme_icon(self, is_dark: bool):
        """主题切换同步点 (gui_app.toggle_theme 在 page.theme_mode 赋值后
        调用本方法)。

        做两件事:
          1. 同步 ui_tokens 的主题状态 + 触发所有已登记控件换色
          2. 刷新本侧栏自己的导航项配色
        主题按钮文案/图标的刷新由 build_theme_toggle.update_theme_state
        负责 (gui_app 另行调用), 此处只管配色。
        """
        同步主题(bool(is_dark))
        for k, btn in self._nav_buttons.items():
            self._update_btn_style(btn, k == self._active_key)
        try:
            if self._control:
                self._control.update()
        except Exception as _e:
            _dbg("导航栏", f'裸 except 吞异常: {type(_e).__name__}: {_e}')

    def _update_btn_style(self, btn, is_active: bool):
        """更新导航按钮选中/未选中样式 (暖色: 选中=浅橙底 + 橙字)

        设计稿 --bg-sidebar-active 日#FAF1E7/夜#382614,
                 --text-sidebar-active 日#9C4A0C/夜#E8A96A
        """
        icon_ctrl = btn.content.controls[0]
        label_ctrl = btn.content.controls[1]

        if is_active:
            btn.bgcolor = 取色('bg-sidebar-active')
            icon_ctrl.color = 取色('text-sidebar-active')
            label_ctrl.color = 取色('text-sidebar-active')
            label_ctrl.weight = WEIGHT_SUBTITLE
        else:
            btn.bgcolor = None
            icon_ctrl.color = 取色('text-tertiary')
            label_ctrl.color = 取色('text-primary')
            label_ctrl.weight = WEIGHT_BODY

    def _make_nav_btn(self, key, icon, label):
        """构建单个导航按钮 (220px 宽, icon + 文字, 圆角 4px = --radius-sm)"""
        icon_ctrl = ft.Icon(icon, size=18, color=取色('text-tertiary'))
        label_ctrl = txt(label, size=SIZE_BODY, color=取色('text-primary'))

        btn = ft.Container(
            content=ft.Row(
                [icon_ctrl, label_ctrl],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=12, vertical=8),
            border_radius=ui_tokens.RADIUS_SM,
            on_click=lambda e, k=key: self._on_btn_click(k),
            on_hover=self._on_nav_hover,
            tooltip=label,
        )
        btn._key = key
        btn._icon_ref = icon_ctrl
        btn._label_ref = label_ctrl
        self._nav_buttons[key] = btn

        self._update_btn_style(btn, key == self._active_key)

        # 登记重刷: 切主题时导航项也要换色 (Container 无 on_focus, 但换色
        # 由 IconRail.toggle_theme_icon 统一驱动, 这里只登记不驱动)
        选中键 = key
        def _换色(c):
            self._update_btn_style(c, 选中键 == self._active_key)
        登记重刷(btn, _换色)
        return btn

    def _on_btn_click(self, key: str):
        self._active_key = key
        # 更新所有按钮样式
        for k, btn in self._nav_buttons.items():
            self._update_btn_style(btn, k == key)
        try:
            if self._control:
                self._control.update()
        except Exception as _e:
            _dbg("导航栏", f'裸 except 吞异常: {type(_e).__name__}: {_e}')
        if self._on_nav:
            self._on_nav(key)

    def _on_nav_hover(self, e):
        try:
            btn = e.control
            is_active = btn._key == self._active_key
            if e.data == 'true' and not is_active:
                btn.bgcolor = 取色('bg-sidebar-hover')
            else:
                self._update_btn_style(btn, is_active)
            btn.update()
        except Exception as _e:
            _dbg("导航栏", f'裸 except 吞异常: {type(_e).__name__}: {_e}')

    def build(self) -> ft.Control:
        """构建 220px 宽侧边栏"""
        # 分区标题 (--fs-micro 11px + 600)
        section_title = txt('主功能', size=ui_tokens.FS_MICRO,
                            weight=WEIGHT_SUBTITLE,
                            color=取色('text-tertiary'))

        # 导航按钮列表
        nav_btns = [self._make_nav_btn(k, ic, lb) for k, ic, lb, _ in NAV_PAGES]

        # 组合: 分区标题 + 导航按钮 + 弹性留白
        # (状态摘要显示已移至窗口底部全局状态条, 侧边栏不再重复)
        body = ft.Column(
            [
                ft.Container(
                    content=section_title,
                    padding=ft.Padding.symmetric(horizontal=12, vertical=4),
                ),
                *nav_btns,
                ft.Container(expand=True),
            ],
            spacing=2,
            expand=True,
        )

        侧栏 = ft.Container(
            content=body,
            width=220,
            # 注意: 不能同时设 expand=True — Row 中 expand 会使 width 失效,
            # 侧栏被拉成窗口一半 (历史遗留 Bug, 曾把内容区挤压一半)
            bgcolor=取色('bg-sidebar'),
            padding=ft.Padding.symmetric(horizontal=8, vertical=12),
        )
        # 侧栏底色 + 分区标题随主题重刷
        登记重刷(侧栏, lambda c: setattr(c, 'bgcolor', 取色('bg-sidebar')))
        登记重刷(section_title, lambda c: setattr(c, 'color', 取色('text-tertiary')))

        self._control = 侧栏
        return self._control
