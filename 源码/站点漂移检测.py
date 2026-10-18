# -*- coding: utf-8 -*-
"""站点改版漂移检测 (P2-2): 任务收尾时对比该域历史基线, 命中率突降即告警。

原理 (文档/实施计划.md §P2 §6-P2-2):
- 站点改版最常见信号 = 正文提取成功率/质检通过率骤降 (选择器失效/混淆变了)
- 数据/站点基线.json: {域名: {"样本数": n, "空章率": x, "短章率": y, "失败率": z}}
  每次任务收尾更新 (指数移动平均), 偏差超阈值 -> 写 风控事件(content_issue) +
  日志告警, 提示用 probe_adapter.py 重探该站。
- 旁路静默, 不影响抓取主流程。

P1-B (C6 Roadmap, 2026-10-17): 漂移告增补**清洗诊断分流** —— 告警时附带本次
任务的清洗统计汇总 (删除行占比/过度清洗章数), 据此外推"站点改版"还是"清洗
规则误杀": 删除占比高 ⇒ 优先怀疑清洗误杀 (看任务卡警示/广告词候选); 占比
正常 ⇒ 更像站点改版 (重探适配器)。数据来自 爬虫._收尾汇总 从 _质检记录 汇总,
按域存 站点基线.json 的 "最近清洗" (只存计数, 无文本)。
"""
import json
import os
import threading
from pathlib import Path
try:
    import 日志 as _app_log          # 批2C: 统一留痕通道 (容错导入, 同 input_bar 桥模式)
except Exception:
    _app_log = None


def _dbg(source: str, message: str):
    """裸 except 吞异常留痕 (DEBUG 级: 只落盘不 console 镜像, 避免刷屏)"""
    if _app_log is not None:
        try:
            _app_log.debug(source, message)
        except Exception:
            pass  # 刻意静默: try 块本身在写日志, 再加日志会递归 (日志链路兜底)


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
        d = os.path.join(_path_utils.get_state_root(), "数据")
    except Exception:
        d = os.path.dirname(os.path.abspath(__file__))
    try:
        os.makedirs(d, exist_ok=True)
    except OSError as _e:
        _dbg("漂移检测", f'裸 except 吞异常: {type(_e).__name__}: {_e}')
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
    except Exception as _e:
        _dbg("漂移检测", f'裸 except 吞异常: {type(_e).__name__}: {_e}')


def _ema(old, new):
    if old is None:
        return new
    return round(old * (1 - _ALPHA) + new * _ALPHA, 4)


def _清洗诊断(清洗汇总) -> str:
    """据本次任务的清洗统计给分流提示 (P1-B)。

    删除行占比 = 5 个行级删除计数之和 / 原始行数 (水印是字符级替换, 不计入,
    与 内容质检器.判定过度清洗 同口径); 原始行数缺失/为 0 时返回 '' (向后兼容)。
    """
    if not isinstance(清洗汇总, dict):
        return ''
    try:
        原行 = int(清洗汇总.get('原始行数', 0) or 0)
    except (TypeError, ValueError):
        return ''
    if 原行 <= 0:
        return ''
    删行 = 0
    for 键 in ('关键词行', '推广行', '过短行', '符号行', '广告行'):
        try:
            删行 += int(清洗汇总.get(键, 0) or 0)
        except (TypeError, ValueError) as _e:
            _dbg('漂移检测', f'清洗诊断跳过非数字计数 {键}: {_e}')
    占比 = 删行 / 原行
    try:
        过度章 = int(清洗汇总.get('过度清洗章数', 0) or 0)
    except (TypeError, ValueError) as _e:
        _dbg('漂移检测', f'清洗诊断的 过度清洗章数 非数字, 按 0: {_e}')
        过度章 = 0
    if 占比 > 0.30 or 过度章 > 0:
        return (f' 本次删除行占比 {占比:.0%}'
                + (f'、过度清洗告警 {过度章} 章' if 过度章 else '')
                + ' — 优先怀疑清洗规则误杀 (看任务卡「⚠ 清洗异常」/ 站点管理页广告词候选)')
    return f' 本次删除行占比 {占比:.0%} (清洗无异常) — 更像站点改版, 建议重探适配器'


def report_task(domain: str, total: int, empty: int, short: int, failed: int,
                清洗汇总=None) -> list:
    """任务收尾上报并检测漂移。

    Args:
        domain: 站点域名
        total: 本次目标章数 (>0)
        empty: 提取为空的章数
        short: 质检"过短/未通过"章数
        failed: 失败章数
        清洗汇总: (P1-B, 可选) 本次任务清洗统计汇总 dict —— {关键词行…广告行,
            原始行数, 过度清洗章数}; 用于漂移告警的成因分流。缺省/None 时
            行为与本函数加参数前完全一致 (向后兼容)。
    Returns:
        告警列表 (空 = 无漂移)
    """
    if not domain or total <= 0:
        return []
    cur = {"空章率": empty / total, "短章率": short / total, "失败率": failed / total}
    alarms = []
    drifted = False   # M9: 本次触发漂移告警时, 基线不被 EMA 吸收坏值
    try:
        from 文件锁 import 写锁
        with _LOCK, 写锁(_path()):     # R03: 读-改-写全程跨进程原子
            st = _load()
            base = st.get(domain)
            if base and base.get("样本数", 0) >= ALARM["最小样本"]:
                for k, v in cur.items():
                    bv = base.get(k)
                    if bv is not None and v > bv + ALARM[k]:
                        alarms.append(
                            f"⚠ {domain}: {k} 本次 {v:.0%} vs 基线 {bv:.0%} — 疑似站点改版, "
                            f"建议用 脚本/probe_adapter.py 重探"
                            + _清洗诊断(清洗汇总))
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
            # P1-B: 记录本次任务的清洗统计 (只存计数无文本; 供下次告警时对比/诊断)
            if isinstance(清洗汇总, dict):
                new["最近清洗"] = {
                    k: (int(v) if isinstance(v, (int, float)) else v)
                    for k, v in 清洗汇总.items()
                    if k in ('关键词行', '推广行', '过短行', '符号行', '广告行',
                             '水印', '原始行数', '过度清洗章数')}
            st[domain] = new
            _save(st)
    except Exception as _e:
        _dbg("漂移检测", f'裸 except 吞异常: {type(_e).__name__}: {_e}')
    if alarms:
        try:
            import 日志 as _app_log
            for a in alarms:
                _app_log.warn("漂移检测", a)
        except Exception:
            pass  # 刻意静默: try 块本身在写日志, 再加日志会递归 (日志链路兜底)
        try:
            import 风控事件 as _event
            _event.add("content_issue", {"域名": domain, "告警": "; ".join(alarms)})
        except Exception as _e:
            _dbg("漂移检测", f'裸 except 吞异常: {type(_e).__name__}: {_e}')
    return alarms


def get_baseline(domain: str):
    """读取该域当前基线 (供 GUI/诊断)。"""
    return _load().get(domain)
