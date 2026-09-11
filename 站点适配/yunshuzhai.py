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
    'content_selectors': ['#novel-content', '.novel-content'],
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


def extract_content(soup, page_url, base_url, **kw):
    """正文提取: Tailwind 布局, 正文容器 #novel-content (2026-09-11 实测
    单页章节 ~5300 字纯文本, 无章节内分页)。"""
    if soup is None:
        return None
    for sel in ('#novel-content', '.novel-content', 'div#content'):
        el = soup.select_one(sel)
        if el is not None:
            text = el.get_text('\n', strip=True)
            if text:
                return text
    return None


def get_title(soup, catalog_url, base_url):
    """书名: 目录页 <title> 形如
    '我的美母教师最新章节_wdw5201314著_全文免费阅读 - 云书斋'"""
    if soup is None or not soup.title or not soup.title.string:
        return None
    t = soup.title.string.split('_')[0].strip()
    for 词 in ('最新章节', '全文阅读', '全文免费阅读'):
        t = t.replace(词, '')
    t = t.strip(' -_')
    return t or None
