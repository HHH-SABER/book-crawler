# -*- coding: utf-8 -*-
"""ui_tokens — 暖色设计系统三层令牌 (设计稿 界面设计预览/index.html 的唯一真值来源)

======================================================================
一、为什么需要这个模块 (Flet 换色机制说明 — 下一轮页面改造必读)
======================================================================
Flet **不是 CSS**, 没有"变量就地替换"这回事。组件一旦构建完成, 它的
bgcolor / color 就是**写死的值**。所以"日间一套、夜间一套"必须在
**构建那一刻**就知道当前是哪个主题。本模块给出的机制是:

    轨道 A (自动适配, 优先用)
        直接用 Flet 的 M3 语义别名 —— ft.Colors.PRIMARY 的真实值是
        字符串 'primary' / 'onprimary' / 'surfacecontainerlow' …,
        由 Flutter 在**渲染时**按 page.theme_mode 解析成当前主题色。
        切主题零成本、零重建、绝不掉色。
        限制: ColorScheme 只有 48 个槽位, 装不下设计稿的
        accent-fg / on-brand-subtle / 6 组状态色 / focus-ring / 终端 8 色。

    轨道 B (本模块 令牌 + 取色, 用于装不进槽位的部分)
        日/夜两套字面量放在 _日间 / _夜间 两个字典里, 构建组件时调
        `取色(键)` 拿当前主题对应的值。
        限制: 取色是**构建期**求值, 切主题后不会自动变 —— 所以配套
        `登记重刷(ctrl, 回调)`: 组件把自己登记进来, 主题切换时
        ui_tokens 统一回调重设属性, 再由 gui_app 已有的 page.update()
        刷出去 (项目硬约定: 禁 page.update(), 这里只改属性不刷)。

    主题状态同步点 (重要):
        gui_app.toggle_theme() 里唯一我们能挂上的钩子是
        `IconRail.toggle_theme_icon(是否夜间)` —— 它在 page.theme_mode
        赋值之后、page.update() 之前被调用, 且 icon_rail.py 属于本轮
        可改文件。所以: toggle_theme_icon -> ui_tokens.设置主题()。
        轨道 B 的重刷就挂在这条链上, **不需要改 gui_app.py**。

======================================================================
二、三层令牌结构
======================================================================
    第一层 基础层  : 原始色板字面量 (本模块 _日间/_夜间 字典, 键名与
                     设计稿 CSS 变量名一一对应, 便于逐条核对)
    第二层 语义层  : 状态色 / 状态容器 / 品牌层 / 可读层 / 焦点环 …
                     (语义名 -> 基础层键, 日夜可不同值)
    第三层 组件层  : 组件规格常量 (BTN_H / BTN_PAD_X / RADIUS_*) 与
                     ui_theme 里的工厂函数 (filled_btn / status_chip …)

======================================================================
三、页面侧怎么用 (下一轮接口约定)
======================================================================
    from gui_components.ui_tokens import 取色, FS_BODY, 间距, RADIUS_LG

    # 1) 凡是能装进 M3 槽位的, 优先 ft.Colors.* 别名 —— 自动适配, 零维护
    ft.Container(bgcolor=ft.Colors.SURFACE)

    # 2) 装不进槽位的 (状态色/焦点环/终端/远控/GitHub…), 用 取色
    ft.Icon(ft.Icons.CIRCLE, color=取色('status-success'))

    # 3) 用了 取色 的组件, 构建后登记重刷, 否则切主题会掉色
    我的组件 = ft.Container(bgcolor=取色('bg-sidebar-active'))
    登记重刷(我的组件, lambda c: setattr(c, 'bgcolor', 取色('bg-sidebar-active')))
"""

# ====================================================================
# 三、第一层: 基础色板 (键名 = 设计稿 CSS 变量名去掉 -- 前缀)
# ====================================================================

# ---- 日间 (:root) ----
_日间 = {
    # 背景
    'bg-primary':          '#F5F5F5',
    'bg-secondary':        '#FFFFFF',
    'bg-tertiary':         '#F5F5F5',
    'bg-sidebar':          '#F1F1F1',
    'bg-sidebar-hover':    '#E7E7E7',
    'bg-sidebar-active':   '#FAF1E7',
    'bg-row-hover':        '#FAFAF9',
    # 文字
    'text-primary':        '#1B1B1B',
    'text-secondary':      '#5C5C5C',
    'text-tertiary':       '#6E6E6E',
    'text-quaternary':     '#767676',
    'text-sidebar-active': '#9C4A0C',
    # 边框
    'border-subtle':       'rgba(0,0,0,0.08)',
    'border-default':      'rgba(0,0,0,0.14)',
    'border-strong':       'rgba(0,0,0,0.22)',
    # 品牌层
    'brand':               '#D9781A',
    'brand-hover':         '#C16816',
    'brand-subtle':        '#FAF1E7',
    # 可读层 (装不进 M3 槽位, 必须走 取色)
    'accent-fg':           '#A6510E',
    'on-brand-subtle':     '#8A4310',
    'on-brand':            '#FFFFFF',
    # 主按钮
    'btn-primary-bg':      '#AD5710',
    'btn-primary-hover':   '#9C4A0C',
    'btn-primary-fg':      '#FFFFFF',
    # 次按钮
    'btn-secondary-bg':    '#FFFFFF',
    'btn-secondary-hover': '#F5F5F5',
    'btn-secondary-fg':    '#3A3A3A',
    'btn-secondary-border': 'rgba(0,0,0,0.16)',
    # 停止 (蓝紫, 不是红!)
    'accent-stop':         '#5C5CD9',
    'accent-stop-hover':   '#4F4FC4',
    'accent-stop-light':   '#EDEDFB',
    # 状态 6 组 (前景 / 浅容器)
    'status-success':      '#1E6B3C',
    'status-success-bg':   '#DFF6E5',
    'status-warning':      '#8A4310',
    'status-warning-bg':   '#FAF1E7',
    'status-error':        '#8E3428',
    'status-error-bg':     '#FBE9E7',
    'status-pending':      '#5E5E5E',
    'status-pending-bg':   '#F0F0F0',
    'status-info':         '#3F3FB0',
    'status-info-bg':      '#EDEDFB',
    # 焦点环
    'focus-ring':          '#AD5710',
    # 远控
    'remote-bg':           '#F9F4EE',
    'remote-text':         '#8A4310',
    # GitHub
    'gh-link':             '#8A4310',
    'gh-hover':            '#74390B',
    'gh-hover-bg':         '#FAF1E7',
    'gh-hint':             '#5E5E5E',
    # 终端 (恒深, 日夜同值)
    'terminal-bg':         '#171717',
    'terminal-text':       '#C8C8C8',
    'terminal-dim':        '#9A9A9A',
    'terminal-green':      '#5BD675',
    'terminal-red':        '#F09A8C',
    'terminal-yellow':     '#E8C57A',
    'terminal-blue':       '#8FB8E0',
    'terminal-cyan':       '#6FDCCC',
    # 其他色
    'red':                 '#A03D33',
    'red-bg':              '#FBE9E7',
    'purple':              '#4F4FC4',
    'purple-bg':           '#EDEDFB',
    'teal':                '#35696B',
    'teal-bg':             '#E4F1F1',
    'green':               '#237A47',
    'green-bg':            '#DFF6E5',
}

# ---- 夜间 (html[data-theme="dark"]) ----
_夜间色 = {
    # 背景
    'bg-primary':          '#202020',
    'bg-secondary':        '#2B2B2B',
    'bg-tertiary':         '#383838',
    'bg-sidebar':          '#171717',      # 纯黑, 比卡片更暗
    'bg-sidebar-hover':    '#2B2B2B',
    'bg-sidebar-active':   '#382614',
    'bg-row-hover':        '#303030',
    # 文字
    'text-primary':        '#FFFFFF',
    'text-secondary':      '#C8C8C8',
    'text-tertiary':       '#A6A6A6',
    'text-quaternary':     '#9A9A9A',
    'text-sidebar-active': '#E8A96A',
    # 边框
    'border-subtle':       'rgba(255,255,255,0.09)',
    'border-default':      'rgba(255,255,255,0.15)',
    'border-strong':       'rgba(255,255,255,0.24)',
    # 品牌层
    'brand':               '#E08A3C',
    'brand-hover':         '#EAA261',
    'brand-subtle':        '#382614',
    # 可读层
    'accent-fg':           '#EAA261',
    'on-brand-subtle':     '#E8A96A',
    'on-brand':            '#1B1B1B',      # 反色: 亮橙底配近黑字 (6.46:1)
    # 主按钮
    'btn-primary-bg':      '#E08A3C',
    'btn-primary-hover':   '#EAA261',
    'btn-primary-fg':      '#1B1B1B',      # 反色
    # 次按钮
    'btn-secondary-bg':    '#2B2B2B',
    'btn-secondary-hover': '#383838',
    'btn-secondary-fg':    '#E4E4E4',
    'btn-secondary-border': 'rgba(255,255,255,0.18)',
    # 停止
    'accent-stop':         '#7B7BE0',
    'accent-stop-hover':   '#9494EC',
    'accent-stop-light':   '#26264A',
    # 状态
    'status-success':      '#7FD472',
    'status-success-bg':   '#1B3D22',
    'status-warning':      '#E8A96A',
    'status-warning-bg':   '#382614',
    'status-error':        '#F0A99C',
    'status-error-bg':     '#432723',
    'status-pending':      '#B0B0B0',
    'status-pending-bg':   '#383838',
    'status-info':         '#A5A5F0',
    'status-info-bg':      '#2B2B4A',
    # 焦点环
    'focus-ring':          '#E8A96A',
    # 远控
    'remote-bg':           '#2B2419',
    'remote-text':         '#E8A96A',
    # GitHub
    'gh-link':             '#E8964A',
    'gh-hover':            '#F2A85C',
    'gh-hover-bg':         '#382614',
    'gh-hint':             '#A6A6A6',
    # 终端: 与日间完全相同 (恒深底)
    'terminal-bg':         '#171717',
    'terminal-text':       '#C8C8C8',
    'terminal-dim':        '#9A9A9A',
    'terminal-green':      '#5BD675',
    'terminal-red':        '#F09A8C',
    'terminal-yellow':     '#E8C57A',
    'terminal-blue':       '#8FB8E0',
    'terminal-cyan':       '#6FDCCC',
    # 其他色
    'red':                 '#F0A99C',
    'red-bg':              '#432723',
    'purple':              '#A5A5F0',
    'purple-bg':           '#2B2B4A',
    'teal':                '#6FDCCC',
    'teal-bg':             '#1B3D3E',
    'green':               '#7FD472',
    'green-bg':            '#1B3D22',
}


# ====================================================================
# 四、第二层: 语义糖 (把"某状态的浅底+深字"打包, 少写两遍键名)
# ====================================================================

# 状态键 -> (前景键, 浅容器键)。'running' 进行中 = 警告色 (设计稿明文规定)
# 2026-10-04 (Phase 3 收尾): `interrupted` 由 status-warning 改到**中性灰**。
# 旧映射下 `interrupted`(已中断) 与 `dead_pending`(书已删除) **完全同色** ——
# 但两者语义相反: 前者只是"进程退出导致没跑完"(无需处理), 后者是"书没了, 需要你裁决"
# (需处理)。同色会让用户在任务表里分不出"哪一行要我去点"。
# 归入灰族后: 等待中/已停止/已中断 = 灰 (同属"未在进行, 也非失败", 靠文案区分, 语义自洽);
# `dead_pending` 独占琥珀警告色, 与 失败(红) 也天然区分。
状态语义 = {
    'success':    ('status-success',    'status-success-bg'),
    'warning':    ('status-warning',    'status-warning-bg'),
    'error':      ('status-error',      'status-error-bg'),
    'pending':    ('status-pending',    'status-pending-bg'),
    'info':       ('status-info',       'status-info-bg'),
    'running':    ('status-warning',    'status-warning-bg'),   # 进行中 = 警告色
    'stopped':    ('status-pending',    'status-pending-bg'),   # 已停止按中性灰
    'interrupted': ('status-pending',   'status-pending-bg'),   # 已中断: 非失败, 中性灰
}

# 徽章/胶囊的语义 -> 状态键
徽章语义 = {
    'completed': 'success',
    'failed':    'error',
    'pending':   'pending',
    'stopped':   'stopped',
    'running':   'running',
    'interrupted': 'interrupted',
    'dead_pending': 'warning',   # 死书待确认 = 需用户裁决, 归入警告
    'success':   'success',
    'warning':   'warning',
    'error':     'error',
    'info':      'info',
}


# ====================================================================
# 五、主题状态 + 取色入口 (轨道 B 的核心)
# ====================================================================

import threading as _threading

_状态锁 = _threading.RLock()
_当前夜间 = False         # 当前是否夜间; 初值 False (gui_app 启动即 LIGHT)
_重刷表 = []              # [(weakref(ctrl), 回调), ...] 主题切换时统一回调
_重刷表压缩阈值 = 512      # 超过即压缩已死弱引用 (2026-10-04, 防全量重建致表单调增长)


def 主题状态() -> bool:
    """当前是否夜间主题 (Flet 语义: True=夜间)"""
    return _当前夜间


# 英文别名 (与团队其它成员/后续代码习惯一致, 两个名字都留)
def is_dark() -> bool:
    """当前是否夜间主题 —— ui_fluent 侧也导出同名函数"""
    return _当前夜间


def 取色(键: str, 夜间: bool = None) -> str:
    """按当前主题取设计稿色值。

    参数:
        键    —— 基础层键名 (见 _日间 字典, 键名 = 设计稿 CSS 变量名)
        夜间  —— 显式指定; None = 跟随全局主题状态

    例: 取色('bg-sidebar-active')  -> '#FAF1E7' (日) / '#382614' (夜)
    """
    表 = _夜间色 if (_当前夜间 if 夜间 is None else 夜间) else _日间
    try:
        return 表[键]
    except KeyError:
        # 拼错键名要立刻炸出来, 不能静默返 None 让控件变成透明
        raise KeyError(
            f'ui_tokens: 未知色键 {键!r}; 可用键示例: '
            f'bg-primary / text-primary / brand / focus-ring / status-success'
        ) from None


def 状态色(状态键: str, 夜间: bool = None):
    """取状态色二元组 (前景色, 浅容器色)。

    状态键 ∈ success/warning/error/pending/info/running/stopped/interrupted
    """
    fg_k, bg_k = 状态语义.get(状态键, 状态语义['pending'])
    return 取色(fg_k, 夜间), 取色(bg_k, 夜间)


# ---------------------------------------------------------------- 重刷登记
def 登记重刷(ctrl, 回调):
    """把"用了 取色() 的控件"登记进来, 主题切换时回调重设属性。

    为什么需要: 取色() 是构建期求值, 切主题不会自动重算。
    回调签名 `回调(ctrl) -> None`, 内部只改属性, **不调 update()**
    (项目硬约定: 只用子树级 ctrl.update(); 且 gui_app.toggle_theme
     末尾已有一次 page.update() 兜底刷出)。

    弱引用: 控件被 GC 后自动摘除, 不会泄漏。
    """
    import weakref
    with _状态锁:
        try:
            引用 = weakref.ref(ctrl)
        except TypeError:
            # 不支持弱引用的对象直接跳过 (不为此中断构建)
            return ctrl
        # 2026-10-04 (Phase 3 加固): 顺手压缩已死引用。
        # 页面 refresh() 常是"全量重建"(500 行表格一次构建就登记 1600+ 条, 搜索框
        # 每键又重建一次) —— 旧实现只在切主题时清理, 登记表会在长会话里单调增长、
        # 切主题遍历越来越慢。超过阈值做一次 O(n) 压缩, 摊销后每次仍是 O(1)。
        if len(_重刷表) >= _重刷表压缩阈值:
            _重刷表[:] = [(r, cb) for (r, cb) in _重刷表 if r() is not None]
        _重刷表.append((引用, 回调))
    return ctrl


def 清空重刷表():
    """测试/热重载用: 清空登记表"""
    with _状态锁:
        _重刷表.clear()


def 设置主题(夜间: bool, 立即重刷: bool = True):
    """切换主题状态并 (可选) 触发已登记控件的换色。

    调用点: IconRail.toggle_theme_icon() —— 它由 gui_app.toggle_theme()
    在 `page.theme_mode` 赋值之后、`page.update()` 之前调用, 是本轮
    唯一不需要改 gui_app.py 就能挂上的同步点。
    """
    global _当前夜间
    with _状态锁:
        _当前夜间 = bool(夜间)
        if not 立即重刷:
            return
        # 复制一份再遍历: 回调里可能会再登记新控件
        待刷 = list(_重刷表)
    for 弱引用, 回调 in 待刷:
        控件 = 弱引用()
        if 控件 is None:
            continue
        try:
            回调(控件)
        except Exception as _e:
            # 单个控件换色失败不能连累其它控件与主题切换本身。
            # 但必须留痕 —— 这里曾真的吞掉过一个 AttributeError
            # (ButtonStyle 在 0.86.5 没有 surface_tint_color),
            # 表现为"按钮切主题静默不掉色", 排查了很久。
            _静默记录('ui_tokens.设置主题', 控件, 回调, _e)
    # 顺手清掉已失效的弱引用
    with _状态锁:
        _重刷表[:] = [(r, c) for (r, c) in _重刷表 if r() is not None]


def _静默记录(出处, 控件, 回调, 异常=None):
    """换色异常留痕 (DEBUG 级, 沿用项目日志通道)"""
    try:
        import 日志 as _app_log
    except Exception:
        return
    try:
        _app_log.debug('UI', f'{出处}: 控件换色失败 '
                             f'(回调={getattr(回调, "__name__", 回调)!r}, '
                             f'{type(异常).__name__ if 异常 else "-"}: {异常})')
    except Exception:
        pass   # 刻意静默: 日志链路自身故障不能再抛


# ====================================================================
# 六、字号 / 字重 / 间距 / 圆角 / 阴影 / 过渡  (日间夜间同值)
# ====================================================================

# ---- 字号 (设计稿 --fs-*) ----
FS_TITLE   = 22     # --fs-title  页面/对话框大标题
FS_H1      = 20     # --fs-h1
FS_H2      = 17     # --fs-h2    卡片标题
FS_H3      = 15     # --fs-h3    输入框/列表主标题
FS_BODY    = 14     # --fs-body  正文
FS_SMALL   = 13     # --fs-small 辅助文字
FS_CAPTION = 12     # --fs-caption
FS_MICRO   = 11     # --fs-micro  徽章/微字

# ---- 字重 (设计稿只有 4 档) ----
FW_BOLD    = 700
FW_SEMI    = 600
FW_MEDIUM  = 500
FW_REGULAR = 400

# ---- 间距: 4px 栅格 ----
SP_1  = 4
SP_2  = 8
SP_3  = 12
SP_4  = 16
SP_5  = 20
SP_6  = 24
SP_7  = 28
SP_8  = 32
SP_9  = 36
SP_10 = 40

_间距表 = {1: SP_1, 2: SP_2, 3: SP_3, 4: SP_4, 5: SP_5,
           6: SP_6, 7: SP_7, 8: SP_8, 9: SP_9, 10: SP_10}


def 间距(n: int) -> int:
    """4px 栅格间距。间距(0)=0, 超界自动夹到 [0, 10]。"""
    if n <= 0:
        return 0
    return _间距表[min(n, 10)]


# ---- 圆角: 只此 4 档 + 胶囊 (设计稿硬约束, 不许新增中间值) ----
RADIUS_SM   = 4      # 控件 (按钮/输入)
RADIUS_MD   = 6      # 卡片内小方块 / 表格图标按钮
RADIUS_LG   = 8      # 卡片
RADIUS_XL   = 12     # 大面板
RADIUS_PILL = 999    # 胶囊 (徽章/筛选芯片)


# ---- 阴影: 克制版 (设计稿 4 档, 低透明度) ----
_阴影表 = {
    'sm': (2,  0, 0, 1, 'rgba(0,0,0,0.04)'),
    'md': (12, 0, 4, 0, 'rgba(0,0,0,0.08)'),
    'lg': (32, 0, 12, 0, 'rgba(0,0,0,0.12)'),
    'xl': (48, 0, 24, 0, 'rgba(0,0,0,0.16)'),
}


def 阴影(档: str = 'sm'):
    """返回 [ft.BoxShadow]。档 ∈ sm/md/lg/xl。

    克制原则: 卡片只用 sm, 浮层用 md, 弹窗用 lg/xl。日夜同值
    (设计稿阴影未按主题分档)。
    """
    import flet as ft
    模糊, 扩展, 横, 纵, 色 = _阴影表.get(档, _阴影表['sm'])
    return [ft.BoxShadow(blur_radius=模糊, spread_radius=扩展,
                         offset=ft.Offset(横, 纵), color=色)]


# ---- 过渡时长 (设计稿 3 档, ease-out) ----
DURATION_FAST   = 150     # 悬停/按下等即时反馈
DURATION_NORMAL = 250     # 常规状态切换
DURATION_SLOW   = 400     # 展开/收起


# ====================================================================
# 七、第三层: 组件规格常量 (设计稿组件规格表, 单位 px)
# ====================================================================
#  .btn 主/次     高34  內距 0 16  圆角 sm4  字号14/500
#  .btn-sm        高28  內距 0 12  圆角 sm4  字号13/500
#  .btn-lg        高40  內距 0 20  圆角 sm4  字号14/500
#  .btn-icon      34x34       0     sm4
#  .icon-btn 表格  36x32       0     md6
#  .chip-btn      高28  內距 0 12  胶囊    字号13/400
#  .badge         高20  內距 0 8   胶囊    字号11/500

BTN_H          = 34
BTN_PAD_X      = 16
BTN_FS         = FS_BODY      # 14
BTN_FW         = FW_MEDIUM    # 500
BTN_RADIUS     = RADIUS_SM    # 4

BTN_SM_H       = 28
BTN_SM_PAD_X   = 12
BTN_SM_FS      = FS_SMALL     # 13
BTN_SM_FW      = FW_MEDIUM    # 500

BTN_LG_H       = 40
BTN_LG_PAD_X   = 20
BTN_LG_FS      = FS_BODY      # 14
BTN_LG_FW      = FW_MEDIUM    # 500

ICON_BTN_W     = 34           # .btn-icon 正方形
ICON_BTN_H     = 34
ICON_BTN_R     = RADIUS_SM    # 4

TBL_ICON_BTN_W = 36           # .icon-btn 表格内图标按钮
TBL_ICON_BTN_H = 32
TBL_ICON_BTN_R = RADIUS_MD    # 6

CHIP_H         = 28
CHIP_PAD_X     = 12
CHIP_FS        = FS_SMALL     # 13
CHIP_FW        = FW_REGULAR   # 400
CHIP_RADIUS    = RADIUS_PILL

BADGE_H        = 20
BADGE_PAD_X    = 8
BADGE_FS       = FS_MICRO     # 11
BADGE_FW       = FW_MEDIUM    # 500
BADGE_RADIUS   = RADIUS_PILL

CARD_RADIUS    = RADIUS_LG    # 8
CARD_PADDING   = SP_3         # 12

# 空态/加载态尺寸 (states.py 用)
EMPTY_ICON_SIZE   = 44
LOADING_ICON_SIZE = 32

# 焦点环: 2px 焦点环色 + 2px 偏移, 仅键盘焦点时出现
FOCUS_RING_WIDTH  = 2
FOCUS_RING_OFFSET = 2


# ====================================================================
# 八、四态交互的语义约定 (给页面/组件实现时的统一口径)
# ====================================================================
#  hover   : 用 ButtonStyle.overlay_color (Flet 原生支持, 免手绘)
#  active  : 同 overlay_color 的 pressed 键
#  focus   : on_focus 时加 FOCUS_RING_WIDTH 边框 (焦点环色), on_blur 撤掉
#            —— Container 无 on_focus (已内省确认), 自绘控件做不了键盘焦点
#  disabled: 文字用 tertiary/quaternary **实色**, 不靠降透明度
#            (设计稿明文 opacity:1); 语义用 MouseCursor.FORBIDDEN
#  胶囊选中: 浅底 + 深字 + 描边, **不**用实心块压白字

DISABLED_FG_KEY   = 'text-tertiary'     # 禁用态文字 (实色, 不降透明度)
DISABLED_BG_KEY   = 'bg-tertiary'       # 禁用态底色


def 禁用前景(夜间: bool = None) -> str:
    return 取色(DISABLED_FG_KEY, 夜间)


def 禁用底色(夜间: bool = None) -> str:
    return 取色(DISABLED_BG_KEY, 夜间)
