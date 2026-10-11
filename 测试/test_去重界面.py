# -*- coding: utf-8 -*-
"""去重界面接入回归 (2026-10-07 新增, 全离线: 假页 + 桩, 零真实文件 IO)。

锁定 源码/gui_components/detail_drawer.py 的查重入口契约:
  - 「查重」走工作线程扫描, 扫描中重复点击不重入
  - 结果弹窗分支: 无重复 / 得检测错误 / 有多组
  - **只有存在「可自动清理」项时** "移入隔离区并清理" 才可点
  - 清理只作用于各组 可自动清理 项, 且恒用 '隔离' 模式 (可反悔)
  - 弹窗文字显式带 color (v2.4.19 G-H1: EXE 缺色渲染成不可见)
运行: python -m unittest discover -s 测试
"""
import asyncio
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))
sys.path.insert(0, str(_根 / '测试'))

import _沙箱          # noqa: E402,F401  状态根沙箱 (LOCALAPPDATA 隔离)
import flet as ft     # noqa: E402
from gui_components.detail_drawer import DetailDrawer   # noqa: E402
from gui_components.task_manager import TaskManager      # noqa: E402


class _假页:
    """最小 flet Page 替身: 记录弹窗与 update 次数, run_task 同步跑完协程。"""

    def __init__(self):
        self.dialogs = []
        self.updates = 0

    def show_dialog(self, ctrl):
        self.dialogs.append(ctrl)

    def pop_dialog(self):
        if self.dialogs:
            self.dialogs.pop()

    def update(self):
        self.updates += 1

    def run_task(self, coro):
        asyncio.run(coro)


def _收集文本(ctrl) -> str:
    """递归收集控件树里所有 Text.value。"""
    片段 = []

    def _走(c):
        if c is None:
            return
        v = getattr(c, 'value', None)
        if isinstance(v, str) and v:
            片段.append(v)
        for 属性 in ('content', 'title', 'text'):
            子 = getattr(c, 属性, None)
            if 子 is not None and not isinstance(子, str):
                _走(子)
        for 属性 in ('controls', 'actions'):
            子列表 = getattr(c, 属性, None)
            if isinstance(子列表, (list, tuple)):
                for x in 子列表:
                    _走(x)
    _走(ctrl)
    return ' '.join(片段)


def _造组(键='k1', 名='保留书.txt', 字数=1000, 可清理=(), 待确认=()):
    return {
        '键': 键,
        '代表': {'路径': f'X:/{名}', '名': 名, '字数': 字数, '字节': 1},
        '可自动清理': [{'路径': f'X:/{n}', '名': n, '字数': w, '字节': 1,
                    '判定': '同一本', '理由': 'r', '指标': {}} for n, w in 可清理],
        '待确认': [{'路径': f'X:/{n}', '名': n, '字数': w, '字节': 1,
                 '判定': '疑似(待人工确认)', '理由': 'r', '指标': {}} for n, w in 待确认],
        '剔除': [],
        '组成员数': 1 + len(可清理) + len(待确认),
    }


class Test查重入口(unittest.TestCase):

    def setUp(self):
        self.d = DetailDrawer(TaskManager(page=None))
        self.页 = _假页()
        self.d.page = self.页

    def test_无重复时弹窗提示且清理按钮禁用(self):
        self.d._显示查重结果([], '')
        self.assertEqual(len(self.页.dialogs), 1)
        文本 = _收集文本(self.页.dialogs[0])
        self.assertIn('未发现重复文件', 文本)
        self.assertTrue(self.页.dialogs[0].actions[1].disabled,
                        '无重复时"移入隔离区并清理"应禁用')

    def test_检测错误时显示错误文案(self):
        self.d._显示查重结果([], 'PermissionError: 拒绝访问')
        self.assertEqual(len(self.页.dialogs), 1)
        文本 = _收集文本(self.页.dialogs[0])
        self.assertIn('检测失败', 文本)
        self.assertIn('PermissionError', 文本)

    def test_有多组时可清理按钮可用且列出保留项(self):
        组 = [_造组(名='保留书.txt', 可清理=[('副本.txt', 900)])]
        self.d._显示查重结果(组, '')
        dlg = self.页.dialogs[0]
        文本 = _收集文本(dlg)
        self.assertIn('保留书.txt', 文本)
        self.assertIn('副本.txt', 文本)
        self.assertIn('发现 1 组重复', 文本)
        self.assertFalse(dlg.actions[1].disabled, '有可清理项时按钮应可点')

    def test_只有待确认项时清理按钮禁用(self):
        组 = [_造组(待确认=[('疑似.txt', 800)])]
        self.d._显示查重结果(组, '')
        dlg = self.页.dialogs[0]
        self.assertIn('疑似.txt', _收集文本(dlg))
        self.assertTrue(dlg.actions[1].disabled,
                        '全是待确认项时不该给"清理"入口 (灰区不自动处理)')

    def test_弹窗文字显式带颜色(self):
        """v2.4.19 G-H1: EXE 里缺 color 的文字渲染成不可见。"""
        组 = [_造组(可清理=[('副本.txt', 900)])]
        self.d._显示查重结果(组, '')
        dlg = self.页.dialogs[0]

        def _查(c):
            if isinstance(c, ft.Text):
                self.assertIsNotNone(c.color, f'Text 缺 color: {c.value!r}')
            for 属性 in ('content', 'title'):
                子 = getattr(c, 属性, None)
                if 子 is not None and not isinstance(子, str):
                    _查(子)
            for 属性 in ('controls', 'actions'):
                子列表 = getattr(c, 属性, None)
                if isinstance(子列表, (list, tuple)):
                    for x in 子列表:
                        _查(x)
        _查(dlg)

    def test_扫描走线程并写入清单(self):
        组 = [_造组()]
        调 = {'写出': 0}

        def _假扫描(目录=None):
            return 组

        def _假写出(列表):
            调['写出'] += 1
            self.assertEqual(列表, 组)
            return 1

        with mock.patch('去重处理.扫描重复', _假扫描), \
                mock.patch('去重处理.写出清单', _假写出):
            self.d._检测重复()
            for _ in range(200):          # 等扫描线程结束 (最长 ~4s)
                if not self.d._查重中:
                    break
                time.sleep(0.02)
            self.assertFalse(self.d._查重中, '扫描应已结束')
            time.sleep(0.05)              # 让 _dispatch 的 run_task 跑完
        self.assertEqual(调['写出'], 1, '扫描结果应写入去重清单')
        self.assertTrue(self.页.dialogs, '应弹出结果弹窗')

    def test_扫描中重复点击不重入(self):
        self.d._查重中 = True
        with mock.patch('去重处理.扫描重复') as m:
            self.d._检测重复()
            m.assert_not_called()
        self.d._查重中 = False

    def test_清理只作用于可自动清理项且恒用隔离模式(self):
        组甲 = _造组(键='ka', 可清理=[('a1.txt', 9)])
        组乙 = _造组(键='kb', 待确认=[('b1.txt', 9)])   # 无可清理
        调用 = []

        def _假清理(键, 模式='隔离', 隔离目录=None):
            调用.append((键, 模式))
            return {'清理': ['x'], '失败': [], '模式': 模式, '隔离目录': ''}

        with mock.patch('去重处理.执行清理', _假清理):
            self.d._执行查重清理([组甲, 组乙], ft.AlertDialog())
            time.sleep(0.2)               # 等清理线程跑完
        self.assertEqual(调用, [('ka', '隔离')],
                         '只有含可自动清理项的组才执行, 且模式必须是 隔离')

    def test_无页面时不抛(self):
        self.d.page = None
        self.d._显示查重结果([_造组()], '')     # 应静默返回
        self.d._执行查重清理([_造组()], ft.AlertDialog())


def _收集按钮(ctrl):
    """递归收集控件树里的 TextButton (按 label 找按钮用)。"""
    出 = []

    def _走(c):
        if isinstance(c, ft.TextButton):
            出.append(c)
        for 属性 in ('content', 'title'):
            子 = getattr(c, 属性, None)
            if 子 is not None and not isinstance(子, str):
                _走(子)
        for 属性 in ('controls', 'actions'):
            子列表 = getattr(c, 属性, None)
            if isinstance(子列表, (list, tuple)):
                for x in 子列表:
                    _走(x)

    _走(ctrl)
    return 出


def _标签(按钮) -> str:
    """取 TextButton 的标签 (Flet 0.86 无 .text: 标签在 .content)。"""
    子 = getattr(按钮, 'content', None)
    if isinstance(子, str):
        return 子
    return str(getattr(子, 'value', '') or '')


def _造记录(键='k1', 状态='已清理', 可清理=(), 待确认=()):
    """造一条 **去重清单** 形状的记录 (区别于 _造组 —— 那是扫描结果形状)。"""
    return {
        '键': 键,
        '状态': 状态,
        '代表': {'路径': 'X:/保留书.txt', '名': '保留书.txt',
                 '字数': 1000, '字节': 1},
        '可自动清理': [{'路径': f'X:/{n}', '名': n, '字数': w, '字节': 1,
                    '判定': '真子集', '理由': 'r', '指标': {}} for n, w in 可清理],
        '待确认': [{'路径': f'X:/{n}', '名': n, '字数': w, '字节': 1,
                 '判定': '疑似(待人工确认)', '理由': '内容有差异', '指标': {}}
                for n, w in 待确认],
        '最近时间': '2026-10-11 00:00', '次数': 1, '首次时间': '2026-10-11 00:00',
    }


class Test查重弹窗展示自动去重记录(unittest.TestCase):
    """C10: 弹窗必须展示**自动去重记录(已清理)** 与 **灰区待确认**, 且动作给对。

    为什么这两类要分开给动作: 已清理项的文件**已被移走**(扫描不到), 该给「还原」;
    灰区项的文件**还在结果目录里**(从未移动), 给它「还原」是错的, 该给「隔离」
    (即点名批准路径)。
    """

    def setUp(self):
        self.d = DetailDrawer(TaskManager(page=None))
        self.页 = _假页()
        self.d.page = self.页

    # ------------------------------------------------------ 分拣 (纯函数)
    def test_分拣_已清理进可还原_待确认进灰区_已忽略都不进(self):
        记录 = [
            _造记录(键='k1', 状态='已清理', 可清理=[('甲.txt', 10)]),
            _造记录(键='k2', 状态='待确认', 待确认=[('乙.txt', 20)]),
            _造记录(键='k3', 状态='已忽略', 可清理=[('丙.txt', 30)]),
        ]
        可还原, 灰区 = DetailDrawer._分拣去重记录(记录)
        self.assertEqual([x['名'] for x in 可还原], ['甲.txt'])
        self.assertEqual([x['键'] for x in 可还原], ['k1'])
        self.assertEqual([x['名'] for x in 灰区], ['乙.txt'])
        self.assertEqual([x['键'] for x in 灰区], ['k2'])
        self.assertEqual(可还原[0]['字数'], 10)

    def test_分拣_空与异常输入不炸(self):
        self.assertEqual(DetailDrawer._分拣去重记录([]), ([], []))
        self.assertEqual(DetailDrawer._分拣去重记录(None), ([], []))

    # ------------------------------------------------------ 弹窗渲染
    def test_弹窗列出已清理项与还原按钮(self):
        记录 = [_造记录(状态='已清理', 可清理=[('示例书名甲(1).txt', 50)])]
        self.d._显示查重结果([], '', 记录)
        dlg = self.页.dialogs[0]
        文本 = _收集文本(dlg)
        self.assertIn('已自动去重 1 个', 文本)
        self.assertIn('示例书名甲(1).txt', 文本)
        还原 = [b for b in _收集按钮(dlg) if _标签(b) == '还原']
        self.assertEqual(len(还原), 1)

    def test_弹窗列出灰区项与隔离按钮(self):
        记录 = [_造记录(状态='待确认', 待确认=[('示例书乙.txt', 20)])]
        self.d._显示查重结果([], '', 记录)
        dlg = self.页.dialogs[0]
        文本 = _收集文本(dlg)
        self.assertIn('待确认 1 个', 文本)
        self.assertIn('示例书乙.txt', 文本)
        隔离 = [b for b in _收集按钮(dlg) if _标签(b) == '隔离']
        self.assertEqual(len(隔离), 1)
        self.assertNotIn('还原', [_标签(b) for b in _收集按钮(dlg)],
                         '从未移动过的灰区项不该有「还原」')

    def test_无记录时不多画栏(self):
        self.d._显示查重结果([], '', [])
        self.assertNotIn('已自动去重', _收集文本(self.页.dialogs[0]))

    # ------------------------------------------------------ 按钮绑定 (防闭包晚绑定)
    def test_每个还原按钮绑定自己那一项(self):
        """⚠️ 关键用例: 循环里建 lambda 若不绑默认参数, 所有按钮都会作用于**最后一项**。"""
        记录 = [_造记录(状态='已清理',
                     可清理=[('甲.txt', 10), ('乙.txt', 20), ('丙.txt', 30)])]
        self.d._显示查重结果([], '', 记录)
        dlg = self.页.dialogs[0]
        调用 = []
        self.d._还原副本 = lambda 键, 名, dialog=None: 调用.append((键, 名))
        for b in [x for x in _收集按钮(dlg) if _标签(x) == '还原']:
            b.on_click(None)
        self.assertEqual([名 for _, 名 in 调用], ['甲.txt', '乙.txt', '丙.txt'])

    def test_隔离按钮走点名批准(self):
        记录 = [_造记录(状态='待确认', 待确认=[('灰区甲.txt', 10), ('灰区乙.txt', 20)])]
        self.d._显示查重结果([], '', 记录)
        dlg = self.页.dialogs[0]
        调用 = []
        self.d._隔离确认项 = lambda 键, 名, dialog=None: 调用.append((键, 名))
        for b in [x for x in _收集按钮(dlg) if _标签(x) == '隔离']:
            b.on_click(None)
        self.assertEqual([名 for _, 名 in 调用], ['灰区甲.txt', '灰区乙.txt'])

    def test_灰区只隔离被点的那一项(self):
        """点名批准必须**逐项**: 调 执行清理 时要带 额外确认项=[该项名]。"""
        记录 = [_造记录(键='k9', 状态='待确认',
                     待确认=[('灰区甲.txt', 10), ('灰区乙.txt', 20)])]
        调用 = []

        def _假清理(键, 模式='隔离', 隔离目录=None, 额外确认项=None):
            调用.append((键, 模式, list(额外确认项 or [])))
            return {'清理': list(额外确认项 or []), '失败': [],
                    '模式': 模式, '隔离目录': ''}

        with mock.patch('去重处理.执行清理', _假清理):
            self.d._隔离确认项('k9', '灰区乙.txt', ft.AlertDialog())
            time.sleep(0.3)
        self.assertEqual(调用, [('k9', '隔离', ['灰区乙.txt'])],
                         '必须只批准被点名的那一项, 且恒用隔离模式')

    def test_展示记录时新文字仍显式带颜色(self):
        """v2.4.19 G-H1: EXE 里缺 color 的文字渲染成不可见 —— 新栏同样要守。"""
        记录 = [_造记录(状态='已清理', 可清理=[('甲.txt', 10)]),
                _造记录(键='k2', 状态='待确认', 待确认=[('乙.txt', 20)])]
        self.d._显示查重结果([], '', 记录)
        dlg = self.页.dialogs[0]

        def _查(c):
            if isinstance(c, ft.Text):
                self.assertIsNotNone(c.color, f'Text 缺 color: {c.value!r}')
            for 属性 in ('content', 'title'):
                子 = getattr(c, 属性, None)
                if 子 is not None and not isinstance(子, str):
                    _查(子)
            for 属性 in ('controls', 'actions'):
                子列表 = getattr(c, 属性, None)
                if isinstance(子列表, (list, tuple)):
                    for x in 子列表:
                        _查(x)
        _查(dlg)

    def test_只有灰区时_清理按钮仍禁用(self):
        """灰区**绝不**走"一键清理" —— 新栏不能把它变成可自动处理的入口。"""
        记录 = [_造记录(状态='待确认', 待确认=[('灰区.txt', 20)])]
        self.d._显示查重结果([], '', 记录)
        dlg = self.页.dialogs[0]
        self.assertTrue(dlg.actions[1].disabled, '灰区不该给"移入隔离区并清理"入口')
        self.assertNotIn('还原', [_标签(b) for b in _收集按钮(dlg)])


if __name__ == '__main__':
    unittest.main()
