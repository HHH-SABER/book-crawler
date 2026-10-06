# -*- coding: utf-8 -*-
"""死书「补新网站」弹窗（2026-10-06 新功能）。

## 用户需求原文
"死书时询问用户是否要添加书籍新网站，没有的话就询问是否删除"。

## 两步流程
```
第一步 (补址):  "这本书没能抓下来 / 网站与书籍都已失效"
                 [新目录页网址输入框]
                 「添加并重抓」 「没有新网站」 「稍后处理」
                     │              └──→ 第二步
                     └──→ 备用源.添加备用源() 成功 → 用新网址发起抓取
第二步 (追问):  "是否删除这本书的记录?"
                 「删除记录」 「忽略此书」 「稍后处理」
```
"添加"不是替换网址，而是把新网址登记为这本书的**备用源**
（`captcha_config.json` 的 `fallback_sources`，消费方 `爬虫.py:7119` 多源回退）:
以后主源被验证码拦死或章节大面积失败时**自动切换**过去继续抓。

## 分层
- `场景文案()` 与 `补址流程` 是**纯逻辑**（不碰 Flet），离线可测；
- `打开补址弹窗()` 只是视图，负责把流程挂到按钮上。
"""
import logging

import flet as ft

from .ui_fluent import FONT_STACK, SIZE_LABEL, SIZE_SMALL, open_dialog, close_dialog, 提示条

_log = logging.getLogger('补址弹窗')

场景_网站失效 = '网站失效'      # 域名级死亡（DNS 解析不了）
场景_其他 = '其他'              # 目录无章节 / 站点不可达等"疑似"

_文字色 = ft.Colors.ON_SURFACE


def 场景文案(场景: str, 标题: str, 类型: str = '', 原因: str = '') -> dict:
    """按场景给出两段文案（纯函数：同一事实只写一处，便于测试与统一口径）。

    Returns:
        {'标题', '正文', '追问标题', '追问正文'}
    """
    书名 = 标题 or '(未知书名)'
    详情 = '\n'.join(x for x in (f"类型: {类型}" if 类型 else '',
                                (原因 or '').strip()) if x)
    if 场景 == 场景_网站失效:
        return {
            '标题': '网站与书籍都已失效',
            '正文': (f"《{书名}》\n{详情}\n\n"
                     f"该书所在的网站已无法访问（域名解析失败）。\n"
                     f"如果你知道这本书在别处的目录页，填在下面即可登记为**备用源**：\n"
                     f"以后主源失败时会自动切换过去继续抓。"),
            '追问标题': '这本书已没有可用的网站来源',
            '追问正文': ('没有补充新网站的话，是否删除这本书的记录？\n'
                         '（任务 / 书架 / 网站清单三处，已下载的文件不会删除）'),
        }
    return {
        '标题': '这本书没能抓下来',
        '正文': (f"《{书名}》\n{详情}\n\n"
                 f"站点通常还能访问，可能只是目录页选择器失效或临时抽风。\n"
                 f"如果这本书在别的网站也有，填在下面即可登记为**备用源**：\n"
                 f"以后主源失败时会自动切换过去继续抓。"),
        '追问标题': '是否删除这本书的记录？',
        '追问正文': ('建议先点「重新检测」确认一次（可能只是选择器失效）。\n'
                     '删除会同时移除任务 / 书架 / 网站清单记录，已下载的文件不会删除。'),
    }


class 补址动作:
    """两种入口（工作台弹窗 / 死书清单页按钮）各自注入的动作。

    刻意用普通类而非 dataclass: 调用方按需传 2~4 个回调, 缺省即为"不提供该动作",
    弹窗据此决定要不要显示对应按钮。
    """

    def __init__(self, 添加并重抓=None, 删除记录=None, 忽略记录=None, 稍后=None):
        self.添加并重抓 = 添加并重抓
        self.删除记录 = 删除记录
        self.忽略记录 = 忽略记录
        self.稍后 = 稍后


class 补址流程:
    """两步弹窗的**决策**（不碰 Flet，可离线测试）。

    一次交互只走一条路径：登记成功→触发重抓；登记失败→保持原状并把原因交回 UI；
    选"没有新网站"→进入追问删除阶段。
    """

    def __init__(self, 目录URL: str, 动作: 补址动作, 场景: str = 场景_其他,
                 标题: str = '', 类型: str = '', 原因: str = ''):
        self.目录URL = 目录URL
        self.动作 = 动作 or 补址动作()
        self.场景 = 场景
        self.文案 = 场景文案(场景, 标题, 类型, 原因)
        self.已添加 = None          # 登记成功的网址
        self.已追问 = False         # 是否已进入"删除追问"阶段
        self.已删除 = False
        self.已忽略 = False

    # ---- 第一步: 登记备用源 ----
    def 尝试添加(self, 新网址: str) -> dict:
        """登记备用源；成功则立刻用新网址发起抓取。

        Returns:
            {'可以': bool, '原因': str}
        """
        import 备用源
        结果 = 备用源.添加备用源(self.目录URL, 新网址)
        if not 结果.get('可以'):
            _log.info(f"登记备用源被拒: {结果.get('原因')}")
            return {'可以': False, '原因': 结果.get('原因') or '登记失败'}
        self.已添加 = (新网址 or '').strip()
        if self.动作.添加并重抓:
            try:
                self.动作.添加并重抓(self.已添加)
            except Exception as e:
                _log.info(f"用新网址发起抓取失败: {type(e).__name__}: {e}")
                return {'可以': True,
                        '原因': f'备用源已登记, 但发起抓取失败: {type(e).__name__}'}
        return {'可以': True, '原因': ''}

    # ---- 第一步 → 第二步 ----
    def 没有新网站(self) -> dict:
        """用户表示"没有新网站" → 进入追问删除。"""
        self.已追问 = True
        return self.文案

    # ---- 第二步 ----
    def 确认删除(self) -> bool:
        self.已删除 = True
        if self.动作.删除记录:
            try:
                self.动作.删除记录()
                return True
            except Exception as e:
                _log.info(f"删除记录失败: {type(e).__name__}: {e}")
                return False
        return False

    def 忽略此书(self) -> bool:
        self.已忽略 = True
        if self.动作.忽略记录:
            try:
                self.动作.忽略记录()
                return True
            except Exception as e:
                _log.info(f"忽略失败: {type(e).__name__}: {e}")
                return False
        return False

    def 稍后(self):
        if self.动作.稍后:
            try:
                self.动作.稍后()
            except Exception as e:
                _log.info(f"稍后处理回调失败: {type(e).__name__}: {e}")


def 打开补址弹窗(page, *, 目录URL: str, 标题: str = '', 场景: str = 场景_其他,
                类型: str = '', 原因: str = '', 动作: 补址动作 = None) -> ft.AlertDialog:
    """构建并弹出"补新网站"弹窗（含第二步追问删除）。返回第一步的对话框对象。"""
    流程 = 补址流程(目录URL, 动作 or 补址动作(), 场景=场景, 标题=标题,
                    类型=类型, 原因=原因)

    def _关(对话框):
        try:
            close_dialog(page, 对话框)
        except Exception as e:
            _log.debug(f"关窗失败: {type(e).__name__}: {e}")

    # ---------------- 第二步: 追问删除 ----------------
    追问 = ft.AlertDialog(modal=True)
    追问.title = ft.Text(流程.文案['追问标题'], color=_文字色, font_family=FONT_STACK)
    追问.content = ft.Text(流程.文案['追问正文'], size=SIZE_SMALL,
                          font_family=FONT_STACK, color=_文字色)

    def _删(_e=None):
        _关(追问)
        if 流程.确认删除():
            _提示栏("已删除这本书的记录 (任务/书架/网站清单; 已下载文件保留)")
        else:
            _提示栏("⚠️ 未接入删除动作, 请到死书清单页处理")

    def _忽略(_e=None):
        _关(追问)
        if 流程.忽略此书():
            _提示栏("已忽略这本书 (不再打扰; 可在死书清单页恢复)")
        else:
            _提示栏("⚠️ 未接入忽略动作, 请到死书清单页处理")

    追问.actions = [
        ft.TextButton("稍后处理", on_click=lambda _e: (_关(追问), 流程.稍后())),
        ft.TextButton("忽略此书", on_click=_忽略),
        ft.TextButton("删除记录", on_click=_删),
    ]

    # ---------------- 第一步: 补新网站 ----------------
    地址框 = ft.TextField(
        hint_text="粘贴这本书在新网站的目录页网址 (http:// 或 https://)",
        text_style=ft.TextStyle(size=SIZE_SMALL, font_family=FONT_STACK, color=_文字色),
        dense=True, autofocus=True,
    )
    对话框 = ft.AlertDialog(modal=True)
    对话框.title = ft.Text(流程.文案['标题'], color=_文字色, font_family=FONT_STACK)
    对话框.content = ft.Column([
        ft.Text(流程.文案['正文'], size=SIZE_SMALL, font_family=FONT_STACK, color=_文字色),
        地址框,
        ft.Text("提示: 登记后主源失败会自动切换到备用源；不填则进入删除确认。",
                size=SIZE_LABEL, font_family=FONT_STACK, color=_文字色),
    ], tight=True, spacing=10)

    def _添加(_e=None):
        结果 = 流程.尝试添加(地址框.value or '')
        if not 结果['可以']:
            _提示栏(f"⚠️ {结果['原因']}")
            return          # 保持弹窗, 让用户改网址
        _关(对话框)
        _提示栏(f"✅ 已登记备用源, 正在用新网址抓取:\n{流程.已添加}")
        if 结果['原因']:
            _提示栏(f"⚠️ {结果['原因']}")

    def _没有(_e=None):
        _关(对话框)
        流程.没有新网站()
        try:
            open_dialog(page, 追问)
        except Exception as e:
            _log.info(f"追问弹窗打开失败: {type(e).__name__}: {e}")

    对话框.actions = [
        ft.TextButton("稍后处理", on_click=lambda _e: (_关(对话框), 流程.稍后())),
        ft.TextButton("没有新网站", on_click=_没有),
        ft.TextButton("添加并重抓", on_click=_添加),
    ]

    def _提示栏(文案: str):
        try:
            open_dialog(page, 提示条(文案))
        except Exception as e:
            _log.debug(f"提示失败: {type(e).__name__}: {e}")

    try:
        open_dialog(page, 对话框)
    except Exception as e:
        _log.info(f"补址弹窗打开失败, 降级为提示: {type(e).__name__}: {e}")
        _提示栏(流程.文案['标题'])
    return 对话框
