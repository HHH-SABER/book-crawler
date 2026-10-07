# -*- coding: utf-8 -*-
"""死书机制 阶段4: 死书清单页 回归 (2026-10-03)

本阶段最大的坑是**页面顺序契约**: gui_app.content_stack 按
`[pages_map[k] for k,_,_,_ in NAV_PAGES]` 建 Stack, 且首屏可见性按
`pages_map.values()` 的**索引 0** 判定 —— pages_map 与 NAV_PAGES 键序
一旦错位, 用户启动就看到错的页(不是报错, 是静默的错界面)。
这类 bug 必须用测试钉死, 肉眼在 6 个页面里看不出来。
"""
import re
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / '源码')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _沙箱  # noqa: F401,E402  import 即把状态根钉到临时目录


def _读源码(相对: str) -> str:
    return (_ROOT / '源码' / 相对).read_text(encoding='utf-8')


class Test页面顺序契约(unittest.TestCase):
    """① pages_map 键序必须 == NAV_PAGES 序 (错位 = 首屏显示错页)"""

    def test_两处键序严格一致(self):
        from gui_components.icon_rail import NAV_PAGES
        nav = [k for k, _, _, _ in NAV_PAGES]
        gui = _读源码('gui_app.py')
        块 = gui.split('pages_map = {')[1].split('}')[0]
        pm = re.findall(r'"(\w+)":', 块)
        self.assertEqual(pm, nav,
                         f'pages_map 键序 {pm} 与 NAV_PAGES 序 {nav} 不一致 '
                         f'→ content_stack 会错位、首屏显示错页')

    def test_gui_app_有顺序自检(self):
        """加一道运行时自检: 顺序不一致立刻炸, 别等用户看到错页。"""
        gui = _读源码('gui_app.py')
        # pages_map = { 在本文件只出现一次, 故取 [1]; 自检紧跟字典定义之后
        自检 = gui.split('pages_map = {')[1][:900]
        self.assertIn('RuntimeError', 自检,
                      '缺顺序自检 → 键序错位只能靠肉眼发现')
        self.assertIn('NAV_PAGES', 自检, '自检未与 NAV_PAGES 比对')

    def test_首屏仍是抓取工作台(self):
        """新增页不能插到 index 0 前面(会把首屏挤掉)。"""
        from gui_components.icon_rail import NAV_PAGES
        self.assertEqual(NAV_PAGES[0][0], 'crawl',
                         '首屏必须是 crawl(抓取工作台), 新增页不得插到最前')

    def test_死书页在历史页之后站点页之前(self):
        from gui_components.icon_rail import NAV_PAGES
        nav = [k for k, _, _, _ in NAV_PAGES]
        self.assertIn('deadbook', nav, '死书清单页未挂到导航')
        self.assertLess(nav.index('history'), nav.index('deadbook'),
                        '死书清单应在爬取历史之后')
        self.assertLess(nav.index('deadbook'), nav.index('sites'),
                        '死书清单应在站点管理之前')

    def test_导航文案存在(self):
        from gui_components.icon_rail import NAV_PAGES
        死书项 = [p for p in NAV_PAGES if p[0] == 'deadbook']
        self.assertTrue(死书项, 'NAV_PAGES 缺 deadbook 项')
        self.assertEqual(死书项[0][2], '死书清单', '导航文案不对')
        # 序号列也应更新(第4列是排序号, 用于导航内顺序断言)
        self.assertEqual(死书项[0][3], 2, '死书清单排序号应为 2')


class Test页面挂载完整性(unittest.TestCase):
    """② 页面必须在四处接线齐全, 漏一处 = 白建一个页"""

    def setUp(self):
        self.gui = _读源码('gui_app.py')

    def test_顶层import存在(self):
        self.assertIn('from gui_components.pages.dead_book_page import DeadBookPage',
                      self.gui, '缺顶层 import → 直接 ImportError 启动失败')

    def test_pyinstaller显式import存在(self):
        """中文模块名需静态收集, 否则 EXE 里缺模块(源码能跑, EXE 崩)。"""
        块 = self.gui.split('import gui_components.task_manager')[1][:2000]
        self.assertIn('gui_components.pages.dead_book_page', 块,
                      'PyInstaller 显式 import 块缺死书页 → EXE 内缺模块')

    def test_实例化并注入依赖(self):
        self.assertIn('dead_page = DeadBookPage()', self.gui, '未实例化')
        self.assertIn('dead_page.page = page', self.gui, '未注入 page')
        self.assertIn('dead_page.task_manager = task_manager', self.gui,
                      '未注入 task_manager → 删除编排删不掉任务行')

    def test_切页刷新已接线(self):
        块 = self.gui.split('def _switch_page')[1][:1800]
        self.assertIn('key == "deadbook"', 块, '切到死书页未刷新 → 显示上一页残留内容')
        self.assertIn('dead_page.refresh()', 块)

    def test_可见时轮询已接线(self):
        块 = self.gui.split('def _refresh_loop')[1][:1200]
        self.assertIn('pages_map["deadbook"].visible', 块,
                      '死书页未接可见时轮询 → 其他会话改清单本页不更新')
        self.assertIn('dead_page.refresh()', 块)


class Test清单页逻辑(unittest.TestCase):
    """③ 页面自身: 筛选 / 空态 / 动作语义 / EXE 文字色"""

    def setUp(self):
        from gui_components.pages.dead_book_page import DeadBookPage
        self.page = DeadBookPage()
        self.src = _读源码('gui_components/pages/dead_book_page.py')

    def test_类可实例化且有refresh(self):
        self.assertTrue(hasattr(self.page, 'refresh'), '缺 refresh (切页/轮询都调它)')

    def test_筛选覆盖三态与全部(self):
        for s in ('全部', '待确认', '已忽略', '已删除'):
            self.assertIn(s, self.src, f'缺状态筛选: {s}')

    def test_空态存在(self):
        """空清单要给明确空态, 不给空白页(用户以为坏了)。"""
        self.assertIn('_空态', self.src, '缺空态控件')
        self.assertIn('死书清单为空', self.src, '空态文案缺失')

    def test_签名比对防重建(self):
        """2s 轮询下必须靠签名跳过重建, 否则丢点击事件(同 task_table 策略)。"""
        self.assertIn('_上次签名', self.src, '缺签名比对 → 轮询会重建列表丢点击')

    def test_已删除态无动作(self):
        块 = self.src.split('def _行内动作')[1][:1500]
        self.assertIn("状态 != '已删除'", 块,
                      '已删除态仍给动作按钮 → 用户会对已结项重复删除')

    def test_忽略可反悔(self):
        """已忽略态须能恢复待确认(用户反悔的正常路径)。"""
        块 = self.src.split('def _行内动作')[1][:1500]
        self.assertIn('恢复待确认', 块, '已忽略态无恢复入口 → 用户反悔无法回退')

    def test_确认框显式颜色(self):
        """EXE 契约: 弹窗文字缺显式 color 会渲染成不可见 (v2.4.19 G-H1)。

        2026-10-04 (Phase 3): 迁移后正文改用 `ft.Colors.ON_SURFACE`（Flet 按
        theme_mode 自动适配），不再绑 `ui_fluent` 的 MORANDI 字符串常量。
        断言随之改为"必须显式给颜色"，并同时接受令牌写法 `取色(...)` ——
        不再锁死某一个常量名（那会让注释里提一句旧名就能骗过测试）。
        """
        块 = self.src.split('ft.AlertDialog')[1][:1200]
        self.assertIn('color=', 块, '确认框文字未显式着色 → EXE 中不可见')
        self.assertTrue(('ft.Colors.ON_SURFACE' in 块) or ('取色(' in 块),
                        '确认框文字须有显式颜色 (ft.Colors.ON_SURFACE 或 取色(...))')
        self.assertIn('modal=True', 块, '删除确认应为模态')

    def test_不可询问类型有额外警示(self):
        """站点不可达/目录无章节不是书被删, 确认框须额外提示误删代价。"""
        块 = self.src.split('def _确认删除')[1][:1500]
        self.assertIn('if not 可询问', 块, '未对非"书已删除"类型额外警示')

    def test_删除恒不删产物(self):
        self.assertIn('已下载的文件不会被删除', self.src,
                      '确认框必须承诺不动产物(与阶段3 语义一致)')
        self.assertIn('delete_file=False', _读源码('死书处理.py'),
                      '删除编排必须恒 delete_file=False')

    def test_页面不重造删除逻辑(self):
        """动作必须走 死书处理 模块, 页面不直接碰 JSON(单一数据源)。"""
        self.assertIn('死书处理.删除书记录', self.src, '未走统一删除编排')
        self.assertIn('死书处理.设状态', self.src, '未走统一状态流转')
        self.assertNotIn('json.load', self.src, '页面不得直接读 JSON(破坏单一数据源)')

    def test_读失败不崩(self):
        """IO 全在 死书处理 内, 失败应回落空表而非抛(刷新循环会整页炸)。"""
        self.assertIn('except Exception', self.src.split('def _取记录')[1][:600],
                      '_取记录 未容错 → 清单损坏时整页崩')

    def test_无控制台挂账号(self):
        """列表刷新会高频调用, _dbg 走文件日志不 console 镜像(同 remote_page)。"""
        self.assertIn('def _dbg', self.src, '缺统一异常留痕通道')
        self.assertIn('app_log', self.src)

    def test_dropdown用flet086事件名(self):
        """flet 0.86: Dropdown 用 on_select, **无 on_change**。

        写 on_change 会在 build() 时 TypeError —— 静态检查抓不到, 只有真构建
        控件树才暴露(阶段4 实测踩到)。
        """
        self.assertIn('on_select=', self.src, 'Dropdown 应用 on_select')
        self.assertNotIn('on_change=', self.src,
                         'flet 0.86 Dropdown 无 on_change 参数 → build() TypeError')

    def test_类型下拉随清单同步(self):
        """类型集合随状态筛选变化(全部态4类, 待确认可能只2类)须同步下拉。"""
        self.assertIn('_同步类型下拉', self.src, '类型下拉未随清单同步')
        块 = self.src.split('def _同步类型下拉')[1][:900]
        self.assertIn('_当前类型集()', 块, '下拉选项未取真实类型集合')
        self.assertIn('回落"全部类型"', 块,
                      '当前类型在新集合消失时须回落, 否则下拉显示空值')


class Test死书卡片meta行数据缺口(unittest.TestCase):
    """批 3 数据缺口收口 (2026-10-07): meta 行 = 设计稿
    `URL · 失败短语 · 判定于 <时间> · 已抓 N 章`。

    第 2 槽在 8 张样卡里有三种词: `HTTP 404`(3 张) / `内容为空`(3 张) /
    `连接超时`(2 张) —— 是**失败状态短语**, 不是"只有 HTTP 码"。

    这里**真构建卡片控件树**再读文本 —— 只做源码字符串断言的话,
    "字段取错/条件写反/拼错键名"这类错全都漏得过去 (K45/K46 同族教训)。
    """

    def setUp(self):
        import flet as ft
        from gui_components.pages.dead_book_page import DeadBookPage
        self.ft = ft
        self.page = DeadBookPage()

    def _文本(self, r: dict) -> list:
        """构建单条卡片并收集全部 ft.Text 的值"""
        return self._收集(self.page._行(r))

    def _收集(self, 控件) -> list:
        out = []
        if 控件 is None:
            return out
        if isinstance(控件, self.ft.Text) and isinstance(控件.value, str):
            out.append(控件.value)
        for attr in ('content', 'controls'):
            sub = getattr(控件, attr, None)
            if isinstance(sub, list):
                for c in sub:
                    out.extend(self._收集(c))
            elif sub is not None:
                out.extend(self._收集(sub))
        return out

    @staticmethod
    def _记录(**kw):
        基 = {'键': 'example.com/book/1', '网址': 'https://example.com/book/1',
              '书名': '示例书', '类型': '目录无章节', '原因': '未解析出章节',
              '可询问删除': False, '状态': '待确认',
              '最近时间': '2026-10-07 12:00:00', '次数': 1}
        基.update(kw)
        return 基

    def test_完整记录显示设计稿四个片段(self):
        文本 = self._文本(self._记录(HTTP状态码=404, 已抓章节=412))
        self.assertIn('https://example.com/book/1', 文本)
        self.assertIn('HTTP 404', 文本, '缺 HTTP 码片段 (数据缺口未接上)')
        self.assertIn('判定于 2026-10-07 12:00:00', 文本)
        self.assertIn('已抓 412 章', 文本, '缺已抓章节片段 (数据缺口未接上)')

    def test_分隔点数量等于片段数减一(self):
        """设计稿用 .dot-sep 分隔; 多一个/少一个都是排版事故"""
        文本 = self._文本(self._记录(HTTP状态码=404, 已抓章节=412))
        self.assertEqual(文本.count('·'), 3, f'4 个片段应有 3 个分隔点, 实得 {文本}')

    def test_拿不到内容时说连接超时(self):
        """页面为空 (三次重试没拿到) 且无状态码 → 设计稿用词「连接超时」"""
        文本 = self._文本(self._记录(HTTP状态码=0, 已抓章节=0, 页面为空=True))
        self.assertIn('连接超时', 文本, f'实得 {文本}')

    def test_页面拿到但无章节说内容为空(self):
        """页面拿到了 (只是解析不出章节) → 设计稿用词「内容为空」"""
        文本 = self._文本(self._记录(HTTP状态码=0, 已抓章节=47, 页面为空=False))
        self.assertIn('内容为空', 文本, f'实得 {文本}')

    def test_有状态码就报码哪怕页面为空(self):
        """5xx 错误页: 页面算"拿到了", 且带得回状态码 → 报 HTTP 码"""
        文本 = self._文本(self._记录(HTTP状态码=502, 页面为空=False))
        self.assertIn('HTTP 502', 文本, f'实得 {文本}')
        self.assertNotIn('内容为空', 文本)

    def test_已抓零章仍显示(self):
        """"一章都没抓到"是用户判断"删了会不会丢东西"的关键事实, 必须显式"""
        self.assertIn('已抓 0 章', self._文本(self._记录(HTTP状态码=200, 已抓章节=0)))

    def test_第二槽永不空缺(self):
        """设计稿每张卡都有失败短语 → 无论新老记录都必须给出一个词"""
        for kw in ({'HTTP状态码': 404}, {'页面为空': True}, {}, {'页面为空': False}):
            文本 = self._文本(self._记录(**kw))
            self.assertTrue(
                [t for t in 文本 if t.startswith('HTTP ') or t in ('连接超时', '内容为空')],
                f'第 2 槽空缺: {kw} → {文本}')

    def test_老记录缺已抓键则跳过该槽(self):
        """无值 ≠ 0: 补字段之前的老记录没有 已抓章节 键 → 跳过, 不冒充 0"""
        文本 = self._文本(self._记录(HTTP状态码=404))     # 不带 已抓章节
        self.assertFalse([t for t in 文本 if t.startswith('已抓')], f'实得 {文本}')

    def test_尝试次数仅在多次时显示(self):
        """有意偏差: 设计稿无"尝试 N 次"; 首次失败属噪声故不显, 反复判死才是排障信息"""
        首次 = self._文本(self._记录(HTTP状态码=404, 已抓章节=1, 次数=1))
        self.assertFalse([t for t in 首次 if t.startswith('尝试')], f'实得 {首次}')
        多次 = self._文本(self._记录(HTTP状态码=404, 已抓章节=1, 次数=5))
        self.assertIn('尝试 5 次', 多次)

    def test_脏字段不致整页崩(self):
        """清单是用户可编辑的 JSON: 一个脏值不能让整页渲染抛异常 (刷新循环会全炸)"""
        文本 = self._文本(self._记录(HTTP状态码='x', 已抓章节=[], 次数='y'))
        self.assertIn('内容为空', 文本, '脏状态码应回落"内容为空"而不是崩')
        self.assertFalse([t for t in 文本 if t.startswith('尝试')], f'实得 {文本}')

    def test_共享单元测试_确认键名与落盘侧一致(self):
        """页面读的键名必须与 死书处理.记录死书 写出的键名逐字相同。

        这是本缺口最可能的失效点: 一边写 'HTTP状态码' 一边读 '状态码'
        → 页面恒显示错误短语, 且**没有任何异常** (静默)。
        """
        import json
        import tempfile
        from pathlib import Path
        import _沙箱  # noqa: F401
        import 死书处理 as D
        with tempfile.TemporaryDirectory() as td:
            原 = D.清单路径
            D.清单路径 = lambda: str(Path(td) / '死书清单.json')
            try:
                D.记录死书('https://example.com/b/9', '书', D.类型_无章节, 'r',
                           状态码=410, 已抓章节=87, 页面为空=False)
                落盘 = json.loads(Path(D.清单路径()).read_text(encoding='utf-8'))
            finally:
                D.清单路径 = 原
        记录 = 落盘['记录'][0]
        for 键 in ('HTTP状态码', '已抓章节', '页面为空'):
            self.assertIn(键, 记录, f'落盘侧未写键 {键}')
        文本 = self._文本(记录)
        self.assertIn('HTTP 410', 文本)
        self.assertIn('已抓 87 章', 文本)


if __name__ == '__main__':
    unittest.main(verbosity=2)
