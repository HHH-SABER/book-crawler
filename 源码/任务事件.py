# -*- coding: utf-8 -*-
"""结构化任务事件通道 (U19)。

## 为什么需要它

GUI 的运行时数据 (进度 / 引擎 / 反爬类型 / 质检分 / 增量跳过) 目前全靠
"爬虫 print 中文日志 → TaskManager 用 14 条正则把状态解析回来"。
**日志文案因此成了隐式数据协议**: 改一句话就可能静默断掉界面状态,
只能靠 `测试/test_log_contract.py` 事后兜底。

本模块提供显式通道: 爬虫在关键节点 `发布('进度', 当前=i, 总数=n)`,
订阅方 (TaskManager 的任务日志重定向器) 直接取字段更新状态, 与文案解耦。

## 渐进式策略 (不一次性替换)

正则解析保留为兜底 (U19 二阶段起默认停用, 置 True 一行回退):

    GUI 状态 = 事件(优先, 有则直接赋值) ⊕ 正则(兜底, 默认停用)

## 线程模型 (修复 H1: 并行抓取时 worker 事件丢失)

订阅发生在任务子线程; 但并行抓取 (threads>1) 时章节 worker 在
ThreadPoolExecutor 里经 `copy_context().run(...)` 执行 —— **threading.local
不随 copy_context 传播**, worker 里发布的 质检/引擎/反爬 事件曾全部静默丢失
(v2.4.24 增量审查 H1; 串行不受影响, 故当时的差分验证未暴露)。

改用 `contextvars.ContextVar` (与 task_manager 的 `_WRITER_CTX` 同机制):

- 任务线程 `订阅()` → `copy_context()` 快照含订阅列表 → worker 里 `发布()` 可见;
- 未订阅的裸线程 / CLI → `get()` 返回默认值 None → `发布()` 零成本直返;
- 退订发生在 `with ThreadPoolExecutor` 退出之后 (run_crawl 返回 → finally),
  无快照失效竞态。

## 约束 (与项目线程纪律一致)

- **无订阅方时零成本**: CLI / 纯爬虫场景直接 return, 不引入任何开销;
- **订阅方异常绝不外溢**: 逐个 try/except, 回调抛错不能影响抓取主流程;
- **按上下文隔离**: 未注册的线程/上下文收不到事件, 多任务并发互不串台。
"""
import contextvars

_订阅槽 = contextvars.ContextVar('任务事件_订阅方', default=None)


def 订阅(接收方) -> None:
    """把接收方注册到**当前上下文** (随 copy_context 传播到章节 worker)。

    接收方需实现 `处理任务事件(类型: str, 数据: dict)`。
    重复注册同一对象不会重复接收。
    """
    接收方列表 = _订阅槽.get()
    if 接收方列表 is None:
        _订阅槽.set([接收方])
    elif all(接收方 is not x for x in 接收方列表):
        接收方列表.append(接收方)


def 退订(接收方=None) -> None:
    """退订; 不传参数则清空当前上下文的全部订阅方"""
    if 接收方 is None:
        _订阅槽.set([])
        return
    接收方列表 = _订阅槽.get()
    if not 接收方列表:
        return
    _订阅槽.set([x for x in 接收方列表 if x is not 接收方])


def 有订阅方() -> bool:
    """当前上下文是否有订阅方 (供调用方跳过昂贵的字段计算)"""
    return bool(_订阅槽.get())


def 发布(类型: str, **数据) -> None:
    """发布一个任务事件。无订阅方时立即返回 (零成本)。

    Args:
        类型: 事件类型, 见 TaskManager.处理任务事件 的分发表
        数据: 事件字段 (全部为基本类型)
    """
    接收方列表 = _订阅槽.get()
    if not 接收方列表:
        return
    for 接收方 in list(接收方列表):
        try:
            接收方.处理任务事件(类型, 数据)
        except Exception as e:      # 订阅方出错绝不影响抓取
            try:
                import 日志 as _app_log
                _app_log.get('任务事件').debug(
                    f'订阅方处理事件失败: {type(e).__name__}: {e} (类型={类型})')
            except Exception:
                pass
