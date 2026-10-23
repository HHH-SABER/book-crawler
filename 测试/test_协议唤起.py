# -*- coding: utf-8 -*-
"""协议唤起回归 (2026-10-23: 插件"开始抓取"→ 自动唤起程序)。

覆盖:
  ① URL 解析: novelcrawler://crawl?url=...&mode=...&start=&end= (含异常输入);
  ② 注册命令形态: frozen=EXE 自身 / 源码=python+启动器, 都带 "%1";
  ③ 转发: 鉴权头与 body 正确, 失败不抛 (mock urlopen);
  ④ 探活: healthz 200/异常 两种结果。
"""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

import 协议唤起 as P   # noqa: E402


class Test解析(unittest.TestCase):

    def test_完整参数(self):
        argv = ['app.exe', 'novelcrawler://crawl?url=https%3A%2F%2Fa.com%2Fb%2F'
                            '&mode=range&start=5&end=20']
        r = P.取唤起参数(argv)
        self.assertEqual(r['url'], 'https://a.com/b/')
        self.assertEqual(r['mode'], 'range')
        self.assertEqual((r['start'], r['end']), (5, 20))

    def test_缺省为完整抓取(self):
        r = P.取唤起参数(['x', 'novelcrawler://crawl?url=https%3A%2F%2Fa.com'])
        self.assertEqual(r['mode'], 'full')
        self.assertEqual(r['start'], 0)

    def test_无协议参数返回空(self):
        self.assertEqual(P.取唤起参数(['x', '--list']), {})
        self.assertEqual(P.取唤起参数(['x']), {})

    def test_缺url或非法mode(self):
        self.assertEqual(P.取唤起参数(['x', 'novelcrawler://crawl?mode=full']), {})
        r = P.取唤起参数(['x', 'novelcrawler://crawl?url=https%3A%2F%2Fa.com&mode=weird'])
        self.assertEqual(r['mode'], 'full', '非法模式回落完整抓取')

    def test_区间非法数值不崩(self):
        r = P.取唤起参数(['x', 'novelcrawler://crawl?url=https%3A%2F%2Fa.com'
                            '&mode=range&start=abc&end=-3'])
        self.assertEqual(r['start'], 0)
        self.assertEqual(r['end'], 1, '负数夹到 1')


class Test注册命令(unittest.TestCase):

    def test_源码形态带启动器(self):
        info = P.注册命令()
        self.assertIn('"%1"', info['命令'])
        self.assertIn('启动器.py', info['命令'])
        self.assertEqual(info['键'], r'Software\Classes\novelcrawler')

    def test_frozen形态用自身exe(self):
        with mock.patch.object(P.sys, 'frozen', True, create=True), \
                mock.patch.object(P.sys, 'executable', r'D:\app\小说爬虫.exe'):
            info = P.注册命令()
        self.assertIn(r'D:\app\小说爬虫.exe', info['命令'])
        self.assertNotIn('启动器.py', info['命令'])


class Test转发(unittest.TestCase):

    def _假响应(self, 状态=200):
        r = mock.MagicMock()
        r.status = 状态
        r.__enter__ = lambda s: r
        r.__exit__ = lambda *a: False
        return r

    def test_转发成功带上鉴权与区间(self):
        捕获 = {}

        def 假urlopen(req, timeout=0):
            捕获['url'] = req.full_url
            捕获['body'] = json.loads(req.data.decode('utf-8'))
            捕获['auth'] = req.headers.get('Authorization')
            return self._假响应(200)

        with mock.patch.object(P.urllib.request, 'urlopen', 假urlopen), \
                mock.patch('远控.配置.取配置',
                           return_value={'端口': 8760, 'token': 'tk'}):
            ok = P.转发到已运行实例({'url': 'https://a.com/b/', 'mode': 'range',
                                    'start': 3, 'end': 9})
        self.assertTrue(ok)
        self.assertIn('/api/v1/tasks', 捕获['url'])
        self.assertEqual(捕获['body']['chapter_range'], [3, 9])
        self.assertEqual(捕获['body']['mode'], 'range')
        self.assertEqual(捕获['auth'], 'Bearer tk')

    def test_转发失败不抛(self):
        with mock.patch.object(P.urllib.request, 'urlopen',
                               side_effect=OSError('refused')), \
                mock.patch('远控.配置.取配置', return_value={'端口': 8760, 'token': 'tk'}):
            self.assertFalse(P.转发到已运行实例({'url': 'https://a.com'}))

    def test_无url或无token直接False(self):
        self.assertFalse(P.转发到已运行实例({'mode': 'full'}))
        with mock.patch('远控.配置.取配置', return_value={'端口': 8760, 'token': ''}):
            self.assertFalse(P.转发到已运行实例({'url': 'https://a.com'}))

    def test_探活(self):
        with mock.patch.object(P.urllib.request, 'urlopen',
                               return_value=self._假响应(200)), \
                mock.patch('远控.配置.取配置', return_value={'端口': 8760, 'token': 'tk'}):
            self.assertTrue(P.有已运行实例())
        with mock.patch.object(P.urllib.request, 'urlopen', side_effect=OSError('x')), \
                mock.patch('远控.配置.取配置', return_value={'端口': 8760, 'token': 'tk'}):
            self.assertFalse(P.有已运行实例())


class Test插件产物(unittest.TestCase):
    """插件 dist 里必须有"抓取当前页面"三要素 (脚本改完必须重新构建 dist)。"""

    def setUp(self):
        self.dist = _根 / '插件' / 'dist'
        if not (self.dist / 'chrome' / 'popup.html').is_file():
            self.skipTest('插件 dist 未构建')

    def test_两版含抓取界面与协议(self):
        for 版 in ('chrome', 'edge'):
            html = (self.dist / 版 / 'popup.html').read_text(encoding='utf-8')
            js = (self.dist / 版 / 'background.js').read_text(encoding='utf-8')
            self.assertIn('开始抓取', html)
            self.assertIn('章节区间', html)
            self.assertIn('novelcrawler://', js)
            self.assertIn('/api/v1/tasks', js)


if __name__ == '__main__':
    unittest.main(verbosity=2)
