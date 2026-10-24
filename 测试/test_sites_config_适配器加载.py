# -*- coding: utf-8 -*-
"""`源码/sites_config.load_adapters` 特征测试（P9 阶段 0 · 高扇入模块护栏）。

为什么补这个: `sites_config` 扇入 **15**，P9 把它排在阶段 6（最后才拆），
前置条件就是「先有特征测试锁行为」。现有 `test_sites_config.py` 已覆盖
匹配/广告/水印/热重载，但**适配器加载链**（三层来源、先到先得、坏插件容错、
站点表与提取器注册）此前零覆盖 —— 而这正是拆分时最容易改坏的部分。

覆盖:
  ① 目录缺失（公开形态）不崩、注册表为空；
  ② 合法插件 → 登记 ADAPTERS + 并入站点表 + `get_adapter` 可命中；
  ③ `_` 开头文件（占位模板）不加载；
  ④ 同域名两个插件 → 先到先得（sorted 在前者生效）；
  ⑤ `仅注册解析器` → 只登记函数，不污染站点表；
  ⑥ 语法错误插件被跳过，不影响同目录其他插件；
  ⑦ 站点表 JSON 加载 + 重复加载不产生重复条目；
  ⑧ `_提取器.py` 的 EXTRACTORS / ALIASES 注册生效。

全程用临时目录伪造 BASE_DIR，tearDown 完整恢复全局状态（ADAPTERS /
SITE_PATTERNS / 两个 APPENDED 集合 / 提取器表），不污染其他测试。
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

import _path_utils as PU      # noqa: E402
import sites_config as SC     # noqa: E402

_域A = 'sitea.example.com'
_域T = 'sitet.example.com'


class _适配器基类(unittest.TestCase):
    """隔离 BASE_DIR + 保存/恢复 sites_config 的全部可变全局状态"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.基 = Path(self._tmp.name)
        (self.基 / '站点适配').mkdir()
        (self.基 / '站点适配_本地').mkdir()

        self._旧 = {
            'ADAPTERS': SC.ADAPTERS,
            'LOADED': SC._ADAPTERS_LOADED,
            'APPENDED': set(SC._ADAPTER_APPENDED),
            '表APPENDED': set(SC._LOCAL_TABLE_APPENDED),
            'PATTERNS': SC.SITE_PATTERNS[:],
            'EXTRACTORS': dict(SC._EXTRACTORS),
            'ALIASES': dict(SC._EXTRACTOR_ALIASES),
        }
        SC.ADAPTERS = {}
        SC._ADAPTERS_LOADED = False
        SC._ADAPTER_APPENDED = set()
        SC._LOCAL_TABLE_APPENDED = set()
        SC.SITE_PATTERNS[:] = []
        SC._EXTRACTORS.clear()
        SC._EXTRACTOR_ALIASES.clear()

        self._补丁 = mock.patch.object(
            PU, 'get_app_base_dir', lambda: str(self.基))
        self._补丁.start()

    def tearDown(self):
        self._补丁.stop()
        SC.ADAPTERS = self._旧['ADAPTERS']
        SC._ADAPTERS_LOADED = self._旧['LOADED']
        SC._ADAPTER_APPENDED = self._旧['APPENDED']
        SC._LOCAL_TABLE_APPENDED = self._旧['表APPENDED']
        SC.SITE_PATTERNS[:] = self._旧['PATTERNS']
        SC._EXTRACTORS.clear()
        SC._EXTRACTORS.update(self._旧['EXTRACTORS'])
        SC._EXTRACTOR_ALIASES.clear()
        SC._EXTRACTOR_ALIASES.update(self._旧['ALIASES'])
        self._tmp.cleanup()

    def 写适配器(self, 文件名, 内容, 目录='站点适配'):
        路径 = self.基 / 目录 / 文件名
        路径.write_text(内容, encoding='utf-8')
        return 路径

    @staticmethod
    def 插件(域, 标记, 额外=''):
        return (f"SITE = {{'domain': '{域}'}}\n"
                f"{额外}\n"
                f"def parse_catalog(soup, catalog_url, base_url, **kw):\n"
                f"    return '{标记}'\n")


class Test加载基本行为(_适配器基类):

    def test_目录缺失不崩且注册表为空(self):
        import shutil
        shutil.rmtree(self.基 / '站点适配')
        shutil.rmtree(self.基 / '站点适配_本地')
        SC.load_adapters()
        self.assertEqual(SC.ADAPTERS, {})
        self.assertIsNone(SC.get_adapter('https://sitea.example.com/x'))

    def test_合法插件被登记并命中(self):
        self.写适配器('sitea.py', self.插件(_域A, 'A'))
        SC.load_adapters()
        self.assertIn(_域A, SC.ADAPTERS)
        self.assertTrue(callable(SC.ADAPTERS[_域A]['parse_catalog']))
        self.assertEqual(SC.get_adapter('https://www.sitea.example.com/read/1')['parse_catalog'](None, '', ''),
                         'A', 'get_adapter 应支持子串匹配')
        self.assertIsNotNone(SC.get_site_pattern(f'https://{_域A}/x'),
                             '适配器 SITE 应并入站点表')

    def test_下划线开头文件不加载(self):
        self.写适配器('_模板.py', self.插件('template.example.com', 'T'))
        SC.load_adapters()
        self.assertNotIn('template.example.com', SC.ADAPTERS)

    def test_同域名先到先得(self):
        self.写适配器('a_dup.py', self.插件(_域A, 'A'))
        self.写适配器('b_dup.py', self.插件(_域A, 'B'))
        SC.load_adapters()
        self.assertEqual(len(SC.ADAPTERS), 1, '同域名只应保留一个登记')
        self.assertEqual(SC.ADAPTERS[_域A]['parse_catalog'](None, '', ''), 'A',
                         'sorted 在前的文件应生效')

    def test_仅注册解析器不并入站点表(self):
        self.写适配器('regonly.py', self.插件(_域A, 'A', "SITE['仅注册解析器'] = True"))
        SC.load_adapters()
        self.assertIn(_域A, SC.ADAPTERS, '仍应登记解析器')
        self.assertIsNone(SC.get_site_pattern(f'https://{_域A}/x'),
                          '声明仅注册解析器后不得并入 SITE_PATTERNS')

    def test_坏插件被跳过不影响其他插件(self):
        self.写适配器('a_broken.py', "def parse_catalog(:\n    pass\n")
        self.写适配器('b_good.py', self.插件(_域A, 'A'))
        SC.load_adapters()
        self.assertIn(_域A, SC.ADAPTERS, '语法错误的插件不应拖垮整轮加载')


class Test站点表与提取器(_适配器基类):

    def test_站点表JSON加载(self):
        import json
        (self.基 / '站点适配_本地' / '站点表.json').write_text(
            json.dumps({'sites': [{'domain': _域T, 'pattern': 'html_selector'}]},
                       ensure_ascii=False), encoding='utf-8')
        SC.load_adapters()
        self.assertIsNotNone(SC.get_site_pattern(f'https://{_域T}/x'))

    def test_站点表重复加载不产生重复条目(self):
        import json
        (self.基 / '站点适配_本地' / '站点表.json').write_text(
            json.dumps({'sites': [{'domain': _域T, 'pattern': 'html_selector'}]},
                       ensure_ascii=False), encoding='utf-8')
        SC._load_site_table()
        SC._load_site_table()
        次数 = sum(1 for p in SC.SITE_PATTERNS if p.get('domain') == _域T)
        self.assertEqual(次数, 1, '重载应先移除上次追加的条目再加载')

    def test_提取器与别名注册(self):
        self.写适配器('_提取器.py',
                      "EXTRACTORS = {'机制A': lambda container: '正文'}\n"
                      "ALIASES = {'旧名A': '机制A'}\n",
                      目录='站点适配_本地')
        SC.load_adapters()
        self.assertTrue(SC.提取器已注册('机制A'))
        self.assertEqual(SC.解析提取器名('旧名A'), '机制A')
        self.assertEqual(SC.解析提取器名('未知名'), '未知名', '未知名应原样返回')

    def test_缺提取器文件时查询安全(self):
        SC.load_adapters()
        self.assertFalse(SC.提取器已注册('机制A'))
        self.assertEqual(SC.解析提取器名('机制A'), '机制A')


if __name__ == '__main__':
    unittest.main()
