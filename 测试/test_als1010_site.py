# -*- coding: utf-8 -*-
"""als1010.space 站点专项适配回归 (2026-09-12)。

背景两问的落点:
  ① "打包 EXE 跑成功率低" → 根因是 EXE 读 EXE 旁的 captcha_config.json
     (首启从合规模板复制, ddddocr 默认关) → 自动识别被拒 → 只能人工;
     源码环境读根目录配置 (用户已显式开启) → 成功率高。属配置层非代码缺陷。
  ② 本批 8/9 号书失败 → 站点进入长时软限频 (整个 IP 收"请稍后再试"页),
     章节经重试仍失败后存空占位待补抓。

本测试锁定站点适配四项: 档位压档 / 专属冷却秒 / 软封页识别 / 正常提取。
"""
import importlib.util
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / '源码'))

_软封页 = (_ROOT / '测试样本' / 'als1010_软封页.html').read_text(encoding='utf-8')
_验证页 = (_ROOT / '测试样本' / 'als1010_访问验证页.html').read_text(encoding='utf-8')


def _载入适配器():
    spec = importlib.util.spec_from_file_location(
        'als1010', str(_ROOT / '站点适配' / 'als1010.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestAls1010站点适配(unittest.TestCase):

    def test_档位压档_最低档(self):
        """als1010 并发上限=最低档 (1线程), 防并发触发软限频"""
        from 速度自适应 import SITE_TIER_CAPS, build_controller
        self.assertEqual(SITE_TIER_CAPS.get('als1010.space'), 0)
        ctl = build_controller(
            'https://xn--vcsx64d.als1010.space/other/chapters/id/49271.html',
            total_chapters=100)
        self.assertLessEqual(ctl._tier.threads, 1,
                             f'als1010 初始档位应≤1线程, 实际 {ctl._tier}')

    def test_专属冷却秒_900(self):
        """软限频恢复极慢 → 该域冷却 900s; 其他域维持 300s"""
        import 爬虫
        self.assertEqual(爬虫._站点冷却秒('xn--vcsx64d.als1010.space'), 900)
        self.assertEqual(爬虫._站点冷却秒('als1010.space'), 900)
        self.assertEqual(爬虫._站点冷却秒('www.yunshuzhai.com'), 300)
        self.assertEqual(爬虫._站点冷却秒(''), 300)

    def test_软封页不提取正文(self):
        """'请稍后再试' 软封页必须返回 None (旧行为会提 342 字符垃圾入库)"""
        from bs4 import BeautifulSoup
        ad = _载入适配器()
        soup = BeautifulSoup(_软封页, 'lxml')
        self.assertIsNone(ad.extract_content(soup, 'https://x/1.html', 'https://x'))

    def test_访问验证页不提取正文_回归(self):
        from bs4 import BeautifulSoup
        ad = _载入适配器()
        soup = BeautifulSoup(_验证页, 'lxml')
        self.assertIsNone(ad.extract_content(soup, 'https://x/1.html', 'https://x'))

    def test_正常页提取不受影响(self):
        from bs4 import BeautifulSoup
        ad = _载入适配器()
        正文 = ''.join(f'<p>第{i}段正文内容，测试段落。</p>' for i in range(5))
        soup = BeautifulSoup(
            f'<html><body><div class="read-content">{正文}</div></body></html>',
            'lxml')
        out = ad.extract_content(soup, 'https://x/1.html', 'https://x')
        self.assertIsNotNone(out)
        self.assertIn('第0段正文内容', out)


if __name__ == '__main__':
    unittest.main(verbosity=2)
