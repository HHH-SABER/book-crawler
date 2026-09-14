# -*- coding: utf-8 -*-
"""守卫测试: 全项目禁止"纯 pass 无留痕/无注释"的 except (AGENTS.md 规约的机器执法)。

## 为什么需要

项目规约要求"裸 except 必须留痕", 但 2026-09-13 AST 摸底实测仍有 191 处
"except ...: pass" 一行不带任何解释——规约靠人记忆执行, 批 2A-2E 治理完成后
(全部处置: 补 debug 留痕 或 保留静默+写明真实原因), 用本测试把基线**钉死为 0**:
今后任何人 (含 AI 会话) 新写一个无留痕无注释的 except, 门禁直接红。

## 判定口径 (与批2 治理工具完全一致, 勿改宽)

- 命中 = ExceptHandler 的 body 只有 Pass、且该 pass 行不含 '#' 注释、
  且 handler 源码不含任何日志/打印调用 (LOGCALLS)。
- 有注释即视为"已解释的有意静默", 放过 (理由质量靠 review, 机器不判)。
- body 非纯 pass (有 continue/赋值等) 的 except 不在本守卫范围。

## 性能

全项目 AST 解析约 100 文件, 单次 <2s, 可放心进 discover 门禁。
"""
import ast
import os
import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ['源码', '站点适配', '脚本']
SKIP_DIRS = {'__pycache__', '.mimosa', 'NVIDIA Corporation', '.toolchain', 'target'}
LOGCALLS = ('_log.', 'log.', 'app_log.', '_app_log.', 'logging.', 'print(')


def _scan_silent():
    """返回 [(相对路径, 行号, 异常类型源码)] —— 纯 pass 无留痕无注释的 except"""
    out = []
    for d in SCAN_DIRS:
        base = _PROJECT_ROOT / d
        if not base.is_dir():
            continue
        for root, dirs, files in os.walk(base):
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
            for f in files:
                if not f.endswith('.py'):
                    continue
                p = Path(root) / f
                try:
                    text = p.read_text(encoding='utf-8', errors='replace')
                    tree = ast.parse(text)
                    lines = text.splitlines()
                except (SyntaxError, OSError):
                    continue  # 语法坏的文件由 check_undefined_refs/单测导入暴露
                for node in ast.walk(tree):
                    if not isinstance(node, ast.ExceptHandler):
                        continue
                    if not all(isinstance(s, ast.Pass) for s in node.body):
                        continue
                    if any(k in ast.unparse(node) for k in LOGCALLS):
                        continue
                    pl = node.body[0].lineno
                    raw = lines[pl - 1] if pl - 1 < len(lines) else ''
                    if '#' in raw:
                        continue   # 有意静默已带解释注释
                    out.append((str(p.relative_to(_PROJECT_ROOT)),
                                node.lineno,
                                ast.unparse(node.type) if node.type else 'Exception'))
    return out


class TestNoSilentExcept(unittest.TestCase):
    """AGENTS.md: 裸 except 必须留痕 —— 新代码不得引入无留痕无注释的 except pass"""

    def test_全项目无纯静默except(self):
        silent = _scan_silent()
        self.assertEqual(
            [], silent,
            f'发现 {len(silent)} 处"纯 pass 无留痕无注释"的 except (违反 AGENTS.md 裸 except 规约):\n'
            + '\n'.join(f'  {rel}:{ln}  except {typ}' for rel, ln, typ in silent)
            + '\n处置二选一: ①补 debug 留痕 (except 补 as 变量, pass 改 _log.debug 输出'
              '异常类型与消息) ②确属有意静默则在 pass 行尾加 "# 刻意静默: <具体原因>" 注释')


if __name__ == '__main__':
    unittest.main(verbosity=2)
