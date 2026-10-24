# -*- coding: utf-8 -*-
"""C14 限流持久化：站点反爬先验 → 起始档位（纯函数 + 工厂集成）。

背景：站点历史的「反爬统计」早就落盘了，但从来没有人读它 ⇒ 上次被限流/WAF 的站点，
重启后仍以最快档起跑，等于把踩过的坑重踩一遍。本用例钉住：
无先验/过期不降档；有过 WAF 或反爬≥3 次降一档；最低档保护。
"""
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '源码'))
sys.path.insert(0, str(_PROJECT_ROOT / '测试'))

import _沙箱  # noqa: E402,F401  状态根沙箱
import 速度自适应 as 速  # noqa: E402


def _时间(偏移秒=0):
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time() - 偏移秒))


class 先验定档用例(unittest.TestCase):
    def test_无先验保持原档(self):
        self.assertEqual(速.按站点先验定起始档(2, {}, _时间(60)), 2)
        self.assertEqual(速.按站点先验定起始档(2, None, _时间(60)), 2)

    def test_无最近抓取时间不降档(self):
        self.assertEqual(速.按站点先验定起始档(2, {'rate_limit': 9}, ''), 2)

    def test_时间不可解析不降档(self):
        self.assertEqual(速.按站点先验定起始档(2, {'rate_limit': 9}, '不是时间'), 2)

    def test_事件少不降档(self):
        self.assertEqual(速.按站点先验定起始档(2, {'rate_limit': 2}, _时间(60)), 2)

    def test_事件达阈值降一档(self):
        self.assertEqual(速.按站点先验定起始档(2, {'rate_limit': 3}, _时间(60)), 1)

    def test_出现WAF即降档(self):
        self.assertEqual(速.按站点先验定起始档(3, {'waf_captcha': 1}, _时间(60)), 2)

    def test_先验过期不降档(self):
        旧 = _时间(8 * 86400)   # 8 天前 > 默认 7 天
        self.assertEqual(速.按站点先验定起始档(2, {'waf_captcha': 5}, 旧), 2)

    def test_最低档保护(self):
        self.assertEqual(速.按站点先验定起始档(1, {'waf_captcha': 5}, _时间(60)), 1)
        self.assertEqual(速.按站点先验定起始档(0, {'waf_captcha': 5}, _时间(60)), 0)

    def test_脏数据不抛异常(self):
        self.assertEqual(速.按站点先验定起始档(2, {'rate_limit': 'x'}, _时间(60)), 2)


class 工厂集成用例(unittest.TestCase):
    """build_controller 是否真的把先验用上（依赖打桩，不读磁盘）。"""

    def setUp(self):
        p1 = mock.patch.object(速, '_加载档位上限', lambda: None)
        p2 = mock.patch.object(速, 'SITE_TIER_CAPS', {})
        p3 = mock.patch.object(速, '设备画像', lambda *a, **k: {})
        p4 = mock.patch.object(速, '_profile_max_level', lambda prof: 2)
        for p in (p1, p2, p3, p4):
            p.start()
            self.addCleanup(p.stop)

    def _假站点历史(self, 先验, 最近):
        class _史:
            def 查站点(self, url):
                return {'反爬统计': 先验, '最近抓取': 最近}

            def 取反爬先验(self, url):
                return 先验
        return _史

    def test_无先验时按最高档起跑(self):
        import 站点历史 as 站史
        with mock.patch.object(站史, '取站点历史', lambda: self._假站点历史({}, _时间(60))()):
            c = 速.build_controller('https://example.com/book/1', total_chapters=500)
        self.assertEqual(c.tier.level, 2)

    def test_有WAF先验时降一档起跑(self):
        import 站点历史 as 站史
        with mock.patch.object(站史, '取站点历史',
                               lambda: self._假站点历史({'waf_captcha': 2}, _时间(60))()):
            c = 速.build_controller('https://example.com/book/1', total_chapters=500)
        self.assertEqual(c.tier.level, 1)

    def test_读过先验失败也不影响建控制器(self):
        import 站点历史 as 站史

        def _炸():
            raise RuntimeError('历史文件损坏')
        with mock.patch.object(站史, '取站点历史', _炸):
            c = 速.build_controller('https://example.com/book/1', total_chapters=500)
        self.assertEqual(c.tier.level, 2)


if __name__ == '__main__':
    unittest.main()
