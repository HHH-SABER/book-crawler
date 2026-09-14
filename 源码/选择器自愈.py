# -*- coding: utf-8 -*-
"""选择器自愈重定位 (批3 PoC-A: 站点改版后自动找回正文容器, 产出"建议待审"清单)。

背景 (文档/项目升级方向与开源对标-2026-09-13.md 第二层★方向):
- 现有链路: 站点漂移检测.py 只**告警** (空章率/短章率 EMA 突升), 不修复;
  选择器失效后需人工跑 probe_adapter.py 重探。
- 本模块对标 Scrapling 自适应元素追踪: 规则选择器**全部落空**时, 用结构启发式
  (中文量/段落数/链接密度/深度惩罚) 在页面中重找正文容器, 生成新选择器,
  写入待审建议清单 —— **不自动改站点配置** (方案 A, 防静默污染用户配置)。

打分算法与阈值来源 (2026-09-14 探针实测, probe_selfheal_a95e0468):
- ltbook 抹掉 #rtext -> TOP1 找回 (0.968); 630wang 抹掉 .word_read -> TOP3 找回 (0.896)
- yueliang 盲测 top1 = #chaptercontent.content (精确)
- 负样本: qiqishu (base64 加密页) 最高分仅 0.179 —— 分数天然可作置信度门槛
- 样本 yunshuzhai top1 命中外层 container (含导航) -> 正式版需"祖先去重",
  PoC 以"链接密度<=0.5 + 选择器回读唯一性"双重门槛压制该风险。

挂载点: sites_config.extract_content 的 HTML_SELECTOR 分支, 仅在"规则选择器全部
落空 (走了兜底或返回空)"时调用 —— 正常抓取路径零开销、零行为变化。

安全边界:
- 建议只写 数据/选择器建议.json (tmp+os.replace 原子写), 人工审核后才进 站点配置.json
- 每域只保留最新 1 条 (改版是域级事件, 旧建议无价值), 全文件最多 50 域防膨胀
"""
import json
import os
import re
import threading
import time
from pathlib import Path

import 日志 as _app_log
_log = _app_log.get('选择器自愈')

_LOCK = threading.Lock()

# 启发式权重与门槛 (探针校准值)
_MIN_CN = 100          # 候选容器最少中文字符
_MAX_LINK_DENSITY = 0.5   # 链接文字占比上限 (超过=导航/目录)
_MIN_CONFIDENCE = 0.55    # 采纳为建议的最低置信分 (负样本实测最高 0.179, 留余量)
_CN_SAT = 3000            # 中文量归一化饱和点
_P_SAT = 30               # <p> 数归一化饱和点
_BLOCK_TAGS = ('div', 'td', 'article', 'section', 'main', 'pre', 'table')
_CJK = re.compile(r'[\u4e00-\u9fff]')


def _cn_len(text: str) -> int:
    return len(_CJK.findall(text or ''))


def score_candidates(soup):
    """页面上所有块级容器按正文相似度打分, 返回 [(分数, 节点)] 降序。"""
    out = []
    for node in soup.find_all(_BLOCK_TAGS):
        txt = node.get_text()
        cn = _cn_len(txt)
        if cn < _MIN_CN:
            continue
        pc = len(node.find_all('p'))
        link = sum(_cn_len(a.get_text()) for a in node.find_all('a'))
        ld = link / cn if cn else 1.0
        if ld > _MAX_LINK_DENSITY:
            continue
        depth, p = 0, node.parent
        while p is not None and getattr(p, 'name', None) not in (None, '[document]'):
            depth += 1
            p = p.parent
        s = (0.45 * min(cn / _CN_SAT, 1.0)
             + 0.35 * min(pc / _P_SAT, 1.0)
             + 0.2 * (1 - ld))
        s -= min(depth, 15) * 0.008          # 深度惩罚: 过深像被包裹的杂项
        s -= min(len(node.find_all(_BLOCK_TAGS, recursive=False)), 10) * 0.005
        out.append((s, node))
    out.sort(key=lambda x: -x[0])
    return out


def make_selector(node, soup):
    """为节点生成**回读唯一**的 CSS 选择器: #id > tag.unique-class; 都失败返回 None。

    唯一性用 soup.select(sel) 命中数==1 验证 —— 生成的选择器若会误伤其他节点,
    宁可不产出 (人工处理), 也不写入可能错抓的建议。
    """
    cand = []
    if node.get('id'):
        cand.append(f"#{node['id']}")
    for cls in (node.get('class') or []):
        cand.append(f"{node.name}.{cls}")
    for sel in cand:
        try:
            if len(soup.select(sel)) == 1:
                return sel
        except Exception as _e:
            _log.debug(f'裸 except 吞异常: {type(_e).__name__}: {_e}')
    return None


def try_heal(soup, domain: str, old_selectors) -> dict | None:
    """选择器全部落空后的自愈尝试: 找容器 -> 生成选择器 -> 记录建议。

    Returns: 建议 dict (已落盘) 或 None (不可信, 不产出)。
    """
    try:
        cands = score_candidates(soup)
        if not cands:
            return None
        score, node = cands[0]
        if score < _MIN_CONFIDENCE:
            _log.info(f"[自愈] {domain}: 启发式最高分 {score:.3f} < 门槛 {_MIN_CONFIDENCE}, "
                      f"疑似非普通改版 (加密变更/软封页?), 不产出建议")
            return None
        sel = make_selector(node, soup)
        if not sel:
            _log.info(f"[自愈] {domain}: 找到容器 (分 {score:.3f}) 但无法生成唯一选择器, 需人工")
            return None
        suggestion = {
            "域名": domain,
            "建议选择器": sel,
            "原选择器": list(old_selectors or []),
            "置信度": round(score, 3),
            "容器中文数": _cn_len(node.get_text()),
            "段落数": len(node.find_all('p')),
            "生成时间": time.strftime('%Y-%m-%d %H:%M:%S'),
            "说明": "规则选择器全部落空时启发式重定位产出; 人工核实后手动并入 站点配置.json 的 content_selectors",
        }
        # 幂等去重: 每章都可能落空, 同域同建议不重复写盘 (防 IO churn/日志刷屏)
        prev = 取待审建议(domain)
        if prev and prev.get("建议选择器") == sel:
            _log.debug(f"[自愈] {domain}: 建议 {sel!r} 已在待审清单, 跳过重复落盘")
            return suggestion
        记录建议(suggestion)
        _log.info(f"[自愈] {domain}: 产出待审建议 {sel!r} (置信 {score:.3f}) —— 见 数据/选择器建议.json")
        return suggestion
    except Exception as _e:
        _log.debug(f'裸 except 吞异常: {type(_e).__name__}: {_e}')
        return None


def _建议文件():
    try:
        import _path_utils
        d = os.path.join(_path_utils.get_state_root(), "数据")
    except Exception:
        d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "数据")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "选择器建议.json")


def 记录建议(suggestion: dict):
    """按域 upsert 到待审清单 (原子写 tmp+os.replace, 仿 站点漂移检测._save)。"""
    with _LOCK:
        p = Path(_建议文件())
        try:
            data = json.loads(p.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
        data[suggestion["域名"]] = suggestion
        # 防膨胀: 最多保留 50 域 (超出时淘汰最旧置信度条目按插入序)
        if len(data) > 50:
            for k in list(data)[:len(data) - 50]:
                data.pop(k, None)
        tmp = p.with_name(p.name + f'.tmp.{os.getpid()}')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(tmp, p)


def 取待审建议(domain: str = None):
    """GUI/人工读取接口: 全部 dict 或指定域条目 (不存在返回 None)。"""
    try:
        data = json.loads(Path(_建议文件()).read_text(encoding='utf-8'))
    except Exception:
        return {} if domain is None else None
    return data.get(domain) if domain else data


def 列出待审() -> list:
    """审核清单 (按置信度降序): [{域名, 建议选择器, 原选择器, 置信度, 生成时间, ...}]"""
    data = 取待审建议() or {}
    return sorted(data.values(), key=lambda s: -float(s.get("置信度", 0)))


# ============================================================
# 审核闭环 (批3 PoC-B, 方案 A 的"人工确认"一步)
# ============================================================

def _配置路径():
    """读写用的 站点配置.json 路径 (与 sites_config 运行时重放同一文件)。

    优先 resolve_data_file (EXE 旁/BASE_DIR 契约); 不可用时退到项目根同名文件。
    """
    try:
        from _path_utils import resolve_data_file
        return resolve_data_file("站点配置.json",
                                 copy_default_from_resource_if_missing=False)
    except Exception:
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "站点配置.json")


def 采纳建议(domain: str) -> tuple:
    """把该域建议并入 站点配置.json 的 content_selectors 并热重载生效。

    步骤 (任一步失败即中止, 建议保留待重试):
    1. 读配置 JSON (列表); 找到该域条目。条目不存在 → 拒绝操作并说明
       (建议来自已禁用的站点时宁可让人工处理, 不擅自新建站点)。
    2. 新选择器**前插**进 content_selectors (自愈容器优先尝试, 旧选择器保留
       兜底 —— 改版只换 id/class 的常见情形下, 旧的仍可能对别的子页有效);
       去重 (同选择器不重复出现)。
    3. tmp + os.replace 原子写回 (G-M4 范式)。
    4. reload_runtime_config() 热重放, 当前进程立即生效 (H7 通道)。
       热重载失败不回滚配置 —— 下次启动 _apply_runtime_config 仍会加载;
       但会如实返回提示。
    5. 从待审清单移除该域。

    Returns: (是否成功, 人读消息)
    """
    sug = 取待审建议(domain)
    if not sug:
        return False, f"无该域待审建议: {domain}"
    p = Path(_配置路径())
    if not p.is_file():
        return False, f"站点配置文件不存在, 无法并入: {p}"
    try:
        items = json.loads(p.read_text(encoding='utf-8'))
    except Exception as e:
        return False, f"配置 JSON 读取失败, 中止 (建议已保留): {e}"
    if not isinstance(items, list):
        return False, "配置 JSON 顶层不是列表, 中止 (建议已保留)"
    entry = next((it for it in items
                  if isinstance(it, dict) and it.get('domain') == domain), None)
    if entry is None:
        return False, (f"配置中无站点 {domain} (可能是内置站被删或建议来自旧站), "
                       f"不擅自新建条目; 请人工在站点管理页添加后再采纳。建议已保留。")
    sel = sug.get("建议选择器") or ""
    if not sel:
        return False, "建议缺少选择器字段, 已保留待人工处理"
    sels = entry.get('content_selectors') or ['#content', '.content']
    if sel in sels:
        _log.info(f"[自愈审核] {domain}: 选择器 {sel!r} 已在配置中, 仅移除建议")
    else:
        # 前插, 旧选择器保留兜底; 不碰 enabled —— 用户禁用中的站点被悄悄启用
        # 正是"静默污染"的一种, 若站点禁用中, 保持原样由人工在站点管理页处理。
        entry['content_selectors'] = [sel] + sels
    # 原子写回 (G-M4 范式; 本函数低频人工操作, 无需 _json_clean —— 我们只读写过 JSON)
    try:
        tmp = p.with_name(p.name + f'.tmp.{os.getpid()}')
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2),
                       encoding='utf-8')
        os.replace(tmp, p)
    except OSError as e:
        return False, f"配置写盘失败, 中止 (建议已保留): {e}"
    # 热重放 (失败不回滚: 下次启动仍会加载, 如实报告)
    重载提示 = ""
    try:
        import sites_config
        sites_config.reload_runtime_config()
    except Exception as e:
        重载提示 = f" (热重载失败 {type(e).__name__}: {e}, 将在下次启动生效)"
    # 移除建议
    try:
        with _LOCK:
            data = json.loads(Path(_建议文件()).read_text(encoding='utf-8'))
            data.pop(domain, None)
            tmp2 = Path(_建议文件()).with_name(f'.tmp.{os.getpid()}')
            tmp2.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                            encoding='utf-8')
            os.replace(tmp2, Path(_建议文件()))
    except Exception as e:
        _log.debug(f'裸 except 吞异常: {type(e).__name__}: {e}')  # 建议文件移除失败仅噪音
    msg = (f"已并入 {domain} 的 content_selectors: {sel!r} 前插"
           f" (旧选择器保留兜底){重载提示}")
    _log.info(f"[自愈审核] 采纳 {domain}: {msg}")
    return True, msg


def 拒绝建议(domain: str) -> tuple:
    """仅从待审清单移除该域建议 (配置不动)。用于误报/已知不修场景。"""
    if not 取待审建议(domain):
        return False, f"无该域待审建议: {domain}"
    with _LOCK:
        p = Path(_建议文件())
        try:
            data = json.loads(p.read_text(encoding='utf-8'))
        except Exception:
            data = {}
        data.pop(domain, None)
        tmp = p.with_name(p.name + f'.tmp.{os.getpid()}')
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                           encoding='utf-8')
            os.replace(tmp, p)
        except OSError as e:
            return False, f"建议文件写盘失败: {e}"
    _log.info(f"[自愈审核] 拒绝 {domain} 的建议 (配置未动)")
    return True, f"已移除 {domain} 的待审建议 (配置未改动)"
