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
  ① **本页只管死书清单, 不做重新检测** —— 那是阶段5 的事 (需重跑抓取判定,
     代价高, 不能在页面刷新里做)。
  ② 动作**复用阶段3 的语义**: 删 = 三处编排(任务/书架/网站清单), 恒不删产物;
     忽略 = 置 已忽略; 不在这里重造删除逻辑。
  ③ 列表是**读快照**, 所有 IO 走 死书处理 模块, 本页不直接碰 JSON。

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


from ..ui_fluent import (txt, FONT_STACK, SIZE_TINY, SIZE_SMALL, SIZE_BODY,
                         WEIGHT_SUBTITLE, WEIGHT_BODY, WEIGHT_EMPHASIS,
                         MORANDI_ERROR, MORANDI_WARNING, MORANDI_SUCCESS,
                         MORANDI_STOPPED, MORANDI_SURFACE_CONTAINER,
                         MORANDI_ON_SURFACE_VARIANT,
                         MORANDI_ON_SURFACE,
                         open_dialog, close_dialog)
from ..ui_theme import page_header


# 三态 → 展示配置 (与 死书处理.状态_* 严格对应; 缺一回落 待确认)
_状态展示 = {
    '待确认': (MORANDI_WARNING, '待确认'),
    '已忽略': (MORANDI_STOPPED, '已忽略'),
    '已删除': (MORANDI_SUCCESS, '已删除'),
}
_筛选全部 = '全部'


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
        self._摘要 = txt("—", size=SIZE_SMALL, weight=WEIGHT_BODY,
                         color=MORANDI_ON_SURFACE_VARIANT, font_family=FONT_STACK)
        self._列表 = ft.Column(spacing=6, tight=True, scroll=ft.ScrollMode.AUTO)
        self._空态 = ft.Column([
            ft.Icon(ft.Icons.CHECK_CIRCLE_OUTLINE, size=44,
                    color=MORANDI_SUCCESS),
            txt("死书清单为空", size=SIZE_BODY, weight=WEIGHT_SUBTITLE),
            ft.Text("抓取失败若被判定为「书已删除」会记到这里, 可在此集中处置。\n"
                    "若列表为空但任务表有「书已删除」行, 可刷新本页。",
                    size=SIZE_SMALL, weight=WEIGHT_BODY,
                    color=MORANDI_ON_SURFACE_VARIANT, font_family=FONT_STACK,
                    text_align=ft.TextAlign.CENTER),
        ], spacing=8, alignment=ft.MainAxisAlignment.CENTER, tight=True)

        头 = page_header(
            "死书清单",
            "被判定为书已删除/不可读的书。删除会同时移除任务、书架与网站清单记录; "
            "已下载的文件不会被删除。",
            actions=[
                ft.TextButton("刷新", icon=ft.Icons.REFRESH,
                              on_click=lambda e: self._切筛选(
                                  self._状态筛选, self._类型筛选)),
            ])

        return ft.Column([
            头,
            self._筛选栏(),
            self._摘要,
            ft.Container(content=ft.Column([self._列表, self._空态], spacing=0,
                                          expand=True),
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
        return ft.Container(
            content=ft.Text(文本, size=SIZE_SMALL,
                            weight=(WEIGHT_EMPHASIS if 选中 else WEIGHT_BODY),
                            color=(ft.Colors.ON_PRIMARY_CONTAINER if 选中
                                   else MORANDI_ON_SURFACE_VARIANT),
                            font_family=FONT_STACK),
            padding=ft.Padding.symmetric(horizontal=12, vertical=7),
            border_radius=16, ink=True, on_click=on_click,
            bgcolor=(ft.Colors.PRIMARY_CONTAINER if 选中
                     else MORANDI_SURFACE_CONTAINER),
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

        self._列表.controls.clear()
        if not 记录:
            self._列表.visible = False
            self._空态.visible = True
        else:
            self._列表.visible = True
            self._空态.visible = False
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
        颜色, 状态文案 = _状态展示.get(状态, (MORANDI_WARNING, 状态))
        可询问 = bool(r.get('可询问删除'))
        类型 = r.get('类型') or '未知'

        # 类型标签: 只有"书已删除"才是可询问删除的类型(可询问删除=True),
        # 其余提示用户"不必删除" —— 避免用户按标签字面误判
        类型色 = MORANDI_ERROR if 可询问 else MORANDI_STOPPED
        动作 = self._行内动作(键, 状态, 网址=r.get('网址') or '',
                            书名=r.get('书名') or '', 可询问=可询问)
        return ft.Container(
            content=ft.Row([
                ft.Column([
                    ft.Row([
                        ft.Text(r.get('书名') or r.get('网址') or '(未知书名)',
                                size=SIZE_BODY, weight=WEIGHT_SUBTITLE,
                                color=MORANDI_ON_SURFACE, font_family=FONT_STACK,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Container(
                            content=ft.Text(类型, size=SIZE_TINY,
                                            weight=WEIGHT_EMPHASIS,
                                            color=类型色, font_family=FONT_STACK),
                            padding=ft.Padding.symmetric(horizontal=7, vertical=2),
                            border_radius=9, bgcolor=MORANDI_SURFACE_CONTAINER),
                        ft.Container(
                            content=ft.Text(状态文案, size=SIZE_TINY,
                                            weight=WEIGHT_EMPHASIS,
                                            color=颜色, font_family=FONT_STACK),
                            padding=ft.Padding.symmetric(horizontal=7, vertical=2),
                            border_radius=9, bgcolor=MORANDI_SURFACE_CONTAINER),
                    ], spacing=8, tight=True),
                    ft.Text(f"{r.get('域名') or ''}　×{r.get('次数') or 1}"
                            f"　{r.get('最近时间') or ''}",
                            size=SIZE_TINY, weight=WEIGHT_BODY,
                            color=MORANDI_ON_SURFACE_VARIANT, font_family=FONT_STACK,
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(r.get('原因') or '', size=SIZE_TINY, weight=WEIGHT_BODY,
                            color=MORANDI_ON_SURFACE_VARIANT, font_family=FONT_STACK,
                            max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                ], spacing=3, expand=True, tight=True),
                动作,
            ], spacing=10, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding.symmetric(horizontal=12, vertical=9),
            border_radius=8, bgcolor=MORANDI_SURFACE_CONTAINER)

    def _行内动作(self, 键: str, 状态: str, *, 网址: str, 书名: str, 可询问: bool):
        """行内动作按钮组。

        语义与阶段3 一致, 不重造删除逻辑:
          已删除 → 无动作(已结项, 只展示)
          待确认 → 忽略 / 删除记录 / (站回待确认 由忽略反做)
          已忽略 → 恢复待确认(反悔) / 删除记录
        """
        按钮 = []
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
            return ft.Text("已处理", size=SIZE_TINY, weight=WEIGHT_BODY,
                           color=MORANDI_STOPPED, font_family=FONT_STACK)
        return ft.Row(按钮, spacing=4, tight=True)

    # ---------------------------------------------------------------- 动作
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
            title=ft.Text("确认删除记录", color=MORANDI_ON_SURFACE,
                          font_family=FONT_STACK),
            content=ft.Text(提示, size=SIZE_SMALL, font_family=FONT_STACK,
                            color=MORANDI_ON_SURFACE),
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
            self.page.show_dialog(ft.SnackBar(ft.Text(
                msg, size=SIZE_SMALL, font_family=FONT_STACK,
                color=MORANDI_ON_SURFACE)))
        except Exception as _e:
            _dbg("死书清单页", f'提示失败: {type(_e).__name__}: {_e}')
