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

from 章节数据文件 import 页指纹  # 纯函数, 无循环依赖

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


def 该用站点提取器(site_pattern):
    """站点配置是否走「专属提取器」路径：pattern=html_selector 且提取器**已注册**。

    注册表在 gitignored 的 `站点适配_本地/_提取器.py`；公开形态未注册 ⇒ False，
    保持原通用提取路径（避免行为退化）。站点名经 `解析提取器名` 归一为机制名。
    """
    try:
        from sites_config import PATTERN_HTML_SELECTOR, 解析提取器名, 提取器已注册
    except ImportError:
        return False
    if not site_pattern or site_pattern.get('pattern') != PATTERN_HTML_SELECTOR:
        return False
    try:
        return bool(提取器已注册(解析提取器名(site_pattern.get('content_extractor') or '')))
    except Exception as _e:      # noqa: BLE001 — 注册表异常按"不可用"处理
        _log.debug(f'[sites_config] 提取器注册判定失败: {type(_e).__name__}: {_e}')
        return False


def 用站点提取器(session, current_url, site_pattern, base_url, headers, 取JS页面):
    """调 `sites_config.extract_content` 抽一页正文。

    Returns:
        (正文, 是否成功)；异常时返回 ('', False) 并留 INFO 日志（与原实现一致）。
    """
    try:
        from sites_config import extract_content
        return extract_content(session, current_url, site_pattern, base_url, headers, 取JS页面)
    except Exception as e:      # noqa: BLE001 — 站点配置缺陷降级到通用检测
        _log.info(f"[sites_config] 站点配置提取异常, 回退通用检测: {e}")
        return '', False


def 结算一页(page_text, 上一页指纹):
    """对"已清洗的一页正文"做合并前的结算：是否重复 + 新指纹 + 要追加的片段。

    原实现把这段在 `get_chapter_content` 里**重复写了 4 遍**（数据文件 / 适配器 /
    站点配置 / 通用检测四条路径各一份），且每份都夹着 `break` 与日志，无法单独验证。
    抽出后"重复判定口径"与"追加格式"只有一处定义。

    Args:
        page_text: 已清洗的正文
        上一页指纹: 上一页的复合指纹（`页指纹()` 的结果；首页传 None）

    Returns:
        (是否重复, 新指纹, 追加片段)
        - 重复: True, 上一页指纹（保持不变）, ''
        - 不重复: False, 本页指纹, `page_text + '\n\n'`
    """
    指纹 = 页指纹(page_text or '')
    if 指纹 == 上一页指纹:
        return True, 上一页指纹, ''
    return False, 指纹, (page_text or '') + '\n\n'
