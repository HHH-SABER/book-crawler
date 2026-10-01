# -*- coding: utf-8 -*-
"""站点适配器模板 (SITE 契约参考实现, 占位域 example.com)

本文件是「站点脱钩机制」的公开侧契约模板:
  - 文件名以 _ 开头 → sites_config.load_adapters 自动跳过, 不会被加载执行
  - 真实适配器放 站点适配_本地/ (不入库, 见 AGENTS §目录与文件管理规范 四),
    一个站点一个 .py, 按 契约字段 实现即可, 无需改动主爬虫代码

复制本文件为 站点适配_本地/你的站点.py 并替换占位内容即可接入新站点。
安全提示: 适配器 .py 会被 import 执行, 等同直接运行代码, 只放可信来源的文件。

========== SITE 契约 (可选导出, 每个适配器文件可暴露) ==========

SITE (dict, 可选): 站点配置, 字段同 站点配置.json
    domain / pattern / catalog_parser / chapter_url_regex /
    content_pagination / content_selectors / content_extractor / anti_spider
    按域名 upsert 进 SITE_PATTERNS (仅内存, 不写 站点配置.json)。

parse_catalog(soup, catalog_url, base_url, **kw) -> list[dict] | None
    目录页解析。返回 [{'title':..., 'url':...}]; 返回 None 表示走通用/内置解析。
    kw 提供 sort_chapters / fetch (抓取额外目录页的回调)。

extract_content(soup, page_url, base_url, **kw) -> str | None
    正文提取。返回正文字符串; 返回 None 表示走通用/内置提取。
    kw 提供 page_index。

paginate(current_url, page_index, **kw) -> str | None
    返回下一页 URL (相对路径自动补全); 返回 None 表示停止分页。

get_title(soup, page_url, base_url, **kw) -> str | None
    从目录/详情页提取书名 (可选)。

catalog_from_chapter(chapter_url, base_url=None) -> str | None
    章节页 URL → 目录页 URL 的纯字符串推导 (不发请求); 返回 None 表示
    无法推导。供通用层在目录解析前把误当任务 URL 的章节页规范化到目录页。
=================================================================
"""

SITE = {
    'domain': 'example.com',
    'pattern': 'html_selector',
    'catalog_parser': 'generic',
    'chapter_url_regex': r'/book/(\d+)/(\d+)\.html',
    'content_pagination': {'suffix': '_{N}.html', 'start': 1, 'max_pages': 30},
    'content_selectors': ['#content', '.content'],
    'anti_spider': {'type': 'auto'},
}


def parse_catalog(soup, catalog_url, base_url, **kw):
    """目录解析 (示例: 收集 #list 下章节链接) — 按目标站点结构改写"""
    chapters = []
    for a in soup.select('#list a[href]'):
        title = a.get_text(strip=True)
        href = a.get('href', '')
        if title and href:
            chapters.append({'title': title, 'url': href})
    return chapters or None


def extract_content(soup, page_url, base_url, **kw):
    """正文提取 (示例: 取 #content 全文) — 按目标站点结构改写"""
    el = soup.select_one('#content')
    return el.get_text('\n', strip=True) if el else None


def paginate(current_url, page_index, **kw):
    """章节内分页 (示例: _{N}.html 后缀) — 按目标站点规则改写"""
    if page_index <= 0:
        return None
    return current_url.replace('.html', f'_{page_index}.html')
