import 日志 as _app_log
_log = _app_log.get('sites_config')

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
import os
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
# orion34g.com 子目录分页 (必须定义在 SITE_PATTERNS 之前)
# 章节第1页: /orion/{book_id}/{chapter_id}.html
# 第2页:     /orion/{book_id}/{chapter_id}/1.html  (去掉 .html, 追加 /N.html)
# chapter_id 就在章节 URL 中, 无需从 HTML 提取
# ============================================================
_ORION34G_CHAPTER_IDS = {}  # 保留兼容 (旧版预留, 当前不用)


def paginate_orion34g(base_url, page_index):
    """orion34g 子目录分页: 第1页=/orion/{bid}/{cid}.html, 第N页=/orion/{bid}/{cid}/{N}.html"""
    if page_index == 0:
        return base_url
    m = re.match(r'(https?://[^/]+/orion/\d+/\d+)\.html$', base_url)
    if not m:
        return None
    return f"{m.group(1)}/{page_index}.html"


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
#       - {'type': 'auto'}   # 自动检测 (默认): 由 反爬检测器.py 基于响应特征实时识别
#           可识别机制: rate_limit(429/频繁) / ua_block(403+UA特征) / waf_captcha
#           / waf_js_challenge / js_cookie / dynamic_token(CSRF隐藏域)
#           并动态调整策略: 指数退避 / UA轮换 / 引擎切换, 未知站点无需配置
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
    {
        # oldtimeswx.net (旧时光文学): 标准 HTML 选择器 + _N.html 分页
        # 目录URL: /book/{book_id}/
        # 章节URL: /book/{book_id}/{chapter_id}.html (第1页) → _{N}.html (后续页)
        # 第2页示例: 35530884_1.html (start=1)
        'domain': 'oldtimeswx.net',
        'pattern': 'html_selector',
        'catalog_parser': 'generic',
        'content_pagination': {'suffix': '_{N}.html', 'start': 1, 'max_pages': 30},
        'content_selectors': ['#content', '#BookText', '#booktxt', '.content', 'div.content'],
        'anti_spider': {'type': 'none'},
    },
    {
        # banlvzw.com (伴侣中文网): WAF JS 挑战 + ?page=N 查询参数分页
        # 目录URL: /{book_id}/index.html
        # 章节URL: /{book_id}/{N}.html (第1页) → ?page=N (后续页)
        # 第2页示例: 5.html?page=2 (start=2)
        'domain': 'banlvzw.com',
        'pattern': 'html_selector',
        'catalog_parser': 'banlvzw',
        'content_pagination': {'suffix': '?page={N}', 'start': 2, 'max_pages': 30},
        'content_selectors': ['#BookText', '#booktxt', '#content', '.content', '#articlecontent'],
        'anti_spider': {'type': 'waf_js'},
    },
    {
        # yipinzongshi.com (一品小说网): qsbs.bb Base64 加密 + _N.html 分页
        # 章节URL: /book/{book_id}/{chapter_id}.html (第1页)
        # 第2页: /book/{book_id}/{chapter_id}_1.html (后缀 _N.html, start=1)
        # 实测: 57724683.html = 第03章第1页, 57724683_1.html = 第03章第2页
        'domain': 'yipinzongshi.com',
        'pattern': 'qsbs_bb',
        'catalog_parser': 'generic',
        'content_pagination': {'suffix': '_{N}.html', 'start': 1, 'max_pages': 30},
        'content_selectors': ['.word_read', '#content', '.content', 'div.content'],
        'anti_spider': {'type': 'none'},
    },
    {
        # orion34g.com (猎人小说网): qsbs.bb Base64 加密 + 子目录分页
        # 章节第1页: /orion/{book_id}/{chapter_id}.html (chapter_id 就在 URL 中)
        # 第2页: /orion/{book_id}/{chapter_id}/1.html (去掉 .html 加 /N.html)
        'domain': 'orion34g.com',
        'pattern': 'qsbs_bb',
        'catalog_parser': 'generic',
        'content_pagination': {'type': 'function', 'function': paginate_orion34g, 'max_pages': 30},
        'content_selectors': ['.word_read', '#content', '.content', 'div.content'],
        'anti_spider': {'type': 'none'},
    },
    {
        # 630wang.cc (恋上看书网): 目录页 /kan/{id}.html (详情页), 目录分页 /kan/{id}/{n}.html
        # 目录分页按钮由 JS 动态加载, 页面无 "下一页" 链接, 需按规则拼接 /kan/{id}/2.html 等
        # 章节URL: /kan/{id}_{chapid}.html; 正文在 div.word_read 的 <p> 中
        # 反爬: 正文中的数字被服务端替换为 o (如 "早自习o分钟"), 有损替换无法还原, 保留原样
        'domain': '630wang.cc',
        'pattern': 'html_selector',
        'catalog_parser': '630wang',
        'chapter_url_regex': r'/kan/(\d+)_(\d+)\.html',
        'content_pagination': {'suffix': '_{N}.html', 'start': 1, 'max_pages': 30},
        'content_selectors': ['div.word_read', '.word_read', '#content', '.content'],
        'content_extractor': 'word_read_p_filter',
        'anti_spider': {'type': 'none'},
    },
    {
        # ciyewk.com (词夜书屋): 目录 /shu/{bid}.html 的 #list dl dd a 结构
        # 章节URL: /shu/{bid}/{N}.html (bid 为字母数字, 如 OqWe)
        # 正文: 章节页仅有 "章节内容加载中" 占位, 通过 initTxt('//js.ciyewk.com/data/chapter/.../N.book')
        #       加载数据文件; .book 为 _txt_call({content:...}) 码点流压缩格式,
        #       由 content_decoder.decode_chapter_data 自动探测并解码
        # 注意: 不使用通用html_selector模式, 避免提取到"章节内容加载中"占位内容
        'domain': 'ciyewk.com',
        'pattern': 'datafile',  # 强制使用数据文件解码模式
        'catalog_parser': 'ciyewk',
        'chapter_url_regex': r'/shu/[A-Za-z0-9]+/(\d+)\.html',
        'content_pagination': {'suffix': '_{N}.html', 'start': 1, 'max_pages': 5},
        'anti_spider': {'type': 'waf_js'},
    },
    {
        # ltbook.net (龙腾小说网): 目录 /83663/ 简介页通常只有少量章节链接
        # 章节URL: /83663/{chapid}.html (chapid 为长数字, 如 16026145)
        # 正文: div#rtext / #content 的 <p> 中, 混有 &amp;ap;ap;ap;ig src...toigdata... 多层实体
        #       混淆串 (部分汉字被替换, 有损), 用 'ltbook_junk_filter' 提取器清洗删除
        # 完整目录: 简介页章节少时, 从 "全文阅读" 连读页 (/83663/6.html) 链式追踪 "下一页" 补充
        'domain': 'ltbook.net',
        'pattern': 'html_selector',
        'catalog_parser': 'ltbook',
        'chapter_url_regex': r'/(\d+)/(\d+)\.html',
        'content_pagination': {'suffix': '_{N}.html', 'start': 1, 'max_pages': 3},
        'content_selectors': ['#rtext', '#content', 'div#content'],
        'content_extractor': 'ltbook_junk_filter',
        'anti_spider': {'type': 'none'},
    },
]


# ============================================================
# 工具函数
# ============================================================

def get_site_pattern(url):
    """根据 URL 返回匹配的站点配置, 未匹配返回 None"""
    _apply_runtime_config()  # 首次调用时合并 站点配置.json (幂等)
    url_lower = url.lower()
    for pat in SITE_PATTERNS:
        if pat['domain'] in url_lower:
            if pat.get('enabled') is False:
                return None  # 站点被用户禁用 (站点管理页开关)
            return pat
    return None


# ============================================================
# 运行时配置合并: 站点配置.json (GUI 站点管理页写入) 覆盖/追加内置配置
# ============================================================
_RUNTIME_APPLIED = False


def _apply_runtime_config():
    """把 BASE_DIR/站点配置.json 合并进 SITE_PATTERNS (按域名 upsert)。

    - 同域名: 用 JSON 字段覆盖内置条目 (函数型字段如自定义分页不受影响)
    - 新域名: 追加到列表末尾
    - enabled=False: 保留条目但 get_site_pattern 跳过 (可随时重新启用)
    - 任何异常静默降级 (仅用内置配置), 不影响爬虫主流程
    """
    global _RUNTIME_APPLIED
    if _RUNTIME_APPLIED:
        return
    _RUNTIME_APPLIED = True
    try:
        import json as _json
        from _path_utils import resolve_data_file
        cfg_path = resolve_data_file("站点配置.json",
                                     copy_default_from_resource_if_missing=False)
        if not os.path.isfile(cfg_path):
            return
        with open(cfg_path, 'r', encoding='utf-8') as f:
            items = _json.load(f)
        if not isinstance(items, list):
            return
        # 内置条目按域名索引 (upsert 用)
        by_domain = {p['domain']: p for p in SITE_PATTERNS}
        for item in items:
            if not isinstance(item, dict):
                continue
            domain = item.get('domain', '')
            if not domain:
                continue
            if domain in by_domain:
                # 覆盖内置条目 (只更新 JSON 中出现的字段, 保留函数型字段)
                for k, v in item.items():
                    by_domain[domain][k] = v
            else:
                SITE_PATTERNS.append(dict(item))
                by_domain[domain] = item
    except Exception as _e:
        # 运行时配置加载失败 → 静默使用内置配置
        try:
            _log.info(f"[sites_config] 运行时站点配置加载失败, 使用内置配置: {_e}")
        except Exception:
            pass


def build_paged_url(base_url, page_index, pagination):
    """根据分页规则生成分页 URL

    Args:
        base_url: 当前页 URL (如 /read/46358/9218488.html)
        page_index: 页码索引 (0=第一页)
        pagination: 三种类型:
            - {'suffix': '_{N}.html', 'start': 1, 'max_pages': 30}  路径替换
            - {'suffix': '?page={N}', 'start': 2, 'max_pages': 10}  查询参数
            - {'type': 'increment_number', 'max_pages': 10}         序号递增

    Returns:
        分页后的 URL, 或 None 表示没有分页
    """
    if page_index == 0:
        return base_url

    # ---- 自定义函数型 (orion34g 等特殊分页模式) ----
    if pagination.get('type') == 'function':
        if page_index >= pagination.get('max_pages', 30):
            return None
        return pagination['function'](base_url, page_index)

    # ---- 序号递增型 (yipinzongshi.com 等) ----
    if pagination.get('type') == 'increment_number':
        if page_index >= pagination.get('max_pages', 10):
            return None
        m = re.search(r'(\d+)\.html$', base_url)
        if not m:
            return None
        num = int(m.group(1)) + page_index
        return re.sub(r'\d+\.html$', f'{num}.html', base_url)

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
            - 'yqyp_nav_strip': 言情一品书 (yqyp.net) 导航/推荐剥离

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
        if extractor == 'ltbook_junk_filter':
            text = _extract_ltbook_junk_filter(el)
            if text:
                return text
        if extractor == 'word_read_p_filter':
            text = _extract_word_read_p_filter(el)
            if text:
                return text
        if extractor == 'yqyp_nav_strip':
            text = _extract_yqyp_nav_strip(el)
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


def _extract_yqyp_nav_strip(container):
    """言情一品书 (yqyp.net) 正文提取器

    正文位于 div.info_dv1.ov 中, 容器内结构:
      - 顶部面包屑/导航 div + "手机浏览器扫描二维码访问"
      - <h2> 章节标题
      - div.read_btn (上一章/章节目录/保存书签/下一章)
      - 正文 <p> 段落
      - 底部 div.read_btn
      - 作者互动/推荐书目 (如 "阅读指南:", "谢谢宝贝们!", 多书名连缀)
    本函数提取 h2 之后、第二个 read_btn 之前的 <p> 段落,
    并过滤导航/广告/推荐/作者互动行。
    """
    if container is None:
        return ''
    nav_keywords = ('上一章', '下一章', '章节目录', '保存书签', '加入书架',
                    '目录', '首页', '手机浏览器', '扫描二维码')
    junk_markers = ('阅读指南', '收藏', '红包', '么么', '宝贝们',
                    '本章完', '作者有话说', '谢谢', '评论')
    parts = []
    passed_first_read_btn = False
    for child in container.children:
        name = getattr(child, 'name', None)
        # 遇到 h2 标记标题后开始收集
        if name == 'h2':
            continue
        # 第一个 read_btn 之后才真正开始正文
        if name == 'div' and 'read_btn' in ' '.join(child.get('class', [])):
            if not passed_first_read_btn:
                passed_first_read_btn = True
                continue
            # 第二个 read_btn: 停止收集
            break
        if not passed_first_read_btn:
            continue
        if name != 'p':
            continue
        txt = child.get_text(strip=True)
        if not txt:
            continue
        # 跳过明显导航/广告/作者互动; 命中后直接停止, 避免把后续互动/推荐也收进来
        if any(kw in txt for kw in nav_keywords):
            continue
        if any(m in txt for m in junk_markers):
            break
        # 跳过纯下划线/无意义占位
        if re.fullmatch(r'[_\-]+', txt):
            continue
        # 跳过推荐书目串 / 作者互动: 长段中无中文句末标点, 视为非正文
        if len(txt) > 80 and '。' not in txt and '！' not in txt and '？' not in txt:
            break
        parts.append(txt)
    return '\n\n'.join(parts)


def _extract_word_read_p_filter(container):
    """恋上看书网 (630wang.cc) 正文提取器

    正文在 div.word_read 下的 <p> 标签中; 容器内还含 <h3> 章节标题
    与 div.read_btn 导航按钮 (上一章/章节目录/保存书签/下一章), 需排除。
    注意: 正文中的数字被服务端替换为 o (有损替换), 无法还原, 保留原样。
    """
    if container is None:
        return ''
    nav_keywords = ('上一章', '下一章', '章节目录', '保存书签', '加入书架', '目录', '首页')
    parts = []
    for p in container.find_all('p'):
        txt = p.get_text(strip=True)
        if not txt:
            continue
        if any(kw in txt for kw in nav_keywords):
            continue
        # 跳过过短行 (导航/广告), 保留正文段落
        if len(txt) < 5 and not re.search(r'[\u4e00-\u9fff]{2}', txt):
            continue
        parts.append(txt)
    return '\n\n'.join(parts)


def _extract_ltbook_junk_filter(container):
    """龙腾小说网 (ltbook.net) 正文提取器

    正文位于 div#rtext / #content 的 <p> 中, 混有多层实体混淆的干扰串:
      - 形态: &amp;ap;ap;ap;ig src&amp;ap;ap;ap;“toigdata---&amp;ap;ap;ap;“ &amp;ap;ap;ap;
      - 本质: 被多层实体编码的 <img src="..."> 反爬串, 且**原位置的汉字已被替换丢失** (有损)
      - BeautifulSoup 解析后残留: &ap;ap;ap;ig src&ap;ap;ap;“toigdata---&ap;ap;ap;“ &ap;ap;ap;
    另混有站点广告行:
      - 连读页首行: "，最快更新招魂 ！" (书名/作者/最快更新 广告残留)
    本函数删除含 toigdata 的干扰片段、孤立 ap; 残留及广告行, 保留剩余正文。
    """
    if container is None:
        return ''
    text = container.get_text('\n', strip=True)
    # 删除含 toigdata 的混淆片段 (从 ap;ig src 到垃圾串结束, 吃掉尾部非汉字残留)
    text = re.sub(r'(?:&|;)?(?:ap;)+ig\s+src.*?toigdata[^\u4e00-\u9fff]*',
                  '', text, flags=re.S)
    # 兜底: 清理残留的孤立 ap; 串 (如 "&ap;ap;ap;" 残留)
    text = re.sub(r'[&;]?(?:ap;)+', '', text)
    # 按行过滤站点广告/导航行 (连读页首行 "，最快更新招魂 ！" 等)
    lines = [ln for ln in text.split('\n') if ln.strip() and '最快更新' not in ln]
    text = '\n'.join(lines)
    # 清理连续空行/首尾空白
    text = re.sub(r'\n{2,}', '\n', text).strip()
    return text


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
