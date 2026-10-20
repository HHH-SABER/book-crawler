# -*- coding: utf-8 -*-
"""浏览器插件安装弹窗 —— 扫描 → 列表 → 选择 → 安装 (2026-10-20 重构)。

需求 (用户验收意见): 点「浏览器插件」后应**自动扫描本机已装浏览器**, 列出
全部支持安装的目标供选择, 选定后再执行安装; 不支持的浏览器要给出明确提示。

流程:
  打开弹窗 → 自动扫描 (插件安装.扫描) → 列表展示
    · 已装且支持: 名称 + 版本 + 路径 + [安装此浏览器]
    · 已装但不支持 (如 Firefox): 灰行 + 明确原因, 无安装按钮
    · 未装的受支持浏览器: 灰行 +「未检测到，请先安装」, 按钮禁用
  → 点安装: 复制插件到本机稳定目录 + 打开该浏览器扩展页 + 展开 4 步引导
  → 安装后状态行的"插件在线"由心跳判断, 点「刷新」即更新

分层: 扫描/版本/复制/打开浏览器/心跳全在 `插件安装.py` (纯逻辑, 离线可测);
本文件只做视图。
"""
import logging

import flet as ft

from .ui_fluent import FONT_STACK, SIZE_LABEL, SIZE_SMALL, open_dialog, close_dialog

_log = logging.getLogger('插件安装弹窗')

_文字色 = ft.Colors.ON_SURFACE
_弱色 = ft.Colors.ON_SURFACE_VARIANT


def 打开插件安装弹窗(page) -> ft.AlertDialog:
    import 插件安装

    状态行 = ft.Text(插件安装.状态文案(), size=SIZE_SMALL,
                   font_family=FONT_STACK, color=_文字色)
    列表区 = ft.Column([], spacing=8, tight=True)
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

    def _行(项: dict) -> ft.Control:
        名 = 项['名称']
        版 = 项.get('版本') or ''
        已装 = 项['已安装']
        支持 = 项['支持']
        可安装 = 已装 and 支持

        副文案 = (' · '.join(x for x in (f'v{版}' if 版 else '', 项.get('路径', '')) if x)
                if 已装 else f'未检测到 {名}，请先安装该浏览器')
        if not 支持:
            副文案 = 项.get('说明') or '不支持的浏览器'

        行们 = [
            ft.Text(名, size=SIZE_SMALL, font_family=FONT_STACK, color=_文字色),
            ft.Text(副文案, size=SIZE_LABEL, font_family=FONT_STACK, color=_弱色),
        ]
        # 已支持但需额外步骤的浏览器 (如夸克的「扩展支持」开关) 明示提示
        if 支持 and 项.get('说明'):
            行们.append(ft.Text(f'⚠️ {项["说明"]}', size=SIZE_LABEL,
                               font_family=FONT_STACK, color=ft.Colors.ORANGE))
        左 = ft.Column(行们, spacing=2, tight=True)

        if 可安装:
            动作 = ft.FilledTonalButton(
                '安装到此浏览器', height=34,
                on_click=lambda _e, k=项['浏览器']: _安装(k))
        else:
            标签 = '不支持' if not 支持 else '未安装'
            动作 = ft.Text(f'— {标签}', size=SIZE_LABEL,
                         font_family=FONT_STACK, color=_弱色)
        return ft.Row([左, ft.Container(expand=True), 动作],
                      spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def _扫描(_e=None):
        try:
            项s = 插件安装.扫描()
        except Exception as e:
            _log.info(f'浏览器扫描失败: {type(e).__name__}: {e}')
            项s = []
        列表区.controls.clear()
        if not 项s:
            列表区.controls.append(
                ft.Text('未扫描到可用浏览器', size=SIZE_SMALL,
                        font_family=FONT_STACK, color=_弱色))
        for 项 in 项s:
            列表区.controls.append(_行(项))
        try:
            列表区.update()
        except Exception as e:
            _log.debug(f'列表刷新失败: {type(e).__name__}: {e}')

    def _安装(浏览器: str):
        结果 = 插件安装.安装(浏览器)
        步骤区.controls.clear()
        if not 结果.get('ok'):
            结果行.value = f'⚠️ {结果.get("原因", "安装失败")}'
        else:
            打开 = 插件安装.打开扩展页(浏览器)
            结果行.value = (f'✅ {结果["浏览器"]} 版已复制到本机'
                          + ('' if 打开.get('ok') else f'（{打开.get("原因", "")}）')
                          + ('\n' + 打开.get('提示', '') if 打开.get('提示') else ''))
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
            ft.Text('本机已检测到以下浏览器：', size=SIZE_SMALL,
                    font_family=FONT_STACK, color=_弱色),
            ft.Container(expand=True),
            ft.TextButton('重新扫描', icon=ft.Icons.REFRESH, on_click=_扫描),
            ft.TextButton('刷新状态', icon=ft.Icons.CHECK_CIRCLE_OUTLINE,
                          on_click=_刷新状态),
        ], spacing=6),
        列表区,
        结果行,
        步骤区,
        ft.Text('装好后在插件里填入端口(8760)与 token（远控页可复制）；'
                '插件每 5 分钟自动同步，这里会显示「已连接」。',
                size=SIZE_LABEL, font_family=FONT_STACK, color=_弱色),
    ], tight=True, spacing=10, width=560)

    对话框.actions = [
        ft.TextButton('关闭', on_click=lambda _e: close_dialog(page, 对话框)),
    ]
    _扫描()          # 打开即自动扫描
    open_dialog(page, 对话框)
    return 对话框
