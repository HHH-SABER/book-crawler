# -*- coding: utf-8 -*-
"""Windows 11 Fluent 风格 220px 侧边导航栏 + 顶栏 (方案 A, 还原设计预览)

布局结构 (与 index.html 一致):
  ┌────────────────────────┐
  │  主功能                  │  ← 分区标题
  │  ⬇  抓取工作台           │  ← 选中态: 浅蓝底 + 蓝字
  │  📊  爬取历史            │
  │  🌐  站点管理            │
  │  📝  运行日志            │
  │  (弹性留白)              │
  │  ──────────────────     │
  │  🟢 抓取中 · 2 项        │  ← 底部状态指示器
  └────────────────────────┘

宽度 220px, 背景 #F1F1F1 (日间) / #171717 (夜间)
导航项: icon(18px) + 文字(14px), 圆角 4px, 选中态浅蓝底蓝字
"""
import flet as ft
import threading

from .ui_morandi import (
    txt, SIZE_TINY, SIZE_BODY, SIZE_SMALL,
    WEIGHT_SUBTITLE, WEIGHT_BODY, WEIGHT_EMPHASIS,
    MORANDI_SIDEBAR_BG, MORANDI_SIDEBAR_HOVER, MORANDI_SIDEBAR_ACTIVE,
)


# ====================================================================
# 一、导航页定义
# ====================================================================
NAV_PAGES = [
    ('crawl',   ft.Icons.DOWNLOADING_OUTLINED,   '抓取工作台', 0),
    ('history', ft.Icons.HISTORY,                '爬取历史',   1),
    ('sites',   ft.Icons.LANGUAGE,               '站点管理',   2),
    ('log',     ft.Icons.SPEED,                  '运行日志',   3),
]

PAGE_TITLES = {
    'crawl':   '抓取工作台',
    'history': '爬取历史',
    'sites':   '站点管理',
    'log':     '运行日志',
}

PAGE_SUBTITLES = {
    'crawl':   '输入小说目录页URL，自动识别站点并开始抓取',
    'history': '查看历史抓取记录与统计',
    'sites':   '管理站点适配器与风控策略',
    'log':     '查看实时运行日志与错误信息',
}


# ====================================================================
# 二、主题切换按钮 (顶栏用 — 胶囊形 + 图标 + 文字)
# ====================================================================

def build_theme_toggle(page, current_mode: str, on_toggle) -> ft.Container:
    """构建醒目的主题切换按钮 (胶囊形, 精确还原预览样式)

    样式: padding 6×12, 圆角 999px, 背景 terciary, 边框 subtle
    """
    is_dark = current_mode == 'dark'
    icon_name = ft.Icons.DARK_MODE_ROUNDED if is_dark else ft.Icons.LIGHT_MODE_ROUNDED
    label = '夜间' if is_dark else '日间'

    icon = ft.Icon(icon_name, size=16, color=ft.Colors.ON_SURFACE_VARIANT)
    label_text = txt(label, size=SIZE_TINY, color=ft.Colors.ON_SURFACE_VARIANT,
                     weight=WEIGHT_EMPHASIS)

    btn = ft.Container(
        content=ft.Row(
            [icon, label_text],
            spacing=8,
            alignment=ft.MainAxisAlignment.CENTER,
        ),
        padding=ft.Padding.symmetric(horizontal=12, vertical=6),
        bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
        border_radius=999,
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
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
        except Exception:
            pass

    btn.update_theme_state = update_theme_state
    return btn


# ====================================================================
# 三、顶栏 (Fluent: 应用图标 + 标题居左 + 右侧主题切换)
# ====================================================================

def build_top_bar(page, title_text: str, theme_toggle_btn) -> ft.Container:
    """构建 Fluent 顶栏 (48px 高, 匹配设计稿 titlebar)

    布局: [📖 小说爬虫] ──────────────────── [🌙 夜间]
    """
    # 左侧: 应用图标 (Fluent 蓝底圆角) + 应用名
    app_icon = ft.Container(
        content=ft.Icon(ft.Icons.MENU_BOOK_OUTLINED, size=14, color=ft.Colors.WHITE),
        width=24, height=24,
        border_radius=4,
        bgcolor=ft.Colors.PRIMARY,
        alignment=ft.Alignment.CENTER,
    )
    app_title = txt(title_text, size=SIZE_BODY, weight=WEIGHT_SUBTITLE,
                    color=ft.Colors.ON_SURFACE)

    bar = ft.Container(
        content=ft.Row(
            [app_icon, app_title, ft.Container(expand=True), theme_toggle_btn],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        height=48,
        padding=ft.Padding.symmetric(horizontal=16, vertical=0),
        bgcolor=ft.Colors.SURFACE,
        border=ft.Border.only(
            bottom=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)
        ),
    )
    return bar


# ====================================================================
# 四、IconRail 类 (220px 宽侧边栏 — 精确还原预览)
# ====================================================================

class IconRail:
    """220px 宽侧边导航栏 — 苹果风格, 自定义按钮

    兼容旧 API:
      - IconRail(on_nav=..., on_theme_toggle=...)
      - .toggle_theme_icon(is_dark)
      - .set_active(key)
      - .build()
    """

    def __init__(self, on_nav=None, on_theme_toggle=None, task_manager=None):
        self._on_nav = on_nav
        self._on_theme_toggle = on_theme_toggle
        self._active_key = 'crawl'
        self._is_dark = False
        self._nav_buttons = {}
        self._control = None
        self.page = None
        # 状态摘要显示已移至窗口底部全局状态条 (gui_app status_bar),
        # 侧边栏不再重复渲染状态指示器
        self._task_manager = task_manager

    def set_active(self, key: str):
        self._active_key = key
        for k, btn in self._nav_buttons.items():
            self._update_btn_style(btn, k == key)
        try:
            if self._control:
                self._control.update()
        except Exception:
            pass

    def toggle_theme_icon(self, is_dark: bool):
        # 兼容保留: 主题按钮的实际刷新由 build_theme_toggle.update_theme_state
        # 负责 (gui_app toggle_theme 中调用), 此处仅同步内部状态标记
        self._is_dark = is_dark

    def _update_btn_style(self, btn, is_active: bool):
        """更新导航按钮选中/未选中样式 (Fluent: 选中=浅蓝底蓝字)"""
        icon_ctrl = btn.content.controls[0]
        label_ctrl = btn.content.controls[1]

        if is_active:
            btn.bgcolor = MORANDI_SIDEBAR_ACTIVE
            icon_ctrl.color = ft.Colors.PRIMARY
            label_ctrl.color = ft.Colors.PRIMARY
            label_ctrl.weight = WEIGHT_SUBTITLE
        else:
            btn.bgcolor = None
            icon_ctrl.color = ft.Colors.ON_SURFACE_VARIANT
            label_ctrl.color = ft.Colors.ON_SURFACE
            label_ctrl.weight = WEIGHT_BODY

    def _make_nav_btn(self, key, icon, label):
        """构建单个导航按钮 (220px 宽, icon + 文字, Fluent 4px 圆角)"""
        icon_ctrl = ft.Icon(icon, size=18, color=ft.Colors.ON_SURFACE_VARIANT)
        label_ctrl = txt(label, size=SIZE_BODY, color=ft.Colors.ON_SURFACE)

        btn = ft.Container(
            content=ft.Row(
                [icon_ctrl, label_ctrl],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=12, vertical=8),
            border_radius=4,
            on_click=lambda e, k=key: self._on_btn_click(k),
            on_hover=self._on_nav_hover,
            tooltip=label,
        )
        btn._key = key
        btn._icon_ref = icon_ctrl
        btn._label_ref = label_ctrl
        self._nav_buttons[key] = btn

        self._update_btn_style(btn, key == self._active_key)
        return btn

    def _on_btn_click(self, key: str):
        self._active_key = key
        # 更新所有按钮样式
        for k, btn in self._nav_buttons.items():
            self._update_btn_style(btn, k == key)
        try:
            if self._control:
                self._control.update()
        except Exception:
            pass
        if self._on_nav:
            self._on_nav(key)

    def _on_nav_hover(self, e):
        try:
            btn = e.control
            is_active = btn._key == self._active_key
            if e.data == 'true' and not is_active:
                btn.bgcolor = MORANDI_SIDEBAR_HOVER
            else:
                self._update_btn_style(btn, is_active)
            btn.update()
        except Exception:
            pass

    def build(self) -> ft.Control:
        """构建 220px 宽侧边栏"""
        # 分区标题
        section_title = txt('主功能', size=11, weight=WEIGHT_SUBTITLE,
                            color=ft.Colors.ON_SURFACE_VARIANT)

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

        self._control = ft.Container(
            content=body,
            width=220,
            # 注意: 不能同时设 expand=True — Row 中 expand 会使 width 失效,
            # 侧栏被拉成窗口一半 (历史遗留 Bug, 曾把内容区挤压一半)
            bgcolor=MORANDI_SIDEBAR_BG,
            padding=ft.Padding.symmetric(horizontal=8, vertical=12),
        )
        return self._control
