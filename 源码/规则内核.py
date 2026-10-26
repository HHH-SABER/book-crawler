# -*- coding: utf-8 -*-
"""规则内核：站点策略阶段词汇的**只读** IR 导出（S1 第一步，2026-10-24）。

为什么要有它
------------
站点脱钩机制的全部行为都从 `sites_config.适配器策略(url, 阶段, **上下文)` 进出，
但"一共有哪些阶段、各自在哪儿被调用、哪些适配器声明实现了哪些阶段"此前**只存在于
阅读代码的人的脑子里**。S1（把规则内核抽成 IR）要求先能**描述现状**，否则
"IR 重放 == 现行为" 没有可比对的基准。

本模块只做三件事，且**全部只读**（不 import 爬虫.py、不改任何全局、不碰网络）：
1. `扫描阶段清单()` —— AST 扫源码里 `_站点策略(...)` / `适配器策略(...)` 调用，
   把**字符串字面量**的阶段名汇集起来（附出现次数与位置），得到权威阶段词汇表；
2. `声明阶段(源码)` —— 从适配器源码里提取它**声明实现**的阶段
   （`阶段 == 'x'` / `阶段 in ('x', 'y')` 两种写法）；
3. `导出IR()` —— 汇总成 `{'阶段': {...}, '适配器': {...}}` 的只读快照。

边界（刻意为之）
----------------
- 不含任何站点域名/书名（IR 只描述**机制**，站点资产仍在 gitignored 的本地目录）；
- 不做运行时探测（不构造适配器、不发请求）——纯静态，稳定可缓存；
- 不改变任何抓取行为：本模块没有调用方（除测试），是"护栏 + 文档"。
"""
import ast
import hashlib
import pathlib

#: 分发入口的两个函数名（`爬虫.py::_站点策略` 是旧名，`sites_config.适配器策略` 是新名）
_入口名 = ('_站点策略', '适配器策略')


def _源码目录() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent


def 扫描阶段清单(文件列表=None) -> dict:
    """扫源码里所有分发调用的**阶段字面量**。

    只认"第二个位置参数是字符串常量"的调用（`适配器策略(url, '目录')`）；
    变量传入的阶段（如透传 `阶段`）不计入 —— 那是转发，不是新增词汇。

    Args:
        文件列表: 要扫的 .py 路径列表；None=源码目录下全部 .py

    Returns:
        {阶段: {'次数': int, '位置': ['文件名:行号', ...]}}
    """
    if 文件列表 is None:
        文件列表 = sorted(_源码目录().rglob('*.py'))
    结果 = {}
    for f in 文件列表:
        f = pathlib.Path(f)
        try:
            树 = ast.parse(f.read_text(encoding='utf-8', errors='replace'))
        except (SyntaxError, OSError):
            continue
        for 节点 in ast.walk(树):
            if not isinstance(节点, ast.Call):
                continue
            函数名 = ''
            if isinstance(节点.func, ast.Name):
                函数名 = 节点.func.id
            elif isinstance(节点.func, ast.Attribute):
                函数名 = 节点.func.attr
            if 函数名 not in _入口名:
                continue
            if len(节点.args) < 2:
                continue
            第二 = 节点.args[1]
            if not (isinstance(第二, ast.Constant) and isinstance(第二.value, str)):
                continue
            阶段 = 第二.value
            桶 = 结果.setdefault(阶段, {'次数': 0, '位置': []})
            桶['次数'] += 1
            桶['位置'].append(f'{f.name}:{节点.lineno}')
    return 结果


def 声明阶段(源码: str) -> list:
    """从适配器源码里提取它**声明实现**的阶段名（静态解析，只读）。

    识别两种常见写法::

        阶段 == '目录规范化'          # 单值分支
        阶段 in ('目录兜底解析', 'x')  # 多值分支

    Returns:
        去重后的阶段名列表（保持源码出现顺序）
    """
    try:
        树 = ast.parse(源码)
    except SyntaxError:
        return []
    结果 = []
    for 节点 in ast.walk(树):
        if not isinstance(节点, ast.Compare):
            continue
        左 = 节点.left
        if not (isinstance(左, ast.Name) and 左.id == '阶段'):
            continue
        for 操作, 右 in zip(节点.ops, 节点.comparators):
            if not isinstance(操作, (ast.Eq, ast.In)):
                continue
            候选 = []
            if isinstance(右, ast.Constant) and isinstance(右.value, str):
                候选 = [右.value]
            elif isinstance(右, (ast.Tuple, ast.List, ast.Set)):
                for 元素 in 右.elts:
                    if isinstance(元素, ast.Constant) and isinstance(元素.value, str):
                        候选.append(元素.value)
            for 名 in 候选:
                if 名 not in 结果:
                    结果.append(名)
    return 结果


def 导出适配器IR(适配器表=None, 脱敏: bool = True) -> dict:
    """把已注册适配器导出成只读 IR。

    Args:
        适配器表: {代号或域名: 适配器 dict}；None ⇒ 尝试读 sites_config 的公开状态，
                 读不到（公开形态/未加载）则返回空 dict，不抛异常。
        脱敏: 默认 **True** —— 只输出 `域名指纹`（sha256 前 12 位），不输出真实域名。
              IR 是"可能被 dump 成文件/贴进文档"的东西，默认就该是能公开的形态；
              需要原始域名做比对时才显式传 `脱敏=False`（结果不要入库）。

    Returns:
        {名称: {'域名指纹': str, '有站点策略': bool, '声明阶段': [str]}}
        （`脱敏=False` 时字段名为 `域名`）
    """
    if 适配器表 is None:
        try:
            import sites_config
            sites_config.load_adapters()
            适配器表 = dict(getattr(sites_config, 'ADAPTERS', {}) or {})
        except Exception:      # 刻意静默: IR 是辅助工具, 适配器表不可用即返回空快照
            return {}
    IR = {}
    for 名称, 适配器 in (适配器表 or {}).items():
        if not isinstance(适配器, dict):
            continue
        钩子 = 适配器.get('站点策略')
        域 = str(适配器.get('域名') or 适配器.get('domain') or '')
        IR[str(名称)] = {
            ('域名指纹' if 脱敏 else '域名'): (_主机指纹(域) if 脱敏 else 域),
            '有站点策略': callable(钩子),
            '声明阶段': 声明阶段(_函数源码(钩子)) if callable(钩子) else [],
        }
    return IR


def _主机指纹(域名: str) -> str:
    """域名的不可逆指纹（空域名返回空串）。"""
    if not 域名:
        return ''
    return hashlib.sha256(域名.lower().encode('utf-8')).hexdigest()[:12]


def _函数源码(函数) -> str:
    """尽力取函数源码（内联模块可用; 取不到返回空串, 不抛）。

    注意: 嵌套函数（定义在别的函数/测试方法里）取出的源码带缩进，
    ``ast.parse`` 会直接 IndentationError —— 必须 dedent。
    """
    try:
        import inspect
        import textwrap
        return textwrap.dedent(inspect.getsource(函数))
    except (OSError, TypeError):
        return ''


def 导出IR(适配器表=None) -> dict:
    """汇总只读 IR 快照：阶段词汇表 + 适配器声明。"""
    return {'阶段': 扫描阶段清单(), '适配器': 导出适配器IR(适配器表)}


if __name__ == '__main__':
    import json
    print(json.dumps(导出IR(), ensure_ascii=False, indent=2))
