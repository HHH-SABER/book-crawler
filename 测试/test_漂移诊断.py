# -*- coding: utf-8 -*-
"""站点漂移检测测试 (P1-B, 2026-10-17) —— 本模块的首批单测。

背景: 此前 站点漂移检测.py 零单测覆盖 (真机验证型)。P1-B 给它加了"清洗诊断
分流" (漂移告警时据本次任务的删除行占比, 提示"清洗规则误杀"还是"站点改版"),
顺手把核心逻辑补上测试。

锁定:
  ① _清洗诊断 纯函数: 高占比→误杀提示 / 低占比→改版提示 / 有过度清洗章数
     (即便占比低) →误杀提示 / 水印不计入分子 / 缺 原始行数→'' / 非 dict→'';
  ② report_task 加 清洗汇总 后: 告警文案带诊断; 基线落 最近清洗 (只存计数);
  ③ **向后兼容**: 不传 清洗汇总 时告警文案与加参数前逐字一致;
  ④ EMA 主逻辑不受影响 (无漂移时正常更新基线)。
运行: python -m unittest discover -s 测试
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

import 站点漂移检测 as D   # noqa: E402


class 夹具(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._基线 = self.tmp / '站点基线.json'
        self._补丁 = mock.patch.object(D, '_path', lambda: str(self._基线))
        self._补丁.start()

    def tearDown(self):
        self._补丁.stop()
        self._tmp.cleanup()

    def _预置基线(self, 域='site-x.example', 样本=5, 空章率=0.0, 短章率=0.0, 失败率=0.0):
        self._基线.write_text(json.dumps({
            域: {'样本数': 样本, '空章率': 空章率, '短章率': 短章率,
                 '失败率': 失败率}}, ensure_ascii=False), encoding='utf-8')


class Test清洗诊断纯函数(夹具):

    def test_高占比判清洗误杀(self):
        文 = D._清洗诊断({'原始行数': 100, '关键词行': 20, '广告行': 15})
        self.assertIn('35%', 文)
        self.assertIn('清洗规则误杀', 文)

    def test_低占比判站点改版(self):
        文 = D._清洗诊断({'原始行数': 100, '关键词行': 2})
        self.assertIn('2%', 文)
        self.assertIn('站点改版', 文)

    def test_有过度清洗章数_占比低也判误杀(self):
        """P1 告警是强信号: 哪怕占比没到 30%, 有过度清洗章就指向误杀"""
        文 = D._清洗诊断({'原始行数': 100, '关键词行': 2, '过度清洗章数': 3})
        self.assertIn('过度清洗告警 3 章', 文)
        self.assertIn('清洗规则误杀', 文)

    def test_水印不计入分子(self):
        文 = D._清洗诊断({'原始行数': 100, '水印': 40})
        self.assertIn('0%', 文)
        self.assertIn('站点改版', 文, '纯水印替换不得判成误杀')

    def test_缺原始行数返回空(self):
        self.assertEqual(D._清洗诊断({'关键词行': 5}), '')
        self.assertEqual(D._清洗诊断({'原始行数': 0, '关键词行': 5}), '')
        self.assertEqual(D._清洗诊断(None), '')
        self.assertEqual(D._清洗诊断('坏数据'), '')


class TestReportTask接入(夹具):

    def test_告警文案带诊断分流(self):
        self._预置基线()
        告 = D.report_task('site-x.example', total=10, empty=5, short=0, failed=5,
                          清洗汇总={'原始行数': 100, '关键词行': 20, '广告行': 15})
        self.assertTrue(告, '空章率 50% vs 基线 0% 应告警')
        self.assertIn('35%', 告[0])
        self.assertIn('清洗规则误杀', 告[0])

    def test_基线落最近清洗且只存计数(self):
        self._预置基线()
        D.report_task('site-x.example', total=10, empty=1, short=0, failed=1,
                     清洗汇总={'原始行数': 100, '关键词行': 2, '水印': 3,
                               '过度清洗章数': 0, '杂项': '不应入库'})
        基线 = json.loads(self._基线.read_text(encoding='utf-8'))
        最近 = 基线['site-x.example'].get('最近清洗') or {}
        self.assertEqual(最近.get('原始行数'), 100)
        self.assertEqual(最近.get('关键词行'), 2)
        self.assertEqual(最近.get('水印'), 3)
        self.assertNotIn('杂项', 最近, '只存白名单计数键')

    def test_不传清洗汇总_文案与旧版一致(self):
        """向后兼容铁律: 老调用方 (无 清洗汇总) 的告警文案逐字不变"""
        self._预置基线()
        告 = D.report_task('site-x.example', total=10, empty=5, short=0, failed=5)
        self.assertTrue(告)
        self.assertIn('疑似站点改版', 告[0])
        self.assertNotIn('删除行占比', 告[0], '无清洗数据时不得出现诊断段')
        self.assertTrue(告[0].endswith('重探'), f'文案不应有尾巴: {告[0]!r}')

    def test_EMA主逻辑不受影响(self):
        """无漂移时基线正常 EMA 更新 (P1-B 没碰主逻辑)"""
        self._预置基线(空章率=0.0)
        D.report_task('site-x.example', total=10, empty=1, short=1, failed=0)
        基线 = json.loads(self._基线.read_text(encoding='utf-8'))
        self.assertAlmostEqual(基线['site-x.example']['空章率'], 0.1 * 0.3, places=3)
        self.assertEqual(基线['site-x.example']['样本数'], 6)

    def test_新站样本不足不告警(self):
        """样本 < 最小样本(3) 时不比对 —— 老规则, P1-B 后仍成立"""
        self._预置基线(样本=2, 空章率=0.0)
        告 = D.report_task('site-x.example', total=10, empty=9, short=0, failed=9)
        self.assertEqual(告, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
