# -*- coding: utf-8 -*-
"""v2.4.28: 网站清单 + 超长书提速 + 历史页关联 回归 (2026-09-13)。

覆盖:
  ① 网站清单.py: 自动生成模板 / 记录去重 / 补齐字段 / 域名→网站名 / 原子写
  ② 提速: 连接重试间隔 1s、_fetch_with_retry 连续失败快速跳过、极速档 8 线程
  ③ history_data 关联: URL→网站名/书名反查 + 书名过滤 (退化安全)

运行 (项目根): python -m unittest discover -s 测试 -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))
sys.path.insert(0, str(_根 / '源码' / 'gui_components'))

import 网站清单 as 清单                  # noqa: E402


# ----------------------------------------------------------------------
# ① 网站清单
# ----------------------------------------------------------------------

class Test网站清单(unittest.TestCase):

    def setUp(self):
        """把清单指向临时目录, 隔离真实用户数据"""
        self._tmp = Path(tempfile.mkdtemp(prefix='nc_wl_'))
        self._patcher = mock.patch.object(清单, 'get_state_root',
                                          return_value=str(self._tmp))
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_自动生成若缺失_生成模板(self):
        路径 = 清单.自动生成若缺失()
        self.assertTrue(os.path.exists(路径))
        with open(路径, encoding='utf-8') as f:
            head = f.read(200)
        self.assertIn('网站清单', head)

    def test_自动生成若缺失_幂等(self):
        路径1 = 清单.自动生成若缺失()
        路径2 = 清单.自动生成若缺失()
        self.assertEqual(路径1, 路径2)

    def test_记录去重(self):
        清单.自动生成若缺失()
        self.assertTrue(清单.记录('https://www.qiqishu.cc/book/47.html',
                                     '奇书网', '深空彼岸'))
        self.assertTrue(清单.记录('https://www.qiqishu.cc/book/47.html',
                                     '', ''))   # 同 URL 再记 → 不重复
        条目 = 清单.读取()
        self.assertEqual(len(条目), 1)
        self.assertEqual(条目[0]['网址'],
                         'https://www.qiqishu.cc/book/47.html')
        self.assertEqual(条目[0]['网站名'], '奇书网')
        self.assertEqual(条目[0]['小说名'], '深空彼岸')

    def test_重复记录补齐空字段(self):
        清单.自动生成若缺失()
        清单.记录('http://y.com/a.html', '', '')
        清单.记录('http://y.com/a.html', '月亮小说网', '禁神之下')
        条目 = 清单.读取()
        self.assertEqual(len(条目), 1)
        self.assertEqual(条目[0]['网站名'], '月亮小说网')
        self.assertEqual(条目[0]['小说名'], '禁神之下')

    def test_域名网站名映射与回退(self):
        self.assertEqual(清单.域名网站名('https://www.qiqishu.cc/x'),
                         '奇书网')
        self.assertEqual(清单.域名网站名('https://www.unknown-zzz.com/a'),
                         'unknown-zzz.com')
        self.assertEqual(清单.域名网站名(''), '')

    def test_按小说名搜索(self):
        清单.自动生成若缺失()
        清单.记录('http://a.com/1.html', '站A', '深空彼岸')
        清单.记录('http://b.com/2.html', '站B', '禁神之下')
        self.assertEqual(len(清单.按小说名搜索('彼岸')), 1)
        self.assertEqual(len(清单.按小说名搜索('不存在')), 0)
        self.assertEqual(清单.按小说名搜索(''), [])


# ----------------------------------------------------------------------
# ② 提速
# ----------------------------------------------------------------------

class Test超长书提速(unittest.TestCase):

    def test_极速档8线程(self):
        from 速度自适应 import _tier_by_level
        self.assertEqual(_tier_by_level(2).threads, 8)
        self.assertEqual(_tier_by_level(2).name, '极速')

    def test_连续失败快速跳过外层补试(self):
        """连续失败 ≥3 章后, _fetch_with_retry 不再做 3s/6s 补试, 直接返回空"""
        import 爬虫
        from unittest import mock as _m

        蜘蛛 = _m.Mock()
        蜘蛛._连续失败章数 = 5
        蜘蛛._fetch_with_qc.return_value = ''
        蜘蛛._清请求缓存 = lambda url: None
        chap = {'title': '第N章', 'url': 'https://x.com/n.html'}
        with _m.patch('time.sleep'):
            result = 爬虫.NovelSpider._fetch_with_retry(蜘蛛, chap, max_retries=2)
        self.assertEqual(result, '')
        蜘蛛._fetch_with_qc.assert_called_once()   # 只初试 1 次, 无外层补试

    def test_非连续失败仍正常补试(self):
        import 爬虫
        from unittest import mock as _m

        蜘蛛 = _m.Mock()
        蜘蛛._连续失败章数 = 1
        蜘蛛._fetch_with_qc.side_effect = ['', '']
        蜘蛛._清请求缓存 = lambda url: None
        chap = {'title': '第N章', 'url': 'https://x.com/n.html'}
        with _m.patch('time.sleep'):
            result = 爬虫.NovelSpider._fetch_with_retry(蜘蛛, chap, max_retries=2)
        self.assertEqual(result, '')
        # 连续失败数 <3: 外层补试仍发生 (初试 + 至少 1 次补试)
        self.assertGreaterEqual(蜘蛛._fetch_with_qc.call_count, 2)


# ----------------------------------------------------------------------
# ③ 历史页关联 (history_data)
# ----------------------------------------------------------------------

class Test历史页关联网站清单(unittest.TestCase):

    def setUp(self):
        import importlib
        # 网站清单模块可被 history_data 实际 import: 用临时状态根制造一条记录。
        # 直接 import 测试模块 (history_data 已 try import 网站清单; 此刻 get_state_root
        # 指向临时目录, 读到的就是测试写的记录)
        self._tmp = Path(tempfile.mkdtemp(prefix='nc_hd_'))
        self._patcher = mock.patch.object(清单, 'get_state_root',
                                          return_value=str(self._tmp))
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        清单.自动生成若缺失()
        清单.记录('https://www.qiqishu.cc/read/47/3980.html', '奇书网', '深空彼岸')
        import gui_components.pages.history_data as hd
        importlib.reload(hd)
        self.hd = hd

    def test_补网站信息(self):
        rows = [{'url': 'https://www.qiqishu.cc/read/47/3980.html',
                 '域名': 'qiqishu.cc'},
                {'url': 'https://no-record.com/x.html', '域名': 'no-record.com'}]
        out = self.hd.补网站信息(rows)
        self.assertEqual(out[0]['网站名'], '奇书网')
        self.assertEqual(out[0]['小说名'], '深空彼岸')
        # 未命中: 网站名回退域名, 书名 '—' 由页面层处理 (空串)
        self.assertEqual(out[1]['网站名'], 'no-record.com')
        self.assertEqual(out[1]['小说名'], '')

    def test_按书名过滤(self):
        rows = [
            {'url': 'https://www.qiqishu.cc/read/47/3980.html', '域名': 'qiqishu.cc'},
            {'url': 'https://other.com/x.html', '域名': 'other.com'},
        ]
        out = self.hd.按书名过滤(rows, '深空')
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['url'],
                         'https://www.qiqishu.cc/read/47/3980.html')


if __name__ == '__main__':
    unittest.main(verbosity=2)