# -*- coding: utf-8 -*-
"""states — 加载态 / 空态 / 错误态 三个可复用状态组件

背景: 空态此前在每个页面各写一遍 (task_table.py:180、dead_book_page.py:108、
history_page.py 等), 文案与视觉不统一。本模块抽出来统一, **本轮不改动
那些调用点** (下一轮页面改造时替换即可)。

设计稿依据 (界面设计预览/index.html):
  - 空态: 44px 图标 + 标题(--fs-h3) + 说明(--fs-body, 次级文字) + 可选动作
  - 两种空态必须区分: "首次为空"(引导用户开始) vs "筛选后为空"
    (引导用户清除筛选) —— 后者必须带"清除筛选"动作, 否则用户会误以为数据没了
  - 加载态: ProgressRing (不定进度) / ProgressBar (定进度) + 说明文字
  - 错误态: 错误色图标 + 说明 + 重试按钮

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

    主体 = ft.Column(
        [
            ft.Container(content=动效, height=48,
                         alignment=ft.Alignment.CENTER),
            ft.Text(说明, size=SIZE_BODY, color=取色('text-secondary'),
                    font_family=FONT_STACK, text_align=ft.TextAlign.CENTER),
        ],
        spacing=ui_tokens.SP_3,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        tight=True,
    )

    # 加载中文案色随主题重刷
    def _换文字(c):
        c.controls[-1].color = 取色('text-secondary')

    容器 = ft.Container(content=主体, height=高, alignment=ft.Alignment.CENTER)
    登记重刷(容器, _换文字)
    return 容器


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
         说明: str = '', 操作按钮=None) -> ft.Control:
    """通用空态: 44px 图标 + 标题 + 说明 + 可选恢复动作, 整体居中。

    参数:
        图标       —— ft.Icons.* 枚举
        标题       —— --fs-h3 15px
        说明       —— --fs-body 14px 次级文字, 可空
        操作按钮   —— ft.Control (建议用 ui_theme 的按钮工厂), 可空

    ⚠️ "首次为空"与"筛选后为空"请用下面两个专用函数, 它们文案与
       动作不同 —— 别都调这个通用函数。
    """
    容器 = _空态主体(图标, 标题, 说明, 操作按钮, 取色('text-quaternary'))
    return 容器


def 首次为空(操作按钮=None, 图标=ft.Icons.INBOX_OUTLINED) -> ft.Control:
    """首次为空 (用户还没建过任何记录) —— 引导"开始第一件事"。"""
    return _空态主体(
        图标,
        '还没有任何记录',
        '创建第一条记录后, 这里会显示完整的列表与统计。',
        操作按钮,
        取色('text-quaternary'),
    )


def 筛选后为空(清除筛选回调=None, 说明: str = '',
              图标=ft.Icons.SEARCH_OFF_ROUNDED) -> ft.Control:
    """筛选后为空 —— **必须**提供"清除筛选"动作。

    没有这个动作, 用户会以为数据被删了 (实测这是空态最常见的投诉)。
    """
    from .ui_theme import tonal_btn     # 局部导入: 避免 ui_theme<->states 循环

    动作 = 操作 = None
    if 清除筛选回调 is not None:
        操作 = tonal_btn('清除筛选', icon=ft.Icons.FILTER_ALT_OFF,
                         on_click=清除筛选回调)
        动作 = 操作
    文案 = 说明 or '没有符合当前筛选条件的记录。'
    return _空态主体(图标, '没有匹配的结果', 文案, 动作,
                     取色('text-quaternary'))


def _空态主体(图标, 标题, 说明, 操作按钮, 图标色) -> ft.Control:
    """空态内部结构 (三个空态函数共用, 保证视觉一致)"""
    列 = [
        ft.Container(
            content=ft.Icon(图标, size=ui_tokens.EMPTY_ICON_SIZE,
                            color=图标色),
            alignment=ft.Alignment.CENTER,
        ),
        ft.Text(标题, size=SIZE_LABEL, weight=WEIGHT_SUBTITLE,
                color=取色('text-primary'), font_family=FONT_STACK,
                text_align=ft.TextAlign.CENTER),
    ]
    if 说明:
        列.append(ft.Text(说明, size=SIZE_BODY, color=取色('text-secondary'),
                          font_family=FONT_STACK,
                          text_align=ft.TextAlign.CENTER))
    if 操作按钮 is not None:
        列.append(操作按钮)

    主体 = ft.Column(列, spacing=ui_tokens.SP_2,
                     horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                     tight=True)

    def _换色(c):
        c.controls[0].content.color = 取色('text-quaternary')
        c.controls[1].color = 取色('text-primary')
        if len(c.controls) > 2:
            c.controls[2].color = 取色('text-secondary')

    容器 = ft.Container(
        content=主体,
        alignment=ft.Alignment.CENTER,
        padding=ft.Padding.symmetric(horizontal=ui_tokens.SP_6,
                                     vertical=ui_tokens.SP_8),
        expand=True,
    )
    return 登记重刷(容器, _换色)


# ---------------------------------------------------------------- 错误态
def 错误态(标题: str = '出错了', 说明: str = '',
           重试回调=None, 重试文案: str = '重试') -> ft.Control:
    """错误态: 错误色图标 + 说明 + 重试按钮。

    参数:
        标题       —— --fs-h3 15px
        说明       —— 具体原因 (技术性文案放这里, 不要塞进标题)
        重试回调   —— 有则显示重试按钮; 无则不显示 (别给没用的按钮)
        重试文案   —— 默认"重试"
    """
    前景, _底 = 状态色('error')

    列 = [
        ft.Container(
            content=ft.Icon(ft.Icons.ERROR_OUTLINE_ROUNDED,
                            size=ui_tokens.EMPTY_ICON_SIZE, color=前景),
            alignment=ft.Alignment.CENTER,
        ),
        ft.Text(标题, size=SIZE_LABEL, weight=WEIGHT_SUBTITLE,
                color=取色('text-primary'), font_family=FONT_STACK,
                text_align=ft.TextAlign.CENTER),
    ]
    if 说明:
        列.append(ft.Text(说明, size=SIZE_BODY, color=取色('text-secondary'),
                          font_family=FONT_STACK,
                          text_align=ft.TextAlign.CENTER,
                          max_lines=3, overflow=ft.TextOverflow.ELLIPSIS))
    if 重试回调 is not None:
        from .ui_theme import filled_btn     # 局部导入: 避免循环导入
        列.append(filled_btn(重试文案, icon=ft.Icons.REFRESH,
                             on_click=重试回调))

    主体 = ft.Column(列, spacing=ui_tokens.SP_2,
                     horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                     tight=True)

    def _换色(c):
        c.controls[0].content.color = 状态色('error')[0]
        c.controls[1].color = 取色('text-primary')
        if len(c.controls) > 2:
            c.controls[2].color = 取色('text-secondary')

    容器 = ft.Container(
        content=主体,
        alignment=ft.Alignment.CENTER,
        padding=ft.Padding.symmetric(horizontal=ui_tokens.SP_6,
                                     vertical=ui_tokens.SP_8),
        expand=True,
    )
    return 登记重刷(容器, _换色)


# ---------------------------------------------------------------- 状态切换壳
def 状态容器(加载控件=None, 空控件=None, 错误控件=None, 正常控件=None):
    """把"加载/空/错误/正常"四选一包装成一个可整体替换的容器。

    页面侧用法 (下一轮改造的推荐姿势)::

        壳, 槽 = 状态容器()
        壳.content = 加载态('正在读取任务…')
        # 数据到了:
        壳.content = 正常控件 or 槽.置空(清除筛选回调=重置筛选)

    返回 (壳, 控制器); 控制器提供 置加载/置空/置错误/置正常 四个方法,
    每个只改 content 并返回自身 —— 调用方自己决定要不要 ctrl.update()
    (项目硬约定: 只用子树级 update, 禁 page.update)。
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

        def 置空(self, 首次: bool = False, 清除筛选回调=None, 说明: str = ''):
            if 首次:
                return self._换(首次为空())
            return self._换(筛选后为空(清除筛选回调=清除筛选回调, 说明=说明))

        def 置错误(self, 标题: str = '出错了', 说明: str = '', 重试回调=None):
            return self._换(错误态(标题, 说明, 重试回调))

        def 置正常(self, 控件=None):
            return self._换(控件 if 控件 is not None else self._正常)

    return 壳, _控制器(壳)
