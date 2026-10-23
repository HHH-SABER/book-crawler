# -*- coding: utf-8 -*-
"""浏览器插件安装弹窗 —— 扫描 → 列表 → 确认 → 安装 (2026-10-23 用户验收重排)。

用户验收意见 (2026-10-23):
  · 弹窗按钮文本要对齐、布局整齐、内容不超出窗口;
  · 点「安装到此浏览器」必须立刻有反应 (旧版会无响应/无提示);
  · 夸克提示要纠正 (不存在"开启扩展"这步)。

流程:
  打开 → 自动扫描 → 列表 (左: 名称+版本·路径 / 右: 固定宽按钮)
       → 点安装 → **本程序内确认框**「是否继续」→ 复制文件 + 打开浏览器 +
         地址进剪贴板 → 结果卡 (4 步引导 + 复制目录 + 重新打开)
分层: 复制/开浏览器/剪贴板/心跳 全在 插件安装.py (纯逻辑可测), 本文件只做视图。
"""
import logging

import flet as ft

from .ui_fluent import (FONT_STACK, SIZE_LABEL, SIZE_SMALL, close_dialog,
                        open_dialog)

_log = logging.getLogger('插件安装弹窗')

_文字色 = ft.Colors.ON_SURFACE
_弱色 = ft.Colors.ON_SURFACE_VARIANT
_按钮宽 = 160          # 右侧动作列固定宽 (对齐的关键; 放得下「安装到此浏览器」不折行)


def 打开插件安装弹窗(page) -> ft.AlertDialog:
    import 插件安装

    状态行 = ft.Text('', size=SIZE_SMALL, font_family=FONT_STACK, color=_文字色)
    列表区 = ft.Column([], spacing=10, tight=True, scroll=ft.ScrollMode.AUTO,
                     height=300)
    结果提示 = ft.Text('', size=SIZE_LABEL, font_family=FONT_STACK, color=_文字色,
                    visible=False)
    结果卡 = ft.Container(visible=False, padding=10, border_radius=8,
                       bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.GREEN),
                       content=ft.Column([], spacing=6, tight=True))

    对话框 = ft.AlertDialog(modal=True)
    对话框.title = ft.Text('安装浏览器插件', color=_文字色, font_family=FONT_STACK)

    def _刷新状态(_e=None):
        try:
            状态行.value = '刷新中…'
            状态行.update()
        except Exception:
            pass    # 刻意静默: 局部刷新失败不影响后续取值
        try:
            状态行.value = 插件安装.状态文案()
            状态行.update()
        except Exception as e:
            _log.debug(f'状态刷新失败: {type(e).__name__}: {e}')

    def _刷新结果卡(_e=None):
        try:
            结果卡.update()
            结果提示.update()
        except Exception as e:
            _log.debug(f'结果卡刷新失败: {type(e).__name__}: {e}')

    # ---------------------------------------------------------------- 结果卡
    def _显示结果(标题: str, 步骤: list, 目录: str = '', 提示: str = '',
               浏览器: str = ''):
        控件s = [ft.Text(标题, size=SIZE_SMALL, font_family=FONT_STACK,
                        color=_文字色, max_lines=3)]
        if 提示:
            控件s.append(ft.Text(提示, size=SIZE_LABEL, font_family=FONT_STACK,
                               color=_文字色, max_lines=3))
        for s in 步骤:
            控件s.append(ft.Text(s, size=SIZE_LABEL, font_family=FONT_STACK,
                                color=_文字色, max_lines=2))
        if 目录:
            控件s.append(ft.Text(
                '⚠️ 若浏览器里已装过本插件：请在扩展页点该插件的「刷新 ↻」按钮重新加载，'
                '否则浏览器仍会用旧版本（会出现「未知消息」或报错）。',
                size=SIZE_LABEL, font_family=FONT_STACK,
                color=ft.Colors.ORANGE, max_lines=3))

            def _复制目录(_e=None):
                try:
                    插件安装._复制剪贴板(目录)
                    结果提示.value = '✅ 目录路径已复制，可在文件选择框里 Ctrl+V 粘贴'
                except Exception as ex:
                    _log.debug(f'复制目录失败: {type(ex).__name__}')
                    结果提示.value = '⚠️ 复制失败，请手动选中目录'
                结果提示.visible = True
                _刷新结果卡()

            def _重开(_e=None):
                try:
                    插件安装.打开扩展页(浏览器)
                except Exception as ex:
                    _log.debug(f'重开扩展页失败: {type(ex).__name__}')

            控件s.append(ft.Row([
                ft.TextButton('复制目录路径', icon=ft.Icons.CONTENT_COPY,
                              on_click=_复制目录),
                ft.TextButton('重新打开扩展页', icon=ft.Icons.OPEN_IN_BROWSER,
                              on_click=_重开),
            ], spacing=4))
        结果卡.content = ft.Column(控件s, spacing=6, tight=True)
        结果卡.visible = True
        结果提示.visible = False
        _刷新结果卡()

    # ---------------------------------------------------------------- 安装
    def _执行安装(浏览器: str):
        结果卡.visible = False
        结果卡.content = ft.Column([])
        结果提示.visible = False
        _刷新结果卡()
        try:
            结果 = 插件安装.安装(浏览器)
        except Exception as e:
            _log.info(f'[安装] 抛异常: {type(e).__name__}: {e}')
            _显示结果(f'⚠️ 安装失败：{type(e).__name__}: {e}', [])
            return
        if not 结果.get('ok'):
            _显示结果(f'⚠️ {结果.get("原因", "安装失败")}', [])
            return
        try:
            打开 = 插件安装.打开扩展页(浏览器)
        except Exception as e:
            _log.info(f'[安装] 打开扩展页异常: {type(e).__name__}: {e}')
            打开 = {'ok': False, '提示': ''}
        标题 = f'✅ {结果["浏览器"]} 版已复制到本机'
        if 结果.get('原因'):
            标题 += f'\n{结果["原因"]}'
        _显示结果(标题, 结果.get('步骤', []), 目录=结果.get('目录', ''),
                提示=打开.get('提示', ''), 浏览器=浏览器)

    def _问确认(浏览器: str):
        """本程序内的安装确认框 (用户要求"弹出确认, 选是即装")。"""
        名 = 插件安装._浏览器名.get(浏览器, 浏览器)
        确认 = ft.AlertDialog(modal=True)
        确认.title = ft.Text(f'在 {名} 中安装插件？', color=_文字色,
                          font_family=FONT_STACK)
        确认.content = ft.Text(
            '将安装「小说爬虫 · 凭据中继」—— 把浏览器里的真实登录 Cookie 提供给本机爬虫。\n\n'
            '点击「是」后会：复制插件文件到本机 → 唤起浏览器 → 把扩展页地址放进剪贴板。',
            size=SIZE_SMALL, font_family=FONT_STACK, color=_文字色)

        def _是(_e=None):
            close_dialog(page, 确认)
            _执行安装(浏览器)

        def _否(_e=None):
            close_dialog(page, 确认)

        确认.actions = [
            ft.TextButton('取消', on_click=_否),
            ft.FilledButton('是，开始安装', on_click=_是),
        ]
        open_dialog(page, 确认)

    # ---------------------------------------------------------------- 列表
    def _行(项: dict) -> ft.Control:
        名 = 项['名称']
        版 = 项.get('版本') or ''
        已装 = 项['已安装']
        支持 = 项['支持']
        可安装 = 已装 and 支持

        if 已装:
            副 = ' · '.join(x for x in (f'v{版}' if 版 else '', 项.get('路径', '')) if x)
        else:
            副 = f'未检测到 {名}，请先安装该浏览器'
        if not 支持:
            副 = 项.get('说明') or '不支持的浏览器'

        左 = ft.Column([
            ft.Text(名, size=SIZE_SMALL, font_family=FONT_STACK, color=_文字色),
            ft.Text(副, size=SIZE_LABEL, font_family=FONT_STACK, color=_弱色,
                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
        ], spacing=2, tight=True, expand=True)

        if 可安装:
            动作 = ft.FilledTonalButton('安装到此浏览器', height=32, width=_按钮宽 - 8,
                                     on_click=lambda _e, k=项['浏览器']: _问确认(k))
        else:
            动作 = ft.Text('— ' + ('不支持' if not 支持 else '未安装'),
                         size=SIZE_LABEL, font_family=FONT_STACK, color=_弱色,
                         text_align=ft.TextAlign.RIGHT)
        右 = ft.Container(width=_按钮宽, alignment=ft.Alignment.CENTER_RIGHT,
                          content=动作)

        控件s = [ft.Row([左, 右], spacing=10,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER)]
        # 备注单独一行占满宽度 (不挤在左列, 避免把按钮顶歪/文字溢出)
        if 支持 and 项.get('说明'):
            控件s.append(ft.Text(f'· {项["说明"]}', size=11, font_family=FONT_STACK,
                               color=_弱色, max_lines=2))
        return ft.Column(控件s, spacing=3, tight=True)

    def _扫描(_e=None):
        try:
            项s = 插件安装.扫描()
        except Exception as e:
            _log.info(f'浏览器扫描失败: {type(e).__name__}: {e}')
            项s = []
        列表区.controls.clear()
        if not 项s:
            列表区.controls.append(ft.Text('未扫描到可用浏览器', size=SIZE_SMALL,
                                       font_family=FONT_STACK, color=_弱色))
        for 项 in 项s:
            列表区.controls.append(_行(项))
        try:
            列表区.update()
        except Exception as e:
            _log.debug(f'列表刷新失败: {type(e).__name__}: {e}')

    对话框.content = ft.Column([
        ft.Text('把浏览器里的真实登录态 Cookie 提供给爬虫（仅白名单站点）。',
                size=SIZE_SMALL, font_family=FONT_STACK, color=_文字色),
        状态行,
        ft.Row([
            ft.Text('本机浏览器', size=SIZE_SMALL, font_family=FONT_STACK,
                    color=_弱色),
            ft.Container(expand=True),
            ft.TextButton('重新扫描', icon=ft.Icons.REFRESH, on_click=_扫描),
            ft.TextButton('刷新状态', icon=ft.Icons.CHECK_CIRCLE_OUTLINE,
                          on_click=_刷新状态),
        ], spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        列表区,
        结果卡,
        结果提示,
        ft.Text('装好后在插件里填端口 8760 与 token（远控页可复制）；插件每 5 分钟'
                '自动同步，这里会显示「已连接」。',
                size=SIZE_LABEL, font_family=FONT_STACK, color=_弱色, max_lines=2),
    ], tight=True, spacing=10, width=600)

    对话框.actions = [
        ft.TextButton('关闭', on_click=lambda _e: close_dialog(page, 对话框)),
    ]
    _刷新状态()
    _扫描()          # 打开即自动扫描
    open_dialog(page, 对话框)
    return 对话框
