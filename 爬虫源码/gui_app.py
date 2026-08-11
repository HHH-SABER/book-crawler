# -*- coding: utf-8 -*-
"""小说爬虫 GUI 主程序

基于 Flet 框架，提供图形化界面替代 BAT 脚本。
包含三个页签：抓取 / 结果预览 / 站点配置
"""
import flet as ft
import sys
import os

# 添加当前目录到 path，确保能 import GUI 组件和爬虫模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui_components.task_manager import TaskManager
from gui_components.crawl_tab import CrawlTab
from gui_components.preview_tab import PreviewTab
from gui_components.config_tab import ConfigTab

# ---------------------------------------------------- PyInstaller 打包友好
# 显式 import 核心爬虫模块，让 PyInstaller 静态分析能发现依赖树，
# 避免通过 --hidden-import 传递中文模块名时的编码问题。
# 真实的抓取执行在 task_manager._run_task 的子线程中再次 import，
# 这里只用于打包时的依赖收集；缺依赖时 GUI 仍可正常启动（只是抓取会失败）。
try:
    import 爬虫  # noqa: F401  (PyInstaller 打包时会追踪此 import)
    import sites_config  # noqa: F401
    import browser_driver  # noqa: F401
    import captcha_module  # noqa: F401
    import content_decoder  # noqa: F401
    import decrypt_utils  # noqa: F401
    import tanmixs_xs  # noqa: F401
    import gui_components.task_manager  # noqa: F401
    import gui_components.crawl_tab  # noqa: F401
    import gui_components.preview_tab  # noqa: F401
    import gui_components.config_tab  # noqa: F401
except Exception:
    # 允许在未装所有爬虫依赖时 GUI 仍可启动（可预览/配置，抓取按钮点时报错）
    pass


def main(page: ft.Page):
    """Flet 应用入口"""
    page.title = "小说爬虫"
    page.window.width = 1200
    page.window.height = 750
    page.window.min_width = 900
    page.window.min_height = 600
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0

    # 全局任务管理器
    task_manager = TaskManager(page)

    # 三个页签组件
    crawl_tab = CrawlTab(task_manager)
    preview_tab = PreviewTab()
    config_tab = ConfigTab()

    # 页签切换时刷新对应内容
    def on_tab_change(e):
        if e.data == "1":  # 结果预览
            preview_tab._refresh_file_list()
            try:
                page.update()
            except Exception:
                pass
        elif e.data == "2":  # 站点配置
            try:
                page.update()
            except Exception:
                pass

    tabs = ft.Tabs(
        selected_index=0,
        on_change=on_tab_change,
        tabs=[
            ft.Tab(text="抓取", content=crawl_tab.build()),
            ft.Tab(text="结果预览", content=preview_tab.build()),
            ft.Tab(text="站点配置", content=config_tab.build()),
        ],
        expand=True,
    )

    # 底部状态栏
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.normpath(os.path.join(script_dir, "..", "抓取结果"))

    status_bar = ft.Container(
        content=ft.Row([
            ft.Icon(ft.icons.CIRCLE, color=ft.colors.GREEN, size=8),
            ft.Text("就绪", size=11),
            ft.VerticalDivider(width=1),
            ft.Text(f"输出: {output_dir}", size=11, color=ft.colors.GREY_600),
        ]),
        padding=ft.padding.symmetric(horizontal=10, vertical=4),
        bgcolor=ft.colors.GREY_100,
    )

    page.add(tabs, status_bar)

    # 保存 page 引用到 crawl_tab 以便后续更新
    crawl_tab.page = page


if __name__ == "__main__":
    ft.app(target=main)
