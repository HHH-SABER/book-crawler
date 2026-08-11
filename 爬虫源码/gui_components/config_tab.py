# -*- coding: utf-8 -*-
"""站点配置页签：可视化查看和编辑站点适配配置

配置数据优先从 JSON 文件加载，回退到 sites_config.py 的 SITE_PATTERNS。
修改保存时写入 JSON 文件，不修改 Python 源码。
"""
import flet as ft
import json
import os
import sys


class ConfigTab:
    """站点配置页签组件"""

    def __init__(self):
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
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.configs, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"保存配置失败: {e}")
            return False

    def build(self) -> ft.Control:
        """构建站点配置页签的完整UI"""
        # 左侧站点列表
        self.site_list_view = ft.ListView(
            expand=True,
            spacing=2,
            auto_scroll=True,
        )

        add_btn = ft.ElevatedButton(
            "新增",
            icon=ft.icons.ADD,
            on_click=self.on_add_click,
            text_size=12,
        )
        reload_btn = ft.ElevatedButton(
            "重载",
            icon=ft.icons.REFRESH,
            on_click=self.on_reload_click,
            text_size=12,
        )
        save_btn = ft.ElevatedButton(
            "保存",
            icon=ft.icons.SAVE,
            on_click=self.on_save_click,
            text_size=12,
            style=ft.ButtonStyle(bgcolor=ft.colors.GREEN_100),
        )

        site_panel = ft.Container(
            content=ft.Column([
                ft.Row([ft.Text("站点列表", size=14, weight=ft.FontWeight.BOLD),
                        add_btn, reload_btn, save_btn]),
                self.site_list_view,
            ]),
            width=280,
            padding=10,
            bgcolor=ft.colors.GREY_50,
            border=ft.border.all(1, ft.colors.GREY_300),
            border_radius=5,
            expand=True,
        )

        # 右侧配置详情
        self.domain_field = ft.TextField(label="域名", text_size=12, width=300)
        self.pattern_field = ft.Dropdown(
            label="模式",
            width=150,
            text_size=12,
            options=[
                ft.dropdown.Option("qsbs_bb", "qsbs_bb (Base64加密)"),
                ft.dropdown.Option("ajax_two_step", "ajax_two_step (动态加载)"),
                ft.dropdown.Option("html_selector", "html_selector (选择器)"),
                ft.dropdown.Option("selenium", "selenium (浏览器渲染)"),
                ft.dropdown.Option("str_decode_bb", "str_decode_bb (Base64解码)"),
            ],
        )
        self.catalog_parser_field = ft.TextField(label="目录解析器", text_size=12, width=200)
        self.chapter_regex_field = ft.TextField(label="章节URL正则", text_size=12, width=400)
        self.pagination_suffix_field = ft.TextField(label="分页后缀", text_size=12, width=200)
        self.pagination_start_field = ft.TextField(label="分页起始页", text_size=12, width=100,
                                                     input_filter=ft.NumbersOnlyInputFilter())
        self.pagination_max_field = ft.TextField(label="最大页数", text_size=12, width=100,
                                                   input_filter=ft.NumbersOnlyInputFilter())
        self.content_selectors_field = ft.TextField(label="正文选择器 (逗号分隔)", text_size=12,
                                                      width=400)
        self.anti_spider_field = ft.TextField(label="反爬类型", text_size=12, width=200)
        self.info_text = ft.Text("", size=11, color=ft.colors.GREY_600)

        self.detail_panel = ft.Container(
            content=ft.Column([
                ft.Text("配置详情", size=14, weight=ft.FontWeight.BOLD),
                ft.Row([self.domain_field, self.pattern_field]),
                ft.Row([self.catalog_parser_field, self.anti_spider_field]),
                self.chapter_regex_field,
                ft.Row([self.pagination_suffix_field, self.pagination_start_field,
                        self.pagination_max_field]),
                self.content_selectors_field,
                self.info_text,
            ], scroll=ft.ScrollMode.AUTO),
            expand=True,
            padding=10,
            bgcolor=ft.colors.GREY_50,
            border=ft.border.all(1, ft.colors.GREY_300),
            border_radius=5,
        )

        # 初始加载
        self._refresh_site_list()
        if self.configs:
            self._load_detail(0)

        return ft.Row([site_panel, self.detail_panel], expand=True)

    def _refresh_site_list(self):
        """刷新左侧站点列表"""
        self.site_list_view.controls.clear()
        if not self.configs:
            self.site_list_view.controls.append(
                ft.Text("暂无配置", size=12, color=ft.colors.GREY_500, italic=True)
            )
            return

        for i, cfg in enumerate(self.configs):
            domain = cfg.get('domain', '未知')
            pattern = cfg.get('pattern', '未知')
            is_selected = (i == self.selected_index)

            item = ft.Container(
                content=ft.Column([
                    ft.Text(domain, size=11, weight=ft.FontWeight.BOLD,
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(pattern, size=10, color=ft.colors.GREY_600),
                ]),
                padding=5,
                border=ft.border.all(2, ft.colors.BLUE) if is_selected else ft.border.all(1, ft.colors.GREY_300),
                border_radius=3,
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
