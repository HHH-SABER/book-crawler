# -*- coding: utf-8 -*-
"""历史页数据源：爬取历史 + 站点历史的查询封装 (GUI 与底层模块解耦)

读取失败/模块不可用时降级为空数据, 页面仍可渲染。
"""
import os
import sys

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    from 爬取历史 import 取爬取历史, RESULT_NEW, RESULT_UPDATE, \
        RESULT_UNCHANGED, RESULT_FAIL
    _历史可用 = True
except Exception:
    _历史可用 = False

try:
    from 站点历史 import 取站点历史
    _站点历史可用 = True
except Exception:
    _站点历史可用 = False


def is_available() -> bool:
    """爬取历史模块是否可用"""
    return _历史可用


def get_result_types() -> list:
    """四种结果类型 (常量)"""
    return [RESULT_NEW, RESULT_UPDATE, RESULT_UNCHANGED, RESULT_FAIL] \
        if _历史可用 else ['新增', '更新', '未变化', '失败']


def query_history(域名=None, 起始时间=None, 结束时间=None, 结果=None) -> list:
    """查询 URL 级历史记录 [{域名, url, 最后抓取, 状态码, 耗时秒, 字节大小, 结果, 错误原因}, ...]"""
    if not _历史可用:
        return []
    try:
        h = 取爬取历史()
        rows = h.查询(域名=域名, 起始时间=起始时间,
                     结束时间=结束时间, 结果=结果)
        # 明细表只显示前 500 行 (防大数据量拖垮渲染)
        return rows[:500]
    except Exception:
        return []


def get_stats(域名=None, 起始时间=None, 结束时间=None) -> dict:
    """统计 {新增, 更新, 未变化, 失败, 总请求数}"""
    if not _历史可用:
        return {}
    try:
        return 取爬取历史().统计(域名=域名, 起始时间=起始时间,
                                     结束时间=结束时间)
    except Exception:
        return {}


def list_domains() -> list:
    """列出全部有记录的站点域名 (按最近抓取倒序)"""
    if not _历史可用:
        return []
    try:
        return [s.get('域名', '') for s in 取爬取历史().列出全部站点()
                if s.get('域名')]
    except Exception:
        return []


def list_sites_summary() -> list:
    """站点维度汇总 [{域名, 首次抓取, 最近抓取, 总请求数, 统计, URL数}, ...]"""
    if not _历史可用:
        return []
    try:
        return 取爬取历史().列出全部站点()
    except Exception:
        return []


def site_prior(domain: str) -> dict:
    """站点抓取先验 (最优引擎/反爬统计), 无数据返回空 dict"""
    if not _站点历史可用 or not domain:
        return {}
    try:
        return 取站点历史().查站点(f"https://{domain}") or {}
    except Exception:
        return {}
