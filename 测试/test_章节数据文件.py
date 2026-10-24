# -*- coding: utf-8 -*-
"""章节数据文件纯逻辑的用例（Wave2 第二块）。

钉住两处最易错的细节：首行元信息剥离条件、复合指纹的判重口径。
"""
import pathlib
import sys
import unittest

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '源码'))
sys.path.insert(0, str(_PROJECT_ROOT / '测试'))

import _沙箱  # noqa: E402,F401  状态根沙箱
import 章节数据文件 as 数  # noqa: E402


class 整理数据正文用例(unittest.TestCase):
    def test_首行含第字当标题丢掉(self):
        self.assertEqual(数.整理数据正文('第一章 起风了\n正文一\n正文二'), '正文一\n正文二')

    def test_首行含作者当标题丢掉(self):
        self.assertEqual(数.整理数据正文('作者：某某\n正文一'), '正文一')

    def test_首行含星号当标题丢掉(self):
        self.assertEqual(数.整理数据正文('★★★ 本书由…整理\n正文一'), '正文一')
        self.assertEqual(数.整理数据正文('☆☆☆\n正文一'), '正文一')

    def test_首行是正文时不能删(self):
        """反例保护：剥离条件写宽了会把正文首段当标题删掉。"""
        self.assertEqual(数.整理数据正文('风从北边吹来，他抬头看天。\n第二行'), '风从北边吹来，他抬头看天。\n第二行')

    def test_统计行被剔除(self):
        文本 = '作者：某某 字数：3000\n正文一\n字数：3000\n正文二'
        self.assertEqual(数.整理数据正文(文本), '正文一\n正文二')

    def test_空行剔除且保留段落顺序(self):
        self.assertEqual(数.整理数据正文('正文一\n\n\n正文二\n'), '正文一\n正文二')

    def test_空输入返回空串(self):
        self.assertEqual(数.整理数据正文(''), '')
        self.assertEqual(数.整理数据正文(None), '')


class 页指纹用例(unittest.TestCase):
    def test_同正文同指纹(self):
        self.assertEqual(数.页指纹('一段正文' * 50), 数.页指纹('一段正文' * 50))

    def test_开头相同但长度不同必须区分(self):
        """分页常见"页首固定模板"——只看开头会误判成重复页，所以复合了长度。"""
        a = '固定页首模板' * 50            # 长度 300 > 200，前 200 字符才真正相同
        b = a + '后续多出来的内容'
        self.assertEqual(a[:200], b[:200])
        self.assertNotEqual(数.页指纹(a), 数.页指纹(b))

    def test_长度相同但200字符后不同视为相同(self):
        """原设计的已知取舍：只取前 200 字符 + 长度，超出部分的差异不计入指纹。"""
        a = 'x' * 200 + 'A' * 100
        b = 'x' * 200 + 'B' * 100
        self.assertEqual(数.页指纹(a), 数.页指纹(b))

    def test_指纹长度固定16(self):
        self.assertEqual(len(数.页指纹('abc')), 16)
        self.assertEqual(len(数.页指纹('')), 16)


if __name__ == '__main__':
    unittest.main()
