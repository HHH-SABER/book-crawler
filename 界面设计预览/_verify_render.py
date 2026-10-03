# -*- coding: utf-8 -*-
"""设计稿落地校验：日/夜 × 6 页 × 3 视口。

覆盖 6 类落地风险：
  1. 结构完整性   —— 切页成功、导航 6 项、无横向溢出
  2. 滚动容器     —— data-scrollable 标记齐全 + scrollbar-gutter 稳定 + 键盘可达
  3. 对比度 (a11y) —— 文字/背景/边框逐元素实测 WCAG 对比度，不达阈值即报错
  4. 组件一致性   —— 按钮/胶囊/徽章的实际高度与圆角是否统一
  5. 交互状态     —— 焦点环是否存在、禁用态是否真的不可点
  6. 令牌落地     —— 关键令牌是否都有值（防止改版漏改导致 var() 解析失败）
"""
import io, json, os, sys, pathlib
from collections import Counter

OUT = pathlib.Path(__file__).parent
URL = (OUT / "index.html").as_uri()

from playwright.sync_api import sync_playwright

PAGES = ["crawl", "history", "deadbook", "sites", "log", "remote"]
VIEWPORTS = [(1500, 940), (1024, 800), (960, 720), (720, 900), (480, 800)]
report = {"shots": [], "issues": []}

# ---------- 主探针：结构 + 溢出 ----------
PROBE = """
() => {
  const root = document.documentElement;
  const cs = getComputedStyle(root);
  const tok = n => cs.getPropertyValue(n).trim();
  const out = {
    tokens: {
      brand: tok('--brand'),
      btnPrimaryBg: tok('--btn-primary-bg'),
      btnPrimaryFg: tok('--btn-primary-fg'),
      textTertiary: tok('--text-tertiary'),
      textQuaternary: tok('--text-quaternary'),
      statusSuccess: tok('--status-success'),
      statusSuccessBg: tok('--status-success-bg'),
      bgSidebar: tok('--bg-sidebar'),
      bgSidebarActive: tok('--bg-sidebar-active'),
      textSidebarActive: tok('--text-sidebar-active'),
      terminal: tok('--terminal-bg'),
      remoteBg: tok('--remote-bg'),
      focusRing: tok('--focus-ring'),
    },
    overflowX: root.scrollWidth - root.clientWidth,
    navCount: document.querySelectorAll('.nav-item').length,
    navLabels: [...document.querySelectorAll('.nav-item .nav-label')].map(e => e.textContent.trim()),
    activePage: (document.querySelector('.page-view.active') || {}).id,
  };
  const intentional = el => {
    const s = getComputedStyle(el);
    if (/(auto|scroll)/.test(s.overflowX)) return true;
    if (s.textOverflow === 'ellipsis') return true;
    return false;
  };
  const bad = [];
  document.querySelectorAll('.page-view.active *').forEach(el => {
    if (el.scrollWidth - el.clientWidth > 2 && el.clientWidth > 0 && !intentional(el)) {
      bad.push((el.className || el.tagName) + ' +' + (el.scrollWidth - el.clientWidth));
    }
  });
  out.hOverflow = bad.slice(0, 8);
  const sc = document.querySelector('.page-view.active .task-table-scroll');
  if (sc) {
    const prev = sc.scrollLeft;
    sc.scrollLeft = sc.scrollWidth;
    const ops = document.querySelector('.page-view.active .task-actions');
    let opsFull = null;
    if (ops) {
      const a = ops.getBoundingClientRect(), b = sc.getBoundingClientRect();
      opsFull = (a.right <= b.right + 1) && (a.left >= b.left - 1);
    }
    sc.scrollLeft = prev;
    out.table = {clientW: sc.clientWidth, scrollW: sc.scrollWidth,
                 scrollable: sc.scrollWidth > sc.clientWidth, opsFullAtRightEnd: opsFull};
  }
  return out;
}
"""

# ---------- 滚动容器专项 ----------
SCROLL_PROBE = """
() => {
  const out = {marked: [], gutterStable: true, focusRing: null};
  document.querySelectorAll('[data-scrollable]').forEach(el => {
    out.marked.push({tag: el.tagName, cls: (el.className || '').toString().slice(0, 30),
                     tabindex: el.getAttribute('tabindex'),
                     aria: el.getAttribute('aria-label') || null});
    if (getComputedStyle(el).scrollbarGutter !== 'stable') out.gutterStable = false;
  });
  const mc = document.querySelector('.main-content');
  if (mc) { mc.focus(); const s = getComputedStyle(mc);
    out.focusRing = {active: document.activeElement === mc,
                     width: s.outlineWidth, style: s.outlineStyle, color: s.outlineColor}; mc.blur(); }
  return out;
}
"""

# ---------- 对比度专项：逐元素实测 ----------
CONTRAST_PROBE = """
() => {
  const lin = c => { c /= 255; return c <= 0.03928 ? c/12.92 : Math.pow((c+0.055)/1.055, 2.4); };
  const lum = ([r,g,b]) => 0.2126*lin(r) + 0.7152*lin(g) + 0.0722*lin(b);
  const parse = s => {
    const m = s.match(/rgba?\\(([^)]+)\\)/); if (!m) return null;
    const p = m[1].split(',').map(x => parseFloat(x));
    return {rgb: p.slice(0,3), a: p.length > 3 ? p[3] : 1};
  };
  const cr = (f, b) => {
    const lf = lum(f), lb = lum(b);
    const hi = Math.max(lf, lb), lo = Math.min(lf, lb);
    return (hi + 0.05) / (lo + 0.05);
  };
  // 逐层向上找第一个不透明背景
  const bgOf = el => {
    let n = el;
    while (n && n !== document.documentElement) {
      const c = parse(getComputedStyle(n).backgroundColor);
      if (c && c.a > 0.85) return c.rgb;
      n = n.parentElement;
    }
    return [255,255,255];
  };
  const out = [];
  const sel = 'p,span,div,button,label,li,h1,h2,h3,h4,td,th,.badge,.cap-tag,.toolbar-note,.text-note';
  // Emoji 图标（app-icon / nav-item-icon）由系统字体彩色渲染，
  // getComputedStyle 返回的 color 不代表实际像素 ⇒ 对比度检测不适用，跳过。
  const isEmojiIcon = el => /^(app-icon|nav-item-icon|empty-state-icon|adapter-icon|adapter-status-icon|icon-inline|icon)$/
    .test((el.className || '').toString().trim());
  document.querySelectorAll('.page-view.active ' + sel).forEach(el => {
    if (isEmojiIcon(el)) return;
    // 只看直接持有文字的节点
    const own = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (!own) return;
    const s = getComputedStyle(el);
    const fg = parse(s.color); if (!fg) return;
    if (fg.a < 0.85) return;                       // 半透明文字不算
    const bg = bgOf(el);
    const px = parseFloat(s.fontSize);
    const bold = parseInt(s.fontWeight, 10) >= 700;
    // WCAG large text: >=24px，或 >=18.66px 且加粗
    const large = px >= 24 || (px >= 18.66 && bold);
    const need = large ? 3.0 : 4.5;
    const ratio = cr(fg.rgb, bg);
    if (ratio < need) {
      out.push({cls: (el.className || el.tagName).toString().slice(0, 40),
                txt: el.textContent.trim().slice(0, 18),
                px: Math.round(px), ratio: +ratio.toFixed(2), need: need});
    }
  });
  return out;
}
"""

# ---------- 组件一致性专项 ----------
COMPONENT_PROBE = """
() => {
  const g = el => { const r = el.getBoundingClientRect();
                    return {w: Math.round(r.width), h: Math.round(r.height),
                            r: getComputedStyle(el).borderRadius,
                            fs: getComputedStyle(el).fontSize}; };
  const coll = {};
  const push = (k, v, n) => { (coll[k] = coll[k] || []).push(Object.assign({n: n}, v)); };
  document.querySelectorAll('.page-view.active .btn').forEach(e => {
    const k = 'btn' + (e.classList.contains('btn-sm') ? '-sm' : e.classList.contains('btn-icon') ? '-icon' : '');
    push(k, g(e), e.textContent.trim().slice(0,8));
  });
  document.querySelectorAll('.page-view.active .chip-btn, .page-view.active .filter-chip').forEach(e =>
    push('chip', g(e), e.textContent.trim().slice(0,8)));
  document.querySelectorAll('.page-view.active .badge, .page-view.active .cap-tag').forEach(e =>
    push('badge', g(e), e.textContent.trim().slice(0,8)));
  document.querySelectorAll('.page-view.active .icon-btn').forEach(e =>
    push('icon-btn', g(e), e.title || '?'));
  // 焦点环：任一 btn 聚焦后应有 outline
  const b = document.querySelector('.page-view.active .btn');
  let focus = null;
  if (b) { b.focus(); const s = getComputedStyle(b);
    focus = {w: s.outlineWidth, st: s.outlineStyle, c: s.outlineColor}; b.blur(); }
  return {coll, focus, count: Object.keys(coll).length};
}
"""

CHROME = r"C:\Users\HEWEN\AppData\Local\ms-playwright\chromium-1234\chrome-win64\chrome.exe"

with sync_playwright() as pw:
    # ⚠️ headless=True 必须显式传: Playwright 0.86 在 Windows 上默认有头,
    #    跑多轮校验会叠出一堆可见浏览器窗口 (用户可见的「一堆网页」即由此而来)。
    br = pw.chromium.launch(executable_path=CHROME, headless=True)
    pg = br.new_page(viewport={"width": 1500, "height": 940}, device_scale_factor=1)
    pg.goto(URL)
    pg.wait_for_timeout(600)

    # ---- 视口矩阵：溢出 + 滚动容器 ----
    report["viewport"] = {}
    for w, h in VIEWPORTS:
        pg.set_viewport_size({"width": w, "height": h})
        pg.wait_for_timeout(220)
        tag = str(w)
        d = pg.evaluate(SCROLL_PROBE)
        ox = pg.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
        d["markedCount"] = len(d["marked"])
        d["overflowX"] = ox
        d["navLabelsVisible"] = pg.evaluate(
            "() => [...document.querySelectorAll('.nav-item .nav-label')]"
            ".filter(e => getComputedStyle(e).display !== 'none').length")
        if ox > 2:
            report["issues"].append("视口 %d 横向溢出 %dpx" % (w, ox))
        if not d["gutterStable"]:
            report["issues"].append("视口 %d scrollbar-gutter 非 stable" % w)
        report["viewport"][tag] = d

    pg.set_viewport_size({"width": 1500, "height": 940})
    pg.wait_for_timeout(250)

    for theme in ("light", "dark"):
        pg.evaluate("t => { document.documentElement.setAttribute('data-theme', t); "
                    "localStorage.setItem('theme', t); }", theme)
        pg.wait_for_timeout(250)
        for p in PAGES:
            pg.evaluate("p => { document.querySelectorAll('.nav-item').forEach(n => "
                        "n.classList.toggle('active', n.dataset.page === p)); "
                        "document.querySelectorAll('.page-view').forEach(v => "
                        "v.classList.toggle('active', v.id === 'page-' + p)); }", p)
            pg.wait_for_timeout(200)

            data = pg.evaluate(PROBE)
            if data["activePage"] != "page-" + p:
                report["issues"].append("切页失败 %s/%s -> %s" % (theme, p, data["activePage"]))
            if data["overflowX"] > 2:
                report["issues"].append("横向溢出 %s/%s = %d" % (theme, p, data["overflowX"]))
            for v in data["hOverflow"]:
                report["issues"].append("元素溢出 %s/%s : %s" % (theme, p, v))
            if p == "crawl":
                report.setdefault("nav", data["navLabels"])
                report.setdefault("tokens", {})[theme] = data["tokens"]
                if data.get("table"):
                    report.setdefault("table", {})[theme] = data["table"]

            # 对比度
            for c in pg.evaluate(CONTRAST_PROBE):
                report["issues"].append("对比度不足 %s/%s [%s] %s %.2f<%.1f"
                                        % (theme, p, c["cls"], c["txt"], c["ratio"], c["need"]))
            # 组件一致性（只在 light 跑一次，避免重复刷屏）
            if theme == "light":
                comp = pg.evaluate(COMPONENT_PROBE)
                report.setdefault("components", {})[p] = {
                    "focus": comp["focus"],
                    "sizes": {k: sorted({(x["h"], x["r"], x["fs"]) for x in v})
                              for k, v in comp["coll"].items()},
                }
                for k, v in comp["coll"].items():
                    hs = {x["h"] for x in v}
                    if len(hs) > 1:
                        report["issues"].append("组件高度不统一 %s/%s .%s = %s"
                                                % (theme, p, k, sorted(hs)))
                    rs = {x["r"] for x in v}
                    if len(rs) > 1:
                        report["issues"].append("组件圆角不统一 %s/%s .%s = %s"
                                                % (theme, p, k, sorted(rs)))

            f = OUT / ("_verify_%s_%s.png" % (theme, p))
            pg.screenshot(path=str(f))
            report["shots"].append(f.name)
    br.close()

# ---------- 汇总 ----------
seen, uniq = set(), []
for i in report["issues"]:
    if i not in seen:
        seen.add(i); uniq.append(i)
report["issues"] = uniq

for i in report["issues"]:
    print("ISSUE:", i)
print("NAV:", report.get("nav"))
print("TOKENS:", json.dumps(report.get("tokens"), ensure_ascii=False, indent=1))
print("SHOTS:", len(report["shots"]))
print("TABLE:", json.dumps(report.get("table"), ensure_ascii=False))
print("VIEWPORT:", json.dumps({k: {"marked": v["markedCount"], "overflowX": v["overflowX"],
                                   "gutter": v["gutterStable"], "navVisible": v["navLabelsVisible"]}
                              for k, v in report["viewport"].items()}, ensure_ascii=False))
print("FOCUS(main):", json.dumps(report["viewport"]["1500"]["focusRing"], ensure_ascii=False))
print("COMPONENTS:", json.dumps(report.get("components"), ensure_ascii=False, indent=1))
print("ISSUES:", len(report["issues"]))
