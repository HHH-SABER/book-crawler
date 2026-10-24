# -*- coding: utf-8 -*-
"""章节正文提取：外部适配器插件钩子的调用封装（Wave2 第三块，2026-10-24）。

`爬虫.py::get_chapter_content` 里"先用适配器 `extract_content` 抽正文"这段，
原先和页面抓取、清洗、合并、指纹判重混在一个循环里。本模块只负责**调用与降级**：

- 取适配器失败 / 无 `extract_content` 钩子 ⇒ 返回 None（交回后续内置提取链）；
- 钩子抛异常 ⇒ 记 INFO 日志并返回 None（与原实现一致，**不是**静默吞）；
- 页面本身通过 `取页面` 回调注入 —— 既保留 `self.inspect_page` 的会话能力，
  又让本函数可离线单测。

清洗、指纹判重、合并与翻页控制仍留在 `爬虫.py`（编排与实例状态不该搬）。
"""
import logging

_log = logging.getLogger('小说爬虫')


def 用适配器提取(current_url, page_index, base_url, 取页面):
    """调外部适配器的 `extract_content` 钩子抽一页正文。

    Args:
        current_url: 当前页 URL（适配器按域名匹配，也参与钩子计算）
        page_index: 页码（从 0 计）
        base_url: 站点基址（相对链接由钩子自行处理）
        取页面: 无参回调，返回 BeautifulSoup；由调用方注入（`self.inspect_page`）

    Returns:
        str 正文（可能为空串）；未命中钩子或异常时为 None。
    """
    try:
        from sites_config import get_adapter
        适配器 = get_adapter(current_url)
    except Exception as _e:      # noqa: BLE001 — 适配器注册表异常不该拖垮抓取
        _log.debug(f'[适配器] 取适配器失败, 跳过插件提取: {type(_e).__name__}: {_e}')
        适配器 = None
    if not (适配器 and 适配器.get('extract_content')):
        return None
    try:
        _log.info(f"[适配器] {适配器['source']} 自定义正文提取 (第{page_index+1}页)")
        soup = 取页面()
        return 适配器['extract_content'](soup, current_url, base_url, page_index=page_index)
    except Exception as e:      # noqa: BLE001 — 插件缺陷降级到内置提取链
        _log.info(f"[适配器] 正文提取异常, 回退通用流程: {e}")
        return None
