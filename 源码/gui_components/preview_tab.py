# -*- coding: utf-8 -*-
"""结果预览页签：列出已抓取的TXT文件，选中后预览内容"""
import flet as ft
import os
import glob

# PyInstaller 打包后路径契约
_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys; sys.path.insert(0, _HERE)  # noqa: E402  (保证 import _path_utils)
from _path_utils import get_default_output_dir  # noqa: E402

# UI 主题系统
from .ui_theme import make_card, tonal_btn, danger_btn, BTN_TEXT_STYLE

# 统一字体规范
from .ui_morandi import (FONT_STACK, SIZE_TITLE, SIZE_SUBTITLE, SIZE_LABEL,
                         SIZE_BODY,
                         SIZE_SMALL, SIZE_TINY, WEIGHT_TITLE, WEIGHT_SUBTITLE,
                         WEIGHT_BODY, MORANDI_SECONDARY)  # noqa: E402


class PreviewTab:
    """结果预览页签组件"""

    def __init__(self):
        # - 开发模式 (python gui_app.py)         : 项目根/抓取结果
        # - PyInstaller onefile (小说爬虫.exe)   : EXE 所在目录/抓取结果
        self.output_dir = get_default_output_dir()
        self.page = None
        self.file_list_view = None
        self.content_view = None
        self.file_info_text = None
        self._files = []
        self._selected_idx = None  # 记录选中的文件索引

    def build(self) -> ft.Control:
        """构建结果预览页签的完整UI"""
        # 左侧文件列表
        self.file_list_view = ft.ListView(
            expand=True,
            spacing=4,
            auto_scroll=True,
        )

        refresh_btn = tonal_btn("刷新", icon=ft.Icons.REFRESH,
                                on_click=self.on_refresh_click)
        open_btn = tonal_btn("打开", icon=ft.Icons.OPEN_IN_NEW,
                             on_click=self.on_open_click)
        open_dir_btn = tonal_btn("打开文件夹", icon=ft.Icons.FOLDER_OPEN,
                                 on_click=self.on_open_dir_click,
                                 tooltip="在资源管理器中打开输出目录")
        delete_btn = danger_btn("删除", icon=ft.Icons.DELETE,
                                on_click=self.on_delete_click)

        file_panel = make_card(
            ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.FOLDER_OPEN, size=18, color=MORANDI_SECONDARY),
                    ft.Text("文件列表", size=SIZE_TITLE, weight=WEIGHT_TITLE,
                            font_family=FONT_STACK),
                ]),
                ft.Row([refresh_btn, open_btn, open_dir_btn, delete_btn],
                       wrap=True, spacing=6),
                ft.Container(content=self.file_list_view, expand=True),
            ], spacing=8),
            width=320,
            expand=True,
        )

        # 右侧内容预览
        self.content_view = ft.TextField(
            multiline=True,
            expand=True,
            read_only=True,
            text_style=ft.TextStyle(size=SIZE_BODY, font_family=FONT_STACK),
            border_color=ft.Colors.OUTLINE_VARIANT,
        )

        self.file_info_text = ft.Text("请选择文件", size=SIZE_SMALL,
                                      weight=WEIGHT_BODY,
                                      color=ft.Colors.ON_SURFACE_VARIANT,
                                      font_family=FONT_STACK)

        content_panel = make_card(
            ft.Column([
                self.file_info_text,
                ft.Container(content=self.content_view, expand=True),
            ], spacing=6),
            expand=True,
        )

        # 初始加载文件列表
        self.__scan_and_update_list()

        return ft.Row([file_panel, content_panel], expand=True, spacing=10)

    def __scan_and_update_list(self):
        """扫描输出目录并刷新左侧文件列表（真正的实现，内部用）
        不调用 page.update，只操作控件树 — 调用方负责触发 update"""
        if self.file_list_view is None:
            return
        self.file_list_view.controls.clear()
        self._files = []
        self._selected_idx = None

        if not os.path.exists(self.output_dir):
            self.file_list_view.controls.append(
                ft.Text("输出目录不存在", size=SIZE_BODY, weight=WEIGHT_BODY,
                        color=ft.Colors.ON_SURFACE_VARIANT, italic=True,
                        font_family=FONT_STACK)
            )
            return

        # 扫描 .txt 文件
        txt_files = glob.glob(os.path.join(self.output_dir, "*.txt"))
        txt_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)

        if not txt_files:
            # 空状态：显示图标 + 提示文案
            self.file_list_view.controls.append(
                ft.Container(
                    content=ft.Column([
                        ft.Icon(ft.Icons.FOLDER_OPEN_OUTLINED, size=48,
                                color=ft.Colors.ON_SURFACE_VARIANT, opacity=0.5),
                        ft.Text("暂无抓取结果", size=SIZE_TITLE,
                                color=ft.Colors.ON_SURFACE_VARIANT,
                                weight=WEIGHT_TITLE, font_family=FONT_STACK),
                        ft.Text("抓取完成后，文件将显示在这里", size=SIZE_SMALL,
                                weight=WEIGHT_BODY,
                                color=ft.Colors.ON_SURFACE_VARIANT, opacity=0.7,
                                font_family=FONT_STACK),
                    ], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=ft.Padding.symmetric(vertical=40),
                )
            )
            return

        for i, filepath in enumerate(txt_files):
            filename = os.path.basename(filepath)
            size_kb = os.path.getsize(filepath) / 1024

            item = ft.Container(
                content=ft.Column([
                    ft.Text(filename, size=SIZE_LABEL, weight=WEIGHT_SUBTITLE,
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                            font_family=FONT_STACK),
                    ft.Text(f"{size_kb:.1f} KB", size=SIZE_TINY,
                            weight=WEIGHT_BODY,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                            font_family=FONT_STACK),
                ]),
                padding=ft.Padding.symmetric(horizontal=10, vertical=6),
                border_radius=8,
                bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
                ink=True,
                on_click=lambda e, idx=i: self._on_file_selected(idx),
            )
            self._files.append(filepath)
            self.file_list_view.controls.append(item)

    def _mark_selected_visual(self):
        """把选中的文件在列表中高亮显示"""
        for i, ctrl in enumerate(self.file_list_view.controls):
            if not isinstance(ctrl, ft.Container):
                continue
            if i == self._selected_idx:
                ctrl.bgcolor = ft.Colors.PRIMARY_CONTAINER
            else:
                ctrl.bgcolor = ft.Colors.SURFACE_CONTAINER_LOW

    def _on_file_selected(self, idx: int):
        """选中文件后加载内容到预览区"""
        if idx < 0 or idx >= len(self._files):
            return
        self._selected_idx = idx
        filepath = self._files[idx]
        filename = os.path.basename(filepath)

        try:
            # 尝试多种编码
            content = ""
            for encoding in ['utf-8', 'gbk', 'gb2312', 'utf-16']:
                try:
                    with open(filepath, 'r', encoding=encoding) as f:
                        content = f.read()
                    break
                except (UnicodeDecodeError, Exception):
                    continue

            # 限制预览长度（避免大文件卡顿）
            max_chars = 200000
            if len(content) > max_chars:
                content = content[:max_chars] + f"\n\n… (文件过大，仅显示前{max_chars}字符)"

            self.content_view.value = content

            # 统计信息
            size_kb = os.path.getsize(filepath) / 1024
            char_count = len(content)
            # 估算章节数：以空行+章节标题模式
            chapter_count = max(
                content.count('\n第'),
                content.count('\n## '),
                content.count('\n### '),
            )
            self.file_info_text.value = (
                f"{filename} | {size_kb:.1f} KB | {char_count} 字符 | 约{chapter_count}章"
            )
        except Exception as e:
            self.content_view.value = f"读取失败: {e}"
            self.file_info_text.value = f"{filename} | 读取错误"

        self._mark_selected_visual()

    def on_refresh_click(self, e):
        """刷新文件列表"""
        self.__scan_and_update_list()
        self.content_view.value = ""
        self.file_info_text.value = "请选择文件"
        try:
            e.page.update()
        except Exception:
            pass

    def on_open_click(self, e):
        """用系统默认程序打开 选中的 文件（没选中则打开第一个）"""
        if not self._files:
            return
        idx = self._selected_idx if self._selected_idx is not None else 0
        if idx >= len(self._files):
            return
        filepath = self._files[idx]
        try:
            if os.name == 'nt':
                os.startfile(filepath)
            else:
                import subprocess
                subprocess.Popen(['xdg-open', filepath])
        except Exception as ex:
            self.file_info_text.value = f"打开失败: {ex}"

    def on_open_dir_click(self, e):
        """在资源管理器中打开输出文件夹"""
        try:
            if not os.path.isdir(self.output_dir):
                os.makedirs(self.output_dir, exist_ok=True)
            if os.name == 'nt':
                os.startfile(self.output_dir)
            else:
                import subprocess
                subprocess.Popen(['xdg-open', self.output_dir])
        except Exception as ex:
            self.file_info_text.value = f"打开文件夹失败: {ex}"

    def on_delete_click(self, e):
        """删除选中文件前弹确认对话框（没选中则针对第一个）"""
        if not self._files:
            return
        idx = self._selected_idx if self._selected_idx is not None else 0
        if idx >= len(self._files):
            return
        filepath = self._files[idx]
        filename = os.path.basename(filepath)
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("删除文件", size=SIZE_SUBTITLE, weight=WEIGHT_TITLE,
                          font_family=FONT_STACK),
            content=ft.Text(f"确定删除文件「{filename}」吗？此操作不可恢复。",
                            size=SIZE_BODY, weight=WEIGHT_BODY,
                            font_family=FONT_STACK),
            actions=[
                ft.TextButton(
                    "取消",
                    on_click=lambda ev: self._close_confirm_dialog(),
                    style=ft.ButtonStyle(text_style=BTN_TEXT_STYLE),
                ),
                ft.TextButton(
                    "删除",
                    on_click=lambda ev: self._do_delete_file(filepath, filename),
                    style=ft.ButtonStyle(
                        color=ft.Colors.ERROR,
                        text_style=BTN_TEXT_STYLE,
                    ),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        try:
            # Flet 0.86: 对话框用 show_dialog() 打开
            e.page.show_dialog(dlg)
            self.page = e.page
        except Exception as ex:
            self.file_info_text.value = f"打开对话框失败: {ex}"

    def _close_confirm_dialog(self):
        """关闭确认对话框"""
        try:
            if self.page is not None:
                self.page.pop_dialog()
        except Exception:
            pass

    def _do_delete_file(self, filepath: str, filename: str):
        """确认后执行文件删除"""
        self._close_confirm_dialog()
        try:
            os.remove(filepath)
            self.__scan_and_update_list()
            self.content_view.value = ""
            self.file_info_text.value = f"已删除: {filename}"
        except Exception as ex:
            self.file_info_text.value = f"删除失败: {ex}"
        try:
            if self.page is not None:
                self.page.update()
        except Exception:
            pass

    # 供外部（gui_app tab切换）调用的公开刷新方法
    def _refresh_file_list(self):
        """外部刷新入口：重新扫描输出目录并更新列表控件"""
        self.__scan_and_update_list()
