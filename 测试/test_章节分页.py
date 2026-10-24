# -*- coding: utf-8 -*-
"""章节分页（Wave2 第一块）的用例。

这段逻辑原来埋在 `get_chapter_content` 的循环里，靠真实抓取才能验证；
抽出后可以纯离线钉住每条停止条件 —— 拆分最怕的就是"停止条件悄悄变了"。
"""
import pathlib
import sys
import unittest
from unittest import mock

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '源码'))
sys.path.insert(0, str(_PROJECT_ROOT / '测试'))

import _沙箱  # noqa: E402,F401  状态根沙箱
import sites_config  # noqa: E402
import 章节分页  # noqa: E402

章节 = 'https://s.example.com/read/1/10.html'


class 分页上限用例(unittest.TestCase):
    def test_配置里有max_pages则采用(self):
        cfg = {'content_pagination': {'max_pages': 30}}
        self.assertEqual(章节分页.分页上限(cfg, 章节), 30)

    def test_显式max_pages只能收紧(self):
        cfg = {'content_pagination': {'max_pages': 30}}
        self.assertEqual(章节分页.分页上限(cfg, 章节, None, max_pages=2), 2)
        self.assertEqual(章节分页.分页上限(cfg, 章节, None, max_pages=99), 30)

    def test_默认20_站点策略可取int(self):
        self.assertEqual(章节分页.分页上限(None, 章节, None), 20)
        self.assertEqual(章节分页.分页上限(None, 章节, lambda u, s, **k: 5), 5)
        self.assertEqual(章节分页.分页上限(None, 章节, lambda u, s, **k: 'x'), 20)

    def test_单页直出配置不吃max_pages(self):
        """content_pagination=None 不是 dict ⇒ 走默认/策略，不能 .get() 炸（K35）。"""
        self.assertEqual(章节分页.分页上限({'content_pagination': None}, 章节, None), 20)


class 下一页URL用例(unittest.TestCase):
    def test_html次序替换(self):
        with mock.patch.object(sites_config, 'get_adapter', lambda u: None):
            self.assertEqual(章节分页.下一页URL(章节, 2, None, 'https://s.example.com'),
                             'https://s.example.com/read/1/10_2.html')

    def test_站点策略优先于次序替换(self):
        with mock.patch.object(sites_config, 'get_adapter', lambda u: None):
            got = 章节分页.下一页URL(章节, 3, None, 'https://s.example.com',
                                    lambda u, 阶段, **k: '/p/3/' if 阶段 == '分页URL' else None)
        self.assertEqual(got, '/p/3/')

    def test_站点配置单页直出即停(self):
        with mock.patch.object(sites_config, 'get_adapter', lambda u: None):
            self.assertIsNone(章节分页.下一页URL(章节, 1, {'content_pagination': None},
                                                'https://s.example.com'))

    def test_站点配置分页走build_paged_url(self):
        with mock.patch.object(sites_config, 'get_adapter', lambda u: None), \
             mock.patch.object(sites_config, 'build_paged_url',
                               lambda u, i, cfg: f'https://s.example.com/p{i}'):
            got = 章节分页.下一页URL(章节, 4, {'content_pagination': {'模式': 'x'}},
                                    'https://s.example.com')
        self.assertEqual(got, 'https://s.example.com/p4')

    def test_适配器相对URL拼base(self):
        with mock.patch.object(sites_config, 'get_adapter',
                               lambda u: {'paginate': lambda cur, i, base_url='': f'/n/{i}'}):
            got = 章节分页.下一页URL(章节, 2, None, 'https://s.example.com/')
        self.assertEqual(got, 'https://s.example.com/n/2')

    def test_适配器收到的是上一页URL(self):
        """回归：原实现给 paginate 传的是 current_url（上一页），不是章节首页。"""
        收到 = {}
        with mock.patch.object(sites_config, 'get_adapter',
                               lambda u: {'paginate':
                                          lambda cur, i, base_url='': 收到.setdefault('cur', cur) and None}):
            章节分页.下一页URL(章节, 2, None, 'https://s.example.com',
                             当前URL='https://s.example.com/read/1/10_2.html')
        self.assertEqual(收到['cur'], 'https://s.example.com/read/1/10_2.html')

    def test_适配器返回None即停(self):
        with mock.patch.object(sites_config, 'get_adapter',
                               lambda u: {'paginate': lambda cur, i, base_url='': None}):
            self.assertIsNone(章节分页.下一页URL(章节, 2, None, 'https://s.example.com'))

    def test_适配器抛异常不炸且停(self):
        def _炸(cur, i, base_url=''):
            raise RuntimeError('插件缺陷')
        with mock.patch.object(sites_config, 'get_adapter', lambda u: {'paginate': _炸}):
            self.assertIsNone(章节分页.下一页URL(章节, 2, None, 'https://s.example.com'))

    def test_无html且无规则即停(self):
        with mock.patch.object(sites_config, 'get_adapter', lambda u: None):
            self.assertIsNone(章节分页.下一页URL('https://s.example.com/read/1/10',
                                               1, None, 'https://s.example.com'))


if __name__ == '__main__':
    unittest.main()
