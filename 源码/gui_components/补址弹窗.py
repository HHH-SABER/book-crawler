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
from urllib.parse import urlsplit

import flet as ft

from .ui_fluent import FONT_STACK, SIZE_LABEL, SIZE_SMALL, open_dialog, close_dialog, 提示条

_log = logging.getLogger('补址弹窗')

场景_网站失效 = '网站失效'      # 域名级死亡（DNS 解析不了）⇒ 书与网站同时失效
场景_书籍失效 = '书籍失效'      # 网站可达但这本书不在了（被删/404/不可读）
场景_其他 = '其他'              # 目录无章节 / 站点临时不可达等"疑似"

_文字色 = ft.Colors.ON_SURFACE


def 检查网站重复(新网址: str) -> dict:
    """新网址的**域名**是否已登记过 (纯逻辑, 不碰 Flet, 离线可测)。

    需求 (2026-10-19): "添加新网站这里增加一个网站重复的提示" —— 死书补址
    登记新网址时, 若该网站早已在 网站清单.txt / 站点配置.json 里登记过, 给
    用户一句人话提示, 避免静默登记出重复站点。

    Returns:
        {'重复': bool, '域名': str, '说明': str}
        说明只在重复时非空 (含该站已登记的用途, 给人看的);
        输入为空/无法解析域名时 重复=False (不误报)。
    """
    网 = (新网址 or '').strip()
    if not 网:
        return {'重复': False, '域名': '', '说明': ''}
    try:
        域名 = (urlsplit(网).hostname or '').lower()
    except Exception:
        return {'重复': False, '域名': '', '说明': ''}
    if not 域名:
        return {'重复': False, '域名': '', '说明': ''}
    if 域名.startswith('www.'):     # www 与非 www 视为同一网站 (同爬虫 取域名 规则)
        域名 = 域名[4:]
    已有 = []

    # 查网站清单 (条目: 网址/网站名/小说名)
    try:
        import 网站清单
        for 条目 in 网站清单.读取():
            网址 = str(条目.get('网址', ''))
            try:
                条域名 = (urlsplit(网址).hostname or '').lower()
            except Exception:
                条域名 = ''
            if 条域名.startswith('www.'):
                条域名 = 条域名[4:]
            if 条域名 == 域名:
                书 = str(条目.get('小说名', '') or '').strip()
                已有.append(书 or 网址)
    except Exception:
        pass    # 刻意静默: 清单读失败不该让补址流程崩, 只是少了重复提示

    # 查站点配置 (已登记解析规则的站点)
    try:
        import json as _json
        from pathlib import Path as _Path
        from _path_utils import resolve_data_file
        配置路径 = resolve_data_file('站点配置.json',
                                     copy_default_from_resource_if_missing=True)
        配置 = _json.loads(_Path(配置路径).read_text(encoding='utf-8'))
        if isinstance(配置, list):
            for 站点 in 配置:
                if isinstance(站点, dict) and str(站点.get('domain', '')).lower().removeprefix('www.') == 域名:
                    已有.append('站点解析规则')
    except Exception:
        pass    # 刻意静默: 同上

    if not 已有:
        return {'重复': False, '域名': 域名, '说明': ''}
    去重 = list(dict.fromkeys(x for x in 已有 if x))
    摘要 = '、'.join(去重[:3]) + (f' 等 {len(去重)} 处' if len(去重) > 3 else '')
    return {'重复': True, '域名': 域名,
            '说明': f'该网站（{域名}）已登记过：{摘要} —— 仍可添加, 不会覆盖已有记录'}


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
                     f"如果你知道这本书在别处的目录页，填在下面即可登记为备用源：\n"
                     f"以后主源失败时会自动切换过去继续抓。"),
            '追问标题': '这本书已没有可用的网站来源',
            '追问正文': ('没有补充新网站的话，是否删除这本书的记录？\n'
                         '（任务 / 书架 / 网站清单三处，已下载的文件不会删除）'),
        }
    if 场景 == 场景_书籍失效:
        return {
            '标题': '书籍已失效（网站仍可访问）',
            '正文': (f"《{书名}》\n{详情}\n\n"
                     f"网站本身还能打开，但这本书已经不在上面了\n"
                     f"（可能被作者/站点删除，或链接已失效）。\n"
                     f"如果这本书在别的网站也有，填在下面即可登记为备用源：\n"
                     f"以后主源失败时会自动切换过去继续抓。"),
            '追问标题': '这本书在原网站已不存在',
            '追问正文': ('不补充新网站的话，是否删除这本书的记录？\n'
                         '（任务 / 书架 / 网站清单三处，已下载的文件不会删除）'),
        }
    return {
        '标题': '这本书没能抓下来',
        '正文': (f"《{书名}》\n{详情}\n\n"
                 f"站点通常还能访问，可能只是目录页选择器失效或临时抽风。\n"
                 f"如果这本书在别的网站也有，填在下面即可登记为备用源：\n"
                 f"以后主源失败时会自动切换过去继续抓。"),
        '追问标题': '是否删除这本书的记录？',
        '追问正文': ('如果不确定是否真失效，选「稍后处理」后可回死书清单页点'
                     '「重新检测」再确认（可能只是选择器失效或站点风控拦截）。\n'
                     '删除会同时移除任务 / 书架 / 网站清单记录，已下载的文件不会删除。'),
    }


def 选场景(记录) -> str:
    """按死书记录的**结构化字段**选场景 (纯函数, 2026-10-13 #3 三档分流)。

    为什么不比较 `类型` 字符串: gui_app 分流契约明确"只认结构化字段" ——
    类型文案会变, 字段语义不会; 且判错代价不对称 (误删仍可恢复的书 > 多问一句)。

    分流规则 (自上而下短路):
      ① `网站失效` 为真        → 网站失效 (域名级死亡, 书与网站同时失效)
      ② `类型` == 书已删除或不可读 → 书籍失效 (网站可达, 书不在了)
      ③ 其余                   → 其他/疑似 (目录无章节 / 站点临时不可达)

    Args:
        记录: task.dead dict (或任何 getattr-able 对象; 非 dict 时静默走③)。
    """
    if not isinstance(记录, dict):
        return 场景_其他
    if 记录.get('网站失效'):
        return 场景_网站失效
    try:
        from 死书处理 import 类型_书已删除
    except Exception:
        类型_书已删除 = '书已删除或不可读'
    if 记录.get('类型') == 类型_书已删除:
        return 场景_书籍失效
    return 场景_其他


class 补址动作:
    """两种入口（工作台弹窗 / 死书清单页按钮）各自注入的动作。

    刻意用普通类而非 dataclass: 调用方按需传 2~4 个回调, 缺省即为"不提供该动作",
    弹窗据此决定要不要显示对应按钮。
    """

    def __init__(self, 添加并重抓=None, 删除记录=None, 忽略记录=None, 稍后=None,
                 重新检测=None):
        self.添加并重抓 = 添加并重抓
        self.删除记录 = 删除记录
        self.忽略记录 = 忽略记录
        self.稍后 = 稍后
        self.重新检测 = 重新检测


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
        self.重复提示 = ''          # 域名重复时的人话提示 (空=不重复)
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
        # 网站重复提示 (2026-10-19 需求): 域名早已登记过也放行, 但告知
        _重复 = 检查网站重复(新网址)
        结果 = 备用源.添加备用源(self.目录URL, 新网址)
        if not 结果.get('可以'):
            _log.info(f"登记备用源被拒: {结果.get('原因')}")
            return {'可以': False, '原因': 结果.get('原因') or '登记失败'}
        self.重复提示 = _重复.get('说明', '') if _重复.get('重复') else ''
        self.已添加 = (新网址 or '').strip()
        if self.动作.添加并重抓:
            try:
                self.动作.添加并重抓(self.已添加)
            except Exception as e:
                _log.info(f"用新网址发起抓取失败: {type(e).__name__}: {e}")
                return {'可以': True,
                        '原因': f'备用源已登记, 但发起抓取失败: {type(e).__name__}',
                        '重复提示': self.重复提示}
        return {'可以': True, '原因': '', '重复提示': self.重复提示}

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

    追问动作们 = [
        ft.TextButton("稍后处理", on_click=lambda _e: (_关(追问), 流程.稍后())),
        ft.TextButton("忽略此书", on_click=_忽略),
        ft.TextButton("删除记录", on_click=_删),
    ]
    if getattr(流程.动作, '重新检测', None):
        def _重检(_e=None):
            _关(追问)
            try:
                流程.动作.重新检测()
            except Exception as e:
                _log.info(f"重新检测回调失败: {type(e).__name__}: {e}")
        追问动作们.insert(0, ft.TextButton("重新检测", on_click=_重检))
    追问.actions = 追问动作们

    # ---------------- 第一步: 补新网站 ----------------
    地址框 = ft.TextField(
        hint_text="粘贴这本书在新网站的目录页网址 (http:// 或 https://)",
        text_style=ft.TextStyle(size=SIZE_SMALL, font_family=FONT_STACK, color=_文字色),
        dense=True, autofocus=True,
    )
    # 网站重复提示位 (2026-10-19 需求): 边输边判, 命中即显示, 不拦截添加
    重复行 = ft.Text('', size=SIZE_LABEL, font_family=FONT_STACK,
                   color=ft.Colors.ORANGE, visible=False)

    def _刷新重复提示(_e=None):
        try:
            检 = 检查网站重复(地址框.value or '')
        except Exception as e:
            _log.debug(f"重复检查失败: {type(e).__name__}: {e}")
            return
        重复行.value = f'⚠️ {检["说明"]}' if 检.get('重复') else ''
        重复行.visible = bool(检.get('重复'))
        try:
            重复行.update()
        except Exception as e:
            _log.debug(f"重复提示行刷新失败: {type(e).__name__}: {e}")

    地址框.on_change = _刷新重复提示
    对话框 = ft.AlertDialog(modal=True)
    对话框.title = ft.Text(流程.文案['标题'], color=_文字色, font_family=FONT_STACK)
    对话框.content = ft.Column([
        ft.Text(流程.文案['正文'], size=SIZE_SMALL, font_family=FONT_STACK, color=_文字色),
        地址框,
        重复行,
        ft.Text("提示: 登记后主源失败会自动切换到备用源；不填则进入删除确认。",
                size=SIZE_LABEL, font_family=FONT_STACK, color=_文字色),
    ], tight=True, spacing=10)

    def _添加(_e=None):
        结果 = 流程.尝试添加(地址框.value or '')
        if not 结果['可以']:
            _提示栏(f"⚠️ {结果['原因']}")
            return          # 保持弹窗, 让用户改网址
        _关(对话框)
        _提示栏(f"✅ 已登记备用源, 正在用新网址抓取:\n{流程.已添加}"
                + (f"\n⚠️ {结果.get('重复提示', '')}" if 结果.get('重复提示') else ''))
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
