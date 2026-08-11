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

# ---- PyInstaller 打包后 Flet client 路径修正 ----
# flet pack 不会自动把 Flet client 打进 EXE，运行时会尝试在线下载（超时崩溃）
# 这里手动把 _flet_client/ 通过 --add-data 嵌入，并在运行时指向它
if getattr(sys, "frozen", False):
    _meipass = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    _bundled_flet_client = os.path.join(_meipass, "flet_client")
    if os.path.isdir(_bundled_flet_client):
        os.environ["FLET_VIEW_PATH"] = _bundled_flet_client

from gui_components.task_manager import TaskManager
from gui_components.crawl_tab import CrawlTab
from gui_components.preview_tab import PreviewTab
from gui_components.config_tab import ConfigTab

# 打包后路径约定（源码/EXE 双模式）
from _path_utils import get_default_output_dir  # noqa: E402

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
        if int(e.data) == 1:  # 结果预览
            preview_tab._refresh_file_list()
            try:
                page.update()
            except Exception:
                pass
        elif int(e.data) == 2:  # 站点配置
            try:
                page.update()
            except Exception:
                pass

    # Flet 0.86+ API: Tabs 包含 TabBar(标签栏) + TabBarView(内容区)
    tabs = ft.Tabs(
        length=3,
        selected_index=0,
        on_change=on_tab_change,
        expand=True,
        content=ft.Column(
            expand=True,
            controls=[
                ft.TabBar(
                    tabs=[
                        ft.Tab(label="抓取"),
                        ft.Tab(label="结果预览"),
                        ft.Tab(label="站点配置"),
                    ],
                    scrollable=False,
                    tab_alignment=ft.TabAlignment.FILL,
                ),
                ft.TabBarView(
                    expand=True,
                    controls=[
                        crawl_tab.build(),
                        preview_tab.build(),
                        config_tab.build(),
                    ],
                ),
            ],
        ),
    )

    # 底部状态栏
    # - 开发模式 (python gui_app.py)         : 项目根/抓取结果
    # - PyInstaller onefile (小说爬虫.exe)   : EXE 所在目录/抓取结果
    output_dir = get_default_output_dir()

    status_bar = ft.Container(
        content=ft.Row([
            ft.Icon(ft.Icons.CIRCLE, color=ft.Colors.GREEN, size=8),
            ft.Text("就绪", size=11),
            ft.VerticalDivider(width=1),
            ft.Text(f"输出: {output_dir}", size=11, color=ft.Colors.GREY_600),
        ]),
        padding=ft.Padding.symmetric(horizontal=10, vertical=4),
        bgcolor=ft.Colors.GREY_100,
    )

    page.add(tabs, status_bar)

    # 保存 page 引用到 crawl_tab 以便后续更新
    crawl_tab.page = page


if __name__ == "__main__":
    ft.run(main)
