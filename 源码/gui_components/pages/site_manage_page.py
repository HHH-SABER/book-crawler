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
import sys
import threading
import time

_HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from ..ui_theme import make_card, filled_btn, tonal_btn, text_btn
from ..ui_morandi import (FONT_STACK, SIZE_TITLE, SIZE_LABEL, SIZE_SMALL,
                          SIZE_TINY, SIZE_BODY, WEIGHT_TITLE,
                          WEIGHT_SUBTITLE, WEIGHT_BODY,
                          MORANDI_SECONDARY, MORANDI_SUCCESS, MORANDI_ERROR,
                          MORANDI_WARNING, MORANDI_ACCENT)
from . import history_data

try:
    from _path_utils import resolve_data_file
except Exception:
    def resolve_data_file(filename, **kw):
        return os.path.join(_HERE, filename)

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
        # UI 引用
        self._table_view = None
        self._edit_card = None
        self._info_text = None
        # 编辑表单字段
        self._domain_field = None
        self._pattern_field = None
        self._chapter_regex_field = None
        self._selectors_field = None
        self._anti_field = None
        self._save_btn = None

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
        """保存配置到 JSON"""
        try:
            from pathlib import Path
            Path(self.config_file).write_text(
                json.dumps(self.configs, ensure_ascii=False, indent=2),
                encoding='utf-8')
            return True
        except Exception as e:
            _log("站点管理", f"保存配置失败: {e}")
            return False

    # ------------------------------------------------------------------ UI
    def build(self) -> ft.Control:
        """构建站点管理页"""
        self.configs = self._load_configs()

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

        # 站点表格 (4 主列 + 操作列)
        self._table_view = ft.ListView(expand=True, spacing=3, auto_scroll=True)
        table_card = make_card(
            ft.Container(content=self._table_view, expand=True),
            expand=True, padding=6,
        )

        # 底部编辑卡 (默认隐藏, 点编辑图标展开)
        self._build_edit_card()

        self._refresh_table()
        return ft.Column([toolbar, table_card, self._edit_card],
                         expand=True, spacing=10)

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
            hcolor = (MORANDI_SUCCESS if health >= '80%'
                      else MORANDI_WARNING if health >= '50%'
                      else MORANDI_ERROR)
            parts.append((health, hcolor))
        prior = history_data.site_prior(domain)
        anti_seen = prior.get('反爬统计', {}) if isinstance(prior, dict) else {}
        if anti_seen:
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

    def _on_import_click(self, e):
        """导入 JSON 配置文件"""
        if self.page is None:
            return
        picker = ft.FilePicker()
        self.page.overlay.append(picker)

        def _on_result(ev):
            try:
                if not ev.files:
                    return
                path = ev.files[0].path
                with open(path, 'r', encoding='utf-8') as f:
                    items = json.load(f)
                if not isinstance(items, list):
                    raise ValueError("格式错误: 期望 JSON 数组")
                # 按域名合并导入
                existing = {c.get('domain') for c in self.configs}
                added = 0
                for item in items:
                    if isinstance(item, dict) and item.get('domain') \
                            and item['domain'] not in existing:
                        self.configs.append(item)
                        existing.add(item['domain'])
                        added += 1
                if self._save_configs():
                    self._info_text.value = f"导入完成: 新增 {added} 条, 跳过已存在"
                    self._refresh_table()
                    self.page.update()
            except Exception as ex:
                self._info_text.value = f"导入失败: {ex}"
                self.page.update()

        picker.on_result = _on_result
        try:
            self.page.update()
            picker.pick_files(allow_multiple=False,
                              allowed_extensions=["json"],
                              dialog_title="选择站点配置 JSON 文件")
        except Exception as ex:
            self._info_text.value = f"打开文件选择器失败: {ex}"

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
        if self.page is not None:
            try:
                self.page.update()
            except Exception:
                pass
