# -*- coding: utf-8 -*-
"""任务行内展开详情：引擎降级链 / 反爬命中 / 质检指标 / 增量统计 / 错误信息

在 TaskTable 行展开时渲染, 数据来自 TaskInfo.metrics (日志解析回填)。
"""
import flet as ft
import time

from .task_manager import TaskInfo
from .ui_theme import status_color
from .ui_morandi import (FONT_STACK, SIZE_LABEL, SIZE_SMALL, SIZE_TINY,
                         SIZE_BODY, WEIGHT_SUBTITLE, WEIGHT_BODY,
                         MORANDI_SUCCESS, MORANDI_ERROR, MORANDI_WARNING,
                         MORANDI_INFO)


def _fmt_elapsed(task: TaskInfo) -> str:
    """格式化任务耗时"""
    st = task.metrics.start_time
    if not st:
        return "—"
    end = time.time()
    if task.status in ("completed", "failed", "stopped"):
        # 结束时间不可得, 以当前计 (近似)
        pass
    secs = max(0, end - st)
    if secs < 60:
        return f"{secs:.0f}s"
    m, s = divmod(int(secs), 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"


def _kv(label: str, value: str, color=None) -> ft.Control:
    """键值对展示单元"""
    return ft.Row([
        ft.Text(label, size=SIZE_TINY, weight=WEIGHT_BODY,
                color=ft.Colors.ON_SURFACE_VARIANT,
                font_family=FONT_STACK, width=64),
        ft.Text(value, size=SIZE_TINY, weight=WEIGHT_BODY,
                color=color or ft.Colors.ON_SURFACE,
                font_family=FONT_STACK, selectable=True,
                expand=True, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
    ], spacing=6)


def _section(title: str, icon: str, body: ft.Control) -> ft.Control:
    """详情分区"""
    return ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Icon(icon, size=13, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Text(title, size=SIZE_TINY, weight=WEIGHT_SUBTITLE,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                        font_family=FONT_STACK),
            ], spacing=4),
            ft.Container(content=body, padding=ft.Padding(left=12, right=4,
                                                          top=2, bottom=0)),
        ], spacing=2),
        bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
        border_radius=8,
        padding=ft.Padding.symmetric(horizontal=8, vertical=6),
        expand=True,
    )


def build_row_detail(task: TaskInfo) -> ft.Control:
    """构建一个任务的行内展开详情 (每次展开时重建, 数据实时)"""
    mt = task.metrics

    # 引擎区
    engine_now = mt.engine or "requests (默认)"
    if mt.engine_fallback_chain:
        chain = " → ".join(mt.engine_fallback_chain + [mt.engine or "…"])
    else:
        chain = engine_now
    engine_body = ft.Column([
        _kv("当前引擎", engine_now,
            color=MORANDI_SUCCESS if mt.engine else None),
        _kv("降级链", chain),
    ], spacing=2)

    # 反爬区
    anti = mt.anti_spider_type or "未检测到"
    anti_color = MORANDI_WARNING if mt.anti_spider_type else None
    anti_body = ft.Column([
        _kv("命中类型", anti, color=anti_color),
        _kv("增量跳过", f"{mt.incremental_skipped} 章"
                        + (" (未启用)" if not mt.incremental_skipped else "")),
    ], spacing=2)

    # 质检区
    if mt.quality_score >= 0:
        q_color = MORANDI_SUCCESS if mt.quality_passed else MORANDI_ERROR
        q_text = f"{mt.quality_score:.0f} 分 ({'通过' if mt.quality_passed else '未通过'})"
    else:
        q_color = None
        q_text = "尚未质检"
    quality_body = ft.Column([
        _kv("最近质检", q_text, color=q_color),
    ], spacing=2)

    # 错误区 (有错才显示)
    sections = [
        _section("引擎", ft.Icons.SPEED_OUTLINED, engine_body),
        _section("反爬", ft.Icons.SHIELD_OUTLINED, anti_body),
        _section("质检", ft.Icons.FACT_CHECK_OUTLINED, quality_body),
    ]
    if task.error:
        err_body = _kv("错误", task.error[:120], color=MORANDI_ERROR)
        sections.append(_section("错误", ft.Icons.ERROR_OUTLINE, err_body))

    return ft.Container(
        content=ft.Row(sections, spacing=6,
                      vertical_alignment=ft.CrossAxisAlignment.START),
        padding=ft.Padding.symmetric(horizontal=28, vertical=4),
    )
