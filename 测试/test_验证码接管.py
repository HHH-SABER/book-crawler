# -*- coding: utf-8 -*-
"""验证码「自动识别连续失败 → 转人工接管」的回归用例 (离线)。

用户要求 (2026-10-11): "把自动识别打开, 设置一个界限, 超过 5-10 次自动识别无法通过
就让人主动接管验证"。

语义: 自动识别策略**连续失败**达 `auto_max_fail` (建议 5–10) 后进入接管窗口
(`handover_cooldown` 秒): 窗口内**不再尝试**自动策略, 直接走人工。
自动识别成功 → 计数清零; 人工解掉 → 重新计时冷却期。

⚠️ 合规护栏也在本文件里守着: **出厂默认必须关闭自动识别** (AGENTS.md 硬边界)。

运行方式 (项目根目录):
    python -m unittest discover -s 测试 -v
"""
import sys
import time
import unittest
from pathlib import Path

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

import captcha_module as C       # noqa: E402

验证码页 = '<html>请输入验证码 __wafcaptcha</html>'
解决页 = '<html><body>正文</body></html>'


class _假自动:
    """假自动策略: 按脚本决定成功还是失败, 并记下被调用次数。"""
    name = 'ddddocr'

    def __init__(self, 调用表, 成功第几次=None):
        self.调用表 = 调用表
        self.成功第几次 = 成功第几次

    def handle(self, driver, url, src):
        self.调用表.append('auto')
        if self.成功第几次 is not None and len(
                [x for x in self.调用表 if x == 'auto']) == self.成功第几次:
            return 解决页
        return 验证码页       # 仍是验证码页 → 判为失败


class _假人工:
    name = 'manual'
    driver_factory = staticmethod(lambda: object())   # 必须有, 否则被跳过

    def __init__(self, 调用表):
        self.调用表 = 调用表

    def handle(self, driver, url, src):
        self.调用表.append('manual')
        return 解决页


def _管理器(阈值=5, 冷却=600, 成功第几次=None):
    调用表 = []
    cfg = C.Config()
    cfg.data['strategies']['ddddocr']['enabled'] = True
    cfg.data['strategies']['manual']['enabled'] = True
    cfg.data['auto_max_fail'] = 阈值
    cfg.data['handover_cooldown'] = 冷却
    m = C.CaptchaManager(config=cfg, monitor=C.CaptchaMonitor())
    m._handlers = {'ddddocr': _假自动(调用表, 成功第几次), 'manual': _假人工(调用表)}
    m.is_captcha_page = lambda src: src == 验证码页
    return m, 调用表


class Test配置项(unittest.TestCase):

    def test_默认阈值与冷却(self):
        cfg = C.Config()
        self.assertEqual(cfg.auto_max_fail, 5, '默认阈值 5 (用户要求 5-10 区间)')
        self.assertEqual(cfg.handover_cooldown, 600)

    def test_非法值被夹紧(self):
        cfg = C.Config()
        for 值, 期望 in ((0, 1), (-3, 1), (999, 50), ('x', 5), (None, 5)):
            cfg.data['auto_max_fail'] = 值
            self.assertEqual(cfg.auto_max_fail, 期望, f'auto_max_fail={值!r}')
        for 值, 期望 in ((-1, 0.0), (1e9, 86400.0), ('x', 600.0)):
            cfg.data['handover_cooldown'] = 值
            self.assertEqual(cfg.handover_cooldown, 期望, f'cooldown={值!r}')

    def test_合规护栏_出厂默认关闭自动识别(self):
        """⚠️ AGENTS 硬边界: 验证码自动识别**默认必须关闭** —— 别把它改开。"""
        s = C.DEFAULT_CONFIG['strategies']
        for 名 in ('ddddocr', 'slider', 'third_party', 'point_click'):
            self.assertFalse(s[名]['enabled'], f'{名} 出厂默认必须关闭')
        self.assertTrue(s['manual']['enabled'], '人工辅助应始终可用')


class Test阈值转人工(unittest.TestCase):

    def test_未达阈值时照常尝试自动(self):
        m, 调用 = _管理器(阈值=5)
        m.handle(None, 'u', 验证码页)
        m.handle(None, 'u', 验证码页)
        self.assertEqual(调用.count('auto'), 2, '未达阈值应继续尝试自动')
        self.assertFalse(m.接管状态()['接管中'])

    def test_达阈值后不再尝试自动_直接人工(self):
        m, 调用 = _管理器(阈值=3)
        for _ in range(3):
            m.handle(None, 'u', 验证码页)
        self.assertEqual(调用.count('auto'), 3, '前 3 次各试一次自动')
        self.assertTrue(m.接管状态()['接管中'], '达阈值应进入接管窗口')
        调用.clear()
        m.handle(None, 'u', 验证码页)
        self.assertEqual(调用, ['manual'], '接管窗口内**只**走人工, 不再烧自动识别')

    def test_自动成功则计数清零(self):
        m, 调用 = _管理器(阈值=5, 成功第几次=3)     # 第 3 次自动调用成功
        m.handle(None, 'u', 验证码页)
        m.handle(None, 'u', 验证码页)
        self.assertEqual(m.接管状态()['连续自动失败'], 2, '这两次自动都失败')
        m.handle(None, 'u', 验证码页)                # 这次自动成功
        self.assertEqual(m.接管状态()['连续自动失败'], 0, '自动成功后应清零')
        self.assertFalse(m.接管状态()['接管中'])

    def test_人工兜住不等于接管_阈值仍照常累积(self):
        """⚠️ 回归: 首版把"人工兜住"也当成进入接管, 于是第 1 次失败后就再不试自动识别,
        用户要的"5-10 次"永远攒不到。接管**只能**由阈值触发。"""
        m, 调用 = _管理器(阈值=4)
        for i in range(1, 4):
            m.handle(None, 'u', 验证码页)       # 每次: 自动失败 → 人工兜住
            self.assertEqual(m.接管状态()['连续自动失败'], i,
                             f'第 {i} 次后计数应为 {i}')
            self.assertFalse(m.接管状态()['接管中'], '未达阈值不该进入接管')
        self.assertEqual(调用.count('auto'), 3, '未达阈值前每次都要试自动')

    def test_人工成功后进入冷却(self):
        m, 调用 = _管理器(阈值=2, 冷却=600)
        for _ in range(2):
            m.handle(None, 'u', 验证码页)      # 达阈值 → 转人工
        调用.clear()
        m.handle(None, 'u', 验证码页)          # 人工解掉
        self.assertIn('manual', 调用)
        self.assertTrue(m.接管状态()['接管中'], '达阈值后应处于接管窗口内')

    def test_冷却为0表示本次会话内不再自动(self):
        m, 调用 = _管理器(阈值=2, 冷却=0)
        for _ in range(2):
            m.handle(None, 'u', 验证码页)
        状态 = m.接管状态()
        self.assertTrue(状态['接管中'])
        self.assertEqual(状态['接管截止'], float('inf'), '冷却 0 = 不再到期')
        调用.clear()
        m.handle(None, 'u', 验证码页)
        self.assertEqual(调用, ['manual'])

    def test_非验证码页不受影响且不计数(self):
        m, 调用 = _管理器(阈值=2)
        for _ in range(5):
            出 = m.handle(None, 'u', 解决页)
        self.assertEqual(出, 解决页)
        self.assertEqual(调用, [], '非验证码页不该调用任何策略')
        self.assertEqual(m.接管状态()['连续自动失败'], 0)

    def test_模块总开关关闭时直接放行(self):
        m, 调用 = _管理器(阈值=2)
        m.config.data['enabled'] = False
        出 = m.handle(None, 'u', 验证码页)
        self.assertEqual(出, 验证码页, '模块关闭 → 原样返回')
        self.assertEqual(调用, [])


class Test合规护栏仍在(unittest.TestCase):
    """旧护栏: 具名策略必须服从 strategies.<name>.enabled (别被本次改动破坏)。"""

    def test_具名策略未启用时拒绝执行(self):
        cfg = C.Config()
        cfg.data['strategies']['ddddocr']['enabled'] = False   # 出厂默认
        m = C.CaptchaManager(config=cfg, monitor=C.CaptchaMonitor())
        调用 = []
        m._handlers = {'ddddocr': _假自动(调用), 'manual': _假人工(调用)}
        m.is_captcha_page = lambda src: src == 验证码页
        m.set_strategy('ddddocr')
        m.handle(None, 'u', 验证码页)
        self.assertNotIn('auto', 调用, 'enabled=false 时不得执行该策略')


if __name__ == '__main__':
    unittest.main(verbosity=2)
