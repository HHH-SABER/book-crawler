# -*- coding: utf-8 -*-
"""远控页: 远控开关 + 访问信息 + 手机端远程任务记录。

- 开关与顶栏胶囊同一逻辑 (gui_app 注入 切换 回调, 状态同源)
- 手机端记录 = 来源为"手机"的任务 (远控 API 创建时标记), 本页 2s 局部刷新
- 访问信息含 Tailscale 外网地址提示; token 默认打码显示, 可点「显示」切换
  (打码只发生在展示层, 真实 token 仍由 取信息() 返回并留在内存)
"""
import time

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
                         make_morandi_card)
# Phase 3 (2026-10-04): 页面颜色一律走令牌, 且登记重刷 —— 直接 import 上面那类
# MORANDI 常量绑到的是**构建期求值的字符串对象**, 切夜间主题不会重刷 (ui_fluent
# 的 globals().update 改不到页面里的本地名); 详见 文档/审查报告汇总.md Phase 3 结论。
from ..ui_tokens import 取色, 登记重刷
from ..ui_theme import page_header


# 开关切换的兜底时长 (秒): 切换是"调度即返回"的异步过程, 正常靠运行状态变化
# 复位进行态; 若状态一直没变 (切换被打断/失败) 最多禁用这么久, 避免永久卡死。
_开关超时兜底秒 = 6.0


def 打码token(token: str) -> str:
    """token 展示层打码: 只留末 4 位, 其余用 • 代替; 空 token 显示 '—'。

    ⚠️ 只管展示: 取信息() 仍返回真实 token, 显示/隐藏切换取用的也是原始值。
    """
    文本 = (token or "").strip()
    if not 文本:
        return "—"
    if len(文本) <= 4:
        return "•" * len(文本)      # 太短: 全打码, 一个字符都不露
    return "•" * (len(文本) - 4) + 文本[-4:]


class RemotePage:
    """远控页 (main 装配: page / task_manager 注入, 绑定(切换, 信息) 接线)"""

    def __init__(self):
        self.page = None
        self.task_manager = None
        self.切换远控 = None       # callable(e): 与顶栏开关同一实现
        self.取信息 = None         # callable() -> {"运行", "地址", "token", "提示"}
        # --- 开关进行态 (防连点) ---
        self._启用状态 = False     # 最近一次同步到的远控运行状态
        self._开关进行中 = False   # True = 已点击、切换尚未尘埃落定
        self._开关起点 = 0.0       # 进行态起点 (time.monotonic)
        self._点击时运行 = False   # 点击瞬间的运行状态 (用于判定切换是否完成)
        # --- token 展示 (默认打码) ---
        self._token明文 = ""       # 真实 token, 只留内存, 从不写入控件
        self._token可见 = False    # 用户是否点了「显示」

    # ---------------------------------------------------------------- 外观
    def 同步外观(self, 启用: bool):
        """远控开关状态变化时刷新本页开关外观 (gui_app._更新远控外观 调用)"""
        try:
            self._启用状态 = bool(启用)
            # 防连点: 运行状态已改变(切换生效) 或 兜底超时 → 退出进行态
            if self._开关进行中 and (
                    bool(启用) != self._点击时运行
                    or time.monotonic() - self._开关起点 > _开关超时兜底秒):
                self._开关进行中 = False
                self._btn.disabled = False
            self._btn.bgcolor = (ft.Colors.PRIMARY_CONTAINER if 启用
                                 else ft.Colors.SURFACE_CONTAINER)
            # 进行中保留"启用中…"文案, 不被本轮运行状态覆盖
            if not self._开关进行中:
                self._btn_lab.value = "远控已启用" if 启用 else "远控已停用"
            # Phase 3: 旧写法 color=MORANDI_SUCCESS/MORANDI_STOPPED 是构建期字符串
            # 常量, 切夜间主题不重刷 → 改走令牌取色 (重刷回调在 build 里登记)。
            self._btn_dot.color = (取色('status-success') if 启用
                                   else 取色('status-pending'))
            self._btn.update()
            self._btn_lab.update()
            self._btn_dot.update()
        except Exception:
            pass  # 刻意静默: 高频路径(同步外观(), 逐行/每秒级), 补日志会刷屏

    def _进入开关进行态(self):
        """点击瞬间进入进行态: 文案改「启用中…」+ 临时禁用, 堵住连点重复启停"""
        self._开关进行中 = True
        self._开关起点 = time.monotonic()
        # 以取信息() 的实时状态为准 (页面首帧可能还没 refresh 过, _启用状态 会偏旧)
        try:
            info = self.取信息() if self.取信息 else {}
            self._点击时运行 = bool(info.get("运行"))
        except Exception as _e:
            self._点击时运行 = bool(self._启用状态)
            _dbg("远控页", f'取实时运行态失败: {type(_e).__name__}: {_e}')
        self._btn_lab.value = "启用中…"
        self._btn.disabled = True
        if self.page is not None:
            self._btn.update()
            self._btn_lab.update()

    def _复位开关进行态(self):
        """退出进行态: 恢复可点 + 文案回到当前运行状态 (调度失败时立即调用)"""
        self._开关进行中 = False
        self._btn.disabled = False
        self._btn_lab.value = "远控已启用" if self._启用状态 else "远控已停用"
        if self.page is not None:
            self._btn.update()
            self._btn_lab.update()

    def _点击开关(self, e=None):
        """本页开关点击入口: 进入进行态后交给注入的 切换远控 (与顶栏同一实现)。

        切换本身是"调度即返回"(gui_app._切远控 里 page.run_task), 所以这里无法
        同步复位; 复位由 refresh() 轮询里的 同步外观() 按运行状态变化完成。
        """
        if self._开关进行中:
            return                       # 双保险: 进行态下忽略重复点击
        if not self.切换远控:
            return                       # 未接线(装配未完成): 维持原行为, 点击不做事
        self._进入开关进行态()
        try:
            self.切换远控(e)
        except Exception as _e:
            _dbg("远控页", f'远控开关调度异常: {type(_e).__name__}: {_e}')
            self._复位开关进行态()

    def build(self):
        # Phase 3: 点色走令牌 (旧 MORANDI_SUCCESS 是构建期字符串常量, 切主题不重刷)
        self._btn_dot = ft.Icon(ft.Icons.CIRCLE, size=9,
                                color=取色('status-success'))
        # 状态点颜色随"启用/停用"变, 重刷回调按最近状态取色 (见 同步外观)
        登记重刷(self._btn_dot, lambda c: setattr(
            c, 'color', 取色('status-success') if self._启用状态
            else 取色('status-pending')))
        self._btn_lab = txt("远控已启用", size=SIZE_BODY, weight=WEIGHT_SUBTITLE)
        self._btn = ft.Container(
            content=ft.Row([self._btn_dot, self._btn_lab,
                            ft.Icon(ft.Icons.POWER_SETTINGS_NEW, size=16)],
                           spacing=8, tight=True,
                           vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding.symmetric(horizontal=14, vertical=9),
            border_radius=20, ink=True,
            on_click=self._点击开关,
            tooltip="启用/停用远控 (停用后手机端将无法访问)",
        )

        self._addr = txt("—", size=SIZE_SMALL, weight=WEIGHT_BODY,
                         font_family=FONT_STACK, selectable=True)
        self._token = txt("—", size=SIZE_SMALL, weight=WEIGHT_BODY,
                          font_family=FONT_STACK, selectable=True)
        # 2026-10-04 UX: token 默认打码, 这个按钮只切换"显示/隐藏"(展示层)
        self._token按钮 = ft.IconButton(ft.Icons.VISIBILITY, icon_size=15,
                                        tooltip="显示 token",
                                        on_click=self._切换token显示)
        # 2026-10-04 #7: 地址可用性提示 —— 手机连不上时给出原因 (空串自动隐藏该行)
        # Phase 3: 提示色走令牌 (旧 MORANDI_WARNING 绑定字符串, 切主题不重刷)
        self._hint = txt("", size=SIZE_SMALL, weight=WEIGHT_BODY,
                         color=取色('status-warning'), font_family=FONT_STACK,
                         visible=False)
        登记重刷(self._hint, lambda c: setattr(c, 'color',
                                            取色('status-warning')))
        # Phase 3: 分隔线同理 —— 旧 MORANDI_OUTLINE_VARIANT 不会随主题重刷
        self._divider = ft.Divider(height=1, color=取色('border-subtle'))
        登记重刷(self._divider, lambda c: setattr(c, 'color',
                                              取色('border-subtle')))

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
                self._divider,
                ft.Row([txt("本机地址", size=SIZE_SMALL, weight=WEIGHT_BODY),
                        self._addr], spacing=8),
                ft.Row([txt("token   ", size=SIZE_SMALL, weight=WEIGHT_BODY),
                        self._token, self._token按钮], spacing=8),
                # 2026-10-04 #7: 地址可用性提示行 (内容为空时 visible=False 自动隐藏)
                self._hint,
                ft.Text("外网访问 (可选): 在电脑执行 tailscale serve --bg 8760, "
                        "手机浏览器打开它给出的 https://….ts.net 地址",
                        size=SIZE_SMALL, weight=WEIGHT_BODY,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                        font_family=FONT_STACK),
            ], spacing=8, tight=True),
            padding=14, border_radius=10,
            bgcolor=ft.Colors.SURFACE_CONTAINER,
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
                bgcolor=ft.Colors.SURFACE_CONTAINER, expand=True,
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

    # ---------------------------------------------------------------- token 展示
    def _切换token显示(self, e=None):
        """「显示/隐藏」切换: 只改展示层, 真实 token 始终留在 self._token明文"""
        self._token可见 = not self._token可见
        self._渲染token()
        try:
            if self.page is not None:
                self._token.update()
                self._token按钮.update()
        except Exception as _e:
            _dbg("远控页", f'token 显示切换刷新失败: {type(_e).__name__}: {_e}')

    def _渲染token(self):
        """按当前 显示/隐藏 状态渲染 token (打码只在展示层, 不改真实值)"""
        self._token.value = (self._token明文 if self._token可见
                             else 打码token(self._token明文))
        按钮 = getattr(self, '_token按钮', None)
        if 按钮 is not None:
            按钮.icon = (ft.Icons.VISIBILITY_OFF if self._token可见
                        else ft.Icons.VISIBILITY)
            按钮.tooltip = "隐藏 token" if self._token可见 else "显示 token"

    # ---------------------------------------------------------------- 数据
    def refresh(self):
        """刷新开关外观 + 访问信息 + 手机端记录列表 (主线程调用)"""
        try:
            if self.取信息:
                info = self.取信息()
                self.同步外观(bool(info.get("运行")))
                self._addr.value = info.get("地址") or "—"
                # 2026-10-04 UX: token 默认打码显示 —— 真实值只存内存, 供「显示」切换
                self._token明文 = info.get("token") or ""
                self._渲染token()
                # 2026-10-04 #7: 地址可用性提示 (回环绑定 / 未探测到局域网地址时非空)
                _提示 = info.get("提示") or ""
                self._hint.value = _提示
                self._hint.visible = bool(_提示)
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
