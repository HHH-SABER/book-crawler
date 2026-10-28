# -*- coding: utf-8 -*-
"""章节正文分页：页数上限与"下一页 URL"的计算（Wave2 拆分第一块，2026-10-24）。

从 `爬虫.py::get_chapter_content()` 里原样搬出，**行为逐字保留**（含日志与停止条件）。
抽出动机：这段是"循环里最内层的分支树"（适配器分页 / sites_config 分页 / `.html` 次序替换），
且带着 K35 那类"适配器声明单页直出"的微妙语义 —— 放在 6000 行大函数里没人敢动，
抽成纯函数后可以离线单测。

设计约束（与调用方约定）
------------------------
- 只做**纯计算**：不读实例状态、不发请求；`base_url` / `适配器策略` 由调用方注入；
- 返回 `None` 表示**停止翻页**（不是错误）；停止原因通过 `_log` 留痕，与拆分前一致；
- `适配器策略` 传入 `None` 时退化为"无站点钩子"（便于单测）。
"""
import logging

_log = logging.getLogger('小说爬虫')


def 分页上限(site_pattern, chapter_url, 适配器策略=None, max_pages=None) -> int:
    """计算本次章节最多抓几页。

    优先级（与 `get_chapter_content` 原实现一致）：
    1. 适配器 `content_pagination.max_pages`（**必须是 dict**；None = 单页直出，见 K35）；
    2. 站点策略阶段 `'分页上限'` 返回 int 时采用，否则默认 20；
    3. 调用方显式 `max_pages` 只能**收紧**，不能放宽。
    """
    if site_pattern and isinstance(site_pattern.get('content_pagination'), dict):
        上限 = site_pattern['content_pagination'].get('max_pages', 30)
    else:
        候选 = 适配器策略(chapter_url, '分页上限') if 适配器策略 else None
        上限 = 候选 if isinstance(候选, int) else 20
    if max_pages is not None:
        return min(max_pages, 上限)
    return 上限


def 下一页URL(chapter_url, page_index, site_pattern, base_url, 适配器策略=None,
             当前URL=None):
    """第 `page_index` 页（从 0 计）的 URL；返回 None 表示**停止翻页**。

    `当前URL` = 循环里上一页的 URL（适配器 paginate 需要它做相对推进）；
    省略时退回 `chapter_url`（单页/首页语义）。

    分支顺序与原实现一致：
    1. 外部适配器插件 `paginate`（站点适配/，优先；异常或返回 None 即停）；
    2. sites_config 的 `content_pagination`（`build_paged_url`；None 配置=单页直出）；
    3. URL 含 `.html` ⇒ 站点策略阶段 `'分页URL'`，否则 `.html` → `_{页码}.html`；
    4. 其它形态 ⇒ 停止。
    """
    # ---- ① 外部适配器插件的 paginate ----
    适配器 = None
    try:
        from sites_config import get_adapter
        适配器 = get_adapter(chapter_url)
    except Exception as _e:      # noqa: BLE001 — 适配器不可用不该拖垮抓取
        _log.debug(f'[分页] 取适配器失败, 按无适配器处理: {type(_e).__name__}: {_e}')
    if 适配器 and 适配器.get('paginate'):
        try:
            # 注意: 适配器拿的是**上一页 URL**（原实现传 current_url），不是章节首页
            源URL = 当前URL or chapter_url
            from sites_config import 调适配器接口
            next_url = 调适配器接口('paginate', 源URL, 适配器,
                                源URL, page_index, base_url=base_url)
        except Exception as e:      # noqa: BLE001 — 插件缺陷降级到内置规则
            _log.info(f"[分页] 适配器分页异常, 回退内置规则: {e}")
            next_url = None
        if next_url:
            return next_url if next_url.startswith('http') else base_url.rstrip('/') + next_url
        _log.info("[分页] 适配器返回 None, 停止")
        return None

    # ---- ② sites_config 的 content_pagination ----
    if site_pattern and 'content_pagination' in site_pattern:
        if not isinstance(site_pattern['content_pagination'], dict):
            _log.info("[分页] 站点配置声明单页直出 (content_pagination=None), 停止")
            return None
        from sites_config import build_paged_url
        页 = build_paged_url(chapter_url, page_index, site_pattern['content_pagination'])
        if 页 is None:
            _log.info("[分页] 已达到最大页数限制，停止")
        return 页

    # ---- ③ .html 次序替换（站点策略阶段 '分页URL' 可接管）----
    if '.html' in chapter_url:
        候选 = 适配器策略(chapter_url, '分页URL', page_index=page_index) if 适配器策略 else None
        return 候选 if 候选 else chapter_url.replace('.html', f'_{page_index}.html')

    # ---- ④ 其它形态（无 .html 且无规则）⇒ 停 ----
    return None
