# -*- coding: utf-8 -*-
"""全宽任务表格：多列行布局 + 行内展开详情

自绘 Column/Row (不用 ft.DataTable —— 其列宽控制弱且不支持行内展开)。
列: 标题/URL | 进度条 | 状态 | 引擎 | 反爬 | 耗时 | 质检 | 操作(展开/预览/重下/删除)

刷新策略: 签名比对, 数据无变化跳过重建 (防止高频 update 丢点击事件)。
"""
import flet as ft
import os
import time

from .task_manager import TaskManager
from .ui_theme import make_card, status_chip, status_color
from .ui_fluent import (FONT_STACK, SIZE_LABEL, SIZE_SMALL, SIZE_TINY,
                         WEIGHT_TITLE, WEIGHT_SUBTITLE,
                         WEIGHT_BODY, MORANDI_SUCCESS, MORANDI_ERROR,
                         MORANDI_WARNING, MORANDI_ON_SURFACE,
                         open_dialog, close_dialog)
from .row_detail import build_row_detail, _fmt_elapsed

try:
    import 日志 as app_log
except Exception:
    app_log = None


# ---------------------------------------------------------------- 列定义
# 表头与数据行共用同一份列宽 (单一定义源, 保证表头与行严格对齐):
#   - 全列固定像素宽 + 表格横向滚动 (2026-09-29 二轮反馈"任务列显示不全"):
#     固定列合计 816px 超出窄窗口可视宽度时, 表头+行整体左右滚动,
#     操作按钮不再被裁; 拖拽调列宽 Flet 0.86 无现成 API, 横向滚动为务实解
_COLUMNS = [
    # (表头文字, 宽度px, 是否居中) — 无 expand 列 (横向滚动容器内 expand 会报错)
    ("任务 / URL", 200, False),
    ("进度", 100, False),
    ("状态", 72, True),
    ("引擎", 84, False),
    ("反爬", 84, False),
    ("耗时", 56, False),
    ("质检", 56, False),
    # 164px: 5 按钮 (展开/预览/EPUB/重下/删除) × 36 + 间距 4×2 = 188 → 200 留余量
    ("操作", 200, True),
]
_TITLE_COL = 0        # 标题列下标 (现亦为固定宽)
_OPS_COL = 7          # 操作列下标


def _log(source: str, message: str):
    if app_log is not None:
        try:
            app_log.info(source, message)
        except Exception:
            pass  # 刻意静默: try 块本身在写日志, 再加日志会递归 (日志链路兜底)
try:
    import 日志 as _app_log          # 批2B: 统一留痕通道 (容错导入, 同 input_bar 桥模式)
except Exception:
    _app_log = None


def _dbg(source: str, message: str):
    """裸 except 吞异常留痕 (DEBUG 级: 只落盘不 console 镜像, 避免刷屏)"""
    if _app_log is not None:
        try:
            _app_log.debug(source, message)
        except Exception:
            pass  # 刻意静默: try 块本身在写日志, 再加日志会递归 (日志链路兜底)



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
        # 常显滚动条 (scroll=ALWAYS, 2026-09-29): 默认悬浮式仅滚动瞬间可见,
        # 任务多时用户看不到滚动条以为"不能滚"
        self._list_view = ft.ListView(expand=True, spacing=4, auto_scroll=False,
                                      scroll=ft.ScrollMode.ALWAYS)
        # 卡片头: "任务列表" + 动态任务计数 (设计稿 card-header)
        self._count_text = ft.Text("共 0 个任务", size=SIZE_TINY,
                                   weight=WEIGHT_BODY,
                                   color=ft.Colors.ON_SURFACE_VARIANT,
                                   font_family=FONT_STACK)
        card_header = ft.Row([
            ft.Text("任务列表", size=SIZE_SMALL, weight=WEIGHT_SUBTITLE,
                    color=ft.Colors.ON_SURFACE, font_family=FONT_STACK),
            ft.Container(expand=True),
            self._count_text,
            # 清空历史 (2026-09-29 任务历史持久化配套): 一键清终态任务记录,
            # 确认框 + 不动输出文件 (历史已落 任务历史.json, 清空即从存档移除)
            ft.TextButton("清空历史", icon=ft.Icons.CLEANING_SERVICES_OUTLINED,
                          tooltip="清空所有已结束任务的记录 (不删除输出文件)",
                          on_click=self._on_clear_history),
        ])
        header = self._build_header()
        self._refresh()
        # 横向滚动容器 (2026-09-29 二轮反馈"任务列显示不全"): 全列固定宽后,
        # 窄窗口 (侧栏+抽屉挤占) 时表格整体左右滚动, 操作按钮不再被裁;
        # vertical_alignment=STRETCH 把卡片高度传给内层 Column → ListView 有界可滚
        # 横滚主轴不约束宽度；ListView 必须取得有限横轴宽度才可布局。
        表宽 = sum(c[1] for c in _COLUMNS) + 6 * (len(_COLUMNS) - 1) + 16
        表格体 = ft.Column([header, self._list_view], spacing=4, width=表宽)
        横滚 = ft.Row([表格体], spacing=0, scroll=ft.ScrollMode.AUTO,
                      vertical_alignment=ft.CrossAxisAlignment.STRETCH)
        return make_card(
            ft.Column([
                card_header,
                ft.Container(
                    content=横滚, expand=True,
                    border=ft.Border(top=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)),
                    padding=ft.Padding(top=4, left=4, right=4, bottom=4),
                ),
            ], spacing=4),
            expand=True, padding=10,
        )

    def _build_header(self) -> ft.Control:
        """表头 (与数据行共用 _COLUMNS 列宽, 严格对齐)"""
        def _h(label, width, center):
            return ft.Container(
                content=ft.Text(label, size=SIZE_TINY, weight=WEIGHT_SUBTITLE,
                                color=ft.Colors.ON_SURFACE_VARIANT,
                                font_family=FONT_STACK),
                expand=(width is None),
                width=width,
                alignment=ft.Alignment(0, 0) if center else ft.Alignment(-1, 0),
            )
        return ft.Row(
            [_h(label, width, center) for label, width, center in _COLUMNS],
            spacing=6)

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
             t.task_id == self._expanded_id,
             # 死书标记(死书机制 阶段2): 状态与 status 同步变, 但阶段3 行内
             # 按钮要按 dead 分流(重试/忽略/删记录), 缺这项则按钮不刷新
             bool(getattr(t, "dead", None)),
             # M6 修复: 运行中任务的耗时按 5 秒桶纳入签名, 否则进度停滞时
             # 耗时列冻结、跳变
             (int((time.time() - t.metrics.start_time) // 5)
              if (t.status == "running" and t.metrics.start_time) else 0))
            for t in tasks
        )
        if sig == self._sig:
            return  # 无变化: 保留控件树
        self._sig = sig

        # 同步任务计数 (设计稿: 卡片头右侧 "共 N 个任务")
        try:
            self._count_text.value = f"共 {len(tasks)} 个任务"
        except Exception:
            pass  # 刻意静默: 高频路径(_refresh(), 逐行/每秒级), 补日志会刷屏

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

        # ---- 单元格工厂 (与表头共用 _COLUMNS 列宽) ----
        def _cell(content, width=None, center=False):
            return ft.Container(
                content=content,
                width=width,
                expand=(width is None),
                alignment=ft.Alignment(0, 0) if center
                else ft.Alignment(-1, 0),
            )
        _w = lambda idx: _COLUMNS[idx][1]

        # 标题+URL 单元格
        title_text = ft.Text((task.title[:24] + "…") if len(task.title) > 24 else task.title,
                             size=SIZE_SMALL, weight=WEIGHT_SUBTITLE,
                             max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                             font_family=FONT_STACK,
                             color=ft.Colors.PRIMARY if is_selected else None)
        url_text = ft.Text(task.url, size=SIZE_TINY, weight=WEIGHT_BODY,
                           color=ft.Colors.ON_SURFACE_VARIANT, opacity=0.7,
                           max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                           font_family=FONT_STACK)
        title_cell = _cell(ft.Column([title_text, url_text],
                                     spacing=1, tight=True), width=_w(0))

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
            value=(ratio if task.progress_total or task.status != "running"
                   else None),
            color=status_color(task.status),
        )
        progress_cell = _cell(ft.Row([ring, ft.Text(pct_text, size=SIZE_TINY,
                                                   font_family=FONT_STACK,
                                                   color=ft.Colors.ON_SURFACE_VARIANT)],
                                    spacing=4), width=_w(1))

        # 状态单元格
        status_cell = _cell(status_chip(task.status), width=_w(2), center=True)

        # 引擎单元格
        engine = task.metrics.engine or "—"
        engine_cell = _cell(ft.Text(engine, size=SIZE_TINY, weight=WEIGHT_BODY,
                                    font_family=FONT_STACK,
                                    color=(MORANDI_SUCCESS if task.metrics.engine
                                           else ft.Colors.ON_SURFACE_VARIANT),
                                    max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS), width=_w(3))

        # 反爬单元格 (命中显示标签色, 未命中灰)
        anti = task.metrics.anti_spider_type
        anti_cell = _cell(ft.Text(anti or "—", size=SIZE_TINY, weight=WEIGHT_BODY,
                                  font_family=FONT_STACK,
                                  color=(MORANDI_WARNING if anti
                                         else ft.Colors.ON_SURFACE_VARIANT),
                                  max_lines=1,
                                  overflow=ft.TextOverflow.ELLIPSIS), width=_w(4))

        # 耗时单元格
        elapsed_cell = _cell(ft.Text(_fmt_elapsed(task), size=SIZE_TINY,
                                     font_family=FONT_STACK,
                                     color=ft.Colors.ON_SURFACE_VARIANT), width=_w(5))

        # 质检单元格
        qs = task.metrics.quality_score
        if qs >= 0:
            q_text = f"{qs:.0f}分"
            q_color = MORANDI_SUCCESS if task.metrics.quality_passed else MORANDI_ERROR
        else:
            q_text, q_color = "—", ft.Colors.ON_SURFACE_VARIANT
        quality_cell = _cell(ft.Text(q_text, size=SIZE_TINY, weight=WEIGHT_BODY,
                                     font_family=FONT_STACK, color=q_color), width=_w(6))

        # 操作单元格: 展开 / 预览 / 重下 / 删除
        expand_btn = ft.IconButton(
            icon=(ft.Icons.EXPAND_LESS if is_expanded else ft.Icons.EXPAND_MORE),
            icon_size=14, tooltip="展开/收起详情",
            on_click=lambda e, tid=task.task_id: self._toggle_expand(tid),
            width=36, height=32,
            style=ft.ButtonStyle(
                padding=2, shape=ft.RoundedRectangleBorder(radius=6),
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
            ),
        )
        preview_btn = ft.IconButton(
            icon=ft.Icons.ARTICLE_OUTLINED, icon_size=14,
            tooltip="预览抽屉 (任务详情/输出文件)",
            on_click=lambda e, tid=task.task_id: self._on_open_preview(tid),
            width=36, height=32,
            style=ft.ButtonStyle(
                padding=2, shape=ft.RoundedRectangleBorder(radius=6),
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
            ),
        )
        # 导出 EPUB (2026-09-29): 单本手动导出, 走 epub_exporter 同一转换链。
        # 已完成且有输出文件时高亮可点; 无输出/运行中置灰 (tooltip 说明原因)
        _可导 = bool(task.output_file) and task.status != "running"
        epub_btn = ft.IconButton(
            icon=ft.Icons.MENU_BOOK_OUTLINED, icon_size=14,
            tooltip=("导出 EPUB (单本导出)" if _可导
                     else ("请等待抓取完成" if task.status == "running"
                           else "无输出文件, 无法导出")),
            disabled=not _可导,
            on_click=lambda e, tid=task.task_id: self._on_export_epub(tid),
            width=36, height=32,
            style=ft.ButtonStyle(
                padding=2, shape=ft.RoundedRectangleBorder(radius=6),
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
            ),
        )
        redl_btn = ft.IconButton(
            icon=ft.Icons.REPLAY, icon_size=14,
            tooltip="重新下载 (从头重新抓取)",
            on_click=lambda e, tid=task.task_id: self._on_redownload(tid),
            width=36, height=32,
            style=ft.ButtonStyle(
                padding=2, shape=ft.RoundedRectangleBorder(radius=6),
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
            ),
        )
        del_btn = ft.IconButton(
            icon=ft.Icons.DELETE_OUTLINE, icon_size=14,
            tooltip="删除任务",
            on_click=lambda e, tid=task.task_id: self._on_delete(tid),
            width=36, height=32,
            style=ft.ButtonStyle(
                padding=2, shape=ft.RoundedRectangleBorder(radius=6),
                bgcolor=ft.Colors.ERROR_CONTAINER,
                color=ft.Colors.ON_ERROR_CONTAINER,
            ),
        )
        ops_cell = _cell(ft.Row([expand_btn, preview_btn, epub_btn, redl_btn, del_btn],
                                spacing=2,
                                alignment=ft.MainAxisAlignment.CENTER),
                         width=_w(7), center=True)

        # 主行
        main_row = ft.Row([
            title_cell, progress_cell, status_cell, engine_cell,
            anti_cell, elapsed_cell, quality_cell, ops_cell,
        ], spacing=6, wrap=False, alignment=ft.MainAxisAlignment.START,
        vertical_alignment=ft.CrossAxisAlignment.CENTER)

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
        else:
            self._notify("任务正在收尾，请稍后重新下载")

    def _on_export_epub(self, task_id: str):
        """导出 EPUB (2026-09-29 单本手动导出): 走 epub_exporter 同一转换链

        失败与自动导出 (静默返回 None) 不同 —— 手动触发必须有明确反馈,
        故 导出单篇() 抛异常, 此处捕获后 SnackBar 提示原因。
        """
        task = self.task_manager.get_task(task_id)
        if not task:
            return
        if not task.output_file:
            self._notify("该任务没有输出文件, 无法导出 EPUB")
            return
        if task.status == "running":
            self._notify("任务仍在运行, 请等待抓取完成后再导出")
            return
        try:
            from epub_exporter import 导出单篇
            epub_path = 导出单篇(task.output_file, title=task.title)
            _log("GUI", f"EPUB 已导出 (单本): {epub_path}")
            self._notify(f"✅ EPUB 已导出: {os.path.basename(epub_path)}")
        except Exception as _e:
            _log("GUI", f"EPUB 导出失败: {type(_e).__name__}: {_e}")
            self._notify(f"❌ EPUB 导出失败: {_e}")

    def _on_delete(self, task_id: str):
        """删除任务: 有本地输出文件时弹确认框, 可选同时删除文件"""
        if self.on_delete_task:
            self.on_delete_task(task_id)
            return
        task = self.task_manager.get_task(task_id)
        if not task:
            return
        # 无本地文件或页面不可用: 直接删除任务
        if not task.output_file or self.page is None:
            self._do_delete(task_id, False)
            return
        # 有输出文件: 确认框 (仅删任务 / 同时删文件 / 取消)
        fname = os.path.basename(task.output_file)
        dialog = ft.AlertDialog(
            modal=True,
            # G-H1 (GUI 专项审查): 打包 EXE 中 dialog 文字缺显式 color 会渲染成
            # 不可见 (v2.4.19 教训, 关闭弹窗已修, 此处同类漏网) —— 这是
            # "是否同时删除本地文件"的确认框, 文字不可见会放大误删风险
            title=ft.Text("删除任务", color=MORANDI_ON_SURFACE,
                          font_family=FONT_STACK),
            content=ft.Text(f"任务输出文件:\n{fname}\n\n是否同时删除本地文件?",
                            size=SIZE_SMALL, font_family=FONT_STACK,
                            color=MORANDI_ON_SURFACE),
            actions=[
                ft.TextButton("取消",
                              on_click=lambda _: close_dialog(self.page, dialog)),
                ft.TextButton("仅删任务",
                              on_click=lambda _: self._confirm_delete(dialog, task_id, False)),
                ft.TextButton("同时删文件",
                              on_click=lambda _: self._confirm_delete(dialog, task_id, True)),
            ],
        )
        open_dialog(self.page, dialog)

    def _confirm_delete(self, dialog, task_id: str, delete_file: bool):
        """确认框回调: 关闭对话框后执行删除"""
        try:
            close_dialog(self.page, dialog)
        except Exception as _e:
            _dbg("任务表", f'裸 except 吞异常: {type(_e).__name__}: {_e}')
        self._do_delete(task_id, delete_file)

    def _do_delete(self, task_id: str, delete_file: bool):
        """真正执行删除任务 (delete_file=True 时连同输出文件删除)"""
        if self.task_manager.delete_task(task_id, delete_file=delete_file):
            if self._expanded_id == task_id:
                self._expanded_id = ""
            self._sig = None
            self.refresh()
        else:
            self._notify("任务正在收尾，文件仍在写入；停止后请稍后重试")

    def _notify(self, msg: str):
        try:
            open_dialog(self.page, ft.SnackBar(ft.Text(msg, font_family=FONT_STACK)))
        except Exception as _e:
            _dbg("任务表", f'裸 except 吞异常: {type(_e).__name__}: {_e}')

    # ------------------------------------------------------- 清空历史
    def _on_clear_history(self, e=None):
        """清空历史: 批量删除终态任务记录 (不动输出文件), 弹确认框。

        运行中/排队中的任务不会被清 (仅 completed/failed/stopped/interrupted/dead_pending)。
        文字显式 color 是 G-H1 教训 (EXE 中 dialog 无色文字不可见)。
        """
        try:
            终态 = [t.task_id for t in self.task_manager.get_all_tasks()
                    if t.status in ("completed", "failed", "stopped", "interrupted",
                                    "dead_pending")]
        except Exception as _e:
            _dbg("任务表", f'清空历史取任务列表失败: {type(_e).__name__}: {_e}')
            return
        if not 终态:
            self._notify("没有可清空的任务 (均为运行中/排队中)")
            return
        if self.page is None:
            self._do_clear_history(终态)
            return
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("清空历史", color=MORANDI_ON_SURFACE,
                          font_family=FONT_STACK),
            content=ft.Text(f"确定清空 {len(终态)} 条已结束任务的记录?\n"
                            "不会删除输出文件 (.txt/.epub)。",
                            size=SIZE_SMALL, font_family=FONT_STACK,
                            color=MORANDI_ON_SURFACE),
            actions=[
                ft.TextButton("取消",
                              on_click=lambda _: close_dialog(self.page, dialog)),
                ft.TextButton("清空",
                              on_click=lambda _: self._confirm_clear_history(dialog, 终态)),
            ],
        )
        open_dialog(self.page, dialog)

    def _confirm_clear_history(self, dialog, 任务ids):
        try:
            close_dialog(self.page, dialog)
        except Exception as _e:
            _dbg("任务表", f'裸 except 吞异常: {type(_e).__name__}: {_e}')
        self._do_clear_history(任务ids)

    def _do_clear_history(self, 任务ids):
        成功 = 0
        for tid in 任务ids:
            try:
                if self.task_manager.delete_task(tid, delete_file=False):
                    成功 += 1
            except Exception as _e:
                _dbg("任务表", f'清空历史删除 {tid} 失败: {type(_e).__name__}: {_e}')
        if self._expanded_id in 任务ids:
            self._expanded_id = ""
        self._sig = None
        self.refresh()
        self._notify(f"已清空 {成功} 条任务记录 (输出文件已保留)")

    # 对外刷新入口 (主线程)
    def refresh(self):
        self._refresh()
        if self.page is not None:
            try:
                self.page.update()
            except Exception:
                pass  # 刻意静默: 高频路径(refresh(), 逐行/每秒级), 补日志会刷屏

    # 子树级刷新入口 (gui_app 刷新循环用, H6: 避免 page.update() 整页 diff)
    def refresh_ui(self):
        self._refresh()
        try:
            self._list_view.update()
            self._count_text.update()
        except Exception:
            pass  # 刻意静默: 高频路径(refresh_ui(), 逐行/每秒级), 补日志会刷屏
