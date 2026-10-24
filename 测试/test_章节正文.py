# -*- coding: utf-8 -*-
"""外部适配器正文提取封装的用例（Wave2 第三块）。"""
import pathlib
import sys
import unittest
from unittest import mock

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '源码'))
sys.path.insert(0, str(_PROJECT_ROOT / '测试'))

import _沙箱  # noqa: E402,F401  状态根沙箱
import sites_config  # noqa: E402
import 章节正文  # noqa: E402

URL = 'https://s.example.com/read/1/10.html'


def _取页面():
    return 'SOUP'


class 用适配器提取用例(unittest.TestCase):
    def test_无适配器返回None(self):
        with mock.patch.object(sites_config, 'get_adapter', lambda u: None):
            self.assertIsNone(章节正文.用适配器提取(URL, 0, 'https://s.example.com', _取页面))

    def test_适配器无钩子返回None(self):
        with mock.patch.object(sites_config, 'get_adapter', lambda u: {'source': 'x'}):
            self.assertIsNone(章节正文.用适配器提取(URL, 0, 'https://s.example.com', _取页面))

    def test_正常提取并透传参数(self):
        收到 = {}

        def 钩子(soup, url, base, page_index=None):
            收到.update(soup=soup, url=url, base=base, page_index=page_index)
            return '正文内容'
        适配器 = {'source': 'siteX', 'extract_content': 钩子}
        with mock.patch.object(sites_config, 'get_adapter', lambda u: 适配器):
            got = 章节正文.用适配器提取(URL, 3, 'https://s.example.com', _取页面)
        self.assertEqual(got, '正文内容')
        self.assertEqual(收到, {'soup': 'SOUP', 'url': URL,
                                'base': 'https://s.example.com', 'page_index': 3})

    def test_钩子抛异常时退回None且不炸(self):
        def 钩子(*a, **k):
            raise RuntimeError('插件缺陷')
        with mock.patch.object(sites_config, 'get_adapter',
                               lambda u: {'source': 'siteX', 'extract_content': 钩子}):
            self.assertIsNone(章节正文.用适配器提取(URL, 0, 'https://s.example.com', _取页面))

    def test_取适配器抛异常时退回None(self):
        def _炸(u):
            raise RuntimeError('注册表坏了')
        with mock.patch.object(sites_config, 'get_adapter', _炸):
            self.assertIsNone(章节正文.用适配器提取(URL, 0, 'https://s.example.com', _取页面))

    def test_钩子返回空串时原样返回(self):
        """空串是"命中了但没抽到"，与 None（没命中）区分开，由调用方判长度。"""
        with mock.patch.object(sites_config, 'get_adapter',
                               lambda u: {'source': 'x', 'extract_content': lambda *a, **k: ''}):
            self.assertEqual(章节正文.用适配器提取(URL, 0, 'https://s.example.com', _取页面), '')

    def test_留痕日志含适配器来源与页码(self):
        with mock.patch.object(sites_config, 'get_adapter',
                               lambda u: {'source': 'siteX',
                                          'extract_content': lambda *a, **k: '正文'}):
            with self.assertLogs('小说爬虫', level='INFO') as 记录:
                章节正文.用适配器提取(URL, 4, 'https://s.example.com', _取页面)
        文本 = '\n'.join(记录.output)
        self.assertIn('siteX', 文本)
        self.assertIn('第5页', 文本)


if __name__ == '__main__':
    unittest.main()
