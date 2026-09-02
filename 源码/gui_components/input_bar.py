# -*- coding: utf-8 -*-
"""单行紧凑输入条：URL + 模式 + 速度 + 开始/停止 + 批量 + 输出目录

从原 crawl_tab 的输入区 (多行卡片) 压缩为两行:
  第一行: URL 输入(自适应拉伸) | 抓取模式 | 速度 | 开始 | 停止
  第二行: 批量导入 | 粘贴网址 | 章节区间(range时) | 断点续传 | 输出目录 | 打开文件夹
批量导入面板按需在下方展开 (沿用原交互逻辑)。
"""
import flet as ft
import os
import sys
import subprocess

from .task_manager import TaskManager

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys as _sys; _sys.path.insert(0, _HERE)  # noqa: E402
from _path_utils import resolve_output_dir  # noqa: E402

try:
    import 日志 as app_log
except Exception:
    app_log = None

from .ui_theme import (make_card, filled_btn, tonal_btn, outline_btn,
                       text_btn, danger_btn)
from .ui_morandi import (FONT_STACK, SIZE_LABEL, SIZE_BODY, SIZE_SMALL,
                          WEIGHT_BODY)


def _log(source: str, message: str):
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


class InputBar:
    """单行紧凑输入条组件"""

    def __init__(self, task_manager: TaskManager):
        self.task_manager = task_manager
        self.page = None
        self.file_picker = None  # 由 gui_app 注册的 FilePicker (导入网址用)
        self.on_task_created = None   # 任务创建后回调 callback() (供表格刷新)
        self._pending_urls = []
        self._pending_invalid = []
        # UI 引用
        self.url_input = None
        self.mode_dropdown = None
        self.start_chapter = None
        self.end_chapter = None
        self.speed_dropdown = None
        self.resume_switch = None
        self.output_dir_input = None
        self.stop_btn = None
        self.batch_panel = None
        self.batch_input = None
        self.batch_hint = None
        self.batch_parse_btn = None
        self.batch_confirm_btn = None
        self.batch_cancel_btn = None

    # ------------------------------------------------------------------ UI
    def build(self) -> ft.Control:
        """构建输入条"""
        self.url_input = ft.TextField(
            label="小说目录页URL",
            hint_text="如: https://m.tanmixs.com/YzN6/ml.html",
            expand=True,
            dense=True,
            text_style=ft.TextStyle(size=SIZE_LABEL, font_family=FONT_STACK),
            on_submit=self.on_start_click,  # 回车直接开始
        )

        self.mode_dropdown = ft.Dropdown(
            label="模式",
            width=140, dense=True,
            text_style=ft.TextStyle(size=SIZE_LABEL, font_family=FONT_STACK),
            value="full",
            options=[
                ft.dropdown.Option("full", "完整抓取"),
                ft.dropdown.Option("list", "仅看目录"),
                ft.dropdown.Option("test", "测试首章"),
                ft.dropdown.Option("range", "章节区间"),
            ],
            on_select=self._on_mode_change,
        )

        self.speed_dropdown = ft.Dropdown(
            label="速度",
            width=150, dense=True,
            text_style=ft.TextStyle(size=SIZE_LABEL, font_family=FONT_STACK),
            value="standard",
            options=[
                ft.dropdown.Option("standard", "标准 (1线程)"),
                ft.dropdown.Option("fast", "快速 (3线程)"),
                ft.dropdown.Option("turbo", "极速 (6线程)"),
            ],
        )

        self.start_chapter = ft.TextField(
            label="起始章", width=80, dense=True, visible=False,
            text_style=ft.TextStyle(size=SIZE_LABEL, font_family=FONT_STACK),
            input_filter=ft.NumbersOnlyInputFilter(),
        )
        self.end_chapter = ft.TextField(
            label="结束章", width=80, dense=True, visible=False,
            text_style=ft.TextStyle(size=SIZE_LABEL, font_family=FONT_STACK),
            input_filter=ft.NumbersOnlyInputFilter(),
        )

        start_btn = filled_btn("开始", icon=ft.Icons.PLAY_ARROW,
                               on_click=self.on_start_click,
                               tooltip="按所选模式开始抓取 (URL框内回车也可)")
        self.stop_btn = danger_btn("停止", icon=ft.Icons.STOP,
                                   on_click=self.on_stop_click, disabled=True,
                                   tooltip="停止当前选中任务")

        import_btn = tonal_btn("导入网址", icon=ft.Icons.UPLOAD_FILE,
                              on_click=self.on_import_click,
                              tooltip="从 txt 清单文件导入网址批量抓取")
        paste_btn = tonal_btn("粘贴网址", icon=ft.Icons.CONTENT_PASTE,
                             on_click=self.on_paste_click,
                             tooltip="粘贴多个网址批量抓取")

        self.resume_switch = ft.Switch(
            label="断点续传", value=True,
            label_position=ft.LabelPosition.LEFT,
        )
        self.output_dir_input = ft.TextField(
            label="输出目录", width=170, dense=True,
            text_style=ft.TextStyle(size=SIZE_LABEL, font_family=FONT_STACK),
            value="抓取结果",
        )
        open_folder_btn = outline_btn("文件夹", icon=ft.Icons.FOLDER_OPEN,
                                      on_click=self.on_open_folder_click,
                                      tooltip="打开结果输出文件夹")

        # 批量导入内嵌面板 (粘贴/导入网址确认区, 默认隐藏)
        self.batch_input = ft.TextField(
            multiline=True, min_lines=4, max_lines=10,
            hint_text="每行一个小说目录页URL，# 开头的行为注释",
            text_style=ft.TextStyle(size=SIZE_BODY, font_family=FONT_STACK),
            expand=True,
        )
        self.batch_hint = ft.Text("", size=SIZE_SMALL, weight=WEIGHT_BODY,
                                  color=ft.Colors.ON_SURFACE_VARIANT,
                                  font_family=FONT_STACK)
        self.batch_parse_btn = tonal_btn("解析网址", icon=ft.Icons.FACT_CHECK,
                                         on_click=self._on_batch_parse,
                                         visible=False)
        self.batch_confirm_btn = filled_btn("开始批量抓取",
                                            icon=ft.Icons.PLAYLIST_PLAY,
                                            on_click=lambda e: self._start_batch(self._pending_urls),
                                            visible=False)
        self.batch_cancel_btn = text_btn("取消", on_click=self._hide_batch_panel,
                                         visible=False)
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

        return make_card(
            ft.Column([
                # 第一行: 主操作 (URL 拉伸填充)
                ft.Row([self.url_input, self.mode_dropdown,
                        self.speed_dropdown, start_btn, self.stop_btn],
                       spacing=6),
                # 第二行: 次操作 (自动换行)
                ft.Row([import_btn, paste_btn, self.start_chapter,
                        self.end_chapter, self.resume_switch,
                        self.output_dir_input, open_folder_btn],
                       wrap=True, spacing=6),
                self.batch_panel,
            ], spacing=6),
            padding=10,
        )

    # --------------------------------------------------------------- 回调
    def _on_mode_change(self, e):
        """模式切换时显示/隐藏章节区间输入"""
        is_range = self.mode_dropdown.value == "range"
        self.start_chapter.visible = is_range
        self.end_chapter.visible = is_range
        try:
            e.page.update()
        except Exception:
            pass

    def _notify(self, msg: str):
        """轻提示 (通过日志系统 + 控制台, 无 snackbar 依赖)"""
        _log("GUI", msg)
        try:
            self.page.open(ft.SnackBar(ft.Text(msg, font_family=FONT_STACK)))
        except Exception:
            pass

    # --------------------------------------------------------- 单任务启动
    def on_start_click(self, e):
        """开始抓取 (URL 框内回车或点击按钮均可触发)"""
        url = (self.url_input.value or '').strip()
        if not url:
            self._notify("请输入小说目录页URL")
            return

        mode = self.mode_dropdown.value
        chapter_range = None
        if mode == "range":
            try:
                start = int(self.start_chapter.value)
                end = int(self.end_chapter.value)
                if start > end:
                    self._notify("起始章不能大于结束章")
                    return
                chapter_range = (start, end)
            except (ValueError, TypeError):
                self._notify("请输入有效的章节号")
                return

        speed_map = {"standard": (1, 1.0), "fast": (3, 0.5), "turbo": (6, 0.2)}
        threads, delay = speed_map.get(self.speed_dropdown.value, (1, 1.0))
        output_dir = (self.output_dir_input.value or '').strip() or None

        err = _validate_url(url)
        if err:
            _log("GUI", f"URL 校验失败: {url} 原因: {err}")
            self._notify(f"网址无效: {err}")
            return

        task_id = self.task_manager.create_task(
            url=url, mode=mode, chapter_range=chapter_range,
            threads=threads, delay=delay,
            resume=self.resume_switch.value, output_dir=output_dir,
        )
        self.task_manager.select_task(task_id)
        self.stop_btn.disabled = False
        _log("GUI", f"开始抓取: {url} 模式={mode} 区间={chapter_range} "
                    f"线程={threads} 延迟={delay} 续传={self.resume_switch.value} → {task_id}")
        self._notify(f"任务已创建: {task_id}")
        if self.page is None and getattr(e, 'page', None) is not None:
            self.page = e.page
        if self.on_task_created:
            self.on_task_created()

    def on_stop_click(self, e):
        """停止当前选中任务"""
        tid = self.task_manager.selected_task_id
        if tid:
            self.task_manager.stop_task(tid)
            _log("GUI", f"用户停止任务: {tid}")
            self._notify("任务已停止")

    def on_open_folder_click(self, e):
        """打开结果输出文件夹 (EXE 相对路径契约)"""
        output_dir = (self.output_dir_input.value or '').strip() or None
        abs_dir = resolve_output_dir(output_dir)
        try:
            if os.name == 'nt':
                os.startfile(abs_dir)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', abs_dir])
            else:
                subprocess.Popen(['xdg-open', abs_dir])
        except Exception as ex:
            self._notify(f"无法打开文件夹: {ex}")

    # ----------------------------------------------------------- 批量导入
    async def on_import_click(self, e):
        """导入 txt 清单文件 (每行一个URL, # 注释)"""
        if self.file_picker is None:
            self._notify("文件选择器未就绪")
            return
        try:
            files = await self.file_picker.pick_files(
                allow_multiple=False,
                allowed_extensions=["txt"],
                dialog_title="选择小说网址清单 (每行一个URL, # 开头为注释)",
            )
        except Exception as ex:
            self._notify(f"打开文件选择器失败: {ex}")
            return
        if not files:
            return
        path = files[0].path
        raw = None
        for enc in ('utf-8', 'gbk'):
            try:
                with open(path, encoding=enc) as f:
                    raw = f.read()
                break
            except UnicodeDecodeError:
                continue
            except Exception as ex:
                self._notify(f"读取文件失败: {ex}")
                return
        if raw is None:
            self._notify("读取文件失败: 编码无法识别")
            return
        urls, invalid = self._parse_urls(raw)
        self._show_batch_panel(urls, invalid, source=path)

    def on_paste_click(self, e):
        """粘贴网址: 展开内嵌面板"""
        if self.page is None and getattr(e, 'page', None) is not None:
            self.page = e.page
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
            self.page.update()
        except Exception:
            pass

    def _on_batch_parse(self, e):
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
        """展示解析结果, 用户确认后创建批量任务"""
        if not urls:
            tip = f"未解析到有效网址 (无效 {len(invalid)} 条)"
            if invalid:
                tip += f"，首条原因: {invalid[0][1]}"
            self._notify(tip)
            return
        self._pending_urls = urls
        invalid_tip = f"，{len(invalid)} 条无效已忽略" if invalid else ""
        preview = '\n'.join(f"  {u}" for u in urls[:5])
        if len(urls) > 5:
            preview += f"\n  ... 等 {len(urls)} 条"
        self.batch_hint.value = (f"解析到 {len(urls)} 个有效网址{invalid_tip}，"
                                 f"确认后开始批量抓取:\n{preview}")
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
        """批量创建抓取任务: 每个 URL 一个独立任务"""
        speed_map = {"standard": (1, 1.0), "fast": (3, 0.5), "turbo": (6, 0.2)}
        threads, delay = speed_map.get(self.speed_dropdown.value, (1, 1.0))
        output_dir = (self.output_dir_input.value or '').strip() or None
        resume = self.resume_switch.value

        # 同域并发提示 (仅提示, 不阻断)
        from urllib.parse import urlparse
        running_domains = {}
        for t in self.task_manager.get_all_tasks():
            if t.status in ("running", "pending"):
                d = urlparse(t.url).netloc
                running_domains[d] = running_domains.get(d, 0) + 1
        dup_domains = [d for d, n in running_domains.items() if n >= 2]
        if dup_domains:
            self._notify(
                f"提示: 站点 {dup_domains[0]} 已有 {running_domains[dup_domains[0]]} "
                f"个任务在跑, 同站并发可能触发验证码")

        created = 0
        for url in urls:
            self.task_manager.create_task(
                url=url, mode="full", threads=threads, delay=delay,
                resume=resume, output_dir=output_dir,
            )
            created += 1

        self.stop_btn.disabled = False
        self._hide_batch_panel()
        _log("GUI", f"批量抓取启动: {created} 个网址 (线程={threads} "
                    f"延迟={delay} 续传={resume})\n  网址列表: {urls}")
        self._notify(f"已创建 {created} 个抓取任务 (每本书独立进度)")
        if self.on_task_created:
            self.on_task_created()
