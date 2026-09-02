# -*- coding: utf-8 -*-
"""P2-2 风控事件聚合监控: 近 24h 按域统计健康度 + 阈值告警。

用法: python 脚本/monitor_summary.py [--hours 24] [--domain xxx]
数据源: 数据/风控事件-YYYYMMDD.jsonl (append-only, 按天轮转)
告警阈值 (可调):
  - anti_spider 命中(非 none 机制) 累计 >= 3    -> ⚠ 风控频繁
  - rate_limit / blocked 类型存在              -> ⚠ 限速/封禁
  - task_result 失败章 > 0 且 目标 >= 5        -> ⚠ 章节失败
  - captcha 命中(成功或失败) 累计 >= 3          -> ⚠ 验证码频繁
"""
import argparse
import sys
from pathlib import Path

_BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BASE / "源码"))

from 风控事件 import summary_by_domain  # noqa: E402

ALARM_THRESHOLDS = {
    "anti_total": 3,      # 反爬命中次数
    "fail_ratio": 0.2,    # 失败章占比
}


def alarms(dom):
    out = []
    for d, s in sorted(dom.items()):
        anti_total = sum(s["anti"].values())
        if anti_total >= ALARM_THRESHOLDS["anti_total"]:
            out.append(f"⚠ {d}: 反爬命中 {anti_total} 次 ({dict(s['anti'])})")
        if "rate_limit" in s["anti"] or "blocked" in s["anti"]:
            out.append(f"⚠ {d}: 出现限速/封禁 ({dict(s['anti'])})")
        cap = sum(s["captcha"].values())
        if cap >= 3:
            out.append(f"⚠ {d}: 验证码触发 {cap} 次 ({dict(s['captcha'])})")
        t = s["task"]
        if t["目标"] >= 5 and t["失败"] / t["目标"] > ALARM_THRESHOLDS["fail_ratio"]:
            out.append(f"⚠ {d}: 章节失败率 {t['失败']}/{t['目标']}")
    return out


def main():
    ap = argparse.ArgumentParser(description="近 24h 风控事件聚合")
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--domain", default="")
    args = ap.parse_args()

    events_raw = 0
    dom = summary_by_domain(args.hours)
    events_raw = sum(len(v["anti"]) + len(v["captcha"]) + (1 if v["task"]["runs"] else 0)
                     for v in dom.values())
    if args.domain:
        dom = {k: v for k, v in dom.items() if args.domain in k}

    print(f"风控事件近 {args.hours}h 聚合 (按域事件)")
    print(f"{'域名':24s} {'反爬':26s} {'验证码':14s} {'任务(成/败/次)':20s}")
    for d, s in sorted(dom.items()):
        anti = ",".join(f"{k}×{v}" for k, v in s["anti"].items()) or "-"
        cap = ",".join(f"{k}×{v}" for k, v in s["captcha"].items()) or "-"
        t = s["task"]
        task = f"{t['完成']}/{t['失败']}/{t['runs']}次" if t["runs"] else "-"
        print(f"{d[:24]:24s} {anti[:26]:26s} {cap[:14]:14s} {task:20s}")
    print()
    al = alarms(dom)
    if al:
        print("== 告警 ==")
        for a in al:
            print(" ", a)
    else:
        print("== 无告警 ==")


if __name__ == "__main__":
    main()
