# -*- coding: utf-8 -*-
"""重构护栏的用例（S1 第三步：一条命令做"锚点 / 校验"）。

只测编排逻辑（不真跑基线，避免用例变慢）：
1. 校验清单必须含五道护栏（少一道 = 有人以为自己验了其实没验）；
2. 缺本地样本时 `--锚点` **必须拒绝**（否则会用空基线覆盖好基线）；
3. 任一道失败 ⇒ 整体退 1（不许把局部通过报成 PASS）。
"""
import importlib.util
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

根 = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(根 / '脚本'))

spec = importlib.util.spec_from_file_location('重构护栏', 根 / '脚本' / '重构护栏.py')
护栏 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(护栏)


class 清单用例(unittest.TestCase):
    def test_校验含五道护栏(self):
        名 = [x[0] for x in 护栏.校验项()]
        self.assertEqual(名, ['目录链', '正文链', '决策轨迹', '阶段覆盖', '静态引用'])

    def test_每道都有脚本参数(self):
        for 名, 参数 in 护栏.校验项():
            self.assertIsInstance(参数, list, 名)
            self.assertTrue(参数 and 参数[0].startswith('脚本/'), f'{名} 参数不对: {参数}')

    def test_解释器可用(self):
        self.assertTrue(护栏.解释器)


class 锚点保护用例(unittest.TestCase):
    def test_当前环境样本就绪(self):
        就绪, 缺 = 护栏.样本就绪()
        self.assertTrue(就绪, f'本机应就绪，缺: {缺}')

    def test_缺样本时拒绝打锚点(self):
        """公开形态（无本地样本）下打锚点会把入库基线覆盖成空 —— 必须拒绝。"""
        临时 = tempfile.TemporaryDirectory()
        self.addCleanup(临时.cleanup)
        空 = pathlib.Path(临时.name) / 'nope'
        with mock.patch.dict(护栏.样本依赖, {k: 空 for k in 护栏.样本依赖}, clear=True):
            就绪, 缺 = 护栏.样本就绪()
            self.assertFalse(就绪)
            self.assertEqual(len(缺), len(护栏.样本依赖))
            self.assertEqual(护栏.打锚点(), 1)


class 聚合用例(unittest.TestCase):
    def test_全过返回0(self):
        with mock.patch.object(护栏, '_跑', lambda 参数, 名: (True, 0.0, 'PASS')):
            self.assertEqual(护栏.校验(), 0)

    def test_任一失败返回1(self):
        def 假跑(参数, 名):
            return (名 != '决策轨迹', 0.0, 'x')

        with mock.patch.object(护栏, '_跑', 假跑):
            self.assertEqual(护栏.校验(), 1)

    def test_跑返回三元组(self):
        ok, 秒, 尾 = 护栏._跑(['-c', 'print(1)'], '自检')
        self.assertTrue(ok)
        self.assertGreaterEqual(秒, 0.0)
        self.assertIn('1', 尾)


if __name__ == '__main__':
    unittest.main()
