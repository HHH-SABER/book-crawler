# -*- coding: utf-8 -*-
"""CI「公开仓库形态」护栏 (2026-11-11)。

背景: `_agent/设计预览/index.html` 是 gitignored 的本地协作文件,
CI checkout 后不存在。三个「设计稿 ↔ 代码」交叉校验用例原先直接读它,
导致 `Offline Tests` / `Build & Release EXE` 从 2026-11-10 起连续 failure
(1 个 FileNotFoundError + 2 个「读不到断点」断言), 而本地门禁一直全绿。

本文件钉住两件事, 防止修复被无意改回去:
  ① 两个交叉校验类必须带 `skipUnless(设计稿存在)` 守卫 (缺文件自动 skip);
  ② `读取设计稿断点()` 缺文件时返回空表且不抛异常 (CI 形态的行为契约)。

运行: python -m unittest discover -s 测试
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_根 = Path(__file__).resolve().parents[1]
for _p in (str(_根), str(_根 / '源码')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _沙箱  # noqa: F401,E402  import 即把状态根钉到临时目录

from gui_components import 布局档位 as L   # noqa: E402


class Test公开形态护栏(unittest.TestCase):

    def test_agent目录必须被忽略(self):
        """设计稿不能靠「入库」修 CI —— 项目规约明确 /_agent/ 不入库。"""
        文本 = (_根 / '.gitignore').read_text(encoding='utf-8')
        self.assertIn('/_agent/', 文本, '_.gitignore 丢了 /_agent/ 规则, 交叉校验口径要重评')

    def test_两个交叉校验类都有缺文件守卫(self):
        for 名 in ('test_状态组件.py', 'test_布局档位.py'):
            with self.subTest(文件=名):
                文本 = (_根 / '测试' / 名).read_text(encoding='utf-8')
                self.assertIn('@unittest.skipUnless', 文本,
                              f'{名} 丢了 skipUnless, CI 会因缺设计稿变红')
                self.assertIn('_设计稿.is_file()', 文本,
                              f'{名} 的守卫条件不是「设计稿存在」')

    def test_设计稿缺失时断点读取返回空表且不抛(self):
        """CI 上 read_text 抛 OSError, 读取函数必须安静返回 []。"""
        with patch.object(Path, 'read_text', side_effect=OSError('缺文件')):
            self.assertEqual(L.读取设计稿断点(), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
