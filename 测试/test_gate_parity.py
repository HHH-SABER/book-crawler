# -*- coding: utf-8 -*-
"""门禁一致性: 本机 `脚本/发布流程.py` 的三步 == CI `.github/workflows/test.yml` 的三步。

背景 (2026-10-04 八项需求质量审查发现): 本机门禁是**三步** ——
①离线单测 ②手写回归 ③静态检查; 而 CI 只有 ①②, 于是产生
**"CI 绿灯 ≠ 可打包"**。本文件把两条路径锁在一起, 任一侧漏步骤即红。

(只校验 test.yml —— `release.yml` 通过 `workflow_call` 复用它, 且该文件常为
 并行会话在途状态, 不纳入本护栏以免误报。)
"""
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_TEST_YML = _ROOT / '.github' / 'workflows' / 'test.yml'
_发布流程 = _ROOT / '脚本' / '发布流程.py'


class Test门禁一致性(unittest.TestCase):

    def _yml(self) -> str:
        return _TEST_YML.read_text(encoding='utf-8')

    def _本机(self) -> str:
        return _发布流程.read_text(encoding='utf-8')

    def test_CI包含离线单测(self):
        self.assertIn('unittest discover -s 测试', self._yml(),
                      'CI 缺门禁第①步 (离线单测)')

    def test_CI包含手写回归(self):
        self.assertIn('测试/回归测试_修复验证.py', self._yml(),
                      'CI 缺门禁第②步 (手写回归脚本)')

    def test_CI包含静态检查(self):
        """③ 必须在 CI 里 —— 只在本机门禁里有, 等于对 PR 没有约束力"""
        self.assertIn('脚本/check_undefined_refs.py', self._yml(),
                      'CI 缺门禁第③步 (静态检查): 会导致 CI 绿灯 ≠ 可打包')

    def test_本机门禁仍是三步(self):
        文本 = self._本机()
        self.assertIn('unittest', 文本)
        self.assertIn('回归测试_修复验证.py', 文本)
        self.assertIn('check_undefined_refs.py', 文本)


if __name__ == '__main__':
    unittest.main(verbosity=2)
