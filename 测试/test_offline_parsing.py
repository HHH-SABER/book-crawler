# -*- coding: utf-8 -*-
"""离线回归测试: 使用 测试样本/ 中的真实页面快照验证解析逻辑, 全程不联网。

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

SAMPLES = _PROJECT_ROOT / '测试样本'


def _read(name: str) -> str:
    return (SAMPLES / name).read_text(encoding='utf-8')


# 正文特征串: 三份样本实际是同一部小说的开篇 (晨读迟到场景)
FEATURE_OPENING = '晨读的声音在校园里回'


# ============================================================
# 1. sites_config 正文提取
# ============================================================

class TestQsbsBbExtraction(unittest.TestCase):
    """qsbs.bb Base64 加密模式 (zhiruo / 云趣阁 / biquwx / ahxsw)。"""

    def test_zhiruo_sample_decodes_to_novel_text(self):
        from sites_config import extract_content_qsbs_bb
        html = _read('zhiruo_content.html')
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

    def test_630wang_word_read(self):
        from sites_config import extract_content_html_selector
        html = _read('630wang_content.html')
        text = extract_content_html_selector(
            html, ['div.word_read', '.word_read', '#content', '.content'])
        self.assertGreater(len(text), 3000, f'630wang 正文过短: {len(text)}')
        self.assertIn(FEATURE_OPENING, text)

    def test_ltbook_junk_filter_removes_obfuscation(self):
        """ltbook 正文混有 &ap;ap;...toigdata 多层实体混淆, junk_filter 必须清干净。"""
        from sites_config import extract_content_html_selector
        html = _read('ltbook_content.html')
        text = extract_content_html_selector(
            html, ['#rtext', '#content', 'div#content'], extractor='ltbook_junk_filter')
        self.assertGreater(len(text), 3000, f'ltbook 正文过短: {len(text)}')
        self.assertIn(FEATURE_OPENING, text)
        self.assertNotIn('toigdata', text, '混淆片段未清除')
        self.assertNotIn('ap;', text, '孤立 ap; 残留未清除')


# ============================================================
# 2. content_decoder 数据文件解码
# ============================================================

class TestDecodeData(unittest.TestCase):
    """decode_data 多格式解码 (tanmixs .xs / banlvzw .book 等数据文件模式)。"""

    def test_codepoint_stream_with_x_prefix(self):
        """x 前缀码点流 (tanmixs 风格, 无压缩映射): x7b2c=第 x4e00=一 x7ae0=章。"""
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

    def test_ciyewk_continuous_hex_stream(self):
        """【P2-7 回归】ciyewk 的裸码点流 (无 x 前缀, 由 \\x01/\\x02/\\x03 引导)。

        数据形如 "\\x026606\\x013001;(...": 前缀标记后的 4 位十六进制即码点,
        其余控制字符查 replace 表还原高频字, ';' 是实体残留分隔符, \\x04 是换行。
        旧实现只认 x 前缀 token, 整段码点被当成明文字母输出 (解码失败)。
        生产环境此前靠 Selenium 渲染兜底, 现已可直接解码 .book 数据文件。"""
        from content_decoder import decode_data
        raw = _read('ciyewk_1.book')
        text, method = decode_data(raw)
        self.assertIsNotNone(text, 'ciyewk 裸码点流应被解码')
        self.assertEqual(method, 'codepoint_stream')
        self.assertGreater(len(text), 1000)
        self.assertIn(FEATURE_OPENING, text)
        # 还原质量: 汉字应占绝对多数, 且不应残留未还原的控制字符 (换行除外)
        chinese = len(re.findall(r'[\u4e00-\u9fff]', text))
        self.assertGreater(chinese / len(text), 0.6)
        self.assertEqual(len(re.findall(r'[\x00-\x1f]', text.replace('\n', ''))), 0)


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
        """区间式标题 (630wang/ltbook 两章合一页): 第1-2章 取起始章号。"""
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
        """'找回新域名'类广告行 (banlvzw 移动版实测: '最新找回4F4F4F,C〇M') 须清除。"""
        raw = ('第一段正常叙事内容，足够长度跨越短行阈值，句子结构完整。\n'
               '最新找回4F4F4F,C〇M\n'
               '第二段正常叙事内容，继续推进情节发展不受影响。')
        cleaned = self.spider.clean_content(raw)
        self.assertNotIn('找回4F4F', cleaned, '找回站广告行未被过滤')
        self.assertIn('第一段正常叙事内容', cleaned)


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
        """H2: ciyewk 真实 .book 携带非空压缩映射 — replace_map 非空是双实现
        最易漂移且此前零覆盖的场景。开关 Rust 路径对比全文逐字符一致。"""
        import content_decoder
        raw = _read('ciyewk_1.book')
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
# 5. yunshuzhai: 章节页→目录页规范化 + 样本解析契约 (2026-09-11 事故)
# ============================================================

def _load_yunshuzhai_adapter():
    """直接按路径加载适配器模块 (不依赖 ADAPTERS 注册表, 与加载路径解耦)"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'site_adapter_yunshuzhai_test',
        str(_PROJECT_ROOT / '站点适配' / 'yunshuzhai.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestYunshuzhaiCatalogFromChapter(unittest.TestCase):
    """用户把章节页 URL 当任务 URL: 通用管线把章节页当目录页解析, 只剩
    "目录"链接 1 个"章节", 把详情页当正文抓 → 整单失败 (09-11 实测)。
    适配器用 catalog_from_chapter 声明章节页→目录页推导, run() 在解析前调用。"""

    def test_chapter_url_to_catalog(self):
        f = _load_yunshuzhai_adapter().catalog_from_chapter
        self.assertEqual(
            f('https://www.yunshuzhai.com/book/3432/1.html'),
            'https://www.yunshuzhai.com/book/3432/')
        self.assertEqual(
            f('https://yunshuzhai.com/book/7/99.html'),
            'https://yunshuzhai.com/book/7/')

    def test_non_chapter_urls_return_none(self):
        f = _load_yunshuzhai_adapter().catalog_from_chapter
        self.assertIsNone(f('https://www.yunshuzhai.com/book/3432/'))  # 目录页本身
        self.assertIsNone(f('https://www.yunshuzhai.com/search.html'))
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
        cls.mod = _load_yunshuzhai_adapter()
        from bs4 import BeautifulSoup
        cls._bs4 = BeautifulSoup

    def test_catalog_sample_yields_chapter_list(self):
        soup = self._bs4(_read('yunshuzhai_catalog.html'), 'html.parser')
        links = self.mod.parse_catalog(
            soup, 'https://www.yunshuzhai.com/book/3432/',
            'https://www.yunshuzhai.com')
        self.assertIsNotNone(links, '目录样本应解析出章节列表')
        self.assertGreater(len(links), 5, f'章节数过少: {len(links)}')
        for it in links:
            self.assertIn('/book/3432/', it['url'])
            self.assertLess(len(it['title']), 41)

    def test_content_sample_yields_body(self):
        soup = self._bs4(_read('yunshuzhai_content.html'), 'html.parser')
        text = self.mod.extract_content(
            soup, 'https://www.yunshuzhai.com/book/3432/1.html',
            'https://www.yunshuzhai.com')
        self.assertIsNotNone(text, '正文样本应提取出内容')
        self.assertGreater(len(text), 1000, f'正文过短: {len(text)}')

    def test_title_from_catalog_sample(self):
        soup = self._bs4(_read('yunshuzhai_catalog.html'), 'html.parser')
        title = self.mod.get_title(
            soup, 'https://www.yunshuzhai.com/book/3432/',
            'https://www.yunshuzhai.com')
        self.assertEqual(title, '我的美母教师')


if __name__ == '__main__':
    unittest.main(verbosity=2)
