# -*- coding: utf-8 -*-
"""云书斋 (yunshuzhai.com) 站点适配器。

背景: 目录页 /book/{id}/ 为 Tailwind 布局, 通用选择器只取到 5 个链接且多为
导航 (开始阅读/最新章节/上一章/下一章), 经导航过滤后仅剩 1 章 (2026-09-10
用户实测 "我的美母教师" 只抓到 1 章)。真实章节链接模式: /book/{id}/{n}.html

契约见 文档/SITE_ADAPTER.md: SITE dict + parse_catalog(soup, catalog_url,
base_url, **kw) -> [{'title','url'}] | None
"""
import re

SITE = {
    'domain': 'yunshuzhai.com',
    'pattern': 'html_selector',
}

_章节链接RE = re.compile(r'/book/\d+/\d+\.html$')
_导航词 = ('开始阅读', '最新章节', '上一章', '下一章', '目录', '加入书架',
           '投推荐票', '章节列表', '查看更多')


def parse_catalog(soup, catalog_url, base_url, **kw):
    """从目录页提取章节列表 (按 URL 去重, 过滤导航/超长文案链接)。"""
    links = []
    seen = set()
    for a in soup.select('a[href]'):
        href = (a.get('href') or '').strip()
        if not _章节链接RE.search(href):
            continue
        title = a.get_text(strip=True)
        if not title or len(title) > 40:
            continue
        if any(w in title for w in _导航词):
            continue
        url = href if href.startswith('http') else \
            base_url.rstrip('/') + ('' if href.startswith('/') else '/') + href
        if url in seen:
            continue
        seen.add(url)
        links.append({'title': title, 'url': url})
    return links or None
