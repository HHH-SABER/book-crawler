# -*- coding: utf-8 -*-
"""WAF 图片验证码自动解决（banlvzw 等站点）

背景: 部分站点 (如 m.banlvzw.com) 在 IP 访问频率过高时返回 401 验证码页:
  <form method=POST action=<原URL>?_waform>
    <img src='/__wafcaptcha?<时间戳>'>
    <input name='__input'>  ← 输入图片中的字符
解决流程:
  1. 从拦截页提取 /__wafcaptcha?<ts> 验证码图片地址
  2. GET 图片 → ddddocr 本地识别 (需在 captcha_config.json 显式开启)
  3. POST <原URL>?_waform + __input=答案 → session 自动保存放行 cookie
  4. 重试原请求即可通过

合规边界: 自动识别默认关闭 (captcha_config.json strategies.dddddocr.enabled=false)。
未开启时给出明确提示, 走人工/等待限频解除路径。

TLS 说明: 本模块不显式传 verify 参数, 继承调用方 session 的 TLS 设置。
"""
import os
import re
import sys
import json
import time
import threading
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

_USE_DDDDOCR = None  # 惰性缓存判断结果


def _preprocess(img_bytes: bytes) -> bytes:
    """验证码图片预处理: 灰度 + 放大3倍, 提升 ddddocr 识别率

    PIL 不可用时返回原图 (不阻断流程)。
    """
    try:
        from PIL import Image
        import io
        im = Image.open(io.BytesIO(img_bytes)).convert('L')
        im2 = im.resize((im.width * 3, im.height * 3), Image.LANCZOS)
        buf = io.BytesIO()
        im2.save(buf, 'PNG')
        return buf.getvalue()
    except Exception:
        return img_bytes


def _ddddocr_enabled() -> bool:
    """自动识别是否显式开启 (读 captcha_config.json 的 strategies.dddddocr.enabled)"""
    global _USE_DDDDOCR
    if _USE_DDDDOCR is not None:
        return _USE_DDDDOCR
    _USE_DDDDOCR = False
    try:
        from _path_utils import resolve_data_file
        cfg_path = resolve_data_file("captcha_config.json")
        if os.path.isfile(cfg_path):
            data = json.loads(Path(cfg_path).read_text(encoding='utf-8'))
            _USE_DDDDOCR = bool(
                data.get('strategies', {}).get('ddddocr', {}).get('enabled'))
    except Exception:
        pass
    return _USE_DDDDOCR


def is_waf_captcha_page(status_code: int, text: str) -> bool:
    """判断响应是否为 WAF 图片验证码拦截页

    两类形态:
    - 经典 __wafcaptcha (401/403/429 + 标记);
    - 内容型"访问验证"页 (als1010 等站点以 **HTTP 200** 返回图片验证码表单,
      状态码层不可区分, 只能靠内容特征: 标题"访问验证" + check_code 接口 +
      页短; 样本 测试样本/als1010_访问验证页.html)。
    命中第二类会进入爬虫既有 WAF 处理分支: 自动识别不适用时转人工兜底。
    """
    if not text:
        return False
    if status_code in (401, 403, 429) and \
            '__wafcaptcha' in text and '验证码' in text:
        return True
    if status_code == 200 and len(text) < 16384 and \
            '访问验证' in text and 'check_code' in text:
        return True
    return False


def _解_表单验证页(session, url: str, 页面文本: str, headers, timeout: int,
                  log, max_tries: int) -> bool:
    """通用表单式验证码页自动求解 (als1010 类: HTTP 200 "访问验证" 页)。

    实测结论 (2026-09-12 实网取证): 该站 WAF 为会话 cookie 制 (无 UA 绑定),
    页面内 `code` 输入框 + `/home/chapter/verify.html` 图片 + `check_code.html`
    表单; ddddocr 识别后按原表单字段 POST 即获放行 cookie, 重取目标 URL 通过。

    做法: 每轮**重新请求被拦页**取新图 (验证码是一次性的), 从页面提取
    图片/表单/隐藏域/输入框名, 识别 → 提交 → 重取目标 URL 验证。

    合规: ddddocr 未显式开启 (strategies.ddddocr.enabled) 时直接拒绝 —
    分发模板与代码默认仍为关闭, 与全局合规边界一致。
    """
    if not _ddddocr_enabled():
        log("[WAF验证码-表单] 自动识别未开启 (captcha_config.json 的 "
            "strategies.ddddocr.enabled=false) → 转人工兜底")
        return False
    from urllib.parse import urljoin
    try:
        import ddddocr
        ocr = ddddocr.DdddOcr(show_ad=False)
    except Exception as e:
        log(f"[WAF验证码-表单] ddddocr 不可用: {e}")
        return False

    for attempt in range(1, max_tries + 1):
        try:
            页 = session.get(url, headers=headers, timeout=timeout)
        except Exception as e:
            log(f"[WAF验证码-表单] 请求拦截页失败: {e}")
            return False
        文本 = 页.text or ''
        if not is_waf_captcha_page(页.status_code, 文本):
            log("[WAF验证码-表单] 页面已非验证页 (证书已放行)")
            return True
        图 = re.search(r'src=["\']([^"\']*(?:verify|captcha|code)[^"\']*)["\']',
                       文本, re.I)
        表单 = re.search(r'<form[^>]+action=["\']([^"\']+)["\']', 文本, re.I)
        if not (图 and 表单):
            log("[WAF验证码-表单] 页面结构不匹配 (无图片/表单), 放弃自动求解")
            return False
        隐藏域 = {}
        输入名 = None
        for m in re.finditer(r'<input\b[^>]*>', 文本, re.I):
            tag = m.group(0)
            nm = re.search(r'name=["\']([^"\']+)["\']', tag)
            if not nm:
                continue
            vm = re.search(r'value=["\']([^"\']*)["\']', tag)
            if 'hidden' in tag.lower():
                隐藏域[nm.group(1)] = vm.group(1) if vm else ''
            elif 输入名 is None:
                输入名 = nm.group(1)
        if not 输入名:
            log("[WAF验证码-表单] 未找到验证码输入框, 放弃")
            return False
        图片URL = urljoin(url, 图.group(1))
        表单URL = urljoin(url, 表单.group(1))
        try:
            from sites_config import validate_public_url
            validate_public_url(图片URL)
            validate_public_url(表单URL)
        except Exception as e:
            log(f"[WAF验证码-表单] 子请求 URL 校验失败: {e}")
            return False
        try:
            图响应 = session.get(图片URL, headers=headers, timeout=timeout)
            if 图响应.status_code != 200 or not 图响应.content:
                raise ValueError(f"状态 {图响应.status_code}")
        except Exception as e:
            log(f"[WAF验证码-表单] 验证码图片获取失败: {e}")
            time.sleep(1.0)
            continue
        try:
            answer = ocr.classification(图响应.content) or \
                ocr.classification(_preprocess(图响应.content))
        except Exception as e:
            log(f"[WAF验证码-表单] 识别异常: {e}")
            answer = None
        if not answer:
            log(f"[WAF验证码-表单] 第{attempt}次识别为空, 重试")
            time.sleep(1.0)
            continue
        log(f"[WAF验证码-表单] 第{attempt}次识别: {answer!r}")
        data = dict(隐藏域)
        data[输入名] = answer
        try:
            session.post(表单URL, data=data,
                         headers={**dict(headers or {}), 'Referer': url,
                                  'Content-Type':
                                      'application/x-www-form-urlencoded'},
                         timeout=timeout, allow_redirects=True)
        except Exception as e:
            log(f"[WAF验证码-表单] 提交失败: {e}")
            time.sleep(1.0)
            continue
        # 以目标 URL 重取验证放行 (提交接口常返回列表页/重定向页, 不作判据)
        try:
            验证 = session.get(url, headers=headers, timeout=timeout)
            if not is_waf_captcha_page(验证.status_code, 验证.text or ''):
                log("[WAF验证码-表单] ✅ 验证码通过, 已获得放行 cookie")
                return True
        except Exception as e:
            log(f"[WAF验证码-表单] 放行验证请求异常: {e}")
        log(f"[WAF验证码-表单] 第{attempt}次未通过, 重试...")
        time.sleep(1.2)
    log("[WAF验证码-表单] 多次识别未通过 (验证码可能较难或被拉黑), 转人工兜底")
    return False


def solve_waf_captcha(session, url: str, headers=None, timeout: int = 20,
                      log=print, max_tries: int = 5) -> bool:
    """解决 WAF 图片验证码并让 session 携带放行 cookie

    Args:
        session: requests.Session (放行 cookie 自动保存, 后续请求直接可用)
        url: 被拦截的请求 URL
        headers: 与原始请求一致的请求头 (尤其 User-Agent, 放行 cookie 绑定 UA)
        max_tries: 识别提交重试次数 (验证码可能识别错)

    Returns:
        True=已通过; False=未解决 (未开启自动识别/识别失败)
    """
    # 安全校验 (防 SSRF): 仅公网 http/https
    try:
        from sites_config import validate_public_url
        validate_public_url(url)
    except Exception as e:
        log(f"[WAF验证码] URL 校验失败: {e}")
        return False

    from urllib.parse import urlparse
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    # 所有子请求带原始 headers (WAF 放行 cookie 与 UA 绑定, 无 UA 会被持续拦截)
    hdrs = dict(headers or {})

    # 内容型表单验证码页 (als1010 类 200 状态"访问验证"页): 走通用表单求解分支
    # (2026-09-12 实网实测: 该形态自动识别可用, 无需弹浏览器人工输入)
    try:
        _首 = session.get(url, headers=hdrs, timeout=timeout)
        if is_waf_captcha_page(_首.status_code, _首.text or '') and \
                '访问验证' in (_首.text or '') and 'check_code' in (_首.text or ''):
            return _解_表单验证页(session, url, _首.text or '', headers,
                                 timeout, log, max_tries)
    except Exception:
        pass

    for attempt in range(1, max_tries + 1):
        # 1. 请求拦截页, 提取验证码图片地址
        # 注意: 不传 verify, 继承调用方 session 的 TLS 设置
        try:
            r = session.get(url, headers=hdrs, timeout=timeout)
        except Exception as e:
            log(f"[WAF验证码] 请求拦截页失败: {e}")
            return False
        m = re.search(r"/__wafcaptcha\?[0-9]+", r.text)
        if not m:
            if '访问验证' in r.text and 'check_code' in r.text:
                log("[WAF验证码] 该站为内容型验证页 (非 __wafcaptcha 表单, "
                    "如 als1010), 自动识别不适用 → 交由人工兜底流程处理")
            else:
                log("[WAF验证码] 页面未包含验证码接口, 可能已放行")
            return False
        captcha_url = base + m.group(0)
        try:
            validate_public_url(captcha_url)
        except Exception:
            return False

        # 2. 获取验证码图片 (继承 session 的 TLS 设置)
        try:
            img = session.get(captcha_url, headers=hdrs, timeout=timeout)
        except Exception as e:
            log(f"[WAF验证码] 图片获取失败: {e}")
            return False
        if img.status_code != 200 or not img.content:
            log("[WAF验证码] 验证码图片获取异常, 跳过重试")
            return False

        # 3. 识别: ddddocr (本地离线, 需显式开启; 预处理图 + 原图双保险)
        answer = None
        if _ddddocr_enabled():
            try:
                import ddddocr
                ocr = ddddocr.DdddOcr(show_ad=False)
                answer = ocr.classification(_preprocess(img.content))
                if not answer:
                    answer = ocr.classification(img.content)
                log(f"[WAF验证码] 第{attempt}次识别: {answer!r}")
            except Exception as e:
                log(f"[WAF验证码] ddddocr 识别失败: {e}")
        if not answer:
            log("[WAF验证码] 自动识别未开启或不可用 → 请在 captcha_config.json 中设置 "
                "strategies.dddddocr.enabled=true 启用自动识别; "
                "或稍后重试等待站点限频解除 (也可在浏览器手动输入验证码)")
            return False

        # 4. POST 提交验证码
        form_url = url + ('&' if '?' in url else '?') + '_waform'
        try:
            r2 = session.post(
                form_url,
                data={'__input': answer},
                headers={**hdrs,
                         'Referer': url,
                         'Content-Type': 'application/x-www-form-urlencoded'},
                timeout=timeout)
        except Exception as e:
            log(f"[WAF验证码] 提交失败: {e}")
            return False
        if r2.status_code == 200 and not is_waf_captcha_page(r2.status_code, r2.text):
            log("[WAF验证码] ✅ 验证码通过, 已获得放行 cookie")
            return True
        log(f"[WAF验证码] 第{attempt}次提交未通过 (状态 {r2.status_code}), 重试...")
        time.sleep(1.5)

    log("[WAF验证码] 多次尝试仍未通过, 可稍后重试")
    return False


# 人工兜底并发闸: 并行 worker 同时遇 WAF 失败时, 只弹一个浏览器
_人工锁 = threading.Lock()


def 回灌cookie(session, cookies: list) -> int:
    """把浏览器 cookie 列表合并进 requests.Session (纯逻辑, 可离线测试)。

    Args:
        cookies: Playwright get_cookies() 格式 [{name, value, domain, path, ...}]
    Returns:
        成功写入条数
    """
    n = 0
    for c in cookies or []:
        try:
            session.cookies.set(
                c['name'], c['value'],
                domain=c.get('domain') or None,
                path=c.get('path') or '/')
            n += 1
        except Exception:
            try:
                session.cookies.set(c['name'], c['value'])
                n += 1
            except Exception:
                pass
    return n


def solve_waf_captcha_manual(session, url: str, log=print,
                             wait_minutes: int = 5) -> bool:
    """自动识别 max_tries 次失败后的人工兜底 (用户需求: 自动5次→人工)。

    流程:
      1. Playwright 反检测**可见**浏览器打开被拦 URL
      2. 轮询页面内容, 直到用户手动输入验证码并通过 (不再是拦截页特征)
      3. 导出浏览器 cookie 回灌 requests session (回灌后原请求可重试)

    注意: WAF 放行 cookie 可能与 UA 绑定 —— 浏览器 UA 与爬虫 UA 不同时,
    回灌后仍可能被拦; 此时由调用方继续走冷却/重试路径 (本函数只负责人工通过)。

    Returns:
        True=用户通过验证码且 cookie 已回灌; False=超时/浏览器不可用/用户放弃
    """
    try:
        from sites_config import validate_public_url
        validate_public_url(url)
    except Exception as e:
        log(f"[WAF验证码-人工] URL 校验失败: {e}")
        return False
    try:
        from browser_driver import create_driver
    except Exception as e:
        log(f"[WAF验证码-人工] 浏览器驱动不可用: {e}")
        return False

    with _人工锁:
        log(f"[WAF验证码-人工] 自动识别未通过 → 打开可见浏览器, "
            f"请在窗口中手动输入验证码并提交 (最长等待 {wait_minutes} 分钟)...")
        driver = None
        try:
            driver = create_driver(visible=True)
            driver.get(url)
            截止 = time.time() + wait_minutes * 60
            while time.time() < 截止:
                src = driver.page_source or ''
                # 拦截页特征消失 = 用户已通过 (浏览器侧无状态码, 按内容判断)
                if '__wafcaptcha' not in src or '验证码' not in src:
                    n = 回灌cookie(session, driver.get_cookies())
                    log(f"[WAF验证码-人工] ✅ 验证码通过, 已回灌 {n} 条 cookie 到 session")
                    return True
                time.sleep(3)
            log("[WAF验证码-人工] ⏳ 等待超时, 放弃人工兜底")
            return False
        except Exception as e:
            log(f"[WAF验证码-人工] 异常: {e}")
            return False
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass
