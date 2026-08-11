# -*- coding: utf-8 -*-
"""结果预览页签：列出已抓取的TXT文件，选中后预览内容"""
import flet as ft
import os
import glob


class PreviewTab:
    """结果预览页签组件"""

    def __init__(self):
        # 输出目录：项目根/抓取结果/
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.output_dir = os.path.normpath(os.path.join(script_dir, "..", "抓取结果"))
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
            spacing=2,
            auto_scroll=True,
        )

        refresh_btn = ft.ElevatedButton(
            "刷新",
            icon=ft.icons.REFRESH,
            on_click=self.on_refresh_click,
            text_size=12,
        )
        open_btn = ft.ElevatedButton(
            "打开",
            icon=ft.icons.OPEN_IN_NEW,
            on_click=self.on_open_click,
            text_size=12,
        )
        delete_btn = ft.ElevatedButton(
            "删除",
            icon=ft.icons.DELETE,
            on_click=self.on_delete_click,
            text_size=12,
            style=ft.ButtonStyle(bgcolor=ft.colors.RED_100),
        )

        file_panel = ft.Container(
            content=ft.Column([
                ft.Row([ft.Text("文件列表", size=14, weight=ft.FontWeight.BOLD),
                        refresh_btn, open_btn, delete_btn], wrap=True),
                ft.Container(content=self.file_list_view, expand=True),
            ]),
            width=300,
            padding=10,
            bgcolor=ft.colors.GREY_50,
            border=ft.border.all(1, ft.colors.GREY_300),
            border_radius=5,
            expand=True,
        )

        # 右侧内容预览
        self.content_view = ft.TextField(
            multiline=True,
            expand=True,
            read_only=True,
            text_size=12,
            border_color=ft.colors.GREY_300,
        )

        self.file_info_text = ft.Text("请选择文件", size=12, color=ft.colors.GREY_600)

        content_panel = ft.Container(
            content=ft.Column([
                self.file_info_text,
                ft.Container(content=self.content_view, expand=True),
            ]),
            expand=True,
            padding=10,
            bgcolor=ft.colors.GREY_50,
            border=ft.border.all(1, ft.colors.GREY_300),
            border_radius=5,
        )

        # 初始加载文件列表
        self.__scan_and_update_list()

        return ft.Row([file_panel, content_panel], expand=True)

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
                ft.Text("输出目录不存在", size=12, color=ft.colors.GREY_500, italic=True)
            )
            return

        # 扫描 .txt 文件
        txt_files = glob.glob(os.path.join(self.output_dir, "*.txt"))
        txt_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)

        if not txt_files:
            self.file_list_view.controls.append(
                ft.Text("暂无抓取结果", size=12, color=ft.colors.GREY_500, italic=True)
            )
            return

        for i, filepath in enumerate(txt_files):
            filename = os.path.basename(filepath)
            size_kb = os.path.getsize(filepath) / 1024

            item = ft.Container(
                content=ft.Column([
                    ft.Text(filename, size=11, weight=ft.FontWeight.BOLD,
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(f"{size_kb:.1f} KB", size=10, color=ft.colors.GREY_600),
                ]),
                padding=5,
                border_radius=3,
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
                ctrl.border = ft.border.all(2, ft.colors.BLUE)
            else:
                ctrl.border = None

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

    def on_delete_click(self, e):
        """删除 选中的 文件（没选中则删除第一个）"""
        if not self._files:
            return
        idx = self._selected_idx if self._selected_idx is not None else 0
        if idx >= len(self._files):
            return
        filepath = self._files[idx]
        filename = os.path.basename(filepath)
        try:
            os.remove(filepath)
            self.__scan_and_update_list()
            self.content_view.value = ""
            self.file_info_text.value = f"已删除: {filename}"
            try:
                e.page.update()
            except Exception:
                pass
        except Exception as ex:
            self.file_info_text.value = f"删除失败: {ex}"

    # 供外部（gui_app tab切换）调用的公开刷新方法
    def _refresh_file_list(self):
        """外部刷新入口：重新扫描输出目录并更新列表控件"""
        self.__scan_and_update_list()
