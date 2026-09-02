# -*- coding: utf-8 -*-
"""P1-1 新站探测辅助: 贴一个 URL, 输出 SITE_PATTERNS 适配建议草稿。

用法:
    python 脚本/probe_adapter.py https://www.example.com/book/123/   目录 URL
    python 脚本/probe_adapter.py https://www.example.com/read/1.html 章节 URL (最准)
    python 脚本/probe_adapter.py --json URL   # 只输出 JSON 草稿

设计 (文档/新站接入与命中监控设计.md §2):
- 探测复用现有能力: site_probe / NovelSpider.inspect_page (UA+质询处理)
  / 通用候选容器 / content_decoder 混淆特征
- 注意: 混淆(正文是否加密/占位)最准在【章节页】判定; 传目录 URL 时会抽样前 4 个
  疑似章节链接, 部分站点(链接模板复杂)可能抽不中正文, 届时请再贴一个章节 URL。
- 建议是"草稿": 需人工确认后写入 SITE_PATTERNS; 需要专用 parser/filter 的站会标注。

不联网时: python 脚本/probe_adapter.py --offline-html samples.html URL  用本地快照
(离线回放是 测试样本/ 回归与 P1-2 验收的主要手段)
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

_BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BASE / "源码"))

# 混淆特征 (与 content_decoder / sites_config 内标注一致)
_OBFUSCATION_MARKERS = [
    ("qsbs_bb", re.compile(r"qsbs\.bb\('")),
    ("str_decode", re.compile(r"str_decode|decodeURIComponent\(\s*['\"]")),
    ("base64_like", re.compile(r"atob\(|btoa\(|data:text/plain;base64")),
    ("initTxt/loadTxt", re.compile(r"initTxt\(|loadTxt\(|_txt_call\(")),
    ("datafile_ext", re.compile(r"['\"][\w/\-.]+\.(xs|book|data)['\"]")),
    ("codepoint_stream", re.compile(r"x[0-9a-fA-F]{4}(?:;|\\x)|&#x[0-9a-fA-F]{2,4}")),
    ("eval_dom_write", re.compile(r"document\.writeln|\.innerHTML\s*=|eval\(")),
]
_PLACEHOLDER_TEXT = ("加载中", "章节内容加载中", "请稍后", "loading", "正在加载")
_AD_HEADER = ("如果出现文字缺失", "取消转码", "退出阅读模式", "请勿开启浏览器")


def detect_obfuscation(html: str):
    hits = [name for name, rx in _OBFUSCATION_MARKERS if rx.search(html)]
    return hits


def _fetch(session, url, timeout=15):
    """直接请求; 返回 (status, html, err)。"""
    try:
        r = session.get(url, timeout=timeout)
        return r.status_code, r.text, None
    except Exception as e:
        return None, "", f"{type(e).__name__}: {e}"


def probe_catalog(session, catalog_url, use_crawler=False):
    """探测目录页, 返回 evidence 字典 (纯数据, 不写任何配置)。"""
    from bs4 import BeautifulSoup
    ev = {"url": catalog_url, "direct_ok": False, "engine": "requests"}
    status, html, err = _fetch(session, catalog_url)
    if status is None or status in (403, 429, 520, 521, 522) or (html and "loading" in html.lower()[:2000] and "challenge" in html.lower()):
        # 首包异常/疑似质询: 用爬虫会话(UA 重试/JS 质询/WAF cookie) 再试
        ev["direct_ok"] = False
        ev["direct_status"] = status
        if use_crawler:
            try:
                import 爬虫 as _crawler_mod
                sp = _crawler_mod.NovelSpider("https://" + re.sub(r"^https?://", "", catalog_url).split("/")[0])
                soup = sp.inspect_page(catalog_url)
                html = str(soup) if soup is not None else ""
                ev["engine"] = "crawler_session"
                ev["needs_challenge_session"] = True
            except Exception as e:
                ev["engine_error"] = f"{type(e).__name__}: {e}"
                return ev
        else:
            ev["engine_error"] = f"direct {status}: {err}"
            return ev
    ev["direct_ok"] = True
    ev["direct_status"] = status or 200
    ev["html_len"] = len(html)
    soup = BeautifulSoup(html, "html.parser")
    ev["title"] = soup.title.get_text(strip=True)[:60] if soup.title else ""

    # ---- L5 混淆 ----
    ev["obfuscation"] = detect_obfuscation(html)

    # ---- 目录链接形态 ----
    hrefs = [a.get("href", "") for a in soup.find_all("a", href=True)]
    hrefs = [h for h in hrefs if h and "javascript:" not in h and not h.startswith("#")]
    NAV_TEXT = ("加入书架", "开始阅读", "章节目录", "上一章", "下一章", "首页", "下一页",
                "上一页", "返回目录", "保存书签", "最新章节列表")
    pat_counter = Counter()
    chapter_samples = []   # (href, link_text)
    for a in soup.find_all("a", href=True):
        h = a.get("href", "")
        t = (a.get_text() or "").strip()
        if not h or "javascript:" in h or h.startswith("#"):
            continue
        if any(k in t for k in NAV_TEXT):
            continue
        m = re.search(r"/(\d+)(?:_\d+)?\.html?$", h)
        if m:
            pat_counter["尾部纯数字.html"] += 1
            chapter_samples.append((h, t[:24]))
            continue
        m = re.search(r"/([a-z]+)/(\d+)/(\d+)\.html", h)
        if m:
            pat_counter[f"/{m.group(1)}/{{id}}/{{n}}.html"] += 1
            chapter_samples.append((h, t[:24]))
            continue
        m = re.search(r"/([a-z]+)/([a-z0-9]+)/([^/]+)\.html", h)
        if m:
            pat_counter[f"/{m.group(1)}/{{id}}/..."] += 1
            chapter_samples.append((h, t[:24]))
    ev["link_count"] = len(hrefs)
    ev["link_patterns"] = [{"pattern": p, "count": c} for p, c in pat_counter.most_common(5)]
    ev["chapter_url_samples"] = [h for h, _ in chapter_samples[:5]]

    # ---- 正文容器 (用通用候选容器找最长文本) ----
    cands = []
    for el in soup.find_all(["div", "article", "section", "td", "dd"]):
        t = el.get_text(strip=True)
        if 300 < len(t) < 200000:
            cands.append((len(t), el.name, ".".join((el.get("class") or [])[:2]), el.get("id") or "", t[:200]))
    cands.sort(reverse=True)
    ev["content_container_candidates"] = [
        {"len": c[0], "tag": c[1], "class": c[2], "id": c[3], "preview": c[4]}
        for c in cands[:3]
    ]
    # 页眉污染与占位判断
    top = cands[0][4] if cands else ""
    ev["placeholder_page"] = any(k in top for k in _PLACEHOLDER_TEXT)
    ev["ad_header"] = [k for k in _AD_HEADER if k in top]
    ev["meta_prefix"] = bool(re.search(r"作者[:：]", top[:60]))
    return ev


def probe_chapter_sample(session, catalog_url, sample_href):
    """抽样一章正文页: 判定 混淆/占位/容器/页眉 (目录页探测不到的正文侧信息)。"""
    from bs4 import BeautifulSoup
    base = re.match(r'^(https?://[^/]+)', catalog_url).group(1)
    url = sample_href if sample_href.startswith("http") else base + sample_href
    out = {"sample_url": url}
    try:
        r = session.get(url, timeout=15)
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        return out
    out["status"] = r.status_code
    html = r.text
    out["obfuscation"] = detect_obfuscation(html)
    soup = BeautifulSoup(html, "html.parser")
    cands = []
    for el in soup.find_all(["div", "article", "td", "dd", "section"]):
        t = el.get_text(strip=True)
        if 300 < len(t) < 200000:
            cands.append((len(t), el.name, ".".join((el.get("class") or [])[:2]),
                          el.get("id") or "", t[:220]))
    cands.sort(reverse=True)
    if cands:
        c = cands[0]
        top = c[4]
        out["container"] = {"tag": c[1], "class": c[2], "id": c[3], "len": c[0]}
        out["placeholder"] = any(k in top for k in _PLACEHOLDER_TEXT)
        out["ad_header"] = [k for k in _AD_HEADER if k in top]
        out["meta_prefix"] = bool(re.search(r"作者[:：]", top[:60]))
        out["preview"] = top[:80]
    else:
        out["container"] = None
    return out


def build_suggestion(ev, catalog_url):
    """evidence -> SITE_PATTERNS 草稿 (纯函数)。"""
    sug = {"domain": re.sub(r"^https?://", "", catalog_url).split("/")[0],
           "url": catalog_url}
    cp = ev.get("chapter_probe") or {}
    obf = list(ev.get("obfuscation") or []) + list(cp.get("obfuscation") or [])
    container = (ev.get("content_container_candidates") or [{}])[0]
    if cp.get("container"):
        container = cp["container"]
    sug["container_hint"] = {"tag": container.get("tag"),
                              "selector": (f"#{container['id']}" if container.get("id")
                                           else ("." + container["class"].split(".")[0] if container.get("class") else ""))}
    placeholder = ev.get("placeholder_page") or cp.get("placeholder")
    # pattern 判定: 数据文件 > 强混淆 base64 > html_selector > 需专用
    if "datafile_ext" in obf or "initTxt/loadTxt" in obf:
        sug["pattern"] = "datafile"
    elif "qsbs_bb" in obf or "str_decode" in obf or "base64_like" in obf:
        sug["pattern"] = "qsbs_bb"
    elif placeholder:
        sug["pattern"] = "datafile"  # 占位正文大概率走数据文件/渲染
        sug["needs_crawler_or_render"] = True
    else:
        sug["pattern"] = "html_selector"
    # catalog 形态提示
    pats = ev.get("link_patterns") or []
    if any(p["count"] >= 10 and "分卷" in (ev.get("title") or "") for p in pats):
        sug["catalog"] = "分卷式, 可能需要专用 parser"
    elif pats:
        sug["catalog"] = f"候选模式: {pats[0]['pattern']} (count={pats[0]['count']})"
    ad_header = list(ev.get("ad_header") or []) + list(cp.get("ad_header") or [])
    meta = ev.get("meta_prefix") or cp.get("meta_prefix")
    sug["content_extractor"] = "建议: " + ("需剥离页眉广告" if ad_header else "无") + \
        (" + 剥离书名作者前缀" if meta else "")
    sug["anti_spider_notes"] = ev.get("engine_error") or (
        "直连可达" if ev.get("direct_ok") else "首包异常, 需爬虫会话/浏览器重测")
    if cp.get("status"):
        sug["chapter_sample"] = f"status={cp['status']} 混淆={cp.get('obfuscation') or '无'}"
    return sug


def main():
    ap = argparse.ArgumentParser(description="新站探测 -> SITE_PATTERNS 草稿")
    ap.add_argument("url")
    ap.add_argument("--json", action="store_true", help="只输出 JSON 草稿")
    ap.add_argument("--crawler", action="store_true",
                    help="首包异常时用爬虫会话(UA/质询处理) 重试")
    ap.add_argument("--offline-html", help="用本地 HTML 快照替代网络(用于回放回归)")
    args = ap.parse_args()

    import requests
    session = requests.Session()
    session.headers.update({
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    if args.offline_html:
        html = Path(args.offline_html).read_text(encoding="utf-8", errors="replace")
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        ev = {
            "url": args.url, "direct_ok": True, "direct_status": 200, "engine": "offline",
            "title": soup.title.get_text(strip=True)[:60] if soup.title else "",
            "obfuscation": detect_obfuscation(html),
        }
        hrefs = [a.get("href", "") for a in soup.find_all("a", href=True) if a.get("href")]
        cands = []
        for el in soup.find_all(["div", "article", "td", "dd"]):
            t = el.get_text(strip=True)
            if 300 < len(t) < 200000:
                cands.append((len(t), el.name, ".".join((el.get("class") or [])[:2]), el.get("id") or "", t[:200]))
        cands.sort(reverse=True)
        ev["content_container_candidates"] = [
            {"len": c[0], "tag": c[1], "class": c[2], "id": c[3], "preview": c[4]} for c in cands[:3]
        ]
        top = cands[0][4] if cands else ""
        ev["placeholder_page"] = any(k in top for k in _PLACEHOLDER_TEXT)
        ev["ad_header"] = [k for k in _AD_HEADER if k in top]
        ev["meta_prefix"] = bool(re.search(r"作者[:：]", top[:60]))
        ev["link_count"] = len(hrefs)
        ev["link_patterns"] = []
    else:
        ev = probe_catalog(session, args.url, use_crawler=args.crawler)
        # 目录页探测到章节链接时, 逐一抽样(最多4个)选首个有正文特征的页面做正文侧判定
        samples = ev.get("chapter_url_samples") or []
        picked = None
        for s in samples:
            cp = probe_chapter_sample(session, args.url, s)
            obf = cp.get("obfuscation") or []
            cont = cp.get("container") or {}
            if obf or cp.get("placeholder") or (cont and cont.get("len", 0) > 1000):
                picked = cp
                break
            picked = cp  # 兜底: 记录最后一次尝试
        if picked:
            ev["chapter_probe"] = picked
    sug = build_suggestion(ev, args.url)
    if args.json:
        print(json.dumps(sug, ensure_ascii=False, indent=2))
        return
    print("=" * 60)
    print(f"站点     : {sug['domain']}")
    print(f"页面标题 : {(ev.get('title') or '?')[:50]}")
    print(f"直连可达 : {ev.get('direct_ok')} (status={ev.get('direct_status')}, engine={ev.get('engine')})")
    print(f"混淆特征 : {ev.get('obfuscation') or '无'}"
          + (f" | 章节页: {sug.get('chapter_sample','')}" if sug.get('chapter_sample') else ""))
    print(f"占位页   : {ev.get('placeholder_page')}  页眉广告: {ev.get('ad_header') or '无'}  书名作者前缀: {ev.get('meta_prefix')}")
    print(f"链接形态 : {ev.get('link_count')} 条; " +
          ", ".join(f"{p['pattern']}×{p['count']}" for p in (ev.get('link_patterns') or [])[:3]) or "无规律")
    cont = ev.get("content_container_candidates") or []
    if cont:
        c = cont[0]
        print(f"正文容器 : <{c['tag']}> id={c['id'] or '-'} class={c['class'] or '-'} ~{c['len']}字符")
        print(f"  预览   : {c['preview'][:80]}...")
    print("-" * 60)
    print(f"建议 pattern : {sug['pattern']}")
    if sug.get("catalog"):
        print(f"目录形态     : {sug['catalog']}")
    if sug.get("content_extractor"):
        print(f"提取器建议   : {sug['content_extractor']}")
    print(f"反爬备注     : {sug['anti_spider_notes']}")
    print("=" * 60)
    print("JSON: 加 --json 输出草稿; 加入 sites_config 前请人工核对。")


if __name__ == "__main__":
    main()
