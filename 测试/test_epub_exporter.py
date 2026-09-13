# -*- coding: utf-8 -*-
"""epub_exporter.py 离线回归测试 (补齐 M13 测试盲区: EPUB 导出零单测)。

覆盖 txt 章节解析 (parse_txt_chapters)、EPUB 导出往返 (txt_to_epub)、
以及边界失败路径 (缺文件 / 空章节 / ebooklib 缺失)。

## 章节格式契约 (与爬虫 txt 输出一致)

爬虫产出的 txt 每章以 "## " 开头, 其后为正文 (每非空行一段)。
EPUB 导出依赖此约定: parse_txt_chapters 按 "## " 切章。

## 实测验证过的关键点 (设计探针确认, 改动 epub_exporter 前必读)

- **导出的 EPUB 读回时, document 项数 = 章节数 + 1**: 因 `book.spine=['nav']+items`,
  nav 导航项也是一个 document item。断言章节数时**必须排除 nav**, 否则假阳性。
- **中文标题/正文经 html.escape 转义**写入 xhtml, 读回时 ebooklib 已还原, 故断言
  原中文而非转义串。
- ebooklib 在本环境可用 (is_available()=True), 故走完整导出+读回往返;
  另用 mock 把 `_ebooklib_ok` 置 False 验证"未安装时优雅返回 None"分支。

所有写文件在 tempfile 临时目录进行, tearDown 清理, 不触碰项目目录, 不联网, 不改源码。
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from ebooklib import ITEM_DOCUMENT     # ebooklib 顶层常量 (非 epub 子模块)
except Exception:                          # ebooklib 未装时占位; 导出往返测试由 skipUnless 跳过
    ITEM_DOCUMENT = 9

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '源码'))

import epub_exporter as ex  # noqa: E402


class TestParseTxtChapters(unittest.TestCase):
    """parse_txt_chapters: txt -> [(标题, 正文), ...]"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='epub_test_')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _写txt(self, content, name='book.txt'):
        p = os.path.join(self.tmp, name)
        with open(p, 'w', encoding='utf-8') as f:
            f.write(content)
        return p

    def test_多章解析(self):
        p = self._写txt('## 第一章 开端\n第一段。\n第二段。\n\n## 第二章 转折\n第二段正文。\n')
        chapters = ex.parse_txt_chapters(p)
        self.assertEqual(2, len(chapters))
        self.assertEqual('第一章 开端', chapters[0][0])
        self.assertIn('第一段。', chapters[0][1])
        self.assertEqual('第二章 转折', chapters[1][0])

    def test_无章节标记返回空(self):
        p = self._写txt('这是一段没有 ## 标记的纯文本。\n再一行。\n')
        self.assertEqual([], ex.parse_txt_chapters(p))

    def test_文件不存在返回空(self):
        self.assertEqual([], ex.parse_txt_chapters(os.path.join(self.tmp, '不存在.txt')))

    def test_正文空行被保留在章节内(self):
        p = self._写txt('## 第一章\n正文一\n\n正文二\n')
        chapters = ex.parse_txt_chapters(p)
        self.assertEqual(1, len(chapters))
        self.assertIn('正文一', chapters[0][1])
        self.assertIn('正文二', chapters[0][1])


class TestParagraphs(unittest.TestCase):
    """_paragraphs: 正文 -> 段落列表 (每非空行一段)"""

    def test_过滤空行并strip(self):
        self.assertEqual(['段落一', '段落二'],
                         ex._paragraphs('  段落一  \n\n\n  段落二  \n'))

    def test_全空返回空列表(self):
        self.assertEqual([], ex._paragraphs('\n\n   \n'))


@unittest.skipUnless(ex.is_available(), 'ebooklib 未安装则跳过导出往返测试')
class TestTxtToEpub导出往返(unittest.TestCase):
    """txt_to_epub: 完整导出 + ebooklib 读回验证 (探针确认往返可行)"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='epub_out_')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _造多章txt(self):
        p = os.path.join(self.tmp, '测试书.txt')
        with open(p, 'w', encoding='utf-8') as f:
            f.write('## 第一章 开端\n这是第一段。\n这是第二段。\n\n'
                    '## 第二章 转折\n第二章正文内容。\n\n'
                    '## 第三章 结局\n第三章正文内容。\n')
        return p

    def test_导出返回存在的路径(self):
        txt = self._造多章txt()
        ep = ex.txt_to_epub(txt, title='测试书', author='测试者')
        self.assertIsNotNone(ep)
        self.assertTrue(os.path.isfile(ep))
        self.assertTrue(ep.endswith('.epub'))

    def test_默认输出路径为同名epub(self):
        txt = self._造多章txt()
        ep = ex.txt_to_epub(txt)
        self.assertEqual(os.path.splitext(txt)[0] + '.epub', ep)

    def test_读回章节数排除nav(self):
        """关键: document 项数 = 章节数 + 1 (nav), 断言时排除 nav"""
        from ebooklib import epub as e
        txt = self._造多章txt()
        ep = ex.txt_to_epub(txt, title='测试书')
        book = e.read_epub(ep)
        doc_items = [i for i in book.get_items() if i.get_type() == ITEM_DOCUMENT]
        # 3 章正文 + 1 nav = 4 个 document item
        self.assertEqual(4, len(doc_items), '3章+nav 应有4个文档项')

    def test_读回标题与语言(self):
        from ebooklib import epub as e
        txt = self._造多章txt()
        ep = ex.txt_to_epub(txt, title='我的测试小说', author='张三')
        book = e.read_epub(ep)
        meta_title = book.get_metadata('DC', 'title')
        self.assertTrue(meta_title)
        self.assertEqual('我的测试小说', meta_title[0][0])

    def test_中文正文完整写入(self):
        """章节中文正文应能在 xhtml 内容中找到 (html.escape 不破坏中文)"""
        from ebooklib import epub as e
        txt = self._造多章txt()
        ep = ex.txt_to_epub(txt, title='测试书')
        book = e.read_epub(ep)
        all_content = b''.join(
            i.get_content() for i in book.get_items()
            if i.get_type() == ITEM_DOCUMENT
        ).decode('utf-8', errors='replace')
        self.assertIn('这是第一段', all_content)
        self.assertIn('第三章正文内容', all_content)

    def test_title缺省取文件名(self):
        from ebooklib import epub as e
        txt = self._造多章txt()   # 文件名 = 测试书.txt
        ep = ex.txt_to_epub(txt)  # 不传 title
        book = e.read_epub(ep)
        self.assertEqual('测试书', book.get_metadata('DC', 'title')[0][0])

    def test_特殊字符标题被转义(self):
        """标题含 <>& 时 html.escape 转义, 导出仍成功且读回原文"""
        from ebooklib import epub as e
        p = os.path.join(self.tmp, 'b.txt')
        with open(p, 'w', encoding='utf-8') as f:
            f.write('## 第一章 <危险> & "引号"\n正文内容测试。\n')
        ep = ex.txt_to_epub(p, title='书名<>&测试')
        self.assertIsNotNone(ep)
        book = e.read_epub(ep)
        self.assertEqual('书名<>&测试', book.get_metadata('DC', 'title')[0][0])


class TestTxtToEpub失败路径(unittest.TestCase):
    """txt_to_epub 的优雅失败 (绝不抛异常影响主流程)"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='epub_fail_')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_源文件不存在返回None(self):
        self.assertIsNone(ex.txt_to_epub(os.path.join(self.tmp, '不存在.txt')))

    def test_无章节txt返回None(self):
        p = os.path.join(self.tmp, '空书.txt')
        with open(p, 'w', encoding='utf-8') as f:
            f.write('没有任何 ## 章节标记的内容。\n')
        self.assertIsNone(ex.txt_to_epub(p))

    def test_ebooklib缺失时返回None(self):
        """mock _ebooklib_ok=False 验证"未安装则跳过"分支 (合规: 不影响主流程)"""
        p = os.path.join(self.tmp, '书.txt')
        with open(p, 'w', encoding='utf-8') as f:
            f.write('## 第一章\n正文。\n')
        with mock.patch.object(ex, '_ebooklib_ok', False):
            self.assertIsNone(ex.txt_to_epub(p))

    def test_is_available返回bool(self):
        self.assertIsInstance(ex.is_available(), bool)


if __name__ == '__main__':
    unittest.main(verbosity=2)
