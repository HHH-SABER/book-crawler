# -*- coding: utf-8 -*-
"""远控服务配置: 数据/远控配置.json 的加载/首建 (token 自动生成)。

设计要点:
- 首次运行自动生成配置 (含随机 token), 之后只读
- 惰性单例 + 线程锁: 多线程并发首访只生成一次
- 原子写 (tmp + os.replace), 对齐项目编码规约
- 测试可直接给 服务._CONFIG 赋值绕过磁盘
"""
import json
import os
import secrets
import threading

from _path_utils import get_app_base_dir

_CONFIG_LOCK = threading.Lock()
_CONFIG: dict | None = None

_CONFIG_NAME = "远控配置.json"

_DEFAULTS = {
    "端口": 8760,
    "绑定": "127.0.0.1",   # 默认仅本机; 对手机服务用 tailscale serve 反代, 不裸绑 0.0.0.0
    "token": "",           # 首建时自动生成 (32 位十六进制)
}


def _配置路径() -> str:
    base = get_app_base_dir()
    return os.path.join(base, "数据", _CONFIG_NAME)


def _加载或创建() -> dict:
    path = _配置路径()
    cfg = dict(_DEFAULTS)
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                disk = json.load(f)
            if isinstance(disk, dict):
                cfg.update(disk)
        except (OSError, ValueError):
            pass  # 配置损坏 → 用默认重建 (token 会更换, 属预期)
    if not cfg.get("token"):
        cfg["token"] = secrets.token_hex(16)
        _原子写(path, cfg)
    return cfg


def _原子写(path: str, cfg: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def 取配置() -> dict:
    """惰性获取配置单例 (线程安全); 返回内部 dict 的引用, 调用方勿改"""
    global _CONFIG
    if _CONFIG is None:
        with _CONFIG_LOCK:
            if _CONFIG is None:
                _CONFIG = _加载或创建()
    return _CONFIG
