# -*- coding: utf-8 -*-
"""站点改版漂移检测 (P2-2): 任务收尾时对比该域历史基线, 命中率突降即告警。

原理 (文档/反爬库选型评估与优化清单.md §6-P2-2):
- 站点改版最常见信号 = 正文提取成功率/质检通过率骤降 (选择器失效/混淆变了)
- 数据/站点基线.json: {域名: {"样本数": n, "空章率": x, "短章率": y, "失败率": z}}
  每次任务收尾更新 (指数移动平均), 偏差超阈值 -> 写 风控事件(content_issue) +
  日志告警, 提示用 probe_adapter.py 重探该站。
- 旁路静默, 不影响抓取主流程。
"""
import json
import os
import threading
from pathlib import Path

_LOCK = threading.Lock()

# 告警阈值: 本次值 vs 基线 (均为 0~1 比率)
ALARM = {
    "空章率": 0.10,      # 基线+0.10 以上
    "短章率": 0.15,
    "失败率": 0.20,
    "最小样本": 3,        # 基线样本 < 3 时不比对 (避免新站误报)
}
_ALPHA = 0.3  # EMA 平滑系数


def _path():
    try:
        import _path_utils
        d = os.path.join(_path_utils.get_app_base_dir(), "数据")
    except Exception:
        d = os.path.dirname(os.path.abspath(__file__))
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return os.path.join(d, "站点基线.json")


def _load():
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(st):
    try:
        p = Path(_path()).resolve()   # pathlib 锚定, 防路径穿越
        p.parent.mkdir(parents=True, exist_ok=True)
        # M8: tmp + os.replace 原子替换 (写一半崩溃不再整体损坏)
        tmp = p.with_name(p.name + '.tmp')
        tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        os.replace(tmp, p)
    except Exception:
        pass


def _ema(old, new):
    if old is None:
        return new
    return round(old * (1 - _ALPHA) + new * _ALPHA, 4)


def report_task(domain: str, total: int, empty: int, short: int, failed: int) -> list:
    """任务收尾上报并检测漂移。

    Args:
        domain: 站点域名
        total: 本次目标章数 (>0)
        empty: 提取为空的章数
        short: 质检"过短/未通过"章数
        failed: 失败章数
    Returns:
        告警列表 (空 = 无漂移)
    """
    if not domain or total <= 0:
        return []
    cur = {"空章率": empty / total, "短章率": short / total, "失败率": failed / total}
    alarms = []
    drifted = False   # M9: 本次触发漂移告警时, 基线不被 EMA 吸收坏值
    try:
        with _LOCK:
            st = _load()
            base = st.get(domain)
            if base and base.get("样本数", 0) >= ALARM["最小样本"]:
                for k, v in cur.items():
                    bv = base.get(k)
                    if bv is not None and v > bv + ALARM[k]:
                        alarms.append(
                            f"⚠ {domain}: {k} 本次 {v:.0%} vs 基线 {bv:.0%} — 疑似站点改版, "
                            f"建议用 脚本/probe_adapter.py 重探")
                        drifted = True
            if drifted:
                # M9 修复: 告警时跳过 EMA 更新 —— 旧实现无条件吸收, 站点真改版
                # 后 2-3 次任务基线即收敛到坏值, 告警自动"熄火"且持久化误报
                new = dict(base) if base else {}
                new["样本数"] = (base or {}).get("样本数", 0) + 1
            else:
                # 更新基线 (EMA)
                new = {k: _ema((base or {}).get(k), v) for k, v in cur.items()}
                new["样本数"] = (base or {}).get("样本数", 0) + 1
            st[domain] = new
            _save(st)
    except Exception:
        pass
    if alarms:
        try:
            import 日志 as _app_log
            for a in alarms:
                _app_log.warn("漂移检测", a)
        except Exception:
            pass
        try:
            import 风控事件 as _event
            _event.add("content_issue", {"域名": domain, "告警": "; ".join(alarms)})
        except Exception:
            pass
    return alarms


def get_baseline(domain: str):
    """读取该域当前基线 (供 GUI/诊断)。"""
    return _load().get(domain)
