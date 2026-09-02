# -*- coding: utf-8 -*-
"""全宽任务表格：多列行布局 + 行内展开详情

自绘 Column/Row (不用 ft.DataTable —— 其列宽控制弱且不支持行内展开)。
列: 标题/URL | 进度条 | 状态 | 引擎 | 反爬 | 耗时 | 质检 | 操作(展开/重下/删除)

刷新策略: 签名比对, 数据无变化跳过重建 (防止高频 update 丢点击事件)。
"""
import flet as ft

from .task_manager import TaskManager
from .ui_theme import make_card, status_chip, status_color
from .ui_morandi import (FONT_STACK, SIZE_LABEL, SIZE_SMALL, SIZE_TINY,
                         WEIGHT_TITLE, WEIGHT_SUBTITLE,
                         WEIGHT_BODY, MORANDI_SUCCESS, MORANDI_ERROR,
                         MORANDI_WARNING)
from .row_detail import build_row_detail, _fmt_elapsed

try:
    import 日志 as app_log
except Exception:
    app_log = None


def _log(source: str, message: str):
    if app_log is not None:
        try:
            app_log.info(source, message)
        except Exception:
            pass


class TaskTable:
    """全宽任务表格组件"""

    def __init__(self, task_manager: TaskManager):
        self.task_manager = task_manager
        self.page = None
        self._expanded_id = ""      # 当前展开详情的任务 ID
        self._sig = None            # 行渲染签名 (无变化跳过重建)
        self._list_view = None
        # 操作回调 (可选, 由外部注入)
        self.on_delete_task = None   # callback(task_id)
        self.on_redownload = None   # callback(task_id)
        self.on_open_preview = None  # callback(task_id) 打开抽屉预览

    # ------------------------------------------------------------------ UI
    def build(self) -> ft.Control:
        """构建任务表格"""
        self._list_view = ft.ListView(expand=True, spacing=4, auto_scroll=False)
        header = self._build_header()
        self._refresh()
        return make_card(
            ft.Column([
                header,
                ft.Container(
                    content=self._list_view, expand=True,
                    border=ft.Border(top=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)),
                    padding=ft.Padding(top=4, left=4, right=4, bottom=4),
                ),
            ], spacing=4),
            expand=True, padding=10,
        )

    def _build_header(self) -> ft.Control:
        """表头 (与数据行同列宽比例)"""
        def _h(text, flex, align=ft.MainAxisAlignment.START):
            return ft.Container(
                content=ft.Text(text, size=SIZE_TINY, weight=WEIGHT_SUBTITLE,
                                color=ft.Colors.ON_SURFACE_VARIANT,
                                font_family=FONT_STACK),
                expand=flex if flex else None,
                alignment=ft.Alignment(-1, 0) if align == ft.MainAxisAlignment.START
                else ft.Alignment(0, 0),
            )
        return ft.Row([
            _h("任务 / URL", 42),
            _h("进度", 12),
            _h("状态", 8, ft.MainAxisAlignment.CENTER),
            _h("引擎", 8),
            _h("反爬", 9),
            _h("耗时", 6),
            _h("质检", 7),
            _h("", 12, ft.MainAxisAlignment.CENTER),
        ], spacing=6)

    # ------------------------------------------------------------- 刷新 (主线程)
    def _refresh(self):
        """重建表格内容 (须在主线程调用; 由刷新 Timer 驱动)"""
        if self._list_view is None:
            return
        tasks = self.task_manager.get_all_tasks()
        sig = tuple(
            (t.task_id, t.status, t.progress_current, t.progress_total,
             t.title, t.url, t.selected, t.metrics.engine,
             t.metrics.anti_spider_type, round(t.metrics.quality_score),
             t.metrics.quality_passed, t.metrics.incremental_skipped,
             t.output_file, bool(t.error),
             t.task_id == self._expanded_id)
            for t in tasks
        )
        if sig == self._sig:
            return  # 无变化: 保留控件树
        self._sig = sig

        self._list_view.controls.clear()
        if not tasks:
            self._list_view.controls.append(
                ft.Container(
                    content=ft.Column([
                        ft.Icon(ft.Icons.LIBRARY_BOOKS_OUTLINED, size=44,
                                color=ft.Colors.ON_SURFACE_VARIANT, opacity=0.5),
                        ft.Text("暂无任务", size=SIZE_LABEL,
                                color=ft.Colors.ON_SURFACE_VARIANT,
                                weight=WEIGHT_TITLE, font_family=FONT_STACK),
                        ft.Text("在上方输入网址后点击「开始」创建任务",
                                size=SIZE_SMALL, weight=WEIGHT_BODY,
                                color=ft.Colors.ON_SURFACE_VARIANT, opacity=0.7,
                                font_family=FONT_STACK),
                    ], spacing=8,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=ft.Padding.symmetric(vertical=48),
                )
            )
            return

        for task in tasks:
            self._list_view.controls.append(self._build_row(task))

    def _build_row(self, task) -> ft.Control:
        """单行: 主行 + 可展开详情"""
        is_expanded = (task.task_id == self._expanded_id)
        is_selected = task.selected

        # ---- 单元格工厂 ----
        def _cell(content, flex=None, center=False):
            return ft.Container(
                content=content,
                expand=flex, alignment=ft.Alignment(0, 0) if center
                else ft.Alignment(-1, 0),
            )

        # 标题+URL 单元格
        title_text = ft.Text(task.title[:24] + ("…" if len(task.title) > 24 else task.title),
                             size=SIZE_SMALL, weight=WEIGHT_SUBTITLE,
                             max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                             font_family=FONT_STACK,
                             color=ft.Colors.PRIMARY if is_selected else None)
        url_text = ft.Text(task.url, size=SIZE_TINY, weight=WEIGHT_BODY,
                           color=ft.Colors.ON_SURFACE_VARIANT, opacity=0.7,
                           max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                           font_family=FONT_STACK)
        title_cell = _cell(ft.Column([title_text, url_text],
                                     spacing=1, tight=True), flex=42)

        # 进度单元格 (迷你条 + 数值)
        if task.progress_total > 0:
            ratio = min(1.0, task.progress_current / task.progress_total)
            pct_text = f"{task.progress_current}/{task.progress_total}"
        elif task.status == "completed":
            ratio, pct_text = 1.0, "完成"
        else:
            ratio, pct_text = 0.0, "—"
        ring = ft.ProgressRing(
            width=16, height=16, stroke_width=2.5,
            value=(ratio if task.progress_total or task.status == "completed"
                   else None),
            color=status_color(task.status),
        )
        progress_cell = _cell(ft.Row([ring, ft.Text(pct_text, size=SIZE_TINY,
                                                   font_family=FONT_STACK,
                                                   color=ft.Colors.ON_SURFACE_VARIANT)],
                                    spacing=4), flex=12)

        # 状态单元格
        status_cell = _cell(status_chip(task.status), flex=8, center=True)

        # 引擎单元格
        engine = task.metrics.engine or "—"
        engine_cell = _cell(ft.Text(engine, size=SIZE_TINY, weight=WEIGHT_BODY,
                                    font_family=FONT_STACK,
                                    color=(MORANDI_SUCCESS if task.metrics.engine
                                           else ft.Colors.ON_SURFACE_VARIANT),
                                    max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS), flex=8)

        # 反爬单元格 (命中显示标签色, 未命中灰)
        anti = task.metrics.anti_spider_type
        anti_cell = _cell(ft.Text(anti or "—", size=SIZE_TINY, weight=WEIGHT_BODY,
                                  font_family=FONT_STACK,
                                  color=(MORANDI_WARNING if anti
                                         else ft.Colors.ON_SURFACE_VARIANT),
                                  max_lines=1,
                                  overflow=ft.TextOverflow.ELLIPSIS), flex=9)

        # 耗时单元格
        elapsed_cell = _cell(ft.Text(_fmt_elapsed(task), size=SIZE_TINY,
                                     font_family=FONT_STACK,
                                     color=ft.Colors.ON_SURFACE_VARIANT), flex=6)

        # 质检单元格
        qs = task.metrics.quality_score
        if qs >= 0:
            q_text = f"{qs:.0f}分"
            q_color = MORANDI_SUCCESS if task.metrics.quality_passed else MORANDI_ERROR
        else:
            q_text, q_color = "—", ft.Colors.ON_SURFACE_VARIANT
        quality_cell = _cell(ft.Text(q_text, size=SIZE_TINY, weight=WEIGHT_BODY,
                                     font_family=FONT_STACK, color=q_color), flex=7)

        # 操作单元格: 展开 / 预览 / 重下 / 删除
        expand_btn = ft.IconButton(
            icon=(ft.Icons.EXPAND_LESS if is_expanded else ft.Icons.EXPAND_MORE),
            icon_size=14, tooltip="展开/收起详情",
            on_click=lambda e, tid=task.task_id: self._toggle_expand(tid),
            style=ft.ButtonStyle(
                padding=2, shape=ft.RoundedRectangleBorder(radius=6),
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
            ),
        )
        preview_btn = ft.IconButton(
            icon=ft.Icons.ARTICLE_OUTLINED, icon_size=14,
            tooltip="预览抽屉 (任务详情/输出文件)",
            on_click=lambda e, tid=task.task_id: self._on_open_preview(tid),
            style=ft.ButtonStyle(
                padding=2, shape=ft.RoundedRectangleBorder(radius=6),
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
            ),
        )
        redl_btn = ft.IconButton(
            icon=ft.Icons.REPLAY, icon_size=14,
            tooltip="重新下载 (从头重新抓取)",
            on_click=lambda e, tid=task.task_id: self._on_redownload(tid),
            style=ft.ButtonStyle(
                padding=2, shape=ft.RoundedRectangleBorder(radius=6),
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
            ),
        )
        del_btn = ft.IconButton(
            icon=ft.Icons.DELETE_OUTLINE, icon_size=14,
            tooltip="删除任务",
            on_click=lambda e, tid=task.task_id: self._on_delete(tid),
            style=ft.ButtonStyle(
                padding=2, shape=ft.RoundedRectangleBorder(radius=6),
                bgcolor=ft.Colors.ERROR_CONTAINER,
                color=ft.Colors.ON_ERROR_CONTAINER,
            ),
        )
        ops_cell = _cell(ft.Row([expand_btn, preview_btn, redl_btn, del_btn],
                                spacing=2,
                                alignment=ft.MainAxisAlignment.CENTER),
                         flex=12, center=True)

        # 主行
        main_row = ft.Row([
            title_cell, progress_cell, status_cell, engine_cell,
            anti_cell, elapsed_cell, quality_cell, ops_cell,
        ], spacing=6)

        # 行容器 (选中态高亮)
        body_controls = [main_row]
        if is_expanded:
            body_controls.append(build_row_detail(task))
        row = ft.Container(
            content=ft.Column(body_controls, spacing=2, tight=True),
            padding=ft.Padding.symmetric(horizontal=8, vertical=5),
            border_radius=8,
            bgcolor=(ft.Colors.PRIMARY_CONTAINER if is_selected
                     else ft.Colors.SURFACE_CONTAINER_LOW),
            border=(ft.Border(left=ft.BorderSide(3, ft.Colors.PRIMARY),
                             right=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT),
                             top=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT),
                             bottom=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT))
                    if is_selected
                    else ft.Border.all(1, ft.Colors.OUTLINE_VARIANT)),
            ink=True,
            on_click=lambda e, tid=task.task_id: self._on_row_click(tid),
        )
        return row

    # -------------------------------------------------------------- 交互
    def _on_row_click(self, task_id: str):
        """行点击 → 选中任务 (联动日志条/抽屉)"""
        self.task_manager.select_task(task_id)
        self.refresh()

    def _toggle_expand(self, task_id: str):
        """展开/收起行内详情"""
        self._expanded_id = ("" if self._expanded_id == task_id else task_id)
        self.refresh()

    def _on_open_preview(self, task_id: str):
        """预览按钮 → 打开抽屉 (外部注入 on_open_preview)"""
        if self.on_open_preview:
            self.on_open_preview(task_id)

    def _on_redownload(self, task_id: str):
        """重新下载 (外部注入逻辑或默认调 restart)"""
        if self.on_redownload:
            self.on_redownload(task_id)
            return
        task = self.task_manager.get_task(task_id)
        if not task:
            return
        if task.status == "running":
            self._notify("任务运行中，请先停止再重新下载")
            return
        if self.task_manager.restart_task(task_id):
            self.task_manager.select_task(task_id)
            _log("GUI", f"重新下载 (原任务重启): {task_id} ({task.url})")
            self.refresh()

    def _on_delete(self, task_id: str):
        """删除任务 (优先走外部注入的对话框流程)"""
        if self.on_delete_task:
            self.on_delete_task(task_id)
            return
        if self.task_manager.delete_task(task_id):
            if self._expanded_id == task_id:
                self._expanded_id = ""
            self._sig = None
            self.refresh()

    def _notify(self, msg: str):
        try:
            self.page.open(ft.SnackBar(ft.Text(msg, font_family=FONT_STACK)))
        except Exception:
            pass

    # 对外刷新入口 (主线程)
    def refresh(self):
        self._refresh()
        if self.page is not None:
            try:
                self.page.update()
            except Exception:
                pass
