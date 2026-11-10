# -*- coding: utf-8 -*-
"""漫画分卷打包 (漫画卷册) 的离线用例。

用临时目录造图，不联网、不依赖任何真实站点/书名。
"""
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / '源码'))

import 漫画卷册 as V   # noqa: E402


def _造书(根: Path, 话数: int, 每话页: int = 3) -> Path:
    书 = 根 / '示例漫画'
    书.mkdir(parents=True)
    for i in range(1, 话数 + 1):
        话 = 书 / f'{i:03d}_第{i}话'
        话.mkdir()
        for p in range(1, 每话页 + 1):
            (话 / f'{p:04d}.webp').write_bytes(b'x' * 4096)   # >1KB: 统一层会过滤坏图
    return 书


class Test卷界(unittest.TestCase):

    def test_解析正常(self):
        self.assertEqual(V.解析卷界('8,16,47', 47), [8, 16, 47])

    def test_解析全角逗号(self):
        self.assertEqual(V.解析卷界('8，47', 47), [8, 47])

    def test_末卷必须等于总数(self):
        with self.assertRaises(ValueError):
            V.解析卷界('8,16', 47)

    def test_非递增报错(self):
        with self.assertRaises(ValueError):
            V.解析卷界('16,8,47', 47)

    def test_非数字报错(self):
        with self.assertRaises(ValueError):
            V.解析卷界('8,a,47', 47)

    def test_均分47话8话每卷(self):
        self.assertEqual(V.均分卷界(47, 8), [8, 16, 24, 32, 40, 47])

    def test_均分整除不多出空卷(self):
        self.assertEqual(V.均分卷界(40, 8), [8, 16, 24, 32, 40])

    def test_每卷话数非法(self):
        with self.assertRaises(ValueError):
            V.均分卷界(47, 0)


class Test打包(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.根 = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_六卷Cbz与内部路径(self):
        书 = _造书(self.根, 47, 每话页=2)
        卷s = V.打包单行本(书, 卷界=[8, 16, 24, 32, 40, 47])
        self.assertEqual([c.name for c in 卷s],
                         ['第01卷.cbz', '第02卷.cbz', '第03卷.cbz',
                          '第04卷.cbz', '第05卷.cbz', '第06卷.cbz'])
        with zipfile.ZipFile(卷s[0]) as z:
            名s = z.namelist()
        self.assertEqual(len(名s), 8 * 2, '第1卷应含 8 话 × 2 页')
        self.assertIn('第01卷/001_第1话/0001.webp', 名s)
        self.assertIn('第01卷/008_第8话/0002.webp', 名s)
        # 第 6 卷只收 41-47（7 话）
        with zipfile.ZipFile(卷s[5]) as z:
            self.assertEqual(len(z.namelist()), 7 * 2)

    def test_话目录排序按序号而非字典序(self):
        书 = self.根 / '示例'
        书.mkdir()
        for 名 in ('10_十', '9_九', '2_二'):
            d = 书 / 名
            d.mkdir()
            (d / '0001.webp').write_bytes(b'x' * 4096)
        话 = V.找话目录(书)
        self.assertEqual([V.话序(p.name)[0] for p in 话], [2, 9, 10])

    def test_忽略不含图片的目录(self):
        书 = _造书(self.根, 2)
        (书 / '单行本').mkdir()
        self.assertEqual(len(V.找话目录(书)), 2)

    def test_空目录报错(self):
        空 = self.根 / '空'
        空.mkdir()
        with self.assertRaises(ValueError):
            V.打包单行本(空)

    def test_目录不存在报错(self):
        with self.assertRaises(FileNotFoundError):
            V.打包单行本(self.根 / '没有')

    def test_索引含卷话对照(self):
        书 = _造书(self.根, 10, 每话页=1)
        界 = [5, 10]
        V.打包单行本(书, 卷界=界)
        索引 = V.写目录索引(书, 界)
        文本 = 索引.read_text(encoding='utf-8')
        self.assertIn('第01卷', 文本)
        self.assertIn('第02卷', 文本)
        self.assertIn('共 10 话 / 2 卷', 文本)

    def test_默认输出目录加后缀(self):
        书 = _造书(self.根, 2)
        卷s = V.打包单行本(书, 每卷话数=2)
        self.assertEqual(卷s[0].parent.name, '示例漫画_单行本')


if __name__ == '__main__':
    unittest.main(verbosity=2)
