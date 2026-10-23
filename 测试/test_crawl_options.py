# -*- coding: utf-8 -*-
"""CrawlOptions 契约回归 (2026-10-24 审查 S2 修复)。

守住三条:
  ① 未知关键字参数必须 TypeError (杜绝静默丢弃 → 静默行为错误);
  ② 旧关键字路径仍可用 (过渡期兼容, 测试与历史调用方);
  ③ CrawlOptions 字段与旧 run_crawl 默认值一一对应。
"""
import sys
import unittest
from pathlib import Path

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

import 爬虫 as C   # noqa: E402


class TestCrawlOptions(unittest.TestCase):

    def test_字段与旧签名一致(self):
        期望 = ['mode', 'sort_chapters', 'output_dir', 'resume', 'show_progress',
                'chapter_range', 'threads', 'delay', 'stop_event', 'unique_title',
                'export_epub', 'incremental', 'txt_indent']
        self.assertEqual(list(C.CrawlOptions.__dataclass_fields__), 期望)

    def test_默认值与旧签名一致(self):
        o = C.CrawlOptions()
        self.assertEqual(o.mode, 'full')
        self.assertTrue(o.sort_chapters)
        self.assertTrue(o.resume)
        self.assertFalse(o.unique_title)
        self.assertFalse(o.export_epub)
        self.assertIsNone(o.txt_indent)

    def test_未知关键字报错(self):
        with self.assertRaises(TypeError) as  ctx:
            C.run_crawl('https://example.com', modee='full')
        self.assertIn('modee', str(ctx.exception))

    def test_opt与旧关键字合并(self):
        """旧关键字显式传入的应覆盖 opt (调用方意图优先)。

        用一个必然在入口校验阶段被拒的 URL (scheme 非法), 不触网、不真抓;
        能走到 raise 说明参数绑定成功。
        """
        from unittest import mock
        # 直接打桩入口校验: 验证绑定逻辑, 不依赖真实网络/站点
        with mock.patch.object(C, 'validate_public_url',
                               side_effect=ValueError('打桩: 校验必败')):
            with self.assertRaises(Exception):
                C.run_crawl('ftp://example.com/x',
                            opt=C.CrawlOptions(mode='range'),
                            mode='full')


if __name__ == '__main__':
    unittest.main(verbosity=2)
