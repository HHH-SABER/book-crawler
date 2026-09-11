# -*- coding: utf-8 -*-
"""check_undefined_refs 离线单测: from-import 名字解析检查 (v2.4.19 教训)。

背景: symtable 把 from-import 标为 is_imported() 合法绑定, 名字在目标模块
不存在也查不出 —— v2.4.19 弹窗 import 不存在的 MORANDI_TERTIARY_CONTAINER,
运行时点关闭按钮才 ImportError 强退。本测试验证增补的静态校验:
  1. 函数体内 from-import 引用不存在的名字 -> 被抓出 (原事故场景)
  2. 包 __init__ 再导出的名字可被正确解析 (不误报)
  3. 相对导入 (level>=1) 可解析
  4. 星号导入 / 项目外模块 (标准库/三方包) 跳过不误报
  5. 契约: 对真实 源码/ 全量扫描必须为空 (防本类事故回流)

运行方式 (项目根目录):
    python -m unittest discover -s 测试 -v
"""

import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

_SPEC = importlib.util.spec_from_file_location(
    'check_undefined_refs',
    _PROJECT_ROOT / '脚本' / 'check_undefined_refs.py')
cur = importlib.util.module_from_spec(_SPEC)
sys.modules['check_undefined_refs'] = cur
_SPEC.loader.exec_module(cur)


class TestFromImport解析检查(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = Path(tempfile.mkdtemp(prefix='nsl_refs_'))
        pkg = cls._tmp / 'pkg'
        pkg.mkdir()
        (pkg / '__init__.py').write_text(
            'from .mod import PUBLIC as RE_EXPORT\n', encoding='utf-8')
        (pkg / 'mod.py').write_text(
            'PUBLIC = 1\n\ndef func():\n    return 2\n', encoding='utf-8')
        # 原事故场景: 函数体内 import 不存在的常量
        (cls._tmp / 'bad.py').write_text(
            'def f():\n'
            '    from pkg.mod import PUBLIC, NOT_EXIST\n'
            '    return PUBLIC, NOT_EXIST\n', encoding='utf-8')
        # 包 __init__ 再导出的名字必须可解析 (不误报)
        (cls._tmp / 'good_reexport.py').write_text(
            'from pkg import RE_EXPORT\nx = RE_EXPORT\n', encoding='utf-8')
        # 正常引用: 不报
        (cls._tmp / 'good.py').write_text(
            'from pkg.mod import PUBLIC, func\nv = PUBLIC + func()\n',
            encoding='utf-8')
        # 星号导入: 静态无法穷举, 跳过不报
        (cls._tmp / 'star.py').write_text(
            'from pkg.mod import *\n', encoding='utf-8')
        # 项目外模块 (标准库): 跳过不报
        (cls._tmp / 'external.py').write_text(
            'from os import path\np = path\n', encoding='utf-8')
        # 相对导入 level=1
        rel = cls._tmp / 'relpkg'
        rel.mkdir()
        (rel / '__init__.py').write_text('', encoding='utf-8')
        (rel / 'mod2.py').write_text('THING = 1\n', encoding='utf-8')
        (rel / 'ok.py').write_text(
            'from .mod2 import THING\nv = THING\n', encoding='utf-8')
        (rel / 'bad_rel.py').write_text(
            'from .mod2 import ABSENT\nv = ABSENT\n', encoding='utf-8')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def _names(self, results):
        """归一化为 {(文件名, 块, 名字)} 便于断言"""
        return {(Path(p).name, block, name) for p, block, name in results}

    def test_函数体内import不存在名字_被抓出(self):
        got = self._names(cur.scan_dir(self._tmp))
        self.assertIn((Path('bad.py').name,
                       'from pkg.mod import', 'NOT_EXIST'), got)

    def test_包再导出与正常引用_不误报(self):
        got = self._names(cur.scan_dir(self._tmp))
        for 文件 in ('good.py', 'good_reexport.py', 'star.py', 'external.py',
                     Path('ok.py').name):
            hit = [g for g in got if g[0] == 文件]
            self.assertEqual(hit, [], f'{文件} 不应有问题: {hit}')

    def test_相对导入不存在名字_被抓出(self):
        got = self._names(cur.scan_dir(self._tmp))
        self.assertIn((Path('bad_rel.py').name,
                       'from .mod2 import', 'ABSENT'), got)

    def test_真实源码全量扫描_契约必须为空(self):
        """v2.4.19 类事故 (import 不存在的名字) 不得再回流进源码树"""
        self.assertEqual(cur.scan_dir(_PROJECT_ROOT / '源码'), [])


if __name__ == '__main__':
    unittest.main()
