# -*- coding: utf-8 -*-
"""月亮小说网 (yueliang.org) 站点适配器。

问题背景 (2026-09-13 用户实测 "禁神之下" 整单失败):
  - 目录 URL 形如 /txt{bookid}.html, 通用 _resolve_novel_paths 推导不出
    novel_path (既不是 /book/ 也不是 /read/ 前缀), 通用链接过滤后只剩
    1 个导航链接被当章节抓, 整单失败;
  - 章内分页第2页是 {cid}_2.html (不是通用默认的 _1.html), 分页规则算错。

修复:
  - 目录: 只认 rel="chapter" 且 href 匹配 /read/{bookid}/{cid}.html。
  - 正文: #booktxt 内纯文本 <p>。
  - 分页: 第2页起为 {cid}_2.html (页码 = page_index + 1)。

已探测边界 (2026-09-13 在线实测):
  - 目录单页含全部章节 (样本 ~400KB / 2029 章), 无需目录分页。
  - 不存在的分页返回**末页**内容 → 靠主循环"与上一页指纹相同则终止"收尾,
    无需特判。
"""
import re

try:
    import 日志 as _app_log
    _log = _app_log.get('adapter.yueliang')
except Exception:  # 独立环境无项目日志模块时退化为标准 logging
    import logging
    _log = logging.getLogger('adapter.yueliang')

SITE = {
    "domain": "yueliang.org",
    "pattern": "html_selector",
    "chapter_url_regex": r"/read/\d+/\d+\.html",
    "content_selectors": ["#booktxt", "#chaptercontent"],
    "anti_spider": {"type": "auto"},
}

# 章节链接或章内分页: /read/{bid}/{cid}(|_{N})?.html
_章节RE = re.compile(r'^/read/\d+/\d+(_\d+)?\.html$')


def _章节排序键(chap):
    """按章节 URL 尾号排序"""
    m = re.search(r'/(\d+)(?:_\d+)?\.html$', chap.get('url', ''))
    return int(m.group(1)) if m else 999999


def _章节标题(a, book_id):
    """章节名: title 属性干净; 无 title 时取 <dd> 文本"""
    t = (a.get('title') or a.get_text(strip=True) or '').strip()
    return t


def parse_catalog(soup, catalog_url, base_url, **kw):
    """目录解析: 单页全部章节, 只认 rel="chapter" 的 /read/ 链接"""
    sort_chapters = kw.get('sort_chapters', True)
    book_m = re.search(r'/txt(\d+)\.html', catalog_url)
    book_id = book_m.group(1) if book_m else ''
    chapters = []
    seen = set()
    if soup is not None:
        for a in soup.find_all('a', href=True):
            href = (a.get('href') or '').strip()
            if not re.match(r'^/read/\d+/\d+\.html$', href):
                continue
            if 'chapter' not in (a.get('rel') or []):
                continue  # 排除"马上阅读"等无 rel 的入口链接
            title = _章节标题(a, book_id)
            if not title or href in seen:
                continue
            seen.add(href)
            url = href if href.startswith('http') else base_url + href
            chapters.append({'title': title, 'url': url})
    if sort_chapters and chapters:
        chapters.sort(key=_章节排序键)
    _log.info(f"[yueliang] 共提取 {len(chapters)} 个章节")
    for i, chap in enumerate(chapters[:5]):
        _log.info(f"  {i+1}. {chap['title'][:40]} -> {chap['url']}")
    if len(chapters) > 5:
        _log.info(f"  ... 共 {len(chapters)} 章")
    return chapters or None


def extract_content(soup, page_url, base_url, **kw):
    """正文提取: #booktxt 内 <p> 段落, 无则 #chaptercontent 兜底"""
    if soup is None:
        return None
    for sel in ('#booktxt', '#chaptercontent'):
        el = soup.select_one(sel)
        if el is None:
            continue
        parts = [p.get_text(strip=True) for p in el.find_all('p')
                 if p.get_text(strip=True)]
        if parts:
            text = '\n\n'.join(parts)
            _log.info(f"[yueliang] {sel} 提取 {len(parts)} 段, {len(text)} 字符")
            return text
    # 无 <p> 时直接取文本
    for sel in ('#booktxt', '#chaptercontent'):
        el = soup.select_one(sel)
        if el is not None:
            t = el.get_text('\n', strip=True)
            if t:
                return t
    _log.info("[yueliang] 未找到正文容器")
    return None


def paginate(current_url, page_index, **kw):
    """章内分页: 第2页起为 {cid}_2.html (page_index=1 → _2)"""
    m = re.search(r'/read/(\d+)/(\d+)(?:_\d+)?\.html$', (current_url or '').strip())
    if not m:
        return None
    return f'/read/{m.group(1)}/{m.group(2)}_{page_index + 1}.html'


def catalog_from_chapter(chapter_url, base_url=None):
    """章节页 /read/{bid}/{cid}.html → 目录页 /txt{bid}.html"""
    m = re.match(r'^https?://[^/]+/read/(\d+)/\d+(?:_\d+)?\.html$',
                 (chapter_url or '').strip())
    if not m:
        return None
    host = re.match(r'^https?://[^/]+', (base_url or chapter_url))
    if not host:
        return None
    return f"{host.group(0)}/txt{m.group(1)}.html"


def get_title(soup, catalog_url, base_url):
    """书名: 目录页 <title> 形如
    '禁神之下最新章节_禁神之下全文免费阅读-月亮小说网' → 首段 '禁神之下'"""
    if soup is not None:
        meta = soup.select_one('meta[property="og:novel:book_name"], meta[name="og:novel:book_name"]')
        if meta and meta.get('content'):
            return meta['content'].strip()
    if soup is not None and soup.title and soup.title.string:
        t = soup.title.string.split('_')[0].strip()
        for 词 in ('最新章节', '全文阅读', '全文免费阅读'):
            t = t.replace(词, '')
        t = t.strip(' -_')
        if t:
            return t
    return None