# -*- coding: utf-8 -*-
"""远控页: 远控开关 + 访问信息 + 手机端远程任务记录。

- 开关与顶栏胶囊同一逻辑 (gui_app 注入 切换 回调, 状态同源)
- 手机端记录 = 来源为"手机"的任务 (远控 API 创建时标记), 本页 2s 局部刷新
- 访问信息含 Tailscale 外网地址提示; token 用可选文本便于复制
"""
import flet as ft

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
            pass

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
                        ft.Text("手机访问: 需与电脑同一 Tailscale 账号",
                                size=SIZE_SMALL, weight=WEIGHT_BODY,
                                color=ft.Colors.ON_SURFACE_VARIANT,
                                font_family=FONT_STACK)], spacing=10),
                ft.Divider(height=1, color=MORANDI_OUTLINE_VARIANT),
                ft.Row([txt("本机地址", size=SIZE_SMALL, weight=WEIGHT_BODY),
                        self._addr], spacing=8),
                ft.Row([txt("token   ", size=SIZE_SMALL, weight=WEIGHT_BODY),
                        self._token], spacing=8),
                ft.Text("外网访问: 在电脑执行 tailscale serve --bg 8760, "
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
        self._rows = ft.Column([self._empty], spacing=4, tight=True)

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
                ], spacing=8, tight=True),
                padding=14, border_radius=10,
                bgcolor=MORANDI_SURFACE_CONTAINER, expand=True,
            ),
        ], spacing=10, expand=True)

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
            pass
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
            pass
