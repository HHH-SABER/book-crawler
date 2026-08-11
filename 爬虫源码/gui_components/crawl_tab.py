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
        self._stop_event = threading.Event()
        self._refresh_thread = None

    # ------------------------------------------------------------------ UI
    def build(self) -> ft.Control:
        """构建抓取页签的完整UI"""
        # === 左侧：任务列表 ===
        self.task_list_view = ft.ListView(
            expand=True,
            spacing=2,
            auto_scroll=False,
        )
        task_panel = ft.Container(
            content=ft.Column([
                ft.Text("任务列表", size=14, weight=ft.FontWeight.BOLD),
                ft.Container(content=self.task_list_view, expand=True),
            ]),
            width=250,
            padding=10,
            bgcolor=ft.colors.GREY_50,
            border=ft.border.all(1, ft.colors.GREY_300),
            border_radius=5,
            expand=True,
        )

        # === 右侧上：输入区 ===
        self.url_input = ft.TextField(
            label="小说目录页URL",
            hint_text="如: https://m.tanmixs.com/YzN6/ml.html",
            expand=True,
            text_size=13,
        )

        self.mode_dropdown = ft.Dropdown(
            label="抓取模式",
            width=150,
            text_size=13,
            value="full",
            options=[
                ft.dropdown.Option("full", "完整抓取"),
                ft.dropdown.Option("list", "仅看章节列表"),
                ft.dropdown.Option("test", "测试第1章"),
                ft.dropdown.Option("range", "章节区间"),
            ],
            on_change=self._on_mode_change,
        )

        self.start_chapter = ft.TextField(
            label="起始章",
            width=80,
            text_size=13,
            visible=False,
            input_filter=ft.NumbersOnlyInputFilter(),
        )
        self.end_chapter = ft.TextField(
            label="结束章",
            width=80,
            text_size=13,
            visible=False,
            input_filter=ft.NumbersOnlyInputFilter(),
        )

        self.speed_dropdown = ft.Dropdown(
            label="速度档位",
            width=130,
            text_size=13,
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
            text_size=13,
            value="抓取结果",
        )

        start_btn = ft.ElevatedButton(
            "开始抓取",
            icon=ft.icons.PLAY_ARROW,
            on_click=self.on_start_click,
            style=ft.ButtonStyle(bgcolor=ft.colors.GREEN, color=ft.colors.WHITE),
        )

        self.stop_btn = ft.ElevatedButton(
            "停止",
            icon=ft.icons.STOP,
            on_click=self.on_stop_click,
            disabled=True,
            style=ft.ButtonStyle(bgcolor=ft.colors.RED_400, color=ft.colors.WHITE),
        )

        self.open_folder_btn = ft.ElevatedButton(
            "打开结果文件夹",
            icon=ft.icons.FOLDER_OPEN,
            on_click=self.on_open_folder_click,
        )

        input_area = ft.Container(
            content=ft.Column([
                ft.Row([self.url_input, self.mode_dropdown,
                        self.start_chapter, self.end_chapter,
                        self.speed_dropdown], wrap=True),
                ft.Row([self.resume_switch, self.output_dir_input,
                        start_btn, self.stop_btn, self.open_folder_btn], wrap=True),
            ]),
            padding=10,
            bgcolor=ft.colors.GREY_50,
            border=ft.border.all(1, ft.colors.GREY_300),
            border_radius=5,
        )

        # === 右侧下：进度+日志 ===
        self.progress_bar = ft.ProgressBar(width=400, height=20, value=0)
        self.progress_text = ft.Text("就绪", size=12)

        self.log_list = ft.ListView(
            expand=True,
            spacing=1,
            auto_scroll=True,
        )

        log_area = ft.Container(
            content=ft.Column([
                ft.Row([self.progress_bar, self.progress_text]),
                ft.Container(
                    content=self.log_list,
                    expand=True,
                    bgcolor=ft.colors.BLACK87,
                    border_radius=5,
                    padding=5,
                ),
            ]),
            expand=True,
            padding=10,
            bgcolor=ft.colors.GREY_50,
            border=ft.border.all(1, ft.colors.GREY_300),
            border_radius=5,
        )

        # 右侧整体
        right_panel = ft.Column([
            input_area,
            ft.Container(content=log_area, expand=True),
        ], expand=True)

        # 先显示一个空的任务列表
        self._refresh_task_list_impl()
        self._refresh_display_impl()

        # 左右布局
        return ft.Row([task_panel, right_panel], expand=True)

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
        self._show_snackbar_impl(f"任务已创建: {task_id}")

        # 保存 page 引用
        self.page = e.page
        # 启动后台刷新线程
        self._ensure_refresh_thread()

    def on_stop_click(self, e):
        """停止任务按钮回调（在主线程）"""
        if self.selected_task_id:
            self.task_manager.stop_task(self.selected_task_id)
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
        """刷新左侧任务列表 - 必须在主线程调用"""
        if self.task_list_view is None:
            return
        self.task_list_view.controls.clear()
        tasks = self.task_manager.get_all_tasks()
        if not tasks:
            self.task_list_view.controls.append(
                ft.Text("暂无任务", size=12, color=ft.colors.GREY_500, italic=True)
            )
            return
        for task in tasks:
            status_colors = {
                "running": ft.colors.BLUE,
                "completed": ft.colors.GREEN,
                "failed": ft.colors.RED,
                "pending": ft.colors.GREY,
            }
            color = status_colors.get(task.status, ft.colors.GREY)
            progress_str = f"{task.progress_current}/{task.progress_total}" if task.progress_total else "0"
            title_str = task.title[:15] + "…" if len(task.title) > 15 else task.title

            item = ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.icons.CIRCLE, color=color, size=8),
                        ft.Text(title_str, size=11, weight=ft.FontWeight.BOLD),
                    ], tight=True),
                    ft.Text(f"{progress_str} | {task.status}", size=10, color=ft.colors.GREY_600),
                ]),
                padding=5,
                border=(ft.border.all(2, ft.colors.BLUE)
                         if task.task_id == self.selected_task_id
                         else None),
                border_radius=3,
                on_click=lambda e, tid=task.task_id: self.on_task_selected(tid),
            )
            self.task_list_view.controls.append(item)

    def _refresh_display_impl(self):
        """刷新右侧进度和日志 - 必须在主线程调用"""
        if not self.selected_task_id:
            return
        task = self.task_manager.get_task(self.selected_task_id)
        if not task:
            return

        # 更新进度条
        if task.progress_total > 0:
            self.progress_bar.value = task.progress_current / task.progress_total
            pct = (task.progress_current / task.progress_total) * 100
            self.progress_text.value = f"{task.progress_current}/{task.progress_total} ({pct:.1f}%) | {task.title}"
        else:
            self.progress_bar.value = 0
            self.progress_text.value = f"{task.status} | {task.title}"

        # 更新按钮状态
        if task.status in ("completed", "failed"):
            self.stop_btn.disabled = True
        else:
            self.stop_btn.disabled = False

        # 更新日志（只显示最近100条）
        self.log_list.controls.clear()
        for log in task.logs[-100:]:
            text_color = ft.colors.WHITE70
            msg = log['msg']
            if '[错误]' in msg or '失败' in msg:
                text_color = ft.colors.RED_200
            elif '成功' in msg or '完成' in msg:
                text_color = ft.colors.GREEN_200
            self.log_list.controls.append(
                ft.Text(
                    f"[{log['time']}] {msg}",
                    size=10,
                    color=text_color,
                    selectable=True,
                )
            )

    # -------------------------------------------------------- snackbar
    def _show_snackbar_impl(self, msg: str):
        """显示提示消息 - 必须在主线程调用"""
        if self.page is None:
            return
        try:
            self.page.show_snackbar(ft.SnackBar(content=ft.Text(msg)))
        except Exception:
            pass
