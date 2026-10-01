# -*- coding: utf-8 -*-
"""守卫测试: `inspect_page` 的请求头不得硬编码 `Host`（对应 踩坑总表 K27）。

**这是待评估补丁的一部分** —— 本文件放在 `文档/待评估补丁/` 下，
评估通过后再移入 `测试/` 并纳入门禁。

为什么用 AST 而不是跑网络:
  本坑的触发条件是"站点做主机级跳转", 离线无法稳定复现(且 SSRF 防线禁止访问本机地址,
  无法起本地跳转服务器)。项目已有同风格先例 —— `test_no_silent_except.py` 与
  `脚本/check_undefined_refs.py` 都是**扫描源码**做机器执法。
  这里用 AST 定位 `inspect_page` 内的 `headers = {...}` 字面量, 断言其中没有 'Host'。

防"空转通过"的自我校验:
  若将来 headers 被重构(变量改名/抽成函数), 本测试必须**响亮地失败**而不是静默通过,
  因此同时断言"确实找到了那个字典"且"里面有 User-Agent"。

用法(项目根): .runtime\\python314\\python.exe -m unittest discover -s 文档/待评估补丁 -v
"""
import ast
import unittest
from pathlib import Path

_根 = Path(__file__).resolve().parents[2]
_爬虫源码 = _根 / '源码' / '爬虫.py'


def _找inspect_page的头字典():
    """返回 inspect_page 内 `headers = {...}` 的键集合; 找不到则返回 None"""
    树 = ast.parse(_爬虫源码.read_text(encoding='utf-8'))
    for 节点 in ast.walk(树):
        if isinstance(节点, ast.FunctionDef) and 节点.name == 'inspect_page':
            for 子 in ast.walk(节点):
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


class TestInspectPage请求头(unittest.TestCase):

    def test_能定位到headers字典(self):
        """自我校验: 定位失败必须报错, 否则本测试会静默变成永远通过的空测试"""
        键s = _找inspect_page的头字典()
        self.assertIsNotNone(
            键s, '未能在 inspect_page 中找到 `headers = {...}` 字面量 —— '
                 '源码结构已变, 请同步更新本守卫测试(不要让它静默通过)')
        self.assertIn('User-Agent', 键s,
                      '定位到的字典看起来不是请求头(缺 User-Agent), 守卫可能已失效')

    def test_请求头不得硬编码Host(self):
        """K27: 手写 Host 会让做 www/主机级跳转的站点陷入 Exceeded 30 redirects"""
        键s = _找inspect_page的头字典()
        self.assertIsNotNone(键s, '未定位到请求头字典')
        self.assertNotIn(
            'Host', 键s,
            "inspect_page 的请求头里出现了硬编码 'Host'。\n"
            "requests 会按 URL 自动生成正确的 Host(含跳转后的新主机)；手写它会覆盖该行为，\n"
            "导致 bookben5.org → www.bookben5.org 这类主机级跳转被反复 301，\n"
            "最终 requests 抛 'Exceeded 30 redirects.' 并返回空页面(目录 0 章)。\n"
            "详见 文档/踩坑总表.md K27。")

    def test_不得在其它位置给session注入Host头(self):
        """兜底: 除了 headers 字面量, 也不该通过 session.headers 等途径固定 Host"""
        源码 = _爬虫源码.read_text(encoding='utf-8')
        for 可疑 in ("session.headers['Host']", 'session.headers["Host"]',
                     "session.headers.update({'Host'", 'session.headers.update({"Host"'):
            self.assertNotIn(可疑, 源码, f'发现固定 Host 的写法: {可疑}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
