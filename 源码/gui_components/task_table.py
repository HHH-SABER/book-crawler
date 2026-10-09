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
                         WEIGHT_BODY,
                         open_dialog, close_dialog, 提示条)
# Phase 3 (2026-10-04): 颜色一律走令牌 —— 直接 import MORANDI_* 绑到的是
# **构建期求值**的字符串对象, 切夜间主题后 ui_fluent 的 globals().update
# 改不动页面里的本地引用, 控件颜色纹丝不动 (见 phase3_迁移规范.md)。
# 取色() 只在构建期取值, 故每处非 M3 槽位的颜色都配 登记重刷()。
from .ui_tokens import 取色, 登记重刷
from .row_detail import build_row_detail, _fmt_elapsed
from . import states
from . import 布局档位

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

# ⚠️ 批 4 (2026-10-07) 已废弃"窄档隐藏次级列"策略 —— 用户拍板对齐设计稿:
# 设计稿在**任何**断点都不隐藏任务表列 (固定 910px + 横向滚动, 见 index.html
# .task-table-inner width:910px 与 .task-table-scroll overflow-x:auto)。
# 旧策略是 ≤1200px 隐藏 引擎/反爬/耗时/质检 四列把表宽压到 606px 来消横滚,
# 与设计稿口径相反。_次级列 保留常量只为记录历史, 代码中不再使用。
_次级列 = (3, 4, 5, 6)
_次级列_已废弃 = True


def _表宽(窄: bool) -> int:
    """按当前可见列算表格内容宽度。

    窄档隐藏次级列后必须同步收窄这个固定宽度, 否则外层 Column 仍按全宽
    占位, 横向溢出照旧 (2026-10-04 UX 改进)。间距/内边距口径与 build() 一致。
    """
    可见宽 = [w for i, (_l, w, _c) in enumerate(_COLUMNS)
              if not (窄 and i in _次级列)]
    return sum(可见宽) + 6 * (len(可见宽) - 1) + 16


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


def _状态色文本(控件: ft.Text, 键: str) -> ft.Text:
    """给文本控件上令牌状态色, 并登记主题重刷 (Phase 3)。

    为什么不能直接 `color=MORANDI_*`: 那是模块级字符串常量, 构建期就定死;
    切夜间主题后页面里的本地引用不会被更新 → 该控件永远停在日间色。
    """
    控件.color = 取色(键)
    return 登记重刷(控件, lambda c, k=键: setattr(c, 'color', 取色(k)))



class TaskTable:
    """全宽任务表格组件"""

    def __init__(self, task_manager: TaskManager):
        self.task_manager = task_manager
        self.page = None
        self._expanded_id = ""      # 当前展开详情的任务 ID
        self._sig = None            # 行渲染签名 (无变化跳过重建)
        self._list_view = None
        # 窄档 (2026-10-04 UX 改进): ≤1200px 窗口隐藏次级列, 可反复切换
        self._窄档 = False
        self._表格体 = None         # 固定宽度的表格 Column (窄档要改它的 width)
        self._头部单元 = []         # 表头各列 Container (按 _COLUMNS 下标)
        self._行单元 = {i: [] for i in range(len(_COLUMNS))}   # 各列当前行单元
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
        # 表宽按当前窄档的可见列计算 (窄档隐藏次级列时会同步收窄)
        表宽 = _表宽(self._窄档)
        表格体 = ft.Column([header, self._list_view], spacing=4, width=表宽)
        self._表格体 = 表格体
        # 2026-10-03 八项需求#6: 横滚改 ALWAYS 常显水平滚动条
        横滚 = ft.Row([表格体], spacing=0, scroll=ft.ScrollMode.ALWAYS,
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
        单元列表 = [_h(label, width, center) for label, width, center in _COLUMNS]
        # 记住表头单元: 窄档切换时直接改 visible/width, 不必重建表头
        self._头部单元 = 单元列表
        for 列号, 单元 in enumerate(单元列表):
            self._应用列可见(单元, 列号)
        return ft.Row(单元列表, spacing=6)

    # ------------------------------------------------------- 窄档 (≤1200px)
    def _应用列可见(self, 单元, 列号: int):
        """设置单个列单元的可见性与宽度 (幂等, 只改属性)。

        批 4 (2026-10-07): **不再隐藏任何列** —— 设计稿任何断点都是
        固定 910px + 横向滚动。本方法保留为"统一设置列宽"的单一出口
        (旧实现在这里按 `_窄档` 把 引擎/反爬/耗时/质检 四列 visible=False
        且 width=0; 那个策略已按用户 2026-10-07 的决定废弃)。
        """
        单元.visible = True
        单元.width = _COLUMNS[列号][1]

    def 设置档位(self, 档: str, 参数: dict = None):
        """按布局档位调整任务表 (批 4)。

        设计稿口径: 表宽**恒为 910px**, 任何档都不隐藏列 → 本方法只保证表宽
        正确 (以及列可见性回到"全显示"), 宽度不够时交给外层横向滚动容器。

        幂等 + 可反复调用 (page.on_resize 每次都调): 只改既有控件属性并做
        子树级 update(), 不重建行、不改数据; 异常就地留痕, 绝不向调用方抛出
        (接口契约: 构造后调用 / 未 build 时调用都安全)。
        """
        try:
            self._档 = 档
            self._窄档 = (档 == 布局档位.窄)     # 兼容字段, 仅用于自检/日志
            参数 = 参数 or 布局档位.取参数(档)
            for 列号, 单元 in enumerate(self._头部单元):
                self._应用列可见(单元, 列号)
            for 列号, 单元s in self._行单元.items():
                for 单元 in 单元s:
                    self._应用列可见(单元, 列号)
            if self._表格体 is not None:
                宽 = 参数.get('表格固定宽') or _表宽(False)
                if self._表格体.width != 宽:
                    self._表格体.width = 宽
                try:
                    self._表格体.update()
                except Exception:
                    pass  # 刻意静默: 尚未挂到 page 上时 update 会抛 (构造后自测场景)
        except Exception as _e:
            _dbg("任务表", f'档位切换失败: {type(_e).__name__}: {_e}')

    def 设置窄档(self, 窄: bool):
        """兼容旧接口 (按设计稿口径: 窄档也不隐藏列, 只影响表宽参数)。"""
        档 = 布局档位.窄 if 窄 else 布局档位.宽
        self.设置档位(档, 布局档位.取参数(档))

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
        # 行要重建 → 先丢弃旧行单元引用 (窄档切换只需管当前活着的控件)
        for _列单元 in self._行单元.values():
            _列单元.clear()
        if not tasks:
            # 批 4 (2026-10-07): 手写空态 → 统一组件 (文案保留, 它比通用文案更指引人)。
            # 填满=False: _list_view 是 ListView, 无界高度里 expand 会被算成 0 高。
            self._list_view.controls.append(states.首次为空(
                图标=ft.Icons.LIBRARY_BOOKS_OUTLINED, 标题='暂无任务',
                说明='在上方输入网址后点击「开始」创建任务', 填满=False))
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
        # URL 改为可点击超链接 (2026-10-09):
        #   · Flet 0.86 的 Text 无 url= 参数, 用 on_tap + page.launch_url()
        #     经系统默认浏览器打开 (与 icon_rail 侧栏 GitHub 卡同一通道)
        #   · tooltip= → 悬停显示完整网址 (列宽 200px, 长 URL 必被省略号截断)
        #   · PRIMARY 色 + TextStyle 下划线 → 明确的可点击视觉提示, 与整体配色一致
        #   · 内层 on_tap 在 Flutter 手势竞技场中胜出, 不会触发行 on_click 选中
        url_text = ft.Text(task.url, size=SIZE_TINY, weight=WEIGHT_BODY,
                           color=ft.Colors.PRIMARY,
                           tooltip=task.url,
                           on_tap=lambda e, u=task.url: self._打开链接(u),
                           max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                           font_family=FONT_STACK,
                           style=ft.TextStyle(
                               decoration=ft.TextDecoration.UNDERLINE))
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
        # Phase 3: status_color() 也是构建期取色 (ui_theme 侧未登记重刷),
        # 不补登记的话进度环在切夜间后仍是日间灰 (与本次迁移同类缺陷)。
        登记重刷(ring, lambda c, s=task.status:
                 setattr(c, 'color', status_color(s)))
        progress_cell = _cell(ft.Row([ring, ft.Text(pct_text, size=SIZE_TINY,
                                                   font_family=FONT_STACK,
                                                   color=ft.Colors.ON_SURFACE_VARIANT)],
                                    spacing=4), width=_w(1))

        # 状态单元格
        status_cell = _cell(status_chip(task.status), width=_w(2), center=True)

        # 引擎单元格
        engine = task.metrics.engine or "—"
        引擎文本 = ft.Text(engine, size=SIZE_TINY, weight=WEIGHT_BODY,
                          font_family=FONT_STACK,
                          color=(None if task.metrics.engine
                                 else ft.Colors.ON_SURFACE_VARIANT),
                          max_lines=1,
                          overflow=ft.TextOverflow.ELLIPSIS)
        if task.metrics.engine:
            # Phase 3: 令牌色 + 登记重刷 (旧写法 import 的字符串常量切夜间不变色)
            _状态色文本(引擎文本, 'status-success')
        engine_cell = _cell(引擎文本, width=_w(3))

        # 反爬单元格 (命中显示标签色, 未命中灰)
        anti = task.metrics.anti_spider_type
        反爬文本 = ft.Text(anti or "—", size=SIZE_TINY, weight=WEIGHT_BODY,
                         font_family=FONT_STACK,
                         color=(None if anti else ft.Colors.ON_SURFACE_VARIANT),
                         max_lines=1,
                         overflow=ft.TextOverflow.ELLIPSIS)
        if anti:
            # Phase 3: 令牌色 + 登记重刷
            _状态色文本(反爬文本, 'status-warning')
        anti_cell = _cell(反爬文本, width=_w(4))

        # 耗时单元格
        elapsed_cell = _cell(ft.Text(_fmt_elapsed(task), size=SIZE_TINY,
                                     font_family=FONT_STACK,
                                     color=ft.Colors.ON_SURFACE_VARIANT), width=_w(5))

        # 质检单元格
        qs = task.metrics.quality_score
        if qs >= 0:
            q_text = f"{qs:.0f}分"
            q_键 = ('status-success' if task.metrics.quality_passed
                   else 'status-error')
        else:
            q_text, q_键 = "—", ""
        质检文本 = ft.Text(q_text, size=SIZE_TINY, weight=WEIGHT_BODY,
                         font_family=FONT_STACK,
                         color=(None if q_键 else ft.Colors.ON_SURFACE_VARIANT))
        if q_键:
            # Phase 3: 令牌色 + 登记重刷 (通过/未通过两色都由回调按主题重取)
            _状态色文本(质检文本, q_键)
        quality_cell = _cell(质检文本, width=_w(6))

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
        #
        # 死书分支 (2026-10-03 阶段3): 死书必然没有输出文件 → epub_btn 恒 disabled
        # 是纯死重按钮, 位置换成 忽略/删记录。**按钮数与列宽均不变** (仍 5 个 × 36px),
        # 不动 _COLUMNS 的 200px 分配。
        _死 = getattr(task, 'dead', None)
        _是死书 = bool(isinstance(_死, dict) and _死.get('类型'))
        if _是死书:
            epub_btn = ft.IconButton(
                icon=ft.Icons.DO_NOT_DISTURB_ON_OUTLINED, icon_size=14,
                tooltip="忽略此书 (标记已知问题, 保留记录不再提示)",
                on_click=lambda e, tid=task.task_id: self._on_ignore_dead(tid),
                width=36, height=32,
                style=ft.ButtonStyle(
                    padding=2, shape=ft.RoundedRectangleBorder(radius=6),
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
                ),
            )
        else:
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
            # 死书态: 删的是"任务行 + 书架 + 网站清单"三处记录 (走死书编排);
            # 普通态: 只删任务行
            tooltip=("删除这本书的记录 (任务/书架/网站清单)" if _是死书
                     else "删除任务"),
            on_click=lambda e, tid=task.task_id: (self._on_delete_dead(tid)
                                                   if _是死书
                                                   else self._on_delete(tid)),
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

        # 窄档(≤1200px): 次级列不参与布局; 同时记下单元引用, 供 设置窄档 后续切换
        单元列表 = [title_cell, progress_cell, status_cell, engine_cell,
                    anti_cell, elapsed_cell, quality_cell, ops_cell]
        for 列号, 单元 in enumerate(单元列表):
            self._应用列可见(单元, 列号)
            self._行单元[列号].append(单元)

        # 主行
        main_row = ft.Row(单元列表, spacing=6, wrap=False,
                          alignment=ft.MainAxisAlignment.START,
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
    def _打开链接(self, url: str):
        """任务列表超链接 → 系统默认浏览器打开原网页。

        主通道 page.launch_url (Flet 跨端 API); page 未就绪时兜底标准库
        webbrowser (桌面端等价)。任何失败只留痕不抛 —— 链接点击绝不能炸 UI。
        """
        try:
            if self.page is not None:
                self.page.launch_url(url)
                return
        except Exception as _e:
            _log("GUI", f"launch_url 失败, 走 webbrowser 兜底: "
                        f"{type(_e).__name__}: {_e}")
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception as _e:
            _log("GUI", f"打开链接失败: {type(_e).__name__}: {_e}")

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

    # ---------------------------------------------------- 死书动作 (阶段3)
    @staticmethod
    def _死书信息(task) -> dict:
        """取死书标记并做类型防御。

        Mock 陷阱 (阶段1 踩坑): getattr 返回 Mock 是 truthy, 直接当 dict 读
        键会 KeyError/TypeError。必须 isinstance(dict) + .get。
        """
        _死 = getattr(task, 'dead', None)
        return _死 if isinstance(_死, dict) else {}

    def _on_ignore_dead(self, task_id: str):
        """忽略此书: 死书清单状态置 已忽略 + 清任务上的 dead 标记。

        语义: 这本书的问题已知 (删了/不可达), 用户表态"不必再问"。
        **只改死书清单与任务标记, 不动书架/网站清单/历史/产物**。
        restart_task 同样会清 dead → 重下后本就不必再忽略。
        """
        task = self.task_manager.get_task(task_id)
        if not task:
            return
        死 = self._死书信息(task)
        键 = 死.get('键')
        if not 键:
            self._notify("该任务没有死书清单记录, 无法忽略")
            return
        try:
            import 死书处理
            ok = 死书处理.设状态(键, 死书处理.状态_已忽略)
        except Exception as _e:
            _dbg("任务表", f'忽略死书失败: {type(_e).__name__}: {_e}')
            self._notify(f"忽略失败: {_e}")
            return
        if not ok:
            self._notify("忽略失败: 死书清单写入未成功")
            return
        task.dead = None      # 清标记 → 状态胶囊回落, 行内按钮切回 EPUB
        self._notify(f"已忽略: {task.title or task.url}")
        _log("GUI", f"忽略死书: {task_id} ({task.url})")
        self.refresh()

    def _on_delete_dead(self, task_id: str):
        """死书删除: 弹确认框 → 删除书记录(任务/书架/网站清单) 三处编排。"""
        task = self.task_manager.get_task(task_id)
        if not task:
            return
        死 = self._死书信息(task)
        类型 = 死.get('类型') or '未知'
        原因 = 死.get('原因') or ''
        标题 = task.title or task.url
        if self.page is None:
            self._do_delete_dead(task_id)
            return
        # G-H1 教训 (v2.4.19): EXE 中 dialog 文字缺显式 color 会渲染成不可见。
        # 这是删数据确认框, 文字不可见会放大误删风险 → 逐个显式指定。
        # Phase 3: ON_SURFACE 直接用 M3 语义别名 (由 Flutter 按 theme_mode 解析),
        # 本就自动适配深浅, 不需要令牌 + 登记重刷。
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("删除这本书的记录", color=ft.Colors.ON_SURFACE,
                          font_family=FONT_STACK),
            content=ft.Text(
                f"书名: {标题}\n类型: {类型}\n\n"
                f"将删除三处记录:\n"
                f"  · 任务列表中的该行\n"
                f"  · 书架中的该书\n"
                f"  · 网站清单中的该网址\n\n"
                f"已下载的文件不会被删除。\n"
                f"判定原因: {原因}",
                size=SIZE_SMALL, font_family=FONT_STACK,
                color=ft.Colors.ON_SURFACE),
            actions=[
                ft.TextButton("取消",
                              on_click=lambda _: close_dialog(self.page, dialog)),
                ft.TextButton("删除记录",
                              on_click=lambda _: self._confirm_delete_dead(dialog, task_id)),
            ],
        )
        open_dialog(self.page, dialog)

    def _confirm_delete_dead(self, dialog, task_id: str):
        try:
            close_dialog(self.page, dialog)
        except Exception as _e:
            _dbg("任务表", f'裸 except 吞异常: {type(_e).__name__}: {_e}')
        self._do_delete_dead(task_id)

    def _do_delete_dead(self, task_id: str):
        """执行死书删除编排, 如实呈现部分成功 (删除书记录 不做回滚)。

        产物文件恒不删 (delete_task 恒传 delete_file=False)。
        """
        task = self.task_manager.get_task(task_id)
        if not task:
            return
        try:
            import 死书处理
            结果 = 死书处理.删除书记录(
                task.url, 任务id=task_id, task_manager=self.task_manager)
        except Exception as _e:
            _dbg("任务表", f'死书删除编排异常: {type(_e).__name__}: {_e}')
            self._notify(f"❌ 删除失败: {_e}")
            return
        try:
            死书处理.设状态(死书处理._键(task.url), 死书处理.状态_已删除)
        except Exception as _e2:
            _dbg("任务表", f'死书状态置已删除失败: {type(_e2).__name__}: {_e2}')
        失败 = [f"{k}: {v[1]}" for k, v in 结果.items()
                if k != '全部成功' and isinstance(v, tuple) and not v[0]]
        if 结果.get('全部成功'):
            self._notify(f"✅ 已删除记录: {task.title or task.url}")
        else:
            # 部分成功必须如实说 —— 伪"已删除"会让用户以为干净了
            self._notify(f"⚠️ 部分删除: {'; '.join(失败) or '未知'}")
        _log("GUI", f"死书删除编排 {task_id}: {结果}")
        self.refresh()

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
            title=ft.Text("删除任务", color=ft.Colors.ON_SURFACE,
                          font_family=FONT_STACK),
            content=ft.Text(f"任务输出文件:\n{fname}\n\n是否同时删除本地文件?",
                            size=SIZE_SMALL, font_family=FONT_STACK,
                            color=ft.Colors.ON_SURFACE),
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
            # 显式 color: EXE 中 SnackBar 文字缺色会渲染成不可见 (G-H1 教训)
            open_dialog(self.page, 提示条(msg))
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
            title=ft.Text("清空历史", color=ft.Colors.ON_SURFACE,
                          font_family=FONT_STACK),
            content=ft.Text(f"确定清空 {len(终态)} 条已结束任务的记录?\n"
                            "不会删除输出文件 (.txt/.epub)。",
                            size=SIZE_SMALL, font_family=FONT_STACK,
                            color=ft.Colors.ON_SURFACE),
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
