# -*- coding: utf-8 -*-
"""反爬机制自动检测器
====================

输入任意 HTTP 响应对象（requests.Response 或同构对象），基于
状态码 + 响应头 + body 特征自动识别反爬机制类型，输出结构化识别
结果与建议策略，供主爬虫动态调整抓取方案。

识别机制类型:
  - rate_limit        请求频率限制 (429 / Retry-After / "访问频繁")
  - ua_block           User-Agent 校验拦截 (403/406 + UA 拦截特征)
  - waf_captcha        WAF 图片验证码 (__wafcaptcha)
  - waf_js_challenge   WAF JS 动态令牌挑战 (@wafjs)
  - js_cookie          JS cookie 校验页 (document.cookie + reload)
  - dynamic_token      动态令牌/CSRF 表单 (需二次提交)
  - none               未命中任何已知反爬特征

设计原则: 通用特征驱动, 不硬编码任何域名/书名。
"""

import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional

# 指数退避序列 (秒): 5s → 10s → 20s → 60s
BACKOFF_SEQUENCE = [5, 10, 20, 60]

# body 特征只扫描前 64KB, 避免超大页面拖慢检测
_BODY_SCAN_LIMIT = 65536

# WAF 图片验证码特征 (与 waf_captcha 模块保持一致)
_WAF_CAPTCHA_MARKERS = ('__wafcaptcha', '_waform')

# WAF JS 动态令牌挑战特征
_WAF_JS_MARKERS = ('@wafjs',)

# JS cookie 校验页特征 (ge_js_validator 机制)
_JS_COOKIE_MARKERS = ('ge_js_validator', 'window.location.reload')

# 频率限制文案特征 (中英)
_RATE_LIMIT_TEXT = ('访问频率太高', '访问过于频繁', '请求过于频繁', '操作太快',
                    '请稍后再试', 'frequency', 'too many requests', 'too fast',
                    'rate limit')

# UA 拦截文案特征
_UA_BLOCK_TEXT = ('user-agent', 'user agent', '浏览器标识', '请更换浏览器',
                  '请使用主流浏览器', '您的浏览器', '异常请求', '不支持当前浏览器')

# CSRF / 动态令牌表单特征
_CSRF_FIELD_RE = re.compile(
    r'<input[^>]+type=["\']hidden["\'][^>]+name=["\'](csrf[_-]?token|'
    r'_token|token|authenticity_token|__RequestVerificationToken)["\']',
    re.I)


@dataclass
class 反爬识别结果:
    """单次响应的反爬机制识别结果"""
    机制: str = 'none'                     # 机制类型 (见模块 docstring)
    置信度: float = 0.0                    # 0.0-1.0
    证据: List[str] = field(default_factory=list)   # 命中的特征列表
    建议策略: Dict = field(default_factory=dict)
    # 建议策略字段: retry_after(秒, 0=立即) / rotate_ua / use_selenium / cooldown(秒)


# 模块级单例 (无状态, 可直接用)
检测器 = None


class 反爬检测器:
    """基于响应特征的反爬机制识别器 (无状态, 线程安全)"""

    def 识别(self, response, ua连续失败数: int = 0) -> 反爬识别结果:
        """识别一个 HTTP 响应命中的反爬机制。

        Args:
            response: 响应对象 (需有 status_code / headers / text 属性)
            ua连续失败数: 调用方维护的"同一 UA 连续失败次数" (用于 ua_block 判断)

        Returns:
            反爬识别结果 (未命中时 机制='none')
        """
        try:
            return self._识别_impl(response, ua连续失败数)
        except Exception as e:
            # 检测器自身异常不应中断抓取主流程
            return 反爬识别结果(机制='none', 置信度=0.0,
                              证据=[f'检测异常: {e}'], 建议策略={})

    # ------------------------------------------------------------------
    def _识别_impl(self, response, ua连续失败数: int) -> 反爬识别结果:
        状态码 = getattr(response, 'status_code', 0)
        响应头 = getattr(response, 'headers', {}) or {}
        try:
            body = (getattr(response, 'text', '') or '')[:_BODY_SCAN_LIMIT]
        except Exception:
            body = ''
        body_lower = body.lower()
        证据 = []

        # ---- 1. WAF 图片验证码 (最具体, 优先判定) ----
        hit_markers = [m for m in _WAF_CAPTCHA_MARKERS if m in body]
        if 状态码 in (401, 403, 429) and hit_markers:
            证据 = [f'状态码={状态码}'] + [f'body含{m}' for m in hit_markers]
            return 反爬识别结果(
                机制='waf_captcha', 置信度=0.95, 证据=证据,
                建议策略={'retry_after': 0, 'rotate_ua': False,
                        'use_selenium': False, 'cooldown': 0})

        # ---- 2. WAF JS 动态令牌挑战 ----
        hit_markers = [m for m in _WAF_JS_MARKERS if m in body]
        if 状态码 == 401 and hit_markers:
            证据 = [f'状态码={状态码}'] + [f'body含{m}' for m in hit_markers]
            return 反爬识别结果(
                机制='waf_js_challenge', 置信度=0.9, 证据=证据,
                建议策略={'retry_after': 0, 'rotate_ua': False,
                        'use_selenium': True, 'cooldown': 0})

        # ---- 3. JS cookie 校验页 (任何状态码都可能返回) ----
        hit_markers = [m for m in _JS_COOKIE_MARKERS if m in body]
        # 200 的正文页本身也可能出现 window.location (正常业务脚本),
        # 因此要求两个标记同时命中, 且页面很短 (校验页通常 <10KB)
        if len(hit_markers) >= 2 and len(body) < 10240:
            证据 = [f'状态码={状态码}'] + [f'body含{m}' for m in hit_markers] + \
                  [f'页面短({len(body)}字节)']
            return 反爬识别结果(
                机制='js_cookie', 置信度=0.85, 证据=证据,
                建议策略={'retry_after': 2, 'rotate_ua': False,
                        'use_selenium': False, 'cooldown': 0})

        # ---- 4. 请求频率限制 ----
        retry_after = self._读_retry_after(响应头)
        rate_text = [t for t in _RATE_LIMIT_TEXT if t in body or t in body_lower]
        if 状态码 == 429 or (状态码 == 403 and rate_text) or \
                (状态码 in (200, 503) and rate_text and len(body) < 8192):
            证据 = [f'状态码={状态码}']
            if retry_after is not None:
                证据.append(f'Retry-After={retry_after}s')
            证据 += [f'body含"{t}"' for t in rate_text]
            置信度 = 0.9 if 状态码 == 429 else 0.7
            return 反爬识别结果(
                机制='rate_limit', 置信度=置信度, 证据=证据,
                建议策略={'retry_after': retry_after if retry_after else BACKOFF_SEQUENCE[0],
                        'rotate_ua': False, 'use_selenium': False,
                        'cooldown': retry_after or 0})

        # ---- 5. UA 校验拦截 ----
        ua_text = [t for t in _UA_BLOCK_TEXT if t in body_lower]
        if 状态码 in (403, 406) and ua_text:
            证据 = [f'状态码={状态码}'] + [f'body含"{t}"' for t in ua_text]
            return 反爬识别结果(
                机制='ua_block', 置信度=0.8, 证据=证据,
                建议策略={'retry_after': 0, 'rotate_ua': True,
                        'use_selenium': False, 'cooldown': 0})
        # 同一 UA 连续多次失败 (调用方统计): 强烈提示 UA 被针对
        if 状态码 in (403, 406) and ua连续失败数 >= 3:
            证据 = [f'状态码={状态码}', f'同一UA连续失败{ua连续失败数}次']
            return 反爬识别结果(
                机制='ua_block', 置信度=0.75, 证据=证据,
                建议策略={'retry_after': 0, 'rotate_ua': True,
                        'use_selenium': False, 'cooldown': 5})

        # ---- 6. 动态令牌/CSRF 表单 (200 但疑似需二次提交) ----
        # 仅当状态 200 且页面为空壳 (无正文特征) 时判定, 避免误伤正常页
        if 状态码 == 200 and _CSRF_FIELD_RE.search(body) and len(body) < 16384:
            证据 = [f'状态码={状态码}', 'body含CSRF隐藏域',
                  f'页面短({len(body)}字节, 疑似空壳)']
            return 反爬识别结果(
                机制='dynamic_token', 置信度=0.6, 证据=证据,
                建议策略={'retry_after': 0, 'rotate_ua': False,
                        'use_selenium': False, 'cooldown': 0})

        # ---- 未命中 ----
        return 反爬识别结果(机制='none', 置信度=0.0,
                          证据=[f'状态码={状态码}'], 建议策略={})

    # ------------------------------------------------------------------
    @staticmethod
    def _读_retry_after(响应头) -> Optional[float]:
        """读取 Retry-After 响应头 (秒数或 HTTP 日期), 无效返回 None"""
        try:
            val = 响应头.get('Retry-After') or 响应头.get('retry-after')
            if not val:
                return None
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
            # HTTP 日期格式: 解析为距今秒数
            from email.utils import parsedate_to_datetime
            from datetime import datetime, timezone
            dt = parsedate_to_datetime(val)
            if dt and dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())
        except Exception:
            return None

    # ------------------------------------------------------------------
    @staticmethod
    def 计算退避秒数(连续次数: int, retry_after提示: float = 0) -> float:
        """指数退避: 优先用服务器 Retry-After, 否则按 5→10→20→60 序列

        Args:
            连续次数: 连续命中频率限制的次数 (从 1 开始)
            retry_after提示: 服务器提示的等待秒数 (0=无提示)

        Returns:
            本次应休眠的秒数
        """
        if retry_after提示 and retry_after提示 > 0:
            return min(retry_after提示, 120)  # 尊重服务器, 但封顶 2 分钟
        idx = min(连续次数 - 1, len(BACKOFF_SEQUENCE) - 1)
        return BACKOFF_SEQUENCE[idx]


def 取检测器() -> 反爬检测器:
    """获取模块级单例检测器"""
    global 检测器
    if 检测器 is None:
        检测器 = 反爬检测器()
    return 检测器


def 格式化日志(结果: 反爬识别结果) -> str:
    """把识别结果格式化为统一的结构化日志行"""
    策略 = 结果.建议策略 or {}
    parts = [f"[反爬] 机制={结果.机制} 置信度={结果.置信度:.2f}",
             f"证据=[{', '.join(结果.证据)}]"]
    描述 = []
    if 策略.get('retry_after'):
        描述.append(f"退避{策略['retry_after']}秒")
    if 策略.get('rotate_ua'):
        描述.append("轮换UA")
    if 策略.get('use_selenium'):
        描述.append("升级Selenium")
    if 策略.get('cooldown'):
        描述.append(f"冷却{策略['cooldown']}秒")
    if 描述:
        parts.append(f"→ 策略={'/'.join(描述)}")
    return ' '.join(parts)
