import 日志 as _app_log
_log = _app_log.get('sites_config')

"""
站点适配模式库
===============

将小说网站的反爬机制、目录解析、正文获取、分页规则等
抽象为可复用的模式。以后遇到新站，只需在站点表中添加一条
配置，无需修改主爬虫逻辑。

站点配置三来源 (按加载顺序, 后者按域名 upsert 覆盖前者):
  1. 站点适配_本地/站点表.json —— 内置站点表 (不入库, 见 AGENTS §目录与文件管理规范 四)
  2. 站点适配/ 与 站点适配_本地/ 下的适配器插件 .py (SITE dict upsert)
  3. 站点配置.json —— 用户运行时配置 (GUI 站点管理页写入)

模式说明：
  - PATTERN_QSBS_BB: qsbs.bb() Base64 加密
      正文是 <script>document.writeln(qsbs.bb('BASE64'))</script>
      分页: /{chap_id}.html → /{chap_id}_{N}.html
      反爬: ge_js_validator JS cookie 校验

  - PATTERN_AJAX_TWO_STEP: 两步 AJAX 动态加载
      步骤1: GET /api/read_sign.php?aid=X&cid=Y 获取 {sign, bk}
      步骤2: GET /read/X/Y.html?ajax=1&aid=X&cid=Y&bk=Z&sign=S 获取正文
      分页: /read/X/Y.html → /read/X/Y_{N}.html (N 从 2 开始)
      反爬: PHPSESSID / SSRID cookie

  - PATTERN_HTML_SELECTOR: 通用 BeautifulSoup 选择器
      通过一组 CSS 选择器按优先级依次尝试提取正文
      可配合 'content_extractor' 标记调用专用提取器
      (站点专属提取器实现放 站点适配_本地/_提取器.py, 不入库;
       机制名经 _EXTRACTORS 注册表分发, 旧站点名别名见 _EXTRACTOR_ALIASES)

  - PATTERN_SELENIUM: Selenium 无头浏览器渲染
      当以上方式都失效时的兜底方案

扩展新站点：
  1. 识别该站点属于哪种模式（上述 4 种 + 可自行添加）
  2. 站点条目加入 站点适配_本地/站点表.json (或适配器插件的 SITE dict)
  3. 无需修改主爬虫代码
"""

import re
import os
import time
import base64
import ipaddress
import threading
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
# 函数型分页注册表 (必须定义在 SITE_PATTERNS 之前)
# 站点表.json 外置形态下 JSON 无法序列化函数, content_pagination 用
#   {'type': 'function', 'function': '<机制名>', ...} 引用本注册表。
#   chapter_subdir — 章节子目录分页:
#   章节第1页: /{seg}/{book_id}/{chapter_id}.html
#   第2页:     /{seg}/{book_id}/{chapter_id}/1.html  (去掉 .html, 追加 /N.html)
#   chapter_id 就在章节 URL 中, 无需从 HTML 提取
# ============================================================


def _paginate_chapter_subdir(base_url, page_index):
    """章节子目录分页: 第1页=/{seg}/{bid}/{cid}.html, 第N页=/{seg}/{bid}/{cid}/{N}.html"""
    if page_index == 0:
        return base_url
    m = re.match(r'(https?://[^/]+/[^/]+/\d+/\d+)\.html$', base_url)
    if not m:
        return None
    return f"{m.group(1)}/{page_index}.html"


_PAGINATION_FUNCTIONS = {
    'chapter_subdir': _paginate_chapter_subdir,
}


# ============================================================
# 站点配置表
# ============================================================
# 内置站点条目已外置到 站点适配_本地/站点表.json (不入库, 站点脱钩机制,
# 见 AGENTS §目录与文件管理规范 四)。公开仓库形态下本表为空, 程序仅靠
# 站点配置.json (用户运行时配置) 与公开侧适配器工作; 本地形态由
# _load_site_table() 启动时把站点表逐条 upsert 进本列表。
#
# 每个站点条目结构 (字段语义, 加载时原样透传):
# {
#   'domain':          域名 (用于匹配, 主爬虫通过 'if domain in url' 选择)
#   'pattern':         模式常量 (见模块 docstring 四种模式)
#   'catalog_parser':  目录解析方式 ('generic' 通用, 其余为站点专属解析器标记,
#                      由主爬虫的目录解析分发表处理)
#   'chapter_url_regex': 章节链接正则 (从目录页 href 提取章节ID)
#   'content_pagination': 分页规则
#       - {'suffix': '_{N}.html', 'start': 1}   # 路径替换, 第2页=_1.html
#       - {'suffix': '_{N}.html', 'start': 2}   # 路径替换, 第2页=_2.html
#       - {'suffix': '?page={N}', 'start': 2}   # 查询参数分页
#       - {'type': 'function', 'function': '<机制名>'}   # 函数型, 见 _PAGINATION_FUNCTIONS
#   'content_selectors': 正文选择器 (仅 HTML_SELECTOR 模式使用)
#   'content_extractor': 专用提取器机制名 (实现在 站点适配_本地/_提取器.py)
#   'anti_spider':     反爬机制
#       - {'type': 'js_cookie', 'cookie_name': 'ge_js_validator_20'}
#       - {'type': 'none'}
#       - {'type': 'auto'}   # 自动检测 (默认): 由 反爬检测器.py 基于响应特征实时识别
#           可识别机制: rate_limit(429/频繁) / ua_block(403+UA特征) / waf_captcha
#           / waf_js_challenge / js_cookie / dynamic_token(CSRF隐藏域)
#           并动态调整策略: 指数退避 / UA轮换 / 引擎切换, 未知站点无需配置
# }

SITE_PATTERNS = []   # 内置站点表已外置 站点适配_本地/站点表.json (站点脱钩)


# ============================================================
# 工具函数
# ============================================================

def get_site_pattern(url):
    """根据 URL 返回匹配的站点配置, 未匹配返回 None"""
    _apply_runtime_config()  # 首次调用时合并 站点配置.json (幂等)
    load_adapters()          # 首次调用时加载站点表与适配器插件 (幂等)
    url_lower = url.lower()
    for pat in SITE_PATTERNS:
        if pat['domain'] in url_lower:
            if pat.get('enabled') is False:
                return None  # 站点被用户禁用 (站点管理页开关)
            return pat
    return None


# ============================================================
# 站点级广告规则 (2026-09-29 清洗智能化): 站点配置.json 条目可选键
#   "ad_rules": {"关键词": [...], "行正则": [...]}
# 由 _执行重放 的任意字段 upsert 自动流入 SITE_PATTERNS (零加载代码),
# 经 获取广告规则() 编译缓存后供 爬虫.clean_content 按域名增补过滤。
# ============================================================
_广告规则缓存 = {}   # domain -> {'关键词': [...], '正则': [compiled...]}


def 获取广告规则(url):
    """按 URL 查询站点级广告增补规则 (未配置返回空规则, 不含内置规则)。

    热重载: reload_runtime_config() → _执行重放 末尾清空本缓存, 下次查询重建。
    非法正则编译失败只告警跳过 (不让一条坏配置打断抓取)。
    """
    _apply_runtime_config()
    load_adapters()
    pat = get_site_pattern(url)
    domain = ''
    if pat:
        domain = pat.get('domain', '')
    else:
        try:
            from urllib.parse import urlparse
            domain = urlparse(url or '').netloc.lower()
        except Exception:
            domain = ''
    if not domain:
        return {'关键词': [], '正则': []}
    if domain in _广告规则缓存:
        return _广告规则缓存[domain]
    规则 = {'关键词': [], '正则': []}
    ad = (pat.get('ad_rules') if pat else None) or {}
    kws = ad.get('关键词')
    if isinstance(kws, list):
        规则['关键词'] = [str(k) for k in kws if k]
    rxs = ad.get('行正则')
    if isinstance(rxs, list):
        for rx in rxs:
            try:
                规则['正则'].append(re.compile(str(rx)))
            except Exception as e:
                try:
                    _log.info(f"[广告规则] 域 {domain} 非法正则已跳过: {rx!r} ({e})")
                except Exception:
                    pass  # 日志链路兜底
    _广告规则缓存[domain] = 规则
    return 规则


# ============================================================
# 运行时配置合并: 站点配置.json (GUI 站点管理页写入) 覆盖/追加内置配置
# ============================================================
_RUNTIME_APPLIED = False
_RUNTIME_APPENDED = set()   # 由 JSON 追加 (非内置) 的域名, 重载时先移除防重复
# G-M3 (GUI 专项审查): 重放全程持 RLock。防两类竞态:
#   ① 两个调用方并发重放 → _RUNTIME_APPENDED 记账交错, 追加条目重复/丢失且
#      持续到重启 (真实损害);
#   ② 重放中途被并发 get_site_pattern 读到中间态 (enabled 标志短暂丢失等) ——
#      该残留窗口为微秒级且自愈, 读侧仍无锁 (保住抓取热路径零开销), 属已接受的
#      弱一致性。
_重载锁 = threading.RLock()


def _apply_runtime_config():
    """把 BASE_DIR/站点配置.json 合并进 SITE_PATTERNS (按域名 upsert)。

    - 同域名: 用 JSON 字段覆盖内置条目 (函数型字段如自定义分页不受影响)
    - 新域名: 追加到列表末尾
    - enabled=False: 保留条目但 get_site_pattern 跳过 (可随时重新启用)
    - 任何异常静默降级 (仅用内置配置), 不影响爬虫主流程

    H7 修复: 支持 reload_runtime_config() 强制重放 —— 旧实现 _RUNTIME_APPLIED
    一次性置位后, GUI 站点管理页的启用/禁用与新增在当前进程内永不生效。
    """
    global _RUNTIME_APPLIED
    if _RUNTIME_APPLIED:
        return
    with _重载锁:
        if _RUNTIME_APPLIED:    # 双检: 并发进入只重放一次
            return
        _执行重放()


def _执行重放():
    """(须持 _重载锁) 重放本体: 记账/复位/upsert 全部在此 (竞态说明见 _重载锁)"""
    global _RUNTIME_APPLIED, _RUNTIME_APPENDED
    # 重放前先移除上次由 JSON 追加的域名条目 (覆盖型条目会被再次覆盖, 无需移除)
    if _RUNTIME_APPENDED:
        SITE_PATTERNS[:] = [p for p in SITE_PATTERNS
                            if p.get('domain') not in _RUNTIME_APPENDED]
        _RUNTIME_APPENDED = set()
    # H4 修复: 重放前先复位内置条目上的 enabled 标志 — 场景: 用户先禁用内置站
    # (enabled=False 被 upsert 进内置条目) 再从 JSON 删除该站点, 重放若不复位,
    # 该站将保持禁用至重启, 与 GUI"内置站点将回退默认配置"的提示相悖。
    # 复位后由下方 JSON upsert 重新施加 JSON 中声明的 enabled (若有)。
    # 此时 _RUNTIME_APPENDED 条目已被移除, 剩余全部是内置条目。
    for _p in SITE_PATTERNS:
        _p.pop('enabled', None)
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
                _RUNTIME_APPENDED.add(domain)
    except Exception as _e:
        # 运行时配置加载失败 → 静默使用内置配置
        try:
            _log.info(f"[sites_config] 运行时站点配置加载失败, 使用内置配置: {_e}")
        except Exception:
            pass  # 刻意静默: 日志链路兜底: try 体在写日志 (热重放告警), 再加日志会递归
    # 广告规则编译缓存失效 (站点级 ad_rules 热重载刷新点, 须在持锁内)
    _广告规则缓存.clear()


def reload_runtime_config():
    """强制重放 站点配置.json 运行时合并 (H7)。

    GUI 站点管理页保存/切换启用开关后调用, 使改动在当前进程内立即生效
    (无需重启程序)。

    G-M3: 复位+重放整体持 _重载锁 —— 若锁外只复位标志, 与并发重放的收尾
    置位交错会导致本次保存被双检误判"已应用"而跳过。
    """
    with _重载锁:
        global _RUNTIME_APPLIED
        _RUNTIME_APPLIED = False
        _apply_runtime_config()


# ============================================================
# 外部站点适配器插件: BASE_DIR/站点适配/*.py (免重新打包扩展新站)
# ============================================================
ADAPTERS = {}          # domain -> {'source', 'parse_catalog', 'extract_content', 'paginate'}
_ADAPTER_APPENDED = set()  # 适配器 _merge_site_pattern 追加进 SITE_PATTERNS 的域名
                           # (覆盖型域名不入 — 语义与 JSON 覆盖内置条目一致)
_ADAPTERS_LOADED = False


def load_adapters():
    """加载站点表/提取器/适配器插件 (幂等)。

    加载顺序 (后者按域名 upsert 覆盖前者):
      1. 站点适配_本地/站点表.json —— 内置站点表 (_load_site_table, 不入库;
         目录缺失 = 公开仓库形态, 静默跳过)
      2. 站点适配/ *.py —— 公开侧适配器插件 (占位模板以 _ 开头, 自动跳过)
      3. 站点适配_本地/ *.py —— 真实站点适配器 (不入库)
      附: 站点适配_本地/_提取器.py —— 站点专属提取器注册进 _EXTRACTORS

    每个适配器文件（一个站点一个 .py）可暴露:
      - SITE (dict, 可选): 站点配置，字段同 站点配置.json
          (domain/pattern/catalog_parser/chapter_url_regex/content_pagination/
           content_selectors/content_extractor/anti_spider 等)。
          按域名 upsert 进 SITE_PATTERNS（仅内存使用，不写入 站点配置.json）。
      - parse_catalog(soup, catalog_url, base_url, **kw) -> list[dict] | None
          返回 [{'title':..., 'url':...}]；返回 None 表示走通用/内置解析。
          kw 提供 sort_chapters / fetch(抓取额外目录页的回调)。
      - extract_content(soup, page_url, base_url, **kw) -> str | None
          返回正文字符串；返回 None 表示走通用/内置提取。
          kw 提供 page_index。
      - paginate(current_url, page_index, **kw) -> str | None
          返回下一页 URL（相对路径自动补全）；返回 None 表示停止分页。
      - catalog_from_chapter(chapter_url, base_url=None) -> str | None
          章节页 URL → 目录页 URL 的纯字符串推导（不发请求）；返回 None
          表示无法推导。供通用层在目录解析前把用户误当任务 URL 的章节页
          规范化到目录页 (resolve_catalog_from_chapter)。

    安全提示: 这些 .py 文件会被 import 执行，等同直接运行代码，
    请只放入可信来源的适配器（信任级别与修改主程序代码一致）。
    """
    global _ADAPTERS_LOADED, ADAPTERS, _ADAPTER_APPENDED
    if _ADAPTERS_LOADED:
        return
    # 站点脱钩: 先加载外置站点表与站点专属提取器 (目录缺失 = 公开形态, 各自静默)
    _load_site_table()
    _register_extractors()
    new_adapters = {}
    try:
        from _path_utils import get_app_base_dir
        _base = get_app_base_dir()

        def _scan_dir(dir_name):
            """列出一个适配器目录的待加载 .py (跳过 _ 开头, 如占位模板)"""
            d = os.path.join(_base, dir_name)
            if not os.path.isdir(d):
                return []
            return [(f, os.path.join(d, f))
                    for f in sorted(os.listdir(d))
                    if f.endswith('.py') and not f.startswith('_')]

        # 双目录: 公开侧 站点适配/ + 本地侧 站点适配_本地/ (站点脱钩, 不入库)。
        # 同域名两文件并存时先到先得 (公开侧在前), 后到者在下方 L3 检查处告警跳过。
        for fname, path in _scan_dir("站点适配") + _scan_dir("站点适配_本地"):
            try:
                mod = _import_adapter_module(path, fname[:-3])
                site = getattr(mod, 'SITE', None)
                domain = ''
                if isinstance(site, dict) and site.get('domain'):
                    domain = str(site['domain']).strip()
                    # 站点脱钩 Wave 2: 允许适配器**只登记 parse_catalog 而不并入 SITE_PATTERNS**。
                    # 为什么需要: 有些站点原先没有任何站点表条目, 走的是
                    # `get_site_pattern() -> None`; 若给它 upsert 一个最小条目,
                    # get_site_pattern() 就变成真值, 会改变 `if 站点配置:` 类分支的行为。
                    # 声明 `SITE = {'domain': …, '仅注册解析器': True}` 即跳过合并 →
                    # 行为与原内置解析器**完全一致**。(字段缺省 = 原行为, 向后兼容)
                    if site.get('仅注册解析器'):
                        _log.info(f"[适配器] {fname}: 仅注册解析器, 不并入站点表")
                    else:
                        _merge_site_pattern(site)
                if not domain:
                    _log.info(f"[适配器] 跳过 {fname}: 未定义 SITE['domain']")
                    continue
                # L3 修复: 同域名第二个插件文件会产生"B 的配置 + A 的函数"缝合体,
                # 显式拒绝并告警 (提示改插件文件里的 SITE['domain'])
                if domain in new_adapters:
                    _log.info(f"[适配器] 跳过 {fname}: 域名 {domain} 已由其他插件注册, "
                              f"请修改该插件的 SITE['domain']")
                    continue
                entry = {
                    'source': path, 'parse_catalog': None,
                    'extract_content': None, 'paginate': None,
                    'get_title': None, 'catalog_from_chapter': None,
                }
                for attr in ('parse_catalog', 'extract_content', 'paginate',
                             'get_title', 'catalog_from_chapter'):
                    fn = getattr(mod, attr, None)
                    if callable(fn):
                        entry[attr] = fn
                # H7 回归修复: entry 必须登记进注册表 — 旧代码经 setdefault
                # 注册, H7 重载重构时赋值被丢, 适配器"已加载"但注册表恒空,
                # get_adapter() 永远返回 None (爬虫不走适配器 + GUI 显示
                # "加载失败或未注册")
                # M3: 先写进本地新表, 扫描完成后整体换引用 (原子, 无并发空窗)
                new_adapters[domain] = entry
                # 注意: setdefault 的默认字典不含 get_title, 适配器未定义书名
                # 函数时该键不存在, 必须用 .get 访问 (旧代码直接索引导致
                # "加载 适配器文件 失败: 'get_title'" 的误报)
                _log.info(f"[适配器] 已加载 {fname} → {domain} "
                          f"(目录={'✓' if entry.get('parse_catalog') else '✗'} "
                          f"正文={'✓' if entry.get('extract_content') else '✗'} "
                          f"分页={'✓' if entry.get('paginate') else '✗'} "
                          f"书名={'✓' if entry.get('get_title') else '✗'})")
            except Exception as e:
                _log.info(f"[适配器] 加载 {fname} 失败: {e}")
    except Exception as e:
        _log.info(f"[适配器] 扫描目录失败: {e}")
        return  # M3: 扫描级失败不置位, 下次调用重试 (旧实现先置位, 失败后永不重试)
    # M3: 构建完成后整体换引用 (旧实现逐条写入 ADAPTERS / reload 先清空后重建,
    # 均存在并发空窗 — 空窗期 get_adapter 返回 None, 抓取中的任务静默降级通用
    # 解析)。get_adapter 每次调用读取模块属性, 换引用原子生效。
    ADAPTERS = new_adapters
    _ADAPTERS_LOADED = True
    # 清理已被删除的适配器此前追加进 SITE_PATTERNS 的站点条目
    # (覆盖型条目保留: 语义与 JSON 覆盖内置条目一致)
    _残留 = _ADAPTER_APPENDED - set(new_adapters)
    if _残留:
        SITE_PATTERNS[:] = [p for p in SITE_PATTERNS
                            if p.get('domain') not in _残留]
        _ADAPTER_APPENDED -= _残留


# ============================================================
# 站点脱钩 (2026-10-01): 外置站点表 + 站点专属提取器注册
# 公开仓库形态: 站点适配_本地/ 不存在 → 站点表为空、提取器注册表为空,
# 程序正常工作 (仅无内置站点); 本地形态全量加载。详见 AGENTS §目录与文件管理规范 四。
# ============================================================
_LOCAL_TABLE_APPENDED = set()   # 由站点表 JSON 追加的域名 (重载先移除防重复)
_EXTRACTORS = {}                # 提取器机制名 -> 函数(container)->str (本地注册)

# 旧站点名别名 -> 机制名。别名字典本体放 站点适配_本地/_提取器.py (ALIASES,
# 不入库 —— 旧名含站点信息), 由 _register_extractors() 注册; 公开形态为空
# (公开用户无旧配置, 无需兼容)。
_EXTRACTOR_ALIASES = {}


def 解析提取器名(name):
    """旧站点名别名归一为机制名; 未知名原样返回 (开放给主爬虫使用)。"""
    return _EXTRACTOR_ALIASES.get(name, name)


def 提取器已注册(name):
    """机制名是否已有实现 (公开形态下站点专属提取器未注册 → False)。"""
    return name in _EXTRACTORS


def _load_site_table():
    """加载 站点适配_本地/站点表.json, 逐条按域名 upsert 进 SITE_PATTERNS。

    - 目录/文件不存在 (公开仓库形态): 静默跳过
    - 由站点表追加的域名记入 _LOCAL_TABLE_APPENDED, 重载时先移除防重复
      (语义同 _ADAPTER_APPENDED); 覆盖型条目由 JSON 再次覆盖, 无需移除
    - upsert 只更新 JSON 中出现的字段, 函数型分页等机制名引用照常透传
    - 任何异常告警并降级 (只用已加载配置), 不影响调用方
    """
    global _LOCAL_TABLE_APPENDED
    try:
        from _path_utils import get_app_base_dir
        path = os.path.join(get_app_base_dir(), "站点适配_本地", "站点表.json")
        if not os.path.isfile(path):
            return
        import json as _json
        with open(path, 'r', encoding='utf-8') as f:
            data = _json.load(f)
        items = data.get('sites') if isinstance(data, dict) else data
        if not isinstance(items, list):
            return
        if _LOCAL_TABLE_APPENDED:
            SITE_PATTERNS[:] = [p for p in SITE_PATTERNS
                                if p.get('domain') not in _LOCAL_TABLE_APPENDED]
            _LOCAL_TABLE_APPENDED = set()
        by_domain = {p.get('domain'): p for p in SITE_PATTERNS}
        for item in items:
            if not isinstance(item, dict):
                continue
            domain = str(item.get('domain', '')).strip()
            if not domain:
                continue
            if domain in by_domain:
                for k, v in item.items():
                    by_domain[domain][k] = v
            else:
                SITE_PATTERNS.append(dict(item))
                by_domain[domain] = SITE_PATTERNS[-1]
                _LOCAL_TABLE_APPENDED.add(domain)
        _log.info(f"[站点表] 已加载 {len(items)} 条内置站点 (站点适配_本地/站点表.json)")
    except Exception as e:
        _log.info(f"[站点表] 加载失败, 使用现有配置: {e}")


def _register_extractors():
    """从 站点适配_本地/_提取器.py 注册站点专属提取器 (文件缺失=公开形态, 跳过)。"""
    try:
        from _path_utils import get_app_base_dir
        path = os.path.join(get_app_base_dir(), "站点适配_本地", "_提取器.py")
        if not os.path.isfile(path):
            return
        mod = _import_adapter_module(path, "_提取器")
        table = getattr(mod, 'EXTRACTORS', None)
        if isinstance(table, dict) and table:
            _EXTRACTORS.clear()
            _EXTRACTORS.update(table)
            _log.info(f"[提取器] 已注册 {len(table)} 个站点专属提取器")
        aliases = getattr(mod, 'ALIASES', None)
        if isinstance(aliases, dict) and aliases:
            _EXTRACTOR_ALIASES.clear()
            _EXTRACTOR_ALIASES.update(aliases)
            _log.info(f"[提取器] 已注册 {len(aliases)} 条旧名别名")
    except Exception as e:
        _log.info(f"[提取器] 注册失败: {e}")


def _import_adapter_module(path, mod_name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(f"site_adapter_{mod_name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _merge_site_pattern(site):
    """把适配器 SITE 按域名 upsert 进 SITE_PATTERNS, 返回合并后的条目。

    追加型 (SITE_PATTERNS 中不存在) 的域名记入 _ADAPTER_APPENDED,
    供 load_adapters 在插件被删除后清理残留条目。"""
    global _ADAPTER_APPENDED
    domain = site.get('domain')
    for p in SITE_PATTERNS:
        if p.get('domain') == domain:
            for k, v in site.items():
                p[k] = v
            return p
    SITE_PATTERNS.append(dict(site))
    _ADAPTER_APPENDED.add(domain)
    return SITE_PATTERNS[-1]


def get_adapter(url_or_domain):
    """按域名匹配外部适配器登记 (先精确后子串), 未命中返回 None"""
    load_adapters()
    key = (url_or_domain or '').lower()
    if key in ADAPTERS:
        return ADAPTERS[key]
    for d, entry in ADAPTERS.items():
        if d and d in key:
            return entry
    return None


def resolve_catalog_from_chapter(url, base_url=None):
    """章节页 URL → 目录页 URL (适配器可选能力 catalog_from_chapter)。

    用户常把章节页 URL 当任务 URL; 若适配器声明了 catalog_from_chapter
    (纯字符串推导, 不发请求), 返回推导出的目录页 URL; 无法推导 (非章节页 /
    适配器未声明 / 推导异常) 时返回 None, 调用方按原 URL 继续。
    """
    try:
        adapter = get_adapter(url)
    except Exception:
        return None
    if not adapter:
        return None
    fn = adapter.get('catalog_from_chapter')
    if not callable(fn):
        return None
    try:
        return fn(url, base_url)
    except Exception as e:
        _log.info(f"[适配器] catalog_from_chapter 异常: {e}")
        return None


def reload_adapters():
    """重置并重新加载 站点适配/ 插件 (GUI 刷新 / 新增文件后用)。

    适配器模块经 module_from_spec 加载且从不注册 sys.modules (L3: 清理
    sys.modules 的旧逻辑是死代码, 已移除), 直接重扫目录即可。
    M3: 旧实现先 ADAPTERS = {} 再重扫, 空窗期并发 get_adapter 返回 None →
    抓取中的任务静默降级通用解析; 现 load_adapters 内部构建新表后原子换引用,
    重载全程无空窗。"""
    global _ADAPTERS_LOADED
    _ADAPTERS_LOADED = False
    load_adapters()


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

    # ---- 自定义函数型 (机制名引用, 见 _PAGINATION_FUNCTIONS) ----
    if pagination.get('type') == 'function':
        if page_index >= pagination.get('max_pages', 30):
            return None
        fn = pagination.get('function')
        # 站点表.json 外置形态: function 以机制名字符串引用注册表;
        # 内存/旧配置形态: 直接是函数对象 (双兼容)。
        if isinstance(fn, str):
            fn = _PAGINATION_FUNCTIONS.get(fn)
        if not callable(fn):
            return None
        return fn(base_url, page_index)

    # ---- 序号递增型 ----
    if pagination.get('type') == 'increment_number':
        if page_index >= pagination.get('max_pages', 10):
            return None
        m = re.search(r'(\d+)\.html$', base_url)
        if not m:
            return None
        num = int(m.group(1)) + page_index
        return re.sub(r'\d+\.html$', f'{num}.html', base_url)

    # L2 修复: start 用 .get 兜底 (GUI 新增/JSON 导入的配置可能缺该键,
    # 旧实现直接 ['start'] 会 KeyError 使整章分页失败)
    page_num = pagination.get('start', 1) + page_index - 1
    if page_num > pagination.get('max_pages', 30):
        return None
    # 缺 suffix 的配置 (GUI 新增/JSON 导入, 如只配 max_pages 的单页站点)
    # 视为无翻页能力, 返回 None 而非 KeyError (调用点无 try 保护)
    suffix = pagination.get('suffix')
    if not suffix:
        return None
    # 查询参数模式 (如 ?page={N}): 直接追加到 URL 末尾, 不替换 .html
    # 用于以 ?page=N 查询参数翻页的站点
    if '?' in suffix:
        return f"{base_url}{suffix.replace('{N}', str(page_num))}"
    # 路径替换模式 (如 _{N}.html): 替换 .html 为分页后缀
    suffix = suffix.replace('{N}', str(page_num))
    return base_url.replace('.html', suffix)


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
        # 变体 (2026-10-01, siteI 类): 同构调用但函数名随机化 ——
        # document.writeln(随机对象.随机方法('BASE64'))。{32,} 长度阈值防误捕
        # 页面上无关的短 base64 (如图标/占位)。
        blocks = re.findall(
            r"document\.writeln\([\w.$]+\('([A-Za-z0-9+/=]{32,})'\)\)", html)
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
    """两步 AJAX 动态加载正文获取
    
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


def extract_content_html_selector(html, selectors, extractor=None, domain=''):
    """通过 BeautifulSoup 选择器提取正文

    Args:
        html: 原始页面 HTML
        selectors: 选择器列表, 按优先级依次尝试
        extractor: 专用提取器机制名 (可选, 实现见 _EXTRACTORS 注册表;
            旧站点名别名经 _EXTRACTOR_ALIASES 归一)
        domain: 站点域名 (可选, 批3 PoC-A)。选择器全部落空时触发选择器自愈,
            产出**待审建议** (数据/选择器建议.json)。不自动改配置、不影响
            本函数返回值与下方兜底逻辑; 自愈异常一律旁路, 绝不断主流程。

    Returns:
        正文文本
    """
    soup = BeautifulSoup(html, 'lxml')
    # 旧站点名别名归一 (兼容既有 站点配置.json / 站点表 里的旧 content_extractor 值)
    extractor = _EXTRACTOR_ALIASES.get(extractor, extractor)
    for sel in selectors:
        el = soup.select_one(sel)
        if not el:
            continue
        # 站点专属提取器经注册表分发 (实现在 站点适配_本地/_提取器.py, 不入库);
        # 未注册 (公开形态) 时跳过, 走通用 get_text 路径。
        fn = _EXTRACTORS.get(extractor)
        if fn is not None:
            text = fn(el)
            if text:
                return text
        text = el.get_text('\n', strip=True)
        if len(text) > 200:
            return text
    # ===== 批3 PoC-A: 规则选择器全部落空 -> 自愈重定位 (只产出待审建议, 方案A) =====
    # 下方"最长文本容器"兜底仍照旧返回, 本次抓取行为零变化; 建议由人工审核后
    # 才并入 站点配置.json。自愈任何异常一律旁路 (只留痕), 绝不断主流程。
    if domain:
        try:
            import 选择器自愈
            选择器自愈.try_heal(soup, domain, selectors)
        except Exception as _e:
            _log.debug(f'裸 except 吞异常: {type(_e).__name__}: {_e}')
    # 兜底: 找最长文本容器
    # get_text('\n') 保留标签间换行: strip=True 无 separator 会把整章压成一行
    # (分段丢失根因②, 下游 clean_content 无法还原段落)
    candidates = []
    for el in soup.find_all(True):
        text = el.get_text('\n', strip=True)
        if len(text) > 500:
            candidates.append((len(text), text))
    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
    return ''


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
        if len(text) <= 100:
            # 批3 任务3: 提取为空 ≠ 无事发生 —— 探测"解密函数名轮换"线索
            # (如 qsbs.bb 改名), 产出 类型=加密变更 的待审建议供人工适配。
            # 旁路: 线索探测任何异常不得影响本分支返回。
            try:
                import 选择器自愈
                选择器自愈.加密变更线索(html, pattern.get('domain', ''))
            except Exception as _e:
                _log.debug(f'裸 except 吞异常: {type(_e).__name__}: {_e}')
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
            domain=pattern.get('domain', ''),
        )
        return text, len(text) > 100
    
    else:
        return '', False
