# -*- coding: utf-8 -*-
"""右侧常驻栏 + 底部常驻日志条 (设计稿 界面设计预览/index.html)

2026-10-06 (Phase 4 批 2) 由"单抽屉三视图切换"改为**两处常驻**:
  - 右侧常驻栏: 任务详情 (默认) ↔ 抓取结果文件预览
  - 底部常驻日志条 (.log-strip): 实时日志, 深色终端风 + ▲/▼ 折叠
理由: 设计稿把「任务详情/输出文件」放右栏常驻、把「实时日志」放底部常驻;
此前两者共用一个"点行才开"的抽屉, 与设计稿的呈现形态不符。

历史沿革: 实时日志 (默认) / 任务详情 / 文件预览 三视图切换

- 宽度固定 320px, 始终展开
- 实时日志视图 (默认): 跟随选中任务的实时日志, 深色终端风 + 语义着色
- 任务详情视图: 大进度环 + 指标卡 (引擎/反爬/质检/增量) + 输出文件
- 文件预览视图: 抓取结果目录文件列表 + 内容预览
- 行内 📄 按钮切到详情/预览, × 按钮返回实时日志
"""
import flet as ft
import os
import sys
import glob
import threading

from .task_manager import TaskManager
from .ui_theme import (status_chip, status_color, tonal_btn,
                       LOG_TERMINAL_BG, LOG_TERMINAL_FONT, log_line_color)
from .ui_fluent import (FONT_STACK, SIZE_LABEL, SIZE_SMALL, SIZE_TINY,
                          WEIGHT_SUBTITLE, WEIGHT_BODY, 提示条,
                          open_dialog, close_dialog)
# Phase 3 (2026-10-04): 颜色一律走令牌 —— 直接 import MORANDI_* 绑到的是
# **构建期求值**的字符串对象, 切夜间主题后本地引用不会被更新 (见
# phase3_迁移规范.md / log_tab.py 样例)。取色() 只在构建期取值 → 配 登记重刷()。
from .ui_tokens import 取色, 登记重刷

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys as _sys; _sys.path.insert(0, _HERE)  # noqa: E402
from _path_utils import get_default_output_dir  # noqa: E402
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


def _令牌色(控件, 键: str):
    """给控件上令牌色并登记主题重刷 (Phase 3), 返回该控件。

    为什么必须两件事一起做: 取色() 是**构建期**求值, 只写取色不登记 = 切主题
    依然不变色 (半迁移等于白干); 登记后由 ui_tokens.设置主题 统一回调重设属性。
    """
    控件.color = 取色(键)
    return 登记重刷(控件, lambda c, k=键: setattr(c, 'color', 取色(k)))


# 面板宽度 (常驻): 常规 320px; 窄窗口(≤1200px) 收到 260px (2026-10-04 UX 改进)
_WIDTH_OPEN = 320
_WIDTH_NARROW = 260


class DetailDrawer:
    """右侧常驻面板 (实时日志 / 任务详情 / 文件预览)"""

    def __init__(self, task_manager: TaskManager):
        self.task_manager = task_manager
        self.page = None
        self._view = "detail"     # 右栏视图: detail (默认) / preview
        self._日志条展开 = True      # 底部日志条折叠态 (设计稿 ▲)
        self._视图已建 = False       # 幂等: 两个构建入口共用一套视图控件
        self._窄档 = False        # 窄窗口(≤1200px)档: 宽度 320 → 260
        self._log_sig = None      # 日志视图渲染签名 (task_id, len(logs))
        self._files = []
        self._selected_file = None
        # UI 引用
        self.container = None
        self._title_text = None
        self._log_view = None
        self._log_list = None
        self._detail_view = None
        self._preview_view = None
        self._file_list = None
        self._file_content = None
        self._file_info = None

    # ------------------------------------------------------------------ UI
    # 底部日志条展开高度 (设计稿 .log-strip 在 940 画布上约 220px;
    # 本机实际逻辑视口 725 → 取 180, 保证日志条 + 任务表都能看见)
    _日志条高 = 180

    def _构建视图(self):
        """构建三块视图控件 (**幂等**: build() 与 build_log_strip() 都会调用)。"""
        if getattr(self, '_视图已建', False):
            return
        # ---- 实时日志 (现居底部常驻日志条) ----
        # scroll=ALWAYS: 常显滚动条 (2026-09-29 二轮反馈"实时日志也加滚动条")
        self._log_list = ft.ListView(expand=True, spacing=1, auto_scroll=True,
                                     scroll=ft.ScrollMode.ALWAYS)
        self._log_view = ft.Container(
            content=self._log_list,
            expand=True,
            bgcolor=LOG_TERMINAL_BG,
            border_radius=8,
            padding=8,
        )

        # ---- 任务详情 (现居右侧常驻栏) ----
        # scroll+tight: 指标卡多时栏内滚, 不再被裁掉 (2026-10-03 改 ALWAYS 常显滚动条)
        self._detail_view = ft.Column(spacing=8, scroll=ft.ScrollMode.ALWAYS,
                                      tight=True)

        # ---- 文件预览 (右栏切换视图) ----
        self._file_list = ft.ListView(expand=True, spacing=2, auto_scroll=True,
                                      scroll=ft.ScrollMode.ALWAYS)
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
        # 查重入口 (2026-10-07): 右栏只有 ~300px, 放不下第二个文字按钮 →
        # 用图标按钮 + tooltip。扫描在工作线程, 结果走弹窗 (见 _检测重复)。
        查重_btn = ft.IconButton(icon=ft.Icons.FIND_REPLACE_OUTLINED, icon_size=16,
                                 tooltip="检测重复文件 (同一本书被抓了多份)",
                                 on_click=lambda e: self._检测重复())
        登记重刷(查重_btn, lambda c: setattr(c, 'icon_color', 取色('text-secondary')))
        # Phase 3: 令牌色 + 登记重刷 (旧写法绑的字符串常量切夜间不变色)
        抓取结果图标 = _令牌色(
            ft.Icon(ft.Icons.FOLDER_OPEN_OUTLINED, size=16), 'status-success')
        self._preview_view = ft.Column([
            ft.Row([
                抓取结果图标,
                ft.Text("抓取结果", size=SIZE_SMALL, weight=WEIGHT_SUBTITLE,
                        font_family=FONT_STACK),
                ft.Container(expand=True),
                refresh_btn,
                查重_btn,
            ], spacing=4),
            ft.Container(content=self._file_list, height=180),
            self._file_info,
            ft.Container(content=self._file_content, expand=True),
        ], spacing=6)
        self._视图已建 = True

    def build(self) -> ft.Control:
        """构建**右侧常驻栏**: 任务详情 (默认) ↔ 抓取结果文件预览。

        设计稿: 右栏常驻「任务详情」(进度环 + 指标卡 + 降级链 + 输出文件卡);
        实时日志改由 build_log_strip() 放在**底部常驻**。
        """
        self._构建视图()
        self._title_text = ft.Text("任务详情", size=SIZE_SMALL,
                                   weight=WEIGHT_SUBTITLE, font_family=FONT_STACK)
        self._toggle_btn = ft.IconButton(
            icon=ft.Icons.FOLDER_OPEN_OUTLINED, icon_size=16,
            tooltip="查看抓取结果文件",
            on_click=lambda e: self._on_toggle_click(),
            style=ft.ButtonStyle(
                padding=4, shape=ft.RoundedRectangleBorder(radius=4)),
        )
        self._view = "detail"
        self._detail_view.visible = True
        self._preview_view.visible = False
        self.container = ft.Container(
            content=ft.Column([
                ft.Row([
                    self._title_text,
                    ft.Container(expand=True),
                    self._toggle_btn,
                ], spacing=4),
                ft.Divider(height=1),
                self._detail_view,
                self._preview_view,
            ], spacing=6, expand=True),
            # 宽度跟随窄档 (设置窄档 可反复切换, 见文件末尾)
            width=(_WIDTH_NARROW if self._窄档 else _WIDTH_OPEN),
            padding=ft.Padding.symmetric(horizontal=10, vertical=10),
            bgcolor=ft.Colors.SURFACE,
            border=ft.Border(left=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)),
            # 注意: 不能再设 expand=True — 工作台 Row 中左列与面板都是
            # expand 时会 50/50 平分, 内容区被压剩一半 (列错位的真正根因)
        )
        try:
            self.refresh()      # 详情视图立即填充
        except Exception as _e:
            _dbg("详情面板", f'裸 except 吞异常: {type(_e).__name__}: {_e}')
        return self.container

    def build_log_strip(self) -> ft.Control:
        """构建**底部常驻日志条** (设计稿 `.log-strip`): 深色终端风 + ▲/▼ 折叠。"""
        self._构建视图()
        # 标题走令牌色 + 登记重刷 (Phase 3 约定: 构建期取色必须登记, 否则切主题不换色;
        # 也让"日志条"这棵树里有令牌色控件, 主题重刷验收不是空测试)
        # 用 text-secondary 而非 text-primary: 后者日间值 #1B1B1B 与夜间
        # on-brand/btn-primary-fg 同值, 是主题重刷"值集合判据"的固有盲区
        # (见 测试/test_主题重刷.py::test_值集合判据的已知盲区) ——
        # 用真正仅日间的令牌色, 才能让日志条这棵树的主题校验不是空测试。
        self._日志条标题 = ft.Text("实时日志", size=SIZE_SMALL,
                                  weight=WEIGHT_SUBTITLE,
                                  color=取色('text-secondary'),
                                  font_family=FONT_STACK)
        登记重刷(self._日志条标题, lambda c: setattr(c, 'color', 取色('text-secondary')))
        self._日志条体 = ft.Container(content=self._log_view, height=self._日志条高)
        self._日志条箭头 = ft.IconButton(
            icon=ft.Icons.KEYBOARD_ARROW_DOWN, icon_size=18,
            tooltip="收起日志",
            on_click=lambda e: self.切换日志条(),
            style=ft.ButtonStyle(
                padding=4, shape=ft.RoundedRectangleBorder(radius=4)),
        )
        self._日志条 = ft.Container(
            content=ft.Column([
                ft.Row([self._日志条标题, ft.Container(expand=True),
                        self._日志条箭头], spacing=4),
                self._日志条体,
            ], spacing=2, tight=True),
            padding=ft.Padding.symmetric(horizontal=10, vertical=6),
            bgcolor=ft.Colors.SURFACE,
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=8,
        )
        self._日志条展开 = True
        try:
            self.refresh_log()   # 日志立即填充
        except Exception as _e:
            _dbg("详情面板", f'裸 except 吞异常: {type(_e).__name__}: {_e}')
        return self._日志条

    def 切换日志条(self):
        """折叠/展开底部日志条 (设计稿日志条右上角 ▲ 的语义)。"""
        self._日志条展开 = not getattr(self, '_日志条展开', True)
        self._应用日志条展开()
        self._update()

    def _应用日志条展开(self):
        """把 _日志条展开 落到控件属性上 (只改属性, 不 update)。"""
        try:
            self._日志条体.visible = getattr(self, '_日志条展开', True)
            self._日志条箭头.icon = (ft.Icons.KEYBOARD_ARROW_DOWN
                                    if self._日志条展开
                                    else ft.Icons.KEYBOARD_ARROW_UP)
            self._日志条箭头.tooltip = ("收起日志" if self._日志条展开 else "展开日志")
        except Exception as _e:
            _dbg("详情面板", f'日志条折叠失败: {type(_e).__name__}: {_e}')

    # ------------------------------------------------------------- 视图路由
    def open(self, view: str = "detail", task_id: str = ""):
        """切换右栏视图 / 选中任务 (主线程)。

        Args:
            view: "detail" (任务详情, 默认) / "preview" (抓取结果文件) /
                  "log" —— **历史 API 兼容**: 日志条已常驻底部, 此值只表示
                  "选中该任务并确保日志条展开", 不再切换可见性。
            task_id: 可选, 指定任务 (默认用当前选中任务)
        """
        if task_id:
            self.task_manager.select_task(task_id)
        if view == "log":
            self._日志条展开 = True
            self._应用日志条展开()
            self.refresh_log()
            self._update()
            return
        self._view = view if view in ("detail", "preview") else "detail"
        self._detail_view.visible = (self._view == "detail")
        self._preview_view.visible = (self._view == "preview")
        self._title_text.value = {"detail": "任务详情", "preview": "文件预览"}[self._view]
        self._toggle_btn.icon = (ft.Icons.CLOSE if self._view == "preview"
                                 else ft.Icons.FOLDER_OPEN_OUTLINED)
        self._toggle_btn.tooltip = ("返回任务详情" if self._view == "preview"
                                    else "查看抓取结果文件")
        if self._view == "preview":
            self._scan_files()
        else:
            self.refresh()
        self._update()

    def close(self):
        """返回右栏详情视图 (历史 API 兼容: 日志已常驻底部条, 无"收起抽屉"语义)"""
        self.open("detail")

    def _on_toggle_click(self):
        """右栏按钮: 任务详情 ↔ 抓取结果文件 (日志已常驻底部条, 不参与切换)"""
        self.open("preview" if self._view == "detail" else "detail")

    def _update(self):
        try:
            self.page.update()
        except Exception:
            pass  # 刻意静默: 高频路径(_update(), 逐行/每秒级), 补日志会刷屏

    # ----------------------------------------------------------- 实时日志视图
    # 语义着色: [引擎]/[反爬]/[质检]/[增量]/[速度] 等前缀着不同颜色
    _SEMANTIC_COLORS = [
        ('[引擎]', '#4CC2FF'),      # 引擎: 亮蓝
        ('[反爬]', '#FCE100'),      # 反爬: 黄
        ('[质检]', '#6CCB5F'),      # 质检: 绿
        ('[增量]', '#9CD8F7'),      # 增量: 浅蓝
        ('[速度自适应]', '#4CC2FF'),
        ('[并发]', '#9CD8F7'),
        ('[缓存]', '#9D9D9D'),
    ]

    def refresh_log(self):
        """刷新实时日志视图 (主线程, 由刷新循环驱动; 仅日志视图可见时渲染)

        H5 修复: 旧实现每秒 clear + 重建 100 条控件, 导致 selectable 文本
        永远无法选中复制 + 每秒全量 patch。改为签名比对 + 增量追加
        (task.logs 只追加; 换任务/截断/堆积超限时回退全量重建)。
        """
        # 日志条常驻: 折叠时不渲染 (省开销); 旧实现判的是抽屉视图可见性
        if self._log_list is None or not getattr(self, '_日志条展开', True):
            return
        tid = self.task_manager.selected_task_id
        if not tid:
            if getattr(self, '_日志条标题', None) is not None \
                    and self._日志条标题.value != "实时日志":
                self._日志条标题.value = "实时日志"
            self._log_sig = None
            self._log_list.controls.clear()
            return
        task = self.task_manager.get_task(tid)
        if not task:
            return
        if getattr(self, '_日志条标题', None) is not None:
            self._日志条标题.value = f"实时日志 · {task.title[:24]}"

        from .task_manager import snapshot_task_logs
        previous = getattr(self, '_log_sig', None)
        prev_count = previous[1] if previous and previous[0] == tid else 0
        snapshot = snapshot_task_logs(task, prev_count)
        sig = (tid, snapshot['total'], snapshot['epoch'])
        if previous == sig:
            return
        if (not previous or previous[0] != tid or previous[2] != snapshot['epoch']
                or snapshot['截断'] or len(snapshot['entries']) > 60):
            self._log_list.controls.clear()
            for log in snapshot_task_logs(task)['entries'][-100:]:
                self._log_list.controls.append(self._log_line(log))
        else:
            for log in snapshot['entries']:
                self._log_list.controls.append(self._log_line(log))
            if len(self._log_list.controls) > 120:
                self._log_list.controls = self._log_list.controls[-100:]
        self._log_sig = sig

    @staticmethod
    def _日志行色(msg: str):
        """日志行文字色 → (颜色, 令牌键或 None)。

        Phase 3: 令牌键非空 = 该色随主题变, 调用方**必须**登记重刷, 否则
        切夜间后这行字还是日间色 (旧写法 import 的字符串常量就栽在这里)。
        语义前缀色/终端级别色是恒深色 (日=夜), 令牌键返回 None 不必登记。
        """
        if '[错误]' in msg or '失败' in msg:
            return 取色('status-error'), 'status-error'
        if '成功' in msg or '完成' in msg:
            return 取色('status-success'), 'status-success'
        for prefix, color in DetailDrawer._SEMANTIC_COLORS:
            if prefix in msg:
                return color, None
        return log_line_color(msg), None

    @staticmethod
    def _log_line(log):
        """单条日志控件 (级别色 + 设计稿语义前缀色)"""
        msg = log['msg']
        色, 令牌键 = DetailDrawer._日志行色(msg)
        控件 = ft.Text(f"[{log['time']}] {msg}",
                       size=SIZE_TINY,
                       font_family=LOG_TERMINAL_FONT,
                       color=色,
                       selectable=True)
        if 令牌键:
            登记重刷(控件, lambda c, k=令牌键: setattr(c, 'color', 取色(k)))
        return 控件

    def update_views(self):
        """子树级刷新收口 (H6: 仅更新面板内当前可见视图, 替代整页 update)"""
        try:
            # 批 2: 日志条与右栏**都常驻**, 不再是二选一
            if getattr(self, '_日志条展开', True):
                self._log_list.update()
            if self._view == "detail":
                self._detail_view.update()
            elif self._view == "preview":
                self._file_list.update()
                self._file_content.update()
        except Exception:
            pass  # 刻意静默: 高频路径(update_views(), 逐行/每秒级), 补日志会刷屏

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
        elif task.status != "running":
            ring_value = 0.0
        ring = ft.ProgressRing(
            width=56, height=56, stroke_width=6, value=ring_value,
            color=status_color(task.status),
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        )
        # Phase 3: status_color() 同属构建期取色 (ui_theme 侧未登记重刷),
        # 不补登记大进度环切夜间后仍停在日间色。
        登记重刷(ring, lambda c, s=task.status:
                 setattr(c, 'color', status_color(s)))

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
        def _metric_cell(label, value, color=None, 色键: str = None):
            """指标格 (Phase 3: 色键非空 = 令牌色 + 登记重刷, 否则用 M3 别名)"""
            值控件 = ft.Text(value, size=SIZE_SMALL, weight=WEIGHT_SUBTITLE,
                            color=(取色(色键) if 色键
                                   else (color or ft.Colors.ON_SURFACE)),
                            font_family=FONT_STACK, max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS)
            if 色键:
                登记重刷(值控件, lambda c, k=色键: setattr(c, 'color', 取色(k)))
            return ft.Container(
                content=ft.Column([
                    ft.Text(label, size=SIZE_TINY, weight=WEIGHT_BODY,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                            font_family=FONT_STACK),
                    值控件,
                ], spacing=1),
                padding=ft.Padding.symmetric(horizontal=10, vertical=6),
                bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
                border_radius=8, expand=True,
            )
        self._detail_view.controls.append(ft.Row([
            _metric_cell("引擎", mt.engine or "requests",
                         色键='status-success' if mt.engine else None),
            _metric_cell("反爬", mt.anti_spider_type or "无",
                         色键='status-warning' if mt.anti_spider_type else None),
        ], spacing=6))
        qs = mt.quality_score
        self._detail_view.controls.append(ft.Row([
            _metric_cell("质检",
                         f"{qs:.0f}分" if qs >= 0 else "—",
                         色键=(('status-success' if mt.quality_passed
                               else 'status-error') if qs >= 0 else None)),
            _metric_cell("增量跳过", f"{mt.incremental_skipped} 章",
                         色键='accent-fg' if mt.incremental_skipped else None),
        ], spacing=6))

        # 降级链 (有才显示)
        if mt.engine_fallback_chain:
            chain = " → ".join(mt.engine_fallback_chain + [mt.engine or "…"])
            self._detail_view.controls.append(ft.Text(
                f"降级链: {chain}", size=SIZE_TINY, font_family=FONT_STACK,
                color=ft.Colors.ON_SURFACE_VARIANT))

        # 输出文件 + 操作 (打开文件夹 / 导出 EPUB 单篇导出)
        if task.output_file:
            文件图标 = _令牌色(
                ft.Icon(ft.Icons.DESCRIPTION_OUTLINED, size=14), 'status-success')
            file_row = ft.Row([
                文件图标,
                ft.Text(os.path.basename(task.output_file),
                        size=SIZE_TINY, font_family=FONT_STACK,
                        color=ft.Colors.ON_SURFACE_VARIANT, expand=True,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ft.IconButton(
                    icon=ft.Icons.IMPORT_CONTACTS, icon_size=14,
                    tooltip="导出 EPUB (单篇导出, 与全局导出同格式)",
                    on_click=lambda e: self._export_epub(task),
                    style=ft.ButtonStyle(
                        padding=2, shape=ft.RoundedRectangleBorder(radius=6)),
                ),
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
            # Phase 3: 令牌色 + 登记重刷 (旧写法绑的字符串常量切夜间不变色)
            错误文本 = _令牌色(ft.Text(
                f"错误: {task.error[:150]}", size=SIZE_TINY,
                font_family=FONT_STACK), 'status-error')
            self._detail_view.controls.append(错误文本)

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
        except Exception as _e:
            _dbg("详情面板", f'裸 except 吞异常: {type(_e).__name__}: {_e}')

    def _export_epub(self, task):
        """单篇 EPUB 导出 (2026-09-29): 对已完成书籍手动触发, 主线程执行"""
        try:
            from epub_exporter import 导出单篇
            epub_path = 导出单篇(task.output_file, title=task.title)
            self._toast(f'✅ EPUB 已导出: {os.path.basename(epub_path)}')
            _dbg("详情面板", f'[单篇EPUB] {task.title}: {epub_path}')
        except Exception as _e:
            self._toast(f'❌ EPUB 导出失败: {_e}')
            _dbg("详情面板", f'[单篇EPUB] 失败: {type(_e).__name__}: {_e}')

    def _toast(self, msg: str):
        """SnackBar 轻提示 (flet 0.86 兼容, 经 ui_fluent.open_dialog)"""
        try:
            from .ui_fluent import open_dialog
            if self.page is not None:
                open_dialog(self.page, 提示条(msg, 时长=4000))
        except Exception as _e:
            _dbg("详情面板", f'裸 except 吞异常: {type(_e).__name__}: {_e} (toast={msg[:40]})')

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
        """选中文件 → 预览内容

        M11 修复: 旧实现全量 read() 后才截断, 几十 MB 的书会冻结 UI 数秒;
        改为只读前 20 万字符。
        """
        if not (0 <= idx < len(self._files)):
            return
        fp = self._files[idx]
        self._selected_file = fp
        content = ""
        for enc in ('utf-8', 'gbk', 'gb2312', 'utf-16'):
            try:
                with open(fp, 'r', encoding=enc) as f:
                    content = f.read(200000)   # 只读前 20 万字符 (预览上限的 4 倍)
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

    # --------------------------------------------------------- 窄窗口档
    # ------------------------------------------------------ 查重 (去重, 2026-10-07)
    def _dispatch(self, fn):
        """提交 UI 更新到主线程 (flet 控件只能在主线程改)。"""
        if self.page is None:
            return
        try:
            async def _runner():
                fn()
                try:
                    self.page.update()
                except Exception as _e:
                    _dbg("详情栏", f'裸 except 吞异常: {type(_e).__name__}: {_e}')
            self.page.run_task(_runner)
        except Exception as _e:
            _dbg("详情栏", f'裸 except 吞异常: {type(_e).__name__}: {_e}')

    def _检测重复(self):
        """扫描抓取结果目录里的重复书籍 → 结果弹窗。

        扫描要读全部正文算句子指纹, 大目录可达数秒, 故放工作线程;
        扫描结果同时写入去重清单 (状态根 数据/去重清单.json)。
        """
        if getattr(self, '_查重中', False):
            self._toast("正在检测重复文件, 请稍候")
            return
        self._查重中 = True
        self._toast("正在检测重复文件…")

        def _worker():
            组, 错误 = [], ''
            try:
                import 去重处理
                组 = 去重处理.扫描重复()
                去重处理.写出清单(组)
            except Exception as e:  # noqa: BLE001 — 必须留痕
                _dbg("详情栏", f'查重异常: {type(e).__name__}: {e}')
                错误 = f'{type(e).__name__}: {e}'
            self._查重中 = False
            self._dispatch(lambda: self._显示查重结果(组, 错误))

        threading.Thread(target=_worker, daemon=True, name='dedupe-scan').start()

    def _显示查重结果(self, 组: list, 错误: str):
        """查重结果弹窗: 每组列出保留项 + 可清理项 + 待确认项。

        ⚠️ EXE 文字必须显式 color (v2.4.19 G-H1 教训: 缺色渲染成不可见)。
        """
        if self.page is None:
            return
        块 = []
        if 错误:
            块.append(ft.Text(f"检测失败: {错误}", size=SIZE_SMALL,
                              color=ft.Colors.ERROR, font_family=FONT_STACK))
        elif not 组:
            块.append(ft.Text("未发现重复文件。", size=SIZE_SMALL,
                              color=ft.Colors.ON_SURFACE, font_family=FONT_STACK))
        else:
            可清理 = sum(len(g['可自动清理']) for g in 组)
            待确认 = sum(len(g['待确认']) for g in 组)
            块.append(ft.Text(
                f"发现 {len(组)} 组重复: 可自动清理 {可清理} 个, 待人工确认 {待确认} 个",
                size=SIZE_SMALL, weight=WEIGHT_SUBTITLE,
                color=ft.Colors.ON_SURFACE, font_family=FONT_STACK))
            for g in 组[:20]:
                行 = [ft.Text(f"保留: {g['代表']['名']}  ({g['代表']['字数']:,} 字)",
                              size=SIZE_TINY, color=ft.Colors.ON_SURFACE,
                              font_family=FONT_STACK, max_lines=1,
                              overflow=ft.TextOverflow.ELLIPSIS)]
                for x in g['可自动清理']:
                    行.append(ft.Text(f"清理[{x['判定']}] {x['名']}",
                                      size=SIZE_TINY, max_lines=1,
                                      color=ft.Colors.ON_SURFACE_VARIANT,
                                      font_family=FONT_STACK,
                                      overflow=ft.TextOverflow.ELLIPSIS))
                for x in g['待确认']:
                    行.append(ft.Text(f"待确认 {x['名']} (差异较大, 未自动处理)",
                                      size=SIZE_TINY, max_lines=1,
                                      color=ft.Colors.ON_SURFACE_VARIANT,
                                      font_family=FONT_STACK,
                                      overflow=ft.TextOverflow.ELLIPSIS))
                块.append(ft.Container(content=ft.Column(行, spacing=1, tight=True),
                                       # flet 0.86 无 padding.symmetric →
                                       # 用 ft.Padding(left, top, right, bottom)
                                       padding=ft.Padding(0, 4, 0, 4)))
            if len(组) > 20:
                块.append(ft.Text(f"…另有 {len(组) - 20} 组未显示",
                                  size=SIZE_TINY,
                                  color=ft.Colors.ON_SURFACE_VARIANT,
                                  font_family=FONT_STACK))

        有可清理 = any(g['可自动清理'] for g in 组)
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("重复文件检测", color=ft.Colors.ON_SURFACE,
                          font_family=FONT_STACK),
            content=ft.Container(
                content=ft.Column(块, spacing=2, tight=True,
                                  scroll=ft.ScrollMode.ALWAYS),
                width=520, height=360),
            actions=[
                ft.TextButton("关闭",
                              on_click=lambda _: close_dialog(self.page, dialog)),
                ft.TextButton("移入隔离区并清理", disabled=not 有可清理,
                              on_click=lambda _: self._执行查重清理(组, dialog)),
            ],
        )
        open_dialog(self.page, dialog)

    def _执行查重清理(self, 组: list, dialog):
        """把各组「可自动清理」项**移入隔离目录** (可反悔)。

        绝不删组内保留项 —— 编排层 (去重处理.执行清理) 也有同样的硬保护。
        """
        try:
            close_dialog(self.page, dialog)
        except Exception as _e:
            _dbg("详情栏", f'关窗失败: {type(_e).__name__}: {_e}')
        self._toast("正在移入隔离区…")

        def _worker():
            清理数, 失败 = 0, []
            try:
                import 去重处理
                for g in 组:
                    if not g['可自动清理']:
                        continue
                    r = 去重处理.执行清理(g['键'], '隔离')
                    清理数 += len(r['清理'])
                    失败.extend(名 for 名, _ in r['失败'])
            except Exception as e:  # noqa: BLE001 — 必须留痕
                _dbg("详情栏", f'清理异常: {type(e).__name__}: {e}')
                失败.append(f'{type(e).__name__}: {e}')

            def _ui():
                if 失败:
                    self._toast(f"⚠️ 已隔离 {清理数} 个, {len(失败)} 个失败")
                else:
                    self._toast(f"✅ 已隔离 {清理数} 个重复文件 (可反悔)")
                self._scan_files()
            self._dispatch(_ui)

        threading.Thread(target=_worker, daemon=True, name='dedupe-clean').start()

    def 设置窄档(self, 窄: bool):
        """窄窗口(≤1200px)模式: 抽屉宽度 320 → 260, 把省下的宽度让给任务表。

        (2026-10-04 UX 改进: 960px 窗宽下任务表横向溢出 538px, 抽屉收窄
        与 task_table.设置窄档 配合使用。)
        幂等 + 可在 page.on_resize 里反复调用: 只改 container.width, 不重建
        控件树; 构造后 (未 build) 调用也安全; 异常一律留痕吞掉, 不向调用方抛。
        """
        try:
            self._窄档 = bool(窄)
            if self.container is not None:
                self.container.width = (_WIDTH_NARROW if self._窄档
                                        else _WIDTH_OPEN)
                try:
                    self.container.update()
                except Exception:
                    pass  # 刻意静默: 尚未挂到 page 上时 update 会抛 (构造后自测场景)
        except Exception as _e:
            _dbg("详情面板", f'窄档切换失败: {type(_e).__name__}: {_e}')
