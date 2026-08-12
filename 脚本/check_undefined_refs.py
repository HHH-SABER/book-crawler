# -*- coding: utf-8 -*-
"""打包前必跑：扫描源码中"被引用但未定义"的名字（运行时 NameError 预检）

背景：`import gui_app` 只验证导入，查不出函数体内的 NameError（如漏 import）。
本脚本用 Python 标准库 symtable 做作用域分析，一次性扫出全部未定义引用。

用法（在项目根目录运行）:
    ./.venv/Scripts/python.exe 脚本/check_undefined_refs.py [源码目录]

坑（已踩过，勿改逻辑）:
- symtable 把函数内"未定义引用"标为 is_global()，必须再核对模块顶层符号集，
  否则全部漏报（回归测试 1 专门验证此点）。
- `__file__` 等模块 dunder 是运行时自动提供的，需加入白名单。
"""
import pathlib
import sys
import symtable
import builtins

# 模块级自动提供的名字（非真正未定义）
_DUNDER_WHITELIST = {
    '__file__', '__name__', '__doc__', '__package__',
    '__path__', '__cached__', '__builtins__',
}

_BUILTIN_NAMES = set(dir(builtins)) | _DUNDER_WHITELIST


def _check_table(st, root_names, problems):
    """递归检查符号表块：引用但无绑定的名字即未定义"""
    for sym in st.get_symbols():
        name = sym.get_name()
        if not sym.is_referenced():
            continue
        # 局部变量/参数/闭包变量/import 绑定 -> 有定义
        if sym.is_local() or sym.is_parameter() or sym.is_free() or sym.is_imported():
            continue
        # 剩下是 global 引用 -> 必须存在于模块顶层或 builtins
        if name in root_names or name in _BUILTIN_NAMES:
            continue
        problems.append((name, st.get_name()))
    for child in st.get_children():
        _check_table(child, root_names, problems)


def scan_dir(root: pathlib.Path) -> list:
    """扫描目录下所有 .py，返回 [(文件, 块名, 名字), ...]"""
    problems = []
    for p in sorted(root.rglob('*.py')):
        try:
            code = p.read_text(encoding='utf-8')
        except Exception:
            continue
        st = symtable.symtable(code, str(p), 'exec')
        root_names = {s.get_name() for s in st.get_symbols()}
        found = []
        _check_table(st, root_names, found)
        for name, block in found:
            problems.append((p, block, name))
    return problems


if __name__ == '__main__':
    target = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('源码')
    problems = scan_dir(target)
    for p, block, name in problems:
        print(f'{p}: block={block} 未定义引用 -> {name}')
    if problems:
        print(f'---\n共发现 {len(problems)} 处问题，请修复后再打包！')
        sys.exit(1)
    print('---\n全部干净，可以打包。')
