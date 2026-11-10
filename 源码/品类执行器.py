# -*- coding: utf-8 -*-
"""内容品类执行器注册表（统一内容库改造 D/6，2026-11-10）。

设计目的：**新增一个内容品类不必新增页面、也不必改 TaskManager**。
品类是任务属性；导航、任务表、日志、停止、历史全都复用同一套。

    ┌ 小说 → TaskManager._执行抓取 原生主体（完全不经过本模块）
    └ 其他 → 本注册表 → 对应「XX任务.py」的 执行(管理器, task, 参数)

为什么用「模块名注册表」而不是 if/elif：以后加文章/音频/图集，只要
`注册('文章', '文章任务')` 或往 `_模块表` 加一行，TaskManager 那一个
早退分支永远不变；且 importlib 是**惰性导入** —— 没跑漫画任务时
selenium / PIL 一个都不会被加载（与小说动态 import 爬虫同款）。

铁律对齐（实施计划 §H-3）：非小说链路可整体关闭 —— 只要不注册执行器，
该类任务会在启动时以明确错误失败，网文主链路零影响。
"""
import importlib

# 品类 → 执行器模块（模块位于 源码/ 下，故调用方须保证该目录在 sys.path）
_模块表 = {
    '漫画': '漫画任务',
}


def 注册(品类: str, 模块名: str) -> None:
    """注册一个品类的执行器模块（供插件/后续品类扩展调用）。"""
    if not 品类 or not 模块名:
        raise ValueError('品类与模块名均不能为空')
    _模块表[品类] = 模块名


def 已注册() -> tuple:
    return tuple(_模块表)


def 执行(管理器, task, 参数: dict) -> None:
    """分派并执行一个非小说任务；异常向上抛给 TaskManager._任务异常收尾。"""
    品类 = getattr(task, '品类', '小说')
    if 品类 == '小说':
        raise ValueError('小说由 TaskManager 原生执行，不应走品类执行器')
    模块名 = _模块表.get(品类)
    if not 模块名:
        raise ValueError(
            f'品类 {品类!r} 尚未注册执行器（已注册: {已注册()}）')
    模块 = importlib.import_module(模块名)
    执行器 = getattr(模块, '执行', None)
    if not callable(执行器):
        raise TypeError(f'{模块名}.执行 不可调用')
    return 执行器(管理器, task, dict(参数))
