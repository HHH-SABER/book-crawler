# -*- coding: utf-8 -*-
"""states 状态组件契约回归 (2026-10-07, Phase 4 批 4 新增)。

**为什么要这个文件**: 批 4 之前 `states.py` 六个函数**一个单测都没有**
(只有 `测试/test_颜色格式合法.py` 扫它的色值字面量) —— 而批 4 要把六个页面
的空态/加载态/错误态全部接到它上面。也就是说: 组件的形一旦被改错,
**六个页面会同时错**, 且没有任何护栏。

尺寸基准 = 设计稿 `界面设计预览/index.html` 的 `.empty-state` (1306-1330 行):
图标 48px + opacity 0.4 / 标题 --fs-h3(15) 字重 500 --text-secondary /
说明 --fs-small(13) --text-tertiary / 留白 --sp-3(12) / 内边距 --sp-8(32)。

运行: python -m unittest discover -s 测试
"""
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / '源码')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _沙箱  # noqa: F401,E402  import 即把状态根钉到临时目录


def _所有文本(控件, ft) -> list:
    """收集控件树里所有可见文字 (Text.value / Button 的 content|text)。"""
    out = []
    if 控件 is None:
        return out
    if isinstance(控件, ft.Text) and isinstance(控件.value, str):
        out.append(控件.value)
    for attr in ('content', 'text', 'label', 'controls'):
        v = getattr(控件, attr, None)
        if isinstance(v, str) and v:
            out.append(v)
        elif isinstance(v, list):
            for c in v:
                out.extend(_所有文本(c, ft))
        elif v is not None and not isinstance(v, (str, int, float, bool)):
            out.extend(_所有文本(v, ft))
    return out


def _收集(控件, 类型, ft) -> list:
    """按类型收集控件树里的控件。"""
    out = []
    if 控件 is None:
        return out
    if isinstance(控件, 类型):
        out.append(控件)
    for attr in ('content', 'controls'):
        v = getattr(控件, attr, None)
        if isinstance(v, list):
            for c in v:
                out.extend(_收集(c, 类型, ft))
        elif v is not None and not isinstance(v, (str, int, float, bool)):
            out.extend(_收集(v, 类型, ft))
    return out


class Test空态(unittest.TestCase):

    def setUp(self):
        import flet as ft
        from gui_components import states, ui_tokens
        self.ft, self.states, self.ui_tokens = ft, states, ui_tokens

    def test_图标尺寸与透明度对齐设计稿(self):
        c = self.states.空态(标题='暂无数据', 说明='说明')
        图标 = _收集(c, self.ft.Icon, self.ft)
        self.assertEqual(len(图标), 1)
        self.assertEqual(图标[0].size, self.ui_tokens.EMPTY_ICON_SIZE)
        self.assertEqual(图标[0].size, 48, '设计稿 .empty-state-icon 是 48px')
        self.assertEqual(图标[0].opacity, 0.4, '设计稿图标 opacity 0.4')

    def test_标题字重与说明字号对齐设计稿(self):
        from gui_components.ui_fluent import SIZE_LABEL, SIZE_SMALL, WEIGHT_EMPHASIS
        c = self.states.空态(标题='暂无数据', 说明='说明文字')
        文本 = _收集(c, self.ft.Text, self.ft)
        标题 = next(t for t in 文本 if t.value == '暂无数据')
        说明 = next(t for t in 文本 if t.value == '说明文字')
        self.assertEqual(标题.size, SIZE_LABEL, '标题 --fs-h3 = 15')
        self.assertEqual(标题.weight, WEIGHT_EMPHASIS, '设计稿标题字重 500')
        self.assertEqual(说明.size, SIZE_SMALL, '说明 --fs-small = 13')

    def test_语义图标色可覆盖且不再降透明度(self):
        """死书清单的"一本死书都没有"是好消息 → 要绿色对勾, 不能用灰图标"""
        c = self.states.空态(标题='x', 图标色='status-success')
        图标 = _收集(c, self.ft.Icon, self.ft)[0]
        from gui_components.ui_tokens import 取色
        self.assertEqual(图标.color, 取色('status-success'))
        self.assertNotEqual(图标.opacity, 0.4,
                            '给了语义色就不该再压 0.4 透明度 (会看不出是绿的)')

    def test_不传说明不产生空文本控件(self):
        c = self.states.空态(标题='只有标题')
        值 = [t.value for t in _收集(c, self.ft.Text, self.ft)]
        self.assertIn('只有标题', 值)
        self.assertNotIn('', 值)


class Test首次为空(unittest.TestCase):

    def setUp(self):
        import flet as ft
        from gui_components import states
        self.ft, self.states = ft, states

    def test_默认给通用兜底文案(self):
        值 = _所有文本(self.states.首次为空(), self.ft)
        self.assertTrue(any('还没有任何记录' in v for v in 值), f'实得 {值}')

    def test_页面专属文案优先(self):
        """设计稿样卡用的也是页面专属文案 (「暂无手机端记录 / 手机发起的…」)"""
        值 = _所有文本(self.states.首次为空(
            标题='暂无手机端记录', 说明='手机发起的抓取任务会实时出现在这里'), self.ft)
        self.assertIn('暂无手机端记录', 值)
        self.assertIn('手机发起的抓取任务会实时出现在这里', 值)
        self.assertFalse([v for v in 值 if '还没有任何记录' in v],
                         '给了专属标题就不该再混进通用文案')

    def test_可带恢复动作(self):
        按钮 = self.ft.FilledButton('开始')
        c = self.states.首次为空(操作按钮=按钮, 标题='空')
        文本 = _所有文本(c, self.ft)
        self.assertIn('开始', 文本)


class Test筛选后为空(unittest.TestCase):

    def setUp(self):
        import flet as ft
        from gui_components import states
        self.ft, self.states = ft, states

    def test_必须能给出清除筛选动作(self):
        """没有这个动作, 用户会以为数据被删了 (实测最常见的空态投诉)"""
        被点 = []
        c = self.states.筛选后为空(清除筛选回调=lambda e: 被点.append(1))
        文本 = _所有文本(c, self.ft)
        self.assertIn('清除筛选', 文本, f'缺清除筛选按钮: {文本}')

    def test_无回调时不给无用按钮(self):
        c = self.states.筛选后为空()
        文本 = _所有文本(c, self.ft)
        self.assertNotIn('清除筛选', 文本, '没有回调就不该给按钮')

    def test_说明可定制且默认为筛选语义(self):
        值 = _所有文本(self.states.筛选后为空(说明='状态=失败 · 站点=siteA'), self.ft)
        self.assertIn('状态=失败 · 站点=siteA', 值)
        默认 = _所有文本(self.states.筛选后为空(), self.ft)
        self.assertTrue(any('筛选' in v for v in 默认), f'实得 {默认}')


class Test错误态(unittest.TestCase):

    def setUp(self):
        import flet as ft
        from gui_components import states
        self.ft, self.states = ft, states

    def test_有回调才给重试按钮(self):
        有 = _所有文本(self.states.错误态(重试回调=lambda e: None), self.ft)
        self.assertIn('重试', 有)
        无 = _所有文本(self.states.错误态(), self.ft)
        self.assertNotIn('重试', 无, '没回调就不该给没用的按钮')

    def test_标题与说明都上屏(self):
        值 = _所有文本(self.states.错误态('历史数据读取失败', '文件损坏'), self.ft)
        self.assertIn('历史数据读取失败', 值)
        self.assertIn('文件损坏', 值)

    def test_图标用错误色(self):
        from gui_components.ui_tokens import 状态色
        c = self.states.错误态()
        图标 = _收集(c, self.ft.Icon, self.ft)[0]
        self.assertEqual(图标.color, 状态色('error')[0])


class Test加载态(unittest.TestCase):

    def setUp(self):
        import flet as ft
        from gui_components import states
        self.ft, self.states = ft, states

    def test_不定进度用环_定进度用条(self):
        环 = self.states.加载态('加载中…')
        self.assertEqual(len(_收集(环, self.ft.ProgressRing, self.ft)), 1)
        self.assertEqual(len(_收集(环, self.ft.ProgressBar, self.ft)), 0)
        条 = self.states.加载态('读取中…', 进度=0.4)
        self.assertEqual(len(_收集(条, self.ft.ProgressBar, self.ft)), 1)
        self.assertEqual(len(_收集(条, self.ft.ProgressRing, self.ft)), 0,
                         '环与条不同时出现 (避免视觉噪音)')

    def test_进度越界被夹紧(self):
        for 给, 期望 in ((-1, 0.0), (5, 1.0)):
            条 = _收集(self.states.加载态('x', 进度=给),
                      self.ft.ProgressBar, self.ft)[0]
            self.assertEqual(条.value, 期望, f'进度 {给}')

    def test_文案上屏(self):
        self.assertIn('正在读取任务…',
                      _所有文本(self.states.加载态('正在读取任务…'), self.ft))


class Test状态容器(unittest.TestCase):

    def setUp(self):
        import flet as ft
        from gui_components import states
        self.ft, self.states = ft, states

    def test_四态可切换且返回壳(self):
        正常 = self.ft.Text('正常内容')
        壳, 槽 = self.states.状态容器(正常控件=正常)
        self.assertIs(槽.置加载('加载中…'), 壳)
        self.assertIn('加载中…', _所有文本(壳, self.ft))
        self.assertIs(槽.置错误('出错了', '原因', lambda e: None), 壳)
        self.assertIn('出错了', _所有文本(壳, self.ft))
        self.assertIs(槽.置空(首次=True, 标题='空'), 壳)
        self.assertIn('空', _所有文本(壳, self.ft))
        self.assertIs(槽.置正常(), 壳)
        self.assertIn('正常内容', _所有文本(壳, self.ft))

    def test_置空支持筛选态与专属文案(self):
        壳, 槽 = self.states.状态容器()
        槽.置空(首次=False, 清除筛选回调=lambda e: None, 标题='没有匹配的结果',
                说明='状态=失败')
        值 = _所有文本(壳, self.ft)
        self.assertIn('没有匹配的结果', 值)
        self.assertIn('状态=失败', 值)
        self.assertIn('清除筛选', 值)


class Test设计稿基准一致(unittest.TestCase):
    """把"设计稿数值"直接钉成断言, 防止有人凭感觉改回去。

    读的是 `界面设计预览/index.html` 的 `.empty-state` 段 —— 设计稿一改,
    这条会红, 提醒同步 (比注释可靠)。
    """

    def test_设计稿empty_state数值与代码一致(self):
        import re
        from gui_components import ui_tokens
        设计 = (_ROOT / '界面设计预览' / 'index.html').read_text(encoding='utf-8')
        段 = 设计.split('.empty-state {')[1].split('/* 日志条 */')[0]
        图标段 = 段.split('.empty-state-icon {')[1].split('}')[0]
        尺寸 = int(re.search(r'font-size:\s*(\d+)px', 图标段).group(1))
        self.assertEqual(尺寸, 48, '设计稿 .empty-state-icon 尺寸变了')
        self.assertEqual(ui_tokens.EMPTY_ICON_SIZE, 尺寸,
                         f'EMPTY_ICON_SIZE={ui_tokens.EMPTY_ICON_SIZE} 与设计稿 {尺寸} 不一致')


if __name__ == '__main__':
    unittest.main(verbosity=2)
