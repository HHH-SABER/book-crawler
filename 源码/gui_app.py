# -*- coding: utf-8 -*-
"""小说爬虫 GUI 主程序 (苹果风格界面)

基于 Flet 框架。布局:
  === 设计稿目标 (界面设计预览/index.html, 2.5 界面重设计) ===
  顶栏 (52px): 应用图标 + 应用名 + 远控胶囊 + 主题胶囊 + 窗口按钮
  + 侧边栏 (220px): 图标+文字导航 + 底部状态块 + 访问 GitHub 卡
  + 主内容区 (抓取工作台: 输入条 + 任务表格 + **底部常驻日志条** + 右侧常驻详情栏)
  + 底部状态栏 (实时任务汇总)
  === 当前实现状态 (2026-10-06, Phase 4 落实中) ===
  ✅ 顶栏 52px / 侧栏底部状态块 + GitHub 卡 / 底部状态栏 / 右侧抽屉
  ⚠️ 待办: 底部常驻日志条 (现为右侧抽屉内的"实时日志"视图) —— 批 2;
          自定义标题栏与窗口按钮、右栏常驻化、控件密度 —— 批 2/批 3
  (旧注释直接写"可折叠日志条", 与实现不符、易误导 —— 已按现状改写)
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
from gui_components.pages.dead_book_page import DeadBookPage
from gui_components import 补址弹窗

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
    import waf_captcha  # noqa: F401  (WAF 验证码自动解决, 移动版站点等)
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
    import gui_components.pages.dead_book_page  # noqa: F401  (死书清单, 阶段4)
    import gui_components.pages.site_manage_page  # noqa: F401
except Exception as _e:
    # 允许在未装所有爬虫依赖时 GUI 仍可启动（可预览/配置，抓取按钮点时报错）
    app_log.debug("GUI", f'裸 except 吞异常: {type(_e).__name__}: {_e}')


def _读显示版本() -> str:
    """界面显示版本号: EXE 读版本资源 (ProductVersion), 源码读 脚本/版本.json。

    失败返回 '' (调用方拼接时自然退化为纯应用名, 不阻断启动)。
    """
    try:
        if getattr(sys, "frozen", False):
            import ctypes
            size = ctypes.windll.version.GetFileVersionInfoSizeW(
                sys.executable, None)
            if size:
                data = ctypes.create_string_buffer(size)
                if ctypes.windll.version.GetFileVersionInfoW(
                        sys.executable, 0, size, data):
                    ptr = ctypes.c_void_p()
                    ln = ctypes.c_uint()
                    if ctypes.windll.version.VerQueryValueW(
                            data, '\\VarFileInfo\\Translation',
                            ctypes.byref(ptr), ctypes.byref(ln)) and ln.value >= 4:
                        pair = ctypes.cast(
                            ptr, ctypes.POINTER(ctypes.c_uint16 * 2)).contents
                        key = (f'\\StringFileInfo\\{pair[0]:04x}{pair[1]:04x}'
                               f'\\ProductVersion')
                        if ctypes.windll.version.VerQueryValueW(
                                data, key, ctypes.byref(ptr), ctypes.byref(ln)):
                            return ctypes.wstring_at(ptr.value).strip()
        else:
            import json as _j
            p = os.path.normpath(os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                '..', '脚本', '版本.json'))
            with open(p, encoding='utf-8') as f:
                return str(_j.load(f).get('版本', '')).strip()
    except Exception as _e:
        app_log.debug("GUI", f'裸 except 吞异常: {type(_e).__name__}: {_e}')
    return ''


def main(page: ft.Page):
    """Flet 应用入口"""
    _版本 = _读显示版本()
    _应用名 = f"小说爬虫 v{_版本}" if _版本 else "小说爬虫"
    page.title = _应用名
    # 窗口尺寸按屏幕自适应 (修复: 写死 1280x800 在小屏/高DPI缩放下内容截断)
    try:
        import ctypes
        _user32 = ctypes.windll.user32
        try:
            _user32.SetProcessDPIAware()
        except Exception as _exc:
            app_log.debug("GUI", f'裸 except 吞异常: {type(_exc).__name__}: {_exc}')
        _sw, _sh = _user32.GetSystemMetrics(0), _user32.GetSystemMetrics(1)
    except Exception:
        _sw, _sh = 1920, 1080
    page.window.width = min(1500, max(960, int(_sw * 0.9)))
    page.window.height = min(860, max(640, int(_sh * 0.85)))
    page.window.min_width = min(960, _sw)
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
            提示条,
    )
    # 2026-10-04 (Phase 3): 状态色改走 ui_tokens 令牌 + 登记重刷 ——
    # 绑 ui_fluent 的 MORANDI_* 字符串常量时, 切主题这些控件不会换色。
    from gui_components.ui_tokens import 取色, 登记重刷

    page.theme = make_morandi_theme()
    page.dark_theme = make_morandi_dark_theme()

    # 启动日志: 记录系统信息 (便于事后排查版本/环境问题)
    try:
        import platform
        _mode = "PyInstaller EXE" if getattr(sys, "frozen", False) else "源码模式"
        app_log.info("系统", f"程序启动 (模式: {_mode}, Python {platform.python_version()})")
        app_log.info("系统", f"EXE/项目目录: {os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, 'frozen', False) else os.getcwd()}")
        # 便携数据开关提示 (P1): flag 仅打包模式生效; 不自动迁移旧数据
        import _path_utils as _pu
        if _pu.is_portable_mode():
            app_log.info("系统", "便携数据模式已启用 (EXE 旁 便携模式.flag): "
                          "数据/日志 将读写 EXE 旁目录; 默认根 "
                          "%LOCALAPPDATA%\\小说爬虫 的历史数据不会自动迁移, "
                          "如需保留请手动复制其中的 数据/ 与 日志/ 两个目录")
    except Exception:
        pass  # 刻意静默: try 块本身在写日志, 再加日志会递归 (日志链路兜底)

    # ---- 网站清单启动自检 (缺失自动生成模板; EXE 迁移/换机后同样生效) ----
    try:
        from 网站清单 import 自动生成若缺失
        自动生成若缺失()
    except Exception as _e_清单:
        app_log.debug("系统", f"网站清单自检失败 (不影响主流程): "
                              f"{type(_e_清单).__name__}")

    # ---- 全局任务管理器 ----
    task_manager = TaskManager(page)

    # ---- 死书弹窗 (死书机制 阶段3; 2026-10-06 统一为两步补址流程) ----
    # 分流契约 (2026-10-06 改版): **所有**死书都先问"要不要给这本书添加一个新网站",
    # 没有则追问"是否删除"; 弹窗实现只有一处 = `gui_components/补址弹窗.py`。
    #   · 记录['网站失效']=True (域名级死亡) → 场景_网站失效 文案
    #   · 其余 (目录无章节/站点不可达, 多为疑似) → 场景_其他 文案, 追问里提示先「重新检测」
    #   —— 分流只认**结构化字段**, UI 不得自行比较类型名:
    #      判错类型会让用户误删仍可恢复的书 (误删代价远高于多问一句)。
    #   —— 每个记录只在**首次**入队 (见 task_manager._记死书 的 首次 判定), 不会反复打扰。
    async def _提示死书(task_id: str):
        """死书提示: 单一入口 (便于测试与追溯)。

        2026-10-06 改版(用户需求): "死书时询问是否要添加书籍新网站, 没有则询问是否删除"
        → 统一走 `gui_components/补址弹窗.py` 的两步流程(补备用源 → 追问删除)。
        旧实现的两个致命伤:
          ① 只有"域名级死亡"(`网站失效`)才弹补址窗, 其余类型**静默** → 用户根本看不到入口;
          ② 那扇补址窗用了 `ft.TextField(hint=…)` —— Flet 无 `hint` 参数(真名 `hint_text`),
             构造即 TypeError, 且发生在 try 之外 → **弹窗从未真正显示过**(2026-10-06 测试发现)。
        2026-10-03 另修: 必须是协程函数 (`page.run_task` 要求, 见 K37)。
        """
        t = task_manager.get_task(task_id)
        if not t:
            return
        死 = getattr(t, 'dead', None)
        if not isinstance(死, dict):     # Mock 防御: getattr 可能返回 Mock
            return
        类型 = 死.get('类型') or '未知'
        原因 = 死.get('原因') or ''
        标题 = t.title or t.url
        # 分流只认**结构化字段**(网站失效), 不比较类型名 ——
        # 判错类型会让用户误删仍可恢复的书。
        场景 = (补址弹窗.场景_网站失效 if 死.get('网站失效')
                else 补址弹窗.场景_其他)
        动作 = 补址弹窗.补址动作(
            添加并重抓=lambda _新址: _带备用源重抓(t.url, 标题),
            删除记录=lambda: task_table._on_delete_dead(task_id),
            忽略记录=lambda: task_table._on_ignore_dead(task_id),
        )
        try:
            补址弹窗.打开补址弹窗(page, 目录URL=t.url, 标题=标题, 场景=场景,
                               类型=类型, 原因=原因, 动作=动作)
            app_log.info("死书", f"询问补新网站/删除: {类型} {t.url}")
        except Exception as e:
            app_log.debug("死书", f"弹窗打开失败, 降级为提示: {type(e).__name__}: {e}")
            try:
                page.show_dialog(提示条(f"《{标题}》抓取失败: {类型}\n{原因}"))
            except Exception as _e2:
                app_log.debug("死书", f"降级提示也失败: {type(_e2).__name__}: {_e2}")

    def _带备用源重抓(网址: str, 标题: str = ''):
        """（登记备用源之后）重新发起抓取。

        重抓的是**原**网址, 不是新网址: 备用源按原目录 URL 登记, 只有抓原网址时
        多源回退才会消费它(`爬虫.py:7130` 精确匹配) —— 主源再失败即自动切到备用源
        (`爬虫.py:7175`)。抓成功后收尾会自动清掉这条死书记录(2026-10-06 修复)。
        """
        try:
            旧 = task_manager.find_task_by_url(网址)
        except Exception as e:
            app_log.debug("死书", f"查找任务失败: {type(e).__name__}: {e}")
            旧 = None
        try:
            if 旧 is not None:
                在跑 = (getattr(旧, 'status', '') == 'running'
                        or (getattr(旧, 'thread', None) is not None
                            and 旧.thread.is_alive()))
                if 在跑:
                    page.show_dialog(提示条("该书任务正在运行中, 无需重复发起"))
                    return
                if not task_manager.restart_task(旧.task_id):
                    page.show_dialog(提示条("该书任务正在收尾, 请稍后再试"))
                    return
            else:
                # 沿用死书清单页的重检口径: resume=False (从未抓到章节, 续传无意义)
                task_manager.create_task(网址, mode='full', resume=False)
            app_log.info("死书", f"已用备用源重新发起: 《{标题}》 {网址}")
        except Exception as e:
            app_log.info("死书", f"重新发起失败: {type(e).__name__}: {e}")
            page.show_dialog(提示条(f"⚠️ 重新发起抓取失败: {type(e).__name__}"))

    def _排空死书队列():
        """每 tick 至多弹一条, 避免批量失败时弹窗刷屏淹没界面。"""
        try:
            task_id = task_manager.取一条待弹死书()
            if task_id:
                page.run_task(_提示死书, task_id)   # 唯一跨线程调度入口
        except Exception as e:
            app_log.debug("死书", f"队列排空失败: {type(e).__name__}: {e}")

    def _弹终态SnackBar(n: dict) -> None:
        行 = f"抓取完成: 《{n.get('书名', '')}》"
        if n.get('状态') != 'success':
            行 = f"抓取失败: 《{n.get('书名', '')}》"
            原因 = (n.get('原因') or '').strip()
            if 原因:
                行 += f"\n{原因}"
        # 2026-10-06: 改走 ui_fluent.提示条(显式 toast 底色+字色成对, 防黑底黑字)
        page.show_dialog(提示条(行, 时长=6000))

    def _窗口不在前台() -> bool:
        """最小化或已隐藏到托盘 → 应用内 SnackBar 不可见, 终态通知走系统气泡。"""
        try:
            return (not page.window.visible) or page.window.minimized
        except Exception as _e:
            app_log.debug("GUI", f'裸 except 吞异常: {type(_e).__name__}: {_e}')
            return False

    def _排空通知():
        """终态通知排空 (八项需求 #2): 每 tick 至多一条 SnackBar —— 书名+状态+
        失败原因, 音效已在 _set_terminal (工作线程侧) 播放, 后台挂机可感知。
        2026-10-09: 窗口最小化/隐藏到托盘时 SnackBar 根本看不见 → 整批取空
        聚合为一条 pystray 系统气泡 (防连续气泡互相顶掉); 托盘不可用/发送失败
        回退首条 SnackBar (恢复窗口后至少可见一条)。"""
        try:
            if _窗口不在前台():
                n = task_manager.取一条待弹通知()
                if n:
                    items = [n]
                    while True:
                        m = task_manager.取一条待弹通知()
                        if not m:
                            break
                        items.append(m)
                    from gui_components.tray import 发终态气泡 as _发气泡
                    if not _发气泡(_托盘["对象"], items):
                        _弹终态SnackBar(items[0])
                return
            n = task_manager.取一条待弹通知()
            if n:
                _弹终态SnackBar(n)
        except Exception as e:
            app_log.debug("通知", f"终态通知展示失败: {type(e).__name__}: {e}")

    # ---- 内嵌远控服务 (常驻): 与桌面客户端共用同一 TaskManager ----
    # 跨端同步: 手机端发起的任务实时出现在本窗口任务表 (同一对象, GUI 轮询
    # 即可见); 桌面方发的任务手机同样可见。客户端关闭则服务随之停止。
    try:
        from 远控 import 服务 as _远控
        _远控.注入任务管理器(task_manager)
        _t = _远控.后台启动()
        if _t is not None:
            # 2026-10-03 #7: 展示地址经 展示地址() 解析 (0.0.0.0 → 首个局域网 IP)
            app_log.info("远控",
                         f"内嵌远控已启动: {_远控.展示地址()} "
                         f"(局域网直连; token 见 数据/远控配置.json)")
    except Exception as _e_远控:
        app_log.info("远控", f"内嵌远控启动失败 (不影响本机使用): "
                             f"{type(_e_远控).__name__}: {_e_远控}")

    # ---- 主题切换 ----
    _theme_dark = [False]
    _theme_toggle_btn = [None]  # 顶栏主题切换按钮引用

    def toggle_theme():
        _theme_dark[0] = not _theme_dark[0]
        page.theme_mode = ft.ThemeMode.DARK if _theme_dark[0] else ft.ThemeMode.LIGHT
        # 暖色令牌同步: rail.toggle_theme_icon 内部会调 ui_fluent.同步主题()
        # -> ui_tokens.设置主题() 触发已登记控件换色 (单一同步点, 勿在此重复)
        rail.toggle_theme_icon(_theme_dark[0])
        # 同步更新顶栏主题切换按钮
        if _theme_toggle_btn[0] and hasattr(_theme_toggle_btn[0], 'update_theme_state'):
            _theme_toggle_btn[0].update_theme_state(_theme_dark[0])
        app_log.info("系统", f"主题切换为: {'深色' if _theme_dark[0] else '浅色'}")
        page.update()

    # ---- 图标导航栏 ----
    rail = IconRail(on_nav=lambda key: _switch_page(key),
                    on_theme_toggle=toggle_theme)
    rail.page = page          # 侧栏底部 GitHub 卡需要 page 才能打开浏览器

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

    # ---- 响应式档位 (Phase 4 批 4, 2026-10-07) ----
    # 旧实现: 单档 1200px 布尔, 窄档把任务表 4 个次级列**隐藏**掉 (910 → 606px)。
    # 用户 2026-10-07 拍板**对齐设计稿**: 任何断点都不隐藏任务表列
    # (固定 910px + 横向滚动), 改为按档调抽屉宽/统计列数/日志展开限高。
    # 真值在 gui_components/布局档位.py (纯函数, 由 测试/test_布局档位.py 钉死) ——
    # 改动前响应式在 测试/ 与 测试_本地/ 里**零命中**, 只靠这行日志 + 人工看。
    # ≤720 / ≤480 两档因窗口 min_width=960 实机不可达 → 不实现 (设计稿自己也注了
    # 这条实机约束, 见 index.html:2300)。
    # 120ms 防抖照旧: 拖动窗口时 on_resize 高频触发, 每次重排所有控件会明显卡顿。
    import gui_components.布局档位 as _档位
    _当前档 = [None]
    # 档位回调的目标 (可增): 先只有工作台的两个控件; pages_map 建好后把
    # 页面对象补进来 —— "只在切页时刷新"的页面(如历史页)不会自己跟上档位变化。
    _档位目标 = [task_table, drawer]

    def _计算窄档():
        try:
            宽 = int(getattr(page, 'width', 0) or 0)
            if 宽 <= 0:
                return
            档 = _档位.计算档位(宽)
            参数 = _档位.取参数(档)
            _档位.设置当前档(档)      # 页面构建时读它取初始参数
            if _当前档[0] == 档:
                return
            _当前档[0] = 档
            for _目标 in _档位目标:
                _设 = getattr(_目标, '设置档位', None)   # 接口由 task_table/drawer 提供
                if callable(_设):
                    try:
                        _设(档, 参数)
                    except Exception as _e2:
                        app_log.debug("GUI", f'档位切换失败({type(_目标).__name__}): '
                                             f'{type(_e2).__name__}: {_e2}')
            app_log.info("系统", f"窗口 {宽}px → {_档位.档位说明(档)}")
        except Exception as _e:
            app_log.debug("GUI", f'档位计算失败: {type(_e).__name__}: {_e}')

    _尺寸防抖 = [None]

    def _on_page_resize(e=None):
        """窗口尺寸变化 → 120ms 防抖后重算窄档 (Phase 3)"""
        try:
            import threading
            if _尺寸防抖[0] is not None:
                _尺寸防抖[0].cancel()
            _尺寸防抖[0] = threading.Timer(0.12, _计算窄档)
            _尺寸防抖[0].daemon = True
            _尺寸防抖[0].start()
        except Exception as _e:
            app_log.debug("GUI", f'窗口尺寸事件处理失败: {type(_e).__name__}: {_e}')

    page.on_resize = _on_page_resize
    _on_page_resize()      # 首帧 page.width 可能尚未就绪 → 交给 120ms 后的首次计算

    # 工作台 = 左列(页头 + 输入条 + 任务表 + **底部常驻日志条**) | 右侧常驻栏(详情/预览)
    # 设计稿 (界面设计预览/index.html) 的三区; 批 2 由"抽屉"改为两处常驻。
    _右侧常驻栏 = drawer.build()          # 必须在 build_log_strip 之前/之后都行: 视图构建幂等
    _底部日志条 = drawer.build_log_strip()
    crawl_workbench = ft.Row([
        ft.Column([
            page_header('抓取工作台', '输入小说目录页URL，自动识别站点并开始抓取'),
            input_bar.build(),
            ft.Container(content=task_table.build(), expand=True),
            _底部日志条,
        ], expand=True, spacing=8),
        _右侧常驻栏,
    ], expand=True, spacing=8)

    # ---- 其他页面 ----
    history_page = HistoryPage()
    site_page = SiteManagePage()
    log_tab = LogTab()
    remote_page = RemotePage()
    dead_page = DeadBookPage()          # 死书清单 (死书机制 阶段4)
    history_page.page = page
    history_page.task_manager = task_manager   # 一键更新书架需创建任务
    site_page.page = page
    log_tab.page = page
    remote_page.page = page
    remote_page.task_manager = task_manager    # 手机端记录数据源
    dead_page.page = page
    dead_page.task_manager = task_manager      # 删除编排需任务管理器(可删任务行)

    # ---- 页面切换 (Stack 保状态) ----
    # ⚠️ 键顺序必须与 icon_rail.NAV_PAGES **严格一致**(死书机制 阶段4 新增页):
    #    下游 content_stack 按 [pages_map[k] for k,_,_,_ in NAV_PAGES] 建 Stack,
    #    且首屏可见性按 pages_map.values() 的索引 0 判定 —— 顺序错位会首屏显示错页。
    pages_map = {
        "crawl": crawl_workbench,
        "history": history_page.build(),
        "deadbook": dead_page.build(),
        "sites": site_page.build(),
        "log": log_tab.build(),
        "remote": remote_page.build(),
    }
    # 自检: 顺序不一致时立刻炸, 别等用户看到错页才发现
    if list(pages_map) != [k for k, _, _, _ in NAV_PAGES]:
        raise RuntimeError(f"pages_map 键序与 NAV_PAGES 不一致: {list(pages_map)}")
    content_stack = ft.Stack(
        controls=[pages_map[k] for k, _, _, _ in NAV_PAGES],
        expand=True)
    for i, p in enumerate(pages_map.values()):
        p.visible = (i == 0)

    # 批 4: 补上实现了 设置档位 的页面对象 (注意 pages_map 的值是 build() 出来的
    # **控件**, 不是页面对象本身, 所以不能从 pages_map.values() 里找)。
    _档位目标.extend(_p for _p in (history_page, dead_page, site_page,
                                  log_tab, remote_page)
                     if callable(getattr(_p, '设置档位', None)))

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
            except Exception as _e:
                app_log.debug("GUI", f'裸 except 吞异常: {type(_e).__name__}: {_e}')
        elif key == "deadbook":
            try:
                dead_page.refresh()
            except Exception as _e:
                app_log.debug("GUI", f'裸 except 吞异常: {type(_e).__name__}: {_e}')
        elif key == "log":
            try:
                log_tab._reload()
            except Exception as _e:
                app_log.debug("GUI", f'裸 except 吞异常: {type(_e).__name__}: {_e}')
        elif key == "remote":
            try:
                remote_page.refresh()
            except Exception as _e:
                app_log.debug("GUI", f'裸 except 吞异常: {type(_e).__name__}: {_e}')
        try:
            page.update()
        except Exception as _e:
            app_log.debug("GUI", f'裸 except 吞异常: {type(_e).__name__}: {_e}')

    # ---- 底部状态栏 ----
    # - 开发模式 (python gui_app.py)         : 项目根/抓取结果
    # - PyInstaller onefile (小说爬虫.exe)   : EXE 所在目录/抓取结果
    output_dir = get_default_output_dir()

    # 底部状态条: 实时任务摘要 (唯一状态显示处; 侧边栏不再重复渲染)
    status_dot = ft.Icon(ft.Icons.CIRCLE, color=取色('status-success'), size=8)
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
                if pages_map["deadbook"].visible:
                    # 死书清单页: 数据源在磁盘(其他会话/远控也可能改),
                    # 2s 轮询同 remote_page; 页内有签名比对, 无变化不重建
                    dead_page.refresh()
                # 死书待弹队列 (死书机制 阶段3): 不限页面可见性 —— 抓取可能在
                # 任意页面运行, 队列排空与页面无关。每 tick 至多一条。
                _排空死书队列()
                # 终态通知队列 (八项需求 #2): 成功/失败 SnackBar, 与音效配合
                _排空通知()
            except Exception:
                pass  # 刻意静默: 高频路径(_refresh_loop(), 逐行/每秒级), 补日志会刷屏
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
                # 死书待确认(死书机制 阶段2): 独立分支 —— 它既非 running 也非
                # failed, 不单独统计会走到 else 显示"就绪", 表里有待确认行而
                # 状态栏说"就绪", 用户以为无事发生
                dead = sum(1 for t in tasks if t.status == "dead_pending")
                total = len(tasks)
                if running > 0:
                    dot_color, label = 取色('status-warning'), f"抓取中 {running} 项 · 共 {total}"
                    if done:
                        label += f" · 已完成 {done}"
                elif dead:
                    dot_color, label = 取色('status-warning'), f"书已删除 {dead} 项 · 待确认"
                elif failed:
                    dot_color, label = 取色('status-error'), f"就绪 · 失败 {failed} 项"
                elif done:
                    dot_color, label = 取色('status-success'), f"就绪 · 已完成 {done} 项"
                else:
                    dot_color, label = 取色('status-success'), "就绪"
                if label != last:
                    last = label
                    status_dot.color = dot_color
                    status_text.value = label
                    status_dot.update()
                    status_text.update()
                    # 设计稿: 侧栏底部也有同源状态块 (同一 label/颜色, 不另算)
                    rail.设置状态摘要(label, dot_color)
                    rail.刷新状态摘要()
            except Exception:
                pass  # 刻意静默: 高频路径(_status_loop(), 逐行/每秒级), 补日志会刷屏
            await asyncio.sleep(1)

    page.run_task(_refresh_loop)
    page.run_task(_status_loop)

    # ---- 首次启动引导 (八项需求 #5): 询问创建桌面快捷方式 ----
    # flag 落 状态根/数据/首次启动.flag —— 问过一次就不再打扰;
    # 用户**明确表态**(创建成功 / 选择暂不) 才写 flag。
    # ⚠ 2026-10-04 (#5 修复): 失败时**不写** —— 旧实现写在 finally 里, 一次瞬时失败
    # (PowerShell 被杀 / 超时 / 非 0 退出) 就让引导永久不再出现, 而程序内没有手动入口。
    def _写首次flag(结果: str = '已询问创建桌面快捷方式'):
        """原子写首次启动标记 (tmp + os.replace, 对齐项目状态文件规约)"""
        try:
            import time as _tm
            p = os.path.join(get_state_root(), "数据", "首次启动.flag")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            tmp = f"{p}.tmp.{os.getpid()}"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(f"{结果}: {_tm.strftime('%Y-%m-%d %H:%M:%S')}\n")
            os.replace(tmp, p)
        except Exception as e:
            app_log.debug("引导", f"首次启动 flag 写入失败: {type(e).__name__}: {e}")

    def _建桌面快捷方式() -> None:
        """PowerShell WScript.Shell 创建桌面快捷方式 (失败抛异常)。

        实现注记: 桌面路径在 PS 侧取 ([Environment]::GetFolderPath 才拿得到
        OneDrive 重定向后的真实桌面); 中文经 -EncodedCommand (UTF-16LE Base64)
        传参, 规避 -Command 代码页转义坑; 只看退出码不捕获文本输出
        (PS 中文 stdout 捕获不可靠, 2026-10-03 实测)。
        """
        import base64
        import subprocess
        if getattr(sys, "frozen", False):
            target = os.path.abspath(sys.executable)
        else:
            target = os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "启动GUI.bat")
        workdir = os.path.dirname(target)
        ps = (
            "$ErrorActionPreference='Stop';"
            "$desk=[Environment]::GetFolderPath('Desktop');"
            "$ws=New-Object -ComObject WScript.Shell;"
            "$lnk=$ws.CreateShortcut((Join-Path $desk '小说爬虫.lnk'));"
            f"$lnk.TargetPath='{target.replace(chr(39), chr(39) * 2)}';"
            f"$lnk.WorkingDirectory='{workdir.replace(chr(39), chr(39) * 2)}';"
            f"$lnk.IconLocation='{target.replace(chr(39), chr(39) * 2)},0';"
            "$lnk.Description='小说爬虫 - 网文离线阅读与远控';"
            "$lnk.Save();exit 0"
        )
        enc = base64.b64encode(ps.encode("utf-16-le")).decode("ascii")
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc],
            capture_output=True, timeout=20)
        if r.returncode != 0:
            # 2026-10-04 (#5 修复): 把 PS 的 stderr 带进异常 —— 旧实现只报退出码,
            # 用户与日志都拿不到"为什么失败"。
            err = (r.stderr or b'').decode('utf-8', errors='replace').strip()
            raise RuntimeError(f"PowerShell 退出码 {r.returncode}"
                               + (f": {err[:200]}" if err else ""))

    async def _首次引导():
        try:
            import asyncio
            flag = os.path.join(get_state_root(), "数据", "首次启动.flag")
            if os.path.exists(flag):
                return
            await asyncio.sleep(1.5)   # 让位窗口居中/首帧渲染, 避免抢焦点
            if os.path.exists(flag):   # 双检: sleep 期间可能已被远控端处理
                return

            def _关窗():
                try:
                    dlg.open = False
                    page.update()
                except Exception as e:
                    app_log.debug("引导", f"引导窗关闭失败: {type(e).__name__}: {e}")

            async def _创建(_e=None):
                try:
                    await asyncio.to_thread(_建桌面快捷方式)
                except Exception as e:
                    # 2026-10-04 (#5 修复): 失败**不写 flag** → 下次启动会再问一次
                    # (旧实现把 _写首次flag 放在 finally, 一次瞬时失败即永久放弃引导)。
                    app_log.info("引导", f"快捷方式创建失败: {type(e).__name__}: {e}")
                    page.show_dialog(提示条(f"快捷方式创建失败 (下次启动会再询问): {e}"[:200]))
                    _关窗()
                    return
                page.show_dialog(提示条("桌面快捷方式已创建"))
                app_log.info("引导", "桌面快捷方式创建成功")
                _写首次flag('已创建桌面快捷方式')
                _关窗()

            def _跳过(_e=None):
                app_log.info("引导", "用户选择暂不创建快捷方式")
                _写首次flag('用户选择暂不创建')
                _关窗()

            dlg = ft.AlertDialog(
                modal=True,
                title=ft.Text("欢迎使用小说爬虫", color=ft.Colors.ON_SURFACE,
                              font_family=FONT_STACK),
                content=ft.Text(
                    "是否在桌面创建一个快捷方式, 方便下次打开?\n"
                    "(也可以稍后从程序目录直接运行)",
                    size=SIZE_SMALL, font_family=FONT_STACK,
                    color=ft.Colors.ON_SURFACE),
                actions=[
                    ft.TextButton("暂不创建", on_click=_跳过),
                    ft.TextButton("创建快捷方式", on_click=_创建),
                ],
            )
            page.show_dialog(dlg)
            app_log.info("引导", "首次启动引导已弹出 (询问创建桌面快捷方式)")
        except Exception as e:
            app_log.debug("引导", f"首次引导异常 (不影响主流程): {type(e).__name__}: {e}")

    page.run_task(_首次引导)

    # ---- 顶栏 (苹果风格: 标题 + 醒目主题切换按钮) ----
    _theme_toggle_btn[0] = build_theme_toggle(page, 'light', toggle_theme)
    # ---- 远控开关 (顶栏胶囊): 控制内嵌远控启用/禁用 ----
    def _更新远控外观(启用):
        _远控按钮更新(启用)
        try:
            page.update()
        except Exception as _e:
            app_log.debug("GUI", f'裸 except 吞异常: {type(_e).__name__}: {_e}')

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
                await asyncio.to_thread(_远控切.停止后台)
                _更新远控外观(False)
                app_log.info("远控", "远控已停用 (手机端将无法访问)")
                page.show_dialog(提示条("远控已停用, 手机端将无法访问"))
            else:
                _远控切.设置启用(True)
                _远控切.后台启动()
                await asyncio.sleep(0.5)   # 留出线程绑定端口的时间再判定
                ok = _远控切.运行中()
                _更新远控外观(ok)
                _cfg = _远控切.取配置()
                # 2026-10-03 #7: 绑定 0.0.0.0 时展示可用局域网地址 (0.0.0.0 不是可访问 URL)
                msg = (f"远控已启用: {_远控切.展示地址()}"
                       if ok else "远控启用失败 (端口 8760 可能被占用)")
                # 2026-10-04 #7: 地址"看着能用但其实连不上"时, 把原因一并说出来
                if ok:
                    try:
                        _提示 = _远控切.地址提示()
                    except Exception:
                        _提示 = ""
                    if _提示:
                        msg = f"{msg} — {_提示}"
                app_log.info("远控", msg)
                page.show_dialog(提示条(msg))
        except Exception as _e_sw:
            app_log.info("远控", f"远控开关切换异常: {type(_e_sw).__name__}: {_e_sw}")

    _远控按钮, _远控按钮更新 = build_remote_toggle(_切远控)
    try:
        import 远控.服务 as _远控初
        _更新远控外观(_远控初.运行中())
    except Exception as _exc:
        app_log.debug("GUI", f'裸 except 吞异常: {type(_exc).__name__}: {_exc}')

    # 远控页接线: 开关与顶栏同一实现; 访问信息同源 (运行状态/地址/token)
    remote_page.切换远控 = _切远控

    def _远控页信息():
        try:
            import 远控.服务 as _s
            cfg = _s.取配置()
            # 2026-10-03 #7: 展示地址经 展示地址() 解析 (0.0.0.0 → 首个局域网 IP)
            return {"运行": _s.运行中(),
                    "地址": _s.展示地址(),
                    "token": cfg.get("token", ""),
                    # 2026-10-04 #7: 地址可用性提示 (绑定回环 / 未探测到局域网地址)
                    "提示": _s.地址提示()}
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
        from pathlib import Path as _P
        try:
            fobj = _P(_关闭配置).resolve()
            fobj.parent.mkdir(parents=True, exist_ok=True)
            tmp = fobj.with_name(fobj.name + ".tmp")
            tmp.write_text(_j.dumps({"关闭行为": v}, ensure_ascii=False),
                           encoding="utf-8")
            os.replace(tmp, fobj)
        except OSError as _e:
            app_log.debug("GUI", f'裸 except 吞异常: {type(_e).__name__}: {_e}')

    _托盘 = {"对象": None}

    async def _显示主窗():
        page.window.visible = True
        page.window.minimized = False
        try:
            page.update()
        except Exception as _e:
            app_log.debug("GUI", f'裸 except 吞异常: {type(_e).__name__}: {_e}')

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
            pass  # 刻意静默: try 块本身在写日志, 再加日志会递归 (日志链路兜底)

    async def _彻底退出():
        """**唯一**的退出出口 —— 步骤顺序不可改, 详见 gui_components/退出流程.py

        实测 (flet 0.86.5, 桌面是"Python + flet.exe"双进程):
          · 只用 os._exit(0): 跳过 flet 的 close_flet_view(), flet.exe 变孤儿窗口
            (界面还在、没有后端、点关闭没反应) = 用户报的"关不掉 / 界面卡死"
          · 只用 page.window.destroy(): 客户端正常回收, 但 ft.run() 不返回, Python 挂住
        故必须 destroy → 等 flet 收尾 → 兜底强退。
        """
        from gui_components.退出流程 import 执行退出
        # 埋点: 退出路径此前直到最后一步都零日志 —— 中途挂死时无迹可查
        # (冒烟脚本 S3 靠它区分 "关闭事件未送达" 与 "退出流程中途挂死")
        app_log.info("退出", "开始退出流程 (停远控→停托盘→任务检查点→落盘→销毁窗口)")
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
                except Exception as _e:
                    app_log.debug("GUI", f'裸 except 吞异常: {type(_e).__name__}: {_e}')
            except Exception as _e_tray:
                app_log.info("托盘", f"托盘不可用, 取消隐藏以保持可操作: {_e_tray}")
                try:
                    page.show_dialog(提示条("系统托盘不可用, 已取消关闭; 建议再点关闭并选直接退出"))
                except Exception as _e:
                    app_log.debug("GUI", f'裸 except 吞异常: {type(_e).__name__}: {_e}')
                return
        page.window.visible = False
        # 显式 update: window 属性变更须 update 才下发到客户端 (与 _显示主窗 对称)。
        # 旧实现缺这一句, "最小化到托盘"点击后窗口不隐藏 —— 托盘其实建好了,
        # 但用户视角就是"没反应/失效"
        try:
            page.update()
        except Exception as _e:
            app_log.debug("GUI", f'裸 except 吞异常: {type(_e).__name__}: {_e}')

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
        )
        # 令牌色由 main() 作用域的 取色/登记重刷 提供 (Phase 3)

        记住 = ft.Checkbox(value=False)
        # 埋点: 冒烟脚本(测试/冒烟_关闭关键路径.py)以日志行为断言依据,
        # 同时给生产日志留运行痕迹 (v2.4.19 教训: 关键路径需要可观测性)
        app_log.info("关闭", "弹出关闭确认弹窗")

        def _弹层关闭():
            try:
                page.pop_dialog()
            except Exception as _e:
                app_log.debug("GUI", f'裸 except 吞异常: {type(_e).__name__}: {_e}')

        def _切换记住(e):
            记住.value = not 记住.value
            try:
                记住.update()
            except Exception as _e:
                app_log.debug("GUI", f'裸 except 吞异常: {type(_e).__name__}: {_e}')

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
            app_log.info("关闭", "用户取消关闭, 窗口保持")
            _弹层关闭()

        rows = [txt("要最小化到系统托盘（远控保持运行），还是直接退出？",
                    color=ft.Colors.ON_SURFACE)]
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
                 content=txt("记住我的选择，以后不再询问", color=ft.Colors.ON_SURFACE),
                 on_tap=_切换记住)],
            spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER))

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                [ft.Icon(ft.Icons.LOGOUT, size=20, color=取色('text-secondary')),
                 txt("关闭窗口", size=SIZE_SUBTITLE, weight=WEIGHT_SUBTITLE,
                     color=ft.Colors.ON_SURFACE)],
                spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            content=ft.Container(
                content=ft.Column(rows, tight=True, spacing=12), width=430),
            actions=[
                ft.TextButton("直接退出", on_click=_选退出,
                              style=ft.ButtonStyle(color=取色('status-error'))),
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

    # 页内标题不带版本号 (设计稿 titlebar 只写应用名); 窗口标题仍用 _应用名
    # 带版本, 便于支持与排查 —— 原先两处都带版本, 视觉上重复。
    top_bar = build_top_bar(page, "小说爬虫", _theme_toggle_btn[0],
                            extra_controls=[_远控按钮])

    # ---- 整体布局 (三段式: 顶栏 + 侧边导航 + 主内容) ----
    main_row = ft.Row([
        rail.build(),
        # 主内容区底色 = --bg-primary (日间 #F5F5F5 / 夜间 #202020)。
        # ⚠️ 注意: 不能用 ft.Colors.SURFACE_CONTAINER —— 那个槽位在当前主题里
        #    对应 --bg-tertiary (夜间 #383838), 比设计稿要求的页面底亮一档,
        #    会让「页面底 vs 卡片底」的两档层次在夜间糊掉。页面底没有对应的
        #    ColorScheme 槽位(0.86 无 background), 只能在此显式赋值。
        ft.Container(
            content=ft.Container(
                content=content_stack, expand=True,
                padding=ft.Padding.symmetric(horizontal=20, vertical=16),
            ),
            expand=True,
            bgcolor=ft.Colors.SURFACE,   # ← 页面底走 surface, 卡片在页面内另行赋白
        ),
    ], expand=True, spacing=0, vertical_alignment=ft.CrossAxisAlignment.STRETCH)

    page.add(
        ft.Column(
            [top_bar, main_row, status_bar],
            spacing=0,
            expand=True,
        ),
    )

    # ---- 截图/自检钩子 (2026-10-06, 仅环境变量触发: 正常使用完全不受影响) ----
    #   用途: "设计稿 vs 程序"逐页对照 (6 页 × 日夜); 解析见 解析启动钩子()。
    #   放在 page.add 之后: 必须先有内容再切页, 否则 Stack 可见性判定拿不到索引。
    try:
        _钩子 = 解析启动钩子(list(pages_map), os.environ)
        if _钩子['警告']:
            app_log.info("系统", f"[测试钩子] {_钩子['警告']}")
        if _钩子['夜间']:
            toggle_theme()
            app_log.info("系统", "[测试钩子] 启动主题 = 夜间")
        if _钩子['页']:
            _switch_page(_钩子['页'])
            app_log.info("系统", f"[测试钩子] 启动页 = {_钩子['页']}")
    except Exception as _e_钩子:
        app_log.debug("系统", f'启动钩子失败(不影响使用): {type(_e_钩子).__name__}: {_e_钩子}')

    # 退出时: 先停掉全部运行中任务 (置位 stop_event, 爬虫循环会保存检查点并
    # 优雅退出, 避免 "cannot schedule new futures after interpreter shutdown"),
    # 再关闭日志句柄
    def _on_disconnect(e):
        try:
            for t in task_manager.get_all_tasks():
                if t.status in ("running", "pending"):
                    t.stop_flag.set()
        except Exception as _e:
            app_log.debug("GUI", f'裸 except 吞异常: {type(_e).__name__}: {_e}')
        try:
            app_log.close()
        except Exception:
            pass  # 刻意静默: try 块本身在写日志, 再加日志会递归 (日志链路兜底)
    try:
        page.on_disconnect = _on_disconnect
    except Exception as _exc:
        app_log.debug("GUI", f'裸 except 吞异常: {type(_exc).__name__}: {_exc}')


def 解析启动钩子(页集, 环境: dict) -> dict:
    """解析截图/自检钩子环境变量（**纯函数**，便于离线测试）。

    - `NC_START_PAGE=<crawl|history|deadbook|sites|log|remote>`：启动直接切到该页；
    - `NC_THEME=dark`：启动即夜间主题。

    为什么需要这两个钩子：做"设计稿 vs 程序"逐页对照时要截 6 页 × 日夜共 12 张图，
    而**鼠标坐标点击在 DPI 缩放下不可靠**（实测点「死书清单」落到了「远控」页）——
    有了钩子就能纯环境变量驱动，不点鼠标。

    Returns:
        {'页': str|None（None=不动）, '夜间': bool, '警告': str（空=无）}
    """
    页 = (环境.get('NC_START_PAGE') or '').strip()
    夜间 = (环境.get('NC_THEME') or '').strip().lower() in ('dark', 'night')
    警告 = ''
    目标页 = None
    if 页:
        if 页 in 页集:
            目标页 = 页
        else:
            警告 = f'NC_START_PAGE 无效, 忽略: {页} (可选: {", ".join(页集)})'
    return {'页': 目标页, '夜间': 夜间, '警告': 警告}


if __name__ == "__main__":
    ft.run(main)