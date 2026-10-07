# -*- coding: utf-8 -*-
"""布局档位 (响应式断点) 回归 — Phase 4 批 4 新增。

**为什么需要**: 改动前响应式**没有任何自动化护栏** —— 全仓 grep
`on_resize|设置窄档|1200` 在 测试/ 与 测试_本地/ 里零命中, 只靠 gui_app 打一行
日志 + 人工去 EXE 里读 (那条"SetWindowPos 改窗口尺寸"的脚本还没留在仓库)。
也就是说: 断点改了、档位算错了、某档参数漏了, 门禁全绿而用户看到坏界面。

本文件做三件事:
  ① 钉死**阈值**与**档位判定**的边界 (含 960/1100 的闭区间归属);
  ② 钉死每档参数, 并**直接读设计稿 index.html 的 @media 数值交叉校验** ——
     设计稿改断点而代码没跟, 这里就红;
  ③ 钉死"任何档都不隐藏任务表列"(用户 2026-10-07 明确拍板的设计稿口径)。

运行: python -m unittest discover -s 测试
"""
import sys
import unittest
from pathlib import Path

根 = Path(__file__).resolve().parents[1]
for _p in (str(根), str(根 / '源码')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _沙箱  # noqa: F401,E402

from gui_components import 布局档位 as L   # noqa: E402


class Test档位判定(unittest.TestCase):

    def test_边界归属(self):
        """960 / 1100 是**闭区间上界** (设计稿写的是 max-width, 含等号)"""
        self.assertEqual(L.计算档位(1101), L.宽)
        self.assertEqual(L.计算档位(1100), L.中, '1100 属 ≤1100 档')
        self.assertEqual(L.计算档位(1099), L.中)
        self.assertEqual(L.计算档位(961), L.中)
        self.assertEqual(L.计算档位(960), L.窄, '960 属 ≤960 档')
        self.assertEqual(L.计算档位(959), L.窄)
        self.assertEqual(L.计算档位(400), L.窄)

    def test_程序真实视口落在宽档(self):
        """本机逻辑视口 1265px (实测, 见 文档/踩坑总表.md K47) —— 必须是基准档,
        否则用户一启动就看到被降级的界面。"""
        self.assertEqual(L.计算档位(1265), L.宽)
        self.assertEqual(L.计算档位(1500), L.宽)

    def test_脏值不抛且不乱降级(self):
        for 值 in (0, -1, None, ''):
            self.assertEqual(L.计算档位(值), L.宽,
                             f'{值!r} 应回落基准档 (首帧 page.width 未就绪)')
        for 值 in ('abc', [], {}):
            self.assertEqual(L.计算档位(值), L.宽, f'{值!r} 不得抛异常')
        self.assertEqual(L.计算档位('1265'), L.宽, '字符串数字应能解析')

    def test_三档齐全(self):
        for 宽 in (1500, 1050, 900):
            self.assertEqual(L.取参数_按宽(宽)['抽屉宽'] > 0, True)


class Test档位参数(unittest.TestCase):

    def test_抽屉宽逐档(self):
        self.assertEqual(L.取参数(L.宽)['抽屉宽'], 320)
        self.assertEqual(L.取参数(L.中)['抽屉宽'], 320, '≤1100 档设计稿不改抽屉')
        self.assertEqual(L.取参数(L.窄)['抽屉宽'], 280)

    def test_统计列数逐档(self):
        self.assertEqual(L.取参数(L.宽)['统计列数'], 5)
        self.assertEqual(L.取参数(L.中)['统计列数'], 5)
        self.assertEqual(L.取参数(L.窄)['统计列数'], 3)

    def test_日志展开限高逐档(self):
        self.assertEqual(L.取参数(L.宽)['日志展开高'], 400)
        self.assertEqual(L.取参数(L.窄)['日志展开高'], 260, '≤960 档要限到 260')

    def test_任何档都不隐藏任务表列(self):
        """用户 2026-10-07 拍板: 对齐设计稿 —— 固定 910px + 横滚, 不靠隐藏列消溢出。

        旧策略 (≤1200 隐藏 引擎/反爬/耗时/质检 四列压到 606px) 已废弃,
        这条断言就是防止有人"顺手"把隐藏列改回来。
        """
        for 档 in (L.宽, L.中, L.窄):
            p = L.取参数(档)
            self.assertFalse(p['隐藏次级列'], f'{档}档不该隐藏任务表列')
            self.assertEqual(p['表格固定宽'], 910, f'{档}档表宽应恒为设计稿的 910px')

    def test_未知档位回落基准(self):
        self.assertEqual(L.取参数('不存在的档'), L.取参数(L.宽))
        self.assertEqual(L.取参数(''), L.取参数(L.宽))
        self.assertEqual(L.取参数(None), L.取参数(L.宽))

    def test_取参数是副本不被外部改坏(self):
        p = L.取参数(L.宽)
        p['抽屉宽'] = 9999
        self.assertEqual(L.取参数(L.宽)['抽屉宽'], 320, '取参数必须返回副本')


class Test与设计稿交叉校验(unittest.TestCase):
    """直接读 `界面设计预览/index.html` 的 @media 数值 —— 设计稿改了就得跟。"""

    def test_设计稿断点存在且被覆盖(self):
        断点 = L.读取设计稿断点()
        self.assertTrue(断点, '读不到设计稿断点 (路径或写法变了?)')
        self.assertIn(1100, 断点)
        self.assertIn(960, 断点)
        # 代码阈值必须与设计稿一致
        self.assertEqual(L.中档阈值, 1100, f'设计稿断点={断点}')
        self.assertEqual(L.窄档阈值, 960, f'设计稿断点={断点}')

    def test_实机不可达的两档有据可查(self):
        """≤720/≤480 设计稿有, 但程序 min_width=960 → 桌面端永远到不了。

        这里把"为什么不做"钉成断言: 设计稿自己也写了这条实机约束,
        且程序窗口 min_width 就是 960 → 别有人以为漏做了。
        """
        断点 = L.读取设计稿断点()
        self.assertIn(720, 断点)
        self.assertIn(480, 断点)
        self.assertEqual(L.实机最小宽, 960)
        设计 = (根 / '界面设计预览' / 'index.html').read_text(encoding='utf-8')
        self.assertIn('min_width=960', 设计, '设计稿里的实机约束注记没了')
        # 窗口最小宽必须**大于** 720 → ≤720 档才真的够不到; 一旦它被调小,
        # 该档就变成可达, 必须补实现 (这条断言就是那个哨兵)。
        self.assertGreater(L.实机最小宽, 720,
                           '窗口最小宽已 ≤720 → ≤720 档变可达, 必须补实现')

    def test_档位说明含关键参数(self):
        s = L.档位说明(L.窄)
        self.assertIn('抽屉280px', s.replace(' ', ''))
        self.assertIn('统计3列', s.replace(' ', ''))


class Test当前档进程状态(unittest.TestCase):
    """gui_app 在 resize 时写 `设置当前档`, 页面构建/刷新时读 `当前档`。"""

    def setUp(self):
        self._原 = L.当前档()

    def tearDown(self):
        L.设置当前档(self._原)      # 全局状态, 用完必须还原 (别污染别的用例)

    def test_默认是基准档(self):
        self.assertIn(L.当前档(), (L.宽, L.中, L.窄))

    def test_设置返回是否真变了(self):
        L.设置当前档(L.窄)
        self.assertEqual(L.当前档(), L.窄)
        self.assertFalse(L.设置当前档(L.窄), '同档重复设置应返回 False (幂等)')
        self.assertTrue(L.设置当前档(L.宽), '换档应返回 True')

    def test_非法档回落基准(self):
        L.设置当前档('乱七八糟')
        self.assertEqual(L.当前档(), L.宽)


class Test任务表不隐藏列(unittest.TestCase):
    """结构性护栏: 任务表**任何档**都不隐藏列 (设计稿 910px + 横滚)。

    为什么不只测参数表: 参数表正确, 但 task_table 里"顺手"把某一列
    `visible=False` / `width=0` 改回去, 门禁会全绿而用户看不到那一列。
    """

    def setUp(self):
        self.src = (根 / '源码' / 'gui_components' / 'task_table.py').read_text(
            encoding='utf-8')

    def test_应用列可见恒为可见且用设计稿列宽(self):
        块 = self.src.split('def _应用列可见')[1][:900]
        # ⚠️ 必须先剥掉 docstring 与整行注释再断言 —— 该方法的 docstring
        # 正是用来记录"旧实现 visible=False / width=0"的, 直接 assertNotIn
        # 会把**注释**当成代码命中 (项目已有同类教训: 见 test_八项需求._去整行注释)。
        if '"""' in 块:
            块 = 块.split('"""', 2)[2]          # 去掉方法自身的 docstring
        码 = '\n'.join(l for l in 块.splitlines()
                      if not l.strip().startswith('#'))
        self.assertIn('单元.visible = True', 码,
                      '列必须恒可见 (旧实现按窄档置 visible=False)')
        self.assertNotIn('visible = False', 码)
        self.assertNotIn('visible=False', 码)
        self.assertNotIn('单元.width = 0', 码, '不得把列宽归零来"隐藏"')
        self.assertIn('_COLUMNS[列号][1]', 码, '列宽必须取设计稿列定义')

    def test_八列定义齐全(self):
        import re
        self.assertIn('_COLUMNS = [', self.src)
        块 = self.src.split('_COLUMNS = [')[1].split(']')[0]
        列 = re.findall(r'\(\s*"([^"]+)"\s*,\s*(\d+)\s*,', 块)
        self.assertEqual(len(列), 8, f'应有 8 列, 实得 {[c[0] for c in 列]}')
        宽 = sum(int(w) for _n, w in 列)
        self.assertEqual(宽, 852, '列宽合计应保持设计稿的 852px (表宽 910 由此推)')
        self.assertEqual([n for n, _w in 列][-1], '操作', '操作列必须在最后')

    def test_设有档位接口且兼容旧接口(self):
        self.assertIn('def 设置档位', self.src, 'gui_app 的 resize 回调要调它')
        self.assertIn('def 设置窄档', self.src, '旧接口保留 (别让调用点 KeyError)')


class Test统计卡按档折行(unittest.TestCase):
    """设计稿 ≤960 是 `.stats-row repeat(3,1fr)` → 5 张卡排成 3+2。"""

    def setUp(self):
        import _沙箱  # noqa: F401
        from gui_components.pages.history_page import HistoryPage
        self.page = HistoryPage()
        self.page.build()
        self._原档 = L.当前档()

    def tearDown(self):
        L.设置当前档(self._原档)

    def test_基准档一行五张(self):
        L.设置当前档(L.宽)
        self.page._排统计卡([object() for _ in range(5)])
        self.assertEqual(len(self.page._stat_row.controls), 5)
        self.assertEqual(len(self.page._stat_row2.controls), 0)
        self.assertFalse(self.page._stat_row2.visible)

    def test_窄档三加二折行(self):
        L.设置当前档(L.窄)
        self.page._排统计卡([object() for _ in range(5)])
        self.assertEqual(len(self.page._stat_row.controls), 3, '第一行 3 张')
        self.assertEqual(len(self.page._stat_row2.controls), 2, '第二行 2 张')
        self.assertTrue(self.page._stat_row2.visible, '第二行必须可见')
        self.assertEqual(len(self.page._stat_row.controls)
                         + len(self.page._stat_row2.controls), 5, '一张都不能丢')

    def test_来回切档不丢卡(self):
        for 档 in (L.窄, L.宽, L.窄, L.中, L.宽):
            L.设置当前档(档)
            self.page._排统计卡([object() for _ in range(5)])
            总 = (len(self.page._stat_row.controls)
                 + len(self.page._stat_row2.controls))
            self.assertEqual(总, 5, f'{档}档后丢了卡')

    def test_设有档位接口且能重排(self):
        """gui_app 的 resize 回调要调 `设置档位` —— 本页只在切页时 refresh(),
        所以**必须**有这个入口, 否则窗口拖窄后统计卡永远不折行
        (2026-10-07 实测踩到: 日志已打印"窄档", 卡片仍是 5 张一行)。"""
        self.assertTrue(callable(getattr(self.page, '设置档位', None)),
                        'HistoryPage 缺 设置档位 → gui_app 通知不到')
        L.设置当前档(L.窄)
        self.page.设置档位(L.窄, L.取参数(L.窄))
        self.assertEqual(len(self.page._stat_row.controls), 3)
        self.assertEqual(len(self.page._stat_row2.controls), 2)
        L.设置当前档(L.宽)
        self.page.设置档位(L.宽, L.取参数(L.宽))
        self.assertEqual(len(self.page._stat_row.controls), 5)
        self.assertFalse(self.page._stat_row2.visible)


class Test抽屉与日志条按档(unittest.TestCase):
    """工作台右栏: 抽屉宽 320→280, 且窄档要**自动收起底部日志条**。

    为什么要自动收起 (2026-10-07 EXE 实测): 逻辑 952px 时左列只剩 ~430px 宽,
    输入卡换行后很高, 日志条再占 160-180px 就**把任务表挤到 0 高 (整张表看不见)**。
    设计稿对同一小屏问题的处理是"展开态限高, 避免吃掉整屏" → 收起来是同一意图。
    """

    def setUp(self):
        import _沙箱  # noqa: F401
        from gui_components.detail_drawer import DetailDrawer
        from gui_components.task_manager import TaskManager
        self.d = DetailDrawer(TaskManager(page=None))
        self.d.build()
        self.d.build_log_strip()
        self._原档 = L.当前档()
        L.设置当前档(L.窄)
        self.d.设置档位(L.窄, L.取参数(L.窄))

    def tearDown(self):
        L.设置当前档(self._原档)

    def test_抽屉宽度按档(self):
        self.assertEqual(self.d.container.width, 280)
        L.设置当前档(L.宽)
        self.d.设置档位(L.宽, L.取参数(L.宽))
        self.assertEqual(self.d.container.width, 320)

    def test_窄档自动收起日志条(self):
        self.assertFalse(self.d._日志条展开,
                         '窄档必须自动收起日志条, 否则会把任务表挤到 0 高')
        self.assertFalse(self.d._日志条体.visible)

    def test_日志条高度取档位表(self):
        self.assertEqual(self.d._日志条体.height, L.取参数(L.窄)['日志基础高'])

    def test_宽档不强行展开(self):
        """自动收起是单向的: 回到宽档不自动展开 (用户自己开, 别替他决定)"""
        L.设置当前档(L.宽)
        self.d.设置档位(L.宽, L.取参数(L.宽))
        self.assertFalse(self.d._日志条展开)

    def test_纯手动展开在宽档仍可用(self):
        L.设置当前档(L.宽)
        self.d.设置档位(L.宽, L.取参数(L.宽))
        self.d.切换日志条()
        self.assertTrue(self.d._日志条展开)
        self.assertTrue(self.d._日志条体.visible)


if __name__ == '__main__':
    unittest.main(verbosity=2)
