# -*- coding: utf-8 -*-
"""适配器"引用了但没定义"的模块级名字守卫 (2026-10-12)。

**真实事故**: Wave 2 把 `爬虫.py` 的内置目录解析器外置成 `站点适配_本地/*.py` 时,
提取脚本只做了 `self.` 前缀的机械替换, **被引用的模块级辅助函数没一起搬过来** ⇒
适配器解析完章节、走到 `chapters.sort(key=_chapter_sort_key)` 时抛 `NameError`
⇒ 被上层 `except` 吞掉 ⇒ **静默退回通用解析** ⇒ 0 章 / 任务失败。
用户看到的是"未提取到章节", 极易误判成 WAF / 折叠 / 死站。
实测一次命中 **9 个适配器** (都缺 `_chapter_sort_key`), 另有 2 个缺格式化辅助函数。

**判定口径**(刻意选宽, 只求零误报): 一个名字只要在**文件任何位置被绑定过**
(赋值 / 形参 / lambda 形参 / def / class / import / for / with / except / 推导式目标),
就算已定义; 只有**从未绑定过**的才可疑。
这样能抓住"漏搬"这一类, 又不会把闭包变量、lambda 形参误报成缺失
(首版按"函数内是否绑定"判定, `lambda x: int(x)` 里的 `x` 就被误报了)。

公开侧安全: 本文件不含任何站点信息; 本地适配器目录缺失时 `skipTest`
(符合项目"机制测试读不到本地 fixture 时跳过"的约定)。

运行方式 (项目根目录):
    python -m unittest discover -s 测试 -v
"""
import ast
import builtins
import sys
import unittest
from pathlib import Path

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

_本地适配器目录 = _根 / '站点适配_本地'
_内建 = set(dir(builtins))


def _已绑定名字(树) -> set:
    """文件里被绑定过的所有名字 (宽口径: 任何绑定形式都算)。"""
    出 = set()
    for n in ast.walk(树):
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            出.add(n.id)
        elif isinstance(n, ast.arg):
            出.add(n.arg)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            出.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                出.add((a.asname or a.name).split('.')[0])
        elif isinstance(n, ast.ExceptHandler) and n.name:
            出.add(n.name)
        elif isinstance(n, ast.Global):
            出.update(n.names)
        elif isinstance(n, ast.Nonlocal):
            出.update(n.names)
    return 出


def _可疑名字(源码: str) -> dict:
    """返回 {名字: 行号} —— 加载过但**从未在文件里绑定**的 (排除内建)。"""
    树 = ast.parse(源码)
    已绑定 = _已绑定名字(树)
    出 = {}
    for n in ast.walk(树):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            if n.id not in 已绑定 and n.id not in _内建:
                出.setdefault(n.id, n.lineno)
    return 出


class Test适配器无未定义名字(unittest.TestCase):

    def setUp(self):
        if not _本地适配器目录.is_dir():
            self.skipTest('本地适配器目录不存在 (公开形态) —— 本用例只在本机形态生效')

    def test_所有适配器都没有从未绑定的名字(self):
        坏 = {}
        for f in sorted(_本地适配器目录.glob('*.py')):
            if f.name.startswith('_'):
                continue                     # `_` 前缀不被加载器加载 (模板/私有)
            try:
                源码 = f.read_text(encoding='utf-8')
            except OSError as e:
                self.fail(f'读取 {f.name} 失败: {e}')
            可疑 = _可疑名字(源码)
            if 可疑:
                坏[f.name] = 可疑
        self.assertEqual(
            坏, {},
            '适配器引用了从未定义的名字 (Wave 2 提取漏搬辅助函数的典型症状; '
            '后果是被上层吞掉 → 静默退回通用解析 → 0 章): ' +
            '; '.join(f'{k}: {sorted(v)}' for k, v in 坏.items()))

    def test_守卫本身有效_能抓到漏搬的函数(self):
        """防"空转通过": 造一个漏搬的样本, 守卫必须报出来。"""
        样本 = ('import re\n'
               'def parse_catalog(soup):\n'
               '    chapters = []\n'
               '    chapters.sort(key=_chapter_sort_key)\n'   # 没定义 → 必须被抓到
               '    return chapters\n')
        可疑 = _可疑名字(样本)
        self.assertIn('_chapter_sort_key', 可疑,
                      '守卫失灵: 漏搬的模块级函数没被识别出来')

    def test_守卫不误报闭包与lambda形参(self):
        """`lambda x: int(x)` / 闭包变量曾被误报, 这条守住不再回归。"""
        样本 = ('def f(xs, n):\n'
               '    seq = []\n'
               '    def inner():\n'
               '        return seq + [pos for pos in range(n)]\n'
               '    xs.sort(key=lambda x: int(x))\n'
               '    return inner()\n')
        self.assertEqual(_可疑名字(样本), {}, '闭包/lambda 形参被误报成未定义')


if __name__ == '__main__':
    unittest.main(verbosity=2)
