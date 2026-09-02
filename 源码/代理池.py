# -*- coding: utf-8 -*-
"""代理池管理 (P0-1): 多代理列表 + 按域稳定分配 + 失败降权/冷却。

设计 (文档/反爬库选型评估与优化清单.md §6-P0-1):
- 配置: captcha_config.json 的 "proxies" 列表 (优先), 兼容原 "request_proxy" 单点
- 默认空池 = 直连不变 (当前目标站点多数无需代理)
- get(domain): 按域名稳定取一个健康代理 (同域同代理, 避免会话跨 IP 触发风控)
- mark_failed(proxy): 失败降权 + 短冷却; 连续失败 N 次移出可用
- 线程安全; 旁路静默 (代理不可用时返回 None 走直连)

用法:
    import 代理池
    pool = 代理池.get_pool()                 # 单例
    p = pool.get('example.com')              # -> {'http':..,'https':..} 或 None
    pool.mark_failed('example.com')          # 失败反馈
"""
import json
import os
import random
import threading
import time
from pathlib import Path

_LOCK = threading.Lock()
_POOL = None


def _config_proxies():
    """从 captcha_config.json 读取 proxies 列表 (兼容 request_proxy)。"""
    try:
        import _path_utils
        path = _path_utils.resolve_data_file("captcha_config.json")
        if os.path.isfile(path):
            cfg = json.loads(Path(path).read_text(encoding="utf-8"))
        else:
            return []
    except Exception:
        return []
    items = cfg.get("proxies") or []
    if isinstance(items, str):
        items = [x.strip() for x in items.split(",") if x.strip()]
    single = cfg.get("request_proxy") or ""
    if single and single not in items:
        items.append(single)
    return items


class ProxyPool:
    """轻量代理池: 列表 + 每代理健康状态。"""

    def __init__(self, proxies=None):
        raw = proxies if proxies is not None else _config_proxies()
        self._items = {}
        for p in raw:
            if p:
                self._items[p] = {"失败": 0, "冷却截止": 0.0, "域绑定": {}}

    def __len__(self):
        return len(self._items)

    def _healthy(self, proxy):
        st = self._items.get(proxy)
        if not st:
            return False
        if st["冷却截止"] > time.time():
            return False
        return st["失败"] < 5

    def get(self, domain=""):
        """取一个健康代理 (同域优先复用已绑定代理); 无可用返回 None(直连)。"""
        with _LOCK:
            if not self._items:
                return None
            # 同域复用
            for p, st in self._items.items():
                if st["域绑定"].get(domain) and self._healthy(p):
                    return self._wrap(p)
            healthy = [p for p in self._items if self._healthy(p)]
            if not healthy:
                return None
            p = random.choice(healthy)
            if domain:
                self._items[p]["域绑定"][domain] = time.time()
            return self._wrap(p)

    def mark_failed(self, proxy=None, domain=""):
        """失败反馈: 降权 + 短冷却 (同域绑定被解除, 下次换代理)。"""
        with _LOCK:
            if proxy and proxy in self._items:
                st = self._items[proxy]
                st["失败"] += 1
                st["冷却截止"] = time.time() + 60 * (st["失败"] + 1)
                if domain:
                    st["域绑定"].pop(domain, None)
                return
            # 未指定 proxy: 解除该域所有绑定, 强制换
            for st in self._items.values():
                st["域绑定"].pop(domain, None)

    def _wrap(self, proxy):
        if proxy.startswith(("http://", "https://", "socks5://")):
            url = proxy
        else:
            url = "http://" + proxy
        return {"http": url, "https": url}


def get_pool() -> ProxyPool:
    global _POOL
    if _POOL is None:
        with _LOCK:
            if _POOL is None:
                _POOL = ProxyPool()
    return _POOL
