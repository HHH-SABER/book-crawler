# -*- coding: utf-8 -*-
"""B1/A3 自动迁移: print -> _log.info + 静默 except(as e, 仅pass) 注入 debug。

- 只处理"单行、单位置参数、无 kwargs"的 print 调用 (绝大多数), 其余输出待人工清单
- 在每个被迁移文件顶部注入: import 日志 as _app_log / _log = _app_log.get('<模块>')
- except Handler 绑定了异常名且体仅为 pass -> pass 替换为 _log.debug(f'静默异常: {e}')
用法: python mig_logging.py <file.py> [<file2.py> ...]   (--dry-run 预览)
"""
import ast
import io
import os
import re
import sys
from pathlib import Path

DRY = '--dry-run' in sys.argv
paths = [a for a in sys.argv[1:] if a != '--dry-run']


def module_source_name(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def inject_logger(lines, first_stmt_lineno, module_name):
    """在文件顶部(import 区后)注入 _log 绑定。返回 (new_lines, 是否已存在)。"""
    if any('_log = ' in l and '_app_log.get' in l for l in lines):
        return lines, False  # 已注入过
    # 找插入点: 第一个语句行前的空行后
    idx = first_stmt_lineno - 1
    while idx > 0 and lines[idx - 1].strip() == '':
        idx -= 1
    # idx 指向第一个语句前一行的末尾; 若无 import 区, docstring 之后
    insert_at = idx
    lines.insert(insert_at, "import 日志 as _app_log")
    lines.insert(insert_at + 1, f"_log = _app_log.get('{module_name}')")
    lines.insert(insert_at + 2, "")
    return lines, True


def process_file(path):
    src = open(path, encoding='utf-8').read()
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        print(f'[跳过-语法错] {path}: {e}')
        return 0, 0, []
    lines = src.split('\n')

    # 收集顶层(模块)第一个语句行, 用于插入 import
    first_stmt = min((n.lineno for n in tree.body if isinstance(n, ast.stmt)),
                     default=1)

    replaced_print = 0
    skipped = []
    edits = []  # (lineno 1-based, old, new)

    # ---- 1. print 迁移 ----
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id == 'print'):
            continue
        lineno = node.lineno
        end_lineno = getattr(node, 'end_lineno', lineno)
        if lineno != end_lineno:
            skipped.append((lineno, '跨行 print'))
            continue
        if node.keywords:
            skipped.append((lineno, 'kwargs print'))
            continue
        args = node.args
        if len(args) != 1:
            skipped.append((lineno, f'多参数 print x{len(args)}'))
            continue
        line = lines[lineno - 1]
        # 整行正则: 仅当 print(...) 独占整行时替换 (greedy 匹配最外层括号)
        m = re.match(r'^(\s*)print\((.*)\)\s*$', line)
        if not m:
            skipped.append((lineno, 'print 非独占行'))
            continue
        indent, inner = m.group(1), m.group(2)
        new_line = f'{indent}_log.info({inner})'
        edits.append((lineno, line, new_line))
        replaced_print += 1

    # ---- 2. 静默 except 注入 debug ----
    # 2a. as e + 仅 pass -> debug 留痕
    injected_except = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        name = node.name
        if not name:
            continue
        body = node.body
        # 仅当体是单个 pass (或 pass + 文档注释无法在 AST 见) 时注入
        if len(body) == 1 and isinstance(body[0], ast.Pass):
            lineno = body[0].lineno
            line = lines[lineno - 1]
            indent = line[:len(line) - len(line.lstrip())]
            new_line = f"{indent}_log.debug(f'静默异常(未处理): {{e}}')"
            edits.append((lineno, line, new_line))
            injected_except += 1
    # 2b. 无 name + 仅 pass + except 行无注释 -> as e + debug 留痕 (A3 裸 except)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if node.name or len(node.body) != 1 or not isinstance(node.body[0], ast.Pass):
            continue
        ex_lineno = node.lineno
        ex_line = lines[ex_lineno - 1]
        # 行内注释解释过的 fallback 视为有意, 不动
        if '#' in ex_line or '#' in lines[node.body[0].lineno - 1]:
            continue
        # except X: -> except X as e: (仅在行内无其他语句时, 保留原异常类型)
        m = re.match(r'^(\s*)except\s+(.+?):\s*$', ex_line)
        if m and ' as ' not in ex_line and '(' not in m.group(2) or (
                m and re.match(r'^(\s*)except\s+\(.+\):\s*$', ex_line)):
            if not m:
                continue
            indent, ex_types = m.group(1), m.group(2).strip()
            if ex_types == 'Exception' or ex_types.startswith('('):
                new_ex = f'{indent}except {ex_types} as e:'
                edits.append((ex_lineno, ex_line, new_ex))
                ps_line = lines[node.body[0].lineno - 1]
                ps_indent = ps_line[:len(ps_line) - len(ps_line.lstrip())]
                new_ps = f"{ps_indent}_log.debug(f'裸 except 吞异常: {{type(e).__name__}}')"
                edits.append((node.body[0].lineno, ps_line, new_ps))
                injected_except += 1

    # ---- 应用 ----
    edits.sort(reverse=True)
    if not DRY:
        # 先按原行号应用替换, 再注入顶部 import (避免行号偏移)
        for lineno, old, new in edits:
            if lines[lineno - 1] == old:
                lines[lineno - 1] = new
            else:
                skipped.append((lineno, '行已变化, 跳过'))
        lines, _injected = inject_logger(lines, first_stmt, module_source_name(path))
        out = '\n'.join(lines)
        # pathlib 锚定解析后写入, 防路径穿越
        target = Path(path).resolve()
        target.write_text(out, encoding='utf-8', newline='')
        print(f'[改] {path}: print→_log x{replaced_print}, except 注入 x{injected_except}, 跳过 {len(skipped)}')
    else:
        print(f'[预演] {path}: print→_log x{replaced_print}, except 注入 x{injected_except}, 跳过 {len(skipped)}')
    for ln, why in skipped[:12]:
        print(f'    L{ln} 跳过: {why}')
    if len(skipped) > 12:
        print(f'    ... 共 {len(skipped)} 条待人工')
    return replaced_print, injected_except, skipped


total_p = total_e = 0
for p in paths:
    rp, re_, sk = process_file(p)
    total_p += rp
    total_e += re_
print(f'==== 合计: print→_log {total_p}, except 注入 {total_e} ====')
