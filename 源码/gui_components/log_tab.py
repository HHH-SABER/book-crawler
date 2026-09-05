# -*- coding: utf-8 -*-
"""运行日志页 (Fluent 风格, 匹配设计稿 page-log)

工具栏: 来源下拉 + 级别下拉 + 关键词搜索 + 复制/导出/清空;
第二行: 日期下拉 + 刷新 + 打开日志目录 (实际按天浏览日志文件的实用入口)。
查看器: 深色终端风, 行按级别着色 (INFO 浅 / WARNING 黄 / ERROR 红 / DEBUG 灰)。
"""
import os
import re
import sys
import subprocess
from pathlib import Path

import flet as ft

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from _path_utils import get_app_base_dir  # noqa: E402

# UI 主题系统
from .ui_theme import (make_card, tonal_btn, filled_btn, BTN_TEXT_STYLE,
                       LOG_TERMINAL_BG, LOG_TERMINAL_FONT, log_line_color,
                       page_header)

# 统一字体规范
from .ui_morandi import (FONT_STACK, SIZE_LABEL, SIZE_SMALL, SIZE_TINY,
                         SIZE_BODY, WEIGHT_BODY,
                         MORANDI_ERROR, open_dialog)

_MAX_DISPLAY_LINES = 3000   # 大文件只显示尾部 N 行


def get_log_dir() -> str:
    """日志目录（与 日志.py 保持一致）"""
    return os.path.join(get_app_base_dir(), "日志")


def list_log_files() -> list:
    """返回日志目录下所有 .log 文件名（按名称倒序，最新在前）"""
    log_dir = get_log_dir()
    try:
        names = [n for n in os.listdir(log_dir) if n.endswith('.log')]
    except OSError:
        return []
    return sorted(names, reverse=True)

# 行格式: "[01:47:19.984] [INFO] [sites_config] 消息..." → 提取来源字段
_SOURCE_RE = re.compile(r'^\[[^\]]+\]\s*\[[A-Z]+\]\s*\[([^\]]+)\]')


class LogTab:
    """运行日志查看页"""

    def __init__(self):
        self.page = None
        self._built = False
        # 过滤状态
        self._source = '__all__'
        self._level = 'all'
        self._keyword = ''
        # 数据
        self._all_lines = []       # 当前文件的行 (截断后)
        self._sources = []         # 当前文件中出现过的来源
        # UI 引用
        self.log_list = None
        self.date_dropdown = None
        self.source_dd = None
        self.level_dd = None
        self.keyword_field = None
        self.status_text = None

    # ---------------------------------------------------------------- UI
    def build(self) -> ft.Control:
        """构建日志页 UI"""
        # 来源下拉 (选项随日志文件动态生成)
        self.source_dd = ft.Dropdown(
            label="来源", width=180, dense=True,
            text_style=ft.TextStyle(size=SIZE_LABEL, font_family=FONT_STACK),
            options=[ft.dropdown.Option("__all__", "全部日志")],
            value="__all__",
            on_select=lambda e: self._on_filter_change('source'),
        )

        # 级别下拉 (设计稿: 全部级别/INFO/WARNING/ERROR/DEBUG)
        self.level_dd = ft.Dropdown(
            label="级别", width=140, dense=True,
            text_style=ft.TextStyle(size=SIZE_LABEL, font_family=FONT_STACK),
            options=[
                ft.dropdown.Option("all", "全部级别"),
                ft.dropdown.Option("info", "INFO"),
                ft.dropdown.Option("warn", "WARNING"),
                ft.dropdown.Option("error", "ERROR"),
                ft.dropdown.Option("debug", "DEBUG"),
            ],
            value="all",
            on_select=lambda e: self._on_filter_change('level'),
        )

        # 关键词搜索 (固定宽度: Column 内 Row 的 expand 在部分组合下失效)
        self.keyword_field = ft.TextField(
            label="搜索关键词", width=360, dense=True,
            text_style=ft.TextStyle(size=SIZE_LABEL, font_family=FONT_STACK),
            on_submit=lambda e: self._on_filter_change('keyword'),
        )

        # 右侧动作按钮 (设计稿: 复制/导出/清空)
        copy_btn = tonal_btn("复制", icon=ft.Icons.CONTENT_COPY,
                             on_click=self._on_copy, tooltip="复制当前过滤结果到剪贴板")
        export_btn = tonal_btn("导出", icon=ft.Icons.DOWNLOAD,
                               on_click=self._on_export, tooltip="导出当前过滤结果为 txt")
        clear_btn = tonal_btn("清空", icon=ft.Icons.DELETE_SWEEP_OUTLINED,
                              on_click=self._on_clear_view,
                              tooltip="仅清空当前显示 (不影响日志文件)")

        # 日期与文件入口 (按天浏览日志的实用行)
        self.date_dropdown = ft.Dropdown(
            label="日志日期", width=200, dense=True,
            text_style=ft.TextStyle(size=SIZE_LABEL, font_family=FONT_STACK),
            options=[],
            on_select=lambda e: self._reload(),
        )
        refresh_btn = tonal_btn("刷新", icon=ft.Icons.REFRESH,
                                on_click=lambda e: self._reload())
        open_dir_btn = tonal_btn("打开日志目录", icon=ft.Icons.FOLDER_OPEN,
                                 on_click=lambda e: self._open_log_dir())
        self.status_text = ft.Text("", size=SIZE_TINY, weight=WEIGHT_BODY,
                                   color=ft.Colors.ON_SURFACE_VARIANT,
                                   font_family=FONT_STACK)

        toolbar = make_card(
            ft.Column([
                ft.Row([self.source_dd, self.level_dd, self.keyword_field,
                        copy_btn, export_btn, clear_btn],
                       spacing=6),
                ft.Row([self.date_dropdown, refresh_btn, open_dir_btn,
                        self.status_text],
                       spacing=6, wrap=True),
            ], spacing=8),
            padding=10,
        )

        self.log_list = ft.ListView(
            expand=True,
            spacing=1,
            auto_scroll=False,
        )

        viewer = ft.Container(
            content=self.log_list,
            expand=True,
            padding=10,
            # 深色终端风格: 深底 + 浅色文字 (ERROR红/WARN黄/DEBUG灰)
            bgcolor=LOG_TERMINAL_BG,
            border_radius=8,
        )

        self._built = True
        # 初始加载（首次构建即刷新下拉与内容）
        try:
            self._reload()
        except Exception:
            pass

        header = page_header(
            "运行日志", "查看系统运行日志，便于排查问题与追踪状态")
        return ft.Column([
            header,
            toolbar,
            ft.Container(content=viewer, expand=True,
                         padding=ft.Padding(left=10, top=0, right=10, bottom=10)),
        ], expand=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    # ---------------------------------------------------------------- 逻辑
    def _open_log_dir(self):
        """打开日志目录（系统文件管理器）"""
        log_dir = get_log_dir()
        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError:
            pass
        try:
            if os.name == 'nt':
                os.startfile(log_dir)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', log_dir])
            else:
                subprocess.Popen(['xdg-open', log_dir])
        except Exception as ex:
            try:
                import 日志 as _app_log
                _app_log.warn('日志页', f"无法打开日志目录: {ex}")
            except Exception:
                pass

    def _reload(self):
        """刷新日期下拉 + 加载选中日期的日志内容"""
        try:
            files = list_log_files()
            # 更新日期下拉选项
            self.date_dropdown.options = [
                ft.dropdown.Option(name[:-4], name[:-4]) for name in files
            ]
            # 选中当前日期（默认最新文件）
            if self.date_dropdown.value not in [n[:-4] for n in files]:
                self.date_dropdown.value = files[0][:-4] if files else None

            if not self.date_dropdown.value:
                self._all_lines = []
                self.log_list.controls.clear()
                self.log_list.controls.append(
                    ft.Text("暂无日志", size=SIZE_SMALL, weight=WEIGHT_BODY,
                            color=ft.Colors.ON_SURFACE_VARIANT, italic=True,
                            font_family=FONT_STACK))
            else:
                self._load_file(f"{self.date_dropdown.value}.log")
            if self.page is not None:
                try:
                    self.page.update()
                except Exception:
                    pass
        except Exception:
            pass

    def _load_file(self, filename: str):
        """读取单个日志文件 (M11: 只读尾部 2MB, 避免大文件冻结 UI; 超出部分
        只显示尾部 _MAX_DISPLAY_LINES 行) 并渲染"""
        path = os.path.join(get_log_dir(), filename)
        self._all_lines = []
        self.log_list.controls.clear()
        if not os.path.isfile(path):
            self.log_list.controls.append(
                ft.Text(f"文件不存在: {filename}", size=SIZE_BODY,
                        color=MORANDI_ERROR, font_family=FONT_STACK))
            return
        try:
            # 尾部读取: seek 到 (文件大小 - 2MB) 处, 丢弃首个可能截断的半行
            _TAIL_BYTES = 2 * 1024 * 1024
            size = os.path.getsize(path)
            with open(path, 'rb') as f:
                if size > _TAIL_BYTES:
                    f.seek(size - _TAIL_BYTES)
                raw = f.read()
            text = raw.decode('utf-8', errors='replace')
            if size > _TAIL_BYTES and '\n' in text:
                text = text.split('\n', 1)[1]
            lines = text.splitlines()
        except OSError as ex:
            self.log_list.controls.append(
                ft.Text(f"读取失败: {ex}", size=SIZE_BODY,
                        color=MORANDI_ERROR, font_family=FONT_STACK))
            return

        if len(lines) > _MAX_DISPLAY_LINES:
            lines = lines[-_MAX_DISPLAY_LINES:]

        self._all_lines = lines
        self._rebuild_source_options(lines)
        self._render_lines()

    def _rebuild_source_options(self, lines):
        """从日志行提取来源字段, 动态生成来源下拉选项"""
        sources = []
        for line in lines[-2000:]:
            m = _SOURCE_RE.match(line)
            if m:
                src = m.group(1)
                if src and src not in sources:
                    sources.append(src)
        self._sources = sources
        if self.source_dd is None:
            return
        self.source_dd.options = (
            [ft.dropdown.Option("__all__", "全部日志")] +
            [ft.dropdown.Option(s, s) for s in sources[:30]]
        )
        if self._source != '__all__' and self._source not in sources:
            self._source = '__all__'
        self.source_dd.value = self._source

    def _on_filter_change(self, kind: str):
        """来源/级别/关键词过滤变化 → 重渲染"""
        self._source = self.source_dd.value or '__all__'
        self._level = self.level_dd.value or 'all'
        self._keyword = (self.keyword_field.value or '').strip()
        self._render_lines()
        try:
            self.page.update()
        except Exception:
            pass

    def _visible_lines(self):
        """应用 来源+级别+关键词 三维过滤, 返回可见行列表"""
        kw = self._keyword.lower()
        out = []
        for line in self._all_lines:
            if self._source != '__all__' and self._source not in line:
                continue
            if not self._level_match(line):
                continue
            if kw and kw not in line.lower():
                continue
            out.append(line)
        return out

    def _level_match(self, line: str) -> bool:
        upper = line.upper()
        if self._level == 'all':
            return True
        if self._level == 'error':
            return '[ERROR]' in upper
        if self._level == 'warn':
            return '[WARN]' in upper or '[WARNING]' in upper
        if self._level == 'debug':
            return '[DEBUG]' in upper
        # info: 非 error/warn/debug
        return not ('[ERROR]' in upper or '[WARN]' in upper or '[DEBUG]' in upper)

    def _render_lines(self):
        """渲染过滤后的日志行"""
        self.log_list.controls.clear()
        lines = self._visible_lines()
        if len(self._all_lines) >= _MAX_DISPLAY_LINES:
            self.log_list.controls.append(
                ft.Text(f"(文件较大，仅显示最后 {_MAX_DISPLAY_LINES} 行)",
                        size=SIZE_TINY, weight=WEIGHT_BODY,
                        color=ft.Colors.ON_SURFACE_VARIANT, italic=True,
                        font_family=FONT_STACK))
        for line in lines:
            self.log_list.controls.append(
                ft.Text(line, size=SIZE_TINY,
                        font_family=LOG_TERMINAL_FONT,
                        color=log_line_color(line), selectable=True))
        if self.status_text is not None:
            self.status_text.value = f"显示 {len(lines)} / {len(self._all_lines)} 行"

    # ------------------------------------------------------------ 动作按钮
    def _on_copy(self, e=None):
        """复制当前过滤结果到剪贴板 (Windows clip.exe)"""
        text = '\n'.join(self._visible_lines())
        if not text:
            self._notify("没有可复制的内容")
            return
        try:
            import locale
            enc = locale.getpreferredencoding(False)
            proc = subprocess.Popen('clip', stdin=subprocess.PIPE, shell=False)
            proc.communicate(text.encode(enc, errors='replace'))
            self._notify(f"已复制 {len(self._visible_lines())} 行到剪贴板")
        except Exception as ex:
            self._notify(f"复制失败: {ex}")

    def _on_export(self, e=None):
        """导出当前过滤结果为 txt (日志目录下, pathlib 写入)"""
        lines = self._visible_lines()
        if not lines:
            self._notify("没有可导出的内容")
            return
        try:
            import time as _t
            fname = f"日志导出_{_t.strftime('%Y%m%d_%H%M%S')}.txt"
            out = Path(get_app_base_dir()) / '日志' / fname
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
            self._notify(f"已导出 {len(lines)} 行 → 日志/{fname}")
        except OSError as ex:
            self._notify(f"导出失败: {ex}")

    def _on_clear_view(self, e=None):
        """清空当前显示 (不影响日志文件)"""
        self.log_list.controls.clear()
        if self.status_text is not None:
            self.status_text.value = "已清空显示 (重新加载即可恢复)"
        try:
            self.page.update()
        except Exception:
            pass

    def _notify(self, msg: str):
        try:
            open_dialog(self.page, ft.SnackBar(ft.Text(msg, font_family=FONT_STACK)))
        except Exception:
            pass
