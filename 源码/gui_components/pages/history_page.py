# -*- coding: utf-8 -*-
"""爬取历史页：统计卡片 + 过滤器 + URL 明细表 / 站点汇总

独立全宽页面 (非抽屉), 数据源 history_data (爬取历史.py / 站点历史.py)。
- 顶部: 5 张统计卡 (总请求/新增/更新/未变化/失败)
- 中部: 过滤器 (域名下拉 / 最近N天 / 结果类型 chips / 刷新)
- 下部: URL 明细表 (可切换为"站点汇总"视图)
"""
import flet as ft
import time

from . import history_data
from ..ui_theme import make_card, tonal_btn, page_header
from ..ui_morandi import (FONT_STACK, SIZE_TITLE, SIZE_LABEL, SIZE_SMALL,
                          SIZE_TINY, WEIGHT_TITLE,
                          WEIGHT_SUBTITLE, WEIGHT_BODY,
                          MORANDI_PRIMARY, MORANDI_SECONDARY, MORANDI_SUCCESS,
                          MORANDI_ERROR, MORANDI_WARNING, MORANDI_ACCENT)

# 结果类型 → 展示色
_RESULT_COLORS = {
    '新增': MORANDI_SUCCESS,
    '更新': MORANDI_PRIMARY,
    '未变化': MORANDI_ACCENT,
    '失败': MORANDI_ERROR,
}

# 明细表最大行数 (超出提示截断)
_MAX_ROWS = 500


class HistoryPage:
    """爬取历史独立页"""

    def __init__(self):
        self.page = None
        self.task_manager = None   # 由 gui_app 注入 (一键更新书架创建任务用)
        self._view_mode = "urls"     # urls: URL明细 / sites: 站点汇总
        self._filter_domain = None
        self._filter_days = 0        # 0=全部时间
        self._filter_result = None
        # UI 引用
        self._domain_dd = None
        self._days_dd = None
        self._result_chips_row = None
        self._stat_row = None
        self._table_view = None
        self._mode_seg = None
        self._shelf_info = None

    # ------------------------------------------------------------------ UI
    def build(self) -> ft.Control:
        """构建历史页"""
        # 域名过滤器
        self._domain_dd = ft.Dropdown(
            label="站点", width=220, dense=True,
            text_style=ft.TextStyle(size=SIZE_LABEL, font_family=FONT_STACK),
            options=[ft.dropdown.Option("__all__", "全部站点")],
            value="__all__",
            on_select=lambda e: self._on_filter_change(),
        )

        # 时间范围过滤器
        self._days_dd = ft.Dropdown(
            label="时间范围", width=160, dense=True,
            text_style=ft.TextStyle(size=SIZE_LABEL, font_family=FONT_STACK),
            options=[
                ft.dropdown.Option("0", "全部时间"),
                ft.dropdown.Option("1", "最近 24 小时"),
                ft.dropdown.Option("7", "最近 7 天"),
                ft.dropdown.Option("30", "最近 30 天"),
            ],
            value="0",
            on_select=lambda e: self._on_filter_change(),
        )

        # 结果类型过滤 chips
        self._result_chips_row = ft.Row(spacing=4)
        self._rebuild_result_chips()

        refresh_btn = tonal_btn("刷新", icon=ft.Icons.REFRESH,
                                on_click=lambda e: self.refresh())
        # P2: 一键更新书架 (对已抓取小说增量抓取)
        update_btn = tonal_btn("一键更新书架", icon=ft.Icons.SYNC,
                               on_click=self._on_update_shelf,
                               tooltip="对书架中已抓取小说做增量抓取 (跳过未变化章节)")
        self._shelf_info = ft.Text("", size=SIZE_TINY,
                                   color=ft.Colors.ON_SURFACE_VARIANT,
                                   font_family=FONT_STACK)

        # 视图切换: URL 明细 / 站点汇总 (两个互斥按钮)
        self._urls_mode_btn = tonal_btn(
            "URL 明细", icon=ft.Icons.LINK,
            on_click=lambda e: self._set_view_mode("urls"))
        self._sites_mode_btn = tonal_btn(
            "站点汇总", icon=ft.Icons.DNS_OUTLINED,
            on_click=lambda e: self._set_view_mode("sites"))
        self._apply_mode_btn_styles()

        # 统计卡行 + 过滤器 + 表格
        self._stat_row = ft.Row(spacing=6)
        self._table_view = ft.ListView(expand=True, spacing=2, auto_scroll=True)

        # Fluent 页面大标题 (设计稿: 标题+副标题在页头, 视图切换在右侧)
        header = page_header(
            "爬取历史", "按 URL 维度记录所有抓取结果, 支持增量抓取与趋势分析",
            actions=[self._urls_mode_btn, self._sites_mode_btn])

        header_card = make_card(
            ft.Column([
                self._stat_row,
                ft.Row([self._domain_dd, self._days_dd,
                        self._result_chips_row, refresh_btn, update_btn],
                       spacing=6, wrap=True),
                self._shelf_info,
            ], spacing=10),
            padding=10,
        )

        table_card = make_card(
            ft.Container(content=self._table_view, expand=True),
            expand=True, padding=6,
        )

        self.refresh()
        return ft.Column([header, header_card, table_card], expand=True, spacing=10,
                         horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    # ------------------------------------------------------------- 过滤交互
    def _on_update_shelf(self, e):
        """一键更新书架: 遍历书架清单, 每本以 增量+续写原文件 方式创建更新任务"""
        if self.task_manager is None:
            if self._shelf_info:
                self._shelf_info.value = "任务管理器未就绪"
            return
        try:
            from 书架 import 列出 as _书架列出
            books = _书架列出()
        except Exception as ex:
            if self._shelf_info:
                self._shelf_info.value = f"书架读取失败: {ex}"
            try:
                self.page.update()
            except Exception:
                pass
            return
        if not books:
            if self._shelf_info:
                self._shelf_info.value = "书架为空 (尚无已抓取小说); 抓取成功后自动登记"
            try:
                self.page.update()
            except Exception:
                pass
            return
        created = 0
        for it in books:
            url = it.get('目录URL', '')
            if not url:
                continue
            self.task_manager.create_task(url, mode="full", resume=True,
                                          output_dir=None, unique_title=False,
                                          incremental=True)
            created += 1
        if self._shelf_info:
            self._shelf_info.value = f"已为 {created} 本书创建更新任务 (增量抓取, 见任务列表)"
        try:
            self.page.update()
        except Exception:
            pass

    def _rebuild_result_chips(self):
        """重建结果类型过滤 chips"""
        self._result_chips_row.controls.clear()
        self._result_chips_row.controls.append(self._make_chip(None, "全部"))
        for r in history_data.get_result_types():
            self._result_chips_row.controls.append(self._make_chip(r, r))

    def _make_chip(self, result: "str | None", label: str) -> ft.Control:
        """单个结果过滤 chip"""
        active = (self._filter_result == result)
        color = _RESULT_COLORS.get(result, MORANDI_PRIMARY)
        return ft.Container(
            content=ft.Text(label, size=SIZE_TINY, weight=WEIGHT_SUBTITLE,
                            color=("#FFFFFF" if active else color),
                            font_family=FONT_STACK),
            padding=ft.Padding.symmetric(horizontal=10, vertical=4),
            bgcolor=(color if active else None),
            border=None if active else ft.Border.all(1, color),
            border_radius=999,
            ink=True,
            on_click=lambda e, r=result: self._on_result_chip(r),
        )

    def _on_result_chip(self, result):
        self._filter_result = None if self._filter_result == result else result
        self._rebuild_result_chips()
        self.refresh()

    def _on_filter_change(self):
        self._filter_domain = (None if self._domain_dd.value == "__all__"
                               else self._domain_dd.value)
        self._filter_days = int(self._days_dd.value or "0")
        self.refresh()

    def _apply_mode_btn_styles(self):
        """按当前视图高亮对应切换按钮"""
        urls_on = (self._view_mode == "urls")
        self._urls_mode_btn.style = ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=10),
            bgcolor=(ft.Colors.PRIMARY_CONTAINER if urls_on else None),
            color=(ft.Colors.ON_PRIMARY_CONTAINER if urls_on else None),
        )
        self._sites_mode_btn.style = ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=10),
            bgcolor=(ft.Colors.PRIMARY_CONTAINER if not urls_on else None),
            color=(ft.Colors.ON_PRIMARY_CONTAINER if not urls_on else None),
        )

    def _set_view_mode(self, mode: str):
        """切换 URL 明细 / 站点汇总视图"""
        if self._view_mode == mode:
            return
        self._view_mode = mode
        self._apply_mode_btn_styles()
        self.refresh()

    # ------------------------------------------------------------- 数据刷新
    def _time_range(self):
        """按天数过滤器换算 (起始时间, 结束时间)"""
        if not self._filter_days:
            return None, None
        ts = time.time() - self._filter_days * 86400
        start = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))
        return start, None

    def refresh(self):
        """重新查询并刷新 (主线程调用)"""
        if self._table_view is None:
            return
        start, end = self._time_range()
        domain = self._filter_domain
        result = self._filter_result

        # 刷新域名下拉 (保留当前选择)
        domains = history_data.list_domains()
        cur = self._domain_dd.value or "__all__"
        self._domain_dd.options = [ft.dropdown.Option("__all__", "全部站点")] + \
            [ft.dropdown.Option(d, d) for d in domains]
        if cur not in [o.key for o in self._domain_dd.options]:
            cur = "__all__"
            self._filter_domain = None
        self._domain_dd.value = cur

        # 统计卡
        stats = history_data.get_stats(域名=domain, 起始时间=start, 结束时间=end)
        self._build_stat_cards(stats)

        # 表格
        if self._view_mode == "sites":
            self._build_sites_table(start, end)
        else:
            self._build_urls_table(domain, start, end, result)

        if self.page is not None:
            try:
                self.page.update()
            except Exception:
                pass

    def _build_stat_cards(self, stats: dict):
        """重建 5 张统计卡"""
        self._stat_row.controls.clear()
        total = stats.get('总请求数', 0)
        items = [
            (str(total), "总请求", MORANDI_PRIMARY),
            (str(stats.get('新增', 0)), "新增", MORANDI_SUCCESS),
            (str(stats.get('更新', 0)), "更新", MORANDI_PRIMARY),
            (str(stats.get('未变化', 0)), "未变化", MORANDI_ACCENT),
            (str(stats.get('失败', 0)), "失败",
             MORANDI_ERROR if stats.get('失败', 0) else MORANDI_WARNING),
        ]
        for value, label, color in items:
            self._stat_row.controls.append(ft.Container(
                content=ft.Column([
                    ft.Text(value, size=SIZE_TITLE, weight=WEIGHT_TITLE,
                            color=color, font_family=FONT_STACK),
                    ft.Text(label, size=SIZE_TINY, weight=WEIGHT_BODY,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                            font_family=FONT_STACK),
                ], spacing=0, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=ft.Padding.symmetric(horizontal=18, vertical=8),
                bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
                border_radius=10,
                expand=True,
            ))

    def _table_header(self, cols: list, flexes: list) -> ft.Control:
        """明细表头"""
        cells = []
        for c, f in zip(cols, flexes):
            cells.append(ft.Container(
                content=ft.Text(c, size=SIZE_TINY, weight=WEIGHT_SUBTITLE,
                                color=ft.Colors.ON_SURFACE_VARIANT,
                                font_family=FONT_STACK),
                expand=f,
                alignment=ft.Alignment(-1, 0),
            ))
        return ft.Row(cells, spacing=6)

    def _build_urls_table(self, domain, start, end, result):
        """URL 明细表"""
        rows = history_data.query_history(域名=domain, 起始时间=start,
                                         结束时间=end, 结果=result)
        self._table_view.controls.clear()
        self._table_view.controls.append(self._table_header(
            ["URL", "最后抓取", "状态码", "耗时", "字节", "结果", "错误原因"],
            [36, 14, 7, 7, 9, 8, 19]))
        if not rows:
            self._append_empty("暂无历史记录 (启动抓取后自动记录)")
            return
        if len(rows) >= _MAX_ROWS:
            self._table_view.controls.append(ft.Text(
                f"(仅显示最近 {_MAX_ROWS} 条)", size=SIZE_TINY, italic=True,
                color=ft.Colors.ON_SURFACE_VARIANT, font_family=FONT_STACK))
        for r in rows:
            color = _RESULT_COLORS.get(r.get('结果', ''), None)
            self._table_view.controls.append(self._url_row(r, color))

    def _url_row(self, r: dict, color) -> ft.Control:
        """URL 明细行"""
        def _cell(content, flex, text_style=None):
            return ft.Container(content=content, expand=flex,
                                 alignment=ft.Alignment(-1, 0))
        def _t(v, color=None, mono=False):
            return ft.Text(v, size=SIZE_TINY, weight=WEIGHT_BODY,
                           color=color, font_family=FONT_STACK,
                           max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                           selectable=True)
        err = r.get('错误原因', '')
        return ft.Container(
            content=ft.Row([
                _cell(_t(r.get('url', '')), 36),
                _cell(_t(r.get('最后抓取', '')[:16]), 14),
                _cell(_t(str(r.get('状态码', '')),
                         MORANDI_ERROR if r.get('状态码', 0) and
                         int(r.get('状态码', 200)) >= 400 else None), 7),
                _cell(_t(f"{r.get('耗时秒', 0):.1f}s" if r.get('耗时秒') else "—"), 7),
                _cell(_t(self._fmt_size(r.get('字节大小', 0))), 9),
                _cell(_t(r.get('结果', ''), color), 8),
                _cell(_t(err[:40] if err else "—",
                         MORANDI_ERROR if err else None), 19),
            ], spacing=6),
            padding=ft.Padding.symmetric(horizontal=8, vertical=3),
            border_radius=6,
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
        )

    @staticmethod
    def _fmt_size(n) -> str:
        """字节大小人性化"""
        try:
            n = int(n or 0)
        except Exception:
            return "—"
        if n >= 1048576:
            return f"{n/1048576:.1f}M"
        if n >= 1024:
            return f"{n/1024:.0f}K"
        return str(n)

    def _build_sites_table(self, start, end):
        """站点汇总表"""
        sites = history_data.list_sites_summary()
        self._table_view.controls.clear()
        self._table_view.controls.append(self._table_header(
            ["域名", "URL数", "总请求", "新增", "更新", "未变化", "失败",
             "首次抓取", "最近抓取"],
            [24, 8, 9, 8, 8, 8, 8, 13, 14]))
        if not sites:
            self._append_empty("暂无站点记录")
            return
        for s in sites:
            st = s.get('统计', {})
            color = MORANDI_ERROR if st.get('失败', 0) > 10 else None
            def _t(v, c=None):
                return ft.Text(str(v), size=SIZE_TINY, weight=WEIGHT_BODY,
                               color=c, font_family=FONT_STACK, max_lines=1)
            def _cell(content, flex):
                return ft.Container(content=content, expand=flex,
                                    alignment=ft.Alignment(-1, 0))
            self._table_view.controls.append(ft.Container(
                content=ft.Row([
                    _cell(_t(s.get('域名', ''), MORANDI_SECONDARY), 24),
                    _cell(_t(s.get('URL数', 0)), 8),
                    _cell(_t(s.get('总请求数', 0)), 9),
                    _cell(_t(st.get('新增', 0)), 8),
                    _cell(_t(st.get('更新', 0)), 8),
                    _cell(_t(st.get('未变化', 0)), 8),
                    _cell(_t(st.get('失败', 0), color), 8),
                    _cell(_t((s.get('首次抓取', '') or '')[:10]), 13),
                    _cell(_t((s.get('最近抓取', '') or '')[:16]), 14),
                ], spacing=6),
                padding=ft.Padding.symmetric(horizontal=8, vertical=3),
                border_radius=6,
                bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
                ink=True,
                tooltip="点击筛选该站点",
                on_click=lambda e, d=s.get('域名', ''): self._filter_to_domain(d),
            ))

    def _filter_to_domain(self, domain: str):
        """点击站点行 → 按该域名过滤并切回 URL 明细"""
        self._filter_domain = domain
        self._view_mode = "urls"
        self._apply_mode_btn_styles()
        self._domain_dd.value = domain
        self.refresh()

    def _append_empty(self, msg: str):
        """空状态占位"""
        self._table_view.controls.append(
            ft.Container(
                content=ft.Column([
                    ft.Icon(ft.Icons.HISTORY_TOGGLE_OFF, size=40,
                            color=ft.Colors.ON_SURFACE_VARIANT, opacity=0.5),
                    ft.Text(msg, size=SIZE_SMALL, weight=WEIGHT_BODY,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                            font_family=FONT_STACK),
                ], spacing=8,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=ft.Padding.symmetric(vertical=36),
            ))
