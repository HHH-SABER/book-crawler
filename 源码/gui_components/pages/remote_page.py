# -*- coding: utf-8 -*-
"""远控页: 远控开关 + 访问信息 + 手机端远程任务记录。

- 开关与顶栏胶囊同一逻辑 (gui_app 注入 切换 回调, 状态同源)
- 手机端记录 = 来源为"手机"的任务 (远控 API 创建时标记), 本页 2s 局部刷新
- 访问信息含 Tailscale 外网地址提示; token 用可选文本便于复制
"""
import flet as ft

try:
    import 日志 as _app_log          # 留痕通道 (桥模式, 同 site_manage_page)
except Exception:
    _app_log = None


def _dbg(source: str, message: str):
    """异常留痕 (DEBUG 级: 只落盘不 console 镜像, 避免高频刷屏)"""
    if _app_log is not None:
        try:
            _app_log.debug(source, message)
        except Exception:
            pass  # 刻意静默: try 块本身在写日志, 再加日志会递归 (日志链路兜底)

from ..ui_fluent import (txt, FONT_STACK, SIZE_SMALL, SIZE_BODY, SIZE_TITLE,
                         WEIGHT_TITLE, WEIGHT_SUBTITLE, WEIGHT_BODY,
                         MORANDI_SUCCESS, MORANDI_STOPPED,
                         MORANDI_SURFACE_CONTAINER, MORANDI_OUTLINE_VARIANT,
                         make_morandi_card)
from ..ui_theme import page_header


class RemotePage:
    """远控页 (main 装配: page / task_manager 注入, 绑定(切换, 信息) 接线)"""

    def __init__(self):
        self.page = None
        self.task_manager = None
        self.切换远控 = None       # callable(e): 与顶栏开关同一实现
        self.取信息 = None         # callable() -> {"运行", "地址", "token"}

    # ---------------------------------------------------------------- 外观
    def 同步外观(self, 启用: bool):
        """远控开关状态变化时刷新本页开关外观 (gui_app._更新远控外观 调用)"""
        try:
            self._btn.bgcolor = (ft.Colors.PRIMARY_CONTAINER if 启用
                                 else MORANDI_SURFACE_CONTAINER)
            self._btn_lab.value = "远控已启用" if 启用 else "远控已停用"
            self._btn_dot.color = MORANDI_SUCCESS if 启用 else MORANDI_STOPPED
            self._btn.update()
            self._btn_lab.update()
            self._btn_dot.update()
        except Exception:
            pass  # 刻意静默: 高频路径(同步外观(), 逐行/每秒级), 补日志会刷屏

    def build(self):
        self._btn_dot = ft.Icon(ft.Icons.CIRCLE, size=9, color=MORANDI_SUCCESS)
        self._btn_lab = txt("远控已启用", size=SIZE_BODY, weight=WEIGHT_SUBTITLE)
        self._btn = ft.Container(
            content=ft.Row([self._btn_dot, self._btn_lab,
                            ft.Icon(ft.Icons.POWER_SETTINGS_NEW, size=16)],
                           spacing=8, tight=True,
                           vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding.symmetric(horizontal=14, vertical=9),
            border_radius=20, ink=True,
            on_click=lambda e: (self.切换远控(e) if self.切换远控 else None),
            tooltip="启用/停用远控 (停用后手机端将无法访问)",
        )

        self._addr = txt("—", size=SIZE_SMALL, weight=WEIGHT_BODY,
                         font_family=FONT_STACK, selectable=True)
        self._token = txt("—", size=SIZE_SMALL, weight=WEIGHT_BODY,
                          font_family=FONT_STACK, selectable=True)

        self._status_card = ft.Container(
            content=ft.Column([
                ft.Row([self._btn,
                        ft.Container(expand=True),
                        # 2026-10-03 #7: 默认 0.0.0.0 局域网直连, Tailscale 降为外网可选
                        ft.Text("手机访问: 与电脑连同一 Wi-Fi, 浏览器打开本机地址",
                                size=SIZE_SMALL, weight=WEIGHT_BODY,
                                color=ft.Colors.ON_SURFACE_VARIANT,
                                font_family=FONT_STACK),
                        # 使用教程入口 (2026-09-29 用户反馈"EXE 里找不到使用说明"):
                        # 教程页由内嵌远控服务的 /tutorial 渲染 (与手机端同一页面),
                        # 故需远控处于开启状态
                        ft.TextButton("使用教程", icon=ft.Icons.BOOK_OUTLINED,
                                      on_click=self._open_tutorial)],
                       spacing=10),
                ft.Divider(height=1, color=MORANDI_OUTLINE_VARIANT),
                ft.Row([txt("本机地址", size=SIZE_SMALL, weight=WEIGHT_BODY),
                        self._addr], spacing=8),
                ft.Row([txt("token   ", size=SIZE_SMALL, weight=WEIGHT_BODY),
                        self._token], spacing=8),
                ft.Text("外网访问 (可选): 在电脑执行 tailscale serve --bg 8760, "
                        "手机浏览器打开它给出的 https://….ts.net 地址",
                        size=SIZE_SMALL, weight=WEIGHT_BODY,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                        font_family=FONT_STACK),
            ], spacing=8, tight=True),
            padding=14, border_radius=10,
            bgcolor=MORANDI_SURFACE_CONTAINER,
        )

        self._empty = txt("暂无手机端记录 — 手机发起的抓取任务会实时出现在这里",
                          size=SIZE_SMALL, weight=WEIGHT_BODY,
                          color=ft.Colors.ON_SURFACE_VARIANT)
        # ListView + 常显滚动条 (2026-09-29): 旧实现 Column(tight) 记录一多
        # 就超出 Container 有界高度被裁, 且无滚动出口; expand 取满卡片剩余高度
        self._rows = ft.ListView(spacing=4, expand=True,
                                 scroll=ft.ScrollMode.ALWAYS)

        return ft.Column([
            page_header('远控', '远程控制开关、手机访问方式与手机端任务记录'),
            self._status_card,
            ft.Container(
                content=ft.Column([
                    ft.Row([txt("手机端记录", size=SIZE_TITLE,
                                weight=WEIGHT_TITLE),
                            ft.Container(expand=True),
                            ft.IconButton(ft.Icons.REFRESH, icon_size=16,
                                          tooltip="刷新",
                                          on_click=lambda e: self.refresh())],
                           vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    self._rows,
                ], spacing=8, expand=True),
                padding=14, border_radius=10,
                bgcolor=MORANDI_SURFACE_CONTAINER, expand=True,
            ),
        ], spacing=10, expand=True)

    # ---------------------------------------------------------------- 教程
    def _open_tutorial(self, e=None):
        """打开使用教程 (系统浏览器 → 内嵌远控 /tutorial, 与手机端同一页面)"""
        try:
            info = self.取信息() if self.取信息 else {}
        except Exception as _e:
            info = {}
            _dbg("远控页", f'取信息失败: {type(_e).__name__}: {_e}')
        if not info.get("运行"):
            self._toast("请先启用远控 —— 教程页由远控服务提供")
            return
        import webbrowser
        地址 = (info.get("地址") or "http://127.0.0.1:8760/").rstrip("/")
        webbrowser.open(f"{地址}/tutorial")

    def _toast(self, msg: str):
        """SnackBar 轻提示 (同 detail_drawer._toast 模式, 经 ui_fluent.open_dialog)"""
        try:
            from ..ui_fluent import open_dialog
            if self.page is not None:
                open_dialog(self.page, ft.SnackBar(
                    ft.Text(msg, font_family=FONT_STACK), duration=4000))
        except Exception:
            pass  # 刻意静默: toast 属锦上添花, 失败不影响教程打开主路径

    # ---------------------------------------------------------------- 数据
    def refresh(self):
        """刷新开关外观 + 访问信息 + 手机端记录列表 (主线程调用)"""
        try:
            if self.取信息:
                info = self.取信息()
                self.同步外观(bool(info.get("运行")))
                self._addr.value = info.get("地址") or "—"
                self._token.value = info.get("token") or "—"
        except Exception:
            pass  # 刻意静默: 高频路径(refresh(), 逐行/每秒级), 补日志会刷屏
        try:
            tasks = [t for t in self.task_manager.get_all_tasks()
                     if getattr(t, '来源', '本机') == '手机']
            self._rows.controls.clear()
            if not tasks:
                self._rows.controls.append(self._empty)
            else:
                for t in tasks:
                    进度 = (f"{t.progress_current}/{t.progress_total}"
                            if t.progress_total else "—")
                    self._rows.controls.append(ft.Container(
                        content=ft.Row([
                            txt(t.task_id, size=SIZE_SMALL, weight=WEIGHT_BODY),
                            txt((t.title or t.url)[:30], size=SIZE_SMALL,
                                weight=WEIGHT_SUBTITLE),
                            ft.Container(expand=True),
                            txt(t.status, size=SIZE_SMALL, weight=WEIGHT_BODY),
                            txt(进度, size=SIZE_SMALL, weight=WEIGHT_BODY),
                        ], spacing=10),
                        padding=ft.Padding.symmetric(vertical=5, horizontal=6),
                        border_radius=6,
                        bgcolor=ft.Colors.SURFACE_CONTAINER,
                    ))
            if self.page is not None:
                self._rows.update()
        except Exception:
            pass  # 刻意静默: 高频路径(refresh(), 逐行/每秒级), 补日志会刷屏
