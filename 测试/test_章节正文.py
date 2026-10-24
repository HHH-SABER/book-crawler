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


class 该用站点提取器用例(unittest.TestCase):
    def test_无配置返回False(self):
        self.assertFalse(章节正文.该用站点提取器(None))

    def test_非html_selector返回False(self):
        with mock.patch.object(sites_config, 'PATTERN_HTML_SELECTOR', 'html_selector'):
            self.assertFalse(章节正文.该用站点提取器({'pattern': 'datafile'}))

    def test_未注册提取器返回False(self):
        with mock.patch.object(sites_config, 'PATTERN_HTML_SELECTOR', 'html_selector'), \
             mock.patch.object(sites_config, '解析提取器名', lambda n: n), \
             mock.patch.object(sites_config, '提取器已注册', lambda n: False):
            self.assertFalse(章节正文.该用站点提取器(
                {'pattern': 'html_selector', 'content_extractor': 'siteX'}))

    def test_已注册返回True(self):
        见过 = {}
        with mock.patch.object(sites_config, 'PATTERN_HTML_SELECTOR', 'html_selector'), \
             mock.patch.object(sites_config, '解析提取器名',
                               lambda n: 见过.setdefault('名', n) or n), \
             mock.patch.object(sites_config, '提取器已注册', lambda n: True):
            self.assertTrue(章节正文.该用站点提取器(
                {'pattern': 'html_selector', 'content_extractor': 'siteX'}))
        self.assertEqual(见过['名'], 'siteX')

    def test_注册判定抛异常按不可用处理(self):
        def _炸(n):
            raise RuntimeError('注册表坏')
        with mock.patch.object(sites_config, 'PATTERN_HTML_SELECTOR', 'html_selector'), \
             mock.patch.object(sites_config, '解析提取器名', lambda n: n), \
             mock.patch.object(sites_config, '提取器已注册', _炸):
            self.assertFalse(章节正文.该用站点提取器(
                {'pattern': 'html_selector', 'content_extractor': 'x'}))


class 用站点提取器用例(unittest.TestCase):
    def test_透传结果与参数(self):
        收到 = {}

        def 抽(session, url, pattern, base, headers, 取JS):
            收到.update(url=url, base=base, 取JS=取JS)
            return '正文', True
        with mock.patch.object(sites_config, 'extract_content', 抽):
            正文, 成功 = 章节正文.用站点提取器(
                'S', URL, {'pattern': 'html_selector'}, 'https://s.example.com',
                {'h': 1}, 'JSFUNC')
        self.assertEqual((正文, 成功), ('正文', True))
        self.assertEqual(收到['url'], URL)
        self.assertEqual(收到['取JS'], 'JSFUNC')

    def test_异常时返回空且留痕(self):
        def 炸(*a, **k):
            raise RuntimeError('配置缺陷')
        with mock.patch.object(sites_config, 'extract_content', 炸):
            with self.assertLogs('小说爬虫', level='INFO') as 记录:
                正文, 成功 = 章节正文.用站点提取器(
                    'S', URL, {}, 'https://s.example.com', {}, 'JS')
        self.assertEqual((正文, 成功), ('', False))
        self.assertIn('回退通用检测', '\n'.join(记录.output))


class 结算一页用例(unittest.TestCase):
    def test_首页不重复且带追加片段(self):
        正文 = '第一页正文内容'
        重复, 指纹, 追加 = 章节正文.结算一页(正文, None)
        self.assertFalse(重复)
        self.assertEqual(指纹, 章节正文.页指纹(正文))
        self.assertEqual(追加, 正文 + '\n\n')

    def test_与上一页相同则判重复且不追加(self):
        正文 = '同一页内容'
        上 = 章节正文.页指纹(正文)
        重复, 指纹, 追加 = 章节正文.结算一页(正文, 上)
        self.assertTrue(重复)
        self.assertEqual(指纹, 上, '重复时指纹应保持不变')
        self.assertEqual(追加, '')

    def test_内容不同则判不重复(self):
        上 = 章节正文.页指纹('上一页')
        重复, 指纹, 追加 = 章节正文.结算一页('这一页', 上)
        self.assertFalse(重复)
        self.assertNotEqual(指纹, 上)
        self.assertEqual(追加, '这一页\n\n')

    def test_空文本也能安全结算(self):
        重复, 指纹, 追加 = 章节正文.结算一页('', None)
        self.assertFalse(重复)
        self.assertEqual(len(指纹), 16)
        self.assertEqual(追加, '\n\n')
