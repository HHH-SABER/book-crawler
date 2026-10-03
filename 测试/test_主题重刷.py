# -*- coding: utf-8 -*-
"""主题重刷护栏 (Phase 3, 2026-10-04): 切主题后**已构建控件必须真的换色**。

背景: 页面此前写 `from ..ui_fluent import MORANDI_ERROR` —— 绑到的是**构建期求值的
字符串对象**; `ui_fluent.刷新兼容常量()` 的 `globals().update` 只改 ui_fluent 自己的
命名空间, 改不动页面里的本地引用 → 切夜间主题页面纹丝不动 (见
`文档/审查报告汇总.md` 的 Phase 3 结论)。

判据设计 (为什么不查源码写了什么):
- `仅日间色值` = 出现在日间调色板、但在夜间调色板**完全不存在**的那些色值。
  一个控件若在切到夜间后仍持有这类值, 说明它**没有被重刷** —— 这是行为事实, 与
  写法无关 (用工厂建的、或登记过重刷的, 都会变成夜间色)。
- 日夜相同的色 (恒深终端色等) 天然被排除, 不会误报。

迁移进度表在 `_已迁移` 里逐个追加; 未列入的文件暂不约束 (渐进式迁移, 门禁始终绿)。
"""
import re
import unittest
from pathlib import Path

import _沙箱  # noqa: F401  沙箱: 状态根 → 一次性临时目录

from gui_components import ui_tokens

_ROOT = Path(__file__).resolve().parents[1]
_GUI = _ROOT / '源码' / 'gui_components'

# Phase 3 迁移进度: 这些文件必须已彻底脱离 MORANDI_* 字面量
# (detail_drawer.py / row_detail.py 仍在迁移中, 完成后追加)
_已迁移 = [
    'log_tab.py',
    'task_table.py',
    'detail_drawer.py',
    'row_detail.py',
    'pages/dead_book_page.py',
    'pages/history_page.py',
    'pages/remote_page.py',
    'pages/site_manage_page.py',
]
# gui_app.py 在 源码/ 下 (不在 gui_components/), 单独校验
_已迁移外层 = ['gui_app.py']


def _去注释与文档串(文本: str) -> str:
    """剥掉文档字符串与整行注释后再做静态判定。

    为什么需要: 迁移说明天生要写出"旧写法用了哪个常量" —— 直接拿原文本查,
    说明文字自己就会被当成违规引用 (2026-10-04 实际踩到两次: 一次是注释里提到函数名,
    一次是 docstring 里提到旧常量)。判据应只看**可执行代码**。
    只剥整行注释 (行尾 `#` 不能碰: 代码里有 '`#AD5710`' 之类颜色字面量)。
    """
    文本 = re.sub(r'"""(?:.|\n)*?"""', '', 文本)
    文本 = re.sub(r"'''(?:.|\n)*?'''", '', 文本)
    return '\n'.join(l for l in 文本.splitlines() if not l.strip().startswith('#'))


def _仅日间色值() -> set:
    """夜里根本不存在的色值集合 (持有它 = 没被重刷)"""
    日 = {v for v in ui_tokens._日间.values() if isinstance(v, str)}
    夜 = {v for v in ui_tokens._夜间色.values() if isinstance(v, str)}
    return 日 - 夜


def _收集残留(根, 仅日间: set) -> list:
    """遍历控件树, 收集仍持有"仅日间色值"的 (控件类名, 属性, 值)"""
    出 = []
    待查 = [根]
    已见 = set()
    while 待查:
        当前 = 待查.pop()
        if 当前 is None or id(当前) in 已见:
            continue
        已见.add(id(当前))
        for 属性 in ('color', 'bgcolor'):
            值 = getattr(当前, 属性, None)
            if isinstance(值, str) and 值 in 仅日间:
                出.append((type(当前).__name__, 属性, 值))
        for 子 in (getattr(当前, 'controls', None) or []):
            待查.append(子)
        内容 = getattr(当前, 'content', None)
        if 内容 is not None:
            待查.append(内容)
    return 出


class Test主题重刷(unittest.TestCase):

    def setUp(self):
        ui_tokens.清空重刷表()
        ui_tokens.设置主题(False, 立即重刷=False)

    def tearDown(self):
        ui_tokens.清空重刷表()
        ui_tokens.设置主题(False, 立即重刷=False)

    def test_日志错误文本切主题会换色(self):
        from gui_components.log_tab import 错误文本
        控件 = 错误文本('文件不存在: x')
        原色 = 控件.color
        self.assertTrue(原色, '错误文本应有颜色')
        ui_tokens.设置主题(True)
        self.assertNotEqual(控件.color, 原色,
                            '错误提示切夜间后没换色 —— 说明绑的是字符串常量而非令牌')
        ui_tokens.设置主题(False)
        self.assertEqual(控件.color, 原色, '切回日间应还原原色')

    def test_日志页控件树无日间色残留(self):
        from gui_components.log_tab import LogTab, 错误文本
        页 = LogTab()
        根 = 页.build()
        页.log_list.controls.append(错误文本('读取失败: 模拟'))   # 制造"有色控件"场景
        仅日间 = _仅日间色值()
        self.assertTrue(仅日间, '令牌表应存在日夜不同的色值 (否则本护栏失去意义)')
        ui_tokens.设置主题(True)
        残留 = _收集残留(根, 仅日间)
        self.assertEqual(残留, [], f'切夜间后仍有控件保持日间专有色: {残留[:6]}')

    def test_已迁移文件不得再有MORANDI字面量(self):
        for 名 in _已迁移:
            文本 = _去注释与文档串((_GUI / 名).read_text(encoding='utf-8'))
            用 = sorted(set(re.findall(r'\bMORANDI_[A-Z_]+', 文本)))
            self.assertEqual(用, [], f'{名} 仍直接引用 MORANDI 常量: {用}')
        for 名 in _已迁移外层:
            文本 = _去注释与文档串((_ROOT / '源码' / 名).read_text(encoding='utf-8'))
            用 = sorted(set(re.findall(r'\bMORANDI_[A-Z_]+', 文本)))
            self.assertEqual(用, [], f'源码/{名} 仍直接引用 MORANDI 常量: {用}')

    # ---- 行为验收: 逐页构建控件树, 翻主题 → 不得有"仅日间色"残留 ----
    # 这是对"迁移是否真的成立"的**唯一可靠判据**: 只写 取色() 不登记 登记重刷()
    # 属半迁移, 计数看着干净但切主题照样不掉色。

    def _验收控件树(self, 根, 名称: str):
        仅日间 = _仅日间色值()
        self.assertTrue(仅日间, '令牌表应有日夜不同的色值')
        # 防空测试: 若这棵树里压根没有令牌色, "翻转后无残留"就是废话
        翻转前 = _收集残留(根, 仅日间)
        self.assertTrue(翻转前,
                        f'{名称} 构建后不存在任何令牌色控件 —— 用例对该页是空测试, '
                        f'要么页面没接令牌, 要么控件未真正挂进树')
        ui_tokens.设置主题(True)
        残留 = _收集残留(根, 仅日间)
        self.assertEqual(残留, [],
                         f'{名称} 切夜间后仍有控件保持日间专有色 (半迁移): {残留[:6]}')

    def test_日志页控件树(self):
        from gui_components.log_tab import LogTab, 错误文本
        页 = LogTab()
        根 = 页.build()
        页.log_list.controls.append(错误文本('读取失败: 模拟'))
        self._验收控件树(根, 'log_tab')

    def test_死书清单页控件树(self):
        from gui_components.pages.dead_book_page import DeadBookPage
        页 = DeadBookPage()
        根 = 页.build()
        self._验收控件树(根, 'dead_book_page')

    def test_爬取历史页控件树(self):
        from gui_components.pages.history_page import HistoryPage
        根 = HistoryPage().build()
        self._验收控件树(根, 'history_page')

    def test_远控页控件树(self):
        from gui_components.pages.remote_page import RemotePage
        页 = RemotePage()
        根 = 页.build()
        self._验收控件树(根, 'remote_page')

    def test_站点管理页控件树(self):
        from gui_components.pages.site_manage_page import SiteManagePage
        根 = SiteManagePage().build()
        self._验收控件树(根, 'site_manage_page')

    def test_任务表控件树(self):
        """⚠ 必须先注入任务: 空表的控件树里没有任何令牌色, 是**空验证**
        (2026-10-04 由"_验收控件树"的非空前置断言当场发现)。"""
        from gui_components.task_manager import TaskManager, TaskInfo
        from gui_components.task_table import TaskTable
        mgr = TaskManager(page=None)
        mgr.tasks['t1'] = TaskInfo(task_id='t1', url='https://example.com/b',
                                   title='测试书甲', status='running')
        mgr.tasks['t2'] = TaskInfo(task_id='t2', url='https://example.com/c',
                                   title='测试书乙', status='completed')
        页 = TaskTable(mgr)
        根 = 页.build()
        页._refresh()          # 建出数据行 (状态徽章/进度条的颜色在这里产生)
        self._验收控件树(根, 'task_table')

    def test_详情抽屉控件树(self):
        from gui_components.detail_drawer import DetailDrawer
        from gui_components.task_manager import TaskManager
        根 = DetailDrawer(TaskManager(page=None)).build()
        self._验收控件树(根, 'detail_drawer')

    def test_任务行详情控件树(self):
        from gui_components.row_detail import build_row_detail
        from gui_components.task_manager import TaskInfo
        根 = build_row_detail(TaskInfo(task_id='t1', url='https://example.com/b',
                                       title='测试书'))
        self._验收控件树(根, 'row_detail')


class Test状态色可区分(unittest.TestCase):
    """Phase 3 收尾 (2026-10-04): **必须一眼分出的状态, 语义色不得相同**。

    审计发现 `dead_pending`(书已删除 —— 需要用户裁决) 与 `interrupted`(已中断 ——
    只是进程退出导致没跑完, 无需处理) **完全同色** → 任务表里分不出"哪一行要我去点"。
    现 `interrupted` 归中性灰族, `dead_pending` 独占琥珀警告色。
    """

    def _任务状态色(self, 任务状态: str):
        """走真实链路: 任务状态 → 徽章语义 → 状态色 (日间)"""
        语义键 = ui_tokens.徽章语义.get(任务状态, 'pending')
        return ui_tokens.状态色(语义键, False)

    def test_死书待确认与已中断必须可区分(self):
        self.assertNotEqual(self._任务状态色('dead_pending'),
                            self._任务状态色('interrupted'),
                            '两个语义相反的状态同色 → 用户分不出哪行需要处理')

    def test_死书待确认与失败必须可区分(self):
        self.assertNotEqual(self._任务状态色('dead_pending'),
                            self._任务状态色('failed'))

    def test_已中断与失败必须可区分(self):
        self.assertNotEqual(self._任务状态色('interrupted'),
                            self._任务状态色('failed'))

    def test_已中断不再占用警告色(self):
        """回归锁: 不许再改回与 running（抓取中）/ dead_pending（书已删除）同色"""
        self.assertNotEqual(self._任务状态色('interrupted'),
                            ui_tokens.状态色('warning', False),
                            '已中断又变回警告色 → 会与 抓取中/书已删除 撞色')


if __name__ == '__main__':
    unittest.main(verbosity=2)
