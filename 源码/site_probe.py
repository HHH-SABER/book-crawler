# -*- coding: utf-8 -*-
"""站点探测：对单站点发测试请求, 返回健康指标 (供站点管理页"测试连接")

流程: requests 探测 → 反爬检测器识别 → 命中反爬时用请求引擎重试 → 汇总。
纯网络 IO, 调用方须放线程池 (避免阻塞 Flet 主线程)。
"""
import time

# 标准桌面 UA (探测用)
_PROBE_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
             "AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/126.0.0.0 Safari/537.36")


def probe_site(url: str, timeout: int = 15) -> dict:
    """探测一个站点, 返回健康指标 dict

    Args:
        url: 站点任意页面 URL (通常取域名根地址)
        timeout: 单次请求超时秒数

    Returns:
        {
          'ok': bool,             # 最终是否拿到 2xx/3xx 响应
          'status_code': int,     # 最终状态码 (0=请求异常)
          'elapsed': float,       # 总耗时秒
          'engine': str,          # 最终成功引擎: requests/cloudscraper/curl_cffi
          'engine_chain': list,   # 尝试过的引擎顺序
          'anti_spider': str,     # 反爬类型 ('none'=未命中)
          'anti_evidence': str,   # 识别证据摘要
          'error': str,           # 异常信息
        }
    """
    result = {
        'ok': False, 'status_code': 0, 'elapsed': 0.0,
        'engine': '', 'engine_chain': [], 'anti_spider': 'none',
        'anti_evidence': '', 'error': '',
    }
    t0 = time.time()
    headers = {'User-Agent': _PROBE_UA,
               'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
               'Accept-Encoding': 'gzip, deflate'}

    # ---- 第一步: requests 探测 ----
    resp = None
    try:
        import requests
        s = requests.Session()
        s.trust_env = False
        resp = s.get(url, headers=headers, timeout=timeout,
                     allow_redirects=True)
        result['status_code'] = int(resp.status_code)
        result['engine'] = 'requests'
    except Exception as e:
        result['error'] = str(e)[:200]
    result['engine_chain'].append('requests')

    # ---- 第二步: 反爬识别 ----
    机制 = 'none'
    if resp is not None:
        try:
            from 反爬检测器 import 取检测器
            r = 取检测器().识别(resp)
            机制 = getattr(r, '机制', 'none')
            result['anti_spider'] = 机制
            result['anti_evidence'] = (getattr(r, '证据', '') or '')[:120]
        except Exception:
            pass

    # ---- 第三步: 命中反爬 → 请求引擎重试 ----
    if resp is not None and 200 <= result['status_code'] < 400 \
            and 机制 in ('none', ''):
        result['ok'] = True
    elif 机制 not in ('none', '') or resp is None or \
            not (200 <= result['status_code'] < 400):
        # 用成熟引擎再试一次 (机制驱动引擎选择)
        try:
            from 请求引擎 import 请求引擎管理器
            mgr = 请求引擎管理器()
            eng_resp = mgr.请求(url, headers=headers, timeout=timeout,
                                机制=机制)
            # 记录降级链 (按可用引擎推断)
            if 机制 in ('waf_js_challenge', 'js_cookie', 'dynamic_token'):
                chain = ['cloudscraper', 'curl_cffi']
            else:
                chain = ['requests']
            for c in chain:
                if c not in result['engine_chain']:
                    result['engine_chain'].append(c)
            if eng_resp is not None:
                sc = int(getattr(eng_resp, 'status_code', 0) or 0)
                if 200 <= sc < 400:
                    result['ok'] = True
                    result['status_code'] = sc
                    result['engine'] = getattr(eng_resp, '引擎', '')
                    result['error'] = ''
        except Exception as e:
            result['error'] = (result['error'] or str(e)[:200])[:200]

    # ---- 汇总 ----
    if resp is not None and not result['ok'] and not result['error']:
        result['error'] = f"HTTP {result['status_code']}"
    result['elapsed'] = round(time.time() - t0, 2)
    return result


def normalize_site_url(domain: str) -> str:
    """域名/URL → 规范探测 URL (根地址)"""
    d = (domain or '').strip()
    if not d:
        return ''
    if not d.startswith(('http://', 'https://')):
        d = 'https://' + d
    # 去路径, 保留根
    try:
        from urllib.parse import urlparse
        p = urlparse(d)
        return f"{p.scheme}://{p.netloc}/"
    except Exception:
        return d
