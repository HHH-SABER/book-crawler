# -*- coding: utf-8 -*-
"""死书清单页 (2026-10-03, 死书处理机制 阶段4): 死书的集中管理与独立入口。

为什么单独一页 (用户拍板"死书清单页独立管理, 无全局偏好开关"):
  死书处置是**低频高影响**动作 —— 删任务/书架/网站清单三处记录, 误删不可逆。
  放在任务表里顺手点删除太危险; 做成独立页 = 用户先看清全貌(哪些书、什么
  原因、几次了), 再决定处置, 天然多一道确认。

与阶段3 弹窗的分工:
  弹窗 = 抓取现场的**即时**询问 (用户可能没在电脑前, 会点"稍后处理")
  本页 = **事后**总账 (稍后处理的书在这里找得到, 不会丢)

三条设计约束 (勿推翻):
 ① **重新检测是用户手动触发的动作, 绝不进页面 2s 轮询** —— 每本都要真发
     请求 (重跑整条抓取判定链路), 轮询会在用户不知情时反复烧流量、且可能
     对同一站点并发轰击。行内按钮 + 页头批量按钮是唯一入口 (阶段5)。
 ② 动作**复用阶段3 的语义**: 删 = 三处编排(任务/书架/网站清单), 恒不删产物;
     忽略 = 置 已忽略; 不在这里重造删除逻辑。
 ③ 列表是**读快照**, 所有 IO 走 死书处理 模块, 本页不直接碰 JSON。
 ④ **恢复判定不归本页管**: 抓成功后由 task_manager 在 completed 分支调
     `死书处理.标记已恢复` 清理记录 (数据层, 与 UI 无关)。本页只负责"发起",
     发起后记录保持原状态不动 —— 是"清掉"还是"次数+1"由抓取结果决定。

刷新策略: 切页时 refresh() + 可见时 2s 轮询 (同 remote_page, 数据源在磁盘,
其他会话/远控也可能改清单)。空清单给明确空态, 不给空白页。
"""
import flet as ft

try:
    import 日志 as _app_log          # 留痕通道 (桥模式, 同 remote_page)
except Exception:
    _app_log = None


def _dbg(source: str, message: str):
    """异常留痕 (DEBUG 级: 只落盘不 console 镜像, 避免高频刷屏)"""
    if _app_log is not None:
        try:
            _app_log.debug(source, message)
        except Exception:
            pass  # 刻意静默: try 块本身在写日志会递归 (日志链路兜底)


from ..ui_fluent import (txt, FONT_STACK, FONT_TERMINAL,
                          SIZE_MICRO, SIZE_TINY, SIZE_SMALL, SIZE_BODY,
                         WEIGHT_SUBTITLE, WEIGHT_BODY, WEIGHT_EMPHASIS,
                         open_dialog, close_dialog, 提示条)
from ..ui_theme import page_header
# Phase 3 (2026-10-04): 页面颜色一律走令牌 + 登记重刷。旧写法 `from ..ui_fluent
# import MORANDI_*` 绑到的是**构建期求值的字符串**, 切主题时
# ui_fluent.刷新兼容常量() 的 globals().update 改不动页面本地引用
# → 切夜间主题这些控件纹丝不动 (见 文档/审查报告汇总.md 的 Phase 3 结论)。
from ..ui_tokens import 取色, 登记重刷
from .. import states


# 三态 → 展示配置 (与 死书处理.状态_* 严格对应; 缺一回落 待确认)
# Phase 3: 色值改为存**令牌键** —— 色值在构建期由 取色(键) 求值, 且必须
# 配套 登记重刷 才能在切主题时重算 (只写 取色 不登记 = 依然不会重刷)。
_状态展示 = {
    '待确认': ('status-warning', '待确认'),
    '已忽略': ('status-pending', '已忽略'),
    '已删除': ('status-success', '已删除'),
}
_筛选全部 = '全部'
# 批量重检单次上限: 每本都要真发一轮请求, 无上限会在用户点一下的瞬间
# 对同一站点并发轰击几十次 (被封 + 堵死同域闸门)。超限如实报数, 让用户分批。
_批量上限 = 10


def _整数(值, 默认: int = 0) -> int:
    """安全取整 (清单是用户可编辑的 JSON, 脏字段不能把整页渲染炸掉)"""
    if isinstance(值, bool):
        return 默认
    try:
        return int(值)
    except (TypeError, ValueError):
        return 默认


def _拼接_dot(片段: list) -> ft.Row:
    """把若干文本片段用设计稿的 `·` 分隔点串成一行 (`.dot-sep`, opacity 0.5)。

    设计稿 meta 行 = `URL · HTTP 码 · 判定于 <时间> · 已抓 N 章`,
    分隔点在相邻片段**之间** (首尾不加), 与 .dot-sep 的用法一致。
    """
    controls = []
    for _i, _c in enumerate(片段):
        if _i:
            controls.append(ft.Text('·', size=SIZE_MICRO, opacity=0.5,
                                    color=取色('text-tertiary'),
                                    font_family=FONT_STACK))
        controls.append(_c)
    return ft.Row(controls, spacing=6, tight=True, wrap=True)


class DeadBookPage:
    """死书清单页 (main 装配: page / task_manager 注入)"""

    def __init__(self):
        self.page = None
        self.task_manager = None
        self._状态筛选 = _筛选全部
        self._类型筛选 = _筛选全部
        self._列表 = None
        self._摘要 = None
        self._空态 = None
        self._筛选空态 = None     # 「筛选后为空」统一空态槽 (Phase 3 UX, 与 _空态 互斥)
        self._类型下拉 = None
        self._上次签名 = None     # 列表签名, 无变化跳过重建

    # ---------------------------------------------------------------- 查询
    @staticmethod
    def _取记录(状态: str = '', 类型: str = ''):
        """读死书清单 (IO 全在 死书处理 内, 失败回落空表不抛)"""
        try:
            import 死书处理
            return 死书处理.列出(状态=状态, 类型=类型)
        except Exception as _e:
            _dbg("死书清单页", f'读取死书清单失败: {type(_e).__name__}: {_e}')
            return []

    def _当前类型集(self) -> list:
        """当前筛选下的类型集合 (供类型下拉的选项来源)"""
        return sorted({(r.get('类型') or '未知') for r in self._取记录()})

    def _筛选后(self) -> list:
        记录 = self._取记录() if self._状态筛选 == _筛选全部 \
            else self._取记录(状态=self._状态筛选)
        if self._类型筛选 != _筛选全部:
            记录 = [r for r in 记录 if (r.get('类型') or '未知') == self._类型筛选]
        return 记录

    # ---------------------------------------------------------------- 构建
    def build(self):
        # Phase 3: 取色() 只在构建期取值, 必须配 登记重刷 —— 否则切主题仍不变色
        self._摘要 = 登记重刷(
            txt("—", size=SIZE_SMALL, weight=WEIGHT_BODY,
                color=取色('text-secondary'), font_family=FONT_STACK),
            lambda c: setattr(c, 'color', 取色('text-secondary')))
        # scroll=ALWAYS: 常显滚动条 (2026-10-03 八项需求#6 统一可见滚动条)
        self._列表 = ft.Column(spacing=6, tight=True, scroll=ft.ScrollMode.ALWAYS)
        # Phase 3: 图标/说明文字同样走令牌 + 登记重刷
        # 批 4 (2026-10-07): 手写空态 → 统一状态组件。
        # **图标色保留语义绿**: "一本死书都没有"是好消息, 灰图标表达不出这一点 ——
        # states.空态 的 图标色 参数就是为这种页面语义开的唯一口子。
        # 填满=False: _列表 是 scroll=ALWAYS 的 Column, 无界高度里 expand 会算成 0 高。
        # 文案原样保留 (测试/test_dead_book_page.py 用源码断言钉着"死书清单为空")。
        self._空态 = states.空态(
            图标=ft.Icons.CHECK_CIRCLE_OUTLINE, 标题='死书清单为空',
            说明='抓取失败若被判定为「书已删除」会记到这里, 可在此集中处置。\n'
                 '若列表为空但任务表有「书已删除」行, 可刷新本页。',
            图标色='status-success', 填满=False)
        # 「筛选后为空」槽 (Phase 3 UX): 有数据但被筛选条件滤空时用它, 不再是一片空白
        self._筛选空态 = ft.Container(visible=False)
        # 批 4 (2026-10-07): build() 不读数据 (数据在切页/轮询时读) —— 旧实现让
        # _空态 默认可见, 于是**首帧先谎报一次"死书清单为空"**再被真实数据覆盖。
        # 现在首帧显示加载态, 首次 refresh() 后收起 (空态只有读到空清单才出现)。
        self._加载槽 = ft.Container(
            content=states.加载态('正在读取死书清单…'), visible=True)
        self._空态.visible = False

        头 = page_header(
            "死书清单",
            "被判定为书已删除/不可读的书。删除会同时移除任务、书架与网站清单记录; "
            "已下载的文件不会被删除。",
            actions=[
                ft.TextButton("重检当前筛选", icon=ft.Icons.RESTART_ALT,
                              on_click=lambda e: self._批量重检()),
                ft.TextButton("刷新", icon=ft.Icons.REFRESH,
                              on_click=lambda e: self._切筛选(
                                  self._状态筛选, self._类型筛选)),
            ])

        return ft.Column([
            头,
            self._筛选栏(),
            self._摘要,
            ft.Container(content=ft.Column([self._列表, self._加载槽,
                                            self._空态, self._筛选空态],
                                          spacing=0, expand=True),
                         expand=True),
        ], expand=True, spacing=10)

    def _筛选栏(self):
        """状态分段 + 类型下拉。分段用 SegmentedButton 风格的胶囊行(自绘可控)。"""
        状态按钮 = []
        for s in (_筛选全部, '待确认', '已忽略', '已删除'):
            状态按钮.append(self._胶囊(s, self._状态筛选 == s,
                                       lambda e, v=s: self._切筛选(v, self._类型筛选)))
        # flet 0.86: Dropdown 用 on_select(无 on_change), 同 history_page 约定
        self._类型下拉 = ft.Dropdown(
            value=_筛选全部,
            options=[ft.dropdown.Option(_筛选全部, "全部类型")],
            width=170, dense=True,
            label="类型",
            text_style=ft.TextStyle(size=SIZE_SMALL, font_family=FONT_STACK),
            on_select=self._类型变更)
        return ft.Row([
            ft.Row(状态按钮, spacing=6),
            ft.Container(expand=True),
            self._类型下拉,
        ], spacing=10)

    def _胶囊(self, 文本: str, 选中: bool, on_click) -> ft.Container:
        """筛选胶囊 (选中态: 强调底色 + 深字; 未选中: 中性)"""
        # Phase 3: 未选中的次级字色走令牌 (取色) + 登记重刷; 选中态与底色用的
        # ft.Colors.* 是 M3 语义别名, 由 Flet 按 theme_mode 自适应, 保持原样。
        胶囊字 = ft.Text(文本, size=SIZE_SMALL,
                        weight=(WEIGHT_EMPHASIS if 选中 else WEIGHT_BODY),
                        color=(ft.Colors.ON_PRIMARY_CONTAINER if 选中
                               else 取色('text-secondary')),
                        font_family=FONT_STACK)
        if not 选中:
            登记重刷(胶囊字, lambda c: setattr(c, 'color', 取色('text-secondary')))
        return ft.Container(
            content=胶囊字,
            padding=ft.Padding.symmetric(horizontal=12, vertical=7),
            border_radius=16, ink=True, on_click=on_click,
            bgcolor=(ft.Colors.PRIMARY_CONTAINER if 选中
                     else ft.Colors.SURFACE_CONTAINER),
        )

    def _切筛选(self, 状态: str, 类型: str = None):
        self._状态筛选 = 状态
        if 类型 is not None:
            self._类型筛选 = 类型
        self._同步类型下拉()      # 类型集合可能随状态筛选变化
        self._上次签名 = None        # 强制重建
        self.refresh()

    def _同步类型下拉(self):
        """刷新类型下拉选项 (类型集合随状态筛选变化: 全部态有4类, 待确认可能只有2类)。

        保持当前选中项: 若当前类型在新集合里消失 → 回落"全部类型"。
        """
        if self._类型下拉 is None:
            return
        类型集 = self._当前类型集()
        self._类型下拉.options = [ft.dropdown.Option(_筛选全部, "全部类型")] + [
            ft.dropdown.Option(t, t) for t in 类型集]
        if self._类型筛选 != _筛选全部 and self._类型筛选 not in 类型集:
            self._类型筛选 = _筛选全部
        self._类型下拉.value = self._类型筛选

    def _类型变更(self, e):
        self._类型筛选 = (self._类型下拉.value or _筛选全部)
        self._上次签名 = None
        self.refresh()

    def _有筛选(self) -> bool:
        """是否处于"非全部"筛选状态 (决定空态用「筛选后为空」还是「首次为空」)"""
        return (self._状态筛选 != _筛选全部
                or self._类型筛选 != _筛选全部)

    def _筛选说明(self) -> str:
        """当前筛选条件的人话描述 (空态里告诉用户"为什么一条都没有")"""
        bits = []
        if self._状态筛选 != _筛选全部:
            bits.append(f"状态={self._状态筛选}")
        if self._类型筛选 != _筛选全部:
            bits.append(f"类型={self._类型筛选}")
        return ("当前筛选: " + " / ".join(bits)) if bits else ""

    def _清除筛选(self, e=None):
        """重置筛选回「全部」并重渲染 (供空态的「清除筛选」按钮调用)"""
        try:
            self._切筛选(_筛选全部, _筛选全部)
        except Exception as _e:
            _dbg("死书清单页", f'清除筛选失败: {type(_e).__name__}: {_e}')

    # ---------------------------------------------------------------- 渲染
    def refresh(self):
        """重建列表 (须主线程调用; 切页与可见时轮询均走此)"""
        if self._列表 is None:
            return
        try:
            记录 = self._筛选后()
        except Exception as _e:
            _dbg("死书清单页", f'筛选失败: {type(_e).__name__}: {_e}')
            记录 = []
        # 签名: 内容变化才重建, 防高频轮询丢点击事件(同 task_table._sig 策略)
        签名 = tuple((r.get('键'), r.get('状态'), r.get('次数'), r.get('最近时间'))
                     for r in 记录)
        if 签名 == self._上次签名:
            return
        self._上次签名 = 签名

        # 摘要: 全量计数(不受当前筛选影响) + 筛选后条数
        全 = self._取记录()
        计数 = {}
        for r in 全:
            k = r.get('状态') or '待确认'
            计数[k] = 计数.get(k, 0) + 1
        self._摘要.value = (
            f"共 {len(全)} 条 · 待确认 {计数.get('待确认', 0)}"
            f" · 已忽略 {计数.get('已忽略', 0)}"
            f" · 已删除 {计数.get('已删除', 0)}"
            f"　（当前筛选 {len(记录)} 条）")
        # 类型下拉随清单变化同步(数据被其他会话/远控改动时选项会变)
        self._同步类型下拉()

        self._加载槽.visible = False      # 批 4: 数据已读到 → 收起加载态
        self._列表.controls.clear()
        if not 记录:
            self._列表.visible = False
            # Phase 3 UX: 底层有记录、只是被筛选条件滤空 → 统一「筛选后为空」空态
            # + 一键清除筛选。旧行为: 直接给一片空白, 用户以为清单被清空/程序卡死。
            if 全 and self._有筛选():
                self._空态.visible = False
                self._筛选空态.content = states.筛选后为空(
                    清除筛选回调=self._清除筛选, 说明=self._筛选说明())
                self._筛选空态.visible = True
            else:
                self._筛选空态.visible = False
                self._空态.visible = True
        else:
            self._列表.visible = True
            self._空态.visible = False
            self._筛选空态.visible = False
            for r in 记录:
                self._列表.controls.append(self._行(r))
        try:
            self.page.update()
        except Exception:
            pass  # 刻意静默: 高频路径(2s 轮询), 补日志会刷屏

    def _行(self, r: dict) -> ft.Container:
        """单条死书记录卡片"""
        键 = r.get('键') or ''
        状态 = r.get('状态') or '待确认'
        # Phase 3: _状态展示 存的是令牌键, 色值在此构建期求值并登记重刷
        颜色键, 状态文案 = _状态展示.get(状态, ('status-warning', 状态))
        颜色 = 取色(颜色键)
        可询问 = bool(r.get('可询问删除'))
        类型 = r.get('类型') or '未知'

        # 类型标签: 只有"书已删除"才是可询问删除的类型(可询问删除=True),
        # 其余提示用户"不必删除" —— 避免用户按标签字面误判
        类型键 = 'status-error' if 可询问 else 'status-pending'
        动作 = self._行内动作(键, 状态, 网址=r.get('网址') or '',
                            书名=r.get('书名') or '', 可询问=可询问, 记录=r)
        # Phase 3: 三处 colored 文字走令牌 + 登记重刷 (字符串常量切主题不变色)
        类型标签 = ft.Text(类型, size=SIZE_TINY, weight=WEIGHT_EMPHASIS,
                         color=取色(类型键), font_family=FONT_STACK)
        登记重刷(类型标签, lambda c: setattr(c, 'color', 取色(类型键)))
        状态标签 = ft.Text(状态文案, size=SIZE_TINY, weight=WEIGHT_EMPHASIS,
                         color=颜色, font_family=FONT_STACK)
        登记重刷(状态标签, lambda c: setattr(c, 'color', 取色(颜色键)))
        # meta 行 (设计稿 .deadbook-meta: 等宽 URL · 失败短语 · 判定于 <时间> · 已抓 N 章)
        # 批 3 数据缺口已于 2026-10-07 补齐: HTTP状态码 / 页面为空 / 已抓章节 由
        # 判定死书 在判定侧采集 → 死书错误 → 记录死书 **落盘**。
        # 其中 已抓章节 对**补字段之前的老记录**确实无值 (键不存在) → 该槽跳过;
        # 不补 0 冒充 —— 0 与"不知道"必须分得开。
        网址 = r.get('网址') or ''
        _片段 = []
        if 网址:
            _片段.append(ft.Text(网址, size=SIZE_MICRO, weight=WEIGHT_BODY,
                                color=取色('text-tertiary'), font_family=FONT_TERMINAL,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                                selectable=True))
        # 失败状态短语 (设计稿第 2 槽: `HTTP 404` / `内容为空` / `连接超时`)
        # 设计稿该槽是**失败状态短语**, 不是"只有 HTTP 码" —— 8 张样卡里 3 张写
        # `内容为空`、2 张写 `连接超时`。用词由**判定时带上来的事实**决定:
        #   有响应状态码 → 报码; 否则页面为空(没拿到内容) → 连接超时; 否则 → 内容为空。
        # ⚠️ 不得在此比对类型名推词 (测试/test_dead_book_ui_actions.py 明文禁止 UI 自比类型名)
        _状态码 = _整数(r.get('HTTP状态码'))
        if _状态码 > 0:
            _失败短语 = f"HTTP {_状态码}"
        elif r.get('页面为空'):
            _失败短语 = '连接超时'
        else:
            _失败短语 = '内容为空'
        _片段.append(ft.Text(_失败短语, size=SIZE_MICRO,
                            weight=WEIGHT_BODY, color=取色('text-tertiary'),
                            font_family=FONT_STACK))
        if r.get('最近时间'):
            _片段.append(ft.Text(f"判定于 {r.get('最近时间')}", size=SIZE_MICRO,
                                weight=WEIGHT_BODY, color=取色('text-tertiary'),
                                font_family=FONT_STACK))
        # 已抓 N 章: 键存在即显示 (含 0 —— "这本书一章都没抓到"是用户判断
        # "删记录会不会丢东西"的关键事实, 不是空值); 键不存在 = 本条是补字段
        # 之前写的老记录 → 跳过。
        if '已抓章节' in r:
            _片段.append(ft.Text(f"已抓 {_整数(r.get('已抓章节'))} 章",
                                size=SIZE_MICRO, weight=WEIGHT_BODY,
                                color=取色('text-tertiary'), font_family=FONT_STACK))
        # 与设计稿的**有意偏差**: 加一段「尝试 N 次」, 且仅在 >1 时出现 ——
        # 设计稿的静态样卡都是首次失败, 没有这个概念; 而"同一本书反复判死 N 次"
        # 是排障信息 (旧实现在这里恒显"尝试 1 次", 属噪声, 故不再常显)。
        _次数 = _整数(r.get('次数'), 1)
        if _次数 > 1:
            _片段.append(ft.Text(f"尝试 {_次数} 次", size=SIZE_MICRO,
                                weight=WEIGHT_BODY, color=取色('text-tertiary'),
                                font_family=FONT_STACK))
        副信息 = _拼接_dot(_片段)
        for _c in 副信息.controls:
            登记重刷(_c, lambda c: setattr(c, 'color', 取色('text-tertiary')))
        登记重刷(副信息, lambda c: setattr(c, 'color', 取色('text-secondary')))
        原因文本 = ft.Text(r.get('原因') or '', size=SIZE_TINY, weight=WEIGHT_BODY,
                        color=取色('text-secondary'), font_family=FONT_STACK,
                        max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)
        登记重刷(原因文本, lambda c: setattr(c, 'color', 取色('text-secondary')))
        # 左侧 3px 状态色条 (设计稿 .deadbook-card)。设计稿此处统一用 error-line,
        # 但本页三种状态各有语义 → 按状态取色 (同属设计稿色板, 值取自其 rgba 蓝本)
        线色键 = {'待确认': 'status-warning-line',
                 '已删除': 'status-error-line',
                 '已忽略': 'status-pending-line'}.get(状态, 'status-warning-line')
        _卡片 = ft.Container(
            content=ft.Row([
                ft.Column([
                    ft.Row([
                        ft.Text(r.get('书名') or r.get('网址') or '(未知书名)',
                                size=SIZE_BODY, weight=WEIGHT_SUBTITLE,
                                color=ft.Colors.ON_SURFACE, font_family=FONT_STACK,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Container(
                            content=类型标签,
                            padding=ft.Padding.symmetric(horizontal=7, vertical=2),
                            border_radius=9, bgcolor=ft.Colors.SURFACE_CONTAINER),
                        ft.Container(
                            content=状态标签,
                            padding=ft.Padding.symmetric(horizontal=7, vertical=2),
                            border_radius=9, bgcolor=ft.Colors.SURFACE_CONTAINER),
                    ], spacing=8, tight=True),
                    副信息,
                    原因文本,
                ], spacing=3, expand=True, tight=True),
                动作,
            ], spacing=10, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding.symmetric(horizontal=12, vertical=9),
            border_radius=8, bgcolor=ft.Colors.SURFACE_CONTAINER,
            border=ft.Border.only(left=ft.BorderSide(3, 取色(线色键))))
        登记重刷(_卡片, lambda c: setattr(
            c, 'border', ft.Border.only(left=ft.BorderSide(3, 取色(线色键)))))
        return _卡片

    def _行内动作(self, 键: str, 状态: str, *, 网址: str, 书名: str,
                  可询问: bool, 记录: dict = None):
        """行内动作按钮组。

        语义与阶段3 一致, 不重造删除逻辑:
          已删除 → 无动作(已结项, 只展示)
          待确认 → 补新网址 / 重新检测 / 忽略 / 删除记录
          已忽略 → 补新网址 / 重新检测 / 恢复待确认(反悔) / 删除记录

        补新网址 (2026-10-06): 把新站点的目录页登记为这本书的**备用源**
        (主源失败自动切换, 见 爬虫.py:7119), 并立即重抓。
        与工作台死书弹窗**共用唯一实现** gui_components/补址弹窗.py ——
        否则两处文案/流程必然漂移 (本项目已有前科)。

        重新检测(阶段5) 对两态都开放: 用户点"忽略"常常是"站点可能只是挂了,
        过两天再看看", 不该逼他先恢复待确认才能重试。
        """
        按钮 = []
        if 状态 != '已删除':
            # 重新检测: 重跑抓取判定。发起后记录状态**不变**,
            # 抓成功 → 死书处理.标记已恢复 清记录; 仍死 → 记录死书 累加次数。
            按钮.append(ft.TextButton("重新检测",
                                      icon=ft.Icons.RESTART_ALT,
                                      on_click=lambda e, k=键, u=网址, n=书名:
                                      self._重新检测(k, u, n)))
            按钮.append(ft.TextButton("补新网址",
                                      icon=ft.Icons.ADD_LINK,
                                      tooltip="给这本书登记一个新网站的目录页 (作为备用源)",
                                      on_click=lambda e, k=键, u=网址, n=书名, rec=记录:
                                      self._补新网址(k, u, n, rec or {})))
        if 状态 == '已忽略':
            按钮.append(ft.TextButton("恢复待确认",
                                      icon=ft.Icons.UNDO,
                                      on_click=lambda e, k=键: self._设状态(
                                          k, '待确认')))
        elif 状态 == '待确认':
            按钮.append(ft.TextButton("忽略", icon=ft.Icons.DO_NOT_DISTURB_ON_OUTLINED,
                                      on_click=lambda e, k=键: self._设状态(
                                          k, '已忽略')))
        if 状态 != '已删除':
            按钮.append(ft.TextButton("删除记录", icon=ft.Icons.DELETE_OUTLINE,
                                      on_click=lambda e, k=键, u=网址, n=书名, c=可询问:
                                      self._确认删除(k, u, n, c)))
        if not 按钮:
            # Phase 3: 中性灰走令牌 + 登记重刷
            已处理 = ft.Text("已处理", size=SIZE_TINY, weight=WEIGHT_BODY,
                           color=取色('status-pending'), font_family=FONT_STACK)
            return 登记重刷(已处理,
                            lambda c: setattr(c, 'color', 取色('status-pending')))
        return ft.Row(按钮, spacing=4, tight=True)

    # ---------------------------------------------------------------- 动作
    def _补新网址(self, 键: str, 网址: str, 书名: str, 记录: dict):
        """补新网址 = 给这本书登记备用源 + 立刻重抓。

        与工作台死书弹窗共用 `gui_components/补址弹窗.py`（两步: 补备用源 → 追问删除）,
        本页只注入"重抓/删除/忽略"三个动作 —— 交互与文案不在此处复制。
        """
        if self.page is None or not 网址:
            self._提示("⚠️ 该记录没有网址, 无法补新网址")
            return
        try:
            import 死书处理
            from gui_components import 补址弹窗
        except Exception as _e:
            _dbg("死书清单页", f'补址弹窗导入失败: {type(_e).__name__}: {_e}')
            self._提示(f"❌ 无法打开补址弹窗: {type(_e).__name__}")
            return
        场景 = (补址弹窗.场景_网站失效 if (记录 or {}).get('网站失效')
                else 补址弹窗.场景_其他)
        动作 = 补址弹窗.补址动作(
            添加并重抓=lambda _新址: self._重新检测(键, 网址, 书名),
            删除记录=lambda: self._执行删除(键, 网址, 书名),
            忽略记录=lambda: self._设状态(键, 死书处理.状态_已忽略),
        )
        try:
            补址弹窗.打开补址弹窗(self.page, 目录URL=网址, 标题=书名 or 网址,
                               场景=场景, 类型=(记录 or {}).get('类型') or '',
                               原因=(记录 or {}).get('原因') or '', 动作=动作)
        except Exception as _e:
            _dbg("死书清单页", f'补址弹窗打开失败: {type(_e).__name__}: {_e}')
            self._提示(f"❌ 打开补址弹窗失败: {type(_e).__name__}")

    def _重新检测(self, 键: str, 网址: str, 书名: str = ''):
        """重新检测: 重跑抓取判定, 确认这本书是否已恢复 (阶段5 核心动作)。

        复用任务表的既有能力, 不新造抓取逻辑:
          有对应任务行 → `restart_task` 原任务内重启 (它会清 task.dead,
                        且保持"一个 URL 恒一行"的界面约定)
          无对应任务行 (如已删记录/重启过) → `create_task` 新建

        ⚠️ 与任务表「重新下载」的区别: 那是在**已成功/部分成功**的书上重抓全本,
        诉求是内容; 这里是在**从未抓到章节**的死书上重试, 诉求是"判定是否恢复"。
        底层都落到同一套抓取链路, 故复用而非复制。

        不 reset 记录状态: 抓成功 → 数据层 `标记已恢复` 清记录;
        仍死 → `记录死书` 累加次数(已忽略的保持已忽略, 不再打扰)。
        """
        if self.task_manager is None:
            self._提示("⚠️ 未接入任务管理器, 无法发起检测 (请在任务表重新下载)")
            return
        if not 网址:
            self._提示("⚠️ 该记录没有网址, 无法检测")
            return
        try:
            旧 = self.task_manager.find_task_by_url(网址)
        except Exception as _e:
            _dbg("死书清单页", f'查找任务失败: {type(_e).__name__}: {_e}')
            旧 = None
        try:
            if 旧 is not None:
                旧状态 = getattr(旧, 'status', '')
                if 旧状态 == 'running' or (getattr(旧, 'thread', None) is not None
                                           and 旧.thread.is_alive()):
                    self._提示("⚠️ 该书任务正在运行中, 无需重复检测")
                    return
                if self.task_manager.restart_task(旧.task_id):
                    方式 = '原任务重启'
                else:
                    self._提示("⚠️ 该书任务正在收尾, 请稍后再检测")
                    return
            else:
                # 新建: resume=False (死书从没抓到章节, 续传无意义且可能
                # 撞上残留的半成品文件); 沿用任务表的默认模式 full。
                新id = self.task_manager.create_task(网址, mode='full', resume=False)
                方式 = f'新建任务 {新id}'
        except Exception as _e:
            _dbg("死书清单页", f'重新检测发起失败: {type(_e).__name__}: {_e}')
            self._提示(f"❌ 发起检测失败: {type(_e).__name__}: {_e}")
            return
        self._上次签名 = None
        self.refresh()
        self._提示(f"已开始重新检测 ({方式}): {书名 or 网址}\n"
                   f"抓成功会自动移出清单; 仍失败则次数 +1。进度见抓取工作台。")

    def _批量重检(self):
        """对当前筛选下的 待确认/已忽略 记录批量发起重新检测。

        ⚠️ **刻意设上限** (`_批量上限`): 每一本都要真发一轮请求, 无上限地
        "全选就检" 会在用户点一下的瞬间对同一站点并发轰击几十次 —— 既可能
        被站点封, 也会把同域闸门堵死。超限则如实报数并让用户分批。
        """
        if self.task_manager is None:
            self._提示("⚠️ 未接入任务管理器, 无法发起检测")
            return
        待检 = [r for r in self._筛选后()
                if (r.get('状态') or '待确认') in ('待确认', '已忽略')]
        if not 待检:
            self._提示("当前筛选下没有可检测的记录")
            return
        超限 = len(待检) > _批量上限
        目标 = 待检[:_批量上限]
        成功 = 0
        for r in 目标:
            网址 = (r.get('网址') or '').strip()
            if not 网址:
                continue
            try:
                旧 = self.task_manager.find_task_by_url(网址)
                if 旧 is not None:
                    if getattr(旧, 'status', '') == 'running':
                        continue
                    if not self.task_manager.restart_task(旧.task_id):
                        continue
                else:
                    self.task_manager.create_task(网址, mode='full', resume=False)
                成功 += 1
            except Exception as _e:
                _dbg("死书清单页", f'批量重检单项失败: {type(_e).__name__}: {_e}')
        self._上次签名 = None
        self.refresh()
        尾 = f"\n另有 {len(待检) - _批量上限} 条未发起 (单次上限 {_批量上限} 本), 请分批。" if 超限 else ""
        self._提示(f"已发起 {成功}/{len(目标)} 本重新检测。\n"
                   f"抓成功会自动移出清单, 仍失败则次数 +1。进度见抓取工作台。{尾}")

    def _设状态(self, 键: str, 状态: str):
        """改清单状态 (死书处理 是唯一数据源)"""
        try:
            import 死书处理
            ok = 死书处理.设状态(键, 状态)
        except Exception as _e:
            _dbg("死书清单页", f'设状态失败: {type(_e).__name__}: {_e}')
            self._提示(f"操作失败: {_e}")
            return
        self._提示("已更新" if ok else "更新失败(清单写入未成功)")
        self._上次签名 = None
        self.refresh()

    def _确认删除(self, 键: str, 网址: str, 书名: str, 可询问: bool):
        """删除确认框。

        ⚠️ EXE 文字必须显式 color (v2.4.19 G-H1 教训: 缺色渲染成不可见)。
        这是删数据确认框, 文字不可见会放大误删风险。
        """
        if self.page is None:
            self._执行删除(键, 网址, 书名)
            return
        提示 = (f"书名: {书名 or 网址}\n\n将删除三处记录:\n"
                f"  · 任务列表中的该行\n  · 书架中的该书\n"
                f"  · 网站清单中的该网址\n\n已下载的文件不会被删除。")
        if not 可询问:
            提示 += "\n\n注意: 该书并非「已被删除」(可能是站点不可达或目录无章节),\n"
            提示 += "删除后若站点恢复将需要重新添加。"
        dialog = ft.AlertDialog(
            modal=True,
            # EXE 文字必须显式 color (v2.4.19 G-H1 教训: 缺色渲染成不可见)。
            # Phase 3: 旧写法 color=MORANDI_ON_SURFACE 只是 ft.Colors.ON_SURFACE
            # 的别名(Flet 按 theme_mode 自适应), 直写 ft.Colors.ON_SURFACE 值不变,
            # 同时去掉了页面本地的字符串绑定。
            title=ft.Text("确认删除记录", color=ft.Colors.ON_SURFACE,
                          font_family=FONT_STACK),
            content=ft.Text(提示, size=SIZE_SMALL, font_family=FONT_STACK,
                            color=ft.Colors.ON_SURFACE),
            actions=[
                ft.TextButton("取消", on_click=lambda _: close_dialog(self.page, dialog)),
                ft.TextButton("确认删除",
                              on_click=lambda _: self._确认删除回调(dialog, 键, 网址, 书名)),
            ],
        )
        open_dialog(self.page, dialog)

    def _确认删除回调(self, dialog, 键: str, 网址: str, 书名: str):
        try:
            close_dialog(self.page, dialog)
        except Exception as _e:
            _dbg("死书清单页", f'关窗失败: {type(_e).__name__}: {_e}')
        self._执行删除(键, 网址, 书名)

    def _执行删除(self, 键: str, 网址: str, 书名: str = ''):
        """执行三处删除编排 (恒不删产物); 本页无 task 上下文, 任务行需用户在
        任务表内自行删除 —— 诚实说明, 不伪成功。"""
        try:
            import 死书处理
            结果 = 死书处理.删除书记录(网址, 任务id='', task_manager=self.task_manager)
        except Exception as _e:
            _dbg("死书清单页", f'删除编排异常: {type(_e).__name__}: {_e}')
            self._提示(f"❌ 删除失败: {_e}")
            return
        try:
            死书处理.设状态(键, 死书处理.状态_已删除)
        except Exception as _e2:
            _dbg("死书清单页", f'置已删除失败: {type(_e2).__name__}: {_e2}')
        失败 = [f"{k}: {v[1]}" for k, v in 结果.items()
                if k != '全部成功' and isinstance(v, tuple) and not v[0]]
        if 结果.get('全部成功'):
            self._提示(f"✅ 已删除: {书名 or 网址}")
        else:
            self._提示(f"⚠️ 部分删除: {'; '.join(失败) or '未知'}")
        self._上次签名 = None
        self.refresh()

    def _提示(self, msg: str):
        try:
            if self.page is None:
                return
            self.page.show_dialog(提示条(msg))
        except Exception as _e:
            _dbg("死书清单页", f'提示失败: {type(_e).__name__}: {_e}')
