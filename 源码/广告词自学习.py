# -*- coding: utf-8 -*-
"""广告词自学习 (C6 Roadmap P2, 2026-10-17): 高频删除行 → 待审 → 人工采纳 → ad_rules。

**闭环** (Roadmap 原话: "删除→观察→审核→固化"):
  删除  —— clean_content 每删一行, 按 (域, 行文本) 计数 (内存聚合, 锁保护);
  观察  —— 任务收尾 flush: 合并进 数据/待审广告词.json (计数累加, 原子写);
  审核  —— 站点管理页列出候选 (次数/类别/末见), 人工判断;
  固化  —— 采纳: 并入 站点配置.json 该域 ad_rules.关键词 + 热重载立即生效。

**方案 A 铁律** (与 选择器自愈 同裁决, 文档/实施计划.md §P7): 只产待审,
**绝不自动生效** —— 没有"学习到就自动加规则"这回事。防静默污染用户配置。

**与 P1 的关系**: P1 (过度清洗告警) 发现"删多了"的信号; 本模块提供
"删的是什么"的候选清单 —— 两者合起来才是完整的误杀治理环。

**候选门槛** (宁缺毋滥):
  · 同域同文本删除 >= 3 次 (一次性噪声不进清单);
  · 文本 >= 4 字 (更短的是正文残片, 不是规则);
  · **未被现有规则覆盖**: 含内置关键词 / 该域 ad_rules 关键词子串 /
    该域 ad_rules 行正则命中 —— 已被覆盖的没有新增价值;
  · 存储截断 50 字 (删除行可能是整段, 关键词规则只需识别性前缀)。

**安全边界**:
  · 待审数据只写 数据/待审广告词.json (本地状态根, gitignored, **含站点文本**,
    严禁入库/外传 —— 与 选择器建议.json 同级对待);
  · 每域最多 30 词 / 全文件最多 50 域 (防膨胀, 超出淘汰次数最少者);
  · 收集全程 try 保护 + `启用` 开关 (关掉后零开销); 失败绝不影响抓取。
"""
import atexit
import json
import os
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import 日志 as _app_log
_log = _app_log.get('广告词自学习')

_LOCK = threading.Lock()

# 总开关 (测试/排查可关; 关掉后 记录删除批次 立即返回, 零开销)
启用 = True

# ---- 门槛与上限 ----
_最少次数 = 3          # 同域同文本至少删这么多次才候选
_最短词长 = 4          # 候选文本最短长度 (字)
_存储截断 = 50         # 待审清单里文本的最大长度 (超出截断加 …)
_每域上限 = 30         # 每域最多保留多少候选词
_总域上限 = 50         # 全文件最多多少域

# (域, 文本) -> [次数, 类别, 首见, 末见]  (内存聚合, flush 时并入待审文件)
_计数: dict = {}


def _取域名(url: str) -> str:
    """从 URL 取域 (与 sites_config.获取广告规则 的口径一致: netloc 小写)。"""
    try:
        return (urlparse(url or '').netloc or '').lower()
    except Exception:
        return ''


def 记录删除批次(url: str, 样本) -> None:
    """一批删除行计入内存聚合 (内容清洗.清洗 在章末调用, 一章一次)。

    Args:
        url: 章节页 URL (取域用; 空则忽略)
        样本: [(行文本, 类别), ...] —— 行文本为 strip 后的删除行
    """
    if not 启用 or not url or not 样本:
        return
    域 = _取域名(url)
    if not 域:
        return
    try:
        with _LOCK:
            for 行, 类别 in 样本:
                if not 行:
                    continue
                文本 = re.sub(r'\s+', ' ', str(行)).strip()[:_存储截断]
                if len(文本) < _最短词长:
                    continue          # 太短: 正文残片, 不是规则 (门槛前置, 省内存)
                键 = (域, 文本)
                现 = _计数.get(键)
                if 现 is None:
                    _计数[键] = [1, str(类别 or ''),
                                time.strftime('%Y-%m-%d %H:%M:%S'),
                                time.strftime('%Y-%m-%d %H:%M:%S')]
                else:
                    现[0] += 1
                    现[3] = time.strftime('%Y-%m-%d %H:%M:%S')
    except Exception as _e:
        # 收集是锦上添花: 任何异常只记 debug, 绝不影响抓取
        _log.debug(f'裸 except 吞异常: {type(_e).__name__}: {_e}')


def _内置关键词() -> list:
    """内置过滤关键词表 (与 内容清洗 同一份, 只读引用)。"""
    try:
        import 内容清洗
        return [str(k) for k in 内容清洗._CONTENT_FILTER_KEYWORDS if k]
    except Exception:
        return []


def _已被规则覆盖(域: str, 文本: str) -> bool:
    """文本是否已被现有规则覆盖 (内置关键词子串 / 该域 ad_rules 关键词或行正则)。

    已覆盖 ⇒ 删它是既定行为, 再候选也没有新增价值 (子串已包含它)。
    """
    for kw in _内置关键词():
        if kw and kw in 文本:
            return True
    try:
        import sites_config
        规则 = sites_config.获取广告规则(f'https://{域}/')
        for kw in (规则.get('关键词') or []):
            if kw and kw in 文本:
                return True
        for rx in (规则.get('正则') or []):
            try:
                if rx.search(文本):
                    return True
            except Exception:
                continue
    except Exception:
        pass    # sites_config 不可用 (独立环境) 时只按内置词判
    return False


def _候选() -> dict:
    """内存计数里达到门槛且未被覆盖的候选: {域: [(文本, 次数, 类别, 末见)]}"""
    with _LOCK:
        快照 = list(_计数.items())
    出: dict = {}
    for (域, 文本), (次数, 类别, _首, 末) in 快照:
        if 次数 < _最少次数 or len(文本) < _最短词长:
            continue
        if _已被规则覆盖(域, 文本):
            continue
        出.setdefault(域, []).append((文本, 次数, 类别, 末))
    return 出


def _待审文件() -> str:
    """待审清单路径 (本地状态根/数据/, gitignored)。"""
    try:
        import _path_utils
        d = os.path.join(_path_utils.get_state_root(), "数据")
    except Exception:
        d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "数据")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "待审广告词.json")


def flush() -> int:
    """把内存候选合并进待审清单 (计数累加, 不清空内存 —— 本章仍是观察样本)。

    Returns: 新写入/更新的候选词条数 (0 = 无达到门槛的新候选)。
    任务收尾与 atexit 调用; 合并语义: 同域同词次数累加、末见刷新。
    """
    if not 启用:
        return 0
    候选 = _候选()
    if not 候选:
        return 0
    # 已落盘的候选键从内存移除 (同一文本后续再被删会重新累计, 下次 flush
    # 增量累加进清单) —— 否则二次 flush 会把**全量**重复加一遍 (3+7=10)。
    # 亚门槛键不动: 它们的累计进度跨 flush 保留, 够数了自然进清单。
    with _LOCK:
        for 域, 词表 in 候选.items():
            for 文本, _次, _类, _末 in 词表:
                _计数.pop((域, 文本), None)
    p = Path(_待审文件())
    from 文件锁 import 写锁
    with 写锁(str(p)):        # R03: 读-合并-写全程跨进程原子
        try:
            data = json.loads(p.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
    变动 = 0
    for 域, 词表 in 候选.items():
        条目 = data.get(域)
        if not isinstance(条目, dict):
            条目 = {"词语": {}, "更新": ""}
        词语 = 条目.setdefault("词语", {})
        if not isinstance(词语, dict):
            词语 = {}
            条目["词语"] = 词语
        for 文本, 次数, 类别, 末 in 词表:
            旧 = 词语.get(文本)
            if isinstance(旧, dict):
                旧["次数"] = int(旧.get("次数", 0)) + 次数
                旧["末见"] = 末
                旧["类别"] = 类别 or 旧.get("类别", "")
            else:
                词语[文本] = {"次数": 次数, "类别": 类别,
                            "首见": 末, "末见": 末}
            变动 += 1
        # 每域上限: 保留次数最多的 _每域上限 条
        if len(词语) > _每域上限:
            保留 = sorted(词语.items(), key=lambda kv: -int(kv[1].get("次数", 0)))
            条目["词语"] = dict(保留[:_每域上限])
        条目["更新"] = time.strftime('%Y-%m-%d %H:%M:%S')
        data[域] = 条目
    # 总域上限: 淘汰"更新"最旧的域
    if len(data) > _总域上限:
        有序 = sorted(data.items(), key=lambda kv: str(kv[1].get("更新", "")))
        data = dict(有序[-_总域上限:])
    tmp = p.with_name(p.name + f'.tmp.{os.getpid()}')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, p)
    if 变动:
        _log.info(f"[广告词学习] 待审清单更新 {变动} 条 (共 {len(data)} 域) —— "
                  f"见 数据/待审广告词.json, 人工审核后采纳")
    return 变动


def 列出待审广告词(domain: str = None):
    """读取接口: 全部 {域: 条目} 或指定域条目 (不存在返回 None/{})。"""
    try:
        data = json.loads(Path(_待审文件()).read_text(encoding='utf-8'))
    except Exception:
        return {} if domain is None else None
    if not isinstance(data, dict):
        return {} if domain is None else None
    return data.get(domain) if domain else data


def 待审词条(domain: str) -> list:
    """指定域的候选词列表 (按次数降序): [{词, 次数, 类别, 首见, 末见}]"""
    条目 = 列出待审广告词(domain) or {}
    词语 = 条目.get("词语") or {}
    出 = [{"词": k, **v} for k, v in 词语.items() if isinstance(v, dict)]
    出.sort(key=lambda x: -int(x.get("次数", 0)))
    return 出


def _配置路径():
    """站点配置.json 路径 (与 选择器自愈 同: resolve_data_file 优先)。"""
    try:
        from _path_utils import resolve_data_file
        return resolve_data_file("站点配置.json",
                                 copy_default_from_resource_if_missing=False)
    except Exception:
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "站点配置.json")


def _热重载() -> str:
    """热重放运行时配置 (失败不回滚: 下次启动仍会加载; 如实返回提示)。"""
    try:
        import sites_config
        sites_config.reload_runtime_config()
        return ""
    except Exception as e:
        return f" (热重载失败: {e}; 下次启动仍生效)"


def 采纳广告词(domain: str, 词: str) -> tuple:
    """把候选词并入 站点配置.json 该域 ad_rules.关键词 并热重载 (人工触发)。

    步骤 (任一步失败即中止, 候选保留待重试):
    1. 读配置 JSON (列表); 找该域条目。不存在 → 拒绝并说明 (不擅自建站点);
    2. 并入 ad_rules.关键词 (条目无 ad_rules 则新建; 去重; **不动行正则**);
    3. tmp + os.replace 原子写回;
    4. reload_runtime_config() 热重放, 当前进程立即生效;
    5. 从待审清单移除该词 (该域无剩余词则移除整域)。

    Returns: (是否成功, 人读消息)
    """
    词 = (词 or '').strip()
    if not 词:
        return False, "空词"
    条目 = 列出待审广告词(domain) or {}
    if 词 not in (条目.get("词语") or {}):
        return False, f"无该域待审候选词: {domain} / {词!r}"
    p = Path(_配置路径())
    if not p.is_file():
        return False, f"站点配置文件不存在, 无法并入: {p}"
    try:
        items = json.loads(p.read_text(encoding='utf-8'))
    except Exception as e:
        return False, f"配置 JSON 读取失败, 中止 (候选已保留): {e}"
    if not isinstance(items, list):
        return False, "配置 JSON 顶层不是列表, 中止 (候选已保留)"
    entry = next((it for it in items
                  if isinstance(it, dict) and it.get('domain') == domain), None)
    if entry is None:
        return False, (f"配置中无站点 {domain} (内置站被删或候选来自旧站), "
                       f"不擅自新建条目; 请人工在站点管理页添加后再采纳。候选已保留。")
    ad = entry.get('ad_rules')
    if not isinstance(ad, dict):
        ad = {}
        entry['ad_rules'] = ad
    关键词 = ad.get('关键词')
    if not isinstance(关键词, list):
        关键词 = []
    if 词 in 关键词:
        _log.info(f"[广告词审核] {domain}: 词 {词!r} 已在配置中, 仅移除候选")
    else:
        关键词.append(词)
        ad['关键词'] = 关键词
    try:
        tmp = p.with_name(p.name + f'.tmp.{os.getpid()}')
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2),
                       encoding='utf-8')
        os.replace(tmp, p)
    except OSError as e:
        return False, f"配置写盘失败, 中止 (候选已保留): {e}"
    提示 = _热重载()
    _移除候选(domain, 词)
    return True, f"已并入 {domain} 的 ad_rules.关键词: {词!r}{提示}"


def 拒绝广告词(domain: str, 词: str) -> tuple:
    """忽略候选词: 仅从待审清单移除, 配置零触碰。"""
    词 = (词 or '').strip()
    if not _移除候选(domain, 词):
        return False, f"无该域待审候选词: {domain} / {词!r}"
    return True, f"已忽略 {domain} 的候选词: {词!r}"


def _移除候选(domain: str, 词: str) -> bool:
    """从待审清单移除一个候选词 (该域清空则移除整域); 返回是否有变动。"""
    p = Path(_待审文件())
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return False
    if not isinstance(data, dict) or domain not in data:
        return False
    条目 = data.get(domain) or {}
    词语 = 条目.get("词语") or {}
    if 词 not in 词语:
        return False
    词语.pop(词, None)
    if 词语:
        条目["词语"] = 词语
        data[domain] = 条目
    else:
        data.pop(domain, None)
    tmp = p.with_name(p.name + f'.tmp.{os.getpid()}')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, p)
    return True


def _atexit_flush():
    """进程退出兜底: 防抖期间未 flush 的候选不丢失 (与 爬取历史 同范式)。"""
    try:
        flush()
    except Exception as _e:
        _log.debug(f'裸 except 吞异常: {type(_e).__name__}: {_e}')


atexit.register(_atexit_flush)
