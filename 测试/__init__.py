# -*- coding: utf-8 -*-
"""测试包引导: 全局状态根沙箱 (2026-10-02 事故根治)。

## 为什么需要

`python -m unittest discover -s 测试` 跑全量时, 部分测试
(test_ledger_fixes / test_log_contract / test_remote_service / _test_task_metrics)
实例化 TaskManager 却不隔离状态根, `get_state_root()` 解析到**真实**
%LOCALAPPDATA%\\小说爬虫, 落盘把用户真实的 任务历史.json 覆盖成空, 并连带
改动 站点基线.json / 阅读进度.json —— 测试污染生产数据, 2026-10-02 实测事故。

## 根治方式

discover 会先 import 本包 (执行此 __init__.py) 再 import 各 test_*.py。
故在此把 LOCALAPPDATA 钉到一次性临时目录, 并清空 _path_utils._STATE_ROOT
陈旧缓存, 令首次 get_state_root() 惰性重算到沙箱 (走完整建目录流程, 不掩盖
落盘 bug)。此后所有离线测试的状态读写 (任务历史/书架/远控配置/爬取历史/
站点历史/风控事件/阅读进度...) 一律落进沙箱, 与用户真实数据物理隔离。

## 与既有单测级隔离兼容

个别用例自带 `_隔离状态根` (把 _STATE_ROOT 置 None 重算到各自 mkdtemp,
addCleanup 还原)。它们还原的目标是本沙箱 (而非真实根), 因此关闭真实数据仍
不被触碰; 两层隔离叠加只会更严, 不冲突。

沙箱目录不主动删除, 交系统 temp 回收 (测试期短, 且删除可能干扰并发用例)。
"""
import os
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(_ROOT / '源码'), str(_ROOT / '源码' / 'gui_components')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 一次性状态沙箱: LOCALAPPDATA 之下再拼 小说爬虫 即 get_state_root 结果
_SANDBOX = tempfile.mkdtemp(prefix='qwen_test_state_')
os.environ['LOCALAPPDATA'] = _SANDBOX
try:
    import _path_utils               # noqa: E402
    _path_utils._STATE_ROOT = None   # 清陈旧缓存, 强制惰性重算到沙箱
except Exception:                    # pragma: no cover - 引导期兜底不应炸收集
    pass
