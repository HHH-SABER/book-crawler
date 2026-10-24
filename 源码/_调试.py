# -*- coding: utf-8 -*-
"""统一调试留痕（G1，2026-10-24）。

原先 `_dbg()` 在 18 个模块里各写了一份**完全相同**的实现（裸 except 留痕用）。
收敛到本模块后：改日志格式只改一处，且新增模块不再复制粘贴。

行为与旧实现逐字等价：
- 日志单例不可用（容错导入失败）时静默跳过；
- 落盘 DEBUG 级，不做 console 镜像（避免刷屏）；
- 自身写日志失败也不能抛 —— 否则"留痕代码"会把故障放大。
"""


def _dbg(source: str, message: str):
    """裸 except 吞异常留痕 (DEBUG 级: 只落盘不 console 镜像, 避免刷屏)"""
    try:
        import 日志 as _app_log
    except Exception:      # 刻意静默: 日志模块不可用时留痕通道整体降级为无
        return
    try:
        _app_log.debug(source, message)
    except Exception:
        pass  # 刻意静默: 留痕失败不能反向打断调用方
