# -*- coding: utf-8 -*-
"""图标导航栏：64px 窄栏, 4 个页面入口 + 主题切换

替代原 200px 文字侧边栏, 释放横向空间给主内容区。
悬停显示 tooltip (Flet 原生), 选中态用主色容器高亮。
"""
import flet as ft

from .ui_morandi import MORANDI_PRIMARY

# 页面定义: (key, 图标, 选中图标, 标题)
NAV_PAGES = [
    ("crawl",   ft.Icons.DOWNLOAD_OUTLINED,   ft.Icons.DOWNLOAD,   "抓取工作台"),
    ("history", ft.Icons.HISTORY_OUTLINED,    ft.Icons.HISTORY,    "爬取历史"),
    ("sites",   ft.Icons.DNS_OUTLINED,        ft.Icons.DNS,        "站点管理"),
    ("log",     ft.Icons.TERMINAL_OUTLINED,   ft.Icons.TERMINAL,   "运行日志"),
]


class IconRail:
    """图标导航栏组件"""

    def __init__(self, on_nav: callable, on_theme_toggle: callable):
        """
        Args:
            on_nav: 页面切换回调, 签名 callback(page_key: str)
            on_theme_toggle: 主题切换回调, 签名 callback()
        """
        self._on_nav = on_nav
        self._on_theme_toggle = on_theme_toggle
        self._current = "crawl"
        self._items: dict[str, ft.Container] = {}
        self._theme_icon = ft.IconButton(
            icon=ft.Icons.DARK_MODE_OUTLINED,
            icon_size=18,
            tooltip="切换深色/浅色主题",
            on_click=lambda e: self._on_theme_toggle(),
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=8),
                color=ft.Colors.ON_SURFACE_VARIANT,
            ),
        )

    def build(self) -> ft.Control:
        """构建图标栏 (宽 56px)"""
        for key, icon, icon_sel, title in NAV_PAGES:
            self._items[key] = self._make_item(key, icon, title)
        self._apply_active()

        return ft.Container(
            content=ft.Column(
                [
                    # 应用图标 (顶部品牌位)
                    ft.Container(
                        content=ft.Icon(ft.Icons.AUTO_STORIES,
                                        size=22, color=MORANDI_PRIMARY),
                        width=36, height=36,
                        alignment=ft.Alignment(0, 0),
                        bgcolor=ft.Colors.PRIMARY_CONTAINER,
                        border_radius=10,
                    ),
                    ft.Container(height=8),
                    *[self._items[k] for k, _, _, _ in NAV_PAGES],
                    ft.Container(expand=True),
                    ft.Divider(height=1),
                    self._theme_icon,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=4,
            ),
            width=56,
            padding=ft.Padding.symmetric(horizontal=6, vertical=10),
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
            border=ft.Border(right=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)),
        )

    def _make_item(self, key: str, icon: str, title: str) -> ft.Container:
        """单个导航图标项"""
        return ft.Container(
            content=ft.Icon(icon, size=20, color=ft.Colors.ON_SURFACE_VARIANT),
            width=40, height=40,
            alignment=ft.Alignment(0, 0),
            border_radius=10,
            ink=True,
            tooltip=title,
            on_click=lambda e, k=key: self._on_nav(k),
        )

    def _apply_active(self):
        """按当前页面高亮对应图标"""
        for key, item in self._items.items():
            if key == self._current:
                item.bgcolor = ft.Colors.PRIMARY_CONTAINER
                if item.content is not None:
                    item.content.color = MORANDI_PRIMARY
            else:
                item.bgcolor = None
                if item.content is not None:
                    item.content.color = ft.Colors.ON_SURFACE_VARIANT

    def set_active(self, key: str, page=None):
        """切换高亮页面 (主线程调用; 传 page 则立即刷新)"""
        if key not in dict((k, 1) for k, *_ in NAV_PAGES):
            return
        if key == self._current:
            return
        self._current = key
        self._apply_active()
        if page is not None:
            try:
                page.update()
            except Exception:
                pass

    def toggle_theme_icon(self, dark: bool):
        """切换主题图标形态"""
        self._theme_icon.icon = (ft.Icons.LIGHT_MODE_OUTLINED if dark
                                 else ft.Icons.DARK_MODE_OUTLINED)
