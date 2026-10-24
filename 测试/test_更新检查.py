# -*- coding: utf-8 -*-
"""更新检查测试 (C7, 2026-10-17)。

锁定契约:
  ① 版本比较按**数字段** (2.5.10 > 2.5.9, 不是字符串比); 任一侧解析不出 → False;
  ② 检查更新: 有新版/已最新/网络失败/坏 JSON/空 tag → 正确返回或 None, **不抛**;
  ③ 响应只读一次, 请求体带 Accept/UA (GitHub API 礼节);
  ④ 取当前版本: 源码模式读 版本.json; 失败返回 '' 不抛;
  ⑤ 全程 mock, **零真实网络**。
运行: python -m unittest discover -s 测试
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

import 更新检查 as U   # noqa: E402


class Test版本比较(unittest.TestCase):

    def test_按数字段不是字符串(self):
        self.assertTrue(U.有新版本('2.5.9', '2.5.10'))
        self.assertTrue(U.有新版本('2.5.9', 'v2.5.10'))

    def test_相同与更旧(self):
        self.assertFalse(U.有新版本('2.5.40', '2.5.40'))
        self.assertFalse(U.有新版本('2.5.41', '2.5.40'))

    def test_任一侧无数字不打扰(self):
        self.assertFalse(U.有新版本('', '2.5.40'))
        self.assertFalse(U.有新版本('2.5.40', ''))
        self.assertFalse(U.有新版本('dev', 'latest'))

    def test_多段版本(self):
        self.assertTrue(U.有新版本('2.5.40.0', '2.5.40.1'))
        self.assertTrue(U.有新版本('2.4.99', '2.5.0'))


class Test检查更新(unittest.TestCase):
    """检查更新: 全 mock requests, 零真实网络。"""

    def setUp(self):
        # 源码内联 IP 边界校验会真实调 socket.getaddrinfo —— 测试环境可能
        # 无 DNS, 统一桩成公网 IP, 保住"零真实网络"承诺
        self._dns = mock.patch.object(
            U.socket, 'getaddrinfo',
            return_value=[(2, 1, 6, '', ('140.82.112.6', 443))])
        self._dns.start()
        self.addCleanup(self._dns.stop)

    def _打桩(self, get):
        return mock.patch('requests.get', get)

    def test_有新版(self):
        当前 = '2.5.41'
        响应 = mock.Mock()
        响应.json.return_value = {
            'tag_name': 'v2.5.50',
            'html_url': 'https://github.com/x/y/releases/tag/v2.5.50'}
        响应.raise_for_status.return_value = None
        with mock.patch('requests.get', return_value=响应) as g, \
                mock.patch.object(U, '取当前版本', return_value=当前):
            d = U.检查更新()
        self.assertTrue(d['有新版'])
        self.assertEqual(d['最新版'], '2.5.50')
        self.assertEqual(d['当前版'], '2.5.41')
        self.assertIn('releases/tag', d['发布页'])
        # GitHub API 礼节: Accept + UA
        头 = g.call_args[1]['headers']
        self.assertIn('Accept', 头)
        self.assertIn('User-Agent', 头)

    def test_已最新(self):
        响应 = mock.Mock()
        响应.json.return_value = {'tag_name': 'v2.5.41', 'html_url': 'u'}
        响应.raise_for_status.return_value = None
        with mock.patch('requests.get', return_value=响应), \
                mock.patch.object(U, '取当前版本', return_value='2.5.41'):
            d = U.检查更新()
        self.assertFalse(d['有新版'])

    def test_本地比远程新不提示(self):
        响应 = mock.Mock()
        响应.json.return_value = {'tag_name': 'v2.5.30', 'html_url': 'u'}
        响应.raise_for_status.return_value = None
        with mock.patch('requests.get', return_value=响应), \
                mock.patch.object(U, '取当前版本', return_value='2.5.41'):
            d = U.检查更新()
        self.assertFalse(d['有新版'], '本地更新 (未发布) 不得提示"有新版本"')

    def test_网络失败返回None(self):
        import requests as _rq
        with mock.patch('requests.get', side_effect=_rq.ConnectionError('offline')):
            self.assertIsNone(U.检查更新())

    def test_端点解析到私网IP放弃且不发请求(self):
        """内联 IP 边界校验: DNS rebinding/ hosts 污染到私网 → 请求前短路。"""
        响应 = mock.Mock()
        响应.json.return_value = {'tag_name': 'v2.5.99'}
        with mock.patch.object(U.socket, 'getaddrinfo',
                               return_value=[(2, 1, 6, '', ('192.168.1.1', 443))]), \
                mock.patch('requests.get', return_value=响应) as g:
            self.assertIsNone(U.检查更新())
        g.assert_not_called()

    def test_超时返回None(self):
        import requests as _rq
        with mock.patch('requests.get', side_effect=_rq.Timeout('slow')):
            self.assertIsNone(U.检查更新())

    def test_坏JSON返回None(self):
        响应 = mock.Mock()
        响应.json.side_effect = ValueError('not json')
        响应.raise_for_status.return_value = None
        with mock.patch('requests.get', return_value=响应):
            self.assertIsNone(U.检查更新())

    def test_空tag返回None(self):
        响应 = mock.Mock()
        响应.json.return_value = {'tag_name': '', 'html_url': 'u'}
        响应.raise_for_status.return_value = None
        with mock.patch('requests.get', return_value=响应):
            self.assertIsNone(U.检查更新())

    def test_非dict响应返回None(self):
        响应 = mock.Mock()
        响应.json.return_value = ['不是', 'dict']
        响应.raise_for_status.return_value = None
        with mock.patch('requests.get', return_value=响应):
            self.assertIsNone(U.检查更新())


class Test取当前版本(unittest.TestCase):

    def test_源码模式读版本json(self):
        """非 frozen: 读 脚本/版本.json (测试环境即此路径)"""
        v = U.取当前版本()
        self.assertRegex(v, r'^\d+\.\d+\.\d+$')

    def test_失败返回空不抛(self):
        with mock.patch('builtins.open', side_effect=OSError('boom')):
            with mock.patch('os.path.normpath', return_value='/nonexistent/x.json'):
                self.assertEqual(U.取当前版本(), '')


if __name__ == '__main__':
    unittest.main(verbosity=2)
