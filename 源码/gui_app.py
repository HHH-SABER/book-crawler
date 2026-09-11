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
from gui_components.icon_rail import (IconRail, NAV_PAGES, build_theme_toggle,
                                      build_top_bar, build_remote_toggle)
from gui_components.ui_theme import page_header
from gui_components.input_bar import InputBar
from gui_components.task_table import TaskTable
from gui_components.detail_drawer import DetailDrawer
from gui_components.log_tab import LogTab
from gui_components.pages.history_page import HistoryPage
from gui_components.pages.site_manage_page import SiteManagePage
from gui_components.pages.remote_page import RemotePage

# 打包后路径约定（源码/EXE 双模式）
from _path_utils import get_default_output_dir, get_state_root  # noqa: E402

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
    from gui_components.ui_fluent import (
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

    # ---- 内嵌远控服务 (常驻): 与桌面客户端共用同一 TaskManager ----
    # 跨端同步: 手机端发起的任务实时出现在本窗口任务表 (同一对象, GUI 轮询
    # 即可见); 桌面方发的任务手机同样可见。客户端关闭则服务随之停止。
    try:
        from 远控 import 服务 as _远控
        _远控.注入任务管理器(task_manager)
        _t = _远控.后台启动()
        if _t is not None:
            _cfg = _远控.取配置()
            app_log.info("远控",
                         f"内嵌远控已启动: http://{_cfg.get('绑定')}:"
                         f"{_cfg.get('端口')}/ (手机访问需 Tailscale; "
                         f"token 见 数据/远控配置.json)")
    except Exception as _e_远控:
        app_log.info("远控", f"内嵌远控启动失败 (不影响本机使用): "
                             f"{type(_e_远控).__name__}: {_e_远控}")

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
                    on_theme_toggle=toggle_theme)

    # ---- 抓取工作台: 输入条 + 任务表格 | 右侧常驻面板 (实时日志/详情/预览) ----
    input_bar = InputBar(task_manager)
    task_table = TaskTable(task_manager)
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
    drawer.page = page

    # 任务表格行点击 → 选中 (右侧面板日志/详情自动跟随); 预览按钮 → 切到文件预览
    task_table.on_open_preview = lambda tid: drawer.open("preview", tid)

    crawl_workbench = ft.Row([
        ft.Column([
            page_header('抓取工作台', '输入小说目录页URL，自动识别站点并开始抓取'),
            input_bar.build(),
            ft.Container(content=task_table.build(), expand=True),
        ], expand=True, spacing=8),
        drawer.build(),
    ], expand=True, spacing=8)

    # ---- 其他三个页面 ----
    history_page = HistoryPage()
    site_page = SiteManagePage()
    log_tab = LogTab()
    remote_page = RemotePage()
    history_page.page = page
    history_page.task_manager = task_manager   # 一键更新书架需创建任务
    site_page.page = page
    log_tab.page = page
    remote_page.page = page
    remote_page.task_manager = task_manager    # 手机端记录数据源

    # ---- 页面切换 (Stack 保状态) ----
    pages_map = {
        "crawl": crawl_workbench,
        "history": history_page.build(),
        "sites": site_page.build(),
        "log": log_tab.build(),
        "remote": remote_page.build(),
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
        elif key == "remote":
            try:
                remote_page.refresh()
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

    # (H4 修复: 原此处有一个守护线程版状态刷新与下方异步 _status_loop 并存,
    #  格式互相覆盖且跨线程整页 page.update() 会与主线程刷新循环并发遍历
    #  控件树 —— 已删除, 状态摘要唯一由 _status_loop 在事件循环线程刷新)

    # ---- 主刷新循环 (主线程 async, 1s 周期) ----
    # 抓取工作台的表格/日志条/抽屉统一在此刷新 (仅 crawl 页可见时刷新, 省资源)
    async def _refresh_loop():
        import asyncio
        while True:
            try:
                if pages_map["crawl"].visible:
                    # 各组件只改控件树; H6 修复: 改为子树级 update —— 无参
                    # page.update() 会 patch 整个 page 树 (四页 Stack 常驻,
                    # 隐藏页也每秒参与 diff), 是 GUI 空闲抖动的主源
                    task_table.refresh_ui()      # 表格行 + 任务计数
                    drawer.refresh()             # 详情视图 (仅可见时渲染)
                    drawer.refresh_log()         # 实时日志视图 (默认视图)
                    drawer.update_views()        # 仅更新面板内可见视图
                if pages_map["remote"].visible:
                    remote_page.refresh()        # 远控页: 手机端记录实时呈现
            except Exception:
                pass
            await asyncio.sleep(1)

    # 状态栏动态刷新: 每秒汇总任务状态 (H4: 唯一状态刷新处; H6: 局部 update)
    async def _status_loop():
        import asyncio
        last = ""
        while True:
            try:
                tasks = task_manager.get_all_tasks()
                running = sum(1 for t in tasks if t.status == "running")
                failed = sum(1 for t in tasks if t.status == "failed")
                done = sum(1 for t in tasks if t.status == "completed")
                total = len(tasks)
                if running > 0:
                    dot_color, label = MORANDI_RUNNING, f"抓取中 {running} 项 · 共 {total}"
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
                    status_dot.update()
                    status_text.update()
            except Exception:
                pass
            await asyncio.sleep(1)

    page.run_task(_refresh_loop)
    page.run_task(_status_loop)

    # ---- 顶栏 (苹果风格: 标题 + 醒目主题切换按钮) ----
    _theme_toggle_btn[0] = build_theme_toggle(page, 'light', toggle_theme)
    # ---- 远控开关 (顶栏胶囊): 控制内嵌远控启用/禁用 ----
    def _更新远控外观(启用):
        _远控按钮更新(启用)
        try:
            page.update()
        except Exception:
            pass

    def _切远控(e):
        """开关点击入口: 只做调度。

        修复: 旧实现把整个切换过程写成同步回调, 其中 `time.sleep(0.5)` 直接睡在
        Flet UI 线程上 —— 这 0.5 秒内窗口不响应任何事件 (点什么都没反应),
        正是"界面卡死"体感的一部分。
        """
        try:
            page.run_task(_切远控异步)
        except Exception as _e_sw:
            app_log.info("远控", f"远控开关调度异常: {type(_e_sw).__name__}: {_e_sw}")

    async def _切远控异步():
        """远控开关的实际切换 (await 让出事件循环, 不阻塞 UI)"""
        try:
            import asyncio   # 本文件惯例: asyncio 在函数内局部导入
            import 远控.服务 as _远控切
            if _远控切.运行中():
                _远控切.设置启用(False)
                _远控切.停止后台()
                _更新远控外观(False)
                app_log.info("远控", "远控已停用 (手机端将无法访问)")
                page.show_dialog(ft.SnackBar(ft.Text("远控已停用, 手机端将无法访问")))
            else:
                _远控切.设置启用(True)
                _远控切.后台启动()
                await asyncio.sleep(0.5)   # 留出线程绑定端口的时间再判定
                ok = _远控切.运行中()
                _更新远控外观(ok)
                _cfg = _远控切.取配置()
                msg = (f"远控已启用: http://{_cfg.get('绑定')}:{_cfg.get('端口')}/"
                       if ok else "远控启用失败 (端口 8760 可能被占用)")
                app_log.info("远控", msg)
                page.show_dialog(ft.SnackBar(ft.Text(msg)))
        except Exception as _e_sw:
            app_log.info("远控", f"远控开关切换异常: {type(_e_sw).__name__}: {_e_sw}")

    _远控按钮, _远控按钮更新 = build_remote_toggle(_切远控)
    try:
        import 远控.服务 as _远控初
        _更新远控外观(_远控初.运行中())
    except Exception:
        pass

    # 远控页接线: 开关与顶栏同一实现; 访问信息同源 (运行状态/地址/token)
    remote_page.切换远控 = _切远控

    def _远控页信息():
        try:
            import 远控.服务 as _s
            cfg = _s.取配置()
            return {"运行": _s.运行中(),
                    "地址": f"http://{cfg.get('绑定')}:{cfg.get('端口')}/",
                    "token": cfg.get("token", "")}
        except Exception:
            return {"运行": False, "地址": "", "token": ""}

    remote_page.取信息 = _远控页信息

    # ---- 关闭行为: 最小化到托盘 / 直接退出 (关闭按钮不再直接退出) ----
    _关闭配置 = os.path.join(get_state_root(), "数据", "客户端配置.json")

    def _读关闭行为():
        import json as _j
        try:
            with open(_关闭配置, "r", encoding="utf-8") as f:
                return _j.load(f).get("关闭行为", "询问")
        except Exception:
            return "询问"

    def _写关闭行为(v):
        import json as _j
        try:
            os.makedirs(os.path.dirname(_关闭配置), exist_ok=True)
            tmp = _关闭配置 + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                _j.dump({"关闭行为": v}, f, ensure_ascii=False)
            os.replace(tmp, _关闭配置)
        except OSError:
            pass

    _托盘 = {"对象": None}

    async def _显示主窗():
        page.window.visible = True
        page.window.minimized = False
        try:
            page.update()
        except Exception:
            pass

    def _停远控服务():
        """停内嵌远控 (非阻塞: 只置 should_exit, 由 daemon 线程自行收尾)"""
        try:
            import 远控.服务 as _远控退
            _远控退.停止后台()
        except Exception as _e:
            app_log.info("退出", f"停远控失败: {type(_e).__name__}: {_e}")

    def _收尾落盘():
        """显式落盘 + 关日志。

        退出流程最后是 os._exit(), 不会触发 atexit —— 而这些模块平时靠 atexit
        兜底, 不在这里显式 flush 就会丢数据 (爬取历史/站点历史的防抖窗口内记录、
        风控事件的内存缓冲、日志尾部)。
        """
        try:
            import 爬取历史 as _ch
            _ch.取爬取历史().flush()
        except Exception as _e:
            app_log.info("退出", f"爬取历史 flush 失败: {type(_e).__name__}: {_e}")
        try:
            import 站点历史 as _sh
            _sh.取站点历史().flush()
        except Exception as _e:
            app_log.info("退出", f"站点历史 flush 失败: {type(_e).__name__}: {_e}")
        try:
            import 风控事件 as _fk
            _fk.flush()
        except Exception as _e:
            app_log.info("退出", f"风控事件 flush 失败: {type(_e).__name__}: {_e}")
        try:
            # 修复(U15b): 请求引擎单例的会话池此前无人 close。
            # os._exit 不跑 atexit, 所以必须在这里显式释放。
            from 请求引擎 import 获取引擎管理器
            获取引擎管理器().close()
        except Exception as _e:
            app_log.info("退出", f"引擎会话释放失败: {type(_e).__name__}: {_e}")
        try:
            app_log.close()
        except Exception:
            pass

    async def _彻底退出():
        """**唯一**的退出出口 —— 步骤顺序不可改, 详见 gui_components/退出流程.py

        实测 (flet 0.86.5, 桌面是"Python + flet.exe"双进程):
          · 只用 os._exit(0): 跳过 flet 的 close_flet_view(), flet.exe 变孤儿窗口
            (界面还在、没有后端、点关闭没反应) = 用户报的"关不掉 / 界面卡死"
          · 只用 page.window.destroy(): 客户端正常回收, 但 ft.run() 不返回, Python 挂住
        故必须 destroy → 等 flet 收尾 → 兜底强退。
        """
        from gui_components.退出流程 import 执行退出
        await 执行退出(
            page,
            托盘对象=_托盘["对象"],
            停远控=_停远控服务,
            任务管理器=task_manager,
            收尾钩子=(_收尾落盘,),
            记录=lambda m: app_log.info("退出", m))

    def _隐藏到托盘():
        # 关键顺序: 先建托盘, 成功后才隐藏窗口 —— 托盘创建失败时窗口保持
        # 可见 (旧实现先隐藏再建托盘, 托盘失败即"窗口消失且无入口"=关不掉)
        if _托盘["对象"] is None:
            try:
                from gui_components.tray import 启动托盘
                图标路径 = os.path.normpath(os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), "..",
                    "脚本", "图标.ico"))
                _托盘["对象"] = 启动托盘(
                    图标路径,
                    显示=lambda: page.run_task(_显示主窗),
                    退出=lambda: page.run_task(_彻底退出))
                app_log.info("托盘", "已最小化到托盘 (远控保持运行; 双击图标恢复)")
                # 首次最小化给一条系统气泡: Windows 11 默认把新托盘图标收进
                # "^" 折叠区, 用户容易以为"托盘没出现/最小化失效"
                try:
                    _托盘["对象"].notify("已最小化到托盘，双击托盘图标恢复主窗口")
                except Exception:
                    pass
            except Exception as _e_tray:
                app_log.info("托盘", f"托盘不可用, 取消隐藏以保持可操作: {_e_tray}")
                try:
                    page.show_dialog(ft.SnackBar(
                        ft.Text("系统托盘不可用, 已取消关闭; 建议再点关闭并选直接退出")))
                except Exception:
                    pass
                return
        page.window.visible = False
        # 显式 update: window 属性变更须 update 才下发到客户端 (与 _显示主窗 对称)。
        # 旧实现缺这一句, "最小化到托盘"点击后窗口不隐藏 —— 托盘其实建好了,
        # 但用户视角就是"没反应/失效"
        try:
            page.update()
        except Exception:
            pass

    def _关闭询问():
        """关闭确认弹窗 (Fluent 风格)。

        交互设计:
          - 默认焦点在"最小化到托盘" (安全动作, Enter 直接触发; 直接退出必须显式点击);
          - "直接退出"用错误色 TextButton 弱化, 且离主按钮最远防误点;
          - 弹窗为 modal, 配显式"取消" —— 遮罩点击不再静默吞掉关闭意图;
          - 有运行中任务时展示警示条 (退出可断点续传), 帮用户做对选择;
          - "记住我的选择"整行可点 (Checkbox 无 label 参数, 文字用 GestureDetector 接管)。
        弹窗内全部文字显式设色: 打包环境下 dialog 文字样式缺 color 会渲染成不可见。
        """
        from gui_components.ui_fluent import (
            txt, SIZE_SUBTITLE, WEIGHT_SUBTITLE,
            MORANDI_ON_SURFACE, MORANDI_ON_SURFACE_VARIANT,
        )

        记住 = ft.Checkbox(value=False)

        def _弹层关闭():
            try:
                page.pop_dialog()
            except Exception:
                pass

        def _切换记住(e):
            记住.value = not 记住.value
            try:
                记住.update()
            except Exception:
                pass

        def _选托盘(e):
            _弹层关闭()
            if 记住.value:
                _写关闭行为("托盘")
            _隐藏到托盘()

        def _选退出(e):
            _弹层关闭()
            if 记住.value:
                _写关闭行为("退出")
            page.run_task(_彻底退出)

        def _取消(e):
            _弹层关闭()

        rows = [txt("要最小化到系统托盘（远控保持运行），还是直接退出？",
                    color=MORANDI_ON_SURFACE)]
        # 运行中任务警示: 直接退出会中断抓取 (进度已存盘, 可断点续传)
        try:
            运行数 = sum(1 for _t in task_manager.tasks.values()
                        if _t.status == "running")
        except Exception:
            运行数 = 0
        if 运行数:
            rows.append(ft.Container(
                content=txt(f"⚠ 有 {运行数} 个任务正在运行，直接退出将中断抓取"
                            f"（已抓进度已保存，可断点续传）",
                            size=SIZE_SMALL, color=ft.Colors.ON_TERTIARY_CONTAINER),
                bgcolor=ft.Colors.TERTIARY_CONTAINER,
                border_radius=4,
                padding=ft.Padding(10, 8, 10, 8),
            ))
        rows.append(ft.Row(
            [记住,
             ft.GestureDetector(
                 content=txt("记住我的选择，以后不再询问", color=MORANDI_ON_SURFACE),
                 on_tap=_切换记住)],
            spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER))

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                [ft.Icon(ft.Icons.LOGOUT, size=20, color=MORANDI_ON_SURFACE_VARIANT),
                 txt("关闭窗口", size=SIZE_SUBTITLE, weight=WEIGHT_SUBTITLE,
                     color=MORANDI_ON_SURFACE)],
                spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            content=ft.Container(
                content=ft.Column(rows, tight=True, spacing=12), width=430),
            actions=[
                ft.TextButton("直接退出", on_click=_选退出,
                              style=ft.ButtonStyle(color=MORANDI_ERROR)),
                ft.TextButton("取消", on_click=_取消),
                ft.FilledButton("最小化到托盘", on_click=_选托盘, autofocus=True),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.show_dialog(dlg)

    def _处理关闭(e):
        try:
            if getattr(e, "type", None) == ft.WindowEventType.CLOSE:
                行为 = _读关闭行为()
                if 行为 == "托盘":
                    _隐藏到托盘()
                elif 行为 == "退出":
                    page.run_task(_彻底退出)
                else:
                    _关闭询问()
        except Exception as _e_cl:
            # 兜底降级 (v2.4.19 教训): 弹窗/配置处理自身异常时**不再直接退出** ——
            # 此前一个 import 错误就让"关闭"变成无确认强退。改为退到托盘:
            # 关闭意图仍被执行 (窗口消失), 应用可从托盘菜单退出, 完全可恢复。
            # 若托盘也建不成, _隐藏到托盘 会保持窗口可见, 不会"关不掉"。
            app_log.info("关闭", f"关闭处理异常, 降级为最小化到托盘: {_e_cl}")
            try:
                _隐藏到托盘()
            except Exception as _e_cl2:
                app_log.info("关闭", f"托盘降级也失败, 直接退出以免卡死: {_e_cl2}")
                page.run_task(_彻底退出)

    page.window.prevent_close = True
    page.window.on_event = _处理关闭

    top_bar = build_top_bar(page, '小说爬虫', _theme_toggle_btn[0],
                            extra_controls=[_远控按钮])

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
