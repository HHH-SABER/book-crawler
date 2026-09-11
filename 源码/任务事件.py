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

正则解析**保留为兜底**, 与事件并行:

    GUI 状态 = 事件(优先, 有则直接赋值) ⊕ 正则(兜底, 覆盖尚未发出事件的路径)

因此第一版只需给高价值路径接上事件即可, 覆盖不全也不会退化 —— 但**迁移完成后**
`测试/test_log_contract.py` 里的契约文案将不再是"数据协议", 改文案才真正安全。

## 约束 (与项目线程纪律一致)

- **无订阅方时零成本**: CLI / 纯爬虫场景直接 return, 不引入任何开销;
- **订阅方异常绝不外溢**: 逐个 try/except, 回调抛错不能影响抓取主流程;
- **按线程隔离**: 每个 worker 只发给"本线程注册的订阅方",
  与 `_ThreadAwareStdout` 的线程模型一致, 多任务并发互不串台。
"""
import threading

_线程槽 = threading.local()


def 订阅(接收方) -> None:
    """把接收方注册到**当前线程**。

    接收方需实现 `处理任务事件(类型: str, 数据: dict)`。
    重复注册同一对象不会重复接收。
    """
    接收方列表 = getattr(_线程槽, '接收方', None)
    if 接收方列表 is None:
        _线程槽.接收方 = [接收方]
    elif all(接收方 is not x for x in 接收方列表):
        接收方列表.append(接收方)


def 退订(接收方=None) -> None:
    """退订; 不传参数则清空当前线程的全部订阅方"""
    if 接收方 is None:
        _线程槽.接收方 = []
        return
    接收方列表 = getattr(_线程槽, '接收方', None)
    if not 接收方列表:
        return
    _线程槽.接收方 = [x for x in 接收方列表 if x is not 接收方]


def 有订阅方() -> bool:
    """当前线程是否有订阅方 (供调用方跳过昂贵的字段计算)"""
    return bool(getattr(_线程槽, '接收方', None))


def 发布(类型: str, **数据) -> None:
    """发布一个任务事件。无订阅方时立即返回 (零成本)。

    Args:
        类型: 事件类型, 见 TaskManager.处理任务事件 的分发表
        数据: 事件字段 (全部为基本类型)
    """
    接收方列表 = getattr(_线程槽, '接收方', None)
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
