# -*- coding: utf-8 -*-
"""目录链接判定工具 (2026-10-14 阶段二从 爬虫.py 拆出, 纯函数零行为变化)。

拆分原则: **原样搬迁 + 显式 import 桥接** —— 爬虫.py 删除本组定义,
`from 目录链接工具 import (...)` 引入, 全部既有调用点与测试导入路径不变。

为什么先拆这组: 它们是"链接收集"的判定核心 (非章节页/章节链接/站点正则),
纯函数、无实例状态依赖, 是爬虫.py 里边界最清晰、风险最低的第一刀。
拆分验证: 脚本/解析基线.py --对比 必须与入库基线一致。
"""
import re

try:
    from 日志 import get as _取日志
    _log = _取日志('目录链接工具')
except Exception:
    import logging
    _log = logging.getLogger('目录链接工具')


def _非章节页名() -> tuple:
    """目录页里"看着像章节、其实是导航/功能区"的链接特征 (2026-10-08 实网取证)。

    实网: <站点> 的「[寻找更多新章] -> /<书号>/liked.html」通过了 `novel_path in href`
    过滤被当成章节抓 → **正文为空、质检 0 分, 还占掉一个章节号**, 于是
    "抓取失败章节号 (1): [1]" 这种误导性报告就出来了 (实抓日志逐字可见)。

    只收**确定不是章节**的页名, 不用"必须纯数字"这类激进规则 —— 后者会误伤
    `chapter-123.html` / 拼音 slug 等正当写法。
    """
    return ('/ch1.html', '/dx1.html', '/index.html', '/indexlist.html',
            '/liked.html', '/bookcase.html', '/comment.html', '/about.html')


def _是非章节链接(href: str, 含index前缀: bool = False) -> bool:
    """统一收口: 该链接是否为"非章节页"(目录/书架/评论/关于/首页列表等)。

    2026-10-10 (E1): 原先 3 处各写一遍 `any(k in href for k in _非章节页名())`,
    其中一处还额外拼了 `['/index_']` —— 改词表时容易漏改一处, 口径会漂移
    (实测就漏过一次: `liked.html` 曾从某个选择器分支被当章节抓)。
    """
    if any(k in href for k in _非章节页名()):
        return True
    return bool(含index前缀 and '/index_' in href)


def _章节链接合正则(href: str, 站点正则: str) -> bool:
    """站点表声明了 `chapter_url_regex` 时, 章节链接**必须**匹配它 (2026-10-13)。

    **为什么要它**: `chapter_url_regex` 在 `sites_config.py` 有文档、在站点管理页可编辑,
    但**爬虫从不读取**(实测全源码 0 处使用) ⇒ 这个字段一直是**死配置**: 站点明明声明了
    自己章节 URL 的形状, 通用筛选却只靠弱启发式(路径前缀 + 词表) ⇒ 目录页里的
    **导航位/外站链接**只要路径前缀凑得上, 就会被当章节收下。

    口径 (安全方向):
      - **未配置** → 一律放行 ⇒ 与改造前行为**完全一致** (18 个已配置站受益, 其余无变化);
      - 配了 → `re.search` 命中才放行;
      - 正则**写坏了** → 放行并留痕 (不能因为一个坏正则让整站抓不动)。
    """
    if not 站点正则:
        return True
    try:
        return bool(re.search(站点正则, href))
    except re.error as e:
        _log.warn(f"[目录解析] 站点表 chapter_url_regex 非法 ({e}), 本次放行: {站点正则[:40]}")
        return True


# ---- 目录判定与折叠站自救 (2026-10-14 阶段二批 2 追加) ----

# 折叠站"完整目录"入口的候选特征 (2026-10-12 折叠自救)
完整目录_文本 = ('全部章节', '全部章节目录', '查看全部', '完整目录', '全部目录',
              '章节目录', '展开全部', '查看更多章节', '完整章节', '目录列表')
完整目录_href = ('indexlist', 'allchapter', 'chapterlist', 'all.html', '/mulu',
              'mulu.', 'list_all', 'full_list', 'alllist')


def _找完整目录链接(soup, catalog_url: str) -> str:
    """在目录页里找"完整目录/全部章节"入口, 返回绝对 URL; 找不到返回 ''。

    **为什么要它** (2026-10-12 真机实测倒逼): 折叠站只把**头尾若干章**放在目录页,
    中间章节收进"全部目录"子页/分页 —— 实测某站页面自述**另有约 126 章未展示**,
    而程序此前只会**告警**, 让用户自己去找那个入口。

    判定: 锚文本命中常见措辞, **或** href 命中目录类特征 (很多站入口文字写"更多")。
    安全: 只接受 http(s) 绝对化后的链接 (跳过 `javascript:`/`#`/`mailto:`),
    跳过指回当前页自身的链接; **同域优先** (跨域入口多半是推荐位)。
    """
    候选 = []
    try:
        from urllib.parse import urljoin, urlsplit
        当前 = urlsplit(catalog_url or '')
        当前键 = (catalog_url or '').rstrip('/')
        for a in soup.find_all('a', href=True):
            文本 = (a.get_text(strip=True) or '')
            href = (a.get('href') or '').strip()
            if not href or href.startswith(('javascript:', '#', 'mailto:', 'tel:')):
                continue
            绝对 = urljoin(catalog_url or '', href)
            分 = urlsplit(绝对)
            if 分.scheme not in ('http', 'https') or not 分.netloc:
                continue
            if 绝对.rstrip('/') == 当前键:
                continue                      # 指回本页 → 无意义
            命中文本 = any(t in 文本 for t in 完整目录_文本)
            命中链接 = any(h in 绝对.lower() for h in 完整目录_href)
            if not (命中文本 or 命中链接):
                continue
            # 排序键: 同域优先 → 文本命中优先 → 先出现者
            候选.append((0 if 分.netloc == 当前.netloc else 1,
                       0 if 命中文本 else 1, len(候选), 绝对))
    except Exception as e:  # noqa: BLE001 — 必须留痕
        _log.debug(f'裸 except 吞异常: {type(e).__name__} (完整目录入口查找)')
    if not 候选:
        return ''
    候选.sort(key=lambda x: (x[0], x[1], x[2]))
    return 候选[0][3]


def _目录列表可疑(章节列表) -> str:
    """目录解析结果"看着不对"的廉价判据 (2026-10-12); 返回原因字符串, 正常返回 ''。

    **为什么需要它** (真机实测倒逼): 有些站点把**别的书的推广章链接**混在目录页里, 而它的
    href 形态与真章节**完全一致** —— 实测推广链 `/read/<书号>/671592.html` vs 真第 1 章
    `/read/<书号>/3980.html`, 通用链接筛选会把推广链**排在真章节前面**收下, 于是抓回来的是
    "本章未完, 点击下一页继续阅读"的空壳页, 正文只剩几十字节。
    这类"结果不对"**用章节数根本发现不了**(数出来一大把), 故补此判据, 作为
    折叠自救(`_折叠自救`)的**第二个触发条件**。

    判据 (任一成立即可疑; 刻意保守, 避免给正常站点多抓一页):
      ① 空列表;
      ② **同一 URL 重复 ≥3 次** —— 推广位/导航位常被重复渲染;
      ③ **首个章节号 ≥ 10× 列表中位数** —— "推广链挂最前"的典型签名
         (真第 1 章号最小, 推广链号大得多)。
    """
    try:
        章节列表 = [c for c in (章节列表 or []) if isinstance(c, dict)]
        if not 章节列表:
            return '目录解析结果为空'
        from collections import Counter
        计数 = Counter(str(c.get('url') or '') for c in 章节列表)
        最重复网址, 次 = 计数.most_common(1)[0]
        if 次 >= 3:
            return (f'同一章节 URL 重复 {次} 次 (疑似推广位/导航位混入): '
                    f'{最重复网址[:60]}')
        号s = []
        for c in 章节列表:
            m = re.search(r'/(\d+)(?:_\d+)?\.html', str(c.get('url') or ''))
            if m:
                号s.append(int(m.group(1)))
        if len(号s) >= 4:
            首 = 号s[0]
            中位 = sorted(号s)[len(号s) // 2]
            if 中位 > 0 and 首 >= 中位 * 10:
                return f'首个章节号 {首} 远大于中位数 {中位} (疑似推广链排在真章节之前)'
    except Exception as e:  # noqa: BLE001 — 必须留痕
        _log.debug(f'裸 except 吞异常: {type(e).__name__} (目录列表可疑判据)')
    return ''


def _剔除非章节单条(章节列表) -> tuple:
    """B 修法 (2026-10-13): 单条级过滤 — 剔"章节号孤立异常大"的可疑链接。

    与 A (`_目录列表可疑` → 折叠自救) **互补而非重复**:
      A 是整表级 —— 判据成立就触发自救 (重新找完整目录入口重解析);
      B 是单条级 —— 不重解析, 只把明显异常的单条剔掉。
    A 覆盖不到、由 B 兜底的场景: 推广链只有一两条 (不满足 A 的"重复≥3")、
    推广链不在最前 (A 只看首个)、A 自救失败或自救后仍有残留 —— 这时至少
    把异常条剔掉, 让真第 1 章露出来。

    判据 (刻意保守, 与 A 同阈值, 保证行为一致):
      单条章节号 ≥ 10× 列表中位数 且 剔除后列表非空。
    **宁不错杀**: 全部条目都异常时原样返回 (不动), 避免把真目录清空。

    Returns:
        (清洗后列表, 剔除条数, 原因字符串); 无需剔除时原样返回 (列表, 0, '')。
    """
    try:
        章节列表 = [c for c in (章节列表 or []) if isinstance(c, dict)]
        if len(章节列表) < 4:
            return 章节列表, 0, ''
        号s = []
        for c in 章节列表:
            m = re.search(r'/(\d+)(?:_\d+)?\.html', str(c.get('url') or ''))
            号s.append(int(m.group(1)) if m else None)
        有效 = [n for n in 号s if n is not None]
        if len(有效) < 4:
            return 章节列表, 0, ''
        中位 = sorted(有效)[len(有效) // 2]
        if 中位 <= 0:
            return 章节列表, 0, ''
        留, 剔号 = [], []
        for c, n in zip(章节列表, 号s):
            if n is not None and n >= 中位 * 10:
                剔号.append(n)
            else:
                留.append(c)
        if not 剔号:
            return 章节列表, 0, ''
        if not 留:
            # 全异常: 保守不动 (清空真目录比放过推广链更糟)
            return 章节列表, 0, '全列表章节号均异常, 保守不剔除 (宁不错杀)'
        return 留, len(剔号), (f'剔除章节号 {剔号[:3]} (≥10× 中位数 {中位})')
    except Exception as e:  # noqa: BLE001 — 必须留痕
        _log.debug(f'裸 except 吞异常: {type(e).__name__} (剔除非章节单条)')
        return (章节列表 or []), 0, ''


def _目录折叠提示(soup, 解析章数):
    """目录折叠站检测 (2026-10-09 首版; 2026-10-13 改判据): 页面宣称章节总数
    远大于实际解析数时告警。

    背景: 天秋类站点目录页只展示首尾章节 (如"点击查看中间隐藏的【1454】章节"),
    中间章节收进独立分页 (directory_N.html); 把可见链接当全部目录会大量漏抓
    (实测某书仅得 40/1494 章)。仅提示不改抓取行为。

    **2026-10-13 判据修正 (真实快照复核)**: 首版开头有 `if 解析章数 > 60: return
    None` 的早退, 假设"能解析 60+ 章就不算折叠"。实测**真折叠站首页能解析 113 条**
    (宣称 1494 / 首页 113, 漏 1381 章) 却因这条早退**静默** ⇒ 早退条件不成立。
    改为**倍率判据**: 宣称数显著大于解析数才告警 —— 完整展开的站 (宣称≈实际)
    与"宣称 1494 / 实际 113"这种都能正确区分。
    """
    try:
        text = soup.get_text(' ', strip=True)[:20000]
        隐藏 = 0
        宣称 = 0
        m = re.search(r'隐藏的?【?\[?(\d+)】?\]?章节?', text) or \
            re.search(r'隐藏的?(\d+)章', text)
        if m:
            隐藏 = int(m.group(1))
            宣称 = 解析章数 + 隐藏
        else:
            m2 = re.search(r'共\s*(\d+)\s*章', text)
            if m2:
                宣称 = int(m2.group(1))
                隐藏 = max(0, 宣称 - 解析章数)
        if 隐藏 >= max(50, 解析章数 * 2) and (
                宣称 >= 300 or 隐藏 >= 解析章数 * 3):
            return (f'⚠️ 该目录页疑似折叠: 实际解析 {解析章数} 章, 页面提示另有'
                    f'约 {隐藏} 章未展示 (中间章节被站点隐藏或收进分页目录)。'
                    f'建议确认完整目录入口 (如"全部章节目录"链接) 后重试, '
                    f'否则将大量漏抓。')
    except Exception as e:
        _log.debug(f'裸 except 吞异常: {type(e).__name__}: {e} (折叠检测失败不影响主流程)')
    return None


# ---- chromedriver 自动就绪 (需求 #7, 2026-10-13) ----
# 背景: `webdriver.Chrome()` 原先依赖 Selenium 自己找到 chromedriver —— 用户
# 得手动下载并放对位置, 且 Chrome 每次自动升级都可能失配。改为: 首次创建驱动
# 前调 `驱动管理.确保可用()` (检测 Chrome → 匹配版本 → 缺失则下载到程序目录)。
# 懒加载 + 进程级缓存: 一次会话只检测/下载一次, 后续创建直接复用路径。
_驱动路径 = None


# 通用广告行/无意义字符特征 (基于内容特征, 适用于所有小说网站)
# 这些正则模式识别广告/导航/推荐列表的通用结构特征, 不依赖具体书名或站点名

# 结构特征 (对所有行生效, 基于行的整体结构判断)
_AD_LINE_STRUCT_PATTERNS = [
    # 相邻推荐列表: 多个书名以连续空格(3+)分隔, 无中文标点
    # 例: "书名1   书名2   书名3   书名4"
    re.compile(r'^[^\s].*\s{3,}[^\s].*\s{3,}[^\s]'),
    # 纯数字/字母组合 (如章节编号残留、验证码、页码)
    re.compile(r'^[\d\s]{5,}$'),
    # 站点域名行: www.xxx.com 或 m.xxx.com 格式
    re.compile(r'^(www\.|m\.|https?://)[\w\.\-]+'),
    # 纯符号分隔行 (如 "----------" 或 "=========")
    re.compile(r'^[\-\=\*\_]{5,}$'),
]

# 标签特征 (仅对短行 <40 字生效, 避免误伤正文段落)
# 这些模式匹配小说搜索标签、站点宣传语等短行广告
_AD_LINE_TAG_PATTERNS = [
    # "XX小说网" / "XX阅读网" 等站点名后缀 (通用, 不针对具体站点)
    re.compile(r'.{2,8}小说网$'),
    re.compile(r'.{2,8}阅读网$'),
    re.compile(r'.{2,8}文学网$'),
    # "XX最新章节" / "XXtxt下载" 等小说搜索标签
    re.compile(r'.{2,15}最新章节$'),
    re.compile(r'.{2,15}txt下载$'),
    re.compile(r'.{2,15}全文阅读$'),
    re.compile(r'.{2,15}无删减$'),
    re.compile(r'.{2,15}完整版$'),
]

# 站点宣传语通用片段 (跨站点共用, 非具体书名; 仅对短行 <40 字检查)
_AD_PHRASE_FRAGMENTS = (
    '记住本站', '收藏本站', '本站域名', '本站网址', '网址:',
    '请记住', '希望大家收藏', '手机用户', '电脑阅读', '手机阅读',
    '扫描二维码', '手机浏览器扫描',
    '发送任意邮件', '最新地址发送', '获取最新地址',
    '无弹窗', 'txt下载', '全文下载', '无删减',
    '最新章节列表', '刚刚更新', '猜你喜欢', '热门推荐',
    '同类推荐', '相邻推荐', '相关推荐', '推荐阅读',
    '加入书架', '存书签', '章节目录', '返回目录',
    '上一章', '下一章', '上一页', '下一页',
    '本章未完', '点击下一页', '继续阅读',
    '请勿开启浏览器', '阅读模式',
    '创作者：', '创作完成日',
    'Copyright', '版权所有', 'All Rights Reserved',
    # "找不到原站/被屏蔽后引导去新域名"类广告 (多站点模板, 如
    # "最新找回4F4F4F,C〇M" / "网址被屏蔽 请访问 xxx,C0M" — 2026-09 实测某站移动版)
    '最新找回', '地址找回', '网址找回', '原域名', '新域名',
    'C〇M', ',C0M', ',C○M',
)


# ---- 正文清洗 (2026-10-14 阶段二批 3 追加) ----

def _排版章节文本(标题: str, 正文: str, 缩进: bool = True) -> str:
    """单章 TXT 写入格式化: '## 标题' + 段首两个全角空格缩进 + 段间空行。

    中文排版规范: 每段首行缩进两个字符 (\u3000\u3000), 段落间空一行。
    与 EPUB 的 text-indent: 2em (epub_exporter.py) 语义对齐。

    段落切分: 单换行即段落边界 (clean_content 的"每行=每段"语义),
    因此对修复前的旧正文 (单 \\n 分段) 同样能正确重排 —— 增量搬运的
    旧内容经过本函数后与新抓取格式统一。

    Args:
        标题: 章节标题 (写成 '## 标题' 行, 不缩进)
        正文: 清洗后的章节正文
        缩进: False 时不加缩进 (仍保留段间空行)

    Returns:
        str: 直接 f.write 的整块文本
    """
    段落 = [ln.strip() for ln in (正文 or '').split('\n') if ln.strip()]
    if 缩进:
        段落 = ['\u3000\u3000' + p for p in 段落]
    正文块 = '\n\n'.join(段落)
    头 = f"## {标题}\n\n"
    return 头 + (正文块 + '\n\n' if 正文块 else '')


def _读txt缩进配置() -> bool:
    """读 TXT 段首缩进开关 (captcha_config.json 的 'txt_indent' 键, 默认开)。

    captcha_config.json 已兼作应用配置 (代理/浏览器引擎/备用源同此文件),
    该键缺失/类型不符/文件不可读时一律回退 True (符合中文排版默认)。
    """
    try:
        import json as _json
        import _path_utils as _pu
        p = _pu.resolve_data_file('captcha_config.json')
        with open(p, 'r', encoding='utf-8') as f:
            cfg = _json.load(f)
        v = cfg.get('txt_indent')
        return True if v is None else bool(v)
    except Exception as e:
        try:
            _log.debug(f'txt_indent 配置读取失败, 默认开启: {type(e).__name__}: {e}')
        except Exception:
            pass  # 日志链路兜底 (模块初始化早期 _log 可能未就绪)
        return True


def _is_ad_line(line, 额外正则=None):
    """通用广告行/无意义字符检测 (基于内容特征, 不依赖具体书名或站点名)

    识别策略 (分两层, 避免误伤正文):
    1. 结构特征 (对所有行): 连续空格分隔的推荐列表、纯符号行、域名行、纯数字行
    2. 标签特征 (仅对短行 <40 字): 小说搜索标签、站点宣传语片段
    3. 站点级增补正则 (对所有行): 站点配置.json 的 ad_rules.行正则 (2026-09-29)

    正文段落通常 >40 字且含完整中文标点, 不会被误伤。

    Args:
        line: 单行文本 (已 strip)
        额外正则: 站点级增补正则列表 (获取广告规则().正则), 可为 None

    Returns:
        True 表示该行是广告/无意义字符, 应过滤
    """
    if not line:
        return False
    # 1. 结构特征匹配 (对所有行生效)
    for pat in _AD_LINE_STRUCT_PATTERNS:
        if pat.search(line):
            return True
    # 2. 标签特征匹配 (仅对短行 <40 字, 避免误伤正文段落)
    if len(line) < 40:
        for pat in _AD_LINE_TAG_PATTERNS:
            if pat.search(line):
                return True
        for frag in _AD_PHRASE_FRAGMENTS:
            if frag in line:
                return True
    # 3. 站点级增补规则 (对所有行生效; 用户在 站点配置.json 里配置的正则
    #    理应全行匹配, 不做短行限制)
    for pat in (额外正则 or ()):
        try:
            if pat.search(line):
                return True
        except Exception as e:
            _log.debug(f'裸 except 吞异常: {type(e).__name__}: {e} '
                       f'(站点广告正则执行失败, 忽略该规则)')
    return False
