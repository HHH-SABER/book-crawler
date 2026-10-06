# -*- coding: utf-8 -*-
"""Phase 4 批 1 回归：顶栏去重复版本号 + 侧栏底部（状态块 / 访问 GitHub 卡）。

设计稿要求（`界面设计预览/index.html`）：titlebar 只写应用名；侧栏底部有
`.sidebar-status` 状态块与 GitHub 卡。本轮按此落实，本文件钉住三件事：
  ① 侧栏底部块能构建，含状态块与 GitHub 文案；
  ② 状态摘要与"打开仓库"在**无 page / 未入树**时必须是安全 no-op（组件单测常见形态）；
  ③ 顶栏页内标题**不带版本号**（版本只在窗口标题，避免两处重复）。
"""
import pathlib
import unittest

import _沙箱  # noqa: F401

from gui_components import icon_rail as R

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_GUI = _ROOT / '源码' / 'gui_app.py'


def _文本(控件) -> str:
    """递归收集控件树里的所有字符串（文案断言用）。"""
    出 = []
    def 走(c):
        if c is None:
            return
        if isinstance(c, str):
            出.append(c)
            return
        v = getattr(c, 'value', None)
        if isinstance(v, str):
            出.append(v)
        for 属性 in ('controls', 'content'):
            子 = getattr(c, 属性, None)
            if isinstance(子, (list, tuple)):
                for x in 子:
                    走(x)
            elif 子 is not None:
                走(子)
    走(控件)
    return '\n'.join(出)


class Test侧栏底部(unittest.TestCase):

    def setUp(self):
        self.rail = R.IconRail()

    def test_底部块含状态与GitHub文案(self):
        块 = self.rail._底部块()
        文案 = _文本(块)
        self.assertIn('就绪', 文案, '状态块初始文案缺失')
        self.assertIn('访问 GitHub', 文案)
        self.assertIn('Star', 文案, '设计稿的 GitHub 提示语缺失')

    def test_状态摘要幂等且未入树不报错(self):
        self.rail._底部块()
        self.rail.设置状态摘要('抓取中 2 项', '#123456')     # 只改属性
        self.rail.设置状态摘要('抓取中 2 项', '#123456')     # 幂等
        self.rail.刷新状态摘要()                          # 未入树 → 内部忽略, 不得抛

    def test_未构建底部块时设置状态也安全(self):
        """边界: 若 build() 尚未调用, 两个方法都必须是 no-op。"""
        self.rail.设置状态摘要('就绪', '#000000')
        self.rail.刷新状态摘要()

    def test_打开仓库无page时静默(self):
        self.rail.page = None
        self.rail._打开仓库(None)      # 不得抛

    def test_仓库地址是https(self):
        self.assertTrue(R._仓库地址.startswith('https://'), R._仓库地址)


class Test顶栏不重复版本(unittest.TestCase):

    def test_页内标题不带版本号(self):
        文本 = _GUI.read_text(encoding='utf-8')
        self.assertIn('build_top_bar(page, "小说爬虫"', 文本,
                      '页内标题应只写应用名（设计稿 titlebar）；带 _应用名 会与窗口标题重复')
        self.assertIn('page.title = _应用名', 文本,
                      '窗口标题仍应带版本号（便于支持与排查）')


if __name__ == '__main__':
    unittest.main(verbosity=2)
