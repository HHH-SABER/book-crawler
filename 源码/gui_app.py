# -*- coding: utf-8 -*-
"""小说爬虫 GUI 主程序 (苹果风格界面)

基于 Flet 框架。布局:
  顶栏 (52px): macOS 交通灯 + 居中应用标题 + 右侧主题切换
  + 侧边栏 (220px): 图标+文字导航 + 底部状态指示器
  + 主内容区 (抓取工作台: 输入条 + 任务表格 + 可折叠日志条 + 右侧上下文抽屉)
  + 底部状态栏 (实时任务汇总)
支持日间/夜间双主题切换。
"""
import flet as ft
import sys
import os
import time

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
from gui_components.icon_rail import IconRail, NAV_PAGES, build_theme_toggle, build_top_bar
import threading
from gui_components.ui_theme import page_header
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
    import epub_exporter  # noqa: F401  (EPUB 导出, ebooklib 依赖收集)
    import ebooklib  # noqa: F401
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
    # 窗口尺寸按屏幕自适应 (修复: 写死 1280x800 在小屏/高DPI缩放下内容截断)
    try:
        import ctypes
        _user32 = ctypes.windll.user32
        try:
            _user32.SetProcessDPIAware()
        except Exception:
            pass
        _sw, _sh = _user32.GetSystemMetrics(0), _user32.GetSystemMetrics(1)
    except Exception:
        _sw, _sh = 1920, 1080
    page.window.width = min(1500, max(960, int(_sw * 0.9)))
    page.window.height = min(860, max(640, int(_sh * 0.85)))
    page.window.min_width = 1100
    page.window.min_height = 640
    # 居中: 用 flet 官方 center() 在窗口就绪后调用。旧实现用 GetSystemMetrics
    # 手算坐标, 与原生窗口创建存在竞态且只算主屏 (多显示器下偏移), 导致启动不居中
    async def _center_window():
        try:
            await page.window.wait_until_ready_to_show()
            await page.window.center()
        except Exception as e:
            app_log.debug("系统", f"窗口居中失败 (不阻断启动): {e}")
    page.run_task(_center_window)
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0
    # 莫兰迪主题：低饱和度柔和配色，深浅双主题，长时间阅读不刺眼
    from gui_components.ui_morandi import (
        make_morandi_theme, make_morandi_dark_theme,
        FONT_STACK, SIZE_SMALL, WEIGHT_BODY,
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
    _theme_toggle_btn = [None]  # 顶栏主题切换按钮引用

    def toggle_theme():
        _theme_dark[0] = not _theme_dark[0]
        page.theme_mode = ft.ThemeMode.DARK if _theme_dark[0] else ft.ThemeMode.LIGHT
        rail.toggle_theme_icon(_theme_dark[0])
        # 同步更新顶栏主题切换按钮
        if _theme_toggle_btn[0] and hasattr(_theme_toggle_btn[0], 'update_theme_state'):
            _theme_toggle_btn[0].update_theme_state(_theme_dark[0])
        app_log.info("系统", f"主题切换为: {'深色' if _theme_dark[0] else '浅色'}")
        page.update()

    # ---- 图标导航栏 ----
    rail = IconRail(on_nav=lambda key: _switch_page(key),
                    task_manager=task_manager,
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
            page_header('抓取工作台', '输入小说目录页URL，自动识别站点并开始抓取'),
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
    history_page.task_manager = task_manager   # 一键更新书架需创建任务
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

    # 底部状态条: 实时任务摘要 (唯一状态显示处; 侧边栏不再重复渲染)
    status_dot = ft.Icon(ft.Icons.CIRCLE, color=MORANDI_SUCCESS, size=8)
    status_text = ft.Text("就绪", size=SIZE_SMALL, weight=WEIGHT_BODY,
                          font_family=FONT_STACK)
    status_bar = ft.Container(
        content=ft.Row([
            status_dot,
            status_text,
            ft.VerticalDivider(width=1),
            ft.Text(f"输出目录: {output_dir}", size=SIZE_SMALL,
                    weight=WEIGHT_BODY,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                    font_family=FONT_STACK),
        ]),
        padding=ft.Padding.symmetric(horizontal=12, vertical=4),
        bgcolor=ft.Colors.SURFACE_CONTAINER,
        border=ft.Border(top=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)),
    )

    # 守护线程每 2s 刷新状态摘要: "运行 N · 共 M" / "就绪 · 共 M"
    def _status_refresh_loop():
        while True:
            try:
                # 注意: tasks 是 {task_id: TaskInfo} 字典, 必须取 values()
                # (旧实现直接遍历字典得到的是 key 字符串, 永远统计为 0 运行)
                tasks = list(getattr(task_manager, 'tasks', {}).values())
                running = sum(1 for t in tasks
                              if (getattr(t, 'status', '') or '') in
                              ('running', 'queued', 'crawling'))
                total = len(tasks)
                if running > 0:
                    status_text.value = f"抓取中 {running} 项 · 共 {total}"
                    status_dot.color = MORANDI_RUNNING
                else:
                    status_text.value = (f"就绪 · 共 {total}" if total else "就绪")
                    status_dot.color = MORANDI_SUCCESS
                page.update()
            except Exception:
                pass
            time.sleep(2)

    threading.Thread(target=_status_refresh_loop, daemon=True,
                     name='status_bar_refresh').start()

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

    # ---- 顶栏 (苹果风格: 标题 + 醒目主题切换按钮) ----
    _theme_toggle_btn[0] = build_theme_toggle(page, 'light', toggle_theme)
    top_bar = build_top_bar(page, '小说爬虫', _theme_toggle_btn[0])

    # ---- 整体布局 (Fluent 三段式: 顶栏 + 侧边导航 + 主内容) ----
    main_row = ft.Row([
        rail.build(),
        # 主内容区: Fluent 平涂底色 (日间 #F3F3F3 / 夜间 #202020, 由主题解析)
        ft.Container(
            content=ft.Container(
                content=content_stack, expand=True,
                padding=ft.Padding.symmetric(horizontal=20, vertical=16),
            ),
            expand=True,
            bgcolor=ft.Colors.SURFACE_CONTAINER,
        ),
    ], expand=True, spacing=0, vertical_alignment=ft.CrossAxisAlignment.STRETCH)

    page.add(
        ft.Column(
            [top_bar, main_row, status_bar],
            spacing=0,
            expand=True,
        ),
    )

    # 退出时: 先停掉全部运行中任务 (置位 stop_event, 爬虫循环会保存检查点并
    # 优雅退出, 避免 "cannot schedule new futures after interpreter shutdown"),
    # 再关闭日志句柄
    def _on_disconnect(e):
        try:
            for t in task_manager.get_all_tasks():
                if t.status in ("running", "pending"):
                    t.stop_flag.set()
        except Exception:
            pass
        try:
            app_log.close()
        except Exception:
            pass
    try:
        page.on_disconnect = _on_disconnect
    except Exception:
        pass


if __name__ == "__main__":
    ft.run(main)
