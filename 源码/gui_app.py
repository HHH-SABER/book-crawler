# -*- coding: utf-8 -*-
"""小说爬虫 GUI 主程序 (v3 紧凑信息密度布局)

基于 Flet 框架。布局:
  左侧 56px 图标导航栏 (抓取 / 历史 / 站点管理 / 日志)
  + 主内容区 (抓取工作台: 输入条 + 任务表格 + 可折叠日志条 + 右侧上下文抽屉)
  + 底部状态栏 (实时任务汇总)
支持深色/浅色双主题切换。
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
from gui_components.icon_rail import IconRail, NAV_PAGES
from gui_components.input_bar import InputBar
from gui_components.task_table import TaskTable
from gui_components.log_strip import LogStrip
from gui_components.detail_drawer import DetailDrawer
from gui_components.log_tab import LogTab
from gui_components.pages.history_page import HistoryPage
from gui_components.pages.site_manage_page import SiteManagePage

# 打包后路径约定（源码/EXE 双模式）
from _path_utils import get_default_output_dir  # noqa: E402

# 统一日志模块: 启动记录 + 全局未捕获异常写日志
import 日志 as app_log  # noqa: E402
app_log.install_global_excepthook()

# ---------------------------------------------------- PyInstaller 打包友好
# 显式 import 核心爬虫模块，让 PyInstaller 静态分析能发现依赖树，
# 避免通过 --hidden-import 传递中文模块名时的编码问题。
# 真实的抓取执行在 task_manager._run_task 的子线程中再次 import，
# 这里只用于打包时的依赖收集；缺依赖时 GUI 仍可正常启动（只是抓取会失败）。
try:
    import 爬虫  # noqa: F401  (PyInstaller 打包时会追踪此 import)
    import sites_config  # noqa: F401
    import site_probe  # noqa: F401  (站点管理页测试连接)
    import browser_driver  # noqa: F401
    import captcha_module  # noqa: F401
    import content_decoder  # noqa: F401
    import decrypt_utils  # noqa: F401
    import waf_captcha  # noqa: F401  (WAF 验证码自动解决, banlvzw 等)
    import gui_components.task_manager  # noqa: F401
    import gui_components.icon_rail  # noqa: F401
    import gui_components.input_bar  # noqa: F401
    import gui_components.task_table  # noqa: F401
    import gui_components.log_strip  # noqa: F401
    import gui_components.detail_drawer  # noqa: F401
    import gui_components.row_detail  # noqa: F401
    import gui_components.log_tab  # noqa: F401
    import gui_components.ui_theme  # noqa: F401
    import gui_components.pages.history_data  # noqa: F401
    import gui_components.pages.history_page  # noqa: F401
    import gui_components.pages.site_manage_page  # noqa: F401
except Exception:
    # 允许在未装所有爬虫依赖时 GUI 仍可启动（可预览/配置，抓取按钮点时报错）
    pass


def main(page: ft.Page):
    """Flet 应用入口"""
    page.title = "小说爬虫"
    page.window.width = 1280
    page.window.height = 800
    page.window.min_width = 960
    page.window.min_height = 640
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0
    # 莫兰迪主题：低饱和度柔和配色，深浅双主题，长时间阅读不刺眼
    from gui_components.ui_morandi import (
        make_morandi_theme, make_morandi_dark_theme,
        FONT_STACK, SIZE_TITLE, SIZE_SMALL, WEIGHT_TITLE, WEIGHT_BODY,
        MORANDI_SUCCESS, MORANDI_ERROR, MORANDI_RUNNING,
    )
    page.theme = make_morandi_theme()
    page.dark_theme = make_morandi_dark_theme()

    # 启动日志: 记录系统信息 (便于事后排查版本/环境问题)
    try:
        import platform
        _mode = "PyInstaller EXE" if getattr(sys, "frozen", False) else "源码模式"
        app_log.info("系统", f"程序启动 (模式: {_mode}, Python {platform.python_version()})")
        app_log.info("系统", f"EXE/项目目录: {os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, 'frozen', False) else os.getcwd()}")
    except Exception:
        pass

    # ---- 全局任务管理器 ----
    task_manager = TaskManager(page)

    # ---- 主题切换 ----
    _theme_dark = [False]

    def toggle_theme():
        _theme_dark[0] = not _theme_dark[0]
        page.theme_mode = ft.ThemeMode.DARK if _theme_dark[0] else ft.ThemeMode.LIGHT
        rail.toggle_theme_icon(_theme_dark[0])
        app_log.info("系统", f"主题切换为: {'深色' if _theme_dark[0] else '浅色'}")
        page.update()

    # ---- 图标导航栏 ----
    rail = IconRail(on_nav=lambda key: _switch_page(key),
                    on_theme_toggle=toggle_theme)

    # ---- 抓取工作台: 输入条 + 任务表格 + 日志条 + 抽屉 ----
    input_bar = InputBar(task_manager)
    task_table = TaskTable(task_manager)
    log_strip = LogStrip(task_manager)
    drawer = DetailDrawer(task_manager)

    file_picker = ft.FilePicker()
    input_bar.file_picker = file_picker

    def _on_task_created():
        """新任务创建后立即刷新表格"""
        task_table._refresh()
        page.update()

    input_bar.on_task_created = _on_task_created
    input_bar.page = page
    task_table.page = page
    log_strip.page = page
    drawer.page = page

    # 任务表格行点击 → 选中 (日志条/抽屉自动跟随); 预览按钮 → 打开抽屉
    task_table.on_open_preview = lambda tid: drawer.open("preview", tid)

    crawl_workbench = ft.Row([
        ft.Column([
            input_bar.build(),
            ft.Container(content=task_table.build(), expand=True),
            log_strip.build(),
        ], expand=True, spacing=8),
        drawer.build(),
    ], expand=True, spacing=0)

    # ---- 其他三个页面 ----
    history_page = HistoryPage()
    site_page = SiteManagePage()
    log_tab = LogTab()
    history_page.page = page
    site_page.page = page
    log_tab.page = page

    # ---- 页面切换 (Stack 保状态) ----
    pages_map = {
        "crawl": crawl_workbench,
        "history": history_page.build(),
        "sites": site_page.build(),
        "log": log_tab.build(),
    }
    content_stack = ft.Stack(
        controls=[pages_map[k] for k, _, _, _ in NAV_PAGES],
        expand=True)
    page_keys = [k for k, _, _, _ in NAV_PAGES]
    for i, p in enumerate(pages_map.values()):
        p.visible = (i == 0)

    def _switch_page(key: str):
        """切换页面: 导航高亮 + 可见性 + 页面级刷新"""
        if key not in pages_map:
            return
        rail.set_active(key)
        for k, p in pages_map.items():
            p.visible = (k == key)
        if key == "history":
            try:
                history_page.refresh()
            except Exception:
                pass
        elif key == "log":
            try:
                log_tab._reload()
            except Exception:
                pass
        try:
            page.update()
        except Exception:
            pass

    # ---- 底部状态栏 ----
    # - 开发模式 (python gui_app.py)         : 项目根/抓取结果
    # - PyInstaller onefile (小说爬虫.exe)   : EXE 所在目录/抓取结果
    output_dir = get_default_output_dir()

    status_dot = ft.Icon(ft.Icons.CIRCLE, color=MORANDI_SUCCESS, size=8)
    status_text = ft.Text("就绪", size=SIZE_SMALL, weight=WEIGHT_BODY,
                          font_family=FONT_STACK)
    status_bar = ft.Container(
        content=ft.Row([
            status_dot,
            status_text,
            ft.VerticalDivider(width=1),
            ft.Text(f"输出: {output_dir}", size=SIZE_SMALL,
                    weight=WEIGHT_BODY,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                    font_family=FONT_STACK),
        ]),
        padding=ft.Padding.symmetric(horizontal=12, vertical=4),
        bgcolor=ft.Colors.SURFACE_CONTAINER,
        border=ft.Border(top=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)),
    )

    # ---- 主刷新循环 (主线程 async, 1s 周期) ----
    # 抓取工作台的表格/日志条/抽屉统一在此刷新 (仅 crawl 页可见时刷新, 省资源)
    async def _refresh_loop():
        import asyncio
        while True:
            try:
                if pages_map["crawl"].visible:
                    # 三个组件只改控件树, 最后统一 update 一次
                    task_table._refresh()
                    log_strip.refresh()
                    drawer.refresh()
                    page.update()
            except Exception:
                pass
            await asyncio.sleep(1)

    # 状态栏动态刷新: 每秒汇总任务状态
    async def _status_loop():
        import asyncio
        last = ""
        while True:
            try:
                tasks = task_manager.get_all_tasks()
                running = sum(1 for t in tasks if t.status == "running")
                failed = sum(1 for t in tasks if t.status == "failed")
                done = sum(1 for t in tasks if t.status == "completed")
                if running > 0:
                    dot_color, label = MORANDI_RUNNING, f"抓取中 {running} 项"
                    if done:
                        label += f" · 已完成 {done}"
                elif failed and not tasks:
                    dot_color, label = MORANDI_ERROR, "就绪"
                elif failed:
                    dot_color, label = MORANDI_ERROR, f"就绪 · 失败 {failed} 项"
                elif done:
                    dot_color, label = MORANDI_SUCCESS, f"就绪 · 已完成 {done} 项"
                else:
                    dot_color, label = MORANDI_SUCCESS, "就绪"
                if label != last:
                    last = label
                    status_dot.color = dot_color
                    status_text.value = label
                    page.update()
            except Exception:
                pass
            await asyncio.sleep(1)

    page.run_task(_refresh_loop)
    page.run_task(_status_loop)

    # ---- 整体布局 ----
    page.add(
        ft.Row([
            rail.build(),
            # 主内容区: 极淡暖色渐变背景 (左上→右下), 提升层次感
            ft.Container(
                content=ft.Container(
                    content=content_stack, expand=True,
                    padding=ft.Padding.symmetric(horizontal=10, vertical=10),
                ),
                expand=True,
                gradient=ft.LinearGradient(
                    begin=ft.Alignment(-1, -1), end=ft.Alignment(1, 1),
                    colors=[ft.Colors.SURFACE, ft.Colors.SURFACE_CONTAINER_LOW],
                ),
            ),
        ], expand=True, spacing=0),
        status_bar,
    )

    # 退出时关闭日志文件
    try:
        page.on_disconnect = lambda e: app_log.close()
    except Exception:
        pass


if __name__ == "__main__":
    ft.run(main)
