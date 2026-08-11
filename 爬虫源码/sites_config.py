"""
站点适配模式库
===============

将已适配过的小说网站的反爬机制、目录解析、正文获取、分页规则等
抽象为可复用的模式。以后遇到新站，只需在 SITE_PATTERNS 中添加一条
配置，无需修改主爬虫逻辑。

模式说明：
  - PATTERN_QSBS_BB: qsbs.bb() Base64 加密 (zhiruo / biquwx / ahxsw)
      正文是 <script>document.writeln(qsbs.bb('BASE64'))</script>
      分页: /{chap_id}.html → /{chap_id}_{N}.html
      反爬: ge_js_validator JS cookie 校验

  - PATTERN_AJAX_TWO_STEP: 两步 AJAX 动态加载 (11bzw.org)
      步骤1: GET /api/read_sign.php?aid=X&cid=Y 获取 {sign, bk}
      步骤2: GET /read/X/Y.html?ajax=1&aid=X&cid=Y&bk=Z&sign=S 获取正文
      分页: /read/X/Y.html → /read/X/Y_{N}.html (N 从 2 开始)
      反爬: PHPSESSID / SSRID cookie

  - PATTERN_HTML_SELECTOR: 通用 BeautifulSoup 选择器
      通过一组 CSS 选择器按优先级依次尝试提取正文
      可配合 'content_extractor' 标记调用专用提取器
      (如 'yunquge_p_filter' 按 <p> 标签逐行过滤云趣阁的广告/导航行)
      已适配站点: yqyp.net, 28zw.org, spscl.com (云趣阁)

  - PATTERN_SELENIUM: Selenium 无头浏览器渲染
      当以上方式都失效时的兜底方案

扩展新站点：
  1. 识别该站点属于哪种模式（上述 4 种 + 可自行添加）
  2. 在 SITE_PATTERNS 中添加条目，填入必要的配置
  3. 无需修改主爬虫代码
"""

import re
import time
import base64
import ipaddress
from urllib.parse import urlparse
from bs4 import BeautifulSoup


def validate_public_url(url):
    """校验请求 URL 是否允许访问。
    仅允许 http/https 协议，且 host 不得为 localhost、环回、私有、
    链路本地、保留、组播或未指定地址（防止请求内网/本地资源）。
    不合法时抛出 ValueError。
    """
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        raise ValueError(f"仅允许 http/https 协议: {url}")
    host = (parsed.hostname or '').lower()
    if not host:
        raise ValueError(f"URL 缺少 host: {url}")
    if host == 'localhost' or host.endswith('.local') or host.endswith('.internal'):
        raise ValueError(f"禁止访问内网主机: {url}")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return  # 公网域名，放行（不在此处发起 DNS 解析）
    if (ip.is_private or ip.is_loopback or ip.is_link_local or
            ip.is_reserved or ip.is_multicast or ip.is_unspecified):
        raise ValueError(f"禁止访问非公网地址: {url}")

# ============================================================
# 模式常量
# ============================================================
PATTERN_QSBS_BB = 'qsbs_bb'
PATTERN_AJAX_TWO_STEP = 'ajax_two_step'
PATTERN_HTML_SELECTOR = 'html_selector'
PATTERN_SELENIUM = 'selenium'


# ============================================================
# 站点配置表
# ============================================================
# 每个站点条目结构:
# {
#   'domain':          域名 (用于匹配, 主爬虫通过 'if domain in url' 选择)
#   'pattern':         模式常量
#   'catalog_parser':  目录解析方式
#       - 'generic':    通用 (用 novel_path 过滤 href)
#       - 'biquwx':     biquwx 专门 (读 /txt{id}.shtml)
#       - '11bzw':      11bzw 专门 (读 /read/{aid}/{cid}.html)
#       - 'zhiruo':     zhiruo 专门 (解析 onclick="read_tz(id)")
#   'chapter_url_regex': 章节链接正则 (从目录页 href 提取章节ID)
#   'chapter_url_template': 章节URL模板, {0}=小说ID, {1}=章节ID
#   'content_pagination': 分页规则
#       - {'suffix': '_{N}.html', 'start': 1}   # zhiruo/biquwx 第2页=_1.html
#       - {'suffix': '_{N}.html', 'start': 2}   # 11bzw 第2页=_2.html
#   'content_selectors': 正文选择器 (仅 HTML_SELECTOR 模式使用)
#   'anti_spider':     反爬机制
#       - {'type': 'js_cookie', 'cookie_name': 'ge_js_validator_20'}
#       - {'type': 'none'}
# }

SITE_PATTERNS = [
    {
        'domain': 'zhiruo.org',
        'pattern': PATTERN_QSBS_BB,
        'catalog_parser': 'zhiruo',
        'chapter_url_regex': r'/(\d+)/(\d+)\.html',
        'content_pagination': {'suffix': '_{N}.html', 'start': 1, 'max_pages': 30},
        'content_selectors': ['#content', '.content'],
        'anti_spider': {'type': 'js_cookie', 'cookie_name': 'ge_js_validator_20'},
    },
    {
        'domain': 'biquwx.cc',
        'pattern': PATTERN_QSBS_BB,
        'catalog_parser': 'biquwx',
        'chapter_url_regex': r'/(\d+)/(\d+)\.html',
        'content_pagination': {'suffix': '_{N}.html', 'start': 1, 'max_pages': 30},
        'content_selectors': ['#content', '.content'],
        'anti_spider': {'type': 'js_cookie', 'cookie_name': 'ge_js_validator_20'},
    },
    {
        'domain': 'ahxsw.com',
        'pattern': PATTERN_QSBS_BB,
        'catalog_parser': 'generic',
        'chapter_url_regex': r'/(\d+)/(\d+)\.html',
        'content_pagination': {'suffix': '_{N}.html', 'start': 1, 'max_pages': 30},
        'content_selectors': ['#content', '.content'],
        'anti_spider': {'type': 'js_cookie', 'cookie_name': 'ge_js_validator_20'},
    },
    {
        'domain': '11bzw.org',
        'pattern': PATTERN_AJAX_TWO_STEP,
        'catalog_parser': '11bzw',
        'chapter_url_regex': r'/read/(\d+)/(\d+)\.html',
        'content_pagination': {'suffix': '_{N}.html', 'start': 2, 'max_pages': 30},
        'content_selectors': ['#content'],
        'anti_spider': {'type': 'session_cookie'},
    },
    {
        'domain': 'yqyp.net',
        'pattern': PATTERN_HTML_SELECTOR,
        'catalog_parser': 'yqyp',
        'chapter_url_regex': r'/book/(\d+)/(\d+)\.html',
        # 分页: 第2页=_2.html (实际多数章节单页, 指纹去重自动处理)
        'content_pagination': {'suffix': '_{N}.html', 'start': 2, 'max_pages': 5},
        # 正文在 div.info_dv1.ov 下, 第一个 div.read_btn 之后的 <p> 标签中
        # 遇到VIP提示/推荐列表/第二个read_btn时停止
        'content_selectors': ['div.info_dv1.ov'],
        'content_extractor': 'yqyp_nav_strip',  # 专用提取器标记
        'anti_spider': {'type': 'js_cookie', 'cookie_name': 'ge_js_validator_20'},
    },
    {
        # 云趣阁 (28zw.org 镜像), 正文用 qsbs.bb() Base64 加密 (与 zhiruo/biquwx/ahxsw 同机制)
        # 目录页: /book/{aid}/ml{N}.html (ml1, ml2, ... 分页; 详情页含"最新章节"倒序+"章节列表"正序, 需去重)
        # 章节页: /book/{aid}/{cid}.html, 分页 _{N}.html (第2页=_1.html)
        # 解码后每个 <p> 含正文, 但混有广告行: "一秒记住新域名 https://..."、"请勿开启浏览器阅读模式"、"相邻推荐:..."等
        # 用 'yunquge_p_filter' 提取器在 Base64 解码后逐 <p> 过滤广告/导航行
        'domain': '28zw.org',
        'pattern': PATTERN_QSBS_BB,
        'catalog_parser': 'yunquge',
        'chapter_url_regex': r'/book/(\d+)/(\d+)\.html',
        'content_pagination': {'suffix': '_{N}.html', 'start': 1, 'max_pages': 30},
        'content_selectors': ['div.content', 'div#txt', '#content', '.content'],
        'content_extractor': 'yunquge_p_filter',
        'anti_spider': {'type': 'js_cookie', 'cookie_name': 'ge_js_validator_20'},
    },
    {
        # spscl.com 与 28zw.org 同属云趣阁, 正文同样用 qsbs.bb() Base64 加密
        # 目录页: /yue/{aid}/ml{N}.html; 章节页: /yue/{aid}/{cid}.html, 分页 _{N}.html
        'domain': 'spscl.com',
        'pattern': PATTERN_QSBS_BB,
        'catalog_parser': 'yunquge',
        'chapter_url_regex': r'/yue/(\d+)/(\d+)\.html',
        'content_pagination': {'suffix': '_{N}.html', 'start': 1, 'max_pages': 30},
        'content_selectors': ['div.word_read', 'div.content', 'div#txt', '#content', '.content'],
        'content_extractor': 'yunquge_p_filter',
        'anti_spider': {'type': 'js_cookie', 'cookie_name': 'ge_js_validator_20'},
    },
    {
        'domain': 'pjxdd.com',
        'pattern': PATTERN_SELENIUM,
        'catalog_parser': 'generic',
        'chapter_url_regex': r'/(\d+)/(\d+)\.html',
        'content_pagination': {'suffix': '_{N}.html', 'start': 1, 'max_pages': 10},
        'content_selectors': ['#content', '.content'],
        'anti_spider': {'type': 'challenge_page'},
    },
    {
        'domain': 'qingheks.com',
        'pattern': PATTERN_SELENIUM,
        'catalog_parser': 'generic',
        'chapter_url_regex': r'/(\d+)/(\d+)\.html',
        'content_pagination': {'suffix': '_{N}.html', 'start': 1, 'max_pages': 10},
        'content_selectors': ['#content', '.content'],
        'anti_spider': {'type': 'challenge_page'},
    },
    {
        'domain': '27xsw.cc',
        'pattern': PATTERN_SELENIUM,
        'catalog_parser': 'generic',
        'chapter_url_regex': r'/(\d+)/(\d+)\.html',
        'content_pagination': {'suffix': '_{N}.html', 'start': 1, 'max_pages': 10},
        'content_selectors': ['#content', '.content'],
        'anti_spider': {'type': 'challenge_page'},
    },
    {
        # 5hbook.net: 正文用 str_decode("...") Base64 加密 (与 qsbs.bb 类似但 JS 函数名不同)
        # 目录页: /books/{id}.html, 章节链接: /books/{id}/{cid}.html
        # 章节页: /books/{id}/{cid}.html, 分页 _{N}.html (第2页=_2.html)
        # 解码后是带 <p> 标签的 HTML 正文
        'domain': '5hbook.net',
        'pattern': 'str_decode_bb',
        'catalog_parser': 'generic',
        'chapter_url_regex': r'/books/(\d+)/(\d+)\.html',
        'content_pagination': {'suffix': '_{N}.html', 'start': 2, 'max_pages': 10},
        'content_selectors': ['#content', '.content', '#htmlContent'],
        'anti_spider': {'type': 'none'},
    },
    {
        # exotxt.net: TXT小说网, 正文直接内嵌HTML, 无分页
        # 目录页: /infos/{book_id}.html (或 /infos/{book_id}/1/ 自动规范化)
        # 章节链接: /infos/{book_id}/{chapter_id}.html
        # 章节页: 单页无分页, 正文在 div.content 中
        'domain': 'exotxt.net',
        'pattern': 'html_selector',
        'catalog_parser': 'generic',
        'chapter_url_regex': r'/infos/(\d+)/(\d+)\.html',
        'content_pagination': {'suffix': '_{N}.html', 'start': 1, 'max_pages': 1},
        'content_selectors': ['div.content', '.content', '#content'],
        'anti_spider': {'type': 'none'},
    },
    {
        # tanmixs.com (探秘小说网移动版): 需 Selenium 绕过 401 反爬
        # 目录URL: /{book_id}/ml.html (第1页) → /{book_id}/ml_N.html (后续页)
        # 章节URL: /{book_id}/{chapter_id}.html
        # 章节分页: ?page=N 查询参数 (如 /YzN6/1.html?page=2)
        # 正文容器: div#chapter-content (含 <p class="chapter-line" data-line="N"> 段落)
        # 目录页章节标题统一为 "分章阅读 N", 实际标题在章节页第一段
        'domain': 'tanmixs.com',
        'pattern': 'selenium',
        'catalog_parser': 'tanmixs',
        'chapter_url_regex': r'/([A-Za-z0-9]+)/(\d+)\.html',
        'content_pagination': {'suffix': '?page={N}', 'start': 2, 'max_pages': 10},
        'content_selectors': ['div#chapter-content', 'div.chapter-content', '#content', '.content'],
        'anti_spider': {'type': 'selenium_required'},
    },
]


# ============================================================
# 工具函数
# ============================================================

def get_site_pattern(url):
    """根据 URL 返回匹配的站点配置, 未匹配返回 None"""
    url_lower = url.lower()
    for pat in SITE_PATTERNS:
        if pat['domain'] in url_lower:
            return pat
    return None


def build_paged_url(base_url, page_index, pagination):
    """根据分页规则生成分页 URL

    Args:
        base_url: 当前页 URL (如 /read/46358/9218488.html)
        page_index: 页码索引 (0=第一页)
        pagination: {'suffix': '_{N}.html', 'start': 1, 'max_pages': 30}
                  或  {'suffix': '?page={N}', 'start': 2, 'max_pages': 10}  (tanmixs.com 格式)

    Returns:
        分页后的 URL, 或 None 表示没有分页
    """
    if page_index == 0:
        return base_url
    page_num = pagination['start'] + page_index - 1
    if page_num > pagination.get('max_pages', 30):
        return None
    suffix = pagination['suffix']
    # 查询参数模式 (如 ?page={N}): 直接追加到 URL 末尾, 不替换 .html
    # 用于 tanmixs.com 等使用 ?page=N 翻页的站点
    if '?' in suffix:
        return f"{base_url}{suffix.replace('{N}', str(page_num))}"
    # 路径替换模式 (如 _{N}.html): 替换 .html 为分页后缀
    suffix = suffix.replace('{N}', str(page_num))
    return base_url.replace('.html', suffix)


def detect_qsbs_bb_pattern(html):
    """检测页面是否使用 qsbs.bb Base64 加密"""
    return bool(re.search(r"qsbs\.bb\('([A-Za-z0-9+/=]+)'\)", html))


def detect_ajax_pattern(html):
    """检测页面是否使用两步 AJAX 动态加载"""
    return bool(re.search(r'/api/read_sign\.php', html))


def auto_detect_pattern(session, url, headers, base_url=None):
    """自动探测未知站点的适配模式
    
    Args:
        session: requests.Session
        url: 章节页 URL
        headers: 请求头
        base_url: 站点基础 URL
    
    Returns:
        检测到的模式, 或 None
    """
    try:
        resp = session.get(url, headers=headers, timeout=30)
        html = resp.content.decode('utf-8', errors='ignore')
        
        if detect_qsbs_bb_pattern(html):
            return PATTERN_QSBS_BB
        if detect_ajax_pattern(html):
            return PATTERN_AJAX_TWO_STEP
        
        # 检查是否有选择器能提取到足够内容
        soup = BeautifulSoup(html, 'lxml')
        for sel in ['#content', '.content', '#nr1', '#bookcontent', '#chaptercontent']:
            el = soup.select_one(sel)
            if el and len(el.get_text(strip=True)) > 500:
                return PATTERN_HTML_SELECTOR
        
        return None
    except Exception:
        return None


# ============================================================
# 正文提取实现 (每个模式对应一个函数)
# ============================================================

def extract_content_qsbs_bb(html):
    """从 qsbs.bb 加密的 HTML 中提取正文
    
    Args:
        html: 原始页面 HTML
    
    Returns:
        解码后的纯文本
    """
    blocks = re.findall(r"qsbs\.bb\('([A-Za-z0-9+/=]+)'\)", html)
    if not blocks:
        return ''
    full_html = ''
    for b in blocks:
        try:
            full_html += base64.b64decode(b).decode('utf-8', errors='ignore')
        except Exception:
            continue
    if not full_html:
        return ''
    soup = BeautifulSoup(full_html, 'lxml')
    return soup.get_text('\n', strip=True)


def extract_content_ajax_two_step(session, current_url, pattern, base_url, headers):
    """11bzw.org 两步 AJAX 正文获取
    
    Args:
        session: requests.Session
        current_url: 当前章节页 URL
        pattern: 站点配置
        base_url: 站点基础 URL
        headers: 请求头
    
    Returns:
        (正文文本, 成功标志)
    """
    
    m_url = re.search(r'/read/(\d+)/(\d+)(_\d+)?\.html', current_url)
    if not m_url:
        return '', False

    validate_public_url(current_url)  # 安全校验
    aid = m_url.group(1)
    cid_base = m_url.group(2)
    cid_full = m_url.group(2) + (m_url.group(3) or '')
    page_path = f"/read/{aid}/{cid_full}.html"
    
    # 1. 访问章节页获取 cookie
    session.get(current_url, headers=headers, timeout=30)
    
    # 2. 获取签名
    ts = int(time.time() * 1000)
    ajax_headers = {
        'Referer': f"{base_url}{page_path}",
        'X-Requested-With': 'XMLHttpRequest',
    }
    sign_url = f"{base_url}/api/read_sign.php?aid={aid}&cid={cid_base}&_={ts}"
    validate_public_url(sign_url)  # 安全校验
    try:
        sign_resp = session.get(sign_url, headers={**headers, **ajax_headers}, timeout=20)
        sign_data = sign_resp.json()
    except Exception:
        return '', False
    
    if sign_data.get('code') != 0:
        return '', False
    
    bk = sign_data['bk']
    sign = sign_data['sign']
    
    # 3. 获取正文
    ts2 = int(time.time() * 1000)
    content_url = f"{base_url}{page_path}?ajax=1&aid={aid}&cid={cid_full}&bk={bk}&sign={sign}&_={ts2}"
    validate_public_url(content_url)  # 安全校验
    try:
        content_resp = session.get(content_url, headers={**headers, **ajax_headers}, timeout=20)
        content_html = content_resp.text
    except Exception:
        return '', False
    
    if not content_html.strip():
        return '', False
    
    csoup = BeautifulSoup(content_html, 'lxml')
    text = csoup.get_text('\n', strip=True)
    return text, True


def extract_content_html_selector(html, selectors, extractor=None):
    """通过 BeautifulSoup 选择器提取正文

    Args:
        html: 原始页面 HTML
        selectors: 选择器列表, 按优先级依次尝试
        extractor: 专用提取器标记 (可选)
            - 'yunquge_p_filter': 云趣阁按 <p> 逐行过滤广告/导航行

    Returns:
        正文文本
    """
    soup = BeautifulSoup(html, 'lxml')
    for sel in selectors:
        el = soup.select_one(sel)
        if not el:
            continue
        if extractor == 'yunquge_p_filter':
            text = _extract_yunquge_p_filter(el)
            if text:
                return text
        text = el.get_text('\n', strip=True)
        if len(text) > 200:
            return text
    # 兜底: 找最长文本容器
    candidates = []
    for el in soup.find_all(True):
        text = el.get_text(strip=True)
        if len(text) > 500:
            candidates.append((len(text), text))
    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
    return ''


def _extract_yunquge_p_filter(container):
    """云趣阁 (28zw.org / spscl.com) 正文提取器

    正文位于 div.content / div.word_read 的 <p> 标签中, 但混有广告/导航行:
      - "一秒记住新域名 https://..." (含 URL 的广告)
      - "请勿开启浏览器阅读模式..."
      - "相邻推荐:..." 或纯推荐书名列表 (短词组以多空格分隔)
      - 章节标题前缀 "XXX最新章节txt——..."
      - "创作者：" / "创作完成日：" 元信息
      - "myJs.bookJs2();" 等 JS 残留
    本函数逐个 <p> 取文本, 跳过上述无意义行, 保留正文段落。
    """
    if container is None:
        return ''
    # 云趣阁广告/导航行特征 (任一命中即跳过该 <p>)
    ad_markers = (
        '一秒记住新域名', '请勿开启浏览器阅读模式', '相邻推荐',
        '最新章节txt——', '创作者：', '创作完成日：',
        'myJs.', 'bookJs', '本章未完，点击下一页',
        '请收藏本站', '手机用户请访问', 'm.spscl.com', 'www.28zw.org',
    )
    parts = []
    for p in container.find_all('p'):
        txt = p.get_text(strip=True)
        if not txt:
            continue
        # 含 URL 的广告行 (云趣阁常见 "一秒记住新域名 https://...")
        if 'http://' in txt or 'https://' in txt:
            continue
        if any(m in txt for m in ad_markers):
            continue
        # 纯相邻推荐列表: 多个书名以连续空格分隔且无标点 (如 "书名1  书名2  书名3")
        # 检测特征: 含 3+ 连续空格且无中文句号/逗号
        if '   ' in txt and '。' not in txt and '，' not in txt and len(txt) > 30:
            continue
        parts.append(txt)
    return '\n\n'.join(parts)


# ============================================================
# 通用正文提取入口 (主爬虫调用此函数)
# ============================================================

def extract_content(session, current_url, pattern, base_url, headers, inspect_page_fn):
    """统一正文提取入口, 根据模式自动分发
    
    Args:
        session: requests.Session
        current_url: 章节页 URL
        pattern: 站点配置 (来自 get_site_pattern)
        base_url: 站点基础 URL
        headers: 请求头
        inspect_page_fn: 反爬校验函数 (由主爬虫提供)
    
    Returns:
        (正文文本, 成功标志)
    """
    pat = pattern['pattern']
    
    if pat == PATTERN_QSBS_BB:
        resp = inspect_page_fn(current_url, headers)
        if resp is None:
            return '', False
        html = resp.content.decode('utf-8', errors='ignore')
        text = extract_content_qsbs_bb(html)
        return text, len(text) > 100
    
    elif pat == PATTERN_AJAX_TWO_STEP:
        return extract_content_ajax_two_step(session, current_url, pattern, base_url, headers)
    
    elif pat == PATTERN_HTML_SELECTOR:
        resp = inspect_page_fn(current_url, headers)
        if resp is None:
            return '', False
        html = resp.content.decode('utf-8', errors='ignore')
        text = extract_content_html_selector(
            html,
            pattern.get('content_selectors', ['#content', '.content']),
            extractor=pattern.get('content_extractor'),
        )
        return text, len(text) > 100
    
    else:
        return '', False
