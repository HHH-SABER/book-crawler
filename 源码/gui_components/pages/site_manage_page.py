# -*- coding: utf-8 -*-
"""站点管理页：站点表格 (域名/模式/状态/启用) + 工具栏 + 底部编辑卡

- 状态列 = 健康度(爬取历史成功率) · 最近命中反爬 · 探测结果
- 启用开关写入 站点配置.json 的 enabled 字段 (sites_config 运行时加载过滤)
- 测试连接放后台线程 (site_probe), 结果回填表格
- 编辑卡在底部 (表格为主角, 编辑是次级动作)
"""
import flet as ft
import json
import os
import re
import sys
import threading
import time

_HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from ..ui_theme import make_card, filled_btn, tonal_btn, text_btn
from ..ui_morandi import (open_dialog, close_dialog,
                          FONT_STACK, SIZE_TITLE, SIZE_LABEL, SIZE_SMALL,
                          SIZE_TINY, SIZE_BODY, WEIGHT_TITLE,
                          WEIGHT_SUBTITLE, WEIGHT_BODY,
                          MORANDI_SECONDARY, MORANDI_SUCCESS, MORANDI_ERROR,
                          MORANDI_WARNING, MORANDI_ACCENT)
from . import history_data

try:
    from _path_utils import resolve_data_file, get_app_base_dir
except Exception:
    def resolve_data_file(filename, **kw):
        return os.path.join(_HERE, filename)

    def get_app_base_dir():
        return _HERE

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


def _is_jsonable(v) -> bool:
    """判断值能否被 json.dumps 序列化 (函数/类型/自定义对象 → False)"""
    if isinstance(v, (str, int, float, bool)) or v is None:
        return True
    if isinstance(v, dict):
        return all(_is_jsonable(k) and _is_jsonable(x) for k, x in v.items())
    if isinstance(v, (list, tuple)):
        return all(_is_jsonable(x) for x in v)
    return False


def _json_clean(obj):
    """递归过滤不可 JSON 序列化的字段 (如内置 SITE_PATTERNS 的自定义分页函数)

    - dict: 保留可序列化字段, 丢弃含函数/对象等的字段
    - list: 逐项清理, 清理后为空的 dict 整体丢弃, 避免条目因个别函数字段被误删
    """
    if isinstance(obj, dict):
        return {k: _json_clean(v) for k, v in obj.items() if _is_jsonable(v)}
    if isinstance(obj, (list, tuple)):
        out = []
        for v in obj:
            cleaned = _json_clean(v)
            if isinstance(cleaned, dict) and not cleaned:
                continue  # 清理后空 dict → 丢弃
            if cleaned is not None:
                out.append(cleaned)
        return out
    return obj


# 站点适配器模板 (新建适配器时生成)
_ADAPTER_TEMPLATE = '''# -*- coding: utf-8 -*-
"""{domain} 站点适配器 —— 外部插件模板

把本文件放进程序目录下的 `站点适配/` 文件夹即自动生效，无需重新打包。
按需实现下面的函数；返回 None 表示走程序内置/通用流程。
"""

try:
    import 日志 as _app_log
    _log = _app_log.get('adapter.{logname}')
except Exception:
    import logging
    _log = logging.getLogger('adapter.{logname}')

SITE = {{
    "domain": "{domain}",
    "pattern": "html_selector",
    "chapter_url_regex": "",
    "content_pagination": {{"suffix": "_{{N}}.html", "start": 1, "max_pages": 30}},
    "content_selectors": ["#content"],
    "anti_spider": {{"type": "auto"}},
}}


def parse_catalog(soup, catalog_url, base_url, **kw):
    """目录解析: 返回 [{{'title':..., 'url':...}}] 或 None (走通用/内置)"""
    return None


def extract_content(soup, page_url, base_url, **kw):
    """正文提取: 返回正文字符串 或 None (走通用/内置)"""
    return None


def paginate(current_url, page_index, **kw):
    """分页: 返回下一页 URL 或 None (停止分页)"""
    return None
'''


class SiteManagePage:
    """站点管理独立页"""

    def __init__(self):
        self.page = None
        self.config_file = resolve_data_file("站点配置.json",
                                             copy_default_from_resource_if_missing=True)
        self.configs = []
        self.selected_index = -1
        # 探测结果缓存 {域名: probe dict}
        self._probe_results = {}
        self._probing = set()
        # P2-4: 近24h 风控事件聚合缓存 (懒加载, _refresh 时失效)
        self._risk_summary_cache = None
        # UI 引用
        self._table_view = None
        self._edit_card = None
        self._info_text = None
        # 适配器插件区 UI
        self._adapter_view = None
        self._adapter_info = None
        self._adapter_card = None
        self._adapter_sig = None
        # 编辑表单字段
        self._domain_field = None
        self._pattern_field = None
        self._chapter_regex_field = None
        self._selectors_field = None
        self._anti_field = None
        self._save_btn = None
        self.file_picker = None  # Flet 0.86 FilePicker 是 Service, 页面构建时实例化

    # ------------------------------------------------------------- 配置读写
    def _load_configs(self) -> list:
        """加载配置: JSON 优先, 回退内置 SITE_PATTERNS"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        try:
            sys.path.insert(0, _HERE)
            from sites_config import SITE_PATTERNS
            return [dict(p) for p in SITE_PATTERNS]
        except Exception:
            return []

    def _save_configs(self) -> bool:
        """保存配置到 JSON (先过滤不可序列化的内置函数字段)"""
        try:
            from pathlib import Path
            cleaned = _json_clean(self.configs)
            Path(self.config_file).write_text(
                json.dumps(cleaned, ensure_ascii=False, indent=2),
                encoding='utf-8')
            return True
        except Exception as e:
            _log("站点管理", f"保存配置失败: {e}")
            return False

    # ------------------------------------------------------------------ UI
    def build(self) -> ft.Control:
        """构建站点管理页"""
        self.configs = self._load_configs()
        # Flet 0.86: FilePicker 是 Service (非 Control), 页面上下文中实例化即可,
        # 不能 overlay.append (会报 "Unknown control: FilePicker"), 通过 await pick_files 调用
        self.file_picker = ft.FilePicker()

        # 工具栏
        add_btn = filled_btn("新增站点", icon=ft.Icons.ADD,
                             on_click=self._on_add_click)
        probe_all_btn = tonal_btn("全部测试", icon=ft.Icons.NETWORK_CHECK,
                                  on_click=self._on_probe_all_click,
                                  tooltip="探测全部站点连接状态")
        import_btn = tonal_btn("导入", icon=ft.Icons.UPLOAD_FILE,
                               on_click=self._on_import_click,
                               tooltip="从 JSON 文件导入站点配置")
        export_btn = tonal_btn("导出", icon=ft.Icons.DOWNLOAD,
                               on_click=self._on_export_click,
                               tooltip="导出全部站点配置为 JSON")
        self._info_text = ft.Text("", size=SIZE_SMALL, weight=WEIGHT_BODY,
                                  color=ft.Colors.ON_SURFACE_VARIANT,
                                  font_family=FONT_STACK)

        toolbar = make_card(
            ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.DNS_OUTLINED, size=18,
                            color=MORANDI_ACCENT),
                    ft.Text("站点管理", size=SIZE_TITLE, weight=WEIGHT_TITLE,
                            font_family=FONT_STACK),
                ], spacing=6),
                ft.Row([add_btn, probe_all_btn, import_btn, export_btn],
                       spacing=6, wrap=True),
                self._info_text,
            ], spacing=8),
            padding=10,
        )

        # 站点适配插件卡 (免重新打包扩展新站)
        adapter_card = self._build_adapter_card()

        # 站点表格 (4 主列 + 操作列)
        self._table_view = ft.ListView(expand=True, spacing=3, auto_scroll=True)
        table_card = make_card(
            ft.Container(content=self._table_view, expand=True),
            expand=True, padding=6,
        )

        # 底部编辑卡 (默认隐藏, 点编辑图标展开)
        self._build_edit_card()

        self._refresh_table()
        banner = self._build_alarm_banner()
        return ft.Column([banner, toolbar, adapter_card, table_card, self._edit_card],
                         expand=True, spacing=10)

    def _build_alarm_banner(self):
        """P1-3: 顶部风控告警横幅 (24h 高反爬命中 + 改版漂移告警), 无告警时空。

        数据源: 风控事件 JSONL (content_issue=漂移检测告警; anti 聚合=高命中域)。
        """
        lines = []
        try:
            import 风控事件 as _ev
            # 1) 漂移/改版告警 (content_issue 事件最近 3 条)
            import os, json, time as _t
            d = os.path.join(get_app_base_dir(), "数据")
            files = sorted([os.path.join(d, f) for f in os.listdir(d)
                            if f.startswith("风控事件-")]) if os.path.isdir(d) else []
            cutoff = _t.time() - 24 * 3600
            hits = []
            for fp in files[-2:]:
                try:
                    with open(fp, encoding="utf-8") as fh:
                        for ln in fh:
                            ln = ln.strip()
                            if 'content_issue' not in ln:
                                continue
                            rec = json.loads(ln)
                            try:
                                ts = _t.mktime(_t.strptime(rec.get("t", ""), "%Y-%m-%d %H:%M:%S"))
                            except Exception:
                                continue
                            if ts >= cutoff:
                                hits.append(rec.get("告警") or rec.get("域名", ""))
                except Exception:
                    continue
            for h in hits[-3:]:
                if h and h not in lines:
                    lines.append(h[:90])
            # 2) 24h 高反爬命中域 (rate_limit/blocked 或 >=3 次)
            agg = _ev.summary_by_domain(24)
            for dom, s in sorted(agg.items()):
                anti = s.get("anti", {})
                if anti.get("blocked", 0) or anti.get("rate_limit", 0) or sum(anti.values()) >= 3:
                    top = max(anti, key=anti.get)
                    lines.append(f"风控 {dom}: {top}×{anti[top]}")
        except Exception:
            return ft.Container()
        if not lines:
            return ft.Container()
        return ft.Container(
            content=ft.Column([ft.Text("⚠ " + ln, size=12, color=MORANDI_ERROR,
                                       font_family=FONT_STACK) for ln in lines[:5]],
                              spacing=3),
            bgcolor=ft.Colors.ERROR_CONTAINER, border_radius=8, padding=8, margin=0,
        )

    def _build_edit_card(self):
        """底部编辑卡 (新增/编辑共用)"""
        self._domain_field = ft.TextField(
            label="域名", width=240, dense=True,
            text_style=ft.TextStyle(size=SIZE_BODY, font_family=FONT_STACK))
        self._pattern_field = ft.Dropdown(
            label="解析模式", width=240, dense=True,
            text_style=ft.TextStyle(size=SIZE_BODY, font_family=FONT_STACK),
            options=[
                ft.dropdown.Option("qsbs_bb", "qsbs_bb (Base64加密)"),
                ft.dropdown.Option("ajax_two_step", "ajax_two_step (动态加载)"),
                ft.dropdown.Option("html_selector", "html_selector (选择器)"),
                ft.dropdown.Option("selenium", "selenium (浏览器渲染)"),
                ft.dropdown.Option("str_decode_bb", "str_decode_bb (Base64解码)"),
            ])
        self._chapter_regex_field = ft.TextField(
            label="章节URL正则", width=340, dense=True,
            text_style=ft.TextStyle(size=SIZE_BODY, font_family=FONT_STACK))
        self._selectors_field = ft.TextField(
            label="正文选择器 (逗号分隔)", width=340, dense=True,
            text_style=ft.TextStyle(size=SIZE_BODY, font_family=FONT_STACK))
        self._anti_field = ft.TextField(
            label="反爬类型 (auto=自动识别)", width=200, dense=True,
            text_style=ft.TextStyle(size=SIZE_BODY, font_family=FONT_STACK))

        self._save_btn = filled_btn("保存", icon=ft.Icons.SAVE,
                                    on_click=self._on_save_edit)
        cancel_btn = text_btn("取消", on_click=lambda e: self._hide_edit())

        self._edit_card = make_card(
            ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.EDIT_OUTLINED, size=16,
                            color=MORANDI_ACCENT),
                    ft.Text("站点编辑", size=SIZE_BODY, weight=WEIGHT_SUBTITLE,
                            font_family=FONT_STACK),
                ], spacing=6),
                ft.Row([self._domain_field, self._pattern_field,
                        self._anti_field], wrap=True, spacing=6),
                ft.Row([self._chapter_regex_field, self._selectors_field],
                       wrap=True, spacing=6),
                ft.Row([self._save_btn, cancel_btn], spacing=6),
            ], spacing=8),
            padding=10, visible=False,
        )

    # ------------------------------------------------------------ 适配器插件区
    def _build_adapter_card(self) -> ft.Control:
        """站点适配插件卡: 列表 + 新建/打开目录/刷新"""
        new_btn = filled_btn("新建适配器", icon=ft.Icons.ADD_BOX_OUTLINED,
                             on_click=self._on_new_adapter_click,
                             tooltip="生成一个适配器模板 .py (免重新打包)")
        open_btn = tonal_btn("打开目录", icon=ft.Icons.FOLDER_OPEN,
                             on_click=self._on_open_adapter_dir,
                             tooltip="打开 站点适配/ 文件夹")
        refresh_btn = tonal_btn("刷新", icon=ft.Icons.REFRESH,
                                on_click=self._on_refresh_adapters,
                                tooltip="重新加载插件列表")
        self._adapter_info = ft.Text("", size=SIZE_SMALL,
                                     color=ft.Colors.ON_SURFACE_VARIANT,
                                     font_family=FONT_STACK)
        self._adapter_view = ft.Column(spacing=4)
        self._adapter_card = make_card(
            ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.EXTENSION_OUTLINED, size=18,
                            color=MORANDI_ACCENT),
                    ft.Text("站点适配插件 (免重新打包)", size=SIZE_TITLE,
                            weight=WEIGHT_TITLE, font_family=FONT_STACK),
                ], spacing=6),
                ft.Row([new_btn, open_btn, refresh_btn], spacing=6, wrap=True),
                self._adapter_info,
                self._adapter_view,
            ], spacing=8),
            padding=10,
        )
        self._render_adapters()
        return self._adapter_card

    def _adapter_status(self) -> list:
        """返回适配器状态列表 [{file, domain, catalog, content, paginate, error}]"""
        out = []
        adapter_dir = os.path.join(get_app_base_dir(), "站点适配")
        if not os.path.isdir(adapter_dir):
            return out
        try:
            from sites_config import load_adapters, ADAPTERS
            load_adapters()
            files = sorted(f for f in os.listdir(adapter_dir)
                           if f.endswith('.py') and not f.startswith('_'))
            for fn in files:
                domain, catalog, content, paginate, error = '', False, False, False, ''
                for d, entry in ADAPTERS.items():
                    if entry.get('source', '').replace('\\', '/').endswith('/' + fn):
                        domain = d
                        catalog = bool(entry.get('parse_catalog'))
                        content = bool(entry.get('extract_content'))
                        paginate = bool(entry.get('paginate'))
                        break
                if not domain:
                    error = '加载失败或未注册'
                out.append({'file': fn, 'domain': domain, 'catalog': catalog,
                            'content': content, 'paginate': paginate, 'error': error})
        except Exception as ex:
            _log("站点管理", f"读取插件状态失败: {ex}")
        return out

    def _render_adapters(self, force: bool = False):
        """重建插件列表 (签名比对跳过无变化重建)"""
        if self._adapter_view is None:
            return
        statuses = self._adapter_status()
        sig = tuple((s['file'], s['domain'], s['catalog'], s['content'],
                     s['paginate']) for s in statuses)
        if not force and sig == getattr(self, '_adapter_sig', None):
            return
        self._adapter_sig = sig
        self._adapter_view.controls.clear()
        if not statuses:
            self._adapter_view.controls.append(
                ft.Text("无插件 · 目录为空 (点“新建适配器”或“打开目录”)",
                        size=SIZE_TINY, color=ft.Colors.ON_SURFACE_VARIANT,
                        font_family=FONT_STACK))
            return
        for st in statuses:
            caps = []
            if st['catalog']:
                caps.append("目录")
            if st['content']:
                caps.append("正文")
            if st['paginate']:
                caps.append("分页")
            cap_text = '/'.join(caps) if caps else "仅配置"
            ok = bool(st['domain'])
            del_btn = ft.IconButton(
                icon=ft.Icons.DELETE_OUTLINE, icon_size=14,
                tooltip=f"删除 {st['file']}",
                on_click=lambda e, f=st['file']: self._on_delete_adapter(f),
                style=ft.ButtonStyle(
                    padding=2, shape=ft.RoundedRectangleBorder(radius=6),
                    bgcolor=ft.Colors.ERROR_CONTAINER,
                    color=ft.Colors.ON_ERROR_CONTAINER))
            self._adapter_view.controls.append(ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.TERMINAL if ok else ft.Icons.ERROR_OUTLINE,
                            size=14,
                            color=MORANDI_SUCCESS if ok else MORANDI_ERROR),
                    ft.Text(st['file'], size=SIZE_SMALL, weight=WEIGHT_SUBTITLE,
                            color=(MORANDI_SECONDARY if ok else MORANDI_ERROR),
                            font_family=FONT_STACK, max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(st['domain'] or (st['error'] or '—'),
                            size=SIZE_TINY, color=ft.Colors.ON_SURFACE_VARIANT,
                            font_family=FONT_STACK),
                    ft.Text(cap_text, size=SIZE_TINY, color=MORANDI_ACCENT,
                            font_family=FONT_STACK),
                    ft.Container(expand=True),
                    del_btn,
                ], spacing=6),
                padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                border_radius=6,
                bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            ))

    def _page_update(self):
        if self.page is not None:
            try:
                self.page.update()
            except Exception:
                pass

    def _on_new_adapter_click(self, e):
        """新建适配器: 弹窗输入域名, 生成模板 .py"""
        if self.page is None:
            return
        domain_field = ft.TextField(label="域名 (如 example.com)", dense=True, width=280,
                                    text_style=ft.TextStyle(size=SIZE_BODY,
                                                            font_family=FONT_STACK))
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("新建适配器模板"),
            content=ft.Column([domain_field], spacing=6, tight=True, width=320),
            actions=[
                ft.TextButton("取消",
                              on_click=lambda _: close_dialog(self.page, dialog)),
                ft.TextButton("生成",
                              on_click=lambda _: self._do_create_adapter(dialog, domain_field)),
            ],
        )
        open_dialog(self.page, dialog)

    def _do_create_adapter(self, dialog, field):
        """生成适配器模板文件 (按域名命名)"""
        if self.page is not None:
            try:
                close_dialog(self.page, dialog)
            except Exception:
                pass
        domain = (field.value or '').strip().lower()
        if not domain:
            self._adapter_info.value = "域名不能为空"
            self._page_update()
            return
        fname = re.sub(r'[^\w.-]', '_', domain) + '.py'
        adapter_dir = os.path.join(get_app_base_dir(), "站点适配")
        try:
            os.makedirs(adapter_dir, exist_ok=True)
            path = os.path.join(adapter_dir, fname)
            if os.path.exists(path):
                self._adapter_info.value = f"已存在: {fname}"
                self._page_update()
                return
            logname = domain.replace('.', '_')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(_ADAPTER_TEMPLATE.format(domain=domain, logname=logname))
            self._adapter_info.value = f"已生成 {fname} (请编辑函数, 点“刷新”生效)"
            _log("站点管理", f"新建适配器: {path}")
        except Exception as ex:
            self._adapter_info.value = f"生成失败: {ex}"
        self._render_adapters(force=True)
        self._page_update()

    def _on_open_adapter_dir(self, e):
        """打开 站点适配/ 文件夹 (Windows 资源管理器)"""
        adapter_dir = os.path.join(get_app_base_dir(), "站点适配")
        try:
            os.makedirs(adapter_dir, exist_ok=True)
            os.startfile(adapter_dir)
        except Exception as ex:
            self._info_text.value = f"打开目录失败: {ex}"
            self._page_update()

    def _on_refresh_adapters(self, e):
        """重新加载插件 (清缓存 + 重扫目录)"""
        try:
            from sites_config import reload_adapters
            reload_adapters()
            self._adapter_info.value = "插件已刷新"
        except Exception as ex:
            self._adapter_info.value = f"刷新失败: {ex}"
        self._render_adapters(force=True)
        self._page_update()

    def _on_delete_adapter(self, fname: str):
        """删除适配器文件"""
        path = os.path.join(get_app_base_dir(), "站点适配", fname)
        try:
            if os.path.exists(path):
                os.remove(path)
                self._adapter_info.value = f"已删除 {fname}"
            else:
                self._adapter_info.value = f"文件不存在: {fname}"
        except Exception as ex:
            self._adapter_info.value = f"删除失败: {ex}"
        self._render_adapters(force=True)
        self._page_update()

    # ------------------------------------------------------------ 表格渲染
    def _health_of(self, cfg: dict) -> str:
        """站点健康度: 爬取历史成功率 (无记录返回空)"""
        domain = cfg.get('domain', '')
        stats = self._site_stats.get(domain)
        if not stats:
            return ""
        total = sum(v for k, v in stats.items() if k != '总请求数')
        fail = stats.get('失败', 0)
        if total <= 0:
            return ""
        return f"{(total - fail) * 100 // total}%"

    def _domain_risk(self, domain: str) -> dict:
        """P2-4: 近 24h 该域风控事件 {total, types:{type:n}} (读 风控事件 JSONL, 懒缓存)。"""
        if self._risk_summary_cache is None:
            try:
                import 风控事件 as _risk_ev
                self._risk_summary_cache = _risk_ev.summary_by_domain(24)
            except Exception:
                self._risk_summary_cache = {}
        agg = (self._risk_summary_cache or {}).get(domain)
        if not agg or not agg.get("anti"):
            return {"total": 0, "types": {}}
        return {"total": sum(agg["anti"].values()), "types": agg["anti"]}

    @property
    def _site_stats(self) -> dict:
        """{域名: 统计dict} (爬取历史)"""
        cached = getattr(self, '_site_stats_cache', None)
        if cached is not None:
            return cached
        result = {}
        for s in history_data.list_sites_summary():
            if s.get('域名'):
                result[s['域名']] = s.get('统计', {})
        self._site_stats_cache = result
        return result

    def _refresh_table(self):
        """重建站点表格 (主线程)"""
        self._site_stats_cache = None  # 清缓存
        self._risk_summary_cache = None  # P2-4: 风控聚合缓存失效 (刷新即重读)
        if self._table_view is None:
            return
        self._table_view.controls.clear()

        if not self.configs:
            self._table_view.controls.append(
                ft.Container(
                    content=ft.Column([
                        ft.Icon(ft.Icons.DNS_OUTLINED, size=40,
                                color=ft.Colors.ON_SURFACE_VARIANT, opacity=0.5),
                        ft.Text("暂无站点配置", size=SIZE_LABEL,
                                color=ft.Colors.ON_SURFACE_VARIANT,
                                font_family=FONT_STACK),
                    ], spacing=8,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=ft.Padding.symmetric(vertical=40),
                ))
            return

        # 表头
        def _h(t, flex, center=False):
            return ft.Container(
                content=ft.Text(t, size=SIZE_TINY, weight=WEIGHT_SUBTITLE,
                                color=ft.Colors.ON_SURFACE_VARIANT,
                                font_family=FONT_STACK),
                expand=flex, alignment=ft.Alignment(-1, 0))
        self._table_view.controls.append(ft.Row([
            _h("域名", 26), _h("模式", 14), _h("状态", 30),
            _h("启用", 10), _h("", 20),
        ], spacing=6))

        for i, cfg in enumerate(self.configs):
            self._table_view.controls.append(self._build_site_row(i, cfg))

    def _build_site_row(self, idx: int, cfg: dict) -> ft.Control:
        """单行站点: 域名 | 模式 | 状态 | 启用 | 操作"""
        domain = cfg.get('domain', '未知')
        enabled = cfg.get('enabled', True)
        pattern = cfg.get('pattern', '—')

        # 状态列: 健康度 · 反爬 · 探测结果 (合并为一个单元)
        parts = []
        health = self._health_of(cfg)
        if health:
            # 健康度为 "NN%" 字符串, 需转数值比较 (字符串比较会使 100% < 80%)
            hval = int(health.rstrip('%')) if health.rstrip('%').isdigit() else 0
            hcolor = (MORANDI_SUCCESS if hval >= 80
                      else MORANDI_WARNING if hval >= 50
                      else MORANDI_ERROR)
            parts.append((health, hcolor))
        prior = history_data.site_prior(domain)
        anti_seen = prior.get('反爬统计', {}) if isinstance(prior, dict) else {}
        # P2-4: 近 24h 风控事件优先展示 (rate_limit/blocked 用错误色)
        risk = self._domain_risk(domain)
        if risk["total"]:
            top = max(risk["types"], key=risk["types"].get)
            rcolor = MORANDI_ERROR if top in ("rate_limit", "blocked") else MORANDI_WARNING
            parts.append((f"风控24h:{top}×{risk['types'][top]}", rcolor))
        elif anti_seen:
            top_anti = max(anti_seen, key=anti_seen.get)
            parts.append((f"反爬:{top_anti}", MORANDI_WARNING))
        probe = self._probe_results.get(domain)
        if probe:
            if probe.get('ok'):
                parts.append((f"探测 {probe['status_code']}/{probe['elapsed']}s",
                              MORANDI_SUCCESS))
            else:
                parts.append((f"探测失败 {probe.get('status_code') or 'X'}",
                              MORANDI_ERROR))
        if not parts:
            parts.append(("无记录", None))
        status_row = ft.Row([
            ft.Text(t, size=SIZE_TINY, weight=WEIGHT_BODY, color=c,
                    font_family=FONT_STACK)
            for t, c in parts[:2]
        ], spacing=6)

        # 启用开关
        switch = ft.Switch(
            value=enabled,
            active_color=MORANDI_SUCCESS,
            on_change=lambda e, i=idx: self._on_toggle_enabled(i, e),
        )

        # 操作: 测试 / 编辑 / 删除
        probe_btn = ft.IconButton(
            icon=ft.Icons.WIFI_TETHERING, icon_size=14,
            tooltip="测试连接 (探测站点状态)",
            on_click=lambda e, i=idx: self._on_probe_site(i),
            style=ft.ButtonStyle(
                padding=2, shape=ft.RoundedRectangleBorder(radius=6),
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH))
        edit_btn = ft.IconButton(
            icon=ft.Icons.EDIT_OUTLINED, icon_size=14,
            tooltip="编辑站点配置",
            on_click=lambda e, i=idx: self._on_edit_site(i),
            style=ft.ButtonStyle(
                padding=2, shape=ft.RoundedRectangleBorder(radius=6),
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH))
        del_btn = ft.IconButton(
            icon=ft.Icons.DELETE_OUTLINE, icon_size=14,
            tooltip="删除站点",
            on_click=lambda e, i=idx: self._on_delete_site(i),
            style=ft.ButtonStyle(
                padding=2, shape=ft.RoundedRectangleBorder(radius=6),
                bgcolor=ft.Colors.ERROR_CONTAINER,
                color=ft.Colors.ON_ERROR_CONTAINER))

        def _cell(content, flex):
            return ft.Container(content=content, expand=flex,
                                alignment=ft.Alignment(-1, 0))

        return ft.Container(
            content=ft.Row([
                _cell(ft.Text(domain, size=SIZE_SMALL, weight=WEIGHT_SUBTITLE,
                              color=(ft.Colors.ON_SURFACE_VARIANT if not enabled
                                     else MORANDI_SECONDARY),
                              font_family=FONT_STACK, max_lines=1,
                              overflow=ft.TextOverflow.ELLIPSIS), 26),
                _cell(ft.Text(pattern, size=SIZE_TINY, font_family=FONT_STACK,
                              color=ft.Colors.ON_SURFACE_VARIANT,
                              max_lines=1), 14),
                _cell(status_row, 30),
                _cell(ft.Row([switch], alignment=ft.MainAxisAlignment.CENTER), 10),
                _cell(ft.Row([probe_btn, edit_btn, del_btn], spacing=2,
                             alignment=ft.MainAxisAlignment.CENTER), 20),
            ], spacing=6),
            padding=ft.Padding.symmetric(horizontal=8, vertical=4),
            border_radius=6,
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            opacity=0.6 if not enabled else 1.0,
        )

    # ------------------------------------------------------------- 交互回调
    def _dispatch(self, fn):
        """提交 UI 更新到主线程"""
        if self.page is None:
            return
        try:
            async def _runner():
                fn()
                try:
                    self.page.update()
                except Exception:
                    pass
            self.page.run_task(_runner)
        except Exception:
            pass

    def _on_toggle_enabled(self, idx: int, e):
        """启用/禁用站点 (写入 enabled 字段)"""
        if not (0 <= idx < len(self.configs)):
            return
        cfg = self.configs[idx]
        cfg['enabled'] = not cfg.get('enabled', True)
        ok = self._save_configs()
        state = "启用" if cfg['enabled'] else "禁用"
        self._info_text.value = (f"{cfg.get('domain')}: 已{state}并保存"
                                  if ok else f"保存失败: {cfg.get('domain')}")
        _log("站点管理", f"{cfg.get('domain')} → {state}")
        self._refresh_table()
        try:
            e.page.update()
        except Exception:
            pass

    def _on_probe_site(self, idx: int):
        """测试连接 (后台线程探测)"""
        if not (0 <= idx < len(self.configs)):
            return
        domain = self.configs[idx].get('domain', '')
        if not domain or domain in self._probing:
            return
        self._probing.add(domain)
        self._info_text.value = f"正在探测 {domain} ..."
        try:
            self.page.update()
        except Exception:
            pass

        def _worker():
            try:
                from site_probe import probe_site, normalize_site_url
                result = probe_site(normalize_site_url(domain))
            except Exception as ex:
                result = {'ok': False, 'status_code': 0, 'elapsed': 0,
                          'error': str(ex)[:120], 'engine': '', 'engine_chain': [],
                          'anti_spider': 'none', 'anti_evidence': ''}
            self._probing.discard(domain)
            self._probe_results[domain] = result
            anti = result.get('anti_spider', 'none')
            anti_tip = f", 反爬:{anti}" if anti != 'none' else ""
            if result['ok']:
                msg = (f"{domain}: 连接正常 HTTP {result['status_code']} "
                       f"({result['elapsed']}s, {result['engine'] or 'requests'}){anti_tip}")
            else:
                msg = (f"{domain}: 探测失败 "
                       f"({result.get('error') or '无响应'}){anti_tip}")
            _log("站点探测", msg)

            def _ui():
                self._info_text.value = msg
                self._refresh_table()
            self._dispatch(_ui)

        threading.Thread(target=_worker, daemon=True,
                          name=f"probe-{domain}").start()

    def _on_probe_all_click(self, e):
        """全部测试 (逐站点后台探测)"""
        for i in range(len(self.configs)):
            self._on_probe_site(i)

    def _on_edit_site(self, idx: int):
        """编辑站点: 填充底部编辑卡并展开"""
        if not (0 <= idx < len(self.configs)):
            return
        self.selected_index = idx
        cfg = self.configs[idx]
        self._domain_field.value = cfg.get('domain', '')
        self._pattern_field.value = cfg.get('pattern', '')
        self._chapter_regex_field.value = cfg.get('chapter_url_regex', '')
        selectors = cfg.get('content_selectors', [])
        self._selectors_field.value = (', '.join(selectors)
                                      if isinstance(selectors, list) else str(selectors))
        anti = cfg.get('anti_spider', {})
        self._anti_field.value = (anti.get('type', '') if isinstance(anti, dict)
                                  else str(anti))
        self._edit_card.visible = True
        try:
            self.page.update()
        except Exception:
            pass

    def _on_add_click(self, e):
        """新增站点: 展开空白编辑卡"""
        self.selected_index = -1
        self._domain_field.value = "new-site.com"
        self._pattern_field.value = "html_selector"
        self._chapter_regex_field.value = ""
        self._selectors_field.value = "#content"
        self._anti_field.value = "auto"
        self._edit_card.visible = True
        self._info_text.value = "新增站点: 填写后点击保存"
        try:
            e.page.update()
        except Exception:
            pass

    def _hide_edit(self):
        self._edit_card.visible = False
        try:
            self.page.update()
        except Exception:
            pass

    def _on_save_edit(self, e):
        """保存编辑卡内容 (新增或更新)"""
        domain = (self._domain_field.value or '').strip()
        if not domain:
            self._info_text.value = "域名不能为空"
            try:
                self.page.update()
            except Exception:
                pass
            return
        entry = {
            'domain': domain,
            'pattern': self._pattern_field.value or 'html_selector',
            'content_selectors': [s.strip() for s in
                                  (self._selectors_field.value or '').split(',')
                                  if s.strip()],
        }
        if self._chapter_regex_field.value:
            entry['chapter_url_regex'] = self._chapter_regex_field.value.strip()
        anti = (self._anti_field.value or '').strip()
        if anti:
            entry['anti_spider'] = {'type': anti}

        if 0 <= self.selected_index < len(self.configs):
            # 更新: 保留原有其他字段 (分页/enabled 等)
            old = self.configs[self.selected_index]
            old.update(entry)
            self._info_text.value = f"已更新: {domain}"
        else:
            self.configs.append(entry)
            self._info_text.value = f"已新增: {domain} (保存后生效)"

        if self._save_configs():
            self._info_text.value += " 并写入 站点配置.json"
            _log("站点管理", self._info_text.value)
        self._hide_edit()
        self._refresh_table()
        try:
            self.page.update()
        except Exception:
            pass

    def _on_delete_site(self, idx: int):
        """删除站点 (从 JSON 配置移除; 内置站点下次仍会用内置默认)"""
        if not (0 <= idx < len(self.configs)):
            return
        domain = self.configs[idx].get('domain', '')
        self.configs.pop(idx)
        if self._save_configs():
            self._info_text.value = f"已删除: {domain} (内置站点将回退默认配置)"
            _log("站点管理", self._info_text.value)
        self._refresh_table()
        try:
            self.page.update()
        except Exception:
            pass

    async def _on_import_click(self, e):
        """导入站点配置: 支持 JSON 配置文件 或 txt 网址清单 (每行一个URL)"""
        if self.page is None or self.file_picker is None:
            self._info_text.value = "文件选择器未就绪"
            return
        try:
            files = await self.file_picker.pick_files(
                allow_multiple=False,
                allowed_extensions=["json", "txt"],
                dialog_title="选择站点配置 JSON 或网址清单 txt (每行一个URL)",
            )
        except Exception as ex:
            self._info_text.value = f"打开文件选择器失败: {ex}"
            try:
                self.page.update()
            except Exception:
                pass
            return
        if not files:
            return  # 用户取消
        path = files[0].path
        try:
            ext = os.path.splitext(path)[1].lower()
            if ext == '.json':
                with open(path, 'r', encoding='utf-8') as f:
                    items = json.load(f)
                if not isinstance(items, list):
                    raise ValueError("格式错误: 期望 JSON 数组")
                added = self._merge_configs(items)
            else:
                added = self._import_from_urls_file(path)
            if self._save_configs():
                self._info_text.value = f"导入完成: 新增 {added} 条, 跳过已存在"
                self._refresh_table()
            else:
                self._info_text.value = "保存失败, 请检查权限"
        except Exception as ex:
            self._info_text.value = f"导入失败: {ex}"
        try:
            self.page.update()
        except Exception:
            pass

    def _merge_configs(self, items: list) -> int:
        """按域名合并导入配置条目, 返回新增数"""
        existing = {c.get('domain') for c in self.configs}
        added = 0
        for item in items:
            if isinstance(item, dict) and item.get('domain') \
                    and item['domain'] not in existing:
                self.configs.append(item)
                existing.add(item['domain'])
                added += 1
        return added

    def _import_from_urls_file(self, path: str) -> int:
        """从 txt 网址清单导入: 每行一个 URL, 提取域名生成站点配置

        去重/物化规则:
        - 已被当前配置覆盖 (自身或子域, 如 m.banlvzw.com 命中 banlvzw.com) → 跳过
        - 命中内置 SITE_PATTERNS 但配置里还没有 → 复制内置可序列化字段进配置
          (使该站点在站点管理页可见; 函数型字段如自定义分页由运行时合并保留)
        - 全新域名 → 生成默认 html_selector 配置
        """
        from urllib.parse import urlparse
        raw = None
        for enc in ('utf-8', 'gbk'):
            try:
                with open(path, encoding=enc) as f:
                    raw = f.read()
                break
            except UnicodeDecodeError:
                continue
        if raw is None:
            return 0

        # 当前配置已有域名 (自身/子域覆盖判断)
        existing = {c.get('domain') for c in self.configs if c.get('domain')}
        # 内置 SITE_PATTERNS 按域名索引 (用于把内置站点物化进配置)
        builtin_by_domain = {}
        try:
            from sites_config import SITE_PATTERNS
            builtin_by_domain = {p.get('domain'): p for p in SITE_PATTERNS
                                 if p.get('domain')}
        except Exception:
            pass

        def _covered_by(host: str, domains) -> bool:
            """host 是否已被某域名覆盖 (自身或主域子域)"""
            for d in domains:
                if not d:
                    continue
                if host == d or host.endswith('.' + d):
                    return True
            return False

        def _serializable(pattern: dict) -> dict:
            """从内置模式提取可 JSON 序列化字段 (丢弃函数型字段如自定义分页)"""
            out = {k: v for k, v in pattern.items() if _is_jsonable(v)}
            return out

        added = 0
        for line in (raw or '').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            url = line if '://' in line else 'https://' + line
            try:
                host = (urlparse(url).hostname or '').lower()
            except Exception:
                host = ''
            # 去掉 www. 前缀 (与内置站点 domain 规范一致)
            if host.startswith('www.'):
                host = host[4:]
            if not host:
                continue
            # 已被当前配置覆盖 (自身或子域) → 跳过
            if _covered_by(host, existing):
                continue
            # 内置站点子域 (如 m.xx.com 命中内置 xx.com) 且配置未收录 → 跳过
            if host not in builtin_by_domain and _covered_by(host, builtin_by_domain):
                continue
            # 命中内置站点 (精确) 但配置里还没有 → 物化内置可序列化字段
            if host in builtin_by_domain:
                entry = _serializable(builtin_by_domain[host])
                entry['domain'] = host
                entry.setdefault('enabled', True)
                self.configs.append(entry)
                existing.add(host)
                added += 1
                continue
            # 全新域名 → 生成默认配置
            existing.add(host)
            self.configs.append({
                'domain': host,
                'pattern': 'html_selector',
                'content_selectors': ['#content'],
                'anti_spider': {'type': 'auto'},
                'enabled': True,
            })
            added += 1
        return added

    def _on_export_click(self, e):
        """导出全部配置为 JSON"""
        if self.page is None:
            return
        default_name = f"站点配置备份_{time.strftime('%Y%m%d_%H%M%S')}.json"
        try:
            from pathlib import Path
            export_path = os.path.join(
                os.path.dirname(self.config_file), default_name)
            Path(export_path).write_text(
                json.dumps(self.configs, ensure_ascii=False, indent=2),
                encoding='utf-8')
            self._info_text.value = f"已导出: {export_path}"
            _log("站点管理", f"导出配置 → {export_path}")
        except Exception as ex:
            self._info_text.value = f"导出失败: {ex}"
        try:
            self.page.update()
        except Exception:
            pass

    # 对外刷新入口
    def refresh(self):
        self._refresh_table()
        self._render_adapters()  # 签名比对, 有变化才重建
        if self.page is not None:
            try:
                self.page.update()
            except Exception:
                pass
