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

    def test_worker_restores_and_closes_session(self):
        """_fetch_chapter_worker 用独立 Session 执行, 结束后复位并关闭。"""
        from unittest import mock
        import requests
        from 爬虫 import NovelSpider
        spider = NovelSpider('https://www.example.com')
        main = spider._main_session
        captured = {}
        closed_ids = []

        class SpySession(requests.Session):
            """记录 close() 调用 —— requests 的 Session.close() 不会清空
            adapters 字典, 无法从外部观测, 只能靠间谍子类。"""

            def close(self):
                closed_ids.append(id(self))
                super().close()

        # 用假实现替换 _fetch_with_qc, 只验证 Session 生命周期, 不触网
        def fake_qc(chap):
            captured['session'] = spider.session
            captured['is_main'] = spider.session is main
            return '正文'

        spider._fetch_with_qc = fake_qc
        try:
            with mock.patch.object(requests, 'Session', SpySession):
                spider._fetch_chapter_worker({'title': '第一章', 'url': '/1.html'})

            self.assertIsNotNone(captured.get('session'))
            self.assertFalse(captured['is_main'], 'worker 内应拿到独立 Session')
            self.assertIs(spider.session, main, 'worker 结束后本线程应复位为主 Session')
            self.assertIn(id(captured['session']), closed_ids,
                          '临时 Session 未关闭, 连接池泄漏 (旧实现从不关闭)')
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


if __name__ == '__main__':
    unittest.main(verbosity=2)
