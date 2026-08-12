# -*- coding: utf-8 -*-
"""站点配置页签：可视化查看和编辑站点适配配置

配置数据优先从 JSON 文件加载，回退到 sites_config.py 的 SITE_PATTERNS。
修改保存时写入 JSON 文件，不修改 Python 源码。
"""
import flet as ft
import json
import os
import sys

# UI 主题系统
from .ui_theme import make_card, filled_btn, tonal_btn

# 统一字体规范
from .ui_morandi import (FONT_STACK, SIZE_TITLE, SIZE_LABEL, SIZE_BODY,
                         SIZE_SMALL, WEIGHT_TITLE, WEIGHT_SUBTITLE,
                         WEIGHT_BODY, MORANDI_ACCENT)  # noqa: E402


class ConfigTab:
    """站点配置页签组件"""

    def __init__(self):
        # 配置文件位置（PyInstaller 打包友好，经验 1341648）：
        #   - 始终写入 BASE_DIR/站点配置.json（EXE 旁边 / 项目根）
        #   - 若 BASE_DIR 没有，先尝试把 RESOURCE_DIR 下打包的同名默认文件拷出来
        #   - 还不存在则在加载时回退到 sites_config.py 里内置的 SITE_PATTERNS
        try:
            _HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            sys.path.insert(0, _HERE)
            from _path_utils import resolve_data_file
            self.config_file = resolve_data_file("站点配置.json",
                                                  copy_default_from_resource_if_missing=True)
        except Exception:
            # 回退：脚本所在目录下（开发模式）
            script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.config_file = os.path.join(script_dir, "站点配置.json")
        self.configs = self._load_configs()
        self.selected_index = 0
        # UI 元素
        self.site_list_view = None
        self.detail_panel = None
        self.domain_field = None
        self.pattern_field = None
        self.catalog_parser_field = None
        self.chapter_regex_field = None
        self.pagination_suffix_field = None
        self.pagination_start_field = None
        self.pagination_max_field = None
        self.content_selectors_field = None
        self.anti_spider_field = None
        self.info_text = None

    def _load_configs(self) -> list:
        """加载配置：优先JSON文件，回退到SITE_PATTERNS"""
        # 先尝试加载JSON
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass

        # 回退到 sites_config.py
        try:
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from sites_config import SITE_PATTERNS
            # 将配置转为可序列化的列表
            configs = []
            for p in SITE_PATTERNS:
                configs.append(dict(p))
            return configs
        except Exception:
            return []

    def _save_configs(self):
        """保存配置到JSON文件"""
        try:
            from pathlib import Path
            Path(self.config_file).write_text(
                json.dumps(self.configs, ensure_ascii=False, indent=2),
                encoding='utf-8')
            return True
        except Exception as e:
            print(f"保存配置失败: {e}")
            return False

    def build(self) -> ft.Control:
        """构建站点配置页签的完整UI"""
        # 左侧站点列表 (Sidebar 卡片)
        self.site_list_view = ft.ListView(
            expand=True,
            spacing=4,
            auto_scroll=True,
        )

        add_btn = tonal_btn("新增", icon=ft.Icons.ADD, on_click=self.on_add_click)
        reload_btn = tonal_btn("重载", icon=ft.Icons.REFRESH,
                               on_click=self.on_reload_click)
        save_btn = filled_btn("保存", icon=ft.Icons.SAVE,
                              on_click=self.on_save_click)

        site_panel = make_card(
            ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.DNS_OUTLINED, size=18, color=MORANDI_ACCENT),
                    ft.Text("站点列表", size=SIZE_TITLE, weight=WEIGHT_TITLE,
                            font_family=FONT_STACK),
                ]),
                ft.Row([add_btn, reload_btn, save_btn], spacing=6),
                self.site_list_view,
            ], spacing=8),
            width=300,
            expand=True,
        )

        # 右侧配置详情: 分组卡片
        self.domain_field = ft.TextField(label="域名", text_style=ft.TextStyle(size=SIZE_BODY, font_family=FONT_STACK), width=320)
        self.pattern_field = ft.Dropdown(
            label="模式",
            width=240,
            text_style=ft.TextStyle(size=SIZE_BODY, font_family=FONT_STACK),
            options=[
                ft.dropdown.Option("qsbs_bb", "qsbs_bb (Base64加密)"),
                ft.dropdown.Option("ajax_two_step", "ajax_two_step (动态加载)"),
                ft.dropdown.Option("html_selector", "html_selector (选择器)"),
                ft.dropdown.Option("selenium", "selenium (浏览器渲染)"),
                ft.dropdown.Option("str_decode_bb", "str_decode_bb (Base64解码)"),
            ],
        )
        self.catalog_parser_field = ft.TextField(label="目录解析器", text_style=ft.TextStyle(size=SIZE_BODY, font_family=FONT_STACK), width=200)
        self.anti_spider_field = ft.TextField(label="反爬类型", text_style=ft.TextStyle(size=SIZE_BODY, font_family=FONT_STACK), width=200)
        self.chapter_regex_field = ft.TextField(label="章节URL正则", text_style=ft.TextStyle(size=SIZE_BODY, font_family=FONT_STACK), width=420)
        self.pagination_suffix_field = ft.TextField(label="分页后缀", text_style=ft.TextStyle(size=SIZE_BODY, font_family=FONT_STACK), width=140)
        self.pagination_start_field = ft.TextField(label="分页起始页", text_style=ft.TextStyle(size=SIZE_BODY, font_family=FONT_STACK), width=110,
                                                     input_filter=ft.NumbersOnlyInputFilter())
        self.pagination_max_field = ft.TextField(label="最大页数", text_style=ft.TextStyle(size=SIZE_BODY, font_family=FONT_STACK), width=110,
                                                   input_filter=ft.NumbersOnlyInputFilter())
        self.content_selectors_field = ft.TextField(label="正文选择器 (逗号分隔)", text_style=ft.TextStyle(size=SIZE_BODY, font_family=FONT_STACK),
                                                      width=420)
        self.info_text = ft.Text("", size=SIZE_SMALL, weight=WEIGHT_BODY,
                                 color=ft.Colors.ON_SURFACE_VARIANT,
                                 font_family=FONT_STACK)

        def _group_card(title, icon, body):
            return make_card(
                ft.Column([
                    ft.Row([
                        ft.Icon(icon, size=16, color=MORANDI_ACCENT),
                        ft.Text(title, size=SIZE_BODY, weight=WEIGHT_SUBTITLE,
                                font_family=FONT_STACK),
                    ], spacing=6),
                    body,
                ], spacing=8),
                padding=10,
            )

        basic_card = _group_card(
            "基本信息", ft.Icons.INFO_OUTLINE,
            ft.Column([
                ft.Row([self.domain_field, self.pattern_field], wrap=True),
                ft.Row([self.catalog_parser_field, self.anti_spider_field], wrap=True),
            ], spacing=8),
        )
        parse_card = _group_card(
            "解析规则", ft.Icons.ACCOUNT_TREE_OUTLINED,
            ft.Column([
                self.chapter_regex_field,
                self.content_selectors_field,
            ], spacing=8),
        )
        page_card = _group_card(
            "分页设置", ft.Icons.PAGES_OUTLINED,
            ft.Row([self.pagination_suffix_field, self.pagination_start_field,
                    self.pagination_max_field], wrap=True),
        )

        detail_body = ft.Column([
            basic_card,
            parse_card,
            page_card,
            self.info_text,
        ], spacing=10, scroll=ft.ScrollMode.AUTO)
        detail_panel = ft.Container(content=detail_body, expand=True, padding=2)

        # 初始加载
        self._refresh_site_list()
        if self.configs:
            self._load_detail(0)

        return ft.Row([site_panel, detail_panel], expand=True, spacing=10)

    def _refresh_site_list(self):
        """刷新左侧站点列表"""
        self.site_list_view.controls.clear()
        if not self.configs:
            self.site_list_view.controls.append(
                ft.Text("暂无配置", size=SIZE_BODY, weight=WEIGHT_BODY,
                        color=ft.Colors.ON_SURFACE_VARIANT, italic=True,
                        font_family=FONT_STACK)
            )
            return

        for i, cfg in enumerate(self.configs):
            domain = cfg.get('domain', '未知')
            pattern = cfg.get('pattern', '未知')
            is_selected = (i == self.selected_index)

            item = ft.Container(
                content=ft.Column([
                    ft.Text(domain, size=SIZE_LABEL, weight=WEIGHT_SUBTITLE,
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                            font_family=FONT_STACK),
                    ft.Text(pattern, size=SIZE_SMALL, weight=WEIGHT_BODY,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                            font_family=FONT_STACK),
                ], spacing=2),
                padding=ft.Padding.symmetric(horizontal=10, vertical=6),
                border_radius=8,
                bgcolor=ft.Colors.PRIMARY_CONTAINER if is_selected
                else ft.Colors.SURFACE_CONTAINER_LOW,
                ink=True,
                on_click=lambda e, idx=i: self._on_site_selected(idx),
            )
            self.site_list_view.controls.append(item)

    def _on_site_selected(self, idx: int):
        """选中站点后加载配置到详情面板"""
        self._save_current_detail()
        self.selected_index = idx
        self._load_detail(idx)
        self._refresh_site_list()

    def _load_detail(self, idx: int):
        """加载指定索引的配置到详情表单"""
        if idx < 0 or idx >= len(self.configs):
            return
        cfg = self.configs[idx]
        self.domain_field.value = cfg.get('domain', '')
        self.pattern_field.value = cfg.get('pattern', '')
        self.catalog_parser_field.value = cfg.get('catalog_parser', '')
        self.chapter_regex_field.value = cfg.get('chapter_url_regex', '')

        pagination = cfg.get('content_pagination', {})
        self.pagination_suffix_field.value = pagination.get('suffix', '')
        self.pagination_start_field.value = str(pagination.get('start', ''))
        self.pagination_max_field.value = str(pagination.get('max_pages', ''))

        selectors = cfg.get('content_selectors', [])
        if isinstance(selectors, list):
            self.content_selectors_field.value = ', '.join(selectors)
        else:
            self.content_selectors_field.value = str(selectors)

        anti_spider = cfg.get('anti_spider', {})
        if isinstance(anti_spider, dict):
            self.anti_spider_field.value = anti_spider.get('type', '')
        else:
            self.anti_spider_field.value = str(anti_spider)

        self.info_text.value = f"当前编辑: 第{idx+1}/{len(self.configs)}个站点"

    def _save_current_detail(self):
        """将当前详情表单的值保存回 configs"""
        if self.selected_index < 0 or self.selected_index >= len(self.configs):
            return
        cfg = self.configs[self.selected_index]
        cfg['domain'] = self.domain_field.value or ''
        cfg['pattern'] = self.pattern_field.value or ''
        cfg['catalog_parser'] = self.catalog_parser_field.value or ''
        cfg['chapter_url_regex'] = self.chapter_regex_field.value or ''

        suffix = self.pagination_suffix_field.value or ''
        start_str = self.pagination_start_field.value or '2'
        max_str = self.pagination_max_field.value or '30'
        if suffix:
            cfg['content_pagination'] = {
                'suffix': suffix,
                'start': int(start_str) if start_str.isdigit() else 2,
                'max_pages': int(max_str) if max_str.isdigit() else 30,
            }
        elif 'content_pagination' in cfg:
            del cfg['content_pagination']

        selectors_str = self.content_selectors_field.value or ''
        if selectors_str:
            cfg['content_selectors'] = [s.strip() for s in selectors_str.split(',') if s.strip()]

        anti_spider_str = self.anti_spider_field.value or ''
        if anti_spider_str:
            cfg['anti_spider'] = {'type': anti_spider_str}

    def on_add_click(self, e):
        """新增站点配置"""
        self._save_current_detail()
        new_cfg = {
            'domain': 'new-site.com',
            'pattern': 'html_selector',
            'catalog_parser': 'generic',
            'content_selectors': ['#content'],
        }
        self.configs.append(new_cfg)
        self.selected_index = len(self.configs) - 1
        self._refresh_site_list()
        self._load_detail(self.selected_index)
        self.info_text.value = f"已新增站点，请编辑后点击保存"
        try:
            e.page.update()
        except Exception:
            pass

    def on_reload_click(self, e):
        """重新加载配置"""
        self.configs = self._load_configs()
        self.selected_index = 0
        self._refresh_site_list()
        if self.configs:
            self._load_detail(0)
        self.info_text.value = "配置已重新加载"
        try:
            e.page.update()
        except Exception:
            pass

    def on_save_click(self, e):
        """保存配置到JSON文件"""
        self._save_current_detail()
        if self._save_configs():
            self.info_text.value = "配置已保存到 站点配置.json"
        else:
            self.info_text.value = "保存失败，请检查权限"
        try:
            e.page.update()
        except Exception:
            pass
