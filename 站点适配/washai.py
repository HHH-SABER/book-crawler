# -*- coding: utf-8 -*-
"""书海阁 (washai.net) 站点适配器。

问题背景 (2026-09-26 用户实测 "禁神之下" 目录收集 0 章):
  - 目录 URL 形如 /book/indexList-{bookid}.html (连字符形态), 通用
    _resolve_novel_paths 的 URL 模式全部匹配不上 → novel_path 为空;
  - 通用兜底因 "novel_path 为空不启用路径过滤" 的保护逻辑, 拒收全部
    /book/{bookid}/{cid}.html 章节链接 (21 页分页遍历完仍 0 章)。

站点结构 (2026-09-26 在线实测):
  - 目录: 第1页 /book/indexList-{bid}.html, 第N页 /book/indexList/{bid}/{N}.html;
    每页 100 章, 末页不足 100; 溢出页 (第22页) 返回**无章节链接的空目录**,
    靠 "本页 0 新章即停" 收尾; 分页入口: a.pgBtn("下一页") + link[rel=next]。
  - 章节链接: /book/{bid}/{cid}.html, **无 rel="chapter" 标记**;
    cid 不随章号单调 (第1章 cid 尾 415, 第100章尾 222, 第101章尾 223),
    **禁止按 cid 排序** — 排序键用标题里的 "第N章", 默认保持目录页顺序。
  - 正文: #readcontent 下 .txtwrap#readPanel 内纯文本 <p>, 服务端直出
    (免费章无内部分页, 页面标注 "1/1"); #vipPanel 与正文同级但内无 <p>,
    只取 <p> 天然排除 VIP 提示与页头 (书名/作者/字数/更新时间)。
  - 作品页 /book/{bid}.html 仅 1 个最新章链接 + indexList 入口, 需跳转目录页。
  - 目录页 <title> 形如 "《禁神之下》-我叫方寸-章节目录-最新章节列表-书海阁"。
"""
import re

try:
    import 日志 as _app_log
    _log = _app_log.get('adapter.washai')
except Exception:  # 独立环境无项目日志模块时退化为标准 logging
    import logging
    _log = logging.getLogger('adapter.washai')

SITE = {
    "domain": "washai.net",
    "pattern": "html_selector",
    "chapter_url_regex": r"/book/\d+/\d+\.html",
    "content_selectors": ["#readcontent", "#readPanel"],
    "anti_spider": {"type": "auto"},
}

# 章节链接: /book/{bid}/{cid}.html (bid 从目录 URL 提取后动态拼入)
_章节RE = re.compile(r'^/book/(\d+)/(\d+)\.html$')
# 目录第1页 (连字符形态) /book/indexList-{bid}.html (search 用, 不锚定行首)
_目录首页RE = re.compile(r'/book/indexList-(\d+)\.html$')
# 目录第N页 /book/indexList/{bid}/{N}.html
_目录页RE = re.compile(r'^/book/indexList/(\d+)/(\d+)\.html$')
# 标题尾部免费/付费标记: "第1章 xxx [免费]" / "第1章 xxx[免费]"
_免费标记RE = re.compile(r'\s*[\[［【](免费|付费|VIP|vip)[\]］】]$')
# 章节号 (排序用): "第123章 ..."
_章号RE = re.compile(r'第(\d+)章')

# 目录分页安全上限 (实测 21 页 + 1 溢出页; 2020 章 / 100 章每页)
_最大目录页数 = 40


def _书ID(catalog_url):
    """从目录/作品页 URL 提取 book id; 失败返回 None"""
    m = (_目录首页RE.search((catalog_url or '').split('?')[0].rstrip('/'))
         or re.search(r'/book/indexList/(\d+)', catalog_url or '')
         or re.search(r'/book/(\d+)(?:\.html)?$', catalog_url or ''))
    return m.group(1) if m else None


def _章节排序键(chap):
    """按标题 "第N章" 排序; 提取不到的保持原相对位置 (稳定排序)

    注意: 本站 cid 不随章号单调, 严禁按 URL 尾号排序。
    """
    m = _章号RE.search(chap.get('title', ''))
    return int(m.group(1)) if m else float('inf')


def _章节标题(a):
    """章节名: title 属性优先, 去掉尾部 [免费]/[付费] 标记"""
    t = (a.get('title') or a.get_text(strip=True) or '').strip()
    return _免费标记RE.sub('', t).strip()


def parse_catalog(soup, catalog_url, base_url, **kw):
    """目录解析: 逐页跟随 "下一页" 收集全部章节

    Args:
        soup: 首个目录页 BeautifulSoup (主程序已抓取 catalog_url)
        catalog_url: 目录页 URL (indexList-*.html / indexList/{bid}/{N}.html
                     / 作品页 /book/{bid}.html 均可)
        base_url: 站点根 URL
        kw: sort_chapters / fetch(抓取额外目录页的回调)
    Returns:
        list[dict] | None (无法提取书 ID 时 None, 回退通用解析)
    """
    sort_chapters = kw.get('sort_chapters', True)
    fetch = kw.get('fetch')
    book_id = _书ID(catalog_url)
    if not book_id:
        _log.info(f"[washai] 无法从URL提取小说ID, 回退通用解析: {catalog_url}")
        return None
    _log.info(f"[washai] 小说ID: {book_id}")

    # 作品页 (/book/{bid}.html) 只有 1 个最新章链接, 跳转到 indexList 目录页
    if 'indexList' not in (catalog_url or '') and soup is not None and fetch:
        entry = soup.find('a', href=re.compile(rf'^/book/indexList-{book_id}\.html$'))
        if entry:
            real_url = entry['href'] if entry['href'].startswith('http') \
                else base_url.rstrip('/') + entry['href']
            _log.info(f"[washai] 作品页跳转目录页: {real_url}")
            real_soup = fetch(real_url)
            if real_soup is not None:
                soup, catalog_url = real_soup, real_url

    _章节RE本站 = re.compile(rf'^/book/{book_id}/\d+\.html$')
    chapters = []
    seen = set()
    page_soup = soup
    page_no = 1
    while page_soup is not None and page_no <= _最大目录页数:
        new_on_page = 0
        for a in page_soup.find_all('a', href=True):
            href = (a.get('href') or '').strip()
            if not _章节RE本站.match(href.split('?')[0]):
                continue
            if href in seen:
                continue
            title = _章节标题(a)
            if not title:
                continue
            seen.add(href)
            url = href if href.startswith('http') else base_url.rstrip('/') + href
            chapters.append({'title': title, 'url': url})
            new_on_page += 1
        _log.info(f"[washai] 目录第{page_no}页: 新增 {new_on_page} 章, 累计 {len(chapters)} 章")

        # 溢出页/末页: 0 新章即停 (实测第22页是无章节链接的空目录)
        if new_on_page == 0:
            break
        # 下一页: link[rel=next] 优先, 回退 a.pgBtn("下一页")
        next_url = None
        nxt = page_soup.find('link', rel=lambda v: v and 'next' in v)
        if nxt and nxt.get('href'):
            next_url = nxt['href']
        else:
            btn = page_soup.find('a', class_='pgBtn', string=lambda s: s and '下一页' in s)
            if btn and btn.get('href'):
                next_url = btn['href']
        if not next_url:
            break
        if not next_url.startswith('http'):
            next_url = base_url.rstrip('/') + next_url
        page_no += 1
        _log.info(f"[washai] 抓取目录第{page_no}页: {next_url}")
        page_soup = fetch(next_url) if fetch else None

    if sort_chapters and chapters:
        chapters.sort(key=_章节排序键)
    _log.info(f"[washai] 共提取 {len(chapters)} 个章节 (遍历 {page_no} 页)")
    for i, chap in enumerate(chapters[:5]):
        _log.info(f"  {i+1}. {chap['title'][:40]} -> {chap['url']}")
    if len(chapters) > 5:
        _log.info(f"  ... 共 {len(chapters)} 章")
    return chapters or None


def extract_content(soup, page_url, base_url, **kw):
    """正文提取: #readcontent 内纯文本 <p> 段落

    VIP 提示 (#vipPanel) 与页头信息 (.book_title) 不含 <p>, 只取 <p> 天然排除;
    选择器均落空时返回 None 走通用提取。
    """
    if soup is None:
        return None
    for sel in ('#readcontent', '#readPanel'):
        el = soup.select_one(sel)
        if el is None:
            continue
        parts = [p.get_text(strip=True) for p in el.find_all('p')
                 if p.get_text(strip=True)]
        if parts:
            text = '\n\n'.join(parts)
            _log.info(f"[washai] {sel} 提取 {len(parts)} 段, {len(text)} 字符")
            return text
        # 无 <p> 时取容器明文 (站点改版兼容)
        t = el.get_text('\n', strip=True)
        if t:
            _log.info(f"[washai] {sel} 明文回退 {len(t)} 字符")
            return t
    _log.info("[washai] 未找到正文容器")
    return None


def paginate(current_url, page_index, **kw):
    """章内分页: 无 (免费章单页直出, 页面标注 "1/1")

    显式返回 None 让主循环在第一页后干净停止, 避免落到通用
    `_{page_index}.html` 规则对每章多发一次无效请求。
    """
    return None


def catalog_from_chapter(chapter_url, base_url=None):
    """章节页 /book/{bid}/{cid}.html → 目录页 /book/indexList-{bid}.html"""
    m = re.match(r'^https?://[^/]+/book/(\d+)/\d+\.html$',
                 (chapter_url or '').strip())
    if not m:
        return None
    host = re.match(r'^https?://[^/]+', (base_url or chapter_url))
    if not host:
        return None
    return f"{host.group(0)}/book/indexList-{m.group(1)}.html"


def get_title(soup, catalog_url, base_url):
    """书名: 页面 <title> 形如 "《禁神之下》-我叫方寸-章节目录-...-书海阁" → 禁神之下"""
    if soup is not None:
        meta = soup.select_one('meta[property="og:novel:book_name"], '
                               'meta[name="og:novel:book_name"]')
        if meta and meta.get('content'):
            return meta['content'].strip()
        if soup.title and soup.title.string:
            m = re.search(r'《(.+?)》', soup.title.string)
            if m:
                return m.group(1).strip()
    return None
