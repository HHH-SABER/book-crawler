# -*- coding: utf-8 -*-
"""字符集探测回归 (P8-C13, 2026-10-24)。

覆盖规格验收 "各 1 个离线用例" 并加码:
  ① 核心痛点场景: 声明 utf-8 实际 GBK/Big5 → 必须探测出真编码;
  ② 反向守护 (防误杀): 合法 UTF-8 中文**不得**被判成 GBK/Big5;
  ③ 声明反压: 声明 GBK 实际 UTF-8 中文 → 信 UTF-8 证据不信声明;
  ④ BOM/meta/纯 ASCII/空/随机字节 边界;
  ⑤ 解码往返保真 (探测→解码→与原串一致)。
"""
import sys
import unittest
from pathlib import Path

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

import 字符集探测 as D   # noqa: E402

_样文 = '第一章 测试内容，这是一段中文小说正文。'
_样文繁 = '第一章 測試內容，這是一段中文小說正文。'
_谎报页 = ('<html><head><meta charset="utf-8"></head>'
         '<body><p>' + _样文 + '</p></body></html>')


class Test探测(unittest.TestCase):

    def test_合法UTF8中文不误判(self):
        """反向守护: UTF-8 中文必须是 strict utf-8, 绝不滑到统计分支。"""
        数据 = _样文.encode('utf-8')
        编码, 依据 = D.探测(数据)
        self.assertEqual(编码, 'utf-8')
        self.assertEqual(依据, 'strict')

    def test_GBK无声明走统计(self):
        编码, 依据 = D.探测(_样文.encode('gb18030'))
        self.assertEqual(编码, 'gb18030')
        self.assertEqual(依据, 'statistic')

    def test_Big5走统计(self):
        编码, 依据 = D.探测(_样文繁.encode('big5'))
        self.assertEqual(编码, 'big5')
        self.assertEqual(依据, 'statistic')

    def test_谎报utf8的GBK页面(self):
        """核心痛点: 页面声明 utf-8 但字节是 GBK → 必须纠偏。"""
        html = ('<html><head><meta charset="utf-8">'
                f'<title>t</title></head><body>{_样文}</body></html>').encode('gb18030')
        编码, 依据 = D.探测(html)
        self.assertEqual(编码, 'gb18030')
        self.assertEqual(依据, 'statistic')

    def test_谎报GBK的UTF8页面(self):
        """声明反压: 声明 gb2312 但字节是合法 UTF-8 中文 → 信 UTF-8。"""
        html = ('<html><head><meta charset="gb2312">'
                f'<title>t</title></head><body>{_样文}</body></html>').encode('utf-8')
        编码, 依据 = D.探测(html)
        self.assertEqual(编码, 'utf-8')

    def test_meta声明正确时采纳(self):
        """声明 GBK 且确是 GBK 字节 → meta 采纳 (不必落到统计)。"""
        html = ('<html><head><meta charset="gb2312">'
                f'<title>t</title></head><body>{_样文}</body></html>').encode('gb18030')
        编码, 依据 = D.探测(html)
        self.assertEqual(编码, 'gb18030')
        self.assertEqual(依据, 'meta')

    def test_BOM优先于一切(self):
        for 数据, 期望 in (
            ('utf-8-sig 中文'.encode('utf-8-sig'), 'utf-8-sig'),
            ('utf-16 中文'.encode('utf-16'), 'utf-16'),
        ):
            with self.subTest(期望):
                编码, 依据 = D.探测(数据)
                self.assertEqual(编码, 期望)
                self.assertEqual(依据, 'bom')

    def test_纯ASCII归utf8(self):
        编码, 依据 = D.探测(b'<html><body>plain ascii only</body></html>')
        self.assertEqual(编码, 'utf-8')

    def test_空与随机字节不硬猜(self):
        self.assertEqual(D.探测(b''), ('utf-8', 'default'))
        编码, 依据 = D.探测(bytes(range(256)) * 4)
        self.assertEqual(依据, 'default')
        self.assertEqual(编码, 'utf-8')


class Test解码往返(unittest.TestCase):

    def test_各编码往返保真(self):
        for 文本, 编码 in ((_样文, 'utf-8'), (_样文, 'gb18030'), (_样文繁, 'big5')):
            with self.subTest(编码):
                解出, _依据 = D.解码(文本.encode(编码))
                self.assertEqual(解出, 文本)

    def test_谎报页面解码出正确正文(self):
        html = ('<html><head><meta charset="utf-8"></head><body>'
                f'<p>{_样文}</p></body></html>').encode('gb18030')
        文本, 依据 = D.解码(html)
        self.assertIn(_样文, 文本)
        self.assertEqual(依据, 'statistic')

    def test_空输入(self):
        self.assertEqual(D.解码(b''), ('', 'default'))


class Test引擎接入(unittest.TestCase):
    """引擎响应 apparent_encoding → 纠偏解码 (集成: P8-C13 的真实消费点)。"""

    def _响应(self, 数据: bytes):
        from 请求引擎 import 引擎响应
        return 引擎响应(status_code=200, headers={}, content=数据,
                       url='http://example.invalid/')

    def test_谎报页经引擎纠偏(self):
        r = self._响应(_谎报页.encode('gb18030'))
        self.assertEqual(r.apparent_encoding, 'gb18030')
        r.encoding = r.apparent_encoding
        self.assertIn(_样文, r.text, '纠偏后必须解出正确正文')

    def test_正常UTF8页不受影响(self):
        r = self._响应(_谎报页.encode('utf-8'))
        self.assertEqual(r.apparent_encoding, 'utf-8')
        r.encoding = r.apparent_encoding
        self.assertIn(_样文, r.text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
