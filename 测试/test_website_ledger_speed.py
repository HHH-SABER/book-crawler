# -*- coding: utf-8 -*-
"""v2.4.28: 网站清单 + 超长书提速 + 历史页关联 回归 (2026-09-13)。

覆盖:
  ① 网站清单.py: 自动生成模板 / 记录去重 / 补齐字段 / 域名→网站名 / 原子写
     (v2.4.35 增补: 落点改为程序基目录 / NC_LEDGER_PATH 隔离 / 旧位置迁移 /
      非 http 目标不入清单)
  ② 提速: 连接重试间隔 1s、_fetch_with_retry 连续失败快速跳过、极速档 8 线程
  ③ history_data 关联: URL→网站名/书名反查 + 书名过滤 (退化安全)

运行 (项目根): python -m unittest discover -s 测试 -v
"""
import os
import shutil
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
        """隔离真实用户数据: NC_LEDGER_PATH 指向临时文件。

        2026-10-01: 清单落点从状态根改到程序基目录后, 原先 patch get_state_root
        的隔离方式已失效 (会真写到项目根)。改用它自身的隔离变量, 且该变量
        生效时模块会跳过"旧位置迁移", 测试不会把真实记录搬进临时环境。
        """
        self._tmp = Path(tempfile.mkdtemp(prefix='nc_wl_'))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self._ledger = self._tmp / '网站清单.txt'
        self._env = mock.patch.dict(os.environ,
                                    {'NC_LEDGER_PATH': str(self._ledger)})
        self._env.start()
        self.addCleanup(self._env.stop)

    def test_默认落点在程序基目录(self):
        """未设覆盖变量时, 清单落在程序基目录 (EXE 同级 / 源码=项目根)"""
        base = self._tmp / 'base'
        with mock.patch.dict(os.environ, {'NC_LEDGER_PATH': ''}), \
             mock.patch.object(清单, 'get_app_base_dir', return_value=str(base)):
            self.assertEqual(清单.文件路径(),
                             os.path.join(str(base), '网站清单.txt'))

    def test_环境变量覆盖优先(self):
        """NC_LEDGER_PATH 优先于程序基目录 (多实例/探针隔离)"""
        自定义 = self._tmp / 'custom' / 'x.txt'
        with mock.patch.dict(os.environ, {'NC_LEDGER_PATH': str(自定义)}):
            self.assertEqual(清单.文件路径(), os.path.abspath(str(自定义)))

    def test_自动生成若缺失_生成模板(self):
        路径 = 清单.自动生成若缺失()
        self.assertTrue(os.path.exists(路径))
        with open(路径, encoding='utf-8') as f:
            head = f.read(200)
        self.assertIn('网站清单', head)
        self.assertIn('请勿上传', head)      # 隐私提示在模板里

    def test_自动生成若缺失_幂等(self):
        路径1 = 清单.自动生成若缺失()
        路径2 = 清单.自动生成若缺失()
        self.assertEqual(路径1, 路径2)

    def test_只收录http网址(self):
        """本地文件/临时路径/空值一律不入清单 — 保证记录对用户始终有意义"""
        清单.自动生成若缺失()
        self.assertFalse(清单.记录(r'C:\Users\x\AppData\Local\Temp\nc_t1_a\测试书.txt',
                                   'c', '测试书'))
        self.assertFalse(清单.记录('file:///C:/a.txt', '本地', '书'))
        self.assertFalse(清单.记录('', '空', '空'))
        self.assertEqual(清单.读取(), [])
        self.assertTrue(清单.记录('https://ok.com/book/1.html', '站A', '书A'))
        self.assertEqual(len(清单.读取()), 1)

    def test_旧位置迁移到新落点(self):
        """状态根旧清单有记录时, 首次运行迁移到新落点, 历史不丢"""
        旧文件 = self._tmp / 'state' / '网站清单.txt'
        旧文件.parent.mkdir(parents=True, exist_ok=True)
        旧文件.write_text('https://old.com/book/1.html\t老站\t老书\n',
                          encoding='utf-8')
        新基 = self._tmp / 'base2'
        新基.mkdir(exist_ok=True)
        with mock.patch.dict(os.environ, {'NC_LEDGER_PATH': ''}), \
             mock.patch.object(清单, 'get_app_base_dir', return_value=str(新基)), \
             mock.patch.object(清单, '旧路径', return_value=str(旧文件)):
            路径 = 清单.自动生成若缺失()
            self.assertTrue(os.path.exists(路径))
            条目 = 清单.读取()
        self.assertEqual(len(条目), 1)
        self.assertEqual(条目[0]['网址'], 'https://old.com/book/1.html')
        self.assertEqual(条目[0]['小说名'], '老书')

    def test_迁移不覆盖已有记录(self):
        """新落点已有内容时不再迁移 (幂等, 只补空)"""
        清单.自动生成若缺失()
        清单.记录('https://new.com/book/1.html', '新站', '新书')
        旧文件 = self._tmp / 'state2' / '网站清单.txt'
        旧文件.parent.mkdir(parents=True, exist_ok=True)
        旧文件.write_text('https://old.com/book/1.html\t老站\t老书\n',
                          encoding='utf-8')
        with mock.patch.object(清单, '旧路径', return_value=str(旧文件)):
            清单.自动生成若缺失()
        条目 = 清单.读取()
        self.assertEqual(len(条目), 1)
        self.assertEqual(条目[0]['网址'], 'https://new.com/book/1.html')

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
        # 实网抓取走 punycode 子域 (xn--vcsx64d = '书'), 同样映射到中文站名
        self.assertEqual(
            清单.域名网站名('https://xn--vcsx64d.als1010.space/x.html'),
            '爱丽丝书屋')

    def test_记录不抹掉表头注释(self):
        """回写清单必须保留 # 注释头。

        2026-10-01 实测: 记录() 原先用 读取() 重建全文, 注释行会被整段丢掉 ——
        别处会话跑完一批抓取后, 清单只剩纯数据行。现统一走 注释头 + 数据行。
        """
        路径 = 清单.自动生成若缺失()
        with open(路径, encoding='utf-8') as f:
            头行数 = sum(1 for l in f if l.startswith('#'))
        self.assertGreater(头行数, 0, '模板应带注释头')

        清单.记录('https://a.com/book/1.html', '站A', '书甲')        # 新增分支
        清单.记录('https://a.com/book/1.html', '站A', '书乙')        # 更新分支

        with open(路径, encoding='utf-8') as f:
            行s = [l.rstrip('\n') for l in f]
        self.assertTrue(行s[0].startswith('#'),
                        f'表头被抹掉: 首行={行s[0]!r}')
        self.assertIn('请勿上传', '\n'.join(行s), '隐私提示行丢失')
        self.assertEqual(sum(1 for l in 行s if l.startswith('#')), 头行数,
                         '注释行数应稳定 (不得重复堆积)')
        self.assertEqual(len(清单.读取()), 1)

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
        # 网站清单模块可被 history_data 实际 import: 用隔离落点制造一条记录。
        # 直接 import 测试模块 (history_data 已 try import 网站清单; 此刻清单
        # 指向临时文件, 读到的就是测试写的记录)
        self._tmp = Path(tempfile.mkdtemp(prefix='nc_hd_'))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self._ledger = self._tmp / '网站清单.txt'
        self._env = mock.patch.dict(os.environ,
                                    {'NC_LEDGER_PATH': str(self._ledger)})
        self._env.start()
        self.addCleanup(self._env.stop)
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