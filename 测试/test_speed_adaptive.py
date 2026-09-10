# -*- coding: utf-8 -*-
"""速度自适应控制器升降档时序单测。

背景: 该模块此前零单测 (审查报告 M13 列为盲区)。本文件同时固化 N3 修复:

  回升判据原本是"自上次换档以来的风险事件数"(_risk_since_change), 而该计数在
  每次换档的 _change_tier_locked 里被清零 → **风险事件导致的降档恰好把判据自己
  抹掉**, 判据形同虚设; 更糟的是在最低档再遇风险事件时计数只增不清零 →
  该任务内永久无法回升。现改为时间判据: 距上次反爬事件静默
  UPGRADE_RISK_FREE_SECONDS 才允许回升。

说明: 直接构造 SpeedController, 绕开 build_controller 的设备基准
(避免读写 数据/速度画像.json, 让用例完全确定性)。

运行方式 (项目根目录):
    python -m unittest discover -s 测试 -v
"""
import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '源码'))

import 速度自适应 as sa  # noqa: E402


def _控制器(起始档=2, 最高档=2):
    return sa.SpeedController('unit.example.com', 起始档, 最高档)


def _免系统压力(c):
    """关掉内存压力判据: 该判据依赖真实可用内存, 留着会让用例偶发失败"""
    c._system_pressure = lambda: False
    return c


class TestSpeedController升降档(unittest.TestCase):

    # ------------------------------------------------------------ 降档
    def test_连续三章失败降一档(self):
        c = _控制器()
        c.record_chapter(False)
        c.record_chapter(False)
        self.assertEqual(c.tier.level, 2, '不足 3 次连败不应降档')
        c.record_chapter(False)
        self.assertEqual(c.tier.level, 1)

    def test_风险事件立即降档(self):
        c = _控制器()
        c.note_risk('rate_limit')
        self.assertEqual(c.tier.level, 1)

    def test_最低档再遇风险不归零静默期(self):
        """N3 根因回归: 降档不得清掉"上次风险事件"的时间戳。

        旧实现把计数写在 _change_tier_locked 里清零, 于是 1→0 这次降档动作
        直接把刚发生的风险事件抹掉, 回升判据再也看不到它。
        """
        c = _控制器(起始档=1, 最高档=2)
        c.note_risk('waf_captcha')            # 1 → 0, 同时记录风险时刻
        self.assertEqual(c.tier.level, 0)
        self.assertGreater(c._last_risk_time, 0.0,
                           '降档后风险时刻被清零 → 回升判据失效 (N3 回归)')
        c.note_risk('waf_captcha')            # 已在最低档: 只刷新时刻, 不换档
        self.assertGreater(c._last_risk_time, 0.0)

    # ------------------------------------------------------------ 回升闸门
    def test_风险未静默时拒绝回升(self):
        c = _免系统压力(_控制器(起始档=1, 最高档=2))
        c.note_risk('rate_limit')             # → 0
        c._last_change_time -= sa.UPGRADE_COOLDOWN_SECONDS + 10
        for _ in range(sa.UPGRADE_CONSEC_OK + 5):
            c.record_chapter(True)
        self.assertEqual(c.tier.level, 0,
                         '风险事件距今不足静默期, 不应回升')

    def test_风险静默期满后回升(self):
        c = _免系统压力(_控制器(起始档=1, 最高档=2))
        c.note_risk('rate_limit')             # → 0
        c._last_change_time -= sa.UPGRADE_COOLDOWN_SECONDS + 10
        c._last_risk_time -= sa.UPGRADE_RISK_FREE_SECONDS + 10
        for _ in range(sa.UPGRADE_CONSEC_OK + 5):
            c.record_chapter(True)
        self.assertEqual(c.tier.level, 1)

    def test_连续成功不足不回升(self):
        c = _免系统压力(_控制器(起始档=1, 最高档=2))
        c._last_change_time -= sa.UPGRADE_COOLDOWN_SECONDS + 10
        for _ in range(sa.UPGRADE_CONSEC_OK - 1):
            c.record_chapter(True)
        self.assertEqual(c.tier.level, 1)

    def test_冷静期未到不回升(self):
        c = _免系统压力(_控制器(起始档=1, 最高档=2))
        for _ in range(sa.UPGRADE_CONSEC_OK + 5):
            c.record_chapter(True)
        self.assertEqual(c.tier.level, 1)

    def test_已达最高档不再回升(self):
        c = _免系统压力(_控制器(起始档=2, 最高档=2))
        c._last_change_time -= sa.UPGRADE_COOLDOWN_SECONDS + 10
        for _ in range(sa.UPGRADE_CONSEC_OK + 5):
            c.record_chapter(True)
        self.assertEqual(c.tier.level, 2)

    def test_回升后须重新等冷静期(self):
        """一次回升不得直接冲上最高档"""
        c = _免系统压力(_控制器(起始档=0, 最高档=2))
        c._last_change_time -= sa.UPGRADE_COOLDOWN_SECONDS + 10
        for _ in range(sa.UPGRADE_CONSEC_OK + 5):
            c.record_chapter(True)
        self.assertEqual(c.tier.level, 1, '同一冷静期内只应升一档')

    # ------------------------------------------------------------ 手动直通
    def test_手动模式不受信号影响(self):
        c = sa.SpeedController('unit.example.com', 2, 2, manual=(2, 0.7))
        c.note_risk('rate_limit')
        c.record_chapter(False)
        self.assertEqual(c.initial_params(), (2, 0.7))


if __name__ == '__main__':
    unittest.main(verbosity=2)
