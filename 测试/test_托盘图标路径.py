# -*- coding: utf-8 -*-
"""托盘图标路径候选的离线用例（2026-10-24，修"托盘图标变纯色块"）。

根因回顾：
- `关闭行为.py` 原来算的是 `<源码目录>/../脚本/图标.ico`（即 `源码/脚本/图标.ico`，不存在）；
- `build_exe.py` 的 add_data_list 也没把 `脚本/图标.ico` 打进 EXE。
⇒ `Image.open` 失败 → tray.py 走纯色占位。

本用例钉住候选顺序：资源根优先（EXE 的 _MEIPASS），再基根（源码/开发态）。
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / '源码'))

from _path_utils import 托盘图标候选  # noqa: E402


class 托盘图标候选用例(unittest.TestCase):
    def test_顺序为资源根优先(self):
        候选 = 托盘图标候选('/res', '/base')
        self.assertEqual(候选[0], str(pathlib.Path('/res/脚本/图标.ico')))
        self.assertEqual(候选[1], str(pathlib.Path('/res/图标.ico')))
        self.assertEqual(候选[2], str(pathlib.Path('/base/脚本/图标.ico')))
        self.assertEqual(候选[3], str(pathlib.Path('/base/图标.ico')))

    def test_去重且顺序稳定(self):
        候选 = 托盘图标候选('/same', '/same')
        self.assertEqual(len(候选), 2)          # /same/脚本/图标.ico 与 /same/图标.ico
        self.assertEqual(len(set(候选)), len(候选))

    def test_空根返回裸文件名兜底(self):
        候选 = 托盘图标候选('', '')
        self.assertEqual(候选, ['图标.ico'])


if __name__ == '__main__':
    unittest.main()
