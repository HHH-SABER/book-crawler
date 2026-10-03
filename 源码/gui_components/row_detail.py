# -*- coding: utf-8 -*-
"""任务行内展开详情：引擎降级链 / 反爬命中 / 质检指标 / 增量统计 / 错误信息

在 TaskTable 行展开时渲染, 数据来自 TaskInfo.metrics (日志解析回填)。
"""
import flet as ft
import time

from .task_manager import TaskInfo
from .ui_fluent import (FONT_STACK, SIZE_TINY,
                         WEIGHT_SUBTITLE, WEIGHT_BODY)
# Phase 3 (2026-10-04): 颜色一律走令牌 —— 直接 import MORANDI_* 绑到的是
# **构建期求值**的字符串对象, 切夜间主题后本地引用不会被更新 (见
# phase3_迁移规范.md / log_tab.py 样例)。取色() 只在构建期取值 → 配 登记重刷()。
from .ui_tokens import 取色, 登记重刷


def _fmt_elapsed(task: TaskInfo) -> str:
    """格式化任务耗时"""
    st = task.metrics.start_time
    if task.status == 'interrupted' and not task.metrics.end_time:
        return '—'  # 上轮实际中断时刻未知，不能当作仍在运行累计
    if not st:
        return "—"
    # 已完成/失败/停止/死书待确认: 用结束时间冻结耗时, 不再随当前时间增长
    # (dead_pending 是终态, 漏判会让耗时列每秒疯涨 —— 死书机制 阶段2)
    et = task.metrics.end_time
    if task.status in ("completed", "failed", "stopped", "dead_pending") and et:
        end = et
    else:
        end = time.time()
    secs = max(0, end - st)
    if secs < 60:
        return f"{secs:.0f}s"
    m, s = divmod(int(secs), 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"


def _kv(label: str, value: str, color=None, 色键: str = None) -> ft.Control:
    """键值对展示单元。

    Phase 3: 色键 非空 = 走令牌色并登记主题重刷 (取色是构建期求值, 不登记
    切夜间就掉不了色); 色键为 None 时沿用调用方给的直接色值 / M3 别名。
    """
    值控件 = ft.Text(value, size=SIZE_TINY, weight=WEIGHT_BODY,
                    color=(取色(色键) if 色键 else (color or ft.Colors.ON_SURFACE)),
                    font_family=FONT_STACK, selectable=True,
                    expand=True, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)
    if 色键:
        登记重刷(值控件, lambda c, k=色键: setattr(c, 'color', 取色(k)))
    return ft.Row([
        ft.Text(label, size=SIZE_TINY, weight=WEIGHT_BODY,
                color=ft.Colors.ON_SURFACE_VARIANT,
                font_family=FONT_STACK, width=64),
        值控件,
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
        # Phase 3: 令牌键替代 MORANDI_* 字符串常量 (后者切夜间不变色)
        _kv("当前引擎", engine_now,
            色键='status-success' if mt.engine else None),
        _kv("降级链", chain),
    ], spacing=2)

    # 反爬区
    anti = mt.anti_spider_type or "未检测到"
    anti_色键 = 'status-warning' if mt.anti_spider_type else None
    anti_body = ft.Column([
        _kv("命中类型", anti, 色键=anti_色键),
        _kv("增量跳过", f"{mt.incremental_skipped} 章"
                        + (" (未启用)" if not mt.incremental_skipped else "")),
    ], spacing=2)

    # 质检区
    if mt.quality_score >= 0:
        q_色键 = 'status-success' if mt.quality_passed else 'status-error'
        q_text = f"{mt.quality_score:.0f} 分 ({'通过' if mt.quality_passed else '未通过'})"
    else:
        q_色键 = None
        q_text = "尚未质检"
    quality_body = ft.Column([
        _kv("最近质检", q_text, 色键=q_色键),
        # 清洗摘要 (2026-09-29 可观测性): 最近一章的删除计数, 无数据不显示
        *([
            _kv("清洗", _清洗摘要文本(mt.clean_summary))
        ] if getattr(mt, 'clean_summary', None) else []),
    ], spacing=2)

    # 错误区 (有错才显示)
    sections = [
        _section("引擎", ft.Icons.SPEED_OUTLINED, engine_body),
        _section("反爬", ft.Icons.SHIELD_OUTLINED, anti_body),
        _section("质检", ft.Icons.FACT_CHECK_OUTLINED, quality_body),
    ]
    if task.error:
        # Phase 3: 令牌色 + 登记重刷 (旧写法绑的字符串常量切夜间不变色)
        err_body = _kv("错误", task.error[:120], 色键='status-error')
        sections.append(_section("错误", ft.Icons.ERROR_OUTLINE, err_body))

    return ft.Container(
        content=ft.Row(sections, spacing=6,
                      vertical_alignment=ft.CrossAxisAlignment.START),
        padding=ft.Padding.symmetric(horizontal=28, vertical=4),
    )


def _清洗摘要文本(summary: dict) -> str:
    """清洗统计 dict → 一行摘要 (如 '广告3 推广2 水印1'), 空统计返回 '无删除'"""
    parts = [f"{k}{int(v)}" for k, v in summary.items()
             if isinstance(v, (int, float)) and v]
    return ' '.join(parts) if parts else '无删除'
