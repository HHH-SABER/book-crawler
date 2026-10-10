# -*- coding: utf-8 -*-
"""守卫测试: 请求头不得硬编码 `Host`（对应 踩坑总表 K29）。

**为什么用 AST 而不是跑网络**: 触发条件是"站点做主机级跳转", 离线无法稳定复现
(SSRF 防线也禁止访问本机地址, 起不了本地跳转服务器)。项目已有同风格先例 ——
`测试/test_no_silent_except.py` 与 `脚本/check_undefined_refs.py` 都是扫描源码做机器执法。

**2026-10-03 修复记录**: 该反模式在 `源码/爬虫.py` 里有**三份拷贝** ——
`inspect_page`(目录解析) / `get_chapter_content`(章节正文) / `get_novel_title`(书名提取),
三处都走 `_get_with_js_challenge`, 症状分别是 目录 0 章 / 正文全空 / 书名空。
本测试对三个函数逐一断言, 防止任意一处被重新引入。

**2026-10-10 结构变更 (C4 书名清洗)**: 书名那位改成了两层 ——
`get_novel_title()` 成了**只做清洗的薄包装**, 真正的请求体(含 `headers`)改名为
`_提取书名原始()`。故受查符号跟着换成 `_提取书名原始`（**本守卫就是这么设计的**:
结构一改就红, 逼人来看一眼, 而不是静默失去覆盖）。请求路径本身未变。

**防"空转通过"**: 若将来 headers 被重构(改名/抽成函数), 本测试必须**响亮地失败**
而不是静默通过 —— 因此同时断言"三个函数都还在"且"能找到那个字典"且"里面有 User-Agent"。
"""
import ast
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_爬虫源码 = _PROJECT_ROOT / '源码' / '爬虫.py'

# 修复覆盖的三个函数: 任一处重新硬编码 Host, 都是同一个 bug 复发
# (第三个在 2026-10-10 由 get_novel_title 改名为 _提取书名原始, 见模块 docstring)
_受查函数 = ('inspect_page', 'get_chapter_content', '_提取书名原始')


def _解析源码():
    return ast.parse(_爬虫源码.read_text(encoding='utf-8'))


def _函数节点(树, 名称):
    for 节点 in ast.walk(树):
        if isinstance(节点, ast.FunctionDef) and 节点.name == 名称:
            return 节点
    return None


def _请求头字典键(函数节点):
    """返回函数内 `headers = {...}` 的键集合; 找不到返回 None"""
    for 子 in ast.walk(函数节点):
        if (isinstance(子, ast.Assign) and len(子.targets) == 1
                and isinstance(子.targets[0], ast.Name)
                and 子.targets[0].id == 'headers'
                and isinstance(子.value, ast.Dict)):
            键s = set()
            for k in 子.value.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    键s.add(k.value)
            return 键s
    return None


class Test请求头不得硬编码Host(unittest.TestCase):

    def test_三个受查函数都还在(self):
        """防空转: 函数被改名/删除时必须失败, 否则覆盖面会静默归零"""
        树 = _解析源码()
        for 名称 in _受查函数:
            with self.subTest(函数=名称):
                self.assertIsNotNone(
                    _函数节点(树, 名称),
                    f'源码里找不到函数 {名称} —— 结构已变, 请同步更新本守卫测试'
                    f'(不要让它静默变成永远通过的空测试)')

    def test_三处请求头都不得硬编码Host(self):
        """K29: 手写 Host 会覆盖 requests 自动生成的 Host, 打断主机级跳转"""
        树 = _解析源码()
        for 名称 in _受查函数:
            函数节点 = _函数节点(树, 名称)
            if 函数节点 is None:
                self.skipTest(f'{名称} 不存在, 由 test_三个受查函数都还在 负责报错')
            键s = _请求头字典键(函数节点)
            with self.subTest(函数=名称):
                self.assertIsNotNone(
                    键s, f'{名称} 里未找到 `headers = {{...}}` 字面量 —— '
                         f'结构已变, 请同步更新本守卫测试(不要让它静默通过)')
                self.assertIn('User-Agent', 键s,
                              f'{名称} 定位到的字典不像请求头(缺 User-Agent), 守卫可能已失效')
                self.assertNotIn(
                    'Host', 键s,
                    f"{名称} 的请求头里出现了硬编码 'Host'。\n"
                    "requests 会按 URL 自动生成正确的 Host(含跳转后的新主机); 手写它会覆盖该行为,\n"
                    "导致 siteah.example.org → www.siteah.example.org 这类主机级跳转被反复 301,\n"
                    '最终抛 "Exceeded 30 redirects." 并返回空页面。\n'
                    "详见 文档/踩坑总表.md K29。")

    def test_全文件不得以任何形式把Host当键(self):
        """兜底(AST 而非正则: 注释里提到 'Host' 不应误伤)"""
        树 = _解析源码()
        坏 = []
        for 子 in ast.walk(树):
            if isinstance(子, ast.Dict):
                for k in 子.keys:
                    if isinstance(k, ast.Constant) and k.value == 'Host':
                        坏.append(f'第 {子.lineno} 行: 字典字面量以 Host 为键')
            elif isinstance(子, ast.Subscript):
                切片 = 子.slice
                if isinstance(切片, ast.Constant) and 切片.value == 'Host':
                    坏.append(f'第 {子.lineno} 行: 用 Host 作下标')
        self.assertEqual(
            [], 坏,
            '任何形式的固定 Host 都会打断主机级跳转(K29): ' + '; '.join(坏))

    def test_不得通过session固定Host(self):
        """K29 原始补丁里的兜底断言, 保留防回归"""
        源码 = _爬虫源码.read_text(encoding='utf-8')
        for 可疑 in ("session.headers['Host']", 'session.headers["Host"]',
                     "session.headers.update({'Host'", 'session.headers.update({"Host"'):
            self.assertNotIn(可疑, 源码, f'发现固定 Host 的写法: {可疑}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
