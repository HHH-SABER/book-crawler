# -*- coding: utf-8 -*-
"""离线回归测试: 使用 测试样本_本地/ 中的真实页面快照验证解析逻辑, 全程不联网。
(站点脱钩: 真实快照不入库, 公开仓库形态下相关用例自动 skipTest, 机制用例照常跑。

运行方式 (项目根目录):
    python 测试/test_offline_parsing.py
    python -m unittest discover -s 测试 -v

覆盖范围:
    1. sites_config 正文提取 (qsbs_bb / html_selector + 各专用过滤器)
    2. content_decoder 数据文件解码 (码点流 / JSON / Base64)
    3. 爬虫.py 纯函数 (章节排序键 / 安全文件名 / URL 校验)
    4. NovelSpider.clean_content 通用清洗 (零宽字符 / 广告行)
"""

import json
import re
import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '源码'))

SAMPLES = _PROJECT_ROOT / '测试样本_本地'   # 站点脱钩: 真实快照不入库, 缺失时相关用例跳过


def _read(name: str) -> str:
    p = SAMPLES / name
    if not p.is_file():
        raise unittest.SkipTest(f'本地站点样本缺失: 测试样本_本地/{name} (公开形态跳过)')
    return p.read_text(encoding='utf-8')


# 正文特征串: 三份样本实际是同一部小说的开篇 (晨读迟到场景)
FEATURE_OPENING = '晨读的声音在校园里回'


# ============================================================
# 1. sites_config 正文提取
# ============================================================

class TestQsbsBbExtraction(unittest.TestCase):
    """qsbs.bb Base64 加密模式 (sitea / 站名sitel / siteb / sitei)。"""

    def test_sitea_sample_decodes_to_novel_text(self):
        from sites_config import extract_content_qsbs_bb
        html = _read('sitea_content.html')
        text = extract_content_qsbs_bb(html)
        self.assertGreater(len(text), 800, f'解码正文过短: {len(text)}')
        self.assertIn(FEATURE_OPENING, text)
        self.assertIn('李辰龙', text)          # 主角名, 校验解码完整性
        self.assertNotIn('qsbs.bb', text)      # 不应残留脚本标记

    def test_no_blocks_returns_empty(self):
        from sites_config import extract_content_qsbs_bb
        self.assertEqual(extract_content_qsbs_bb('<html><body>普通页面</body></html>'), '')


class TestHtmlSelectorExtraction(unittest.TestCase):
    """html_selector 通用模式 + 专用过滤器。"""

    def test_siteo_word_read(self):
        from sites_config import extract_content_html_selector
        html = _read('siteo_content.html')
        text = extract_content_html_selector(
            html, ['div.word_read', '.word_read', '#content', '.content'])
        self.assertGreater(len(text), 3000, f'siteo 正文过短: {len(text)}')
        self.assertIn(FEATURE_OPENING, text)

    def test_siteq_junk_filter_removes_obfuscation(self):
        """站点专属提取器 (entity_junk_filter) 的混淆清理断言。

        站点脱钩: 该提取器只在本地 站点适配_本地/_提取器.py 注册, 且真实站点
        样本不入库 —— 公开形态必然未注册 (走通用路径), 因此**公开侧只做归属
        声明**, 真实行为断言在 测试_本地/test_entity_junk_filter.py。
        (2026-10-02 修正: 此前误判为"清洗规则缺陷", 实为测试分层错误。)
        """
        self.skipTest('站点专属提取器与真实样本仅在本地形态可用; '
                      '行为断言见 测试_本地/test_entity_junk_filter.py')


# ============================================================
# 2. content_decoder 数据文件解码
# ============================================================

class TestDecodeData(unittest.TestCase):
    """decode_data 多格式解码 (siten .xs / sites .book 等数据文件模式)。"""

    def test_codepoint_stream_with_x_prefix(self):
        """x 前缀码点流 (siten 风格, 无压缩映射): x7b2c=第 x4e00=一 x7ae0=章。"""
        from content_decoder import decode_data
        expected = '第一章' * 12                        # 36 汉字, 超过 _looks_like_content 阈值
        payload = json.dumps({'content': 'x7b2cx4e00x7ae0' * 12}, ensure_ascii=False)
        text, method = decode_data(f'_txt_call({payload})')
        self.assertIsNotNone(text)
        self.assertEqual(method, 'codepoint_stream')
        self.assertEqual(text, expected)

    def test_codepoint_stream_with_replace_map(self):
        """【P1-7 回归】高频字压缩映射路径。

        旧 tokenizer 的首个候选 [\\x00-\\x1f]x[0-9a-fA-F]{4} 会把"控制字符+紧跟的
        x码点"吞成一个 6 字符 token, mapping 查不到、又不匹配纯 x码点, 落入 else
        原样输出 —— replace_map 永不命中, 含压缩映射的数据文件解码出乱码。
        现改为逐字符分词 + 循环内判定, 压缩字与码点各自还原。"""
        from content_decoder import decode_data
        expected = '一章' * 12
        payload = json.dumps({'content': 'x4e00\x01' * 12, 'replace': {'7ae0': '\x01'}},
                             ensure_ascii=False)
        text, method = decode_data(f'_txt_call({payload})')
        self.assertIsNotNone(text)
        self.assertEqual(method, 'codepoint_stream')
        self.assertEqual(text, expected)

    def test_json_content_field(self):
        from content_decoder import decode_data
        long_text = '这是一段足够长的中文正文内容，包含完整的标点符号与叙事结构。' * 3
        text, method = decode_data(json.dumps({'content': long_text}, ensure_ascii=False))
        self.assertIsNotNone(text)
        self.assertEqual(method, 'json.content')
        self.assertEqual(text, long_text)

    def test_plain_text_fallback(self):
        from content_decoder import decode_data
        long_text = '纯粹的正文文本没有包装结构，直接是章节内容，应当走纯文本兜底路径。' * 3
        text, method = decode_data(long_text)
        self.assertIsNotNone(text)
        self.assertEqual(method, 'plain_text')

    def test_base64_fallback(self):
        import base64
        from content_decoder import decode_data
        long_text = '经过Base64编码的章节正文内容，解码后应当还原为可读的中文文本。' * 3
        text, method = decode_data(base64.b64encode(long_text.encode('utf-8')).decode('ascii'))
        self.assertIsNotNone(text)
        self.assertEqual(method, 'base64')
        self.assertEqual(text, long_text)

    def test_sitep_continuous_hex_stream(self):
        """【P2-7 回归】sitep 的裸码点流 (无 x 前缀, 由 \\x01/\\x02/\\x03 引导)。

        数据形如 "\\x026606\\x013001;(...": 前缀标记后的 4 位十六进制即码点,
        其余控制字符查 replace 表还原高频字, ';' 是实体残留分隔符, \\x04 是换行。
        旧实现只认 x 前缀 token, 整段码点被当成明文字母输出 (解码失败)。
        生产环境此前靠 Selenium 渲染兜底, 现已可直接解码 .book 数据文件。"""
        from content_decoder import decode_data
        raw = _read('sitep_1.book')
        text, method = decode_data(raw)
        self.assertIsNotNone(text, 'sitep 裸码点流应被解码')
        self.assertEqual(method, 'codepoint_stream')
        self.assertGreater(len(text), 1000)
        self.assertIn(FEATURE_OPENING, text)
        # 还原质量: 汉字应占绝对多数, 且不应残留未还原的控制字符 (换行除外)
        chinese = len(re.findall(r'[\u4e00-\u9fff]', text))
        self.assertGreater(chinese / len(text), 0.6)
        self.assertEqual(len(re.findall(r'[\x00-\x1f]', text.replace('\n', ''))), 0)


# ============================================================
# 2b. 数据文件引用探测 (detect_data_refs) —— 后缀白名单回归
# ============================================================

class TestDetectDataRefs(unittest.TestCase):
    """探测正则的后缀白名单 (2026-10-03 补 word)。

    背景: 某站 (lukutxt 系阅读站) 章节页只有"章节内容加载中"占位, 正文由
    initTxt("//j.<主域>/data/chapter/<书号>/<卷>/<N>.word") 异步拉取。
    探测正则的 _DATA_EXT 漏了 word → detect_data_refs 返回空 → decode_chapter_data
    直接 (None, None) → 该站被误判"无正文"。decode_data 本身能解(word 内容
    就是码点流), 纯粹是探测层把它挡在了门外。
    """

    def test_detects_word_suffix(self):
        from content_decoder import detect_data_refs
        html = ('<script>initTxt("//j.example.com/data/chapter/BOOK1/v1/1.word",'
                '"第 1 篇")</script>')
        refs = detect_data_refs(html)
        self.assertTrue(refs, 'initTxt(...word) 应被探测到')
        self.assertIn('.word', refs[0][0])

    def test_detects_existing_suffixes_regression(self):
        """既有后缀不能被本次改动挤掉 (回归护栏)。"""
        from content_decoder import detect_data_refs
        for 后缀 in ('xs', 'book', 'data', 'txt', 'json', 'word'):
            with self.subTest(后缀=后缀):
                html = f'<script>initTxt("//j.example.com/data/c/1.{后缀}")</script>'
                self.assertTrue(detect_data_refs(html), f'{后缀} 后缀应可探测')

    def test_data_path_pattern_covers_word(self):
        """data路径 模式 (无 initTxt 包装) 也应覆盖 word。"""
        from content_decoder import detect_data_refs
        html = '<script>var u="/data/chapter/B1/1.word";</script>'
        refs = detect_data_refs(html)
        self.assertTrue(refs, '/data/... 路径形态的 .word 应被探测')
        self.assertIn('.word', refs[0][0])

    def test_pagination_regex_includes_word(self):
        """分页替换正则的后缀清单必须与 _DATA_EXT 一致。

        漏 word 会让 page>1 的请求仍取第 1 页 → 每页内容相同, 只能靠
        指纹去重才没炸出重复正文 (行为上不易察觉, 但等于分页失效)。
        """
        import inspect
        import content_decoder
        源码 = inspect.getsource(content_decoder.decode_chapter_data)
        # 分页替换语句可能跨两行 (re.sub 的 pattern 与 repl 分行写), 故整段找
        分页段 = [ln for ln in 源码.splitlines() if 're.sub' in ln]
        self.assertTrue(分页段, '未找到分页替换语句')
        self.assertTrue(any('word' in ln for ln in 分页段),
                        '分页正则的后缀清单缺 word → 分页请求会重复取第 1 页')

    def test_source_keeps_word_in_ext_list(self):
        """源码级断言: word 必须在 _DATA_EXT 里 (钉死不被后人摘掉)。"""
        import inspect
        import content_decoder
        源码 = inspect.getsource(content_decoder)
        self.assertIn("json|word", 源码,
                      '_DATA_EXT 缺 word —— 该后缀站会静默退化为"无正文"')


# ============================================================
# 3. 爬虫.py 纯函数
# ============================================================

class TestChapterSortKey(unittest.TestCase):
    """章节标题排序键: 数字感知排序。"""

    def test_numeric_order(self):
        from 爬虫 import _chapter_sort_key
        self.assertLess(_chapter_sort_key({'title': '第3章', 'url': '/a3.html'}),
                        _chapter_sort_key({'title': '第12章', 'url': '/a12.html'}))

    def test_range_title_uses_start(self):
        """区间式标题 (siteo/siteq 两章合一页): 第1-2章 取起始章号。"""
        from 爬虫 import _chapter_sort_key
        self.assertEqual(_chapter_sort_key({'title': '第1-2章', 'url': '/b.html'}), 1)

    def test_unparseable_title_gets_large_key(self):
        """中文数字等无法解析的标题得到 9999 大键值, 排序时沉底不崩溃。
        (中文数字转换仅在站点特定分支实现, 顶层通用键不覆盖)"""
        from 爬虫 import _chapter_sort_key
        self.assertEqual(_chapter_sort_key({'title': '序章', 'url': '/c.html'}), 9999)


class TestSafeFilename(unittest.TestCase):
    def test_strips_illegal_chars(self):
        from 爬虫 import _safe_filename_part
        self.assertEqual(_safe_filename_part('测试/小说:第1章?'), '测试_小说_第1章')

    def test_max_length(self):
        from 爬虫 import _safe_filename_part
        self.assertLessEqual(len(_safe_filename_part('超' * 200)), 80)


class TestValidatePublicUrl(unittest.TestCase):
    """SSRF 防护: 仅允许公网 http/https。"""

    def test_public_http_passes(self):
        from sites_config import validate_public_url
        validate_public_url('https://www.example.com/book/1.html')
        validate_public_url('http://123.45.67.89/x.html')

    def test_private_and_loopback_blocked(self):
        from sites_config import validate_public_url
        for bad in ('http://localhost/x', 'http://127.0.0.1/x',
                    'http://192.168.1.1/x', 'http://10.0.0.1/x',
                    'ftp://www.example.com/x', 'file:///etc/passwd'):
            with self.assertRaises(ValueError, msg=bad):
                validate_public_url(bad)


# ============================================================
# 4. clean_content 通用清洗
# ============================================================

class TestCleanContent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from 爬虫 import NovelSpider
        cls.spider = NovelSpider.__new__(NovelSpider)   # 跳过 __init__, 不触网

    def test_removes_zero_width_chars(self):
        cleaned = self.spider.clean_content('第一段\u200b含零宽字符。\u200b')
        self.assertNotIn('\u200b', cleaned)
        self.assertIn('第一段含零宽字符。', cleaned)

    def test_removes_ad_lines_keeps_paragraphs(self):
        raw = ('这是第一段正常的叙事内容，讲述主角的日常与冲突，长度足以超过短行阈值。\n\n'
               '请记住本站的最新网址以便下次访问\n\n'
               'www.example.com\n\n'
               '这是第二段同样正常的叙事内容，情节继续推进，句子完整且带有中文标点符号。')
        cleaned = self.spider.clean_content(raw)
        self.assertIn('这是第一段正常的叙事内容', cleaned)
        self.assertIn('这是第二段同样正常的叙事内容', cleaned)
        self.assertNotIn('请记住本站', cleaned, '宣传语行未被过滤')
        self.assertNotIn('www.example.com', cleaned, '域名行未被过滤')

    def test_keeps_normal_paragraphs(self):
        raw = '正常段落，含有完整的中文标点与足够的长度，不应该被广告过滤器误伤。'
        self.assertIn(raw, self.spider.clean_content(raw))

    def test_removes_markdown_heading_markers(self):
        """正文行首 '## ' 标记须被清除 (P2-6): 否则输出文件里 '## ' 开头行
        会被 _count_written_chapters 误计为章节标题, 检查点兜底续传时跳章。"""
        raw = ('第一段正常叙事内容，长度足以跨越短行阈值，句子结构完整。\n'
               '## 正文里残留的章节标记\n'
               '第二段正常叙事内容，继续推进情节发展，不应当受影响。')
        cleaned = self.spider.clean_content(raw)
        self.assertNotIn('\n## ', cleaned, '正文中的 "## " 行首标记未被清除')
        self.assertIn('正文里残留的章节标记', cleaned, '应只去前缀不删文本')

    def test_removes_fallback_domain_ad(self):
        """'找回新域名'类广告行 (sites 移动版实测: '最新找回4F4F4F,C〇M') 须清除。"""
        raw = ('第一段正常叙事内容，足够长度跨越短行阈值，句子结构完整。\n'
               '最新找回4F4F4F,C〇M\n'
               '第二段正常叙事内容，继续推进情节发展不受影响。')
        cleaned = self.spider.clean_content(raw)
        self.assertNotIn('找回4F4F', cleaned, '找回站广告行未被过滤')
        self.assertIn('第一段正常叙事内容', cleaned)

    # ===== 分段修复回归 (2026-09-29): 段落边界保留 + 短行合并不粘连 =====

    def test_paragraph_blank_line_preserved(self):
        """段落边界以 \\n\\n 保留: 旧行为把段间空行压成单 \\n (根因③)。"""
        raw = ('第一段完整叙事内容，句子完整并以句号收尾，长度足够跨越短行合并阈值判定。\n\n'
               '第二段完整叙事内容，同样以句号收尾，长度也足够跨过阈值独立成段。')
        cleaned = self.spider.clean_content(raw)
        self.assertIn('阈值判定。\n\n第二段', cleaned,
                      '段间空行未保留, 段落边界丢失')

    def test_short_line_not_glued_after_full_sentence(self):
        """完整句 (句号收尾) 之后的短行另起一段, 不被粘成长段 (根因④)。"""
        raw = ('主角推开门缓缓走进屋子，环顾四周一圈后轻轻叹了口气，神色复杂。\n'
               '这是短尾巴')
        cleaned = self.spider.clean_content(raw)
        self.assertIn('神色复杂。\n\n这是短尾巴', cleaned,
                      '完整句后的短行被粘连')

    def test_half_sentence_still_continues(self):
        """半句断行 (无句末标点收尾) 仍续接, 且中文直接拼接不加空格。"""
        raw = ('主角推开门缓缓走进屋子，环顾四周一圈后轻轻\n'
               '叹了口气继续动作')
        cleaned = self.spider.clean_content(raw)
        self.assertIn('轻轻叹了口气继续动作', cleaned, '半句断行未被续接')
        self.assertNotIn('轻轻 叹了口气', cleaned, '续接处残留空格')

    # ===== 误纠表清理 + 行内URL剥离回归 (2026-09-29) =====

    def test_typo_table_no_semantic_tampering(self):
        """误纠表清理后: 高危条目不得再篡改正文语义 (直接含触发词)。"""
        raw = ('村里的老张头脾气倔，谁跟他作对他就跟谁急，天天闹得鸡飞狗跳不安生。\n'
               '庙会那天集市人山人海，摊位生意个个爆满，吆喝声此起彼伏好不热闹。')
        cleaned = self.spider.clean_content(raw)
        self.assertIn('作对', cleaned, '"作对"被误纠表篡改成"作为"')
        self.assertNotIn('作为他就跟谁急', cleaned)
        self.assertIn('爆满', cleaned, '"爆满"被误纠表篡改成"爆发"')
        self.assertNotIn('爆发，吆喝', cleaned)

    def test_typo_table_still_fixes_real_typos(self):
        """误纠表清理后: 无争议错字纠正仍然生效。"""
        raw = '他巳经离开了三个小时，房间里按排好的茶具还没有人动过，显然走得匆忙。'
        cleaned = self.spider.clean_content(raw)
        self.assertIn('已经', cleaned, '巳经→已经 纠错失效')
        self.assertNotIn('巳经', cleaned)
        self.assertIn('安排', cleaned, '按排→安排 纠错失效')

    def test_inline_url_stripped_keeps_text(self):
        """行内 URL 剥离: 含链接的正文行保留剥离后的文字 (旧行为整行误删)。"""
        raw = ('他打开浏览器搜索了半天资料，终于在某个论坛里找到了关键线索，\n'
               '详情参见 https://forum.example.com/thread/12345 这条帖子写得很清楚。')
        cleaned = self.spider.clean_content(raw)
        self.assertIn('这条帖子写得很清楚', cleaned, '含URL正文行被整行误删')
        self.assertNotIn('https://', cleaned, 'URL 本身未剥离')

    def test_pure_promo_url_line_removed(self):
        """纯推广行 (URL + 少量中文) 仍被删除。"""
        raw = ('第一段完整叙事内容，句子完整并以句号收尾，长度足够跨越短行合并阈值判定。\n'
               '最新网址 www.example.com 请收藏\n'
               '第二段完整叙事内容，同样以句号收尾，长度也足够跨过阈值独立成段。')
        cleaned = self.spider.clean_content(raw)
        self.assertNotIn('www.example.com', cleaned, '纯推广URL行未删除')
        self.assertNotIn('请收藏', cleaned, '推广语未随行删除')

    def test_email_line_handled(self):
        """@ 推广行: 剥离后剩余中文不足则删行。"""
        raw = ('第一段完整叙事内容，句子完整并以句号收尾，长度足够跨越短行合并阈值判定。\n'
               '联系邮箱 book@example.com 记得发邮件\n'
               '第二段完整叙事内容，同样以句号收尾，长度也足够跨过阈值独立成段。')
        cleaned = self.spider.clean_content(raw)
        self.assertNotIn('book@example.com', cleaned, '邮箱推广行未删除')

    def test_clean_stats_via_contextvar(self):
        """清洗统计经 contextvar 传出: 广告/关键词行被删时统计可读且总数非零。"""
        from 爬虫 import _最近清洗统计
        raw = ('第一段完整叙事内容，句子完整并以句号收尾，长度足够跨越阈值判定。\n'
               '一秒记住本站最新域名，请收藏备用\n'
               '第二段完整叙事内容，同样以句号收尾，长度也足够跨过阈值独立成段。')
        cleaned = self.spider.clean_content(raw)
        stats = _最近清洗统计.get()
        self.assertIsNotNone(stats, 'clean_content 未写入清洗统计 contextvar')
        self.assertIsInstance(stats, dict)
        # 该宣传行至少被 关键词表 或 广告行检测 之一拦截计数
        total = sum(v for v in stats.values() if isinstance(v, int))
        self.assertGreaterEqual(total, 1, '删除行未被计数')
        self.assertNotIn('记住本站', cleaned, '宣传行未被删除')

    def test_排版章节文本_indent_and_blank_lines(self):
        """_排版章节文本: 段首两全角空格 + 段间空行 + 标题行不缩进 (中文排版规范)。"""
        from 爬虫 import _排版章节文本
        out = _排版章节文本('第一章 测试', '段落一内容。\n段落二内容。', 缩进=True)
        self.assertEqual(out, '## 第一章 测试\n\n'
                              '\u3000\u3000段落一内容。\n\n'
                              '\u3000\u3000段落二内容。\n\n')

    def test_排版章节文本_no_indent(self):
        """_排版章节文本: 缩进关闭时只保留段间空行。"""
        from 爬虫 import _排版章节文本
        out = _排版章节文本('第一章', '段落一。\n段落二。', 缩进=False)
        self.assertNotIn('\u3000', out, '关闭缩进后仍有全角空格')
        self.assertIn('段落一。\n\n段落二。', out)

    def test_排版章节文本_empty_body(self):
        """_排版章节文本: 空正文只写标题行 (空占位章不产生缩进空段)。"""
        from 爬虫 import _排版章节文本
        self.assertEqual(_排版章节文本('第一章', '', 缩进=True), '## 第一章\n\n')
        self.assertEqual(_排版章节文本('第一章', None, 缩进=True), '## 第一章\n\n')

    def test_site_ad_rules_filter(self):
        """站点级 ad_rules: 关键词与行正则按域名增补过滤, 不污染其他站点 (2026-09-29)。"""
        import sites_config
        sites_config.SITE_PATTERNS.append({
            'domain': 'adtest.example', 'enabled': True,
            'ad_rules': {'关键词': ['本站特供广告词'],
                         '行正则': [r'^.*带推广链接.*$']}})
        try:
            sites_config._广告规则缓存.clear()
            raw = ('第一段完整叙事内容，句子完整并以句号收尾，长度足够跨越阈值判定。\n'
                   '本站特供广告词请勿保留\n'
                   '这是一行带推广链接的内容也应该被删掉。\n'
                   '第二段完整叙事内容，同样以句号收尾，长度也足够跨过阈值独立成段。')
            cleaned = self.spider.clean_content(
                raw, site_url='https://adtest.example/book/1/')
            self.assertNotIn('本站特供广告词', cleaned, '站点关键词未过滤')
            self.assertNotIn('带推广链接', cleaned, '站点行正则未过滤')
        finally:
            sites_config.SITE_PATTERNS[:] = [
                p for p in sites_config.SITE_PATTERNS
                if p.get('domain') != 'adtest.example']
            sites_config._广告规则缓存.clear()

    def test_site_ad_rules_invalid_regex_skipped(self):
        """站点 ad_rules 非法正则: 编译失败只跳过该规则, 清洗不抛异常。"""
        import sites_config
        sites_config.SITE_PATTERNS.append({
            'domain': 'badregex.example', 'enabled': True,
            'ad_rules': {'行正则': ['[非法正则(']}})
        try:
            sites_config._广告规则缓存.clear()
            raw = ('第一段完整叙事内容，句子完整并以句号收尾，长度足够跨越阈值判定。')
            cleaned = self.spider.clean_content(
                raw, site_url='https://badregex.example/book/1/')
            self.assertIn('第一段完整叙事内容', cleaned)
        finally:
            sites_config.SITE_PATTERNS[:] = [
                p for p in sites_config.SITE_PATTERNS
                if p.get('domain') != 'badregex.example']
            sites_config._广告规则缓存.clear()


# ============================================================
# 5b. 点选验证码多模态调用器 (C4 回归)
# ============================================================

class TestPointClickModel(unittest.TestCase):
    """_solve_with_model: 未配置/坏配置必须安全返回 None (上层转人工), 绝不抛异常。"""

    def test_no_provider_returns_none(self):
        from captcha_module import PointClickCaptchaHandler
        h = PointClickCaptchaHandler.__new__(PointClickCaptchaHandler)
        self.assertIsNone(h._solve_with_model(None, 'https://x/', {}))

    def test_provider_without_endpoint_returns_none(self):
        from captcha_module import PointClickCaptchaHandler
        h = PointClickCaptchaHandler.__new__(PointClickCaptchaHandler)
        self.assertIsNone(h._solve_with_model(None, 'https://x/',
                                              {'provider': 'ollama', 'endpoint': ''}))

    def test_unreachable_endpoint_returns_none(self):
        from captcha_module import PointClickCaptchaHandler
        h = PointClickCaptchaHandler.__new__(PointClickCaptchaHandler)
        cfg = {'provider': 'ollama', 'endpoint': 'http://127.0.0.1:1', 'model': 'm'}
        self.assertIsNone(h._solve_with_model(None, 'https://x/', cfg))


# ============================================================
# 5. Session 线程隔离 (P1-8 回归)
# ============================================================

class TestSessionThreadIsolation(unittest.TestCase):
    """并发抓取时每个线程必须拿到自己刚赋的 Session。

    旧实现靠 "替换 self.session + finally 还原" 发独立 Session, 而 self.session
    是实例级共享属性: 线程B 进入时读到的"旧值"可能是 线程A 刚赋的新 Session,
    于是 A 还原后 B 又把 A 的 Session 写回去 —— Session 错配 + 连接泄漏。
    现改为 threading.local 属性, 赋值只作用于当前线程。
    """

    @classmethod
    def setUpClass(cls):
        from 爬虫 import NovelSpider
        cls.spider = NovelSpider('https://www.example.com')  # 离线可构造 (~0.8s)

    @classmethod
    def tearDownClass(cls):
        cls.spider.close()

    def test_fallback_to_main_session(self):
        """主线程未赋值时, self.session 回退到主 Session (串行路径行为不变)。"""
        self.assertIs(self.spider.session, self.spider._main_session)

    def test_concurrent_assignment_isolated(self):
        """4 线程同时赋值, 各自读回的必须是自己那一个。"""
        import threading
        import requests
        main = self.spider._main_session
        barrier = threading.Barrier(4)
        errors = []
        seen = {}
        lock = threading.Lock()

        def body(idx):
            try:
                mine = requests.Session()
                self.spider.session = mine
                barrier.wait(timeout=10)          # 强制重叠, 放大竞态窗口
                with lock:
                    seen[idx] = id(self.spider.session)
                if self.spider.session is not mine:
                    errors.append(f'线程 {idx} 读到了别的线程的 Session')
                self.spider.session = main       # 模拟 worker 的 finally 复位
            except Exception as e:               # noqa: BLE001 - 收集后统一断言
                errors.append(f'线程 {idx} 异常: {e!r}')

        threads = [threading.Thread(target=body, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
            self.assertFalse(t.is_alive(), '线程未在 30s 内结束 (barrier 死锁?)')

        self.assertEqual(errors, [])
        self.assertEqual(len(set(seen.values())), 4, '各线程应持有互不相同的 Session')

    def test_worker_restores_and_reuses_session(self):
        """_fetch_chapter_worker 用线程级独立 Session 执行, 结束复位,
        同线程复用同一 Session (连接保活), close() 时统一关闭。"""
        from unittest import mock
        from 爬虫 import NovelSpider
        spider = NovelSpider('https://www.example.com')
        main = spider._main_session
        captured = {}

        # 用假实现替换 _fetch_with_qc, 只验证 Session 生命周期, 不触网
        def fake_qc(chap):
            captured['session'] = spider.session
            captured['is_main'] = spider.session is main
            return '正文'

        spider._fetch_with_qc = fake_qc
        try:
            spider._fetch_chapter_worker({'title': '第一章', 'url': '/1.html'})
            self.assertIsNotNone(captured.get('session'))
            self.assertFalse(captured['is_main'], 'worker 内应拿到独立 Session')
            self.assertIs(spider.session, main, 'worker 结束后本线程应复位为主 Session')
            first = captured['session']

            # 同线程第二次执行: 应复用同一 Session (线程级保活, 免每章 TLS 握手)
            spider._fetch_chapter_worker({'title': '第二章', 'url': '/2.html'})
            self.assertIs(captured['session'], first, '同线程应复用临时 Session')

            # close() 应统一关闭线程级 Session (防止连接池泄漏)
            with mock.patch.object(type(first), 'close',
                                   side_effect=first.close) as m:
                spider.close()
            self.assertTrue(m.called, 'close() 应关闭线程级临时 Session')
        finally:
            spider.close()

    def test_worker_returns_empty_when_stopped(self):
        """stop_event 已置位时 worker 立即返回空串, 不发请求 (P1-2)。"""
        import threading
        from 爬虫 import NovelSpider
        spider = NovelSpider('https://www.example.com')
        try:
            spider._fetch_with_qc = lambda chap: (_ for _ in ()).throw(
                AssertionError('stop_event 已置位, 不应发起抓取'))
            stop = threading.Event()
            stop.set()
            self.assertEqual(spider._fetch_chapter_worker(
                {'title': '第一章', 'url': '/1.html'}, stop), '')
        finally:
            spider.close()


class TestPinyinNoiseCleaning(unittest.TestCase):
    """拼音替代串 / 无意义字符清洗 (_clean_pinyin_and_noise) 各分支"""

    @classmethod
    def setUpClass(cls):
        from 爬虫 import NovelSpider
        cls.clean = staticmethod(NovelSpider._clean_pinyin_and_noise)

    def test_toned_pinyin_removed(self):
        # 纯声调段 (āáǎà): 曾因 translate 后检查声调字符而漏删
        self.assertEqual(self.clean('他说āáǎà然后走了'), '他说然后走了')

    def test_toned_syllable_removed(self):
        # 带声调的合法音节 (shuōde → shude 可切分)
        self.assertEqual(self.clean('他说shuōde很快'), '他说很快')

    def test_unvoiced_pinyin_pair_removed(self):
        # 无声调拼音对删除 (残留单空格由双空格收敛而来)
        self.assertEqual(self.clean('他的 ta de 名字'), '他的 名字')

    def test_whitelist_kept(self):
        self.assertEqual(self.clean('他打开了 app 开始听歌'),
                         '他打开了 app 开始听歌')

    def test_english_kept(self):
        # hello/world 无法完整切分为音节 → 保留
        self.assertEqual(self.clean('他说 hello world 很好'),
                         '他说 hello world 很好')

    def test_valid_pinyin_word_removed(self):
        # shuo 是合法音节 → 判定拼音替代, 删除
        self.assertEqual(self.clean('她说shuo完就走了'), '她说完就走了')

    def test_repeated_punct_collapsed(self):
        self.assertEqual(self.clean('重复！！！！'), '重复！！！')

    def test_control_chars_removed(self):
        self.assertEqual(self.clean('好\u009f\ue000\ufffd内容'), '好内容')

    def test_normal_text_untouched(self):
        s = '这是一段完全正常的中文内容，没有任何噪声。'
        self.assertEqual(self.clean(s), s)


class TestRustFallbackParity(unittest.TestCase):
    """Rust 加速路径与纯 Python 兜底路径的一致性 (CHANGELOG 2.4.0)。

    rust_core.pyd 存在时走 Rust, 缺失/异常回退纯 Python — 本用例通过
    开关 _RUST_*可用 标志, 断言两条路径对同一输入产出完全一致的结果;
    pyd 缺失的环境 (CI/fresh clone) 两次都走纯 Python, 兜底路径同样被覆盖。
    """

    SAMPLE = ('晨读的声音在校园里回荡，他抱着书本跑过操场，' * 30)  # 长中文正文

    def test_qa_质检_rust_on_off_一致(self):
        import 内容质检器
        old = 内容质检器._RUST_质检可用
        try:
            内容质检器._RUST_质检可用 = True
            on = 内容质检器.内容质检器().质检(self.SAMPLE, 章节标题='第一章')
            内容质检器._RUST_质检可用 = False
            off = 内容质检器.内容质检器().质检(self.SAMPLE, 章节标题='第一章')
        finally:
            内容质检器._RUST_质检可用 = old
        self.assertEqual(on.得分, off.得分, 'Rust 与纯 Python 得分不一致')
        self.assertEqual(on.有效, off.有效)
        self.assertEqual(on.原因, off.原因)
        self.assertEqual(on.统计, off.统计)

    def test_qa_空文本_rust_on_off_一致(self):
        # 空文本走不到 Rust (Python 侧先判空)? 无论哪边先处理, 结果必须一致
        import 内容质检器
        old = 内容质检器._RUST_质检可用
        try:
            内容质检器._RUST_质检可用 = True
            on = 内容质检器.内容质检器().质检('')
            内容质检器._RUST_质检可用 = False
            off = 内容质检器.内容质检器().质检('')
        finally:
            内容质检器._RUST_质检可用 = old
        self.assertEqual(on.得分, off.得分)
        self.assertEqual(on.有效, off.有效)

    def test_codepoint_解码_rust_on_off_一致(self):
        import content_decoder
        raw = 'x7b2cx4e00x7ae0' * 12   # x 前缀码点流 (同 test_codepoint_stream_with_x_prefix)
        old = content_decoder._RUST_解码可用
        try:
            content_decoder._RUST_解码可用 = True
            on = content_decoder.parse_codepoint_stream(raw)
            content_decoder._RUST_解码可用 = False
            off = content_decoder.parse_codepoint_stream(raw)
        finally:
            content_decoder._RUST_解码可用 = old
        self.assertEqual(on, off, 'Rust 与纯 Python 码点流解码结果不一致')
        self.assertIn('第一章', on)

    @unittest.skipUnless((_PROJECT_ROOT / '源码' / 'rust_core.pyd').exists(),
                         'rust_core.pyd 未安装, 跳过真实 pyd A/B')
    def test_qa_真实pyd样本扫描一致(self):
        """H2: 仅 pyd 真实存在时运行 — 多形态样本逐个对比 Rust 与纯 Python。

        旧的开关式用例在 pyd 缺失时恒真 (门禁测不出 lib.rs 与 Python 漂移),
        本用例补上"真实 pyd 参与运算"的断言。"""
        import 内容质检器
        qa = 内容质检器.内容质检器()
        cases = [
            self.SAMPLE,                                  # 长中文正文
            '短章内容较少的情况。',                        # 短章区间
            'ab12 \x01\x02 {}<>??',                       # 乱码/符号密集
            '\ufffd\ue000\ufff0' * 40,                    # 乱码区
            '标点only，。。！！？？' * 10,                 # 标点密度高
        ]
        old = 内容质检器._RUST_质检可用
        try:
            for text in cases:
                内容质检器._RUST_质检可用 = True
                on = qa.质检(text, 章节标题='样本')
                内容质检器._RUST_质检可用 = False
                off = qa.质检(text, 章节标题='样本')
                tag = repr(text[:16])
                self.assertEqual(on.得分, off.得分, f'得分不一致: {tag}')
                self.assertEqual(on.有效, off.有效, f'有效不一致: {tag}')
                self.assertEqual(on.原因, off.原因, f'原因不一致: {tag}')
                self.assertEqual(on.统计, off.统计, f'统计不一致: {tag}')
        finally:
            内容质检器._RUST_质检可用 = old

    def test_codepoint_真实样本_replace_map_双路径一致(self):
        """H2: sitep 真实 .book 携带非空压缩映射 — replace_map 非空是双实现
        最易漂移且此前零覆盖的场景。开关 Rust 路径对比全文逐字符一致。"""
        import content_decoder
        raw = _read('sitep_1.book')
        old = content_decoder._RUST_解码可用
        try:
            content_decoder._RUST_解码可用 = True
            on = content_decoder.decode_data(raw)
            content_decoder._RUST_解码可用 = False
            off = content_decoder.decode_data(raw)
        finally:
            content_decoder._RUST_解码可用 = old
        self.assertEqual(on[1], 'codepoint_stream')
        self.assertIsNotNone(on[0])
        self.assertEqual(on[0], off[0], '含映射的码点流解码 Rust/纯Python 不一致')
        self.assertIn(FEATURE_OPENING, on[0])


# ============================================================
# 5. sitef: 章节页→目录页规范化 + 样本解析契约 (2026-09-11 事故)
# ============================================================

def _load_sitef_adapter():
    """直接按路径加载适配器模块 (不依赖 ADAPTERS 注册表, 与加载路径解耦)"""
    import importlib.util
    _p = _PROJECT_ROOT / '站点适配_本地' / 'sitef.py'
    if not _p.is_file():
        raise unittest.SkipTest('本地适配器缺失: 站点适配_本地/sitef.py (公开形态跳过)')
    spec = importlib.util.spec_from_file_location(
        'site_adapter_sitef_test', str(_p))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestYunshuzhaiCatalogFromChapter(unittest.TestCase):
    """用户把章节页 URL 当任务 URL: 通用管线把章节页当目录页解析, 只剩
    "目录"链接 1 个"章节", 把详情页当正文抓 → 整单失败 (09-11 实测)。
    适配器用 catalog_from_chapter 声明章节页→目录页推导, run() 在解析前调用。"""

    def test_chapter_url_to_catalog(self):
        f = _load_sitef_adapter().catalog_from_chapter
        self.assertEqual(
            f('https://www.sitef.example.com/book/3432/1.html'),
            'https://www.sitef.example.com/book/3432/')
        self.assertEqual(
            f('https://sitef.example.com/book/7/99.html'),
            'https://sitef.example.com/book/7/')

    def test_non_chapter_urls_return_none(self):
        f = _load_sitef_adapter().catalog_from_chapter
        self.assertIsNone(f('https://www.sitef.example.com/book/3432/'))  # 目录页本身
        self.assertIsNone(f('https://www.sitef.example.com/search.html'))
        self.assertIsNone(f(''))
        self.assertIsNone(f(None))
        # 域名无关纯路径推导 (域名限定由 resolve 分发层按注册表保证), 主机保留
        self.assertEqual(f('https://other.com/book/1/2.html'),
                         'https://other.com/book/1/')

    def test_resolve_dispatch_via_registry(self):
        """resolve_catalog_from_chapter 按 ADAPTERS 注册表分发:
        未声明/无匹配域名 → None; 异常 → None (不阻断抓取)。"""
        import sites_config
        saved = dict(sites_config.ADAPTERS)

        def fake_fn(url, base_url=None):
            return 'https://x.example/book/1/'

        entry_ok = {'source': 't', 'parse_catalog': None,
                    'extract_content': None, 'paginate': None,
                    'get_title': None, 'catalog_from_chapter': fake_fn}
        entry_none = dict(entry_ok, catalog_from_chapter=None)
        try:
            sites_config.ADAPTERS = {'example.com': entry_ok}
            self.assertEqual(
                sites_config.resolve_catalog_from_chapter(
                    'https://www.example.com/book/1/2.html'),
                'https://x.example/book/1/')
            sites_config.ADAPTERS = {'example.com': entry_none}
            self.assertIsNone(sites_config.resolve_catalog_from_chapter(
                'https://www.example.com/book/1/2.html'))
            sites_config.ADAPTERS = {'other.org': entry_ok}
            self.assertIsNone(sites_config.resolve_catalog_from_chapter(
                'https://unknown.example.com/book/1/2.html'))
        finally:
            sites_config.ADAPTERS = saved


class TestYunshuzhaiSamples(unittest.TestCase):
    """真实页面快照契约: 目录解析 / 正文提取 / 书名 (09-10/09-11 两轮修复)。"""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_sitef_adapter()
        from bs4 import BeautifulSoup
        cls._bs4 = BeautifulSoup

    def test_catalog_sample_yields_chapter_list(self):
        soup = self._bs4(_read('sitef_catalog.html'), 'html.parser')
        links = self.mod.parse_catalog(
            soup, 'https://www.sitef.example.com/book/3432/',
            'https://www.sitef.example.com')
        self.assertIsNotNone(links, '目录样本应解析出章节列表')
        self.assertGreater(len(links), 5, f'章节数过少: {len(links)}')
        for it in links:
            self.assertIn('/book/3432/', it['url'])
            self.assertLess(len(it['title']), 41)

    def test_content_sample_yields_body(self):
        soup = self._bs4(_read('sitef_content.html'), 'html.parser')
        text = self.mod.extract_content(
            soup, 'https://www.sitef.example.com/book/3432/1.html',
            'https://www.sitef.example.com')
        self.assertIsNotNone(text, '正文样本应提取出内容')
        self.assertGreater(len(text), 1000, f'正文过短: {len(text)}')

    def test_paginate_declares_single_page(self):
        """单页章节: paginate 返回 None 显式停止, 通用规则不再瞎猜 _1.html
        续页 (瞎猜会 404 并污染爬取历史失败统计, 09-12 实测)。"""
        mod = _load_sitef_adapter()
        self.assertIsNone(mod.paginate('https://www.sitef.example.com/book/3432/1.html', 1))

    def test_title_from_catalog_sample(self):
        soup = self._bs4(_read('sitef_catalog.html'), 'html.parser')
        title = self.mod.get_title(
            soup, 'https://www.sitef.example.com/book/3432/',
            'https://www.sitef.example.com')
        self.assertEqual(title, '我的美母教师')


class TestSortSampleIndex(unittest.TestCase):
    """_排序样本下标 (2026-10-03, 修 K30 日志洪水时引入)。

    这组测试的由来: 降级日志时把调用处写成 `for i, chap in _排序样本下标(...)`
    而该函数返回 int 下标 → 运行时 "cannot unpack non-iterable int object",
    **584 单测 + 41 手写回归全绿却没抓到** (EXE 实测跑真站才暴露)。
    故此处既测函数本身, 也用源码级断言钉死"调用处不得解包"。
    """

    def setUp(self):
        import 爬虫
        self.爬虫 = 爬虫

    def test_zero_and_small_are_full(self):
        f = self.爬虫._排序样本下标
        self.assertEqual(f(0), [])
        self.assertEqual(f(1), [0])
        self.assertEqual(f(3), [0, 1, 2])
        # <= 样本数*2 时全量返回 (10 <= 5*2)
        self.assertEqual(f(10), list(range(10)))

    def test_large_returns_head_and_tail(self):
        f = self.爬虫._排序样本下标
        idx = f(2019)
        self.assertEqual(idx, [0, 1, 2, 3, 4, 2014, 2015, 2016, 2017, 2018])
        # 头尾不重叠、无重复、升序
        self.assertEqual(len(idx), len(set(idx)))
        self.assertEqual(idx, sorted(idx))

    def test_result_usable_as_plain_int_index(self):
        """返回值必须能直接当下标用 —— 这正是原先解包报错的根因。"""
        chapters = [{'title': f'第{i}章', 'url': f'/c/{i}'} for i in range(2019)]
        for i in self.爬虫._排序样本下标(len(chapters)):
            self.assertIsInstance(i, int)
            _ = chapters[i]['title']      # 不应抛 TypeError/ValueError
            _ = chapters[i]['url']

    def test_call_sites_must_not_unpack(self):
        """源码级护栏: 调用处不得把返回值解包成多个变量。

        判据用正则 `for A, B in ..._排序样本下标(` —— 不能用 `split('in ')`:
        `for` 自身含 "in "，会把切点落在 for 上而让判据恒为假
        (第一版就这么写坏的: 注入错误写法 69 个测试仍全绿)。
        """
        import inspect
        import re
        src = inspect.getsource(self.爬虫)
        bad = [ln.strip() for ln in src.splitlines()
               if re.search(r'for\s+\w+\s*,\s*\w+\s+in\s+_排序样本下标\(', ln)]
        self.assertEqual(bad, [], f'调用处出现了解包写法: {bad}')


class TestNovelPathIndexList(unittest.TestCase):
    """_resolve_novel_paths 模式5 扩展 (2026-10-03)。

    某书吧站目录页形如 /{书号}/indexlist.html (书号含大写字母), 章节链接
    /{书号}/{N}.html。旧模式5正则只认「小写书号 + index.html/index_N.html」,
    两道限制都匹配不上 → novel_path 为空 → 通用提取的 `novel_path and
    novel_path in href` 恒假, 即使分页处理器重新取到真页面也判 0 章节
    (61 个链接全部被过滤, 日志可见"链接 12: 第 1 篇 -> /{书号}/1.html")。
    """

    def setUp(self):
        import 爬虫
        self.解析 = 爬虫._resolve_novel_paths

    def test_indexlist_with_upper_book_id(self):
        self.assertEqual(
            self.解析('https://www.example.com/mmHJ/indexlist.html'),
            ('/mmHJ/', '/mmHJ/'))

    def test_indexlist_lower_book_id(self):
        self.assertEqual(
            self.解析('https://www.example.com/mmhj/indexlist.html'),
            ('/mmhj/', '/mmhj/'))

    def test_legacy_index_page_still_works(self):
        """原 banlvzw 形态 /4y9k/index_1.html 不得回归。"""
        self.assertEqual(
            self.解析('https://www.example.com/4y9k/index_1.html'),
            ('/4y9k/', '/4y9k/'))
        self.assertEqual(
            self.解析('https://www.example.com/ab12/index.html'),
            ('/ab12/', '/ab12/'))

    def test_upper_book_id_plain_index(self):
        """扩展大写支持后 /AbC12/index.html 也能提取 (原返回空)。"""
        self.assertEqual(
            self.解析('https://www.example.com/AbC12/index.html'),
            ('/AbC12/', '/AbC12/'))

    def test_earlier_patterns_take_precedence(self):
        """模式2/3 (小写前缀+数字ID) 优先级高于模式5, 不得被扩展改变。"""
        self.assertEqual(
            self.解析('https://www.example.com/books/301597.html'),
            ('/books/301597/', '/books/301597/'))
        self.assertEqual(
            self.解析('https://www.example.com/infos/5523629.html'),
            ('/infos/5523629/', '/infos/5523629/'))

    def test_plain_root_still_empty(self):
        self.assertEqual(self.解析('https://www.example.com/'), ('', ''))


class _FakeWafResp:
    """脚本化响应: 覆盖检测器/WAF循环访问到的最小属性面。"""

    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text
        self.content = text.encode('utf-8')
        self.headers = {}
        self.url = 'https://www.example.com/x'
        self.encoding = 'utf-8'
        self.apparent_encoding = 'utf-8'


# 裸 401 质询页形态 (meta-refresh + Set-Cookie, 无任何已知反爬特征)
_BARE_401_BODY = ('<html><head><meta http-equiv="refresh" content="0">'
                  '</head><body></body></html>')
_REAL_PAGE_BODY = ('<html><body><div id="real">真页面标记</div>'
                   '</body></html>')


class _ScriptedSession:
    """按脚本顺序吐响应的假会话, 记录每次 get 调用。"""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append({'url': url, 'headers': headers})
        if not self._responses:
            raise AssertionError(f'脚本响应耗尽, 第 {len(self.calls)} 次调用: {url}')
        return self._responses.pop(0)


class TestBareWafChallengeRetry(unittest.TestCase):
    """裸 401/403 质询页必须重发而非当正文返回 (2026-10-03)。

    某书吧站 WAF 三段式 (实测):
      ① 无/过期 _wa_ cookie → 401 + meta-refresh 小页面 (无任何已知特征)
      ② 带 _wa_ → 401 + @wafjs JS 质询页 (检测器置信度 0.90 可识别)
      ③ 浏览器解出令牌 cookie → 200
    旧实现在 ① 直接把质询页当真实页面返回: 适配器找不到容器 return None、
    通用提取 0 章节 → "目录无章节"死书。修复后在 WAF 循环新增第 3 关:
    401/403 且 body <4KB → 视为裸质询, 延迟重发。
    """

    @classmethod
    def setUpClass(cls):
        from 爬虫 import NovelSpider
        cls.spider = NovelSpider('https://www.example.com')  # 离线可构造 (~0.8s)

    @classmethod
    def tearDownClass(cls):
        cls.spider.close()

    def setUp(self):
        import unittest.mock as _mock
        # 测试内所有 sleep 瞬时完成 (裸质询重发固定 sleep(1))
        _sleep_patcher = _mock.patch('time.sleep')
        _sleep_patcher.start()
        self.addCleanup(_sleep_patcher.stop)

    def _inspect(self, path, responses):
        session = _ScriptedSession(responses)
        self.spider.session = session
        url = f'https://www.example.com/{path}'
        soup = self.spider.inspect_page(url, polite_delay=False)
        return session, soup

    def test_bare_401_then_200_recovers(self):
        """裸 401 → 重发 → 200: 必须拿到真页面, 恰好发 2 次请求。"""
        session, soup = self._inspect('bare401_ok/index.html', [
            _FakeWafResp(401, _BARE_401_BODY),
            _FakeWafResp(200, _REAL_PAGE_BODY),
        ])
        self.assertEqual(len(session.calls), 2)
        self.assertIn('真页面标记', str(soup))

    def test_bare_401_loop_is_bounded(self):
        """始终裸 401: 重发有界 (WAF 循环 4 轮), 不得死循环, 最终返回最后一次页面。"""
        session, soup = self._inspect('bare401_loop/index.html', [
            _FakeWafResp(401, _BARE_401_BODY),
        ] * 10)
        # 首次 + 每轮 1 次重发 = 5 次
        self.assertEqual(len(session.calls), 5)
        self.assertIn('refresh', str(soup))   # 返回的是质询页本身, 不崩溃

    def test_large_401_body_not_retried(self):
        """401 但 body >=4KB: 不视为裸质询 (真实内容页可能 403/401 附大页面), 只发 1 次。"""
        big = '<html><body>' + 'x' * 5000 + '</body></html>'
        session, soup = self._inspect('bare401_big/index.html', [
            _FakeWafResp(401, big),
        ])
        self.assertEqual(len(session.calls), 1)
        self.assertIn('xxxx', str(soup))

    def test_wafjs_challenge_still_solved_by_stage2(self):
        """@wafjs 质询体必须由第 2 关 (浏览器解令牌) 处理, 不得被第 3 关截胡。"""
        import unittest.mock as _mock
        challenge = ('<html><body>Loading...<script src="/@wafjs?x=1">'
                     '</script></body></html>')
        # 检测器会对 @wafjs 返回 waf_js_challenge → 引擎分支会调 cloudscraper
        # (真实网络 I/O) → 测试中置空实例级引擎管理器, 验证"保留原响应走
        # 现有流程"后第 2 关接管的路径。
        原引擎 = self.spider._引擎管理器
        self.spider._引擎管理器 = None
        self.addCleanup(setattr, self.spider, '_引擎管理器', 原引擎)
        with _mock.patch.object(self.spider, '_solve_waf_js_challenge',
                                return_value=True) as solve:
            session, soup = self._inspect('wafjs_stage2/index.html', [
                _FakeWafResp(401, challenge),
                _FakeWafResp(200, _REAL_PAGE_BODY),
            ])
        solve.assert_called_once()
        self.assertEqual(len(session.calls), 2)
        self.assertIn('真页面标记', str(soup))

    def test_200_never_retried(self):
        """正常 200: WAF 循环不触发任何重发。"""
        session, soup = self._inspect('ok200/index.html', [
            _FakeWafResp(200, _REAL_PAGE_BODY),
        ])
        self.assertEqual(len(session.calls), 1)
        self.assertIn('真页面标记', str(soup))


class TestContentPaginationNone(unittest.TestCase):
    """适配器声明 content_pagination: None (单页直出) 不得炸正文提取 (K35)。

    hulaisb 适配器 SITE 写有 "content_pagination": None (单页直出意图)。
    get_chapter_content 旧守卫 'content_pagination' in site_pattern 只查键存在,
    None.get('max_pages', 30) 抛 TypeError, 被 _fetch_with_qc 吞成
    "[质检] 抓取异常: 'NoneType' object has no attribute 'get'" →
    全部章节 ~0.5s 瞬时空正文 (hulaisb task_9 2026-10-03 实测, 5 篇全灭)。
    修后: None → 视为无 dict 分页配置, 且第 2 页直接停止、不构造 _1.html。
    URL 全部 example.com 脱钩。
    """

    @classmethod
    def setUpClass(cls):
        from 爬虫 import NovelSpider
        cls.spider = NovelSpider('https://www.example.com')  # 离线可构造 (~0.8s)

    @classmethod
    def tearDownClass(cls):
        cls.spider.close()

    def setUp(self):
        import unittest.mock as _mock
        from bs4 import BeautifulSoup
        # 站点配置: hulaisb 形态 —— html_selector 模式 + content_pagination=None。
        # pattern 用 generic 走通用检测, 避免 html_selector 提取器真实取页。
        site_pattern = {
            'domain': 'example.com',
            'pattern': 'generic',
            'content_pagination': None,      # 单页直出 (K35 触发点)
        }
        p1 = _mock.patch('爬虫.get_site_pattern', return_value=site_pattern)
        p1.start()
        self.addCleanup(p1.stop)
        # 外部适配器缺席 (分页/正文都落通用路径)
        p2 = _mock.patch('sites_config.get_adapter', return_value=None)
        p2.start()
        self.addCleanup(p2.stop)
        # 数据文件探测不命中 (hulaisb 真站走 .word, 离线无需覆盖)
        p3 = _mock.patch('content_decoder.decode_chapter_data',
                         return_value=('', ''))
        p3.start()
        self.addCleanup(p3.stop)
        # 页面请求全部 mock: 恒定最小页面, 记录收到的 URL
        self.inspected_urls = []
        _soup = BeautifulSoup(
            '<html><body><div id="content">测试正文内容。</div></body></html>',
            'html.parser')

        def _fake_inspect(url, *args, **kwargs):
            self.inspected_urls.append(url)
            return _soup

        p4 = _mock.patch.object(type(self.spider), 'inspect_page',
                                side_effect=_fake_inspect)
        p4.start()
        self.addCleanup(p4.stop)
        # 清洗统计 contextvar 无关紧要; 睡眠瞬时化 (防通用路径退避)
        p5 = _mock.patch('time.sleep')
        p5.start()
        self.addCleanup(p5.stop)

    def test_none_pagination_no_typeerror(self):
        """K35 主断言: content_pagination=None 时 get_chapter_content 不抛 TypeError。"""
        content = self.spider.get_chapter_content(
            'https://www.example.com/book/1.html')
        self.assertIsInstance(content, str)

    def test_none_pagination_never_builds_page2_url(self):
        """单页直出第 2 页必须停止: 任何后续请求都不得是 _1.html 形态。"""
        self.spider.get_chapter_content('https://www.example.com/book/1.html')
        for u in self.inspected_urls:
            self.assertNotIn('_1.html', u,
                             f'单页直出站点不应构造分页 URL: {u}')

    def test_dict_pagination_still_reads_max_pages(self):
        """回归保护: content_pagination 为 dict 时 max_pages 照常生效。"""
        import unittest.mock as _mock
        site_pattern = {
            'domain': 'example.com',
            'pattern': 'generic',
            'content_pagination': {'max_pages': 1},
        }
        p = _mock.patch('爬虫.get_site_pattern', return_value=site_pattern)
        p.start()
        self.addCleanup(p.stop)
        # max_pages=1 → 只请求第 1 页; 不抛异常即守卫未破坏
        content = self.spider.get_chapter_content(
            'https://www.example.com/book/1.html')
        self.assertIsInstance(content, str)


class TestServerErrorRetry(unittest.TestCase):
    """5xx 错误页必须重试而非当正文返回 (K36, 2026-10-03)。

    shuhaige 源站间歇 502: 目录页 GET → 502 + "502 Bad Gateway" 错误页,
    旧实现把错误页当正常响应解析 → 书名 "502 Bad Gateway" → 0 章节 →
    死书[目录无章节] (误导用户查选择器)。修后 inspect_page 对 5xx
    与网络异常同等重试 (3 次退避), 耗尽返回空 soup → 死书判定走
    "站点不可达" (_目录页为空=True)。URL 全部 example.com 脱钩。
    """

    @classmethod
    def setUpClass(cls):
        from 爬虫 import NovelSpider
        cls.spider = NovelSpider('https://www.example.com')

    @classmethod
    def tearDownClass(cls):
        cls.spider.close()

    def setUp(self):
        import unittest.mock as _mock
        _sleep_patcher = _mock.patch('time.sleep')
        _sleep_patcher.start()
        self.addCleanup(_sleep_patcher.stop)

    def _inspect(self, path, responses):
        session = _ScriptedSession(responses)
        self.spider.session = session
        # 每用例独立 URL: inspect_page 有 20s TTL 缓存, 同 URL 会命中缓存跳过请求
        soup = self.spider.inspect_page(
            f'https://www.example.com/{path}', polite_delay=False)
        return session, soup

    def test_502_then_200_recovers(self):
        """502 → 重试 → 200: 必须拿到真页面, 恰好发 2 次请求。"""
        session, soup = self._inspect('502_ok/index.html', [
            _FakeWafResp(502, _BARE_401_BODY),
            _FakeWafResp(200, _REAL_PAGE_BODY),
        ])
        self.assertEqual(len(session.calls), 2)
        self.assertIn('真页面标记', str(soup))

    def test_persistent_502_bounded_and_empty(self):
        """恒 502: 重试 3 次有界, 最终返回空 soup (站点不可达信号, 不崩溃)。"""
        session, soup = self._inspect('502_loop/index.html',
                                      [_FakeWafResp(502, _BARE_401_BODY)] * 10)
        self.assertEqual(len(session.calls), 3)
        self.assertEqual(str(soup).strip(), '',
                         '5xx 耗尽必须返回空 soup (触发 _目录页为空 → 站点不可达)')

    def test_503_also_retried(self):
        """503 同样重试 (与 502 同族)。"""
        session, soup = self._inspect('503_ok/index.html', [
            _FakeWafResp(503, _BARE_401_BODY),
            _FakeWafResp(200, _REAL_PAGE_BODY),
        ])
        self.assertEqual(len(session.calls), 2)
        self.assertIn('真页面标记', str(soup))

    def test_404_not_retried(self):
        """404 不是服务器错误: 不重试 (资源真不存在, 重试无意义)。"""
        session, soup = self._inspect('404_once/index.html',
                                      [_FakeWafResp(404, '<html><body>404</body></html>')])
        self.assertEqual(len(session.calls), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
