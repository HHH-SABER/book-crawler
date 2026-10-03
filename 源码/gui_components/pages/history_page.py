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
from .. import states
from ..ui_theme import make_card, tonal_btn, page_header
from ..ui_fluent import (FONT_STACK, SIZE_TITLE, SIZE_LABEL, SIZE_SMALL,
                          SIZE_TINY, WEIGHT_TITLE,
                          WEIGHT_SUBTITLE, WEIGHT_BODY)
# Phase 3 (2026-10-04): 页面颜色一律走令牌 + 登记重刷 —— 直接 import MORANDI_*
# 绑到的是**构建期字符串**, 切夜间主题这些控件纹丝不动; 见 文档/审查报告汇总.md 的 Phase 3 结论。
from ..ui_tokens import 取色, 登记重刷
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


# 结果类型 → 令牌键 (Phase 3: 旧写法在这里存的是构建期求值的色字符串, 切主题不会重刷;
# 令牌键在**构建控件时**才 取色(), 并逐控件 登记重刷。)
_结果令牌表 = {
    '新增': 'status-success',
    '更新': 'btn-primary-bg',
    '未变化': 'accent-fg',
    '失败': 'status-error',
}

# 时间范围下拉 值 → 人话 (空态说明里用)
_天数说明表 = {1: '最近 24 小时', 7: '最近 7 天', 30: '最近 30 天'}


def _结果令牌(结果, 默认=None):
    """结果类型 → 令牌键 (未命中返回 默认)"""
    return _结果令牌表.get(结果, 默认)


def _登记文本色(控件: ft.Text, 令牌: str) -> ft.Text:
    """把 ft.Text 前景色绑到令牌并登记重刷 (Phase 3)。

    只写 取色() 不登记 = 切主题依然不掉色, 等于半迁移白干。
    """
    return 登记重刷(控件, lambda c: setattr(c, 'color', 取色(令牌)))


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
        self._book_filter = None     # build() 创建; 清除筛选时需复位
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

        # v2.4.28: 书名关键词搜索框 (对 URL 明细按书名筛选; 数据源为 网站清单)
        self._book_filter = ft.TextField(
            label="按书名搜索", dense=True, width=170,
            hint_text="书名关键词",
            text_style=ft.TextStyle(size=SIZE_LABEL, font_family=FONT_STACK),
            on_submit=lambda e: self.refresh(),
            on_change=lambda e: self.refresh(),
        )

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
        self._table_view = ft.ListView(expand=True, spacing=2, auto_scroll=True,
                                       scroll=ft.ScrollMode.ALWAYS)

        # Fluent 页面大标题 (设计稿: 标题+副标题在页头, 视图切换在右侧)
        header = page_header(
            "爬取历史", "按 URL 维度记录所有抓取结果, 支持增量抓取与趋势分析",
            actions=[self._urls_mode_btn, self._sites_mode_btn])

        header_card = make_card(
            ft.Column([
                self._stat_row,
                ft.Row([self._domain_dd, self._days_dd,
                        self._book_filter, self._result_chips_row,
                        refresh_btn, update_btn],
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
            except Exception as _e:
                _dbg("历史页", f'裸 except 吞异常: {type(_e).__name__}: {_e}')
            return
        if not books:
            if self._shelf_info:
                self._shelf_info.value = "书架为空 (尚无已抓取小说); 抓取成功后自动登记"
            try:
                self.page.update()
            except Exception as _e:
                _dbg("历史页", f'裸 except 吞异常: {type(_e).__name__}: {_e}')
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
        except Exception as _e:
            _dbg("历史页", f'裸 except 吞异常: {type(_e).__name__}: {_e}')

    def _rebuild_result_chips(self):
        """重建结果类型过滤 chips"""
        self._result_chips_row.controls.clear()
        self._result_chips_row.controls.append(self._make_chip(None, "全部"))
        for r in history_data.get_result_types():
            self._result_chips_row.controls.append(self._make_chip(r, r))

    def _make_chip(self, result: "str | None", label: str) -> ft.Control:
        """单个结果过滤 chip"""
        active = (self._filter_result == result)
        # Phase 3: 令牌色构建期求值, 未登记重刷则切夜间主题 chip 颜色不变
        令牌 = _结果令牌(result, 'btn-primary-bg')
        color = 取色(令牌)
        文字 = ft.Text(label, size=SIZE_TINY, weight=WEIGHT_SUBTITLE,
                       color=("#FFFFFF" if active else color),
                       font_family=FONT_STACK)
        chip = ft.Container(
            content=文字,
            padding=ft.Padding.symmetric(horizontal=10, vertical=4),
            bgcolor=(color if active else None),
            border=None if active else ft.Border.all(1, color),
            border_radius=999,
            ink=True,
            on_click=lambda e, r=result: self._on_result_chip(r),
        )

        def _重刷(_控件, _选中=active, _令牌=令牌):
            """选中=同色填充白字, 未选中=同色描边彩字 —— 一个回调里一起改, 只登记一次

            子控件从 _控件 身上取, 回调不额外持有它 (避免弱引用登记表把旧控件留活)。
            """
            新色 = 取色(_令牌)
            _控件.content.color = "#FFFFFF" if _选中 else 新色
            _控件.bgcolor = 新色 if _选中 else None
            _控件.border = None if _选中 else ft.Border.all(1, 新色)

        return 登记重刷(chip, _重刷)

    def _on_result_chip(self, result):
        self._filter_result = None if self._filter_result == result else result
        self._rebuild_result_chips()
        self.refresh()

    def _on_filter_change(self):
        self._filter_domain = (None if self._domain_dd.value == "__all__"
                               else self._domain_dd.value)
        self._filter_days = int(self._days_dd.value or "0")
        self.refresh()

    def _有筛选条件(self) -> bool:
        """当前是否有任何生效的筛选/搜索 (决定空态是"暂无记录"还是"筛选后为空")"""
        if self._filter_domain or self._filter_days or self._filter_result:
            return True
        try:
            return bool((self._book_filter.value or '').strip())
        except Exception:
            return False

    def _筛选说明(self) -> str:
        """当前筛选条件的人话描述 (空态里告诉用户"为什么一行都没有")"""
        bits = []
        if self._filter_domain:
            bits.append(f"站点={self._filter_domain}")
        if self._filter_days:
            bits.append("时间范围=" + _天数说明表.get(
                self._filter_days, f"最近 {self._filter_days} 天"))
        if self._filter_result:
            bits.append(f"结果={self._filter_result}")
        try:
            关键词 = (self._book_filter.value or '').strip()
        except Exception:
            关键词 = ''
        if 关键词:
            bits.append(f"书名关键词“{关键词}”")
        return ("当前筛选: " + " / ".join(bits)) if bits else ""

    def _清除筛选(self, e=None):
        """清空筛选条件并重渲染 (供空态的「清除筛选」按钮调用)"""
        try:
            self._filter_domain = None
            self._filter_days = 0
            self._filter_result = None
            for 控件, 值 in ((self._domain_dd, "__all__"), (self._days_dd, "0"),
                            (self._book_filter, "")):
                if 控件 is not None:
                    控件.value = 值
            self._rebuild_result_chips()
            self.refresh()      # refresh() 末尾已带 page.update() 兜底刷出
        except Exception as _e:
            _dbg("历史页", f'清除筛选失败: {type(_e).__name__}: {_e}')

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
                pass  # 刻意静默: 高频路径(refresh(), 逐行/每秒级), 补日志会刷屏

    def _build_stat_cards(self, stats: dict):
        """重建 5 张统计卡"""
        self._stat_row.controls.clear()
        total = stats.get('总请求数', 0)
        items = [
            (str(total), "总请求", 'btn-primary-bg'),
            (str(stats.get('新增', 0)), "新增", 'status-success'),
            (str(stats.get('更新', 0)), "更新", 'btn-primary-bg'),
            (str(stats.get('未变化', 0)), "未变化", 'accent-fg'),
            (str(stats.get('失败', 0)), "失败",
             'status-error' if stats.get('失败', 0) else 'status-warning'),
        ]
        for value, label, 令牌 in items:
            # Phase 3: 数值文字走令牌并登记重刷 (只 取色 不登记 = 切主题不掉色)
            值文本 = ft.Text(value, size=SIZE_TITLE, weight=WEIGHT_TITLE,
                            color=取色(令牌), font_family=FONT_STACK)
            _登记文本色(值文本, 令牌)
            self._stat_row.controls.append(ft.Container(
                content=ft.Column([
                    值文本,
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
        """URL 明细表 (v2.4.28: 先按书名关键词过滤, 再补 网站名/书名 两列)"""
        rows = history_data.query_history(域名=domain, 起始时间=start,
                                         结束时间=end, 结果=result)
        # v2.4.28: 书名搜索框过滤 (匹配 网站清单 中该书名对应的所有 URL)
        try:
            关键词 = (self._book_filter.value or '').strip()
        except Exception:
            关键词 = ''
        if 关键词:
            rows = history_data.按书名过滤(rows, 关键词)
        # v2.4.28: 按 URL 反查 网站名/小说名 (清单未命中则回退域名/留空)
        rows = history_data.补网站信息(rows)
        self._table_view.controls.clear()
        self._table_view.controls.append(self._table_header(
            ["书名", "网站", "URL", "最后抓取", "状态码", "耗时", "字节", "结果", "错误原因"],
            [16, 11, 22, 11, 6, 6, 7, 7, 14]))
        if not rows:
            # Phase 3 UX: 筛选后为空不再只显示"暂无历史记录"(会被误解成数据丢了),
            # 改统一空态 + 一键清除筛选; 无任何筛选条件时保持原"首次为空"文案。
            if self._有筛选条件():
                self._table_view.controls.append(states.筛选后为空(
                    清除筛选回调=self._清除筛选, 说明=self._筛选说明()))
            else:
                self._append_empty("暂无历史记录 (启动抓取后自动记录)")
            return
        if len(rows) >= _MAX_ROWS:
            self._table_view.controls.append(ft.Text(
                f"(仅显示最近 {_MAX_ROWS} 条)", size=SIZE_TINY, italic=True,
                color=ft.Colors.ON_SURFACE_VARIANT, font_family=FONT_STACK))
        for r in rows:
            令牌 = _结果令牌(r.get('结果', ''))
            self._table_view.controls.append(self._url_row(r, 令牌))

    def _url_row(self, r: dict, 结果令牌=None) -> ft.Control:
        """URL 明细行 (含 书名/网站名 前两列)"""
        def _cell(content, flex, text_style=None):
            return ft.Container(content=content, expand=flex,
                                 alignment=ft.Alignment(-1, 0))
        def _t(v, color=None, bold=False, 令牌=None):
            控件 = ft.Text(v, size=SIZE_TINY, weight=(WEIGHT_SUBTITLE if bold
                                                      else WEIGHT_BODY),
                           color=(取色(令牌) if 令牌 else color),
                           font_family=FONT_STACK,
                           max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                           selectable=True)
            # Phase 3: 走令牌的才登记重刷; ft.Colors.* 由 Flet 按 theme_mode 自行适配
            return _登记文本色(控件, 令牌) if 令牌 else 控件
        err = r.get('错误原因', '')
        书名 = r.get('小说名', '') or ''
        网站 = r.get('网站名', '') or ''
        return ft.Container(
            content=ft.Row([
                _cell(_t(书名 if 书名 else "—",
                         color=None if 书名 else ft.Colors.ON_SURFACE_VARIANT,
                         令牌='status-success' if 书名 else None,
                         bold=bool(书名)), 16),
                _cell(_t(网站 if 网站 else "—",
                         color=None if 网站 else ft.Colors.ON_SURFACE_VARIANT,
                         令牌='accent-fg' if 网站 else None), 11),
                _cell(_t(r.get('url', '')), 22),
                _cell(_t(r.get('最后抓取', '')[:16]), 11),
                _cell(_t(str(r.get('状态码', '')),
                         令牌=('status-error' if r.get('状态码', 0) and
                              int(r.get('状态码', 200)) >= 400 else None)), 6),
                _cell(_t(f"{r.get('耗时秒', 0):.1f}s" if r.get('耗时秒') else "—"), 6),
                _cell(_t(self._fmt_size(r.get('字节大小', 0))), 7),
                _cell(_t(r.get('结果', ''), 令牌=结果令牌), 7),
                _cell(_t(err[:40] if err else "—",
                         令牌='status-error' if err else None), 14),
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
            失败令牌 = 'status-error' if st.get('失败', 0) > 10 else None
            def _t(v, c=None, 令牌=None):
                控件 = ft.Text(str(v), size=SIZE_TINY, weight=WEIGHT_BODY,
                               color=(取色(令牌) if 令牌 else c),
                               font_family=FONT_STACK, max_lines=1)
                # Phase 3: 走令牌的登记重刷 (构建期取色, 切主题不会自动重算)
                return _登记文本色(控件, 令牌) if 令牌 else 控件
            def _cell(content, flex):
                return ft.Container(content=content, expand=flex,
                                    alignment=ft.Alignment(-1, 0))
            self._table_view.controls.append(ft.Container(
                content=ft.Row([
                    _cell(_t(s.get('域名', ''), 令牌='status-success'), 24),
                    _cell(_t(s.get('URL数', 0)), 8),
                    _cell(_t(s.get('总请求数', 0)), 9),
                    _cell(_t(st.get('新增', 0)), 8),
                    _cell(_t(st.get('更新', 0)), 8),
                    _cell(_t(st.get('未变化', 0)), 8),
                    _cell(_t(st.get('失败', 0), 令牌=失败令牌), 8),
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
