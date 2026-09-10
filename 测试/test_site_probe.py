# -*- coding: utf-8 -*-
"""站点探测的 SSRF 防护 (离线, 不联网)。

修复背景: `probe_site` 的 URL 直接来自站点管理页的用户输入, 而旧实现发请求前
**完全没有校验** —— 填入内网/环回地址即可让本机对其发起请求。现与抓取同标准,
统一走 `sites_config.validate_public_url`。

这些用例之所以能离线跑, 正是因为非法 URL 在发请求之前就被拦下。

运行方式 (项目根目录):
    python -m unittest discover -s 测试 -v
"""
import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '源码'))

import site_probe  # noqa: E402


class TestProbeSSRF(unittest.TestCase):
    """非公网 URL 必须被拒, 且不得发起任何请求"""

    def _probe(self, url):
        return site_probe.probe_site(url, timeout=1)

    def _assert_被拒(self, url):
        r = self._probe(url)
        self.assertFalse(r['ok'], f'{url} 不应被判定为可用')
        self.assertEqual(r['status_code'], 0, f'{url} 不应发出请求 (状态码应保持 0)')
        self.assertEqual(r['engine_chain'], [], f'{url} 不应走到引擎请求阶段')
        self.assertIn('未通过公网校验', r['error'])

    def test_环回地址被拒(self):
        self._assert_被拒('http://127.0.0.1/')

    def test_localhost被拒(self):
        self._assert_被拒('http://localhost:8080/')

    def test_内网域名后缀被拒(self):
        self._assert_被拒('http://router.internal/')

    def test_私有网段被拒(self):
        self._assert_被拒('http://192.168.1.1/')

    def test_链路本地地址被拒(self):
        self._assert_被拒('http://169.254.169.254/')

    def test_非http协议被拒(self):
        self._assert_被拒('file:///etc/passwd')


if __name__ == '__main__':
    unittest.main(verbosity=2)
