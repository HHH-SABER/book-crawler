# -*- coding: utf-8 -*-
"""死书「补新网站」交互流程回归（2026-10-06 新功能）。

对应需求："死书时询问用户是否要添加书籍新网站，没有的话就询问是否删除"。

本文件测**决策逻辑**（`gui_components/补址弹窗.py::补址流程/场景文案`）与
**弹窗结构契约**（按钮与输入框必须存在、两步齐全）—— 视图与逻辑分层后，
这些都能离线断言，不需要真机。

真机行为（点击路径）在 EXE 实测时复核；数据层见 `测试/test_备用源.py`。
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

import _沙箱  # noqa: F401

import flet as ft

import 备用源
from gui_components import 补址弹窗 as C


class _隔离配置:
    """把备用源落点指到临时文件（绝不动用户真实 captcha_config.json）。"""

    def setUp(self):
        根 = Path(tempfile.mkdtemp(prefix='补址流程_'))
        os.environ[备用源.环境覆盖变量] = str(根 / 'captcha_config.json')
        self.addCleanup(lambda: os.environ.pop(备用源.环境覆盖变量, None))
        self.addCleanup(lambda: __import__('shutil').rmtree(根, ignore_errors=True))


class _假页:
    """最小 page 替身: 只记录弹窗/更新调用, 不碰真 Flet 会话。"""

    def __init__(self):
        self.弹出的 = []
        self.更新的 = 0

    def show_dialog(self, ctrl):
        self.弹出的.append(ctrl)

    def pop_dialog(self):
        if self.弹出的:
            self.弹出的.pop()

    def update(self):
        self.更新的 += 1


def _标签(按钮) -> str:
    """取按钮文案。Flet 0.86 的 TextButton 没有 `.text`, 标签落在 `content`。

    (这里踩过一次: 先按 `.text` 断言 → AttributeError, 5 个用例全红。)
    """
    c = getattr(按钮, 'content', None)
    if isinstance(c, str):
        return c
    return str(getattr(c, 'value', '') or '')


class Test文案与结构(_隔离配置, unittest.TestCase):

    def test_两种场景文案都提到备用源(self):
        for 场景 in (C.场景_网站失效, C.场景_其他):
            with self.subTest(场景=场景):
                文案 = C.场景文案(场景, '某本书', '目录无章节', '未解析出章节')
                for 键 in ('标题', '正文', '追问标题', '追问正文'):
                    self.assertTrue(文案.get(键), f'{键} 不能为空')
                self.assertIn('备用源', 文案['正文'], '必须告诉用户"添加后会成为备用源"')
                self.assertIn('删除', 文案['追问正文'], '第二步必须问是否删除')
        # 场景文案必须可区分: 域名死亡 vs 疑似失效
        self.assertNotEqual(C.场景文案(C.场景_网站失效, '书')['标题'],
                            C.场景文案(C.场景_其他, '书')['标题'])

    def test_追问文案承诺不删产物(self):
        """删除确认必须说明"已下载的文件不会被删除" —— 否则用户不敢删。"""
        for 场景 in (C.场景_网站失效, C.场景_其他):
            with self.subTest(场景=场景):
                self.assertRegex(C.场景文案(场景, '书')['追问正文'],
                                 r'不会删除|不会被删除')

    def test_疑似场景不鼓励删书(self):
        """目录无章节常常只是选择器失效 —— 文案要引导先重新检测。"""
        文案 = C.场景文案(C.场景_其他, '书', '目录无章节')
        self.assertIn('重新检测', 文案['追问正文'])

    def test_弹窗文字都显式给色(self):
        """EXE 契约 (v2.4.19 G-H1): 弹窗文字缺显式 color 会渲染成不可见。"""
        page = _假页()
        对话框 = C.打开补址弹窗(page, 目录URL='https://a.example.com/book/1',
                              标题='某本书', 场景=C.场景_其他)
        self.assertIsNotNone(对话框.title.color, '弹窗标题必须显式给色')
        正文们 = [c for c in 对话框.content.controls if isinstance(c, ft.Text)]
        self.assertTrue(正文们, '正文应有文字控件')
        for c in 正文们:
            self.assertIsNotNone(c.color, f'正文缺显式颜色: {str(c.value)[:16]!r}')
        # 第二步(追问删除)也要显式给色
        [b for b in 对话框.actions if _标签(b) == '没有新网站'][0].on_click(None)
        追问 = [c for c in page.弹出的 if isinstance(c, ft.AlertDialog) and c is not 对话框][0]
        self.assertIsNotNone(追问.title.color, '追问弹窗标题必须显式给色')
        self.assertIsNotNone(追问.content.color, '追问弹窗正文必须显式给色')

    def test_弹窗第一步有输入框和三个按钮(self):
        page = _假页()
        对话框 = C.打开补址弹窗(page, 目录URL='https://a.example.com/book/1',
                              标题='某本书', 场景=C.场景_其他)
        标签 = [_标签(b) for b in 对话框.actions]
        self.assertIn('添加并重抓', 标签)
        self.assertIn('没有新网站', 标签, '缺"没有新网站"就没有第二步删除追问')
        self.assertIn('稍后处理', 标签)
        控件 = 对话框.content.controls
        输入框 = [c for c in 控件 if isinstance(c, ft.TextField)]
        self.assertEqual(len(输入框), 1, '必须有一个粘贴新网址的输入框')
        self.assertTrue(page.弹出的, '弹窗应已打开')

    def test_第一步添加成功即登记并触发重抓(self):
        调用 = {}
        page = _假页()
        对话框 = C.打开补址弹窗(
            page, 目录URL='https://a.example.com/book/1', 标题='某本书',
            场景=C.场景_其他,
            动作=C.补址动作(添加并重抓=lambda u: 调用.setdefault('新址', u)))
        输入框 = [c for c in 对话框.content.controls if isinstance(c, ft.TextField)][0]
        输入框.value = 'https://b.example.com/novel/1'
        [b for b in 对话框.actions if _标签(b) == '添加并重抓'][0].on_click(None)
        self.assertEqual(备用源.取备用源('https://a.example.com/book/1'),
                         ['https://b.example.com/novel/1'], '应已登记为备用源')
        self.assertEqual(调用.get('新址'), 'https://b.example.com/novel/1',
                         '登记成功后必须立刻用新网址发起抓取')

    def test_第一步非法网址保持弹窗且不登记(self):
        page = _假页()
        对话框 = C.打开补址弹窗(page, 目录URL='https://a.example.com/book/1',
                              标题='某本书', 场景=C.场景_其他)
        输入框 = [c for c in 对话框.content.controls if isinstance(c, ft.TextField)][0]
        输入框.value = '不是网址'
        [b for b in 对话框.actions if _标签(b) == '添加并重抓'][0].on_click(None)
        self.assertEqual(备用源.取备用源('https://a.example.com/book/1'), [],
                         '非法网址不得登记')
        self.assertIn(对话框, page.弹出的, '失败时应保持弹窗让用户改')

    def test_没有新网站会追问删除(self):
        page = _假页()
        对话框 = C.打开补址弹窗(page, 目录URL='https://a.example.com/book/1',
                              标题='某本书', 场景=C.场景_其他)
        [b for b in 对话框.actions if _标签(b) == '没有新网站'][0].on_click(None)
        追问 = [c for c in page.弹出的 if isinstance(c, ft.AlertDialog) and c is not 对话框]
        self.assertEqual(len(追问), 1, '第二步"是否删除"弹窗必须出现')
        标签 = [_标签(b) for b in 追问[0].actions]
        self.assertIn('删除记录', 标签)
        self.assertIn('忽略此书', 标签)


class Test流程逻辑(_隔离配置, unittest.TestCase):
    """直接驱动 `补址流程`（不依赖 Flet 事件包装），钉住状态机语义。"""

    def setUp(self):
        self.动作调用 = []
        动作 = C.补址动作(
            添加并重抓=lambda u: self.动作调用.append(('添加并重抓', u)),
            删除记录=lambda: self.动作调用.append(('删除记录', None)),
            忽略记录=lambda: self.动作调用.append(('忽略记录', None)),
        )
        self.流程 = C.补址流程('https://a.example.com/book/1', 动作,
                             场景=C.场景_其他, 标题='某本书')

    def test_添加成功路径(self):
        结果 = self.流程.尝试添加('https://b.example.com/novel/1')
        self.assertTrue(结果['可以'], 结果['原因'])
        self.assertEqual(self.流程.已添加, 'https://b.example.com/novel/1')
        self.assertEqual(self.动作调用, [('添加并重抓', 'https://b.example.com/novel/1')])

    def test_添加失败不触发重抓(self):
        结果 = self.流程.尝试添加('ftp://x')
        self.assertFalse(结果['可以'])
        self.assertTrue(结果['原因'])
        self.assertIsNone(self.流程.已添加)
        self.assertEqual(self.动作调用, [], '登记失败不得发起抓取')

    def test_没有新网站进入追问(self):
        self.流程.没有新网站()
        self.assertTrue(self.流程.已追问)

    def test_确认删除与忽略各自只触发一次(self):
        self.流程.确认删除()
        self.流程.忽略此书()
        self.assertEqual([c[0] for c in self.动作调用], ['删除记录', '忽略记录'])

    def test_回调缺失时不抛异常(self):
        """清单页/工作台可能只提供部分动作 —— 缺回调必须是安全 no-op。"""
        流程 = C.补址流程('https://a.example.com/book/1', C.补址动作())
        self.assertFalse(流程.确认删除())
        self.assertFalse(流程.忽略此书())
        流程.稍后()
        self.assertTrue(流程.尝试添加('https://b.example.com/novel/1')['可以'],
                        '缺"重抓"回调不影响登记备用源本身')

    def test_回调抛异常被吞并如实返回(self):
        def 炸():
            raise RuntimeError('下游挂了')
        流程 = C.补址流程('https://a.example.com/book/1',
                         C.补址动作(添加并重抓=lambda u: (_ for _ in ()).throw(RuntimeError('x')),
                                   删除记录=炸),
                        场景=C.场景_其他)
        结果 = 流程.尝试添加('https://b.example.com/novel/1')
        self.assertTrue(结果['可以'], '登记已成功, 不应因重抓失败而回滚')
        self.assertIn('发起抓取失败', 结果['原因'])
        self.assertFalse(流程.确认删除(), '删除回调抛异常应返回 False 而不是冒泡')


if __name__ == '__main__':
    unittest.main(verbosity=2)
