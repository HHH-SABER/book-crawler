# -*- coding: utf-8 -*-
"""字词修正测试 (2026-11-01)。

背景: 审稿报告把 8 处字词判成"错别字", 复核后发现 **只有「做为」2 处是真的**:

  · 「做为」→「作为」: 真错字, 但唯一真实误伤是「做+为什么」
    ("拿来做为什么用"), 所以用带守卫的正则 `做为(?!什么)` 而不是裸替换;
  · 「觉的」→「觉得」: **6 处全是误报** —— 睡觉的(1)/感觉的(3)/
    神不知鬼不觉的(2), 全是合法中文。盲目替换会把
    「准备上床睡觉的时候」改成「睡觉得时候」。**本条故意不做**, 用用例锁死。

覆盖:
  ① 做为→作为 生效; ② 做为什么 不被误改; ③ 觉的 的三种合法同形词原样保留;
  ④ 既有无条件修正表 (巳经/按排/渡假) 未回归。

运行: python -m unittest discover -s 测试
"""
import sys
import unittest
from pathlib import Path

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))


class Test作为修正(unittest.TestCase):

    def setUp(self):
        from 内容清洗 import 清洗
        self.清 = 清洗

    def test_做为改作为(self):
        出, _ = self.清('连做为他最亲密的爱人，这一点谁都不会否认。')
        self.assertIn('作为他', 出)
        self.assertNotIn('做为', 出)

    def test_做为什么不被误改(self):
        """「做+为什么」是合法组合 (拿来做为什么用), 守卫正则必须放过"""
        出, _ = self.清('这些工具平时拿来做为什么用，你心里应该有数。')
        self.assertIn('做为什么', 出)
        self.assertNotIn('作为什么', 出)


class Test觉的保持不变(unittest.TestCase):
    """「觉的」不做替换: 实测那 6 处全是合法中文 (审稿误报)"""

    def setUp(self):
        from 内容清洗 import 清洗
        self.清 = 清洗

    def test_睡觉的不得改成睡觉得(self):
        出, _ = self.清('准备上床睡觉的时候，他忽然想起白天那句不舒服的话。')
        self.assertIn('睡觉的时候', 出)
        self.assertNotIn('睡觉得', 出)

    def test_神不知鬼不觉的不得改(self):
        出, _ = self.清('他自认神不知鬼不觉的举动，其实早就被人看在眼里。')
        self.assertIn('神不知鬼不觉的', 出)
        self.assertNotIn('觉得', 出)

    def test_感觉的不得改(self):
        出, _ = self.清('伤口恢复得不错，那一片地方还是有感觉的，只是不明显。')
        self.assertIn('有感觉的', 出)
        self.assertNotIn('觉得', 出)


class Test既有修正表未回归(unittest.TestCase):
    """encoding_fixes (无条件修正) 不能被本轮的守卫表影响"""

    def setUp(self):
        from 内容清洗 import 清洗
        self.清 = 清洗

    def test_既有错字仍修正(self):
        出, _ = self.清('他巳经按排好了一切，只等大家到齐就出发。')
        self.assertIn('已经', 出)
        self.assertIn('安排', 出)

    def test_前缀型修正仍生效(self):
        出, _ = self.清('他把渡假村的地图摊开，指着一处渡假屋问我怎么走。')
        self.assertIn('度假村', 出)
        self.assertNotIn('渡假', 出)

    def test_正常文本不动(self):
        原文 = '这是一段完全正常的中文内容，没有任何噪声，也没有错别字。'
        出, _ = self.清(原文)
        self.assertEqual(出, 原文)


if __name__ == '__main__':
    unittest.main(verbosity=2)
