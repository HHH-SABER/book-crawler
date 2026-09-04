# -*- coding: utf-8 -*-
"""单页全章小说适配器 (示例: victor-w-ma.github.io 黑爹麦克的黄皮绿奴)

结构: 一个 HTML 页面包含整本书, 每个章节是一个带 id 锚点的 <h1>,
      <h1> 与正文 <p> 为同级兄弟节点, 位于 <div class="post-content e-content"> 内。
- 目录解析: 收集所有带 id 的 <h1> → 章节 url = 页面 url + #锚点
- 正文提取: 按 #锚点 定位 <h1>, 取其到下一个 <h1> 之间的段落
- 分页: 单页无分页
"""

import re
from urllib.parse import quote, unquote

try:
    import 日志 as _app_log
    _log = _app_log.get('adapter.single_page')
except Exception:
    import logging
    _log = logging.getLogger('adapter.single_page')

SITE = {
    "domain": "victor-w-ma.github.io",
    "pattern": "html_selector",
    "chapter_url_regex": r"/\d{4}/\d{2}/\d{2}/[a-z0-9-]+\.html(?:#[^\"']*)?$",
    "content_selectors": [".post-content", "div.post-content", ".e-content"],
    "anti_spider": {"type": "auto"},
}


def parse_catalog(soup, catalog_url, base_url, **kw):
    """目录解析: 页面内带 id 的 <h1> 即章节 (书名 h1 无 id, 自动排除)"""
    chapters = []
    base = (catalog_url or '').split('#')[0]
    for h in soup.find_all('h1', id=True):
        title = h.get_text(strip=True)
        if not title:
            continue
        # 锚点含中文, 必须 URL 编码, 否则 requests 报 latin-1 codec 错误
        frag = quote(h.get('id'), safe='-')
        chapters.append({'title': title, 'url': base + '#' + frag})
    _log.info(f"[单页小说] 目录解析完成: {len(chapters)} 章, 页面={base}")
    for i, chap in enumerate(chapters[:5]):
        _log.info(f"  {i+1}. {chap['title']} -> {chap['url']}")
    if len(chapters) > 5:
        _log.info(f"  ... 共 {len(chapters)} 章")
    return chapters


def extract_content(soup, page_url, base_url, **kw):
    """正文提取: 按 #锚点 定位 <h1>, 取其到下一个 <h1> 之前的段落"""
    frag = ''
    if '#' in page_url:
        frag = page_url.split('#', 1)[1]
    if not frag:
        _log.info("[单页小说] URL 无锚点, 跳过")
        return None
    frag = unquote(frag)  # 目录解析时做了 URL 编码, 此处还原
    h = soup.find('h1', id=frag) if soup is not None else None
    if h is None:
        _log.info(f"[单页小说] 未找到锚点章节: {frag}")
        return None
    parts = []
    for node in h.find_next_siblings():
        if getattr(node, 'name', None) == 'h1':
            break
        if getattr(node, 'name', None) in ('p', 'div', 'blockquote'):
            txt = node.get_text(separator='\n', strip=True)
            if txt:
                parts.append(txt)
    text = '\n\n'.join(parts)
    _log.info(f"[单页小说] 提取章节 '{frag}': {len(text)} 字符")
    return text


def paginate(current_url, page_index, **kw):
    """单页无分页"""
    return None
