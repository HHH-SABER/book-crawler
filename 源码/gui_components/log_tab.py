# -*- coding: utf-8 -*-
"""运行日志页签：按日期查看落盘日志，错误/警告高亮

日志文件位于 BASE_DIR/日志/YYYY-MM-DD[._N].log（见 日志.py）。
"""
import os
import sys
import subprocess
import flet as ft

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys as _sys; _sys.path.insert(0, _HERE)  # noqa: E402
from _path_utils import get_app_base_dir  # noqa: E402

# UI 主题系统
from .ui_theme import (make_card, tonal_btn, BTN_TEXT_STYLE,
                       LOG_TERMINAL_BG, LOG_TERMINAL_FONT, log_line_color)

# 统一字体规范
from .ui_morandi import (FONT_STACK, SIZE_LABEL, SIZE_SMALL,
                         SIZE_BODY, SIZE_TINY, WEIGHT_BODY,
                         MORANDI_ERROR)  # noqa: E402

# 单文件最多显示行数（超出取尾部）
_MAX_DISPLAY_LINES = 1500


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


class LogTab:
    """运行日志查看页签"""

    def __init__(self):
        self.date_dropdown = None
        self.log_list = None
        self.page = None  # 由 gui_app 注入
        self._built = False
        self._current_filter = 'all'  # 日志级别过滤：all / error / warn / info / debug

    # ------------------------------------------------------------------ UI
    def build(self) -> ft.Control:
        """构建日志页签 UI"""
        self.date_dropdown = ft.Dropdown(
            label="日志日期",
            width=260,
            text_style=ft.TextStyle(size=SIZE_LABEL, font_family=FONT_STACK),
            options=[],
            on_select=lambda e: self._reload(),
        )

        refresh_btn = tonal_btn("刷新", icon=ft.Icons.REFRESH,
                                on_click=lambda e: self._reload())
        open_dir_btn = tonal_btn("打开日志目录", icon=ft.Icons.FOLDER_OPEN,
                                 on_click=lambda e: self._open_log_dir())
        # 日志级别过滤按钮
        self.filter_btns = {
            'all': tonal_btn("全部", icon=ft.Icons.LIST,
                             on_click=lambda e: self._set_filter('all')),
            'error': tonal_btn("错误", icon=ft.Icons.ERROR_OUTLINED,
                               on_click=lambda e: self._set_filter('error')),
            'warn': tonal_btn("警告", icon=ft.Icons.WARNING_OUTLINED,
                              on_click=lambda e: self._set_filter('warn')),
            'info': tonal_btn("信息", icon=ft.Icons.INFO_OUTLINED,
                              on_click=lambda e: self._set_filter('info')),
            'debug': tonal_btn("调试", icon=ft.Icons.BUG_REPORT,
                               on_click=lambda e: self._set_filter('debug')),
        }
        tip = ft.Text(
            "日志记录所有任务操作、抓取详情与错误堆栈，便于事后排查问题。"
            "文件位置：BASE_DIR/日志/YYYY-MM-DD.log（保留最近30天）",
            size=SIZE_SMALL, weight=WEIGHT_BODY,
            color=ft.Colors.ON_SURFACE_VARIANT, italic=True,
            font_family=FONT_STACK,
        )

        self.log_list = ft.ListView(
            expand=True,
            spacing=1,
            auto_scroll=True,
        )

        toolbar = make_card(
            ft.Column([
                ft.Row([self.date_dropdown, refresh_btn, open_dir_btn],
                       wrap=True),
                ft.Row([self.filter_btns[k] for k in self.filter_btns],
                       wrap=True, spacing=4),
                tip,
            ]),
            padding=10,
        )

        viewer = ft.Container(
            content=self.log_list,
            expand=True,
            padding=10,
            # 深色终端风格: 深底 + 浅色文字 (ERROR红/WARN黄/DEBUG灰)
            bgcolor=LOG_TERMINAL_BG,
            border_radius=12,
        )

        self._built = True
        # 初始加载（首次构建即刷新下拉与内容）
        try:
            self._reload()
        except Exception:
            pass

        return ft.Column([
            toolbar,
            ft.Container(content=viewer, expand=True,
                         padding=ft.Padding(left=10, top=0, right=10, bottom=10)),
        ], expand=True)

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
            print(f"[日志] 无法打开日志目录: {ex}")

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
        """读取并渲染单个日志文件（大文件只显示尾部 _MAX_DISPLAY_LINES 行）"""
        path = os.path.join(get_log_dir(), filename)
        self.log_list.controls.clear()
        if not os.path.isfile(path):
            self.log_list.controls.append(
                ft.Text(f"文件不存在: {filename}", size=SIZE_BODY,
                        color=MORANDI_ERROR, font_family=FONT_STACK))
            return
        try:
            with open(path, encoding='utf-8', errors='replace') as f:
                lines = f.read().splitlines()
        except OSError as ex:
            self.log_list.controls.append(
                ft.Text(f"读取失败: {ex}", size=SIZE_BODY,
                        color=MORANDI_ERROR, font_family=FONT_STACK))
            return

        if len(lines) > _MAX_DISPLAY_LINES:
            lines = lines[-_MAX_DISPLAY_LINES:]
            self.log_list.controls.append(
                ft.Text(f"(文件较大，仅显示最后 {_MAX_DISPLAY_LINES} 行)",
                        size=SIZE_TINY, weight=WEIGHT_BODY,
                        color=ft.Colors.ON_SURFACE_VARIANT, italic=True,
                        font_family=FONT_STACK))

        for line in lines:
            # 应用日志级别过滤
            if not self._filter_line(line):
                continue
            self.log_list.controls.append(
                ft.Text(line, size=SIZE_TINY,
                        font_family=LOG_TERMINAL_FONT,
                        color=log_line_color(line), selectable=True))

    @staticmethod
    def _line_color(line: str):
        """按日志级别着色（统一走 ui_theme）"""
        return log_line_color(line)

    def _set_filter(self, level: str):
        """设置日志级别过滤"""
        self._current_filter = level
        # 更新按钮样式
        for key, btn in self.filter_btns.items():
            if key == level:
                btn.style = ft.ButtonStyle(
                    shape=ft.RoundedRectangleBorder(radius=10),
                    bgcolor=ft.Colors.PRIMARY_CONTAINER,
                    color=ft.Colors.ON_PRIMARY_CONTAINER,
                    text_style=BTN_TEXT_STYLE,
                )
            else:
                btn.style = ft.ButtonStyle(
                    shape=ft.RoundedRectangleBorder(radius=10),
                    text_style=BTN_TEXT_STYLE,
                )
        # 重新加载当前日志文件
        if self.date_dropdown.value:
            self._load_file(f"{self.date_dropdown.value}.log")
        try:
            self.page.update()
        except Exception:
            pass

    def _filter_line(self, line: str) -> bool:
        """判断日志行是否应该显示（根据当前过滤级别）"""
        if self._current_filter == 'all':
            return True
        level = line.upper()
        if self._current_filter == 'error':
            return 'ERROR' in level or '错误' in line or '失败' in line
        if self._current_filter == 'warn':
            return 'WARN' in level or '警告' in line
        if self._current_filter == 'debug':
            return 'DEBUG' in level or '调试' in line
        # info: 显示所有非 error/warn/debug 的行
        return not ('ERROR' in level or '错误' in line or '失败' in line) and \
               not ('WARN' in level or '警告' in line) and \
               not ('DEBUG' in level or '调试' in line)
