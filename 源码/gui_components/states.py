# -*- coding: utf-8 -*-
"""states — 加载态 / 空态 / 错误态 三个可复用状态组件

背景: 空态此前在每个页面各写一遍 (task_table.py:180、dead_book_page.py:108、
history_page.py 等), 文案与视觉不统一。本模块抽出来统一。
Phase 4 批 4 (2026-10-07): **接线完成** —— 六个页面的空态/加载/错误态已全部改走本模块,
故下面"本轮不改动那些调用点"的旧说法已作废。

设计稿依据 (界面设计预览/index.html `.empty-state`, 第 1306-1330 行):
  - 图标 48px + **opacity 0.4**; 标题 --fs-h3(15) / **字重 500** / --text-secondary;
    说明 --fs-small(13) / --text-tertiary; 留白 --sp-3(12); 内边距 --sp-8(32)
  - 两种空态必须区分: "首次为空"(引导用户开始) vs "筛选后为空"
    (引导用户清除筛选) —— 后者必须带"清除筛选"动作, 否则用户会误以为数据没了
  - ⚠️ 设计稿的 `max-width:300px`(说明文字) **未实现**: Flet 的 Text 无 max_width,
    而用固定宽 Container 会在 320px 抽屉里溢出 → 交由父容器宽度自然约束。
  - ⚠️ 每个页面的**文案仍由调用方给** (设计稿样卡也是页面专属文案:
    「暂无手机端记录 / 手机发起的抓取任务会实时出现在这里」) → 本模块只统一"形",
    不硬塞通用文案; 不传时才回落到通用兜底文案。

四态与可访问性:
  - 三个组件都只用 ft.Container (无焦点能力), 焦点环做不了 —— 见 ui_theme
    文件头说明。自绘控件的键盘焦点是 Flet 硬限制, 不做假实现。
  - 空态/错误态的图标 + 文字是纯展示, 用 semantics_label 兜一层读屏标签。
"""
import flet as ft

from .ui_fluent import (
    FONT_STACK, SIZE_BODY, SIZE_LABEL, SIZE_SMALL, WEIGHT_BODY,
    WEIGHT_SUBTITLE, WEIGHT_EMPHASIS,
)
from .ui_tokens import 取色, 状态色, 登记重刷
from . import ui_tokens


# ---------------------------------------------------------------- 加载态
def 加载态(说明: str = '加载中…', 进度: float = None, 高: int = None) -> ft.Control:
    """加载态。

    参数:
        说明   —— 文案 (设计稿 --fs-body)
        进度   —— None = 不定进度 (ProgressRing);
                  0.0~1.0 = 定进度 (ProgressBar 线性条)
        高     —— 整体高度; None = 自适应内容

    进度条给了的话, 环退化为线性条 —— 两者不同时出现, 避免视觉噪音。
    """
    if 进度 is None:
        动效 = ft.ProgressRing(
            width=ui_tokens.LOADING_ICON_SIZE,
            height=ui_tokens.LOADING_ICON_SIZE,
            stroke_width=3,
            color=取色('brand'),
            bgcolor=取色('border-subtle'),
        )
        # 不定进度: 颜色随主题走
        登记重刷(动效, lambda c: (
            setattr(c, 'color', 取色('brand')),
            setattr(c, 'bgcolor', 取色('border-subtle')),
        ))
    else:
        进度 = max(0.0, min(1.0, float(进度)))
        动效 = ft.ProgressBar(
            value=进度,
            bar_height=4,
            border_radius=2,
            color=取色('brand'),
            bgcolor=取色('border-subtle'),
        )
        登记重刷(动效, lambda c: (
            setattr(c, 'color', 取色('brand')),
            setattr(c, 'bgcolor', 取色('border-subtle')),
        ))

    # 逐控件登记换色 (理由同 _空态主体: 登记外层 Container 再按下标取子控件会
    # AttributeError → 回调静默失败 → 切主题后加载文案仍是日间色)
    说明控件 = ft.Text(说明, size=SIZE_BODY, color=取色('text-secondary'),
                     font_family=FONT_STACK, text_align=ft.TextAlign.CENTER)
    登记重刷(说明控件, lambda c: setattr(c, 'color', 取色('text-secondary')))
    主体 = ft.Column(
        [
            ft.Container(content=动效, height=48,
                         alignment=ft.Alignment.CENTER),
            说明控件,
        ],
        spacing=ui_tokens.SP_3,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        tight=True,
    )

    return ft.Container(content=主体, height=高, alignment=ft.Alignment.CENTER)


def 骨架屏(行数: int = 3, 高: int = 16) -> ft.Control:
    """骨架屏占位 (列表加载时替代"转圈", 避免布局跳动)。

    刻意做成**静态灰块**而非真动画: Flet 无 CSS 关键帧动画, 假 shimmer
    只能靠 on_animation 定时器驱动, 收益低复杂度高, 不做。
    """
    条 = []
    for _ in range(max(1, 行数)):
        条.append(ft.Container(
            height=高,
            bgcolor=取色('bg-sidebar-hover'),
            border_radius=ui_tokens.RADIUS_SM,
        ))
    列 = ft.Column(条, spacing=ui_tokens.SP_2, tight=True)
    登记重刷(列, lambda c: [
        setattr(子, 'bgcolor', 取色('bg-sidebar-hover')) for 序 in c.controls
        for 子 in ([序] if hasattr(序, 'bgcolor') else [])
    ])
    return ft.Container(content=列, padding=ft.Padding.symmetric(
        horizontal=ui_tokens.SP_4, vertical=ui_tokens.SP_3))


# ---------------------------------------------------------------- 空态
def 空态(图标=ft.Icons.INBOX_OUTLINED, 标题: str = '暂无数据',
         说明: str = '', 操作按钮=None, 图标色: str = '',
         填满: bool = True) -> ft.Control:
    """通用空态: 48px 图标 + 标题 + 说明 + 可选恢复动作, 整体居中。

    参数:
        图标       —— ft.Icons.* 枚举
        标题       —— --fs-h3 15px
        说明       —— --fs-small 13px 三级文字, 可空
        操作按钮   —— ft.Control (建议用 ui_theme 的按钮工厂), 可空
        图标色     —— **令牌键** (如 'status-success'); 空串 = 用设计稿默认的
                      三级文字色。给页面保留语义色的口子: 死书清单的
                      「一本死书都没有」是**好消息**, 用绿色对勾比灰图标达意。
        填满       —— True = expand 撑满父容器并垂直居中 (页面级用法);
                      **放进 ListView 时必须给 False** —— 可滚动列表的高度是无界的,
                      子控件再 expand 会被算成 0 高 → 空态直接看不见。

    ⚠️ "首次为空"与"筛选后为空"请用下面两个专用函数, 它们默认文案不同 ——
       别都调这个通用函数。
    """
    return _空态主体(图标, 标题, 说明, 操作按钮, 图标色, 填满)


def 首次为空(操作按钮=None, 图标=ft.Icons.INBOX_OUTLINED,
            标题: str = '', 说明: str = '', 图标色: str = '',
            填满: bool = True) -> ft.Control:
    """首次为空 (用户还没建过任何记录) —— 引导"开始第一件事"。

    `标题`/`说明` 不传时回落通用文案。**建议各页传自己的文案**: 设计稿样卡
    用的也是页面专属文案, 通用文案对"接下来该干什么"的指引远不如专属文案。
    """
    return _空态主体(
        图标,
        标题 or '还没有任何记录',
        说明 or '创建第一条记录后, 这里会显示完整的列表与统计。',
        操作按钮,
        图标色,
        填满,
    )


def 筛选后为空(清除筛选回调=None, 说明: str = '',
              图标=ft.Icons.SEARCH_OFF_ROUNDED, 标题: str = '',
              图标色: str = '', 填满: bool = True) -> ft.Control:
    """筛选后为空 —— **必须**提供"清除筛选"动作。

    没有这个动作, 用户会以为数据被删了 (实测这是空态最常见的投诉)。
    """
    from .ui_theme import tonal_btn     # 局部导入: 避免 ui_theme<->states 循环

    动作 = None
    if 清除筛选回调 is not None:
        动作 = tonal_btn('清除筛选', icon=ft.Icons.FILTER_ALT_OFF,
                        on_click=清除筛选回调)
    return _空态主体(图标, 标题 or '没有匹配的结果',
                    说明 or '没有符合当前筛选条件的记录。', 动作, 图标色, 填满)


def _空态主体(图标, 标题, 说明, 操作按钮, 图标色: str = '',
            填满: bool = True) -> ft.Control:
    """空态内部结构 (三个空态函数共用, 保证视觉一致)。

    尺寸/字重/色阶全部对齐设计稿 `.empty-state` (见模块 docstring)。
    图标色: 给了令牌键就用它, 否则用设计稿的三级文字色 + 0.4 透明度。
    """
    _键 = 图标色 or 'text-tertiary'
    图标控件 = ft.Icon(图标, size=ui_tokens.EMPTY_ICON_SIZE, color=取色(_键))
    if not 图标色:
        图标控件.opacity = 0.4      # 设计稿 .empty-state-icon { opacity: 0.4 }
    # ⚠️ 换色必须**逐控件登记**, 不能登记外层容器再按下标取子控件:
    # 外层是 Container (只有 content), 旧写法 `c.controls[0].content.color`
    # 必然 AttributeError → 回调静默失败 → 切主题后标题/说明/图标仍是日间色。
    # 该 bug 自 Phase 3 就在, 只是当时死书页用的还是手写空态、未被主题护栏覆盖;
    # 批 4 把页面接过来后, 测试/test_主题重刷.py 当场抓出 (K45 同族"半迁移")。
    登记重刷(图标控件, lambda c: setattr(c, 'color', 取色(_键)))
    标题控件 = ft.Text(标题, size=SIZE_LABEL, weight=WEIGHT_EMPHASIS,
                     color=取色('text-secondary'), font_family=FONT_STACK,
                     text_align=ft.TextAlign.CENTER)
    登记重刷(标题控件, lambda c: setattr(c, 'color', 取色('text-secondary')))
    列 = [
        ft.Container(content=图标控件, alignment=ft.Alignment.CENTER),
        标题控件,
    ]
    if 说明:
        说明控件 = ft.Text(说明, size=SIZE_SMALL, color=取色('text-tertiary'),
                          font_family=FONT_STACK,
                          text_align=ft.TextAlign.CENTER)
        登记重刷(说明控件, lambda c: setattr(c, 'color', 取色('text-tertiary')))
        列.append(说明控件)
    if 操作按钮 is not None:
        列.append(操作按钮)

    主体 = ft.Column(列, spacing=ui_tokens.SP_3,
                     horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                     tight=True)

    return ft.Container(
        content=主体,
        alignment=ft.Alignment.CENTER,
        padding=ft.Padding.symmetric(horizontal=ui_tokens.SP_8,
                                     vertical=ui_tokens.SP_8),
        expand=填满,
    )


# ---------------------------------------------------------------- 错误态
def 错误态(标题: str = '出错了', 说明: str = '',
           重试回调=None, 重试文案: str = '', 填满: bool = True) -> ft.Control:
    """错误态: 错误色图标 + 说明 + 重试按钮。

    参数:
        标题       —— --fs-h3 15px
        说明       —— 具体原因 (技术性文案放这里, 不要塞进标题)
        重试回调   —— 有则显示重试按钮; 无则不显示 (别给没用的按钮)
        重试文案   —— 默认"重试"

    ⚠️ 设计稿**没有**错误态样卡 (只定义了 `.empty-state`), 故这里是本模块
    自定的形: 与空态同尺寸同留白, 但标题用 text-primary **不降级** ——
    出错需要引人注意, 而空态是正常状态、刻意做淡 (设计稿就是淡化处理)。
    ⚠️ **重试回调必给**: 读失败类错误若不给重试入口, 用户只能重启程序。
    """
    前景, _底 = 状态色('error')

    # 逐控件登记换色 (理由同 _空态主体: 登记外层 Container 再按下标取子控件会
    # AttributeError → 回调静默失败 → 切主题后错误态仍是日间色)
    图标控件 = ft.Icon(ft.Icons.ERROR_OUTLINE_ROUNDED,
                     size=ui_tokens.EMPTY_ICON_SIZE, color=前景)
    登记重刷(图标控件, lambda c: setattr(c, 'color', 状态色('error')[0]))
    标题控件 = ft.Text(标题, size=SIZE_LABEL, weight=WEIGHT_EMPHASIS,
                     color=取色('text-primary'), font_family=FONT_STACK,
                     text_align=ft.TextAlign.CENTER)
    登记重刷(标题控件, lambda c: setattr(c, 'color', 取色('text-primary')))
    列 = [
        ft.Container(content=图标控件, alignment=ft.Alignment.CENTER),
        标题控件,
    ]
    if 说明:
        说明控件 = ft.Text(说明, size=SIZE_SMALL, color=取色('text-secondary'),
                          font_family=FONT_STACK,
                          text_align=ft.TextAlign.CENTER,
                          max_lines=3, overflow=ft.TextOverflow.ELLIPSIS)
        登记重刷(说明控件, lambda c: setattr(c, 'color', 取色('text-secondary')))
        列.append(说明控件)
    if 重试回调 is not None:
        from .ui_theme import filled_btn     # 局部导入: 避免循环导入
        列.append(filled_btn(重试文案 or '重试', icon=ft.Icons.REFRESH,
                             on_click=重试回调))

    主体 = ft.Column(列, spacing=ui_tokens.SP_3,
                     horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                     tight=True)

    return ft.Container(
        content=主体,
        alignment=ft.Alignment.CENTER,
        padding=ft.Padding.symmetric(horizontal=ui_tokens.SP_8,
                                     vertical=ui_tokens.SP_8),
        expand=填满,
    )


# ---------------------------------------------------------------- 状态切换壳
def 状态容器(加载控件=None, 空控件=None, 错误控件=None, 正常控件=None):
    """把"加载/空/错误/正常"四选一包装成一个可整体替换的容器。

    页面侧用法::

        壳, 槽 = 状态容器()
        壳.content = 加载态('正在读取任务…')
        # 数据到了:
        壳.content = 正常控件 or 槽.置空(清除筛选回调=重置筛选)

    返回 (壳, 控制器); 控制器提供 置加载/置空/置错误/置正常 四个方法,
    每个只改 content 并返回自身 —— 调用方自己决定要不要 ctrl.update()
    (项目硬约定: 只用子树级 update, 禁 page.update)。

    ⚠️ 本壳的定位是"**同一块区域**要轮流显示四态"的场合 (如列表区)。
    页面级的"首次为空 vs 筛选后为空"仍应由页面自己按 `if 有筛选` 分支决定,
    不要用本壳代替那个判断 —— 判据只有页面知道。
    """
    壳 = ft.Container(expand=True)

    class _控制器:
        def __init__(self, 外壳):
            self.外壳 = 外壳
            self._正常 = 正常控件

        def _换(self, 控件):
            if 控件 is not None:
                self.外壳.content = 控件
            return self.外壳

        def 置加载(self, 说明: str = '加载中…', 进度=None):
            return self._换(加载态(说明, 进度))

        def 置空(self, 首次: bool = False, 清除筛选回调=None, 说明: str = '',
                 标题: str = '', 图标色: str = '', 填满: bool = True):
            if 首次:
                return self._换(首次为空(标题=标题, 说明=说明, 图标色=图标色,
                                       填满=填满))
            return self._换(筛选后为空(清除筛选回调=清除筛选回调, 说明=说明,
                                     标题=标题, 图标色=图标色, 填满=填满))

        def 置错误(self, 标题: str = '出错了', 说明: str = '', 重试回调=None,
                  填满: bool = True):
            return self._换(错误态(标题, 说明, 重试回调, 填满=填满))

        def 置正常(self, 控件=None):
            return self._换(控件 if 控件 is not None else self._正常)

    return 壳, _控制器(壳)
