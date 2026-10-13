# -*- coding: utf-8 -*-
"""章节链接正则闸 — 链路守卫 (2026-10-13 F5 补验新增)。

背景: `chapter_url_regex` 曾是"死配置"（18 站声明、全源码 0 处使用），
2.5.16 修复后现有 `test_章节链接正则.py` 覆盖了**匹配函数**与**粗粒度接线**
（"源码里出现过该字段/闸门被调用 2 次"）。本文件补**链路级**守卫，防退化：

  ① 正则来源必须来自站点表 `_站点配置.get('chapter_url_regex')`
     （防止退化成硬编码/局部变量，配置重新失效）
  ② 两个放行点里 `_章节链接合正则()` 必须在 `chapters.append()` **之前**
     （顺序错 = 闸门形同虚设）
  ③ 拒绝计数 `_正则拒 += 1` 紧邻闸门（拦了要可观测）
  ④ 汇总日志带正则可观测项

真机补验仍受阻（本地 9 站全有适配器，无"无适配器+配正则"样本），
这些结构守卫 + 匹配函数用例是当前能做到的最强保障；K33 变异测试见下。
运行: .runtime/python314/python.exe -m unittest discover -s 测试
"""
import ast
import unittest
from pathlib import Path

_根 = Path(__file__).resolve().parent.parent
_源码 = (_根 / '源码' / '爬虫.py').read_text(encoding='utf-8')
_树 = ast.parse(_源码)


def _函数源码(名: str) -> str:
    for n in ast.walk(_树):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == 名:
            return ast.get_source_segment(_源码, n) or ''
    return ''


def _函数节点(名: str):
    for n in ast.walk(_树):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == 名:
            return n
    return None


def _是闸门调用(n) -> bool:
    """_章节链接合正则(...) 调用节点"""
    return (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == '_章节链接合正则')


def _是chapters追加(n) -> bool:
    """chapters.append(...) 调用节点 (Attribute 形态, 不能按 Name 字符串匹配)"""
    return (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == 'append'
            and isinstance(n.func.value, ast.Name) and n.func.value.id == 'chapters')


class Test正则闸链路(unittest.TestCase):

    def test_正则来源是站点表(self):
        """① 章节正则必须从 _站点配置 读取 (防硬编码退化)"""
        段 = _函数源码('get_chapter_list')
        self.assertIn('_站点配置', 段)
        self.assertIn("_站点配置.get('chapter_url_regex')", 段,
                      '章节正则必须来自站点表 chapter_url_regex 字段')

    def test_闸门调用在append之前(self):
        """② 每个放行点内: 正则闸必须早于紧随的 chapters.append (顺序错=白拦)

        注意: 函数内有 10 处 chapters.append (多分支), 不能拿"最前 append"
        比较 (早期分支与闸门无关)。正确形态: 每个闸门调用之后 25 行内必须
        出现 append (即闸门拦完才收录)。
        """
        节点 = _函数节点('get_chapter_list')
        self.assertIsNotNone(节点)
        闸门行 = [n.lineno for n in ast.walk(节点) if _是闸门调用(n)]
        append行 = [n.lineno for n in ast.walk(节点) if _是chapters追加(n)]
        self.assertGreaterEqual(len(闸门行), 2, '至少两个放行点')
        self.assertGreaterEqual(len(append行), 2, '至少两个 append')
        for 闸 in 闸门行:
            后续append = [a for a in append行 if 0 < a - 闸 <= 25]
            self.assertTrue(后续append,
                            f'闸门(第{闸}行)之后 25 行内必须紧跟 chapters.append '
                            f'(顺序错=闸门白拦)')

    def test_拒绝计数紧邻闸门(self):
        """③ 拦下的链接要计数 (_正则拒 += 1 出现在闸门调用之后)"""
        段 = _函数源码('get_chapter_list')
        self.assertGreaterEqual(段.count('_正则拒 += 1'), 2,
                                '两个放行点都应累加拒绝计数')
        self.assertLess(段.index('_章节链接合正则('), 段.rindex('_正则拒 += 1'),
                        '拒绝计数必须出现在闸门调用之后')

    def test_汇总日志带正则可观测项(self):
        """④ 日志要能看出正则是否参与 (排障靠它)"""
        段 = _函数源码('get_chapter_list')
        self.assertIn('_正则拒', 段)
        self.assertIn('正则:', 段, '汇总日志应带正则信息')


if __name__ == '__main__':
    unittest.main(verbosity=2)
