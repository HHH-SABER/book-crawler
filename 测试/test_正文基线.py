# -*- coding: utf-8 -*-
"""正文链路基线的用例（S1 第三步）。

重点不只是"能跑"，而是**红线**：基线只存指标与哈希，**绝不把正文写进 JSON**。
"""
import json
import pathlib
import sys
import tempfile
import unittest

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '源码'))
sys.path.insert(0, str(_PROJECT_ROOT / '脚本'))
sys.path.insert(0, str(_PROJECT_ROOT / '测试'))

import _沙箱  # noqa: E402,F401  状态根沙箱
import 正文基线  # noqa: E402

_内联样本 = (
    '<html><body>'
    '<h1>第一章</h1>'
    '<div id="content"><p>' + '正文文字反复出现用于长度判定。' * 40 + '</p>'
    '<p>' + '第二段同样足够长以便通过筛选。' * 40 + '</p></div>'
    '</body></html>'
)


class 快照用例(unittest.TestCase):
    def setUp(self):
        临时 = tempfile.TemporaryDirectory()
        self.addCleanup(临时.cleanup)
        self.根 = pathlib.Path(临时.name)
        (self.根 / 'sample.html').write_text(_内联样本, encoding='utf-8')

    def test_返回纯指标字段(self):
        指标 = 正文基线.快照('sample.html', 'https://x.example.com/1.html', self.根)
        期望 = {'抽取字数', '抽取段落数', '抽取哈希', '清洗字数', '清洗哈希',
                '是否为空', 'html长度'}
        self.assertEqual(set(指标), 期望)
        self.assertGreater(指标['抽取字数'], 0, '简单容器应能抽出正文')
        self.assertFalse(指标['是否为空'])

    def test_不含任何正文文本(self):
        """红线：基线里不能出现正文/首尾文字，只能是数字与哈希。"""
        指标 = 正文基线.快照('sample.html', 'https://x.example.com/1.html', self.根)
        值串 = json.dumps(指标, ensure_ascii=False)
        self.assertNotIn('正文文字反复出现', 值串)
        self.assertNotIn('第二段同样足够长', 值串)

    def test_哈希稳定且对改动敏感(self):
        a = 正文基线.快照('sample.html', 'https://x.example.com/1.html', self.根)
        b = 正文基线.快照('sample.html', 'https://x.example.com/1.html', self.根)
        self.assertEqual(a['抽取哈希'], b['抽取哈希'])
        # 改一个字 ⇒ 哈希必须变（否则基线抓不住行为变化）
        # 必须改**正文容器内**的文字：h1 标题不参与正文抽取，改它哈希当然不变
        (self.根 / 'sample.html').write_text(
            _内联样本.replace('第二段同样足够长', '第二段改过一个字足够长'), encoding='utf-8')
        c = 正文基线.快照('sample.html', 'https://x.example.com/1.html', self.根)
        self.assertNotEqual(a['抽取哈希'], c['抽取哈希'])


class 跑全部用例(unittest.TestCase):
    def test_空目录安全返回空(self):
        临时 = tempfile.TemporaryDirectory()
        self.addCleanup(临时.cleanup)
        self.assertEqual(正文基线.跑全部(临时.name), {})

    def test_只跑存在的样本(self):
        临时 = tempfile.TemporaryDirectory()
        self.addCleanup(临时.cleanup)
        根 = pathlib.Path(临时.name)
        (根 / 正文基线.正文样本[0][0]).write_text(_内联样本, encoding='utf-8')
        结果 = 正文基线.跑全部(根)
        self.assertIn(正文基线.正文样本[0][0], 结果)


class 库内基线用例(unittest.TestCase):
    """入库的 文档/正文基线.json 必须"只有指标没有正文"。"""

    def test_入库基线只含指标(self):
        p = _PROJECT_ROOT / '文档' / '正文基线.json'
        if not p.is_file():
            self.skipTest('本机未生成 正文基线.json（公开形态正常）')
        d = json.loads(p.read_text(encoding='utf-8'))
        for 文件, 指标 in d.items():
            self.assertEqual(set(指标), {'抽取字数', '抽取段落数', '抽取哈希',
                                         '清洗字数', '清洗哈希', '是否为空', 'html长度'},
                             f'{文件} 字段集不符')
        self.assertNotIn('正文文字', json.dumps(d, ensure_ascii=False))


if __name__ == '__main__':
    unittest.main()
