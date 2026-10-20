# -*- coding: utf-8 -*-
"""浏览器插件安装弹窗 (2026-10-20)。

入口: 远控页「浏览器插件」按钮。
流程: 状态行 (插件是否在线) → 选 Chrome / Edge 版 → 自动复制到本机稳定目录
+ 打开对应浏览器的扩展页 → 弹窗内给出 4 步引导 (目录已自动复制好)。

分层: 安装/复制/打开浏览器/ping 状态全在 `插件安装.py` (纯逻辑, 离线可测);
本文件只做视图。
"""
import logging

import flet as ft

from .ui_fluent import FONT_STACK, SIZE_LABEL, SIZE_SMALL, open_dialog, close_dialog

_log = logging.getLogger('插件安装弹窗')

_文字色 = ft.Colors.ON_SURFACE


def 打开插件安装弹窗(page) -> ft.AlertDialog:
    import 插件安装

    状态行 = ft.Text(插件安装.状态文案(), size=SIZE_SMALL,
                   font_family=FONT_STACK, color=_文字色)
    步骤区 = ft.Column([], spacing=4, tight=True)
    结果行 = ft.Text('', size=SIZE_SMALL, font_family=FONT_STACK, color=_文字色)

    对话框 = ft.AlertDialog(modal=True)
    对话框.title = ft.Text('安装浏览器插件', color=_文字色, font_family=FONT_STACK)

    def _刷新状态(_e=None):
        try:
            状态行.value = 插件安装.状态文案()
            状态行.update()
        except Exception as e:
            _log.debug(f'状态刷新失败: {type(e).__name__}: {e}')

    def _安装(浏览器: str):
        结果 = 插件安装.安装(浏览器)
        if not 结果.get('ok'):
            结果行.value = f'⚠️ {结果.get("原因", "安装失败")}'
            步骤区.controls.clear()
        else:
            打开 = 插件安装.打开扩展页(浏览器)
            结果行.value = (f'✅ {结果["浏览器"]} 版已复制到本机'
                          + ('' if 打开.get('ok') else f'（{打开.get("原因", "")}）'))
            步骤区.controls.clear()
            步骤区.controls.extend(
                ft.Text(s, size=SIZE_LABEL, font_family=FONT_STACK, color=_文字色)
                for s in 结果.get('步骤', []))
        try:
            结果行.update()
            步骤区.update()
        except Exception as e:
            _log.debug(f'安装结果刷新失败: {type(e).__name__}: {e}')

    对话框.content = ft.Column([
        ft.Text('把浏览器里的真实登录态 Cookie 提供给爬虫（仅白名单站点）。',
                size=SIZE_SMALL, font_family=FONT_STACK, color=_文字色),
        状态行,
        ft.Row([
            ft.FilledTonalButton('安装 Chrome 版', icon=ft.Icons.EXTENSION_OUTLINED,
                                 on_click=lambda _e: _安装('chrome')),
            ft.FilledTonalButton('安装 Edge 版', icon=ft.Icons.EXTENSION_OUTLINED,
                                 on_click=lambda _e: _安装('edge')),
            ft.TextButton('刷新状态', icon=ft.Icons.REFRESH,
                          on_click=_刷新状态),
        ], spacing=8),
        结果行,
        步骤区,
        ft.Text('装好后回到这里点「刷新状态」即可看到连接情况（插件每 5 分钟自动同步一次）。',
                size=SIZE_LABEL, font_family=FONT_STACK,
                color=ft.Colors.ON_SURFACE_VARIANT),
    ], tight=True, spacing=10, width=520)

    对话框.actions = [
        ft.TextButton('关闭', on_click=lambda _e: close_dialog(page, 对话框)),
    ]
    open_dialog(page, 对话框)
    return 对话框
