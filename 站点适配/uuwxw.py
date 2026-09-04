# -*- coding: utf-8 -*-
"""悠悠书城 (uuwxw.cc) 站点适配器 —— 外部插件示例。

把本文件放进程序目录下的 `站点适配/` 文件夹 (与 EXE 同目录) 即自动生效，
无需重新打包。以后遇到结构类似的新站，复制本文件改改 SITE 和 parse_catalog 即可。

适配器文件可暴露 (均可选):
  - SITE (dict)            站点配置，字段同 站点配置.json
  - parse_catalog(...)     自定义目录解析，返回章节列表或 None
  - extract_content(...)   自定义正文提取，返回正文或 None
  - paginate(...)          自定义分页，返回下一页 URL 或 None

安全: 本文件会被 import 执行，请只放入可信来源的适配器。
"""

import re

try:
    import 日志 as _app_log
    _log = _app_log.get('adapter.uuwxw')
except Exception:  # 独立环境无项目日志模块时退化为标准 logging
    import logging
    _log = logging.getLogger('adapter.uuwxw')

SITE = {
    "domain": "uuwxw.cc",
    "pattern": "qsbs_bb",          # 正文用 document.writeln(akxa('BASE64')) 加密
    "catalog_parser": "uuwxw",     # 语义化标识 (站点管理页显示用)
    "chapter_url_regex": "/book/[a-z0-9]+/[a-z0-9]+\\.html",
    "content_pagination": {
        "suffix": "_{N}.html",     # 第2页 = {cid}_1.html
        "start": 1,
        "max_pages": 30,
    },
    "content_selectors": ["#content", "#booktxt", ".content"],
    "anti_spider": {"type": "auto"},
}


def _chapter_sort_key(chap):
    """统一章节排序键: 章节号 → 楔子 → URL数字 → 番外 (与主程序一致)"""
    title = chap.get('title', '')
    url = chap.get('url', '')
    if '楔子' in title:
        return 0
    m = re.search(r'第(\d+)', title)
    if m:
        return int(m.group(1))
    m2 = re.search(r'/(\d+)\.html', url)
    if m2:
        return int(m2.group(1))
    if '番外' in title:
        return 99999
    return 9999


def parse_catalog(soup, catalog_url, base_url, **kw):
    """悠悠书城 (uuwxw.cc) 目录解析。

    目录页 /book/{bid}/list{N}.html, 每页 100 章。章节链接藏在 <div id="list"><dl> 下:
        <a href="/book/{bid}/{cid}.html" rel="chapter"><dd>第N章...</dd></a>
    注意 <dd> 在 <a> 内部, 直接取 a 的文本即章节名。
    目录分页: 从 <select> 的 option 值 (/book/{bid}/list{N}.html) 收集全部页码,
    无 select 时回退为仅当前页。

    Args:
        soup: 目录页 BeautifulSoup (主程序已抓取)
        catalog_url: 目录页 URL
        base_url: 站点根 URL
        kw: sort_chapters(是否按章节号排序) / fetch(抓取额外目录页的回调)
    Returns:
        list[dict] | None
    """
    sort_chapters = kw.get('sort_chapters', True)
    fetch = kw.get('fetch')  # 抓取额外目录页的回调 (无则跳过翻页)

    chapters = []
    _log.info("检测到uuwxw.cc网站，使用专用目录解析")
    path_m = re.search(r'(/book/[a-z0-9]+/)', catalog_url)
    if not path_m:
        _log.info("[uuwxw] 无法从URL提取书路径")
        return chapters
    book_prefix = path_m.group(1)
    _log.info(f"[uuwxw] 书路径前缀: {book_prefix}")

    # 收集全部目录页码 (select 的 option, 如 list1.html 第1-100章 / list2.html ...)
    page_urls = []
    if soup is not None:
        for opt in soup.select('select option[value]'):
            v = opt.get('value', '')
            if re.fullmatch(rf'{re.escape(book_prefix)}list\d+\.html', v) and v not in page_urls:
                page_urls.append(v)
    if not page_urls:
        # 兜底: 仅当前目录页
        if catalog_url.startswith(base_url):
            page_urls = [catalog_url[len(base_url):]]
        else:
            page_urls = [catalog_url]
    _log.info(f"[uuwxw] 目录页数: {len(page_urls)}")

    seen = set()
    for i, rel in enumerate(page_urls):
        if i == 0:
            page_soup = soup
        else:
            page_url = base_url + rel
            _log.info(f"[uuwxw] 抓取目录第{i+1}页: {page_url}")
            page_soup = fetch(page_url) if fetch else None
        if page_soup is None:
            continue
        found = 0
        for a in page_soup.find_all('a', href=True):
            rels = a.get('rel') or []
            if 'chapter' not in rels:
                continue
            href = a.get('href', '')
            if not (href.startswith(book_prefix) and href.endswith('.html')):
                continue
            if re.search(r'list\d+\.html$', href):
                continue  # 目录分页链接
            if href in seen:
                continue
            title = a.get_text(strip=True)
            if not title:
                continue
            seen.add(href)
            url = href if href.startswith('http') else base_url + href
            chapters.append({'title': title.strip(), 'url': url})
            found += 1
        _log.info(f"[uuwxw] 第{i+1}页: 新增 {found} 章, 累计 {len(chapters)} 章")

    if sort_chapters and chapters:
        chapters.sort(key=_chapter_sort_key)
    for i, chap in enumerate(chapters[:5]):
        _log.info(f"  {i+1}. {chap['title']} -> {chap['url']}")
    if len(chapters) > 5:
        _log.info(f"  ... 共 {len(chapters)} 章")
    return chapters
