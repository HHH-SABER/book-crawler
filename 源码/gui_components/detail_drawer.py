# -*- coding: utf-8 -*-
"""右侧上下文抽屉：任务详情 / 文件预览 (跟随选中对象切换)

- 收起时宽度 0 (不占主区空间), 展开时 320px
- 任务详情视图: 大进度环 + 指标卡 (引擎/反爬/质检/增量) + 输出文件
- 文件预览视图: 抓取结果目录文件列表 + 内容预览
历史/站点配置已升级为独立页面, 不在本抽屉。
"""
import flet as ft
import os
import sys
import glob

from .task_manager import TaskManager
from .ui_theme import (status_chip, status_color, tonal_btn)
from .ui_morandi import (FONT_STACK, SIZE_LABEL, SIZE_SMALL, SIZE_TINY,
                          WEIGHT_SUBTITLE, WEIGHT_BODY,
                          MORANDI_SECONDARY, MORANDI_SUCCESS, MORANDI_ERROR,
                          MORANDI_WARNING, MORANDI_ACCENT)

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys as _sys; _sys.path.insert(0, _HERE)  # noqa: E402
from _path_utils import get_default_output_dir  # noqa: E402

# 抽屉宽度
_WIDTH_OPEN = 320
_WIDTH_CLOSED = 0


class DetailDrawer:
    """右侧上下文抽屉组件"""

    def __init__(self, task_manager: TaskManager):
        self.task_manager = task_manager
        self.page = None
        self._view = "detail"     # detail / preview
        self._files = []
        self._selected_file = None
        # UI 引用
        self.container = None
        self._detail_view = None
        self._preview_view = None
        self._file_list = None
        self._file_content = None
        self._file_info = None

    # ------------------------------------------------------------------ UI
    def build(self) -> ft.Control:
        """构建抽屉 (默认收起)"""
        # ---- 任务详情视图 ----
        self._detail_view = ft.Column(spacing=8)

        # ---- 文件预览视图 ----
        self._file_list = ft.ListView(expand=True, spacing=2, auto_scroll=True)
        self._file_content = ft.TextField(
            multiline=True, expand=True, read_only=True, dense=True,
            text_style=ft.TextStyle(size=SIZE_SMALL, font_family=FONT_STACK),
            border_color=ft.Colors.OUTLINE_VARIANT,
        )
        self._file_info = ft.Text("选择文件预览", size=SIZE_TINY,
                                  color=ft.Colors.ON_SURFACE_VARIANT,
                                  font_family=FONT_STACK, max_lines=1,
                                  overflow=ft.TextOverflow.ELLIPSIS)
        refresh_btn = tonal_btn("刷新", icon=ft.Icons.REFRESH,
                                on_click=lambda e: self._scan_files())
        self._preview_view = ft.Column([
            ft.Row([
                ft.Icon(ft.Icons.FOLDER_OPEN_OUTLINED, size=16,
                        color=MORANDI_SECONDARY),
                ft.Text("抓取结果", size=SIZE_SMALL, weight=WEIGHT_SUBTITLE,
                        font_family=FONT_STACK),
                ft.Container(expand=True),
                refresh_btn,
            ], spacing=4),
            ft.Container(content=self._file_list, height=180),
            self._file_info,
            ft.Container(content=self._file_content, expand=True),
        ], spacing=6)

        # 抽屉容器 (收起时内容整体隐藏, 只留 0 宽占位; 旧实现内容未隐藏
        # 导致收起后在右缘挤成一列竖排文字)
        self._drawer_body = ft.Column([
            # 标题行: 视图名 + 关闭按钮
            ft.Row([
                self._title_text(),
                ft.Container(expand=True),
                ft.IconButton(
                    icon=ft.Icons.CLOSE, icon_size=16,
                    tooltip="关闭抽屉",
                    on_click=lambda e: self.close(),
                    style=ft.ButtonStyle(
                        padding=4,
                        shape=ft.RoundedRectangleBorder(radius=4)),
                ),
            ], spacing=4),
            ft.Divider(height=1),
            self._detail_view,
            self._preview_view,
        ], spacing=6)
        self._drawer_body.visible = False
        self.container = ft.Container(
            content=self._drawer_body,
            width=_WIDTH_CLOSED,
            padding=ft.Padding.symmetric(horizontal=10, vertical=10),
            bgcolor=ft.Colors.SURFACE,
            animate=ft.Animation(200, "easeOutCubic"),
        )
        self._preview_view.visible = False
        self._detail_view.visible = True
        return self.container

    def _title_text(self) -> ft.Text:
        return ft.Text("任务详情", size=SIZE_SMALL, weight=WEIGHT_SUBTITLE,
                       font_family=FONT_STACK)

    # ------------------------------------------------------------- 开关路由
    def open(self, view: str = "detail", task_id: str = ""):
        """展开抽屉并切换视图 (主线程)

        Args:
            view: "detail" (任务详情, 用选中任务) / "preview" (文件预览)
            task_id: 可选, 指定任务 (默认用当前选中任务)
        """
        if task_id:
            self.task_manager.select_task(task_id)
        self._view = view
        self.container.width = _WIDTH_OPEN
        self.container.border = ft.Border(left=ft.BorderSide(
            1, ft.Colors.OUTLINE_VARIANT))
        if view == "preview":
            self._detail_view.visible = False
            self._preview_view.visible = True
            self._scan_files()
        else:
            self._detail_view.visible = True
            self._preview_view.visible = False
            self.refresh()
        self._drawer_body.visible = True   # 展开时显示内容
        self._update()

    def close(self):
        """收起抽屉"""
        self.container.width = _WIDTH_CLOSED
        self.container.border = None  # 收起时隐藏左边框线
        self._drawer_body.visible = False  # 隐藏内容, 防止挤成竖排文字
        self._update()

    @property
    def is_open(self) -> bool:
        return self.container is not None and self.container.width == _WIDTH_OPEN

    def _update(self):
        try:
            self.page.update()
        except Exception:
            pass

    # ----------------------------------------------------------- 详情刷新
    def refresh(self):
        """刷新任务详情视图 (主线程, 由刷新 Timer 驱动)"""
        if self._detail_view is None or not self._detail_view.visible:
            return
        tid = self.task_manager.selected_task_id
        task = self.task_manager.get_task(tid) if tid else None
        if not task:
            self._detail_view.controls.clear()
            self._detail_view.controls.append(ft.Text(
                "未选中任务 (点击表格行选中)",
                size=SIZE_SMALL, color=ft.Colors.ON_SURFACE_VARIANT,
                font_family=FONT_STACK))
            return

        mt = task.metrics
        # 大进度环
        ring_value = None
        if task.progress_total > 0:
            ring_value = min(1.0, task.progress_current / task.progress_total)
        elif task.status == "completed":
            ring_value = 1.0
        ring = ft.ProgressRing(
            width=56, height=56, stroke_width=6, value=ring_value,
            color=status_color(task.status),
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        )

        self._detail_view.controls.clear()
        self._detail_view.controls.append(ft.Row([
            ring,
            ft.Column([
                ft.Text(task.title, size=SIZE_LABEL, weight=WEIGHT_SUBTITLE,
                        font_family=FONT_STACK, max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS),
                ft.Row([status_chip(task.status),
                        ft.Text(f"{task.progress_current}/{task.progress_total}",
                                size=SIZE_TINY, font_family=FONT_STACK,
                                color=ft.Colors.ON_SURFACE_VARIANT)], spacing=6),
            ], spacing=4, expand=True),
        ], spacing=10))

        # 指标卡 (2×2)
        def _metric_cell(label, value, color=None):
            return ft.Container(
                content=ft.Column([
                    ft.Text(label, size=SIZE_TINY, weight=WEIGHT_BODY,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                            font_family=FONT_STACK),
                    ft.Text(value, size=SIZE_SMALL, weight=WEIGHT_SUBTITLE,
                            color=color or ft.Colors.ON_SURFACE,
                            font_family=FONT_STACK, max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS),
                ], spacing=1),
                padding=ft.Padding.symmetric(horizontal=10, vertical=6),
                bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
                border_radius=8, expand=True,
            )
        self._detail_view.controls.append(ft.Row([
            _metric_cell("引擎", mt.engine or "requests",
                         MORANDI_SUCCESS if mt.engine else None),
            _metric_cell("反爬", mt.anti_spider_type or "无",
                         MORANDI_WARNING if mt.anti_spider_type else None),
        ], spacing=6))
        qs = mt.quality_score
        self._detail_view.controls.append(ft.Row([
            _metric_cell("质检",
                         f"{qs:.0f}分" if qs >= 0 else "—",
                         MORANDI_SUCCESS if mt.quality_passed
                         else MORANDI_ERROR if qs >= 0 else None),
            _metric_cell("增量跳过", f"{mt.incremental_skipped} 章",
                         MORANDI_ACCENT if mt.incremental_skipped else None),
        ], spacing=6))

        # 降级链 (有才显示)
        if mt.engine_fallback_chain:
            chain = " → ".join(mt.engine_fallback_chain + [mt.engine or "…"])
            self._detail_view.controls.append(ft.Text(
                f"降级链: {chain}", size=SIZE_TINY, font_family=FONT_STACK,
                color=ft.Colors.ON_SURFACE_VARIANT))

        # 输出文件 + 操作
        if task.output_file:
            file_row = ft.Row([
                ft.Icon(ft.Icons.DESCRIPTION_OUTLINED, size=14,
                        color=MORANDI_SECONDARY),
                ft.Text(os.path.basename(task.output_file),
                        size=SIZE_TINY, font_family=FONT_STACK,
                        color=ft.Colors.ON_SURFACE_VARIANT, expand=True,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ft.IconButton(
                    icon=ft.Icons.FOLDER_OPEN, icon_size=14,
                    tooltip="打开所在文件夹",
                    on_click=lambda e: self._open_folder(task.output_file),
                    style=ft.ButtonStyle(
                        padding=2, shape=ft.RoundedRectangleBorder(radius=6)),
                ),
            ], spacing=4)
            self._detail_view.controls.append(file_row)
        if task.error:
            self._detail_view.controls.append(ft.Text(
                f"错误: {task.error[:150]}", size=SIZE_TINY,
                font_family=FONT_STACK, color=MORANDI_ERROR))

    def _open_folder(self, filepath: str):
        """打开文件所在目录"""
        try:
            import subprocess
            d = os.path.dirname(os.path.abspath(filepath))
            if os.name == 'nt':
                os.startfile(d)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', d])
            else:
                subprocess.Popen(['xdg-open', d])
        except Exception:
            pass

    # ----------------------------------------------------------- 文件预览
    def _scan_files(self):
        """扫描输出目录 txt 文件 (主线程)"""
        if self._file_list is None:
            return
        self._file_list.controls.clear()
        self._files = []
        output_dir = get_default_output_dir()
        txt_files = glob.glob(os.path.join(output_dir, "*.txt"))
        txt_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
        if not txt_files:
            self._file_list.controls.append(ft.Text(
                "暂无抓取结果", size=SIZE_SMALL, italic=True,
                color=ft.Colors.ON_SURFACE_VARIANT, font_family=FONT_STACK))
            return
        for i, fp in enumerate(txt_files):
            size_kb = os.path.getsize(fp) / 1024
            item = ft.Container(
                content=ft.Column([
                    ft.Text(os.path.basename(fp), size=SIZE_SMALL,
                            weight=WEIGHT_SUBTITLE, font_family=FONT_STACK,
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(f"{size_kb:.1f} KB", size=SIZE_TINY,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                            font_family=FONT_STACK),
                ], spacing=1),
                padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                border_radius=6,
                bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
                ink=True,
                on_click=lambda e, idx=i: self._on_file_selected(idx),
            )
            self._files.append(fp)
            self._file_list.controls.append(item)
        self._update()

    def _on_file_selected(self, idx: int):
        """选中文件 → 预览内容"""
        if not (0 <= idx < len(self._files)):
            return
        fp = self._files[idx]
        self._selected_file = fp
        content = ""
        for enc in ('utf-8', 'gbk', 'gb2312', 'utf-16'):
            try:
                with open(fp, 'r', encoding=enc) as f:
                    content = f.read()
                break
            except Exception:
                continue
        # 抽屉空间有限, 预览前 5 万字符
        if len(content) > 50000:
            content = content[:50000] + "\n\n… (仅预览前 5 万字符)"
        self._file_content.value = content
        size_kb = os.path.getsize(fp) / 1024
        chapter_count = max(content.count('\n第'), content.count('\n## '))
        self._file_info.value = (f"{os.path.basename(fp)} | {size_kb:.1f}KB "
                                 f"| 约{chapter_count}章")
        self._update()
