# -*- coding: utf-8 -*-
"""书本网 (bookben5.org) 站点适配器。

问题背景 (2026-10-01 用户给的 10 站测试):
  - 目录页 /txt/{bid}.html 内含 **1,516 个 `/read/{bid}/{cid}.html` 章节链接**,
    但通用解析对该域**一条都识别不出** → 目录 0 章, 需专用适配器。

站点结构 (2026-10-01 在线实测 + 离线快照 `测试样本/bookben5_catalog.html`、
`bookben5_chapter_1.html`):
  - 目录: **单页, 无分页**(整页 `下一页`/`page=`/`rel=next` 计数均为 0) —— 与
    washai 的多页不同, 无需 fetch 翻页。
  - 章节链接: `/read/{bid}/{cid}.html`; 页面里另混有**导航链**:
    `开始阅读` 与 `下载TXT`(两者同一 URL), 以及顶部一条"最新章"链接
    (标题就是最新章节名, 与文末同名同 URL) → **靠 URL 去重 + 标题过滤** 处理。
  - **章号不可用于严格排序**: 1,516 条里有 4 个重复号(670/671/1354/1357)、
    2 个缺号(690/691), 且约 156 条是番外型标题("陈俊南（终）"/"宋明辉（终）")
    不含 "第N章" → 排序键 = (章号, 文档序), 番外排在末尾且保持原相对顺序。
  - 正文: `div.content` 内纯文本 `<p>`(实测 48 段); 同页 `footer` 另有 6 个
    `<p>` → **必须限定在 div.content 内**, 否则会把页脚吃进正文。
  - 章内分页: 无(`1/1`/`page` 计数均 0) → `paginate` 显式返回 None,
    避免通用规则对每章多发无效请求。
  - 书名: `<meta property="og:novel:book_name">` / `<h1>` / `<title>`
    形如 "十日终焉TXT全集下载,TXT电子书免费下载-书本网"。
  - 站点会把 `bookben5.org` 301 到 `www.bookben5.org`(域名匹配为**子串**,
    `SITE["domain"]` 填 `bookben5.org` 可同时命中带 www 的 URL)。
"""
import re

from bs4 import BeautifulSoup

try:
    import 日志 as _app_log
    _log = _app_log.get('adapter.bookben5')
except Exception:  # 独立环境无项目日志模块时退化为标准 logging
    import logging
    _log = logging.getLogger('adapter.bookben5')

SITE = {
    "domain": "bookben5.org",
    "pattern": "html_selector",
    "chapter_url_regex": r"/read/\d+/\d+\.html",
    "content_selectors": ["div.content", ".content"],
    "anti_spider": {"type": "auto"},
}

# 章节链接 /read/{bid}/{cid}.html
_章节RE = re.compile(r'^/read/(\d+)/(\d+)\.html$')
# 目录页 /txt/{bid}.html
_目录RE = re.compile(r'/txt/(\d+)(?:_\d+)?\.html$')
# 导航链标题(非章节), 实测出现: 开始阅读 / 下载TXT
_导航标题RE = re.compile(r'^(开始阅读|下载TXT|下载TXT全集|加入书架|章节目录|'
                         r'最新章节|手机阅读|投票推荐|返回目录|目录)$')
# 章节号(排序用)
_章号RE = re.compile(r'第\s*(\d+)\s*章')
# 正文尾部常见站内招呼语(稳妥剔除, 不影响正文)
_尾注RE = re.compile(r'^\s*(书本网|bookben5|本章完|未完待续|上一章|下一章|'
                     r'加入书签|推荐本书)[^\n]{0,40}$', re.I)


def _书ID(catalog_url):
    """从 /txt/{bid}.html 或 /read/{bid}/... 提取 book id; 失败 None"""
    u = (catalog_url or '').split('?')[0]
    m = _目录RE.search(u) or re.search(r'/read/(\d+)/', u)
    return m.group(1) if m else None


def _章节排序键(项):
    """(章号, 文档序): 无"第N章"的番外型标题排末尾, 且保持原相对顺序"""
    序, chap = 项
    m = _章号RE.search(chap.get('title', ''))
    return (int(m.group(1)) if m else 10 ** 9, 序)


def _自助抓取(url):
    """主程序交来的 soup 为空时, 由适配器自行抓一次目录页。

    为什么需要 (2026-10-01 实测根因):
      主程序 `inspect_page` 的请求头里**硬编码了 `Host: url.split('/')[2]`**;
      而本站会把 `bookben5.org` **301 跳转到 `www.bookben5.org`** → 带固定 Host 的
      请求被反复跳转 → requests 报 `Exceeded 30 redirects.` → 重试 3 次耗尽后
      **返回空 soup**(`爬虫.py` 的兜底分支) → 适配器收到空页面, 目录 0 章。
      该问题对**任何做 www/主机级跳转的站点**都成立, 属核心层隐患;
      此处仅做适配器自愈(不覆盖 Host 头 + 跟随跳转), 不修改核心。
    安全: 仍走 `validate_public_url` 校验(与主程序同一道 SSRF 防线)。
    """
    try:
        import requests
        from sites_config import validate_public_url
        validate_public_url(url)
        r = requests.get(url, timeout=20, allow_redirects=True, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/126.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        })
        r.encoding = r.apparent_encoding or 'utf-8'
        _log.info(f"[bookben5] 自主抓取 {r.status_code} {len(r.text):,d} 字符 (最终URL {r.url})")
        return BeautifulSoup(r.text, 'lxml')
    except Exception as e:
        _log.info(f"[bookben5] 自主抓取失败: {type(e).__name__}: {e}")
        return None


def parse_catalog(soup, catalog_url, base_url, **kw):
    """目录解析: 单页取全部 /read/{bid}/{cid}.html, 去重 + 过滤导航链

    Returns: list[dict] | None (拿不到 book id 或 0 章时 None, 回退通用解析)
    """
    sort_chapters = kw.get('sort_chapters', True)
    book_id = _书ID(catalog_url)
    if not book_id:
        _log.info(f"[bookben5] 无法从URL提取小说ID, 回退通用解析: {catalog_url}")
        return None

    # 主程序交来的页面为空(见 _自助抓取 的根因说明) → 自行抓一次
    # 开关: allow_self_fetch=False 时不做任何网络访问, 仅回退(离线测试用,
    # 保证单测不触网、结果确定)
    if soup is None or not soup.find('a'):
        if not kw.get('allow_self_fetch', True):
            _log.info("[bookben5] 页面为空且未允许自主抓取, 回退通用解析")
            return None
        _log.info("[bookben5] 主程序未提供有效页面, 尝试自主抓取目录页")
        soup = _自助抓取(catalog_url)
        if soup is None or not soup.find('a'):
            return None
    _log.info(f"[bookben5] 小说ID: {book_id}")

    本站RE = re.compile(rf'^/read/{book_id}/\d+\.html$')
    chapters, seen = [], set()
    for a in soup.find_all('a', href=True):
        href = (a.get('href') or '').strip().split('?')[0]
        if not 本站RE.match(href) or href in seen:
            continue
        title = (a.get('title') or a.get_text(strip=True) or '').strip()
        # 导航链过滤(开始阅读/下载TXT 与最新章链接同 URL 的情况由 seen 兜住)
        if not title or _导航标题RE.match(title):
            continue
        seen.add(href)
        url = href if href.startswith('http') else base_url.rstrip('/') + href
        chapters.append({'title': title, 'url': url})

    if sort_chapters and chapters:
        chapters = [c for _, c in sorted(enumerate(chapters), key=_章节排序键)]
    _log.info(f"[bookben5] 共提取 {len(chapters)} 个章节 (单页, 无分页)")
    for i, chap in enumerate(chapters[:3]):
        _log.info(f"  {i + 1}. {chap['title'][:40]} -> {chap['url']}")
    if len(chapters) > 3:
        _log.info(f"  ... 末章: {chapters[-1]['title'][:40]} -> {chapters[-1]['url']}")
    return chapters or None


def extract_content(soup, page_url, base_url, **kw):
    """正文提取: div.content 内 <p> 段落

    **必须限定容器**: 本页 footer 另有 6 个 <p>(站内链接), 取全文 <p> 会污染正文。
    选择器均落空时返回 None 走通用提取。
    """
    if soup is None:
        return None
    for sel in ('div.content', '.content'):
        el = soup.select_one(sel)
        if el is None:
            continue
        parts = []
        for p in el.find_all('p'):
            t = p.get_text(strip=True)
            if not t or _尾注RE.match(t):
                continue
            parts.append(t)
        if parts:
            text = '\n\n'.join(parts)
            _log.info(f"[bookben5] {sel} 提取 {len(parts)} 段, {len(text)} 字符")
            return text
        t = el.get_text('\n', strip=True)
        if t:
            _log.info(f"[bookben5] {sel} 明文回退 {len(t)} 字符")
            return t
    _log.info("[bookben5] 未找到正文容器")
    return None


def paginate(current_url, page_index, **kw):
    """章内分页: 无 (单页直出). 显式 None 让主循环第一页后干净停止。"""
    return None


def catalog_from_chapter(chapter_url, base_url=None):
    """/read/{bid}/{cid}.html → 目录页 {host}/txt/{bid}.html"""
    m = re.match(r'^https?://[^/]+/read/(\d+)/\d+\.html', (chapter_url or '').strip())
    if not m:
        return None
    host = re.match(r'^https?://[^/]+', (base_url or chapter_url))
    if not host:
        return None
    return f"{host.group(0)}/txt/{m.group(1)}.html"


def get_title(soup, catalog_url, base_url):
    """书名: og:novel:book_name → <h1> → <title> 首段"""
    if soup is not None:
        meta = soup.select_one('meta[property="og:novel:book_name"]')
        if meta and meta.get('content'):
            return meta['content'].strip()
        h1 = soup.find('h1')
        if h1 and h1.get_text(strip=True):
            return h1.get_text(strip=True)[:60]
        if soup.title and soup.title.string:
            m = re.match(r'^([^,，\-_|]+)', soup.title.string.strip())
            if m:
                return m.group(1).strip()
    return None
