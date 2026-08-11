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
    """判断响应是否为 WAF 图片验证码拦截页"""
    if status_code not in (401, 403, 429) or not text:
        return False
    return ('__wafcaptcha' in text and '验证码' in text)


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
