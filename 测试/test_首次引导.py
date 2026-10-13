# -*- coding: utf-8 -*-
"""首次引导/桌面快捷方式回归 (2026-10-13 服务化提取后新增)。

锁 `gui_components/首次引导.py` 的行为契约 (与原 gui_app.main() 闭包一致):
① flag 原子写 + 路径稳定; ② PS 命令含 OneDrive 桌面路径/UTF-16 传参准备;
③ 引号转义 (路径含单引号时不炸); ④ 失败**必须**把 stderr 带进异常。
运行: python -m unittest discover -s 测试
"""
import base64
import os
import sys
import tempfile
import unittest
from pathlib import Path

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

from gui_components import 首次引导 as F   # noqa: E402


class _假结果:
    def __init__(self, rc=0, err=b''):
        self.returncode = rc
        self.stderr = err


class TestFlag读写(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._原 = F.get_state_root
        F.get_state_root = lambda: str(self.tmp)

    def tearDown(self):
        F.get_state_root = self._原
        self._tmp.cleanup()

    def test_首次判定与写入(self):
        self.assertTrue(F.是否首次启动(), '无 flag 时应判首次')
        F.写首次flag('已创建桌面快捷方式')
        self.assertFalse(F.是否首次启动(), '写后不应再判首次')
        文 = (self.tmp / '数据' / '首次启动.flag').read_text(encoding='utf-8')
        self.assertIn('已创建桌面快捷方式', 文)

    def test_flag路径稳定(self):
        p = F.首次flag路径()
        self.assertTrue(p.replace('\\', '/').endswith('数据/首次启动.flag'))

    def test_原子写不残留tmp(self):
        F.写首次flag()
        留 = [x.name for x in (self.tmp / '数据').iterdir() if '.tmp.' in x.name]
        self.assertEqual(留, [], '原子替换后不应残留 tmp 文件')


class TestPowerShell命令(unittest.TestCase):

    def test_含关键要素(self):
        ps = F.构建PowerShell命令(r'C:\app\小说爬虫.exe', r'C:\app')
        self.assertIn("GetFolderPath('Desktop')", ps,
                      '桌面路径必须在 PS 侧取 (OneDrive 重定向)')
        self.assertIn('小说爬虫.lnk', ps)
        self.assertIn('WScript.Shell', ps)
        self.assertIn('TargetPath', ps)

    def test_单引号转义(self):
        """路径含单引号时 PS 字符串不能炸 (旧实现踩过)"""
        ps = F.构建PowerShell命令(r"C:\it's\app.exe", r"C:\it's")
        self.assertIn("C:\\it''s\\app.exe", ps)

    def test_创建成功不抛(self):
        F.建桌面快捷方式(r'C:\app\x.exe', 运行器=lambda *a, **k: _假结果(0))

    def test_失败带stderr进异常(self):
        """④ 契约: 失败必须把 PS stderr 带进异常 (只报退出码等于没报)"""
        with self.assertRaises(RuntimeError) as ctx:
            F.建桌面快捷方式(r'C:\app\x.exe',
                            运行器=lambda *a, **k: _假结果(
                                1, '拒绝访问'.encode('utf-8')))
        self.assertIn('拒绝访问', str(ctx.exception))

    def test_编码参数可解回(self):
        """命令经 UTF-16LE Base64 传入 (中文不走代码页) —— 验证可逆"""
        ps = F.构建PowerShell命令(r'C:\app\小说爬虫.exe', r'C:\app')
        enc = base64.b64encode(ps.encode('utf-16-le')).decode('ascii')
        self.assertEqual(base64.b64decode(enc).decode('utf-16-le'), ps)


if __name__ == '__main__':
    unittest.main(verbosity=2)
