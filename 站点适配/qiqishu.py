# -*- coding: utf-8 -*-
"""奇书网 (qiqishu.cc) 站点适配器。

问题背景 (2026-09-13 用户实测 "深空彼岸" 整单失败):
  - 章节链接 /read/{bookid}/{cid}.html 不在通用 novel_path (/book/) 下,
    通用链接过滤整单抓不到, 只剩 1 个"点击查看全部章节目录"导航被当章节抓;
  - 正文页正文藏在 <script>document.writeln(对象.方法('BASE64'))</script>,
    且对象名每页随机 (mec.eng / wmm.uz / zhju.etculg), 无法按固定函数名匹配。

修复:
  - 目录: 只认 rel="chapter" 且 href 匹配 /read/{bookid}/{cid}.html;
    页码从 <select> 的 option (/book/{bid}/mulu_{N}.html) 收集, 逐页 fetch。
  - 正文: 通用正则提取任意 对象.方法 的 BASE64 段并解码 (段落为 <p> HTML)。

已探测边界 (2026-09-13 在线实测):
  - 目录分页: /book/{bookid}/mulu_{N}.html, N=1..25 (每页100章, select option 列出)
  - 章内分页: {cid}.html → {cid}_1.html (第2页起); 不存在的分页返回**第1页**内容,
    靠主循环"与上一页指纹相同则终止"即可收尾, 无需特判。
"""
import base64
import re

try:
    import 日志 as _app_log
    _log = _app_log.get('adapter.qiqishu')
except Exception:  # 独立环境无项目日志模块时退化为标准 logging
    import logging
    _log = logging.getLogger('adapter.qiqishu')

SITE = {
    "domain": "qiqishu.cc",
    "pattern": "html_selector",
    "chapter_url_regex": r"/read/\d+/\d+\.html",
    "content_selectors": ["#booktxt", "#content"],
    "anti_spider": {"type": "auto"},
}

# 章节链接 (目录页)
_章节RE = re.compile(r'^/read/\d+/\d+\.html$')
# 目录分页 /book/{bid}/mulu_{N}.html
_目录页RE = re.compile(r'^/book/\d+/mulu_\d+\.html$')
# 章内分页 /read/{bid}/{cid}_{N}.html
_分页RE = re.compile(r'^(/read/\d+/\d+)_\d+\.html$')
# document.writeln(对象.方法('BASE64')) — 对象名每页随机, 用通用形
_正文B64RE = re.compile(r"document\.writeln\(\s*[\w$.]+\(['\"]([^'\"]+)['\"]\)\s*\)")


def _章节排序键(chap):
    """按章节 URL 尾号排序 (目录页按章号正序, 跨分页抓取保证全局有序)"""
    m = re.search(r'/(\d+)\.html$', chap.get('url', ''))
    return int(m.group(1)) if m else 999999


def _章节标题(a):
    """章节名: <a rel="chapter"><dd>章节名</dd></a>, title 属性更干净"""
    return (a.get('title') or a.get_text(strip=True) or '').strip()


def parse_catalog(soup, catalog_url, base_url, **kw):
    """目录解析: 当前页章节 + select 收集全部分页逐页抓取

    Args:
        soup: 目录分页页 BeautifulSoup (主程序已抓取 mulu_1.html)
        catalog_url: 当前目录页 URL
        base_url: 站点根 URL
        kw: sort_chapters / fetch(抓取额外目录页的回调)
    Returns:
        list[dict] | None
    """
    sort_chapters = kw.get('sort_chapters', True)
    fetch = kw.get('fetch')
    book_m = re.search(r'/book/(\d+)/', catalog_url)
    if not book_m:
        _log.info("[qiqishu] 无法从目录URL提取小说ID, 回退通用解析")
        return None
    book_id = book_m.group(1)
    _log.info(f"[qiqishu] 小说ID: {book_id}")

    # 收集全部分页 (select option 值, 含当前页)
    page_urls = []
    if soup is not None:
        for opt in soup.select('select option[value]'):
            v = opt.get('value', '').strip()
            if v.startswith(f'/book/{book_id}/mulu_') and v.endswith('.html') \
                    and v not in page_urls:
                page_urls.append(v)
    if not page_urls:
        _log.info("[qiqishu] 未找到目录分页 option, 仅解析当前页")
        page_urls = [catalog_url]  # 兜底: 当前 URL 本身可能是 mulu 页

    seen = set()
    chapters = []
    for i, rel in enumerate(page_urls):
        if i == 0:
            page_soup = soup
        else:
            page_url = rel if rel.startswith('http') else base_url + rel
            _log.info(f"[qiqishu] 抓取目录第{i+1}页: {page_url}")
            page_soup = fetch(page_url) if fetch else None
        if page_soup is None:
            continue
        found = 0
        for a in page_soup.find_all('a', href=True):
            href = (a.get('href') or '').strip()
            if not _章节RE.match(href):
                continue
            # 保持与通用过滤器一致: 只认 rel="chapter" 的章节链接,
            # 排除无 rel 的导航/推荐链接 (如"马上阅读"指向 read/ 的入口)
            if 'chapter' not in (a.get('rel') or []):
                continue
            title = _章节标题(a)
            if not title or href in seen:
                continue
            seen.add(href)
            url = href if href.startswith('http') else base_url + href
            chapters.append({'title': title, 'url': url})
            found += 1
        _log.info(f"[qiqishu] 第{i+1}页: 新增 {found} 章, 累计 {len(chapters)} 章")

    if sort_chapters and chapters:
        chapters.sort(key=_章节排序键)
    for i, chap in enumerate(chapters[:5]):
        _log.info(f"  {i+1}. {chap['title'][:40]} -> {chap['url']}")
    if len(chapters) > 5:
        _log.info(f"  ... 共 {len(chapters)} 章")
    return chapters


def _解码正文(script_html):
    """从包含 document.writeln(对象.方法('BASE64')) 的 HTML 解码出纯文本正文

    Returns:
        str: 段落式文本 (\n\n 分隔); 无效时返回 ''
    """
    chunks = _正文B64RE.findall(script_html)
    if not chunks:
        return ''
    parts = []
    for b64 in chunks:
        try:
            raw = base64.b64decode(b64, validate=False).decode('utf-8', errors='replace')
        except Exception as e:
            _log.debug(f'裸 except 吞异常: {type(e).__name__} (b64 解码失败)')
            continue
        # 段落 HTML → 文本
        raw = re.sub(r'<br\s*/?>', '\n', raw)
        raw = re.sub(r'</p>', '\n\n', raw)
        raw = re.sub(r'<[^>]+>', '', raw)
        from html import unescape
        txt = unescape(raw).strip()
        if txt:
            parts.append(txt)
    return '\n\n'.join(parts)


def extract_content(soup, page_url, base_url, **kw):
    """正文提取: #booktxt 下的 document.writeln BASE64 段

    回退: BASE64 正则未命中时取 #booktxt 明文 (站点改版兼容)。
    """
    if soup is None:
        return None
    # 优先 #booktxt, 再 #content (构造样本/换版兼容)
    for sel in ('#booktxt', '#content'):
        el = soup.select_one(sel)
        if el is None:
            continue
        text = _解码正文(str(el))
        if text:
            _log.info(f"[qiqishu] {sel} BASE64 解码 {len(text)} 字符")
            return text
        # 明文回退
        plain = el.get_text('\n', strip=True)
        if plain:
            _log.info(f"[qiqishu] {sel} 明文回退 {len(plain)} 字符")
            return plain
    _log.info("[qiqishu] 未找到正文容器")
    return None


def paginate(current_url, page_index, **kw):
    """章内分页: {cid}.html → {cid}_1.html (第2页起)"""
    m = _分页RE.match(current_url)
    if m:
        # 已是分页 URL, 回退到基础 URL 保证页码递增正确
        base = m.group(1)
    else:
        base = current_url.replace('.html', '') if '.html' in current_url else current_url
    if 'read/' not in base and 'read/' not in current_url:
        return None
    b = re.sub(r'_\d+$', '', base)
    return f"{b}_{page_index}.html"


def catalog_from_chapter(chapter_url, base_url=None):
    """章节页 /read/{bid}/{cid}.html → 目录页 /book/{bid}/mulu_1.html"""
    m = re.search(r'/read/(\d+)/\d+(?:_\d+)?\.html$', (chapter_url or '').strip())
    if not m:
        return None
    host = re.match(r'^https?://[^/]+', (base_url or chapter_url))
    if not host:
        return None
    return f"{host.group(0)}/book/{m.group(1)}/mulu_1.html"


def get_title(soup, catalog_url, base_url):
    """书名: 目录页 <title> 形如 '深空彼岸最新章节_辰东_深空彼岸免费阅读_深空彼岸_奇书网'

    优先 og:novel:book_name meta; 失败取 title 首段。
    """
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