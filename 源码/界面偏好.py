# -*- coding: utf-8 -*-
"""界面偏好: `状态根/数据/界面偏好.json` 的读写 (轻量, 原子写)。

用途 (2026-10-04 修八项需求 #2 的"静音"缺口): 保存与界面体验相关的用户开关。
目前只有 `提示音` —— 任务终态提示音是否播放 (关掉后仅静默, 通知 SnackBar 照常弹)。

约定 (对齐项目编码规约):
- 状态文件一律 tmp + `os.replace`, 不直接 `write_text`;
- **读失败/文件损坏一律回默认, 绝不抛** —— 本模块在 UI 启动路径上被调用;
- 未知键原样保留 (向前兼容: 新版本写的键, 旧版本读回时不丢)。
"""
import json
import os
import threading

_锁 = threading.Lock()
_缓存: dict | None = None

_默认 = {
    "提示音": True,      # 任务终态提示音 (关掉后只是不响, 通知仍弹)
}

_文件名 = "界面偏好.json"


def _路径() -> str:
    from _path_utils import get_state_root
    return os.path.join(get_state_root(), "数据", _文件名)


def _载入() -> dict:
    global _缓存
    if _缓存 is not None:
        return _缓存
    cfg = dict(_默认)
    try:
        with open(_路径(), "r", encoding="utf-8") as f:
            disk = json.load(f)
        if isinstance(disk, dict):
            cfg.update(disk)
    except (OSError, ValueError):
        pass  # 缺失/损坏 → 用默认值 (启动路径不能因此崩)
    _缓存 = cfg
    return cfg


def 取(键: str, 默认=None):
    """读偏好; 任何异常都回落到 `默认` (或内置默认)"""
    try:
        with _锁:
            cfg = _载入()
        if 键 in cfg:
            return cfg[键]
    except Exception:
        pass  # 刻意静默: 偏好读失败不该影响主流程, 下面统一回默认
    return _默认.get(键) if 默认 is None else 默认


def 设置(键: str, 值) -> bool:
    """原子写回并同步缓存; 失败返回 False (调用方自行留痕)"""
    global _缓存
    try:
        with _锁:
            cfg = dict(_载入())
            cfg[键] = 值
            path = _路径()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = f"{path}.tmp.{os.getpid()}.{threading.get_ident()}"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
            _缓存 = cfg
        return True
    except OSError:
        return False


def 清空缓存() -> None:
    """测试用: 丢弃内存缓存, 下次重新读盘"""
    global _缓存
    with _锁:
        _缓存 = None
