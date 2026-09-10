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
    "启用": True,          # 桌面客户端启动时内嵌远控 (常驻: 客户端开着即服务在)
    "端口": 8760,
    "绑定": "127.0.0.1",   # 默认仅本机; 手机访问见 文档/手机远控方案设计.md 使用指南
    "token": "",           # 首建时自动生成 (32 位十六进制)
    # 外链前缀: 推送/分享链接的基地址 (如 https://主机名.tailxxxx.ts.net),
    # 留空则推送不含链接
    "外链前缀": "",
    # 完成推送 (④): 二选一或都开; 地址填你自己的服务
    "推送": {
        "bark": {"启用": False, "地址": ""},          # 如 https://api.day.app/你的key
        "ntfy": {"启用": False, "服务器": "https://ntfy.sh", "主题": ""},
    },
}

_推送默认 = dict(_DEFAULTS["推送"])


def _合并默认(cfg: dict) -> dict:
    """嵌套字段深合并: 磁盘缺键/半配置时补齐默认, 防 KeyError"""
    合并 = dict(_DEFAULTS)
    合并.update({k: v for k, v in cfg.items() if k not in ("推送",)})
    推送 = cfg.get("推送") if isinstance(cfg.get("推送"), dict) else {}
    合并["推送"] = {}
    for 渠道, 默认 in _推送默认.items():
        合并["推送"][渠道] = {**默认, **(推送.get(渠道) or {})}
    return 合并


def _配置路径() -> str:
    base = get_app_base_dir()
    return os.path.join(base, "数据", _CONFIG_NAME)


def _加载或创建() -> dict:
    path = _配置路径()
    cfg = dict(_DEFAULTS)
    disk = None
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                _d = json.load(f)
            if isinstance(_d, dict):
                disk = _d
                cfg = _合并默认(_d)   # 深合并: 磁盘半配置也不缺键
        except (OSError, ValueError):
            pass  # 配置损坏 → 用默认重建 (token 会更换, 属预期)
    if not cfg.get("token"):
        cfg["token"] = secrets.token_hex(16)
        _原子写(path, cfg)
        return cfg
    # 老配置缺新字段 (首次引入的 推送/外链前缀) → 落盘补齐, 便于用户直接编辑
    if disk is None or "推送" not in disk or "外链前缀" not in disk:
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
