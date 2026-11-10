# -*- coding: utf-8 -*-
"""统一导出层（漫画导出）的离线用例：cbz / pdf / pages 三种格式行为一致。

用 PIL 生成**真实图片**（不是假字节），这样 PDF 编码路径也被真正执行。
"""
import random
import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / '源码'))

import 漫画导出 as E   # noqa: E402


def _造书(根: Path, 话数: int, 每话页: int = 2) -> Path:
    """造一本多话的书：每页是 20x30 的真 PNG（体积 >1KB 需靠内容, 用噪点填充）。"""
    书 = 根 / '示例漫画'
    书.mkdir(parents=True)
    for i in range(1, 话数 + 1):
        话 = 书 / f'{i:03d}_第{i}话'
        话.mkdir()
        for p in range(1, 每话页 + 1):
            # 噪点图: 纯色 PNG 会被压到 1KB 以下、被统一层当坏图过滤
            rnd = random.Random(i * 1000 + p)
            im = Image.frombytes('RGB', (64, 96), rnd.randbytes(64 * 96 * 3))
            im.save(话 / f'{p:04d}.png')
            im.close()
    return 书


class Test格式校验(unittest.TestCase):

    def test_未知格式报错(self):
        with tempfile.TemporaryDirectory() as tmp:
            书 = _造书(Path(tmp), 2)
            with self.assertRaises(ValueError):
                E.导出(书, 格式='epub')

    def test_未知单位报错(self):
        with tempfile.TemporaryDirectory() as tmp:
            书 = _造书(Path(tmp), 2)
            with self.assertRaises(ValueError):
                E.导出(书, 格式='cbz', 单位='册')

    def test_空目录报错(self):
        with tempfile.TemporaryDirectory() as tmp:
            空 = Path(tmp) / '空'
            空.mkdir()
            with self.assertRaises(ValueError):
                E.导出(空)

    def test_目录不存在报错(self):
        with self.assertRaises(FileNotFoundError):
            E.导出(Path(tempfile.gettempdir()) / '__不存在__')

    def test_小于1KB的坏图被过滤(self):
        with tempfile.TemporaryDirectory() as tmp:
            书 = _造书(Path(tmp), 1, 每话页=1)
            话 = next(d for d in 书.iterdir() if d.is_dir())
            (话 / '0002.png').write_bytes(b'x' * 10)     # 截断文件
            结果 = E.导出(书, 格式='cbz', 单位='话')
            with zipfile.ZipFile(结果['册s'][0]) as z:
                self.assertEqual(z.namelist(), ['0001.png'], '坏图不应进包')


class TestCBZ(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.根 = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_卷级_分层且六卷(self):
        书 = _造书(self.根, 12, 每话页=1)
        结果 = E.导出(书, 格式='cbz', 单位='卷', 卷界=[4, 8, 12])
        self.assertEqual([p.name for p in 结果['册s']],
                         ['第01卷.cbz', '第02卷.cbz', '第03卷.cbz'])
        with zipfile.ZipFile(结果['册s'][0]) as z:
            self.assertIn('第01卷/001_第1话/0001.png', z.namelist())

    def test_话级_扁平命名与内容(self):
        书 = _造书(self.根, 3, 每话页=2)
        结果 = E.导出(书, self.根, 格式='cbz', 单位='话', 写索引=False)
        self.assertEqual([p.name for p in 结果['册s']],
                         ['001_第1话.cbz', '002_第2话.cbz', '003_第3话.cbz'])
        with zipfile.ZipFile(结果['册s'][0]) as z:
            self.assertEqual(z.namelist(), ['0001.png', '0002.png'],
                             '一话一册 → 内部不套同名目录')

    def test_统一使用STORED不二次压缩(self):
        """webp/png 已压缩, 统一层必须 STORED —— 历史上有入口用 DEFLATED, 会不一致。"""
        书 = _造书(self.根, 2, 每话页=1)
        结果 = E.导出(书, 格式='cbz', 单位='卷', 卷界=[2])
        with zipfile.ZipFile(结果['册s'][0]) as z:
            for info in z.infolist():
                self.assertEqual(info.compress_type, zipfile.ZIP_STORED)

    def test_先写tmp再替换_无残留(self):
        书 = _造书(self.根, 2, 每话页=1)
        结果 = E.导出(书, 格式='cbz', 单位='卷', 卷界=[2])
        输出 = Path(结果['输出目录'])
        self.assertEqual(list(输出.glob('*.tmp')), [])


class TestPDF(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.根 = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _页数(self, pdf: Path) -> int:
        数据 = pdf.read_bytes()
        return len(re.findall(rb'/Type\s*/Page[^s]', 数据))

    def test_卷级PDF页数等于图片数(self):
        书 = _造书(self.根, 4, 每话页=2)
        结果 = E.导出(书, 格式='pdf', 单位='卷', 卷界=[2, 4])
        self.assertEqual([p.name for p in 结果['册s']],
                         ['第01卷.pdf', '第02卷.pdf'])
        self.assertEqual(self._页数(结果['册s'][0]), 4)
        self.assertEqual(self._页数(结果['册s'][1]), 4)

    def test_PDF文件头合法(self):
        书 = _造书(self.根, 1, 每话页=1)
        结果 = E.导出(书, 格式='pdf', 单位='话', 写索引=False)
        self.assertTrue(结果['册s'][0].read_bytes().startswith(b'%PDF'))

    def test_话级PDF命名(self):
        书 = _造书(self.根, 2, 每话页=1)
        结果 = E.导出(书, self.根, 格式='pdf', 单位='话', 写索引=False)
        self.assertEqual([p.name for p in 结果['册s']],
                         ['001_第1话.pdf', '002_第2话.pdf'])

    def test_无tmp残留(self):
        书 = _造书(self.根, 1, 每话页=2)
        结果 = E.导出(书, 格式='pdf', 单位='卷')
        self.assertEqual(list(Path(结果['输出目录']).glob('*.tmp')), [])


class TestPages格式(unittest.TestCase):

    def test_pages不产新文件(self):
        with tempfile.TemporaryDirectory() as tmp:
            书 = _造书(Path(tmp), 2)
            结果 = E.导出(书, 格式='pages')
            self.assertEqual(结果['册s'], [])
            self.assertEqual(结果['输出目录'], str(书))
            self.assertEqual(len(list(书.iterdir())), 2, '不应新建任何目录')


class Test索引(unittest.TestCase):

    def test_卷级导出附卷目录(self):
        with tempfile.TemporaryDirectory() as tmp:
            书 = _造书(Path(tmp), 6, 每话页=1)
            结果 = E.导出(书, 格式='cbz', 单位='卷', 卷界=[3, 6])
            索引 = Path(结果['输出目录']) / '卷目录.md'
            self.assertTrue(索引.is_file())
            文本 = 索引.read_text(encoding='utf-8')
            self.assertIn('第01卷', 文本)
            self.assertIn('共 6 话 / 2 卷', 文本)

    def test_话级不写索引(self):
        with tempfile.TemporaryDirectory() as tmp:
            书 = _造书(Path(tmp), 2, 每话页=1)
            E.导出(书, Path(tmp), 格式='cbz', 单位='话', 写索引=False)
            self.assertFalse((Path(tmp) / '卷目录.md').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
