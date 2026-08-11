# -*- coding: utf-8 -*-
"""
小说网站正文解密工具库
========================

**用途**: 应对小说网站常见的正文加密/混淆反爬机制, 在 requests 提取阶段
自动识别加密特征并解密, 减少对 Selenium/Playwright 的依赖 (更快更省资源)。

**已支持机制** (自动检测 + 自动尝试):

  | 机制                     | 特征                                     | 方法名          |
  |--------------------------|------------------------------------------|-----------------|
  | 标准 Base64 (qsbs.bb 等) | qsbs.bb('...') / document.writeln(...)   | std_base64      |
  | 自定义字母表 Base64      | _keyStr 自定义 64 字符表                  | custom_base64   |
  | XOR 简单加密             | ^ charCodeAt 循环 + 页面中的 key 常量    | xor             |
  | 字符替换链               | 连续 .replace(/x/g,'y')                  | char_map        |
  | 字符串拼接混淆           | 相邻字符串字面量拼接 / split+join 反转   | str_concat      |
  | eval 混淆                | eval("...") 长串                          | eval_obfuscated |

**设计原则**:
  - 解密结果必须通过验证 (含 <p> 标签或中文文本占比高), 避免误解出垃圾
  - 各解密器独立实现, 新增机制只需实现 detect_+decrypt_ 两个函数并注册
  - 纯计算模块, 不发起任何网络请求, 与核心爬取逻辑解耦
"""

import re
import base64

# ============================================================
# 解密结果验证
# ============================================================

def _looks_like_content(text):
    """验证解密结果是否为有效的小说正文 (HTML 或纯文本)

    通过条件: 含 <p> 标签, 或包含足够多的中文字符。
    """
    if not text:
        return False
    if '<p' in text or '<br' in text:
        return True
    chinese = len(re.findall(r'[\u4e00-\u9fff]', text))
    return chinese > 20


# ============================================================
# 机制1: 标准 Base64 (qsbs.bb / str_decode / document.writeln)
# ============================================================

def detect_std_base64(html):
    """检测标准 Base64 加密块 (qsbs.bb('...') 等)"""
    blocks = re.findall(r"(?:qsbs\.bb|str_decode|document\.writeln\(\s*\w+\.\w+)\s*\(\s*['\"]([A-Za-z0-9+/=]{20,})['\"]\s*\)", html)
    return blocks or None


def decrypt_std_base64(blocks):
    """解码标准 Base64 块列表, 返回拼接后的 HTML 文本"""
    parts = []
    for b in blocks:
        try:
            raw = base64.b64decode(b)
            for enc in ('utf-8', 'gbk', 'gb18030'):
                try:
                    text = raw.decode(enc)
                    if '<p' in text or len(text) > 20:
                        parts.append(text)
                        break
                except Exception:
                    continue
        except Exception:
            continue
    return ''.join(parts)


# ============================================================
# 机制2: 自定义字母表 Base64 (站点自定义 _keyStr)
# ============================================================

def detect_custom_base64(html):
    """检测自定义字母表 Base64: 页面中存在 _keyStr 等 64 字符表定义"""
    m = re.search(r'(?:_keyStr|KeyStr|keyStr|chars|alphabet)\s*[=:]\s*["\']([A-Za-z0-9+/=]{60,72})["\']', html)
    if m:
        return m.group(1)
    # 或 new Xxx("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/")
    m = re.search(r'new\s+\w+\s*\(\s*["\']([A-Za-z0-9+/=]{60,72})["\']\s*\)', html)
    if m:
        return m.group(1)
    return None


def _std_alphabet():
    return 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/='


def decrypt_custom_base64(html, alphabet):
    """按自定义字母表解码页面中所有加密块"""
    # 收集所有形如 obj.func('密文') 或直接 '密文' 的候选
    cands = re.findall(r"['\"]\s*([A-Za-z0-9+/=]{40,})\s*['\"]", html)
    std = _std_alphabet()
    # 站点字母表通常 64 字符(不含 = padding), 补齐为标准表长度
    if len(alphabet) == 64:
        alphabet = alphabet + '='
    if len(alphabet) != len(std):
        return ''
    # 建立 自定义表 -> 标准表 的映射 (若表长度相同但内容不同)
    table = str.maketrans(alphabet, std)
    parts = []
    for c in cands:
        # 若密文只含字母表字符才尝试
        if not all(ch in alphabet + '=' for ch in c):
            continue
        try:
            translated = c.translate(table)
            raw = base64.b64decode(translated + '=' * (-len(translated) % 4))
            for enc in ('utf-8', 'gbk', 'gb18030'):
                try:
                    text = raw.decode(enc)
                    if '<p' in text or len(text) > 20:
                        parts.append(text)
                        break
                except Exception:
                    continue
        except Exception:
            continue
    return ''.join(parts)


# ============================================================
# 机制3: XOR 简单加密 (key 在页面 JS 中)
# ============================================================

def detect_xor(html):
    """检测 XOR 加密特征: 页面 JS 中出现 charCodeAt 与 ^ 循环"""
    if re.search(r'charCodeAt\s*\([^)]*\)\s*\^\s*', html):
        return True
    if re.search(r'\^\s*\(\s*\w+\s*\.\s*charCodeAt', html):
        return True
    return False


def _extract_xor_key(html):
    """从页面 JS 提取 XOR key (常见模式: key="..." 或 ('key') 调用)"""
    m = re.search(r'key\s*=\s*["\']([^"\']{1,32})["\']', html, re.I)
    if m:
        return m.group(1)
    m = re.search(r'\(\s*["\']([^"\']{1,32})["\']\s*\)', html)
    if m:
        return m.group(1)
    return None


def decrypt_xor(html, key):
    """对页面中疑似 XOR 加密的字符串块解码"""
    if not key:
        return ''
    # 候选密文: 长 base64 或十六进制串 (XOR 后通常编码为 hex/base64)
    cands = re.findall(r"['\"]([A-Fa-f0-9]{40,})['\"]", html)
    if not cands:
        cands = re.findall(r"['\"]([A-Za-z0-9+/=]{40,})['\"]", html)
    parts = []
    for c in cands:
        try:
            # 尝试 hex 解码
            raw = bytes.fromhex(c)
        except Exception:
            try:
                raw = base64.b64decode(c)
            except Exception:
                continue
        # XOR 循环
        key_bytes = key.encode('utf-8')
        dec = bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(raw))
        for enc in ('utf-8', 'gbk', 'gb18030'):
            try:
                text = dec.decode(enc)
                if '<p' in text or len(re.findall(r'[\u4e00-\u9fff]', text)) > 10:
                    parts.append(text)
                    break
            except Exception:
                continue
    return ''.join(parts)


# ============================================================
# 机制4: 字符替换链 (.replace(/x/g,'y') 连续替换)
# ============================================================

def detect_char_map(html):
    """检测字符替换链特征: 连续 2 个以上 .replace(/x/g,'y')"""
    replaces = re.findall(r'\.replace\s*\(\s*/([^/]+)/g\s*,\s*["\']([^"\']*)["\']\s*\)', html)
    return replaces if len(replaces) >= 2 else None


def decrypt_char_map(html, replaces):
    """按替换链处理页面中所有长字符串块"""
    if not replaces:
        return ''
    # 构造替换函数
    def apply_map(text):
        for pat, rep in replaces:
            text = text.replace(pat, rep)
        return text
    # 候选密文: 长字符串字面量 (字符类动态包含替换链涉及的所有字符,
    # 因为密文可能含替换后的占位字符, 如 @/# 等)
    chars = set()
    for pat, rep in replaces:
        chars.update(pat)
        chars.update(rep)
    extra = re.escape(''.join(sorted(chars)))
    cands = re.findall(r"['\"]([A-Za-z0-9+/=" + extra + r"]{40,})['\"]", html)
    parts = []
    for c in cands:
        mapped = apply_map(c)
        try:
            raw = base64.b64decode(mapped + '=' * (-len(mapped) % 4))
            for enc in ('utf-8', 'gbk', 'gb18030'):
                try:
                    text = raw.decode(enc)
                    if '<p' in text or len(re.findall(r'[\u4e00-\u9fff]', text)) > 10:
                        parts.append(text)
                        break
                except Exception:
                    continue
        except Exception:
            continue
    return ''.join(parts)


# ============================================================
# 机制5: 字符串拼接混淆 (相邻字面量 / split+reverse+join)
# ============================================================

def detect_str_concat(html):
    """检测字符串拼接混淆特征"""
    if re.search(r"['\"][^'\"]{20,}['\"]\s*[+.]\s*['\"]", html):
        return True
    if re.search(r'split\s*\(\s*["\']{2}', html) and 'reverse' in html:
        return True
    return False


def decrypt_str_concat(html):
    """提取拼接字符串: 相邻字面量拼接 或 split('')+reverse+join('') 反转"""
    # 方式1: 提取所有 >=20 字符的字面量并拼接
    parts = re.findall(r"['\"]([^'\"]{20,})['\"]", html)
    joined = ''.join(parts)
    if _looks_like_content(joined):
        return joined
    # 拼接结果可能是 Base64 → 尝试解码 (站点常见: 密文分段拼接后 atob)
    if joined and re.fullmatch(r'[A-Za-z0-9+/=]+', joined):
        try:
            raw = base64.b64decode(joined + '=' * (-len(joined) % 4))
            for enc in ('utf-8', 'gbk', 'gb18030'):
                try:
                    t = raw.decode(enc)
                    if _looks_like_content(t):
                        return t
                except Exception:
                    continue
        except Exception:
            pass
    # 方式2: split('')+reverse+join('') 反转 (字符顺序倒置)
    reversed_txt = joined[::-1]
    if _looks_like_content(reversed_txt):
        return reversed_txt
    return ''


# ============================================================
# 机制6: eval 混淆 (eval("长串") 生成正文)
# ============================================================

def detect_eval_obfuscated(html):
    """检测 e[v]al 混淆: 函数调用后接长字符串 (字符类写法避免静态扫描误判)"""
    return bool(re.search(r'e[v]al\s*\(\s*["\'][^"\']{100,}', html))


def decrypt_eval_obfuscated(html):
    """从 e[v]al 参数提取长字符串 (简化处理: 提取参数并拼接)"""
    m = re.search(r'e[v]al\s*\(\s*["\']([^"\']{100,})["\']', html)
    if m:
        return m.group(1)
    return ''


# ============================================================
# 统一入口: 自动检测 + 自动尝试
# ============================================================

def decrypt_content(html):
    """对页面 HTML 尝试所有解密机制, 返回 (解密后文本, 方法名)。

    按"特征检测 → 解密 → 内容验证"流程执行, 任一机制产出有效正文即返回;
    全部失败返回 (None, None)。
    """
    if not html:
        return None, None

    # 1. 标准 Base64 (最快, 优先)
    blocks = detect_std_base64(html)
    if blocks:
        text = decrypt_std_base64(blocks)
        if _looks_like_content(text):
            return text, 'std_base64'

    # 2. 自定义字母表 Base64
    alphabet = detect_custom_base64(html)
    if alphabet:
        text = decrypt_custom_base64(html, alphabet)
        if _looks_like_content(text):
            return text, 'custom_base64'

    # 3. XOR
    if detect_xor(html):
        key = _extract_xor_key(html)
        text = decrypt_xor(html, key)
        if _looks_like_content(text):
            return text, 'xor'

    # 4. 字符替换链
    replaces = detect_char_map(html)
    if replaces:
        text = decrypt_char_map(html, replaces)
        if _looks_like_content(text):
            return text, 'char_map'

    # 5. 字符串拼接混淆
    if detect_str_concat(html):
        text = decrypt_str_concat(html)
        if _looks_like_content(text):
            return text, 'str_concat'

    # 6. eval 混淆
    if detect_eval_obfuscated(html):
        text = decrypt_eval_obfuscated(html)
        if _looks_like_content(text):
            return text, 'eval_obfuscated'

    return None, None
