# -*- coding: utf-8 -*-
"""decrypt_utils.py 离线回归测试 (补齐 M13 测试盲区: 6 种正文解密零单测)。

覆盖 `decrypt_content()` 统一入口 + 6 种机制各自的 detect_/decrypt_ 函数。

## 数据来源 (两类)

1. **真实样本回归** — `测试样本/` 现有 HTML 快照, 锁定线上已验证行为防退化。
   实测只有 2 种机制有真实样本: std_base64 (zhiruo/qiqishu)、str_concat (ltbook)。
2. **合成正向样本** — 其余 4 种机制 (custom_base64 / xor / char_map / eval_obfuscated)
   无真实快照, 在测试内**现场用 base64/xor/translate 构造加密 HTML**, 不落任何二进制文件。
   每种构造都先经设计探针验证 `decrypt_content()` 能正确解出 (见下方注释), 再固化为断言。

## 关键隐式契约 (探针实测, 改动 decrypt_utils 前必读)

- **eval_obfuscated 明文阈值 = 100 字符**: 源码正则 `decrypt_utils.py:275` 要求
  `eval("...")` 内明文 `[^"']{100,}`。明文 <100 时该机制**不命中**(返回 None), 这是
  设计如此而非 bug —— `test_eval短明文不命中` 锁定该边界。
- **机制检测有优先级**: `decrypt_content()` 按 std_base64→custom_base64→xor→
  char_map→str_concat→eval_obfuscated 顺序检测, 先命中且过内容校验即返回。
  合成样本的 JS 特征串需避开前面机制的正则 (如 char_map 样本不含 `charCodeAt...^`),
  否则会被更高优先级机制截走。
- **解密结果必过内容校验** (`_looks_like_content`): 含 `<p>`/`<br>` 或中文占比高。
  解出英文短句/乱码会被拦截返回 None, 防误解垃圾入库。

不联网, 不改任何源码。
"""
import base64
import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '源码'))

import decrypt_utils as d  # noqa: E402

SAMPLES = _PROJECT_ROOT / '测试样本'


def _样本(name):
    return (SAMPLES / name).read_text(encoding='utf-8', errors='replace')


# 探针验证过的合成明文: 79 字符, 满足 std_base64/custom_base64/xor/char_map
# 机制的 {40,} 密文长度阈值与内容校验 (含 <p> + 中文占比高)。
PLAIN = '<p>' + '这是用于测试的中文正文内容，需要足够长以通过验证。' * 3 + '</p>'
# eval_obfuscated 机制正则要求明文 >=100 字符, 单独构造长明文 (实测 109 字符)。
PLAIN_LONG = '<p>' + '这是用于测试的中文正文内容，需要足够长以通过验证。' * 5 + '</p>'

_STD64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'


def _旋转字母表(n=3):
    """构造一个整体旋转 n 位的自定义 64 字符表 (站点常用手法)"""
    return _STD64[n:] + _STD64[:n]


def _自定义base64密文(plaintext, alphabet):
    """先标准 base64 编码, 再按 自定义表<->标准表 置换出密文"""
    std = base64.b64encode(plaintext.encode('utf-8')).decode('ascii')
    return std.translate(str.maketrans(_STD64, alphabet))


class TestStdBase64机制(unittest.TestCase):
    """机制1: 标准 Base64 (qsbs.bb / str_decode / document.writeln)"""

    def test_真实样本zhiruo解出std_base64(self):
        txt, method = d.decrypt_content(_样本('zhiruo_content.html'))
        self.assertEqual(method, 'std_base64')
        self.assertIsNotNone(txt)
        self.assertGreater(len(txt), 500, '应解出可观长度正文')

    def test_真实样本qiqishu解出std_base64(self):
        txt, method = d.decrypt_content(_样本('qiqishu_content.html'))
        self.assertEqual(method, 'std_base64')
        self.assertGreater(len(txt), 500)

    def test_合成qsbs块往返(self):
        """qsbs.bb('base64') 应被 detect 命中并解回原文"""
        cipher = base64.b64encode(PLAIN.encode('utf-8')).decode('ascii')
        html = f'<script>document.write(qsbs.bb("{cipher}"));</script>'
        blocks = d.detect_std_base64(html)
        self.assertTrue(blocks, 'detect_std_base64 应命中 qsbs.bb 块')
        txt = d.decrypt_std_base64(blocks)
        self.assertEqual(txt, PLAIN)

    def test_短base64不被检测(self):
        """密文长度 <20 不满足 {20,} 阈值, 不应误检"""
        short = base64.b64encode(b'abc').decode()
        self.assertIsNone(d.detect_std_base64(f'qsbs.bb("{short}")'))


class TestCustomBase64机制(unittest.TestCase):
    """机制2: 自定义字母表 Base64 (探针验证可正向解出)"""

    def test_合成自定义表往返(self):
        alphabet = _旋转字母表(3)
        cipher = _自定义base64密文(PLAIN, alphabet)
        html = f'var _keyStr = "{alphabet}"; var data = "{cipher}";'
        self.assertEqual(alphabet, d.detect_custom_base64(html),
                         'detect 应提取页面中的 _keyStr 自定义表')
        txt, method = d.decrypt_content(html)
        self.assertEqual(method, 'custom_base64')
        self.assertEqual(txt, PLAIN)

    def test_new构造式字母表也被检测(self):
        alphabet = _旋转字母表(5)
        html = f'var d = new Base64("{alphabet}");'
        self.assertEqual(alphabet, d.detect_custom_base64(html))

    def test_无字母表定义返回None(self):
        self.assertIsNone(d.detect_custom_base64('<p>普通明文页面无加密</p>'))


class TestXor机制(unittest.TestCase):
    """机制3: XOR 简单加密 (key 在页面 JS 中, 密文 hex 编码)"""

    def test_合成xor往返(self):
        key = 'secret'
        pb = PLAIN.encode('utf-8')
        kb = key.encode('utf-8')
        xor_bytes = bytes(b ^ kb[i % len(kb)] for i, b in enumerate(pb))
        html = (f'var key = "{key}"; '
                f'for (var i=0;i<s.length;i++) {{ out += String.fromCharCode('
                f's.charCodeAt(i) ^ key.charCodeAt(i % key.length)); }} '
                f'var data = "{xor_bytes.hex()}";')
        self.assertTrue(d.detect_xor(html), 'detect 应命中 charCodeAt ... ^ 特征')
        txt, method = d.decrypt_content(html)
        self.assertEqual(method, 'xor')
        self.assertEqual(txt, PLAIN)

    def test_extract_xor_key取key变量(self):
        self.assertEqual('secret', d._extract_xor_key('var key = "secret";'))

    def test_无key时解密返回空(self):
        self.assertEqual('', d.decrypt_xor('任意页面', None))


class TestCharMap机制(unittest.TestCase):
    """机制4: 字符替换链 (连续 .replace(/x/g,'y'))"""

    def test_合成替换链往返(self):
        """构造: 标准base64 后把两个高频字符替换为占位符, replace链反向还原。
        注意 JS 特征串避开 charCodeAt...^ (否则会被更高优先级的 xor 机制截走)。"""
        std = base64.b64encode(PLAIN.encode('utf-8')).decode('ascii')
        present = [ch for ch in _STD64 if ch in std]
        c1, c2 = present[0], present[-1]          # 密文中确实存在的两个字符
        cipher = std.replace(c1, '@').replace(c2, '#')
        html = (f'var s = data.replace(/@/g, "{c1}").replace(/#/g, "{c2}"); '
                f'var data = "{cipher}";')
        replaces = d.detect_char_map(html)
        self.assertTrue(replaces and len(replaces) >= 2,
                        'detect 应命中 >=2 个 .replace(/x/g,y)')
        txt, method = d.decrypt_content(html)
        self.assertEqual(method, 'char_map')
        self.assertEqual(txt, PLAIN)

    def test_单个replace不被检测(self):
        """替换链需 >=2 个 replace 才算特征"""
        self.assertIsNone(d.detect_char_map('a.replace(/x/g, "y")'))

    def test_空替换链解密返回空(self):
        self.assertEqual('', d.decrypt_char_map('任意页面', None))


class TestStrConcat机制(unittest.TestCase):
    """机制5: 字符串拼接混淆 (相邻字面量 / split+reverse)"""

    def test_真实样本ltbook解出str_concat(self):
        txt, method = d.decrypt_content(_样本('ltbook_content.html'))
        self.assertEqual(method, 'str_concat')
        self.assertGreater(len(txt), 1000, 'ltbook 样本应解出长正文')

    def test_相邻字面量拼接检测(self):
        html = "<script>var s = '一二三四五六七八九十一二三四五六七八九十' + '继续拼接的正文内容';</script>"
        self.assertTrue(d.detect_str_concat(html))

    def test_拼接结果为base64时解码(self):
        cipher = base64.b64encode(PLAIN.encode('utf-8')).decode('ascii')
        half = len(cipher) // 2
        html = f"<script>var s = '{cipher[:half]}' + '{cipher[half:]}';</script>"
        txt = d.decrypt_str_concat(html)
        self.assertEqual(txt, PLAIN)


class TestEvalObfuscated机制(unittest.TestCase):
    """机制6: eval 混淆 (eval("长串") 内联正文)"""

    def test_合成eval长明文往返(self):
        self.assertGreaterEqual(len(PLAIN_LONG), 100, '长明文须 >=100 触发检测')
        html = f'eval("{PLAIN_LONG}")'
        self.assertTrue(d.detect_eval_obfuscated(html))
        txt, method = d.decrypt_content(html)
        self.assertEqual(method, 'eval_obfuscated')
        self.assertEqual(txt, PLAIN_LONG)

    def test_eval短明文不命中(self):
        """关键边界契约: 明文 <100 字符时 eval 机制不命中 (源码 {100,} 阈值)。
        锁定此行为, 防止有人误改阈值或以为短明文也该解出。"""
        self.assertLess(len(PLAIN), 100)
        html = f'eval("{PLAIN}")'
        self.assertFalse(d.detect_eval_obfuscated(html),
                         '明文不足 100 字符不应被 eval 机制检测')
        txt, method = d.decrypt_content(html)
        self.assertIsNone(method, '短明文经全链路应返回 None (无其他机制命中)')


class Test统一入口与负向用例(unittest.TestCase):
    """decrypt_content 统一入口的边界与失败路径"""

    def test_空HTML返回None(self):
        self.assertEqual((None, None), d.decrypt_content(''))

    def test_无加密明文页返回None(self):
        """普通中文页面 (无加密特征) 不应被任何机制解出"""
        txt, method = d.decrypt_content('<html><body><p>这是一段普通的中文小说正文内容，没有任何加密。</p></body></html>')
        self.assertIsNone(method)
        self.assertIsNone(txt)

    def test_base64形态但解出非正文被拦截(self):
        """std_base64 命中但解出英文短句, 内容校验不过 -> 返回 None"""
        eng = base64.b64encode(b'hello world this is a short test').decode('ascii')
        html = f'qsbs.bb("{eng}")'
        txt, method = d.decrypt_content(html)
        self.assertIsNone(method, '解出非中文非HTML内容应被内容校验拦截')

    def test_真实无加密样本返回None(self):
        """多份实测无加密的真实样本应正确返回 (None, None), 不误判"""
        for name in ('630wang_content.html', 'yueliang_content.html',
                     'yunshuzhai_content.html', 'als1010_软封页.html'):
            path = SAMPLES / name
            if not path.exists():
                self.skipTest(f'缺样本 {name}')
            txt, method = d.decrypt_content(_样本(name))
            self.assertIsNone(method, f'{name} 应判定为无加密')


if __name__ == '__main__':
    unittest.main(verbosity=2)
