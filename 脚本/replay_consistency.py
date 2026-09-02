# -*- coding: utf-8 -*-
"""P1-2 回放一致率统计: 对 测试样本/ 全部 HTML 快照离线跑 probe, 汇总建议模式。

用法: python 脚本/replay_consistency.py
真值表 (正文页快照 -> 站点真实 pattern) 来自 sites_config 现有配置;
目录页/列表页只报链接形态, 不计入模式一致率。
"""
import re
import sys
from pathlib import Path

_BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BASE / "脚本"))

import probe_adapter  # noqa: E402

SAMPLES = _BASE / "测试样本"

# 已知真值: 文件名特征 -> 真实 pattern (据 sites_config.py)
GROUND_TRUTH = {
    "630wang_content": "html_selector",
    "630wang_dir": "html_selector",      # 目录页 (模式=正文模式)
    "630wang_list": "html_selector",
    "ciyewk_content": "datafile",
    "ciyewk_real": "datafile",
    "ciyewk_catalog": "datafile",
    "ciyewk_ml": "datafile",
    "ltbook_content": "html_selector",
    "ltbook_full": "html_selector",
    "ltbook_list": "html_selector",
    "zhiruo_content": "qsbs_bb",
    "zhiruo_real": "qsbs_bb",
    "zhiruo_dir": "qsbs_bb",
    "zhiruo_list": "qsbs_bb",
}
SKIP = {"630wang_dir_2", "630wang_dir_3"}  # 同站目录分页, 避免重复计数

rows = []
for f in sorted(SAMPLES.glob("*.html")):
    name = f.stem
    if name in SKIP:
        continue
    html = f.read_text(encoding="utf-8", errors="replace")
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    ev = {
        "url": "https://x.example/1.html", "direct_ok": True, "direct_status": 200,
        "engine": "offline", "title": soup.title.get_text(strip=True)[:60] if soup.title else "",
        "obfuscation": probe_adapter.detect_obfuscation(html),
    }
    cands = []
    for el in soup.find_all(["div", "article", "section", "td", "dd"]):
        t = el.get_text(strip=True)
        if 300 < len(t) < 200000:
            cands.append((len(t), el.name, ".".join((el.get("class") or [])[:2]), el.get("id") or "", t[:200]))
    cands.sort(reverse=True)
    ev["content_container_candidates"] = [
        {"len": c[0], "tag": c[1], "class": c[2], "id": c[3], "preview": c[4]} for c in cands[:3]
    ]
    top = cands[0][4] if cands else ""
    ev["placeholder_page"] = any(k in top for k in probe_adapter._PLACEHOLDER_TEXT)
    ev["ad_header"] = [k for k in probe_adapter._AD_HEADER if k in top]
    ev["meta_prefix"] = bool(re.search(r"作者[:：]", top[:60]))
    sug = probe_adapter.build_suggestion(ev, "https://x.example/1.html")
    gt = GROUND_TRUTH.get(name)
    # 正文页口径: 仅文件名含 content/full 的快照确为正文页 (目录/列表/渲染页
    # 快照不内嵌正文混淆, probe 如实报目录侧信息, 不参与正文模式一致率)
    is_body = "content" in name or "full" in name
    rows.append((name, sug["pattern"], gt, is_body, ev["obfuscation"], top[:50].replace("\n", " ")))

print(f"{'快照':24s} {'建议':16s} {'真值':16s} {'一致':4s} 混淆/预览")
ok = total = 0
for name, sug, gt, is_body, obf, prev in rows:
    same = ""
    if gt:
        same = "OK" if sug == gt else "X!"
        if is_body:
            total += 1
            ok += 1 if sug == gt else 0
    print(f"{name:24s} {sug:16s} {(gt or '-'):16s} {same:4s} {','.join(obf)[:28] or '-'} | {prev[:40]}")
print(f"\n正文页一致率: {ok}/{total}")
