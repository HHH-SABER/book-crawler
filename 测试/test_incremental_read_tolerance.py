# -*- coding: utf-8 -*-
"""增量读旧文件严格 UTF-8 解码崩溃回归 (2026-10-02 EXE 批量实测事故)。

## 为什么需要

EXE 用远控 incremental=True 批量续跑 40 本书时, 部分站点反复 failed,
错误固定为 'utf-8' codec can't decode bytes in position 61995-61996 /
73997。跨站位置却相同 —— 排查发现根因是**上一次系统蓝屏/硬杀**瞬间,
爬虫正以 encoding='utf-8' 写输出 txt, 把某个 3 字节汉字的最后字节截断
落盘 (实测某产物文件坏点是 `E8 80` 缺第三字节, 另一产物是孤立 `0x80`
续字节); 重启后断点续传以 append 从下一章接着写, 半截字节永久留在文件里。

`_旧章节内容索引` (爬虫.py:6024) 增量搬运旧正文时用
`read_text(encoding='utf-8')` **严格解码**, 且 except 只捕 `OSError`。
`UnicodeDecodeError` 是 `ValueError` 的子类、**不是** `OSError`, 于是异常
冒泡炸掉整个 run_crawl, 任务被标 failed —— 一个残缺字节毁掉一整本书。

## 锁定的契约

1. 旧文件含非法 UTF-8 字节时, `_旧章节内容索引` **不得抛异常**;
   坏字节降级为 U+FFFD, 其余章节正文完整保留 (增量搬运的目的就是保旧正文,
   个别字符损坏远优于整本丢失 → 任务崩溃)。
2. 正常 UTF-8 文件的索引往返行为不变 (回归保护, 确保没改坏正常路径)。
3. 文件不存在仍返回 {} (OSError 分支保留)。
4. 空文件返回 {}。

所有读写在 tempfile 临时目录, tearDown 清理, 不联网, 不触碰项目产物。
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '源码'))


def _造蜘蛛():
    from 爬虫 import NovelSpider
    return NovelSpider('https://example.com')


class Test增量读旧文件容错(unittest.TestCase):
    """#5: _旧章节内容索引 遇坏字节旧文件必须容错, 不得炸整任务"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='incr_read_')
        self.spider = _造蜘蛛()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _写坏字节文件(self):
        """第一章正文结尾写入被截断的多字节汉字 (E8 80 缺尾), 再接第二章"""
        p = os.path.join(self.tmp, '坏书.txt')
        with open(p, 'wb') as f:
            f.write('## 第一章\n'.encode('utf-8'))
            f.write('  两个孩子望向门口的'.encode('utf-8'))
            f.write(b'\xe8\x80')                    # 半截汉字 → 非法字节
            f.write('\n## 第二章\n正文乙完整内容\n'.encode('utf-8'))
        return p

    def test_坏字节文件不抛异常(self):
        p = self._写坏字节文件()
        # 严格解码必炸的前置确认 (证明这份 fixture 确实含非法字节)
        with self.assertRaises(UnicodeDecodeError):
            Path(p).read_bytes().decode('utf-8')
        # 被测函数不得把该异常冒泡出来
        idx = self.spider._旧章节内容索引(p)
        self.assertIsInstance(idx, dict)

    def test_坏字节文件保留其余章节(self):
        p = self._写坏字节文件()
        idx = self.spider._旧章节内容索引(p)
        self.assertIn('第一章', idx)
        self.assertIn('第二章', idx)
        # 坏字节之后的第二章正文必须完整, 不受前面残缺字节影响
        self.assertEqual(idx['第二章'], '正文乙完整内容')

    def test_正常文件往返不变(self):
        p = os.path.join(self.tmp, '正常.txt')
        Path(p).write_text(
            '## 甲\n内容A\n## 乙\n内容B\n', encoding='utf-8')
        idx = self.spider._旧章节内容索引(p)
        self.assertEqual(idx.get('甲'), '内容A')
        self.assertEqual(idx.get('乙'), '内容B')

    def test_文件不存在返回空(self):
        idx = self.spider._旧章节内容索引(os.path.join(self.tmp, '无.txt'))
        self.assertEqual(idx, {})

    def test_空文件返回空(self):
        p = os.path.join(self.tmp, '空.txt')
        Path(p).write_text('', encoding='utf-8')
        self.assertEqual(self.spider._旧章节内容索引(p), {})


if __name__ == '__main__':
    unittest.main(verbosity=2)
