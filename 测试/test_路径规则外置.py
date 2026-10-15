# -*- coding: utf-8 -*-
"""站点路径规则外置 (Wave 2 批次1) 的门禁用例。

**机制**：`_resolve_novel_paths` 先问外部适配器钩子 `novel_paths(catalog_url)`；
命中即用其返回值，未命中走**通用多模式推断**（8 个模式）。
公开侧因此**不再有任何站点分支**（站点专属规则放不入库的 `站点适配_本地/*.py`）。

本文件**只用占位域名**（`*.example.com`）与**假适配器**，不含真实站点信息。
"""
import ast
import sys
import unittest
from pathlib import Path
from unittest import mock

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

import 爬虫 as C                # noqa: E402

_源码 = (_根 / '源码' / '爬虫.py').read_text(encoding='utf-8')


def _函数源(名: str) -> str:
    for n in ast.walk(ast.parse(_源码)):
        if isinstance(n, ast.FunctionDef) and n.name == 名:
            return ast.get_source_segment(_源码, n) or ''
    return ''


class Test通用回退(unittest.TestCase):
    """没命中适配器时，通用 8 模式必须照旧工作（占位域名）。"""

    def _解(self, url: str):
        # 强制"无适配器"：确保通用分支被走到
        with mock.patch('sites_config.get_adapter', return_value=None):
            return C._resolve_novel_paths(url)

    def test_模式1_下划线书号(self):
        self.assertEqual(self._解('https://site1.example.com/97_97855/'),
                         ('/97_97855/', '/97_97855/'))

    def test_模式2_斜杠数字点html(self):
        路径, alt = self._解('https://site2.example.com/books/301597.html')
        self.assertEqual(路径, '/books/301597/')
        self.assertEqual(alt, 路径)

    def test_模式5_index分页目录(self):
        self.assertEqual(self._解('https://site5.example.com/Ab12/indexlist.html')[0],
                         '/Ab12/')

    def test_无法识别时返回空(self):
        self.assertEqual(self._解('https://site9.example.com/'),
                         ('', ''))


class Test适配器钩子(unittest.TestCase):
    """站点专属规则必须由适配器提供，且优先级高于通用推断。"""

    def test_命中钩子时以适配器为准(self):
        假 = {'source': 'fake.py',
              'novel_paths': lambda u: ('/special/1/', '/special/1')}
        with mock.patch('sites_config.get_adapter', return_value=假):
            结果 = C._resolve_novel_paths('https://site7.example.com/whatever/')
        self.assertEqual(结果, ('/special/1/', '/special/1'))

    def test_钩子返回None时回退通用(self):
        假 = {'source': 'fake.py', 'novel_paths': lambda u: None}
        with mock.patch('sites_config.get_adapter', return_value=假):
            结果 = C._resolve_novel_paths('https://site1.example.com/97_97855/')
        self.assertEqual(结果, ('/97_97855/', '/97_97855/'))

    def test_钩子抛异常时回退且不崩(self):
        def _炸(_u):
            raise RuntimeError('boom')
        假 = {'source': 'fake.py', 'novel_paths': _炸}
        with mock.patch('sites_config.get_adapter', return_value=假):
            结果 = C._resolve_novel_paths('https://site1.example.com/97_97855/')
        self.assertEqual(结果, ('/97_97855/', '/97_97855/'))

    def test_适配器无该钩子时回退通用(self):
        假 = {'source': 'fake.py', 'parse_catalog': lambda *a, **k: None}
        with mock.patch('sites_config.get_adapter', return_value=假):
            结果 = C._resolve_novel_paths('https://site1.example.com/97_97855/')
        self.assertEqual(结果, ('/97_97855/', '/97_97855/'))


class Test结构护栏(unittest.TestCase):
    """防回归：公开侧函数里**不得**再出现站点特判；加载器必须登记该钩子。"""

    def test_函数内无站点特判(self):
        段 = _函数源('_resolve_novel_paths')
        self.assertTrue(段, '找不到 _resolve_novel_paths')
        self.assertNotIn('站点匹配(', 段,
                         '公开侧路径函数不应再含站点特判 (应走 novel_paths 适配器钩子)')
        self.assertIn('novel_paths', 段, '函数必须咨询适配器 novel_paths 钩子')

    def test_加载器登记了novel_paths钩子(self):
        配 = (_根 / '源码' / 'sites_config.py').read_text(encoding='utf-8')
        self.assertIn("'novel_paths'", 配, 'sites_config 加载器必须登记 novel_paths 钩子')
        # 契约文档也要写（避免钩子只存在于代码里、适配器作者看不到）
        self.assertIn('novel_paths(catalog_url)', 配, 'load_adapters 文档应说明该钩子')


if __name__ == '__main__':
    unittest.main(verbosity=2)
