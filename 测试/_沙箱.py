# -*- coding: utf-8 -*-
"""测试级状态沙箱 (module 引导, 2026-10-02 事故根治)。

## 为什么用模块级而非仅 测试/__init__.py

AGENTS 门禁命令 `python -m unittest discover -s 测试` 会把 测试/ 下每个
test 文件当**顶层模块** import, **不执行** 测试/__init__.py (top_level_dir
== start_dir)。故仅靠包 __init__ 兜底在该命令下不生效。

真正有效的是: 实例化 TaskManager 且不自行隔离的测试文件, 在 import 区显式
`import _沙箱` —— 模块级代码在 import 时必然执行, 把 LOCALAPPDATA 钉到一次性
临时目录并清 _path_utils._STATE_ROOT 陈旧缓存, 令后续 get_state_root() 惰性
重算到沙箱。此后该进程内所有任务历史/书架/远控配置/站点基线/阅读进度/风控
事件落盘全进沙箱, 与用户真实数据物理隔离。

个别用例另有 _隔离状态根 (还原目标即本沙箱), 两层叠加只会更严, 不冲突。
沙箱目录不主动删 (测试期短, 删除可能干扰并发用例), 交系统 temp 回收。
"""
import os
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent          # 项目根
for _p in (str(_ROOT / '源码'), str(_ROOT / '源码' / 'gui_components')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault('_QWEN_TEST_SANDBOX_ROOT',
                      tempfile.mkdtemp(prefix='qwen_test_state_'))
os.environ['LOCALAPPDATA'] = os.environ['_QWEN_TEST_SANDBOX_ROOT']
try:
    import _path_utils               # noqa: E402
    _path_utils._STATE_ROOT = None   # 清缓存, 强制首次 get_state_root 惰性重算到沙箱
except Exception:                    # pragma: no cover - 引导兜底不应中断收集
    pass
