# -*- coding: utf-8 -*-
"""抓取页签：URL输入、模式选择、参数设置、任务列表、进度日志

注意：Flet UI 操作必须在主线程的 asyncio 事件循环中执行。
后台线程（Timer / 爬虫子线程）对 UI 的变更必须通过 `page.run_task()`
提交到主线程，否则会出现控件丢失、数据竞争或崩溃。
"""
import flet as ft
import os
import subprocess
import threading
import asyncio
from .task_manager import TaskManager

# PyInstaller 打包后路径契约
_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys as _sys; _sys.path.insert(0, _HERE)  # noqa: E402
from _path_utils import resolve_output_dir  # noqa: E402

# 统一日志模块 (GUI 操作记录)
try:
    import 日志 as app_log
except Exception:
    app_log = None

# UI 主题系统 (卡片/按钮/状态标签/日志终端)
from .ui_theme import (  # noqa: E402
    make_card, status_chip, status_color, filled_btn, tonal_btn,
    outline_btn, text_btn, danger_btn, BTN_TEXT_STYLE,
    LOG_TERMINAL_BG, LOG_TERMINAL_FONT, log_line_color,
)

# 统一字体规范
from .ui_morandi import (FONT_STACK, SIZE_TITLE, SIZE_SUBTITLE, SIZE_LABEL,
                         SIZE_BODY, SIZE_SMALL, SIZE_TINY,
                         WEIGHT_TITLE, WEIGHT_SUBTITLE, WEIGHT_BODY,
                         MORANDI_PRIMARY, MORANDI_ERROR,
                         MORANDI_SUCCESS)  # noqa: E402


def _log(source: str, message: str):
    """GUI 操作日志 (写盘失败不影响界面)"""
    if app_log is not None:
        try:
            app_log.info(source, message)
        except Exception:
            pass


def _validate_url(url: str):
    """校验小说 URL: 仅 http/https 公网地址 (拒绝 localhost/内网, 防 SSRF)"""
    try:
        from sites_config import validate_public_url
        validate_public_url(url)
        return None
    except Exception as e:
        return str(e)


class CrawlTab:
    """抓取页签组件"""

    def __init__(self, task_manager: TaskManager):
        self.task_manager = task_manager
        self.page = None
        self.selected_task_id = None
        self._selected_file_idx = None  # preview 使用，此处保留对称命名
        # UI 元素引用
        self.url_input = None
        self.mode_dropdown = None
        self.start_chapter = None
        self.end_chapter = None
        self.sort_switch = None
        self.resume_switch = None
        self.speed_dropdown = None
        self.output_dir_input = None
        self.task_list_view = None
        self.progress_bar = None
        self.progress_text = None
        self.log_list = None
        self.stop_btn = None
        self.open_folder_btn = None
        self.file_picker = None  # 由 gui_app 注册的 FilePicker (导入网址用)
        # 批量导入内嵌面板控件
        self.batch_panel = None
        self.batch_input = None
        self.batch_hint = None
        self.batch_confirm_btn = None
        self.batch_cancel_btn = None
        self._pending_urls = []
        self._pending_invalid = []
        self._stop_event = threading.Event()
        self._refresh_thread = None
        self._task_list_sig = None  # 任务列表特征: 无变化时跳过重建 (避免控件频繁替换导致点击丢失)

    # ------------------------------------------------------------------ UI
    def build(self) -> ft.Control:
        """构建抓取页签的完整UI"""
        # === 左侧：任务列表 ===
        self.task_list_view = ft.ListView(
            expand=True,
            spacing=4,
            auto_scroll=False,
        )
        task_panel = make_card(
            ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.LIST_ALT, size=18, color=MORANDI_PRIMARY),
                    ft.Text("任务列表", size=SIZE_TITLE, weight=WEIGHT_TITLE,
                            font_family=FONT_STACK),
                ]),
                ft.Container(content=self.task_list_view, expand=True),
            ]),
            width=300,
        )

        # === 右侧上：输入区 ===
        self.url_input = ft.TextField(
            label="小说目录页URL",
            hint_text="如: https://m.tanmixs.com/YzN6/ml.html",
            expand=True,
            text_style=ft.TextStyle(size=SIZE_LABEL, font_family=FONT_STACK),
        )

        self.mode_dropdown = ft.Dropdown(
            label="抓取模式",
            width=150,
            text_style=ft.TextStyle(size=SIZE_LABEL, font_family=FONT_STACK),
            value="full",
            options=[
                ft.dropdown.Option("full", "完整抓取"),
                ft.dropdown.Option("list", "仅看章节列表"),
                ft.dropdown.Option("test", "测试第1章"),
                ft.dropdown.Option("range", "章节区间"),
            ],
            on_select=self._on_mode_change,
        )

        self.start_chapter = ft.TextField(
            label="起始章",
            width=80,
            text_style=ft.TextStyle(size=SIZE_LABEL, font_family=FONT_STACK),
            visible=False,
            input_filter=ft.NumbersOnlyInputFilter(),
        )
        self.end_chapter = ft.TextField(
            label="结束章",
            width=80,
            text_style=ft.TextStyle(size=SIZE_LABEL, font_family=FONT_STACK),
            visible=False,
            input_filter=ft.NumbersOnlyInputFilter(),
        )

        self.speed_dropdown = ft.Dropdown(
            label="速度档位",
            # 加宽防止选中文字 (如"标准 (1线程)") 被截断
            width=180,
            text_style=ft.TextStyle(size=SIZE_LABEL, font_family=FONT_STACK),
            value="standard",
            options=[
                ft.dropdown.Option("standard", "标准 (1线程)"),
                ft.dropdown.Option("fast", "快速 (3线程)"),
                ft.dropdown.Option("turbo", "极速 (6线程)"),
            ],
        )

        self.resume_switch = ft.Switch(
            label="断点续传",
            value=True,
            label_position=ft.LabelPosition.LEFT,
        )

        self.output_dir_input = ft.TextField(
            label="输出目录",
            width=200,
            text_style=ft.TextStyle(size=SIZE_LABEL, font_family=FONT_STACK),
            value="抓取结果",
        )

        start_btn = filled_btn(
            "开始抓取",
            icon=ft.Icons.PLAY_ARROW,
            on_click=self.on_start_click,
            tooltip="按所选模式开始抓取",
        )

        # 批量导入网址按钮 (导入 txt 清单 / 粘贴 URL 列表)
        import_btn = tonal_btn(
            "导入网址",
            icon=ft.Icons.UPLOAD_FILE,
            on_click=self.on_import_click,
            tooltip="从 txt 清单文件导入网址",
        )
        paste_btn = tonal_btn(
            "粘贴网址",
            icon=ft.Icons.CONTENT_PASTE,
            on_click=self.on_paste_click,
            tooltip="粘贴多个网址批量抓取",
        )

        self.stop_btn = danger_btn(
            "停止",
            icon=ft.Icons.STOP,
            on_click=self.on_stop_click,
            disabled=True,
            tooltip="停止当前任务",
        )

        self.open_folder_btn = outline_btn(
            "打开结果文件夹",
            icon=ft.Icons.FOLDER_OPEN,
            on_click=self.on_open_folder_click,
        )

        # === 批量导入内嵌面板 (粘贴/导入网址确认区, 默认隐藏) ===
        self.batch_input = ft.TextField(
            multiline=True,
            min_lines=4,
            max_lines=10,
            hint_text="每行一个小说目录页URL，# 开头的行为注释",
            text_style=ft.TextStyle(size=SIZE_BODY, font_family=FONT_STACK),
            expand=True,
        )
        self.batch_hint = ft.Text("", size=SIZE_SMALL, weight=WEIGHT_BODY,
                                  color=ft.Colors.ON_SURFACE_VARIANT,
                                  font_family=FONT_STACK)
        self.batch_parse_btn = tonal_btn(
            "解析网址",
            icon=ft.Icons.FACT_CHECK,
            on_click=self._on_batch_parse,
            visible=False,
        )
        self.batch_confirm_btn = filled_btn(
            "开始批量抓取",
            icon=ft.Icons.PLAYLIST_PLAY,
            on_click=lambda e: self._start_batch(self._pending_urls),
            visible=False,
        )
        self.batch_cancel_btn = text_btn(
            "取消", on_click=self._hide_batch_panel, visible=False)
        self.batch_panel = make_card(
            ft.Column([
                ft.Row([self.batch_input], expand=True),
                ft.Row([self.batch_hint], expand=True),
                ft.Row([self.batch_parse_btn, self.batch_confirm_btn,
                        self.batch_cancel_btn]),
            ]),
            padding=10,
            bgcolor=ft.Colors.SECONDARY_CONTAINER,
            visible=False,
        )

        input_area = make_card(
            ft.Column([
                # URL 独占一行，自动拉伸填满宽度
                ft.Row([self.url_input]),
                # 模式 / 章节区间 / 速度档位，自动换行
                ft.Row([self.mode_dropdown,
                        self.start_chapter, self.end_chapter,
                        self.speed_dropdown], wrap=True),
                # 操作按钮行，自动换行
                ft.Row([import_btn, paste_btn, self.resume_switch,
                        self.output_dir_input,
                        start_btn, self.stop_btn, self.open_folder_btn], wrap=True),
                self.batch_panel,
            ]),
        )

        # === 右侧下：进度+日志 ===
        # 主进度: 进度环 (progress_total 已知时显示比例, 否则转圈)
        self.progress_bar = ft.ProgressRing(
            width=64, height=64, stroke_width=7, value=0,
            color=ft.Colors.PRIMARY,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
        )
        self.progress_text = ft.Text("就绪", size=SIZE_SMALL,
                                     weight=WEIGHT_BODY,
                                     color=ft.Colors.ON_SURFACE_VARIANT,
                                     font_family=FONT_STACK)

        self.log_list = ft.ListView(
            expand=True,
            spacing=1,
            auto_scroll=True,
        )

        log_area = make_card(
            ft.Column([
                ft.Row([
                    self.progress_bar,
                    ft.Container(width=8),
                    self.progress_text,
                ]),
                # 终端风格日志面板: 深底 + 等宽字体
                ft.Container(
                    content=self.log_list,
                    expand=True,
                    bgcolor=LOG_TERMINAL_BG,
                    border_radius=8,
                    padding=8,
                ),
            ], spacing=10),
            expand=True,
        )

        # 右侧整体
        right_panel = ft.Column([
            input_area,
            ft.Container(content=log_area, expand=True),
        ], expand=True, spacing=10)

        # 先显示一个空的任务列表
        self._refresh_task_list_impl()
        self._refresh_display_impl()

        # 左右布局
        return ft.Row([task_panel, right_panel], expand=True, spacing=10)

    # --------------------------------------------------------- 主线程调度
    def _dispatch_ui(self, fn):
        """将 UI 更新函数提交到 Flet 主线程 asyncio 事件循环

        Flet 不允许在非主线程修改控件或调用 page.update()，
        必须通过 page.run_task() 提交 async 函数。
        """
        if self.page is None:
            return
        try:
            async def _runner():
                fn()
                try:
                    self.page.update()
                except Exception:
                    pass
            self.page.run_task(_runner)
        except Exception:
            pass

    # --------------------------------------------------------------- 回调
    def _on_mode_change(self, e):
        """模式切换时显示/隐藏章节区间输入（在主线程）"""
        is_range = self.mode_dropdown.value == "range"
        self.start_chapter.visible = is_range
        self.end_chapter.visible = is_range
        try:
            e.page.update()
        except Exception:
            pass

    # ----------------------------------------------------------- 批量导入网址
    async def on_import_click(self, e):
        """导入网址按钮: 打开系统文件选择器选择 .txt 清单 (每行一个URL)

        Flet 0.86: FilePicker 为 Service, await pick_files() 直接返回文件列表。
        """
        if self.file_picker is None:
            self._show_snackbar_impl("文件选择器未就绪")
            return
        try:
            files = await self.file_picker.pick_files(
                allow_multiple=False,
                allowed_extensions=["txt"],
                dialog_title="选择小说网址清单 (每行一个URL, # 开头为注释)",
            )
        except Exception as ex:
            self._show_snackbar_impl(f"打开文件选择器失败: {ex}")
            return
        if not files:
            return  # 用户取消
        path = files[0].path
        # 读取清单文件 (先 UTF-8 后 GBK 兜底)
        raw = None
        for enc in ('utf-8', 'gbk'):
            try:
                with open(path, encoding=enc) as f:
                    raw = f.read()
                break
            except UnicodeDecodeError:
                continue
            except Exception as ex:
                self._show_snackbar_impl(f"读取文件失败: {ex}")
                return
        if raw is None:
            self._show_snackbar_impl("读取文件失败: 编码无法识别")
            return
        urls, invalid = self._parse_urls(raw)
        self._show_batch_panel(urls, invalid, source=path)

    def on_paste_click(self, e):
        """粘贴网址按钮: 展开内嵌面板, 粘贴多行 URL 列表"""
        self.batch_input.value = ""
        self.batch_input.visible = True
        self.batch_hint.visible = False
        self.batch_parse_btn.visible = True
        self.batch_confirm_btn.visible = False
        self.batch_cancel_btn.visible = True
        self.batch_panel.visible = True
        self._pending_urls = []
        self._pending_invalid = []
        try:
            e.page.update()
        except Exception:
            pass

    def _on_batch_parse(self, e):
        """解析按钮: 解析粘贴的 URL 列表并显示结果摘要"""
        raw = self.batch_input.value or ""
        urls, invalid = self._parse_urls(raw)
        self._show_batch_panel(urls, invalid)

    def _hide_batch_panel(self, e=None):
        """隐藏批量导入面板"""
        self.batch_panel.visible = False
        self.batch_input.visible = True
        self.batch_hint.visible = False
        self.batch_parse_btn.visible = False
        self.batch_confirm_btn.visible = False
        self.batch_cancel_btn.visible = False
        try:
            self.page.update()
        except Exception:
            pass

    def _parse_urls(self, raw_text):
        """解析并校验 URL 列表, 返回 (有效列表, 无效列表[(url, 原因)])"""
        urls, invalid = [], []
        for line in (raw_text or '').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            err = _validate_url(line)
            if err:
                invalid.append((line, err))
            else:
                urls.append(line)
        return urls, invalid

    def _show_batch_panel(self, urls, invalid, source=""):
        """在内嵌面板中展示解析结果, 由用户确认后创建批量任务"""
        if not urls:
            tip = f"未解析到有效网址 (无效 {len(invalid)} 条)"
            if invalid:
                tip += f"，首条原因: {invalid[0][1]}"
            self._show_snackbar_impl(tip)
            return
        self._pending_urls = urls
        invalid_tip = f"，{len(invalid)} 条无效已忽略" if invalid else ""
        preview = '\n'.join(f"  {u}" for u in urls[:5])
        if len(urls) > 5:
            preview += f"\n  ... 等 {len(urls)} 条"
        self.batch_hint.value = (f"解析到 {len(urls)} 个有效网址{invalid_tip}，确认后开始批量抓取:"
                                 f"\n{preview}")
        self.batch_input.visible = False
        self.batch_hint.visible = True
        self.batch_parse_btn.visible = False
        self.batch_confirm_btn.visible = True
        self.batch_cancel_btn.visible = True
        self.batch_panel.visible = True
        try:
            self.page.update()
        except Exception:
            pass

    def _start_batch(self, urls, ev=None):
        """批量创建抓取任务: 每个 URL 一个独立任务 (任务列表逐条显示各自进度)

        同域并发保护: 统计同域已有 running 任务, 超过限制时提示用户
        (同一站点多任务并发可能触发验证码/限流)。
        """
        speed_map = {"standard": (1, 1.0), "fast": (3, 0.5), "turbo": (6, 0.2)}
        threads, delay = speed_map.get(self.speed_dropdown.value, (1, 1.0))
        output_dir = self.output_dir_input.value.strip() or None
        resume = self.resume_switch.value

        # 同域并发统计 (仅提示, 不阻断)
        from urllib.parse import urlparse
        running_domains = {}
        for t in self.task_manager.get_all_tasks():
            if t.status in ("running", "pending"):
                d = urlparse(t.url).netloc
                running_domains[d] = running_domains.get(d, 0) + 1
        dup_domains = [d for d, n in running_domains.items() if n >= 2]
        if dup_domains:
            self._show_snackbar_impl(
                f"提示: 站点 {dup_domains[0]} 已有 {running_domains[dup_domains[0]]} 个任务在跑, "
                f"同站并发可能触发验证码")

        # 每个 URL 创建独立任务 → 任务列表逐条显示各书进度
        created = 0
        for url in urls:
            task_id = self.task_manager.create_task(
                url=url,
                mode="full",
                threads=threads,
                delay=delay,
                resume=resume,
                output_dir=output_dir,
            )
            created += 1
            self.selected_task_id = task_id  # 高亮最后创建的任务

        self.stop_btn.disabled = False
        self._hide_batch_panel()
        _log("GUI", f"批量抓取启动: {created} 个网址 (线程={threads} 延迟={delay} 续传={resume})\n"
                    f"  网址列表: {urls}")
        self._show_snackbar_impl(f"已创建 {created} 个抓取任务 (每本书独立进度)")
        # 启动后台刷新线程
        self._ensure_refresh_thread()

    def on_start_click(self, e):
        """开始抓取按钮回调（在主线程）"""
        url = self.url_input.value.strip()
        if not url:
            self._show_snackbar_impl("请输入小说目录页URL")
            return

        mode = self.mode_dropdown.value
        chapter_range = None
        if mode == "range":
            try:
                start = int(self.start_chapter.value)
                end = int(self.end_chapter.value)
                if start > end:
                    self._show_snackbar_impl("起始章不能大于结束章")
                    return
                chapter_range = (start, end)
            except (ValueError, TypeError):
                self._show_snackbar_impl("请输入有效的章节号")
                return

        # 速度档位映射
        speed_map = {"standard": (1, 1.0), "fast": (3, 0.5), "turbo": (6, 0.2)}
        threads, delay = speed_map.get(self.speed_dropdown.value, (1, 1.0))

        output_dir = self.output_dir_input.value.strip() or None

        # URL 安全校验 (防 SSRF: 仅公网 http/https)
        err = _validate_url(url)
        if err:
            _log("GUI", f"URL 校验失败: {url} 原因: {err}")
            self._show_snackbar_impl(f"网址无效: {err}")
            return

        # 创建任务
        task_id = self.task_manager.create_task(
            url=url,
            mode=mode,
            chapter_range=chapter_range,
            threads=threads,
            delay=delay,
            resume=self.resume_switch.value,
            output_dir=output_dir,
        )
        self.selected_task_id = task_id
        self.stop_btn.disabled = False
        _log("GUI", f"开始抓取: {url} 模式={mode} 区间={chapter_range} "
                    f"线程={threads} 延迟={delay} 续传={self.resume_switch.value} → {task_id}")
        self._show_snackbar_impl(f"任务已创建: {task_id}")

        # 保存 page 引用
        self.page = e.page
        # 启动后台刷新线程
        self._ensure_refresh_thread()

    def on_stop_click(self, e):
        """停止任务按钮回调（在主线程）"""
        if self.selected_task_id:
            self.task_manager.stop_task(self.selected_task_id)
            _log("GUI", f"用户停止任务: {self.selected_task_id}")
            self._show_snackbar_impl("任务已停止")

    def on_open_folder_click(self, e):
        """打开结果文件夹

        PyInstaller onefile 模式下必须相对于 EXE 所在目录解析，
        否则会落到 _MEIPASS 临时目录或用户的 cwd。
        """
        output_dir = self.output_dir_input.value.strip() or None
        abs_dir = resolve_output_dir(output_dir)
        try:
            if os.name == 'nt':
                os.startfile(abs_dir)
            else:
                subprocess.Popen(['xdg-open', abs_dir])
        except Exception as ex:
            self._show_snackbar_impl(f"无法打开文件夹: {ex}")

    def on_task_selected(self, task_id: str):
        """任务列表选中项变化回调"""
        self.selected_task_id = task_id
        self._dispatch_ui(self._refresh_display_impl)

    # ---------------------------------------------------------- 刷新线程
    def _ensure_refresh_thread(self):
        """启动后台刷新线程（已启动则跳过）

        后台线程 sleep 1s 后把 UI 更新 dispatch 到主线程，
        本身不触碰任何 Flet 控件。
        """
        if self._refresh_thread and self._refresh_thread.is_alive():
            return
        self._stop_event.clear()
        self._refresh_thread = threading.Thread(
            target=self._refresh_loop,
            name="crawl-ui-refresh",
            daemon=True,
        )
        self._refresh_thread.start()

    def _refresh_loop(self):
        """后台刷新循环：仅 sleep + dispatch，不触碰控件"""
        import time as _time
        while not self._stop_event.is_set():
            try:
                self._dispatch_ui(self._refresh_task_list_impl)
                self._dispatch_ui(self._refresh_display_impl)
            except Exception:
                pass
            for _ in range(10):  # 1s 分 10 段，stop 响应更快
                if self._stop_event.is_set():
                    return
                _time.sleep(0.1)

    # -------------------------------------------------------- UI 实现（必须在主线程）
    def _refresh_task_list_impl(self):
        """刷新左侧任务列表 - 必须在主线程调用

        仅在任务状态签名变化时重建控件树, 避免每秒全量重建导致
        用户点击瞬间控件被替换而丢事件 (删除/重下按钮点不中的诱因)。
        """
        if self.task_list_view is None:
            return
        tasks = self.task_manager.get_all_tasks()
        sig = tuple(
            (t.task_id, t.status, t.progress_current, t.progress_total,
             t.title, t.url)
            for t in tasks
        )
        if sig == self._task_list_sig:
            return  # 无变化: 保留现有控件树
        self._task_list_sig = sig
        self.task_list_view.controls.clear()
        if not tasks:
            # 空状态：显示图标 + 提示文案
            self.task_list_view.controls.append(
                ft.Container(
                    content=ft.Column([
                        ft.Icon(ft.Icons.LIBRARY_BOOKS_OUTLINED, size=48,
                                color=ft.Colors.ON_SURFACE_VARIANT, opacity=0.5),
                        ft.Text("暂无任务", size=SIZE_TITLE,
                                color=ft.Colors.ON_SURFACE_VARIANT,
                                weight=WEIGHT_TITLE, font_family=FONT_STACK),
                        ft.Text("输入网址后点击「开始抓取」创建任务", size=SIZE_SMALL,
                                weight=WEIGHT_BODY,
                                color=ft.Colors.ON_SURFACE_VARIANT, opacity=0.7,
                                font_family=FONT_STACK),
                    ], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=ft.Padding.symmetric(vertical=40),
                )
            )
            return
        for task in tasks:
            color = status_color(task.status)
            progress_str = f"{task.progress_current}/{task.progress_total}" if task.progress_total else "0"
            title_str = task.title[:20] + "…" if len(task.title) > 20 else task.title

            # 小进度环: 进行中显示比例, 完成/失败显示固定状态色
            ring_value = 0.0
            if task.progress_total > 0:
                ring_value = min(1.0, task.progress_current / task.progress_total)
            if task.status == "completed":
                ring_value = 1.0
            ring = ft.ProgressRing(
                width=18, height=18, stroke_width=3,
                value=ring_value,
                color=color if task.status in ("completed", "failed", "stopped")
                else ft.Colors.PRIMARY,
            )

            # 操作按钮: 重新下载 / 删除 (小图标按钮)
            redownload_btn = ft.IconButton(
                icon=ft.Icons.REPLAY,
                icon_size=14,
                tooltip="重新下载 (从头重新抓取)",
                on_click=lambda e, tid=task.task_id: self.on_task_redownload(tid),
                style=ft.ButtonStyle(
                    padding=2, shape=ft.RoundedRectangleBorder(radius=6),
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
                ),
            )
            delete_btn = ft.IconButton(
                icon=ft.Icons.DELETE_OUTLINE,
                icon_size=14,
                tooltip="删除任务",
                on_click=lambda e, tid=task.task_id: self.on_task_delete(tid),
                style=ft.ButtonStyle(
                    padding=2, shape=ft.RoundedRectangleBorder(radius=6),
                    bgcolor=ft.Colors.ERROR_CONTAINER,
                    color=ft.Colors.ON_ERROR_CONTAINER,
                ),
            )

            item = ft.Container(
                content=ft.Column([
                    ft.Row([
                        ring,
                        ft.Column([
                            ft.Text(title_str, size=SIZE_LABEL, weight=WEIGHT_SUBTITLE,
                                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                                    font_family=FONT_STACK),
                            ft.Row([
                                status_chip(task.status),
                                ft.Text(progress_str, size=SIZE_TINY,
                                        weight=WEIGHT_BODY,
                                        color=ft.Colors.ON_SURFACE_VARIANT,
                                        font_family=FONT_STACK),
                            ], spacing=6),
                        ], expand=True, spacing=2, tight=True),
                        ft.Text("🔗", size=SIZE_TINY, opacity=0.5,
                                font_family=FONT_STACK),  # URL 预览指示器
                    ], spacing=6),
                    # URL 预览 (截断显示)
                    ft.Text(task.url[:50] + ("…" if len(task.url) > 50 else ""),
                            size=SIZE_TINY, weight=WEIGHT_BODY,
                            color=ft.Colors.ON_SURFACE_VARIANT, opacity=0.6,
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                            font_family=FONT_STACK),
                    ft.Row([redownload_btn, delete_btn], spacing=4),
                ], spacing=4),
                padding=ft.Padding.symmetric(horizontal=8, vertical=6),
                # 选中态: 左侧 3px 主色高亮条 + 淡主色容器 (替代粗边框, 更精致)
                border=(
                    ft.Border(
                        left=ft.BorderSide(3, ft.Colors.PRIMARY),
                        right=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT),
                        top=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT),
                        bottom=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT),
                    ) if task.task_id == self.selected_task_id
                    else ft.Border.all(1, ft.Colors.OUTLINE_VARIANT)
                ),
                border_radius=8,
                bgcolor=(ft.Colors.PRIMARY_CONTAINER
                         if task.task_id == self.selected_task_id
                         else ft.Colors.SURFACE_CONTAINER_LOW),
                ink=True,
                on_click=lambda e, tid=task.task_id: self.on_task_selected(tid),
            )
            self.task_list_view.controls.append(item)

    # ------------------------------------------------------------ 任务操作
    def on_task_delete(self, task_id: str):
        """删除任务: 弹确认对话框, 可选是否删除已下载的源文件"""
        task = self.task_manager.get_task(task_id)
        if not task:
            return
        if self.page is None:
            return
        has_file = bool(task.output_file) and os.path.isfile(task.output_file)
        del_file_check = ft.Checkbox(
            label="同时删除已下载的源文件",
            value=False,
            disabled=not has_file,
            visible=has_file,
            label_style=ft.TextStyle(size=SIZE_BODY, font_family=FONT_STACK),
        )
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("删除任务", size=SIZE_SUBTITLE, weight=WEIGHT_TITLE,
                          font_family=FONT_STACK),
            content=ft.Column([
                ft.Text(f"确定删除任务「{task.title[:30]}」吗？", size=SIZE_BODY,
                        weight=WEIGHT_BODY, font_family=FONT_STACK),
                del_file_check,
            ], tight=True, spacing=8),
            actions=[
                ft.TextButton(
                    "取消",
                    on_click=lambda ev: self._close_dialog(),
                    style=ft.ButtonStyle(text_style=BTN_TEXT_STYLE),
                ),
                ft.TextButton(
                    "删除",
                    on_click=lambda ev: self._confirm_delete(task_id, del_file_check, ev),
                    style=ft.ButtonStyle(
                        color=ft.Colors.ERROR,
                        text_style=BTN_TEXT_STYLE,
                    ),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        try:
            # Flet 0.86: 对话框用 show_dialog() 打开 (旧版 page.open 已移除)
            self.page.show_dialog(dlg)
        except Exception as ex:
            _log("GUI", f"打开删除确认对话框失败: {ex}")
            self._show_snackbar_impl(f"打开对话框失败: {ex}")

    def _close_dialog(self):
        """关闭对话框 (Flet 0.86: pop_dialog 关闭最近的对话框)"""
        try:
            self.page.pop_dialog()
        except Exception:
            pass

    def _confirm_delete(self, task_id: str, del_file_check: ft.Checkbox, ev=None):
        """确认删除任务 (复选框决定是否同时删除已下载的源文件)"""
        delete_file = bool(del_file_check.value)
        self._close_dialog()
        ok = self.task_manager.delete_task(task_id, delete_file=delete_file)
        if ok:
            if self.selected_task_id == task_id:
                self.selected_task_id = None
            self._task_list_sig = None  # 强制下次重建列表
            _log("GUI", f"删除任务 {task_id} (删除源文件={delete_file})")
            self._show_snackbar_impl(
                f"任务已删除" + ("，源文件已删除" if delete_file else ""))
        else:
            self._show_snackbar_impl("删除失败: 任务不存在")

    def on_task_redownload(self, task_id: str):
        """重新下载: 在原任务内从头重新抓取 (不新建任务, 输出覆盖)"""
        task = self.task_manager.get_task(task_id)
        if not task:
            return
        if task.status == "running":
            self._show_snackbar_impl("任务运行中，请先停止再重新下载")
            return
        ok = self.task_manager.restart_task(task_id)
        if ok:
            self.selected_task_id = task_id
            self.stop_btn.disabled = False
            _log("GUI", f"重新下载 (原任务重启): {task_id} ({task.url})")
            self._show_snackbar_impl("已在原任务中重新开始抓取")
            self._ensure_refresh_thread()
        else:
            self._show_snackbar_impl("重新下载失败: 任务不存在或运行中")

    def _refresh_display_impl(self):
        """刷新右侧进度和日志 - 必须在主线程调用"""
        if not self.selected_task_id:
            return
        task = self.task_manager.get_task(self.selected_task_id)
        if not task:
            return

        # 更新进度环
        if task.progress_total > 0:
            self.progress_bar.value = task.progress_current / task.progress_total
            pct = (task.progress_current / task.progress_total) * 100
            self.progress_text.value = f"{task.progress_current}/{task.progress_total} ({pct:.1f}%) | {task.title}"
        elif task.status == "completed":
            self.progress_bar.value = 1.0
            self.progress_text.value = f"完成 | {task.title}"
        else:
            self.progress_bar.value = None  # 未知总量: 转圈
            self.progress_text.value = f"{task.status} | {task.title}"

        # 进度环颜色随状态变化
        self.progress_bar.color = status_color(task.status)

        # 更新按钮状态
        if task.status in ("completed", "failed"):
            self.stop_btn.disabled = True
        else:
            self.stop_btn.disabled = False

        # 更新日志（只显示最近100条, 终端风格: 等宽字体 + 级别着色）
        self.log_list.controls.clear()
        for log in task.logs[-100:]:
            msg = log['msg']
            text_color = log_line_color(msg)
            if '[错误]' in msg or '失败' in msg:
                text_color = MORANDI_ERROR
            elif '成功' in msg or '完成' in msg:
                text_color = MORANDI_SUCCESS
            self.log_list.controls.append(
                ft.Text(
                    f"[{log['time']}] {msg}",
                    size=SIZE_TINY,
                    font_family=LOG_TERMINAL_FONT,
                    color=text_color,
                    selectable=True,
                )
            )

    # -------------------------------------------------------- snackbar
    def _show_snackbar_impl(self, msg: str):
        """显示提示消息 - 必须在主线程调用

        Flet 0.86 无 page.show_snackbar, 改用进度文本区显示提示 (稳定可靠)。
        """
        if self.page is None:
            return
        try:
            self.progress_text.value = f"提示: {msg}"
            self.page.update()
        except Exception:
            pass
