# -*- coding: utf-8 -*-
"""打包前必跑：扫描源码中"被引用但未定义"的名字（运行时 NameError 预检）

背景：`import gui_app` 只验证导入，查不出函数体内的 NameError（如漏 import）。
本脚本用 Python 标准库 symtable 做作用域分析，一次性扫出全部未定义引用。

v2.4.20 增补：**from-import 名字解析检查**（v2.4.19 教训）——
    函数体内 `from gui_components.ui_fluent import MORANDI_TERTIARY_CONTAINER`
    这类写法，symtable 将其标为 is_imported()（合法绑定），名字在目标模块里
    根本不存在也查不出来，直到运行时才 ImportError（v2.4.19 首发实测：点关闭
    按钮直接强退）。现对**所有** from-import（含函数体内）做二次校验：
    仅当目标模块能解析到源码树内的 .py 文件时才校验——标准库/三方包跳过，
    不做 importlib 探测以免 import 副作用。

用法（在项目根目录运行）:
    ./.venv/Scripts/python.exe 脚本/check_undefined_refs.py [源码目录]

坑（已踩过，勿改逻辑）:
- symtable 把函数内"未定义引用"标为 is_global()，必须再核对模块顶层符号集，
  否则全部漏报（回归测试 1 专门验证此点）。
- `__file__` 等模块 dunder 是运行时自动提供的，需加入白名单。
- from-import 校验只针对解析到本项目源码树内的模块；目标文件顶层存在
  `import *` 时放弃校验该条（静态无法穷举其导出集）。
"""
import ast
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


# ====================================================================
# v2.4.20: from-import 名字解析检查
# ====================================================================

def _collect_defs(tree):
    """收集模块顶层绑定的名字集合 (定义/赋值/导入), 及是否含星号导入。

    - 顶层 def/class: 只记名字, 不深入函数体 (体内绑定是局部的, 不对外导出);
    - 其余语句 (if/try/for/with...) 整棵 walk: 模块级控制流里的 def/import
      兜底 (如 try/except ImportError: def 兜底函数) 同样是模块级名字;
      副作用: 深层函数体内的局部名也会被收进集合 —— 宁可放过不可错杀。
    """
    names = set()
    has_star = False
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
            continue
        for sub in ast.walk(node):
            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef,
                                ast.ClassDef)):
                names.add(sub.name)
            elif isinstance(sub, (ast.Import, ast.ImportFrom)):
                for alias in sub.names:
                    if alias.name == '*':
                        has_star = True
                    else:
                        names.add(alias.asname or alias.name.split('.')[0])
            elif isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                names.add(sub.id)
    return names, has_star


def _resolve_module(root: pathlib.Path, node: ast.ImportFrom,
                    current_file: pathlib.Path):
    """把 ImportFrom 解析为源码树内的候选定义文件集合。

    返回 (cands, base): cands=[文件, ...] (包 __init__.py 与 模块.py 都可能
    持有名字), base=包/模块对应目录 (供子模块存在性判断);
    None = 项目外模块/无法解析 -> 跳过校验 (标准库/三方包不做 import 探测)。
    """
    parts = node.module.split('.') if node.module else []
    if node.level == 0:
        if not parts:
            return None
        base = root.joinpath(*parts)
        try:
            base.resolve().relative_to(root.resolve())
        except ValueError:
            return None
    else:
        # 相对导入: level=1 从当前文件所在包起算
        base = current_file.parent
        for _ in range(node.level - 1):
            base = base.parent
        base = base.joinpath(*parts)
    cands = []
    init = base / '__init__.py'
    if init.is_file():
        cands.append(init)
    mod = base.parent / (base.name + '.py')
    if mod.is_file():
        cands.append(mod)
    if not cands:
        return None
    return cands, base


def _check_from_imports(tree, root: pathlib.Path, current_file: pathlib.Path,
                        cache: dict, problems):
    """校验本文件所有 from-import 的名字在目标模块顶层确实存在"""
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        解析 = _resolve_module(root, node, current_file)
        if 解析 is None:
            continue
        cands, base = 解析
        def_sets = []
        skip = False
        for c in cands:
            key = str(c)
            if key not in cache:
                try:
                    cache[key] = _collect_defs(ast.parse(
                        c.read_text(encoding='utf-8')))
                except Exception:
                    cache[key] = None      # 读不了/解析不了 -> 放弃该候选
            info = cache[key]
            if info is None:
                skip = True
                break
            def_sets.append(info)
        if skip:
            continue
        if any(has_star for _, has_star in def_sets):
            continue                        # 星号导入无法穷举导出, 放弃
        known = set()
        for names, _ in def_sets:
            known |= names
        # 相对导入补前导点 (ast 把 . 存进 level), 诊断输出才不歧义
        来源 = ('.' * node.level) + (node.module or '')
        for alias in node.names:
            if alias.name == '*':
                continue
            # `from 包 import 子模块` 是合法语法 (Python 自动导入包下子模块)
            if (base / f'{alias.name}.py').is_file() or \
                    (base / alias.name / '__init__.py').is_file():
                continue
            if alias.name not in known:
                problems.append((current_file, f'from {来源} import', alias.name))


def scan_dir(root: pathlib.Path) -> list:
    """扫描目录下所有 .py，返回 [(文件, 块名, 名字), ...]"""
    problems = []
    def_cache: dict = {}
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
        # v2.4.20: from-import 名字解析 (symtable 查不出的那一类)
        try:
            tree = ast.parse(code)
        except Exception:
            tree = None
        if tree is not None:
            _check_from_imports(tree, root, p, def_cache, problems)
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
