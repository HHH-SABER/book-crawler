# -*- coding: utf-8 -*-
"""交接快照脚本回归 (P8-C8, 2026-10-24)。

锁住三件容易静默出错的事:
  ① 未发布版本数计算 (跨补丁号/跨次版本/无 tag/已发布 四种形态);
  ② 状态块渲染 (关键行必须出现, 且"未发布"措辞随形态变化);
  ③ 干净判定 (收尾仪式退出码的依据)。
集成用例真跑 采集() (本仓库实况, 只读)。
"""
import sys
import unittest
from pathlib import Path

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '脚本'))

import 生成交接快照 as H   # noqa: E402


class Test未发布版本数(unittest.TestCase):

    def test_领先两个补丁号(self):
        self.assertEqual(H.未发布版本数('2.5.57', 'v2.5.55'), 2)

    def test_已发布为零(self):
        self.assertEqual(H.未发布版本数('2.5.57', 'v2.5.57'), 0)

    def test_无tag无法判定(self):
        self.assertIsNone(H.未发布版本数('2.5.57', ''))

    def test_跨次版本不用差值表达(self):
        self.assertIsNone(H.未发布版本数('3.0.1', 'v2.5.57'))

    def test_无v前缀也能解(self):
        self.assertEqual(H.未发布版本数('2.5.60', '2.5.55'), 5)


class Test状态块与干净判定(unittest.TestCase):

    def _数据(self, **覆盖):
        基 = {
            '版本': '2.5.57', 'HEAD': 'abc1234', 'origin': 'abc1234',
            '领先': 0, '落后': 0, '未推送提交': [], '工作区在途': [],
            '最新tag': 'v2.5.57', '未发布版本数': 0,
            '门禁': {'通过': True, '摘要': 'Ran 1447 tests'},
            '门禁来源': '实跑',
        }
        基.update(覆盖)
        return 基

    def test_干净快照(self):
        self.assertTrue(H.是否干净(self._数据()))

    def test_有未推送则不干净(self):
        self.assertFalse(H.是否干净(self._数据(
            未推送提交=['abc1234 fix: x'], 领先=1)))

    def test_有未发布版本则不干净(self):
        self.assertFalse(H.是否干净(self._数据(未发布版本数=2)))

    def test_门禁没跑则不干净(self):
        self.assertFalse(H.是否干净(self._数据(门禁=None)))

    def test_状态块含七要素关键行(self):
        块 = H.状态块(self._数据())
        for 关键 in ('2.5.57', 'abc1234', '未推送提交: 0 个',
                   '工作区在途: 0 项', 'Ran 1447 tests', '已发布至 v2.5.57'):
            self.assertIn(关键, 块)

    def test_未发布措辞随形态变化(self):
        self.assertIn('0 (已发布至', H.状态块(self._数据()))
        self.assertIn('2 个版本未发布', H.状态块(self._数据(未发布版本数=2)))
        self.assertIn('从未打 tag 发布', H.状态块(self._数据(最新tag='')))


class Test真实仓库集成(unittest.TestCase):
    """采集() 只读跑一遍, 结构必须完整 (防止 git 解析回归)。"""

    def test_采集结构完整(self):
        数据 = H.采集(gate=False)
        for 键 in ('版本', 'HEAD', 'origin', '领先', '落后', '未推送提交',
                 '工作区在途', '最新tag', '未发布版本数'):
            self.assertIn(键, 数据)
        self.assertTrue(数据['HEAD'], 'HEAD 必须解析到')
        self.assertIsInstance(数据['领先'], int)


if __name__ == '__main__':
    unittest.main(verbosity=2)
