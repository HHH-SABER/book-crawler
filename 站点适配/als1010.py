# -*- coding: utf-8 -*-
"""爱丽丝书屋 (als1010.space) 站点适配器

- 目录页: /other/chapters/id/{bookid}.html (单页含全部章节)
- 章节链接: /book/{bookid}/{hash}.html (hash 为 16 进制字符串)
- 正文: <div class="read-content j_readContent user_ad_content"> 内 <p> 段落 (纯 HTML, 无加密)
"""

import re

try:
    import 日志 as _app_log
    _log = _app_log.get('adapter.als1010')
except Exception:
    import logging
    _log = logging.getLogger('adapter.als1010')

SITE = {
    "domain": "als1010.space",
    "pattern": "html_selector",
    "chapter_url_regex": r"/book/\d+/[0-9a-f]+\.html",
    "content_selectors": [".read-content", "div.read-content", ".j_readContent"],
    "anti_spider": {"type": "auto"},
}


def _sort_key(chap):
    """章节排序: 序号在前, 番外/外传最后"""
    title = chap.get('title', '')
    if '番外' in title or '外传' in title:
        return (99999, title)
    m = re.match(r'^\s*(\d+)', title)
    if m:
        return (int(m.group(1)), title)
    return (100000, title)


def parse_catalog(soup, catalog_url, base_url, **kw):
    """目录解析: 收集 /book/{bookid}/{hash}.html 章节链接"""
    chapters = []
    seen = set()
    for a in soup.find_all('a', href=True):
        href = a.get('href', '')
        if not re.fullmatch(r'/book/\d+/[0-9a-f]+\.html', href):
            continue
        if href in seen:
            continue
        title = a.get_text(strip=True)
        if not title:
            continue
        seen.add(href)
        url = href if href.startswith('http') else base_url + href
        chapters.append({'title': title, 'url': url})
    if kw.get('sort_chapters', True):
        chapters.sort(key=_sort_key)
    for i, chap in enumerate(chapters[:5]):
        _log.info(f"  {i+1}. {chap['title']} -> {chap['url']}")
    if len(chapters) > 5:
        _log.info(f"  ... 共 {len(chapters)} 章")
    return chapters


def extract_content(soup, page_url, base_url, **kw):
    """正文提取: 兼容 PC(桌面) 与 移动端 两套布局

    - PC:  <div class="read-content j_readContent user_ad_content"> 内 <p>
    - 移动: <div class="read-article" id="chapterContent"> 内 <p class="content_txt">
    优先取 <p> 文本最长的候选容器。
    """
    if soup is None:
        return None
    # WAF 验证码拦截页检测: 章节页被"访问验证"图片验证码拦截时, 提示清晰原因
    try:
        page_text = soup.get_text(' ', strip=True)[:200] if hasattr(soup, 'get_text') else ''
        if '访问验证' in page_text or (soup.title and '访问验证' in soup.title.get_text(strip=True)):
            _log.info("[als1010] ⚠️ 章节页被 WAF 验证码拦截 (访问验证/check_code), "
                      "请求被反爬拦截, 无法自动获取正文; 请稍后重试或降低并发")
            return None
    except Exception:
        pass
    selectors = [
        '.read-content',            # PC 单容器
        'div#chapterContent',       # 移动 总容器
        '.content_txt',             # 移动 每段一容器 (需收集全部)
        '#j_chapterBox',
        '.text-wrap',
    ]
    best_text, best_n = '', 0
    for sel in selectors:
        parts = []
        for el in soup.select(sel):
            ps = el.find_all('p')
            if ps:
                parts.extend(p.get_text(strip=True) for p in ps
                             if p.get_text(strip=True))
            else:
                t = el.get_text(strip=True)
                if t:
                    parts.append(t)
        text = '\n\n'.join(parts)
        if len(text) > len(best_text):
            best_text, best_n = text, len(parts)
    if best_text:
        _log.info(f"[als1010] 提取 {best_n} 段, {len(best_text)} 字符")
        return best_text
    _log.info("[als1010] 未找到正文容器")
    return None


def get_title(soup, catalog_url, base_url):
    """书名: 目录页 <title> 形如 '章节列表-淫乱家族-乱伦-爱丽丝书屋...'

    通用逻辑按第一个 '-' 截断会取到 '章节列表' (页面类型标签) 而非书名。
    改为优先取面包屑中指向 /novel/{id}.html 的链接文本 (= 书名);
    失败则从 <title> 分隔段中挑不含站点关键词的段。
    """
    if soup is not None:
        # 1) 面包屑/详情链接: /novel/{id}.html 的文本即书名
        for a in soup.find_all('a', href=True):
            href = a.get('href', '')
            if re.fullmatch(r'/novel/\d+\.html', href):
                t = a.get_text(strip=True)
                if t:
                    return t
    # 2) <title> 取非站点关键词的一段
    if soup is not None and soup.title and soup.title.string:
        parts = [p.strip() for p in re.split(r'[-_—|]', soup.title.string) if p.strip()]
        for p in parts[1:]:
            if len(p) >= 2 and not any(k in p for k in ('书屋', '章节', '小说', '列表', '爱丽丝', 'ALICE')):
                return p
    return None


def paginate(current_url, page_index, **kw):
    """单页正文, 不分页"""
    return None
