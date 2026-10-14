# -*- coding: utf-8 -*-
"""页面抓取与引擎降级 (2026-10-14 阶段二批 4 从 爬虫.py 拆出)。

`NovelSpider.inspect_page` 的原样逻辑拆为模块函数 `检查页面(宿主, url)` ——
爬虫.py 的 inspect_page 变为 3 行薄壳 (docstring + 委托), **调用点零变化**
(宿主.inspect_page(url) 仍是方法)。

依赖约定 (宿主 = NovelSpider 实例, 薄壳透传):
  属性: _inspect_cache / _inspect_cache_lock / _fixed_ua /
        last_status_code / last_request_error
  方法: _solve_waf_captcha / _selenium_get_soup / _get_with_js_challenge /
        _get_waf_driver
符号独立性: RESP_CACHE_MAX 在本模块单点定义 (爬虫.py import 桥接,
不留双份); selenium 可用性独立 try-import (与爬虫.py 各自判断同一件事)。

验证: 脚本/解析基线.py --对比 (get_chapter_list 全链路快照) 必须一致。
"""
import time

from bs4 import BeautifulSoup

try:
    from 日志 import get as _取日志
    _log = _取日志('页面抓取')
except Exception:
    import logging
    _log = logging.getLogger('页面抓取')

from sites_config import 站点匹配, validate_public_url

# 响应缓存条目上限 (防长书运行期内存无界增长; 爬虫.py 经 import 桥接使用)
RESP_CACHE_MAX = 64


def 检查页面(宿主, url, polite_delay=True):
    # 延迟 import 避循环依赖: 爬虫.py 在**顶部** import 本模块 (薄壳委托),
    # 本模块若在顶部 import 爬虫会形成环 ⇒ 函数内 import (调用时爬虫模块
    # 必然已加载完毕)。别名一次取全, 函数体内照旧使用。
    import 爬虫 as _爬虫
    _wait_driver_body = _爬虫._wait_driver_body
    _像验证码页 = _爬虫._像验证码页
    _应主动接管验证码 = _爬虫._应主动接管验证码
    _含挑战特征 = _爬虫._含挑战特征
    selenium_available = _爬虫.selenium_available
    """获取网页结构

    polite_delay: 抓取前固定等待 3 秒 (反爬礼貌延迟)。目录页等低频抓取
    保持默认 True; 章节级高频调用 (数据文件探测/适配器正文提取) 传 False,
    请求间隔已由速度自适应模块按档位控制, 固定 3 秒会拖慢千章书近 1 小时。
    """
    validate_public_url(url)  # 安全校验: 仅允许公网 http/https
    # ---- 短时页面缓存 (性能优化) ----
    # 同一 URL 在数秒内常被抓取多次: 每章第 1 页会先经数据文件探测抓取,
    # 随后通用检测再抓同一 URL; 适配器路径亦然。旧实现每章重复请求一次
    # 并各自 sleep(3), 千章书浪费近 1 小时。命中缓存时跳过 sleep 与网络。
    # (已在 __init__ 固定初始化; 挑战页不缓存 — 与 _resp_cache 同一守卫)
    cache = 宿主._inspect_cache
    with 宿主._inspect_cache_lock:
        hit = cache.get(url)
    if hit is not None and time.time() - hit[0] < 20:
        _log.debug(f"[页面缓存] 复用 {time.time() - hit[0]:.1f}s 前的页面 "
                   f"({len(hit[1])} 字符): {url}")
        return BeautifulSoup(hit[1], 'lxml')

    # 尝试使用不同的User-Agent和请求头
    headers = {
        'User-Agent': 宿主._fixed_ua,  # 会话固定UA (验证码cookie绑定UA)
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Cache-Control': 'max-age=0',
        'DNT': '1',
        'Sec-GPC': '1',
        'Referer': url,
        # 不要在此硬编码 'Host'：requests 会按 URL 自动生成（含跳转后的新主机），
        # 手写它会打断 www/主机级跳转 → 无限 301 → Exceeded 30 redirects（踩坑总表 K29）。
        # 不要在此硬编码 Cookie 头：requests 传入 headers 中的 Cookie 会覆盖 session.cookies，
        # 导致反爬提取的 cookie(如 siteW 的 ge_js_validator_20)无法随请求发出，校验永远过不去。
        # 让 session.cookies 自动管理即可。
        'Pragma': 'no-cache',
        'TE': 'trailers'
    }
        
    # WAF 站点: 使用持久化 Selenium driver, 验证码解决后复用同一浏览器实例
    # 避免每次创建新driver都触发WAF验证码
    if 站点匹配(url, 'siteT') and selenium_available:
        _log.info("[WAF驱动] 使用持久化Selenium driver抓取")
        try:
            driver = 宿主._get_waf_driver(visible=False)
            driver.get(url)
            _wait_driver_body(driver)
            # 该类站点为服务端渲染静态页, driver.get 返回即内容就绪, 无需额外等待
            page_source = driver.page_source
            # 检测并处理验证码 (如有)
            page_source = 宿主._solve_waf_captcha(driver, url)
            if '<html' in page_source.lower() or '<body' in page_source.lower():
                _log.info(f"[WAF驱动] 成功获取页面, 长度: {len(page_source)} 字符")
                soup = BeautifulSoup(page_source, 'lxml')
                return soup
            else:
                _log.info("[WAF驱动] 未能获取到HTML内容")
        except Exception as e:
            _log.info(f"[WAF驱动] Selenium抓取失败: {e}")
            import traceback
            traceback.print_exc()

    # 对于siteU、siteV网站，直接使用Selenium
    # (siteW也使用JS cookie校验反爬ge_js_validator，但经测试用requests提取cookie重试即可绕过，
    #  无需Selenium，因此siteW走下方requests路径；仅当requests失败时才回退到末尾的Selenium)
    if (站点匹配(url, 'siteU', 'siteV')) and selenium_available:
        _log.info(f"直接使用Selenium抓取{url.split('/')[2]}网站")
        soup = 宿主._selenium_get_soup(url, headers)
        if soup:
            return soup
        
    if polite_delay:
        time.sleep(3)  # 增加延迟，避免被反爬虫 (章节级高频路径传 polite_delay=False)
        
    try:
        # 网络异常(如 siteW 目录页的 ConnectionResetError)时自动重试, 避免直接进入Selenium兜底
        _conn_retries = 3
        response = None
        宿主.last_request_error = ''   # 每次进入请求路径先清零, 防上一次的失败原因串味
        宿主.last_status_code = 0      # 同上: 状态码也清零, 防上一次响应的码串味
        for _attempt in range(1, _conn_retries + 1):
            try:
                response = 宿主._get_with_js_challenge(url, headers)
                # 状态码就地采集 (批 3 数据缺口): 必须在下面的 5xx 分支把
                # response 置 None **之前**取, 否则 502 也记成"未知"。
                if response is not None:
                    宿主.last_status_code = int(
                        getattr(response, 'status_code', 0) or 0)
                # K36: 5xx 错误页与网络异常同等对待 —— shuhaige 源站间歇 502,
                # 错误页被当目录解析 → 书名 "502 Bad Gateway" → 0 章节死书
                # (2026-10-03 task_10 实测)。重试耗尽 response=None → 空 soup
                # → _目录页为空=True → 死书判定"站点不可达" (不误判目录无章节)。
                if response is not None and getattr(response, 'status_code', 200) >= 500:
                    _log.info(f"[服务器错误] 状态 {response.status_code} "
                              f"({_attempt}/{_conn_retries}), 视为瞬时故障退避重试")
                    # 记下失败原因: 5xx 属"临时故障", 不含 DNS 特征 →
                    # 判定死书时 网站失效=False, 不会误弹"补址"窗 (K36 语义保持)
                    宿主.last_request_error = f'HTTP {response.status_code} 服务器错误'
                    response = None
                    if _attempt >= _conn_retries:
                        break
                    time.sleep(1.0)
                    continue
                break
            except Exception as e:
                _log.info(f"请求失败({_attempt}/{_conn_retries}): {e}")
                # 2026-10-04 (八项需求 #3 修复): 这里是把"域名解析失败"这一信号
                # 带到下游的唯一机会 —— 判定死书 据此置 网站失效, GUI 才可能弹补址窗
                宿主.last_request_error = f'{type(e).__name__}: {e}'
                if _attempt >= _conn_retries:
                    break
                time.sleep(1.0)   # v2.4.28: 3→1s. 失败路径只求快速判定, 不拖延 (超长书提速)
        if response is None:
            _log.info("请求重试耗尽, 返回空页面(交由调用方Selenium兜底)")
            return BeautifulSoup('', 'lxml')

        # 尝试使用ignore模式解码
        try:
            text = response.content.decode('utf-8', errors='ignore')
            # 原始 HTML 预览仅排障用; 此处每页 1 次 (含 500 字符正文), 保持
            # debug 级 —— INFO 级会随页数线性刷爆日志与 GUI 实时面板
            _log.debug(f"解码后内容前500个字符: {text[:500]}")
            # 检查解码后的内容是否包含HTML标签
            if '<html' in text.lower() or '<body' in text.lower():
                _log.info(f"成功获取到HTML内容，长度: {len(text)} 字符")
                # ---- 通用验证码接管 (2026-10-12) ----
                # 入口原先只挂在 siteT 分支 → 非 siteT 站点的验证码页永远进不了
                # 验证码管理器, 用户打开的"自动识别/失败转人工"对它们形同虚设。
                # 这里补一道: 页面像验证码页 **且** 用户启用过自动识别策略 → 接管。
                # 闸门与失败回退都在下方方法内, 保证不改变原本可用的站点行为。
                if _像验证码页(text) and _应主动接管验证码(宿主._captcha_manager):
                    _log.info("[验证码接管] 通用路径检测到验证码页, 尝试接管")
                    _接管soup = 宿主._尝试通用验证码接管(url)
                    if _接管soup is not None:
                        return _接管soup
                response.encoding = 'utf-8'
                if not _含挑战特征(text[:2000]):
                    with 宿主._inspect_cache_lock:
                        # 条目上限淘汰 (M2)
                        while len(宿主._inspect_cache) >= RESP_CACHE_MAX:
                            oldest = min(宿主._inspect_cache,
                                         key=lambda k: 宿主._inspect_cache[k][0])
                            宿主._inspect_cache.pop(oldest, None)
                        宿主._inspect_cache[url] = (time.time(), text)
                soup = BeautifulSoup(text, 'lxml')
                return soup
            else:
                # 尝试使用其他解析器
                _log.info("尝试使用html.parser解析器")
                soup = BeautifulSoup(text, 'html.parser')
                if soup.find():  # 检查是否解析出了任何元素
                    _log.info("成功解析出HTML元素")
                    return soup
        except Exception as e:
            _log.info(f"解码失败: {e}")
    except Exception as e:
        _log.info(f"请求失败: {e}")
        
    # requests 失败后的 Selenium 兜底 (复用 _selenium_get_soup 方法)
    if (站点匹配(url, 'siteU', 'siteV', 'siteW', 'siteT')) and selenium_available:
        soup = 宿主._selenium_get_soup(url, headers)
        if soup:
            return soup
        
    # 如果所有尝试都失败，返回空的BeautifulSoup对象
    return BeautifulSoup('', 'lxml')
