# -*- coding: utf-8 -*-
"""风控事件日志 (P2-1): 请求/反爬/验证码/任务事件追加到 数据/风控事件-YYYYMMDD.jsonl。

设计 (文档/新站接入与命中监控设计.md §3):
- 事件源: request / anti_spider / captcha / task_result / content_issue
- 写入: append-only JSONL, 按天轮转; 内存缓冲满 N 条或显式 flush 才落盘 (热路径零阻塞)
- 旁路: 任何失败静默忽略, 绝不影响抓取 (与 日志.py 同策略)
- 消费: 脚本/monitor_summary.py 按域聚合 24h 健康度 (P2-2)

用法:
    import 风控事件
    风控事件.add("request", {"域名": host, "status": 200, "耗时": 0.4, "引擎": "requests"})
    风控事件.add("anti_spider", {"域名": host, "类型": "rate_limit", "建议": {...}})
    风控事件.add("captcha", {"域名": host, "类型": "ocr", "结果": "success"})
    风控事件.add("task_result", {"域名": host, "新增": 3, "失败": 0, "目标": 120})
    风控事件.flush()   # 任务收尾时调用; 进程退出由 atexit 兜底
"""
import atexit
import json
import os
import threading
import time

_FLUSH_SIZE = 60
_BUFFER = []
_LOCK = threading.Lock()
_PATH = None
_ENABLED = True


def _log_dir():
    try:
        import _path_utils
        base = _path_utils.get_app_base_dir()
    except Exception:
        base = os.path.dirname(os.path.abspath(__file__))
    d = os.path.join(base, "数据")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def _daily_path():
    return os.path.join(_log_dir(), f"风控事件-{time.strftime('%Y%m%d')}.jsonl")


def add(event_type: str, fields: dict):
    """追加一条风控事件 (线程安全, 缓冲)。"""
    if not _ENABLED:
        return
    try:
        rec = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "type": event_type, **fields}
        with _LOCK:
            _BUFFER.append(rec)
            if len(_BUFFER) >= _FLUSH_SIZE:
                _flush_locked()
    except Exception:
        pass


def flush():
    """把缓冲落盘 (任务收尾/close 时调用)。"""
    try:
        with _LOCK:
            _flush_locked()
    except Exception:
        pass


def _flush_locked():
    global _PATH, _BUFFER
    if not _BUFFER:
        return
    path = _daily_path()
    try:
        with open(path, "a", encoding="utf-8") as f:
            for rec in _BUFFER:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
    _BUFFER = []


atexit.register(flush)


# ============================================================
# 域级冷却状态 (P2-3): 反爬命中后跨 run 持久化退避
# 数据/域状态.json 结构: {"<域名>": {"冷却截止": <epoch>, "最后命中": <type>}}
# ============================================================

def _state_path():
    return os.path.join(_log_dir(), "域状态.json")


def _load_state():
    try:
        with open(_state_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def get_domain_cooldown(domain: str) -> float:
    """该域冷却剩余秒数 (<=0 表示无需等待)。"""
    st = _load_state().get(domain)
    if not st:
        return 0.0
    try:
        return float(st.get("冷却截止", 0)) - time.time()
    except Exception:
        return 0.0


def set_domain_cooldown(domain: str, seconds: float, reason: str = ""):
    """给域设置冷却 (seconds 秒), 用于跨 run 自动退避。"""
    try:
        st = _load_state()
        st[domain] = {"冷却截止": time.time() + max(seconds, 0),
                      "最后命中": reason}
        with _LOCK:
            with open(_state_path(), "w", encoding="utf-8") as f:
                json.dump(st, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def clear_domain_cooldown(domain: str):
    try:
        st = _load_state()
        if domain in st:
            del st[domain]
            with _LOCK:
                with open(_state_path(), "w", encoding="utf-8") as f:
                    json.dump(st, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


# ============================================================
# 聚合统计 API (P2-2/2-4 共用): monitor_summary.py 与 GUI 站点健康度列
# ============================================================

def summary_by_domain(hours: int = 24) -> dict:
    """近 N 小时按域聚合: {域名: {anti:{type:n}, captcha:{result:n}, task:{完成,失败,目标,runs}}}"""
    import time as _t
    agg = {}
    cutoff = _t.time() - hours * 3600
    d = _log_dir()
    try:
        files = [os.path.join(d, f) for f in os.listdir(d)
                 if f.startswith("风控事件-") and f.endswith(".jsonl")]
    except OSError:
        files = []
    for fp in sorted(files)[-3:]:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        ts = _t.mktime(_t.strptime(rec.get("t", ""), "%Y-%m-%d %H:%M:%S"))
                    except Exception:
                        continue
                    if ts < cutoff:
                        continue
                    dom = agg.setdefault(rec.get("域名") or "?", {
                        "anti": {}, "captcha": {}, "task": {"完成": 0, "失败": 0, "目标": 0, "runs": 0}})
                    kind = rec.get("type")
                    if kind == "anti_spider":
                        dom["anti"][rec.get("类型", "?")] = dom["anti"].get(rec.get("类型", "?"), 0) + 1
                    elif kind == "captcha":
                        k = rec.get("结果", "?")
                        dom["captcha"][k] = dom["captcha"].get(k, 0) + 1
                    elif kind == "task_result":
                        dom["task"]["完成"] += rec.get("完成", 0)
                        dom["task"]["失败"] += rec.get("失败", 0)
                        dom["task"]["目标"] += rec.get("目标", 0)
                        dom["task"]["runs"] += 1
        except Exception:
            continue
    return agg
