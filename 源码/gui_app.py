# -*- coding: utf-8 -*-
"""小说爬虫 GUI 主程序

基于 Flet 框架，提供图形化界面替代 BAT 脚本。
布局：左侧 NavigationRail 导航 + 右侧内容区（抓取 / 结果预览 / 站点配置 / 运行日志）
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
from gui_components.crawl_tab import CrawlTab
from gui_components.preview_tab import PreviewTab
from gui_components.config_tab import ConfigTab
from gui_components.log_tab import LogTab

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
    import browser_driver  # noqa: F401
    import captcha_module  # noqa: F401
    import content_decoder  # noqa: F401
    import decrypt_utils  # noqa: F401
    import waf_captcha  # noqa: F401  (WAF 验证码自动解决, banlvzw 等)
    import gui_components.task_manager  # noqa: F401
    import gui_components.crawl_tab  # noqa: F401
    import gui_components.preview_tab  # noqa: F401
    import gui_components.config_tab  # noqa: F401
    import gui_components.log_tab  # noqa: F401
    import gui_components.ui_theme  # noqa: F401
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
        FONT_STACK, SIZE_TITLE, SIZE_SUBTITLE, SIZE_LABEL, SIZE_SMALL, SIZE_TINY,
        WEIGHT_TITLE, WEIGHT_SUBTITLE, WEIGHT_BODY,
        MORANDI_SUCCESS, MORANDI_ERROR, MORANDI_RUNNING,
    )
    from gui_components.ui_theme import tonal_btn  # noqa: F401 (预留)
    page.theme = make_morandi_theme()
    page.dark_theme = make_morandi_dark_theme()

    # 全局任务管理器
    task_manager = TaskManager(page)
    # 四个页签组件
    crawl_tab = CrawlTab(task_manager)
    preview_tab = PreviewTab()
    config_tab = ConfigTab()
    log_tab = LogTab()
    # 启动日志: 记录系统信息 (便于事后排查版本/环境问题)
    try:
        import platform
        _mode = "PyInstaller EXE" if getattr(sys, "frozen", False) else "源码模式"
        app_log.info("系统", f"程序启动 (模式: {_mode}, Python {platform.python_version()})")
        app_log.info("系统", f"EXE/项目目录: {os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, 'frozen', False) else os.getcwd()}")
    except Exception:
        pass

    # 文件选择器 (导入网址清单用)
    # Flet 0.86: FilePicker 是 Service, 在页面上下文中实例化即自动注册,
    # 通过 await pick_files() 直接获取文件列表 (无 on_result 回调 / overlay 挂载)
    crawl_tab.file_picker = ft.FilePicker()

    # ---- 四个页面内容 (Stack 切换, 保留各页状态) ----
    pages = [
        crawl_tab.build(),
        preview_tab.build(),
        config_tab.build(),
        log_tab.build(),
    ]
    content_stack = ft.Stack(controls=pages, expand=True)
    for i, p in enumerate(pages):
        p.visible = (i == 0)

    # ---- 主题切换 ----
    _theme_dark = [False]

    def toggle_theme(e):
        _theme_dark[0] = not _theme_dark[0]
        page.theme_mode = ft.ThemeMode.DARK if _theme_dark[0] else ft.ThemeMode.LIGHT
        theme_btn.icon = (ft.Icons.LIGHT_MODE_OUTLINED if _theme_dark[0]
                          else ft.Icons.DARK_MODE_OUTLINED)
        theme_btn.tooltip = "切换为浅色主题" if _theme_dark[0] else "切换为深色主题"
        app_log.info("系统", f"主题切换为: {'深色' if _theme_dark[0] else '浅色'}")
        page.update()

    theme_btn = ft.IconButton(
        icon=ft.Icons.DARK_MODE_OUTLINED,
        tooltip="切换为深色主题",
        on_click=toggle_theme,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)),
    )

    # ---- 自定义侧边栏 (Linear/Notion 风格: 徽标 + 图标文字导航 + 选中高亮条) ----
    _PAGE_NAMES = ["抓取", "结果预览", "站点配置", "运行日志"]
    _NAV_META = [
        # (未选中图标, 选中图标, 标签)
        (ft.Icons.DOWNLOAD_OUTLINED, ft.Icons.DOWNLOAD, "抓取"),
        (ft.Icons.FOLDER_OUTLINED, ft.Icons.FOLDER, "结果预览"),
        (ft.Icons.SETTINGS_OUTLINED, ft.Icons.SETTINGS, "站点配置"),
        (ft.Icons.TERMINAL_OUTLINED, ft.Icons.TERMINAL, "运行日志"),
    ]
    nav_items = []  # 保存每项控件引用, 切换时更新选中态
    page_title_ref = ft.Text("抓取", size=SIZE_TITLE, weight=WEIGHT_TITLE,
                             font_family=FONT_STACK)

    def _make_nav_item(icon, icon_sel, label, idx):
        """导航项: 左侧 3px 高亮条 + 图标 + 文字, 选中时主色容器"""
        bar = ft.Container(
            width=3, height=18,
            border_radius=ft.BorderRadius(0, 3, 3, 0),
        )
        icon_ctrl = ft.Icon(icon, size=20, color=ft.Colors.ON_SURFACE)
        text_ctrl = ft.Text(label, size=SIZE_LABEL, weight=WEIGHT_BODY,
                            color=ft.Colors.ON_SURFACE, font_family=FONT_STACK)
        item = ft.Container(
            content=ft.Row([bar, icon_ctrl, text_ctrl], spacing=12),
            padding=ft.Padding.symmetric(horizontal=10, vertical=11),
            border_radius=10,
            ink=True,
            on_click=lambda e, i=idx: _switch_page(i),
        )
        nav_items.append({
            "idx": idx, "container": item, "bar": bar,
            "icon": icon_ctrl, "icon_outlined": icon, "icon_sel": icon_sel,
            "text": text_ctrl, "label": label,
        })
        return item

    # 顶部徽标区: 圆角图标 + 应用名 + 副标题
    logo_badge = ft.Container(
        content=ft.Icon(ft.Icons.MENU_BOOK, size=22, color=ft.Colors.PRIMARY),
        width=40, height=40,
        bgcolor=ft.Colors.PRIMARY_CONTAINER,
        border_radius=12,
        shadow=ft.BoxShadow(
            blur_radius=8, spread_radius=0, offset=ft.Offset(0, 2),
            color=ft.Colors.with_opacity(0.12, ft.Colors.BLACK),
        ),
    )
    sidebar_header = ft.Row([
        logo_badge,
        ft.Column([
            ft.Text("小说爬虫", size=SIZE_SUBTITLE, weight=WEIGHT_TITLE,
                    color=ft.Colors.ON_SURFACE, font_family=FONT_STACK),
            ft.Text("便携版 · 多站抓取", size=SIZE_TINY,
                    color=ft.Colors.ON_SURFACE_VARIANT, font_family=FONT_STACK),
        ], spacing=1, tight=True),
    ], spacing=10)

    sidebar = ft.Container(
        content=ft.Column([
            sidebar_header,
            ft.Container(height=18),
            *[_make_nav_item(ic, ic_sel, lb, i)
              for i, (ic, ic_sel, lb) in enumerate(_NAV_META)],
            ft.Container(expand=True),
            ft.Divider(height=1),
            ft.Text("小说爬虫 · 便携版", size=SIZE_TINY,
                    color=ft.Colors.ON_SURFACE_VARIANT, opacity=0.75,
                    font_family=FONT_STACK),
        ], spacing=4),
        width=200,
        padding=ft.Padding.symmetric(horizontal=12, vertical=16),
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
        border=ft.Border(right=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)),
    )

    def _switch_page(idx: int):
        """切换页签: 更新导航选中态 + 可见性 + 工具栏标题"""
        for i, p in enumerate(pages):
            p.visible = (i == idx)
        # 更新侧边栏选中态
        for meta in nav_items:
            sel = meta["idx"] == idx
            meta["bar"].bgcolor = ft.Colors.PRIMARY if sel else None
            meta["icon"].name = (meta["icon_sel"] if sel
                                  else meta["icon_outlined"])
            meta["icon"].color = (ft.Colors.PRIMARY if sel
                                  else ft.Colors.ON_SURFACE_VARIANT)
            meta["text"].weight = WEIGHT_SUBTITLE if sel else WEIGHT_BODY
            meta["container"].bgcolor = (ft.Colors.PRIMARY_CONTAINER if sel
                                         else None)
        page_title_ref.value = _PAGE_NAMES[idx]
        # 页签切换时刷新对应内容
        if idx == 1:  # 结果预览
            try:
                preview_tab._refresh_file_list()
            except Exception:
                pass
        elif idx == 3:  # 运行日志
            try:
                log_tab.page = page
                log_tab._reload()
            except Exception:
                pass
        try:
            page.update()
        except Exception:
            pass

    # ---- 顶部工具栏 (动态页标题) ----
    toolbar = ft.Container(
        content=ft.Row([
            page_title_ref,
            ft.Container(width=10),
            ft.Text("多站小说抓取工具", size=SIZE_SMALL,
                    weight=WEIGHT_BODY,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                    font_family=FONT_STACK),
            ft.Container(expand=True),
            theme_btn,
        ]),
        padding=ft.Padding.symmetric(horizontal=16, vertical=8),
        bgcolor=ft.Colors.SURFACE_CONTAINER,
        border=ft.Border(bottom=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)),
    )

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

    # 状态栏动态刷新: 每秒汇总任务状态 (原来永远显示"就绪", 无参考价值)
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

    page.run_task(_status_loop)

    page.add(
        ft.Row([
            sidebar,
            # 主内容区: 极淡暖色渐变背景 (左上→右下), 提升层次感
            ft.Container(
                content=ft.Column([toolbar, content_stack],
                                  expand=True, spacing=0),
                expand=True,
                gradient=ft.LinearGradient(
                    begin=ft.Alignment(-1, -1), end=ft.Alignment(1, 1),
                    colors=[ft.Colors.SURFACE, ft.Colors.SURFACE_CONTAINER_LOW],
                ),
            ),
        ], expand=True, spacing=0),
        status_bar,
    )

    # 初始选中第 0 项 (控件挂载后再设置选中态样式)
    _switch_page(0)

    # 保存 page 引用到 crawl_tab / log_tab 以便后续更新
    crawl_tab.page = page
    log_tab.page = page

    # 退出时关闭日志文件
    try:
        page.on_disconnect = lambda e: app_log.close()
    except Exception:
        pass


if __name__ == "__main__":
    ft.run(main)
