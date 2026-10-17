# -*- coding: utf-8 -*-
"""章节正文清洗 (P3 从 爬虫.py 拆出, 2026-10-17)。

**来历**: C6 Roadmap P3 (清洗模块拆分, 纯重构) —— `爬虫.py` 6858 行里,
清洗相关逻辑 (正文过滤/水印/广告行/拼音替代/排版规范化) 与抓取编排无关,
拆出来获得: 可测性 (纯函数, 无 contextvar/事件副作用) / 可配置性 /
Rust 化端口 (P3 既定收益)。

**零行为变化**: 代码从 爬虫.py **逐字搬移** (仅去类缩进与 `NovelSpider._`
→ `_` 两类机械变换)。爬虫侧保留 `clean_content` 薄壳: 调本模块 `清洗()`,
再设 contextvar + 发 '清洗' 事件 (那两个出口是编排职责, 留在壳层)。

**调用链** (拆后):
    爬虫.NovelSpider.clean_content(content, site_url)   ← 既有入口, 4 处调用点不变
      └─ 内容清洗.清洗(content, site_url) -> (text, stats)   ← 本模块, 纯函数

依赖方向: 本模块 **不 import 爬虫** (避免循环); `_is_ad_line` 来自
目录链接工具 (拆前就在那里); 站点级规则经 sites_config 懒加载 (函数内 try)。
"""
import re

import 日志 as _app_log
from 目录链接工具 import _is_ad_line

_log = _app_log.get('内容清洗')


# 通用正文过滤关键词 (跨站点共用, 内容清洗.清洗 复用)
_CONTENT_FILTER_KEYWORDS = [
    # 导航元素
    '上一章', '下一章', '上一页', '下一页', '章节目录', '保存书签',

    '加入书架', '返回顶部', '首页', '末页', '目录', '书页',
    '本章未完', '本章未完，点击下一页继续阅读', '开始阅读',
    '没有了', '返回书页', '返回目录',
    # 站点宣传语/占位提示 (通用, 跨站点)
    '一秒记住新域名', '三秒记住本站', '请收藏本站', '请记住本站域名',
    '请记住域名', '手机用户请访问', '手机阅读', '电脑阅读',
    '手机版阅读', '本站网址', '网址：www', '网址:www',
    '内容正在更新', '请稍后查看', '免费提供', '在线阅读',
    '希望大家收藏', '无防盗', '转载作品', '网友上传',
    '转载至本站只是为了宣传本书让更多读者欣赏',
    '基于搜索引擎技术为您提供免费阅读无弹窗',
    # 版权/法律声明
    'Copyright', '版权所有', '本站所有内容', '本站所有小说',
    '本站爬虫遵循robots协议', '本站仅对抓取到的内容',
    # 阅读器提示
    '请勿开启浏览器阅读模式',
    # 元信息标记 (siteAA/siteAB 等站点在正文前插入的元数据)
    '创作者：', '创作完成日：', '最新章节txt——',
    '最新章节列表', '刚刚更新',
    # JS 残留 (Base64 解码或渲染失败时的脚本碎片)
    'myJs.', 'bookJs', 'novelspider', 'Add to Chat',
    'document.writeln', 'document.write',
    # 通用阅读引导/广告短语
    '相邻推荐', '相关推荐', '番外+大结局',
    '全文阅读', '免费阅读', 'VIP会员', '退出浏览器',
    '后续内容已被隐藏',
]

# 站点内嵌水印 token (嵌入正文段落内部/段尾, 非整行, 行级过滤抓不到):
# 站点级 token 已外置站点表 watermark_tokens 字段 (站点脱钩 D层),
# clean_content 经 sites_config.获取水印token(site_url) 按域名合并;
# 此处内置为空 —— 公开形态无站点表即无水印清洗, 本地形态行为不变。
_WATERMARK_TOKENS = ()

# 行内 URL/邮箱剥离正则 (clean_content 的 URL 行处理):
# 旧实现"整行含 URL 即删"会误杀含链接的正文行; 现在只剥离 URL 本身,
# 按剩余中文字数判定该行是正文 (保留) 还是纯推广行 (删除)。
# 字符类仅收 URL 合法字符, 不吃粘连的中文 (避免把"xxx.com首页"的中文一起吞掉)。
_行内URL_RE = re.compile(
    r'https?://[A-Za-z0-9.\-]+(?:/[A-Za-z0-9./?#&=%_\-+~]*)?'
    r'|www\.[A-Za-z0-9.\-]+(?:/[A-Za-z0-9./?#&=%_\-+~]*)?'
    r'|\S*@\S*')

# ================================================================
# 拼音替代 / 无意义字符清洗 (模块级, 便于单测)
# ================================================================

# 合法拼音音节表 (无调, 覆盖全部标准组合)
_PINYIN_SYLLABLES = frozenset("""
a o e ai ei ao ou an en ang er yi ya ye yao you yan yin yang yu yun yuan
wu wa wo wai wei wan wen wang weng ba bo bai bei bao ban ben bang beng bi
bie biao bian bin bing bu po pai pao pou pan pen pang peng pi pie piao pian
pin ping pu ma mo mai mei mao mou man men mang meng mi mie miao miu mian
min ming mu fa fo fei fou fan fen fang feng da de dai dei dao dou dan den
dang deng di die diao diu dian ding du duo dui duan dun dong ta te tai tao
tou tan tang teng ti tie tiao tian ting tu tuo tui tuan tun tong na ne nai
nei nao nou nan nen nang neng ni nie niao niu nian nin ning nu nuo nuan
nong nv nue nü la le lai lei lao lou lan lang leng li lia lie liao liu lia
lian lin ling lu luo luan lun long lv lüe lue ga gai gei gao gou gan gen
gang geng gu gua guo guai gui guan gun gong ka kai kao kou kan ken kang
keng ku kua kuo kuai kui kuan kun kong ha hai hei hao hou han hen hang
heng hu hua huo huai hui huan hun hong ji jia jie jiao jiu jian jin jiang
jing ju juan jun jiong qi qia qie qiao qiu qian qin qiang qing qu quan
qiong xi xia xie xiao xiu xian xin xiang xing xu xuan xun xiong zha zhe
zhi zai zei zao zou zan zen zang zeng zhong zhu zhua zhuo zhuai zhui zhuan
zhun cha che chi cai cao cou can cen cang ceng ci cuo cui cuan cun cong
zhu zhai zhao zhou zhan zhen zhang zheng shu shua shuo shuai shui shuan
shun sha she shi shai sao shou shan shen shang sheng sheng re rei rao rou
ran ren rang reng ri ru rua ruo rui ruan run rong er
""".split())

# 常见英文缩写/词白名单 (夹在汉字间也不删)。L5 修复: 补充可被音节
# 切分误伤的常用英文词 (game/name/time 等恰好能切成合法音节组合)
_ALPHA_WHITELIST = frozenset({
    'app', 'api', 'vip', 'svip', 'ok', 'id', 'ip', 'cpu', 'gpu', 'kpi',
    'k歌', '3d', '2d', '4k', '8k', 'hd', 'ai', 'ar', 'vr', 'hr', 'ceo',
    'cba', 'nba', 'gdp', 'dna', 'mba', 'pdf', 'wifi', 'qq', 'kpi',
    # 常见英文词 (可被误切为音节组合)
    'game', 'name', 'time', 'like', 'make', 'take', 'side', 'line',
    'nine', 'home', 'come', 'gave', 'live', 'wine', 'huge', 'page',
    'sale', 'same', 'some', 'code', 'date', 'face', 'gate', 'hate',
    'late', 'lake', 'mine', 'nine', 'none', 'note', 'pine', 'race',
    'rise', 'rose', 'site', 'size', 'tale', 'tile', 'tune', 'type',
    'wide', 'wife', 'wine', 'wipe', 'bone', 'case', 'dose', 'dove',
    'five', 'four', 'gave', 'here', 'hire', 'hope', 'joke', 'lone',
})

_TONE_MAP = str.maketrans('āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ',
                          'aaaaeeeeiiiioooouuuuvvvv')

@staticmethod
def _is_pinyin_noise(s: str) -> bool:
    """纯小写字母段是否为"拼音替代串": 可被完整切分为合法音节序列,
    且至少含一个长度>=2 的音节 (排除 a/e/o 纯单字母堆叠的误伤)。"""
    if s.lower() in _ALPHA_WHITELIST:
        return False
    n = len(s)
    if n < 2 or n > 8:
        return False
    if not s.isalpha() or not s.islower():
        return False
    syl = _PINYIN_SYLLABLES
    # ok[i] = (可切分, 路径上含 >=2 字母音节)
    ok = [(False, False)] * (n + 1)
    ok[0] = (True, False)
    for i in range(1, n + 1):
        for j in range(max(0, i - 6), i):
            prev_ok, prev_long = ok[j]
            if prev_ok and s[j:i] in syl:
                ok[i] = (True, prev_long or (i - j) >= 2)
                break
    return ok[n][0] and ok[n][1]

@staticmethod
def _clean_pinyin_and_noise(content: str) -> str:
    """过滤拼音替代串与无意义字符 (P-内容质量)。

    1. 带声调拉丁字母 (āáǎà...) 出现在字词间 → 站点用拼音替代汉字, 直接删
    2. 夹在汉字/中文标点(允许空格)间的 2-8 位纯小写字母段, 若可完整切分为
       拼音音节且不在英文白名单 → 判定为"汉字被替换成拼音", 连同两侧空格删除
    3. C1 控制符 / 私用区 / U+FFFD 替换符清除
    4. 连续重复标点收敛 (!!!!! -> !!!)
    """
    try:
        # 1) 带声调字母段 (夹在汉字或中文标点间, 允许空格)
        # 注意: 声调字符检查必须用原文 (m.group(0)) —— 若先 translate 成
        # 普通字母再检查, 声调字符已被转换, 纯声调段 (如 āáǎà) 永远漏删
        content = re.sub(
            r'(?<=[\u4e00-\u9fff，。！？；：、])\s*'
            r'[a-zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ]{2,8}'
            r'(?=\s*[\u4e00-\u9fff，。！？；：、])',
            lambda m: '' if any(ch in m.group(0) for ch in 'āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ')
            or _is_pinyin_noise(m.group(0).translate(
                _TONE_MAP)) else m.group(0),
            content)

        # 2) 无声调拼音替代 (支持连续多词如 "ta de"; 连同前后空格删除)
        content = re.sub(
            r'(?<=[\u4e00-\u9fff，。！？；：、 \t])'
            r'[a-z]{2,8}(?:[ \t]+[a-z]{2,8}){0,3}'
            r'(?=[ \t]*[\u4e00-\u9fff，。！？；：、])',
            lambda m: ('' if all(_is_pinyin_noise(w)
                                 for w in m.group(0).split()) else m.group(0)),
            content)

        # 3) 无意义控制/私用字符
        content = re.sub(r'[\u0080-\u009f\ue000-\uf8ff\ufffd]', '', content)

        # 4) 重复标点收敛 (保留最多 3 个)
        content = re.sub(r'([!！?？。…~～])\1{2,}', r'\1\1\1', content)
        content = re.sub(r'  +', ' ', content)
    except Exception as _e:
        _log.debug(f'裸 except 吞异常: {type(_e).__name__}: {_e}')
    return content

def 清洗(content, site_url=None) -> tuple:
    """章节正文清洗 (P3 从 爬虫.clean_content 逐字搬出, 2026-10-17)。

    纯函数: 只算文本与统计, **不碰 contextvar / 不发事件** —— 那两个出口是
    编排职责, 留在 爬虫.clean_content 壳层 (GUI/远控消费不变)。

    Args:
        content: 待清洗正文
        site_url: 章节页 URL (可选)。提供时按域名加载 站点配置.json 的
            ad_rules 站点级广告增补规则 (关键词 + 行正则), 与内置规则合并。

    Returns:
        (清洗后正文, 清洗统计 dict) —— 统计含 原始行数 (分母) 与各删除维度。
    """
    if not content:
        return "", {}

    # 移除零宽/不可见字符 (U+200B 零宽空格 / U+200C ZWNJ / U+200D ZWJ /
    # U+FEFF BOM / U+2060 Word Joiner / U+00AD 软连字符)
    # 部分网站会在正文中插入这些不可见字符用于反爬/水印, 通用清理适用于所有站点
    content = re.sub(r'[\u200b\u200c\u200d\ufeff\u2060\u00ad]', '', content)

    # 拼音替代串与无意义字符清洗 (P-内容质量: 汉字被拼音替换/控制符/重复标点)
    content = _clean_pinyin_and_noise(content)

    # 移除Unicode编码错误乱码
    # 1. 十六进制Unicode转义序列 (如 x6700;x65b0;x627e;x56de;xff14;...)
    # 2. 未解码的编码错误 (如 65294)
    # 这些通常是HTML编码错误或Base64解码残留
    while True:
        old_len = len(content)
        # 移除十六进制Unicode转义序列 (xHHHH;xHHHH;...格式)
        content = re.sub(r'x[0-9a-fA-F]{4}(?:;x[0-9a-fA-F]{4})*', '', content)
        # 移除未解码的数字乱码 (单个数字或短数字串)
        content = re.sub(r'\b\d{4,}\b', '', content)
        if len(content) == old_len:
            break

    # 移除反爬干扰串: 部分站点 (如 siteAK) 会在正文中随机插入
    # "字母+数字"混合短串作为水印 (如"给体0N肏烂了"中的"0N")。
    # 规则: 直接夹在两个汉字之间的 2-4 位"含数字且含字母"的混合串 → 删除。
    # 白名单保护正常词汇 (如 "5G时代"/"3D眼镜"); 纯字母串 (SPA/NBA/RBQ) 与
    # 纯数字串 (1999年) 天然不被匹配, 无需担心误删。
    _JUNK_WHITELIST = {'3d', '5g', '4g', '2g', '2k', '4k', '8k', '3s', 't恤', 'vip', 'ok', 'app', 'api'}
    content = re.sub(
        r'(?<=[\u4e00-\u9fff])([A-Za-z0-9]{2,4})(?=[\u4e00-\u9fff])',
        lambda m: m.group(0) if (
            m.group(1).lower() in _JUNK_WHITELIST
            or m.group(1).isdigit()
            or m.group(1).isalpha()
        ) else '',
        content)

    # 修复HTML实体（Base64解码后可能残留的实体名称）
    html_entities = {
        'ldquo': '"', 'rdquo': '"', 'lsquo': "'", 'rsquo': "'",
        'hellip': '…', 'mdash': '—', 'ndash': '–', 'nbsp': ' ',
        'middot': '·', 'bull': '•', 'amp': '&', 'lt': '<', 'gt': '>',
    }
    for entity, char in html_entities.items():
        content = content.replace(f'&{entity};', char)

    # 清洗统计 (2026-09-29 可观测性): 各删除类型的行数累计,
    # 函数末尾经 contextvar 供 _fetch_with_qc 附加进质检报告 + 发布事件
    # 2026-10-17 (C6/P1): 加 '原始行数' (非空行) 作**分母** ——
    # 只有删除计数没有总量, 就算不出"删除行占比", 过度清洗告警无从谈起。
    # 口径: 非空行 (空行不参与删除判定, 计入会稀释占比); 水印是字符级
    # 替换计数、不是行, **不计入删除行分子** (内容质检器.判定过度清洗)。
    清洗统计 = {'关键词行': 0, '推广行': 0, '过短行': 0,
                '符号行': 0, '广告行': 0, '水印': 0, '原始行数': 0}

    # 移除站点内嵌水印 (段落内部/段尾, 非整行): 连同前后空白一起删,
    # 保证 "句号。 W<水印串> 新段落" 清洗后自然衔接为 "句号。 新段落"
    # token 来源: 内置 (空) + 站点表 watermark_tokens 按域名合并 (D层外置)
    _wm_tokens = list(_WATERMARK_TOKENS)
    if site_url:
        try:
            from sites_config import 获取水印token as _获取水印token
            _wm_tokens += _获取水印token(site_url)
        except Exception as _e:
            _log.debug(f'裸 except 吞异常: {type(_e).__name__}: {_e} '
                       f'(站点水印token加载失败, 仅用内置)')
    for _wm in _wm_tokens:
        content, _wm_n = re.subn(r'\s*' + re.escape(_wm) + r'\s*', '', content)
        清洗统计['水印'] += _wm_n

    # 使用模块级常量 (避免重复定义); 站点级增补规则按域名合并 (2026-09-29)
    if site_url:
        try:
            from sites_config import 获取广告规则 as _获取广告规则
            _site_rules = _获取广告规则(site_url)
        except Exception as _e:
            _log.debug(f'裸 except 吞异常: {type(_e).__name__}: {_e} '
                       f'(站点广告规则加载失败, 仅用内置规则)')
            _site_rules = {'关键词': [], '正则': []}
    else:
        _site_rules = {'关键词': [], '正则': []}
    filter_keywords = list(_CONTENT_FILTER_KEYWORDS) + list(_site_rules['关键词'])
    _额外广告正则 = tuple(_site_rules['正则'])

    # 修复常见编码错误字符（Base64 解码后可能出现的乱码）
    # 2026-09-29 清理: 仅保留"形近/音近错字"级无争议替换 (48→20 条)。
    # 已删除的高危误纠 (会篡改正文语义):
    #   作对→作为 / 做对→对错 / 象限→相当于 / 像当→相当 / 爆满→爆发 /
    #   暴发→爆发 (暴发户为正确词) / 经已→已经 (粤语书面语合法) /
    #   在次→再次 ("生活在次元"误伤) / 插人→插入
    # 已删除的恒等映射: 再次/安排/复合/辩证/出类拔萃/游记系列 (9 条无效果)
    # 已合并: 渡假村/渡假胜地/... 等 17 条前缀变体 → 统一 '渡假'→'度假' 前缀替换
    encoding_fixes = {
        '口禽': '噙', '昏滚': '混蛋', '昏蛋': '混蛋',
        '王八旦': '王八蛋', '玉辟': '玉臂',
        '律劲': '律动',
        '巳经': '已经', '佷多': '很多',
        '以经': '已经', '已径': '已经', '再此': '在此',
        '按排': '安排',
        '复盖': '覆盖', '覆合': '复合', '辨正': '辩证',
        '宏扬': '弘扬', '洪扬': '弘扬',
        '渡假': '度假',
        '再接再励': '再接再厉',
        '迫不急待': '迫不及待',
        '不寒而粟': '不寒而栗',
        # 只纠错字不改词: "歪曲事非"→"歪曲是非" (原"→颠倒是非"篡改了动词;
        # 必须整词替换, 单纯 '事非'→'是非' 会误伤 "这事非常麻烦" 类句子)
        '歪曲事非': '歪曲是非',
    }
    for wrong, correct in encoding_fixes.items():
        content = content.replace(wrong, correct)

    # 移除页码标记, 如 （第1页）/(第2页), 防止混入正文
    content = re.sub(r'[（(]\s*第\d+页\s*[)）]', '', content)
    content = re.sub(r'^第\d+部分（第\d+页）', '', content)

    # 按行处理 (必须在上述修复之后拆分)
    lines = content.split('\n')
    # C6/P1: 分母 = 非空行数 (删除判定只对非空行生效, 空行计入会稀释占比)
    清洗统计['原始行数'] = sum(1 for _l in lines if _l.strip())
    filtered_lines = []

    for line in lines:
        stripped_line = line.strip()
        if not stripped_line:
            continue

        # 跳过包含过滤关键词的行
        if any(keyword in stripped_line for keyword in filter_keywords):
            清洗统计['关键词行'] += 1
            continue

        # URL/邮箱处理 (2026-09-29 改为行内剥离): 旧行为整行删除会误杀
        # "他打开 https://xxx 看了眼新闻" 这类正文行。
        # 新行为: 仅当行内确有 URL/邮箱特征时才剥离; 剥离后剩余中文字
        # >=10 视为正文行保留, 否则视为纯推广行删除。
        # ⚠ 必须先判特征再剥离: 无条件 sub+strip 会剥掉无 URL 行的句尾
        # 标点, 并使短行合并的"完整句"判断失效 (回归实测教训)。
        if ('http://' in stripped_line or 'https://' in stripped_line
                or 'www.' in stripped_line or '@' in stripped_line):
            _url_residual = _行内URL_RE.sub('', stripped_line)
            _url_cn = sum('\u4e00' <= c <= '\u9fff' for c in _url_residual)
            if _url_cn < 10:
                清洗统计['推广行'] += 1
                continue
            stripped_line = _url_residual.strip()   # 只剥空白, 句尾标点不动

        # 跳过过短的行（可能是导航或广告）
        if len(stripped_line) < 5:
            清洗统计['过短行'] += 1
            continue

        # 跳过主要是符号的行
        symbol_count = sum(1 for c in stripped_line if not c.isalnum() and not c.isspace() and not '\u4e00' <= c <= '\u9fff')
        if symbol_count > len(stripped_line) * 0.5:
            清洗统计['符号行'] += 1
            continue

        # 通用广告行特征检测 (基于内容特征, 不依赖具体书名/站点名)
        if _is_ad_line(stripped_line, _额外广告正则):
            清洗统计['广告行'] += 1
            continue

        filtered_lines.append(stripped_line)

    # 段落排版整理: 合并碎片化短行
    # siteAA/siteY 等站点的 <p> 标签可能因分段不一致产生短行,
    # 这些短行既非对话引语 (不以中文/英文引号开头) 也非独立段落,
    # 应合并到上一段, 使正文段落完整、连贯。
    _段末终结标点 = ('。', '！', '？', '…', '”', '』', '」', '!', '?')
    merged_lines = []
    for line in filtered_lines:
        if not line:
            continue
        # 对话引语独立成段: 以 "「 或 " 或 ' 或 「 开头的短行保留独立
        is_dialogue = bool(re.match(r'^[“”"\']', line)) or line.startswith('「') or line.startswith('『')
        # 段落首行特征: 较长 (>=30字) 或是对话引语
        is_paragraph_start = (len(line) >= 35) or is_dialogue
        if merged_lines and not is_paragraph_start and len(line) < 35:
            上一行 = merged_lines[-1]
            if not 上一行.endswith(_段末终结标点):
                # 上一行是半句 (逗号/无标点收尾) → 续接; 中文直接拼接
                # 不加空格 (宁过拆勿粘连: 过拆可由导出排版/离线工具兜底, 粘连不可逆)
                merged_lines[-1] = 上一行 + line
            else:
                # 上一行已完整成句 → 短行另起一段, 不粘连 (分段丢失根因④)
                merged_lines.append(line)
        else:
            merged_lines.append(line)

    # 合并过滤后的行
    cleaned_content = '\n\n'.join(merged_lines)

    # 移除多余的空行
    cleaned_content = re.sub(r'\n{3,}', '\n\n', cleaned_content)

    # 段落边界保留 (分段丢失根因③的修复):
    # 旧实现 '\n'.join([... if line.strip()]) 把 \n\n 段间空行全部删除,
    # 段落边界不可逆丢失 → TXT 观感"不分段"。
    # 新实现按 \n\n 切段: 段内 strip (清除残行), 段间保留恰好一个空行。
    # 注意: merged_lines 每项本就是单行 (无段内 \n), replace 为防御兜底。
    cleaned_content = '\n\n'.join(
        p.replace('\n', '').strip()
        for p in cleaned_content.split('\n\n') if p.strip())

    # ===== 排版规范化 (对整章最终文本，均不影响语义) =====
    # 1. 全角空格 → 空 (部分站点用全角空格做对齐水印)
    cleaned_content = cleaned_content.replace('\u3000', '')
    # 2. 行内连续空格压缩为单空格
    cleaned_content = re.sub(r' {2,}', ' ', cleaned_content)
    # 3. 逗号句号连排 ",。" / "，。" → "。" (站点拼接残渣)
    cleaned_content = re.sub(r'[，,]+[。.]', '。', cleaned_content)
    # 4. 重复标点压缩：4 个以上连续感叹/问号/句号 → 保留 2 个 (保留强调语气，去掉刷屏冗余)
    cleaned_content = re.sub(r'([！？。])\1{3,}', r'\1\1', cleaned_content)
    # 5. 段内行尾残留的章节号/页码 (如行尾 "第 3 页" 残留) 清理
    cleaned_content = re.sub(r'(?<=[\u4e00-\u9fff])第\d+页\s*$', '', cleaned_content, flags=re.M)
    # 6. 全角逗号句号之间不加空格
    cleaned_content = cleaned_content.replace('，。', '。').replace('，！', '！').replace('，？', '？')
    # 7. 半角标点转全角 (中文语境)
    cleaned_content = cleaned_content.replace(',。', '，').replace('，,', '，')
    cleaned_content = cleaned_content.replace('!?','！').replace('?!','？').replace('??','？')
    # 8. 括号内无内容清理
    cleaned_content = re.sub(r'[（\(]\s*[）\)]', '', cleaned_content)
    # 9. 段首多余标点清理 (逐行): 行首的逗号/句号/分号等残留
    cleaned_content = re.sub(r'^[，,；;：:]+', '', cleaned_content, flags=re.M)
    # 10. 段尾"连接性"标点清理 (逐行): 只删逗号/分号/冒号等，
    #     保留句号/感叹号/问号 (有语义的结束标点不删)
    cleaned_content = re.sub(r'[，,；;：:]+$', '', cleaned_content, flags=re.M)
    # 11. 行首 markdown 标记清理 (P2-6): 正文残留的 "## xxx" 若未处理,
    #     会让 _count_written_chapters 的 "## " 前缀计数虚增, 续传跳章。
    #     章节标题由调用方以 "## {title}" 写出(不经过本函数), 故此处去前缀
    #     可保证输出文件中 "## " 开头行必然 == 真实章节标题。
    cleaned_content = re.sub(r'^##\s+', '', cleaned_content, flags=re.M)

    # P3: 统计随返回值交回爬虫壳层 (contextvar 设置 + '清洗' 事件发布
    # 留在 爬虫.clean_content —— 编排职责; 本函数保持纯计算)
    return cleaned_content.strip(), 清洗统计
