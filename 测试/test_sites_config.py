# -*- coding: utf-8 -*-
"""`源码/sites_config.py` 契约测试 (阶段一 #3)。

为什么补这个: 站点配置是**抓取行为的核心配置源** (站点匹配/禁用/广告规则/
水印/分页/SSRF 校验), 而它此前无专属测试 —— 今天 B 修法那次 bug 就是
"配置正则不生效"这一类问题的实例。

覆盖:
  ① SSRF 校验 (远控 API 也用它) —— 协议/localhost/私网/保留地址拒绝, 公网放行;
  ② 分页 URL 构造 (chapter_subdir 函数型机制);
  ③ get_site_pattern 匹配/禁用/未命中;
  ④ 广告规则: 关键词+正则/非法正则跳过/空规则/缓存命中;
  ⑤ 水印 token 过滤;
  ⑥ 热重载: reload 后广告缓存失效 (H7 修复的行为回归)。

全程 mock 运行时配置加载 (不读本机 站点配置.json/站点表), 注入条目一律用
`sitex.example.com` 占位域名; 全局状态在 tearDown 完整恢复, 不污染其他测试。
运行: python -m unittest discover -s 测试
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

import sites_config as SC   # noqa: E402

_占位域 = 'sitex.example.com'


def _测试条目(**覆盖):
    条 = {'domain': _占位域, 'pattern': 'html_selector',
          'catalog_parser': 'generic'}
    条.update(覆盖)
    return 条


class TestSSRF校验(unittest.TestCase):
    """validate_public_url: 远控 API 与抓取的入口安全闸"""

    def test_公网http放行(self):
        SC.validate_public_url('http://book.sitex.example.com/read/1/2.html')

    def test_公网https放行(self):
        SC.validate_public_url('https://sitex.example.com/')

    def test_拒绝非http协议(self):
        for url in ('ftp://sitex.example.com/x', 'file:///etc/passwd',
                    'javascript:alert(1)', 'gopher://sitex.example.com'):
            with self.subTest(url=url):
                self.assertRaises(ValueError, SC.validate_public_url, url)

    def test_拒绝localhost与内部域(self):
        for url in ('http://localhost:8080/', 'http://127.0.0.1/x',
                    'http://host.internal/x', 'http://my.host.local/'):
            with self.subTest(url=url):
                self.assertRaises(ValueError, SC.validate_public_url, url)

    def test_拒绝私网与保留地址(self):
        for url in ('http://10.0.0.1/', 'http://192.168.1.1/',
                    'http://172.16.0.1/', 'http://169.254.169.254/',
                    'http://0.0.0.0/', 'http://224.0.0.1/', 'http://[::1]/'):
            with self.subTest(url=url):
                self.assertRaises(ValueError, SC.validate_public_url, url)

    def test_拒绝缺host(self):
        self.assertRaises(ValueError, SC.validate_public_url, 'http:///x')


class Test分页构造(unittest.TestCase):

    def test_第1页原样(self):
        u = 'https://sitex.example.com/dir/123/456.html'
        self.assertEqual(SC._paginate_chapter_subdir(u, 0), u)

    def test_第N页子目录(self):
        u = 'https://sitex.example.com/dir/123/456.html'
        self.assertEqual(SC._paginate_chapter_subdir(u, 2),
                         'https://sitex.example.com/dir/123/456/2.html')

    def test_形态不匹配返回None(self):
        for u in ('https://sitex.example.com/dir/abc.html',
                  'https://sitex.example.com/456.html',
                  'not-a-url'):
            with self.subTest(url=u):
                self.assertIsNone(SC._paginate_chapter_subdir(u, 2))


class Test站点匹配与规则(unittest.TestCase):
    """get_site_pattern / 广告规则 / 水印 token (注入占位条目)"""

    def setUp(self):
        self._旧表 = SC.SITE_PATTERNS[:]
        self._旧缓存 = dict(SC._广告规则缓存)
        # 隔离运行时加载: 不读本机 站点配置.json, 不加载本机适配器
        self._patcher = mock.patch.multiple(
            SC, _apply_runtime_config=lambda: None, load_adapters=lambda: None)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        SC.SITE_PATTERNS[:] = self._旧表
        SC._广告规则缓存.clear()
        SC._广告规则缓存.update(self._旧缓存)

    # ---- get_site_pattern ----
    def test_命中(self):
        SC.SITE_PATTERNS.append(_测试条目())
        pat = SC.get_site_pattern(f'https://{_占位域}/read/1/2.html')
        self.assertIsNotNone(pat)
        self.assertEqual(pat['domain'], _占位域)

    def test_未命中返回None(self):
        self.assertIsNone(SC.get_site_pattern('https://other.example.org/'))

    def test_禁用跳过(self):
        SC.SITE_PATTERNS.append(_测试条目(enabled=False))
        self.assertIsNone(SC.get_site_pattern(f'https://{_占位域}/x'))

    def test_大小写不敏感(self):
        SC.SITE_PATTERNS.append(_测试条目())
        self.assertIsNotNone(
            SC.get_site_pattern(f'https://{_占位域.upper()}/x'))

    # ---- 广告规则 ----
    def test_广告规则关键词与正则(self):
        SC.SITE_PATTERNS.append(_测试条目(ad_rules={
            '关键词': ['下载APP', ''],
            '行正则': [r'^\s*广告\s*$', r'([未闭合']}))
        规则 = SC.获取广告规则(f'https://{_占位域}/x')
        self.assertEqual(规则['关键词'], ['下载APP'], '空关键词应被过滤')
        self.assertEqual(len(规则['正则']), 1, '非法正则应跳过, 合法正则保留')

    def test_广告规则_未配置返回空(self):
        SC.SITE_PATTERNS.append(_测试条目())
        规则 = SC.获取广告规则(f'https://{_占位域}/x')
        self.assertEqual(规则, {'关键词': [], '正则': []})

    def test_广告规则_缓存命中(self):
        SC.SITE_PATTERNS.append(_测试条目(ad_rules={'关键词': ['a']}))
        a = SC.获取广告规则(f'https://{_占位域}/x')
        b = SC.获取广告规则(f'https://{_占位域}/y')
        self.assertIs(a, b, '同域名二次查询应命中缓存')

    # ---- 水印 token ----
    def test_水印token过滤空值(self):
        SC.SITE_PATTERNS.append(_测试条目(watermark_tokens=['水印A', '', None]))
        self.assertEqual(SC.获取水印token(f'https://{_占位域}/x'), ['水印A'])

    def test_水印token_未配置空(self):
        SC.SITE_PATTERNS.append(_测试条目())
        self.assertEqual(SC.获取水印token(f'https://{_占位域}/x'), [])

    # ---- 热重载清缓存 (H7 行为回归) ----
    def test_热重载清广告缓存(self):
        SC.SITE_PATTERNS.append(_测试条目(ad_rules={'关键词': ['a']}))
        SC.获取广告规则(f'https://{_占位域}/x')
        self.assertIn(_占位域, SC._广告规则缓存)
        # 只验证"重放会清缓存"这一契约, 不真的重放本机配置
        with mock.patch.object(SC, '_执行重放', wraps=SC._执行重放):
            SC._执行重放()
        self.assertNotIn(_占位域, SC._广告规则缓存,
                         '重放后广告缓存必须失效 (否则站点规则改动不生效)')


if __name__ == '__main__':
    unittest.main(verbosity=2)
