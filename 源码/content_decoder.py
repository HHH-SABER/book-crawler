# -*- coding: utf-8 -*-
"""
通用小说正文解码器 (所有站点可用)
==================================

**背景**: 部分小说站把章节正文存放在独立的数据文件中 (页面仅引用),
且数据经过压缩/编码 (如 tanmixs 的 .xs 十六进制码点流 + 高频字压缩映射)。
旧流程仅靠浏览器渲染提取, 会丢失被压缩的常用字, 导致文章不通顺。

**本模块通用化能力**:
  1. 数据文件引用自动探测: 从任意章节页 HTML 发现正文数据文件
     (initTxt/loadChapter/data-src/getChapter 等常见调用模式)
  2. 数据文件安全校验: 与章节页同域(含 CDN 子域) + 公网地址 (防 SSRF)
  3. 通用码点流解析: 十六进制 Unicode 码点流 + 高频字压缩映射还原
  4. 多格式自动尝试: 码点流 → JSON(content字段) → 纯文本 → Base64

**使用**: 爬虫在常规提取之前调用 decode_chapter_data() 即可,
对任何站点自动生效; 无数据文件或解析失败时返回 None, 走原流程。
"""

import re
import json
import base64
import ipaddress
from urllib.parse import urlparse

import requests

# ============================================================
# 1. 数据文件引用探测
# ============================================================

# 常见的数据文件引用模式: (正则, 说明)
# 数据文件常见后缀: .xs (tanmixs) / .book (banlvzw 伴侣中文网) / .data / .txt / .json
_DATA_EXT = r'(?:xs|book|data|txt|json)'
DATA_REF_PATTERNS = [
    (r'initTxt\s*\(\s*["\']([^"\']+?\.' + _DATA_EXT + r')["\']', 'initTxt()'),
    (r'loadChapter\s*\(\s*["\']([^"\']+)["\']', 'loadChapter()'),
    (r'getChapter\s*\(\s*["\']([^"\']+)["\']', 'getChapter()'),
    (r'data-src\s*=\s*["\']([^"\']+\.(?:' + _DATA_EXT + r'|js))["\']', 'data-src'),
    (r'["\']([^"\']*?/(?:data|chapter|content)/[^"\']+\.(?:' + _DATA_EXT + r'))["\']', 'data路径'),
    (r'\.load\s*\(\s*["\']([^"\']+\.(?:txt|html|data))["\']', '.load()'),
]


def detect_data_refs(html):
    """从章节页 HTML 探测正文数据文件引用。

    Returns:
        list[(url, kind)]: 去重后的数据文件 URL 与引用类型
    """
    refs = []
    seen = set()
    for pattern, kind in DATA_REF_PATTERNS:
        for m in re.finditer(pattern, html):
            u = m.group(1).strip()
            if u and u not in seen:
                seen.add(u)
                refs.append((u, kind))
    return refs


# ============================================================
# 2. 数据文件安全校验 (防 SSRF)
# ============================================================

def _reg_domain(host):
    """提取注册域 (取最后两段, 处理常见多段后缀)"""
    parts = host.split('.')
    if len(parts) <= 2:
        return host
    # 常见二级后缀: com.cn / net.cn / org.cn / com.hk 等
    two_level = {'com', 'net', 'org', 'gov', 'edu', 'ac', 'co', 'hk', 'tw', 'jp'}
    if parts[-2] in two_level and len(parts) >= 3:
        return '.'.join(parts[-3:])
    return '.'.join(parts[-2:])


def validate_data_url(chapter_url, data_url):
    """校验数据文件 URL: 协议合法 + 与章节页同注册域(含CDN子域) + 公网地址

    Args:
        chapter_url: 章节页 URL (信任来源)
        data_url: 数据文件 URL (动态, 需校验)

    Returns:
        str: 校验后的绝对 URL; 非法时抛出 ValueError
    """
    # 协议相对路径 (//host/path) 先补全为 https
    if data_url.startswith('//'):
        data_url = 'https:' + data_url
    p = urlparse(data_url)
    if p.scheme not in ('http', 'https'):
        # 站点相对路径 (/data/... 或 data/...): 拼上章节页域名
        cp = urlparse(chapter_url)
        if not cp.scheme or not cp.hostname:
            raise ValueError(f"数据文件路径非法: {data_url}")
        if data_url.startswith('/'):
            data_url = f"{cp.scheme}://{cp.hostname}{data_url}"
        else:
            data_url = f"{cp.scheme}://{cp.hostname}/{data_url}"
        p = urlparse(data_url)
        if p.scheme not in ('http', 'https'):
            raise ValueError(f"数据文件协议非法: {data_url}")
    host = (p.hostname or '').lower()
    if not host:
        raise ValueError(f"数据文件缺少主机: {data_url}")

    # 与章节页同注册域 (允许 CDN 子域, 如 js.tanmixs.com vs m.tanmixs.com)
    cp = urlparse(chapter_url)
    chapter_host = (cp.hostname or '').lower()
    if not chapter_host:
        raise ValueError(f"章节页 URL 非法: {chapter_url}")
    if _reg_domain(host) != _reg_domain(chapter_host):
        raise ValueError(f"数据文件域名与章节页不同域: {host}")

    # 公网地址校验 (仅当 host 是 IP 字面量时)
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip and (ip.is_private or ip.is_loopback or ip.is_link_local
               or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
        raise ValueError(f"数据文件指向内网地址: {host}")

    # 拼接绝对 URL (协议相对路径 //xxx 补 https:)
    if data_url.startswith('//'):
        return 'https:' + data_url
    return data_url


# ============================================================
# 3. 通用码点流解析 (十六进制 Unicode + 高频字压缩映射)
# ============================================================

def _json_safe(text):
    """将 JSON 字符串中的字面控制字符转为 \\uXXXX 转义 (json.loads 拒绝裸控制字符)"""
    return re.sub(r'[\x00-\x1f]', lambda m: '\\u%04x' % ord(m.group(0)), text)


def parse_codepoint_stream(content, replace_map=None):
    """解析压缩字符流为正文文本。

    格式:
      - 4位十六进制 = Unicode 码点 (两种写法都支持)
          a) x 前缀:  "x6700"          (tanmixs 的 .xs)
          b) 裸码点:  "\x01 6700"      (ciyewk 的 .book, 由前缀标记引导)
      - 前缀标记 \x01 / \x02 / \x03 表示其后 4 位十六进制是码点
          (原始 HTML 实体分别为 ";&#x" / "&#x" / ";&#", 压缩时被整体替换)
      - \x04 = 换行 (原始 ";\n")
      - 高频字被压缩为控制字符, 映射表 {码点: 控制字符} 由 replace_map 提供
      - 明文 ASCII 直接保留; 孤立 ; 为实体残留, 不显示

    Args:
        content: 压缩字符流 (str)
        replace_map: {码点字符串: 控制字符} 映射, 用于还原高频字。
            键为 2-6 位十六进制时按"压缩字"处理; 形如 ";&#x" 的非十六进制键
            表示前缀标记/换行, 不参与映射。

    Returns:
        str: 还原后的正文
    """
    mapping = {}
    if replace_map:
        for code, ctrl in replace_map.items():
            if isinstance(ctrl, str) and len(ctrl) == 1 and ord(ctrl) < 32:
                if re.fullmatch(r'[0-9a-fA-F]{2,6}', code):
                    mapping[ctrl] = chr(int(code, 16))

    # 分词顺序很重要 (P1-7 修复):
    #   ① x+4位hex        → x 前缀码点 (tanmixs)
    #   ② 4位hex          → 裸码点, 仅当前一个 token 是前缀标记时才解码
    #                        (ciyewk 等站点把 ";&#x6700;" 压成 "\x016700")
    #   ③ 单个控制字符     → 压缩字 / 前缀标记 / 换行
    #   ④ 其它单字符       → 明文
    #
    # 旧实现的第一个候选是 "控制字符 + x码点" 的合并模式, 会把紧邻码点的压缩字
    # 吞进一个 6 字符 token: mapping 查不到 (键是单字符), 又不匹配纯 x码点,
    # 最终落入 else 原样输出 —— 高频字整段丢失, 正文出现裸控制字符。
    # 改为逐字符切分 + 循环内判定前缀标记后, 压缩字与码点都能正确还原。
    tokens = re.findall(r'x[0-9a-fA-F]{4}|[0-9a-fA-F]{4}|[\x00-\x1f]|[^\x00-\x1f]',
                        content)
    result = []
    pending_marker = False   # 上一个 token 是未被 mapping 消费的前缀标记
    for t in tokens:
        # 前缀标记后的裸码点 (P2-7: ciyewk 连续码点流支持)
        if pending_marker and re.fullmatch(r'[0-9a-fA-F]{4}', t):
            pending_marker = False
            try:
                result.append(chr(int(t, 16)))
            except ValueError:
                result.append(t)
            continue
        pending_marker = False

        if t in mapping:
            result.append(mapping[t])
        elif t in ('\x01', '\x02', '\x03'):
            # 未被 mapping 消费时才是"前缀标记"; 否则它本身是压缩字, 已在上一步输出
            pending_marker = True
            continue
        elif t == '\x04':
            result.append('\n')
        elif t == ';':
            continue
        elif len(t) == 5 and t[0] == 'x':
            # x 前缀码点。旧逻辑要求前导为分隔符才解码, 否则尝试解码并兜底保留;
            # 两条分支行为一致, 这里合并为"解码失败才回退原 token"。
            try:
                result.append(chr(int(t[1:], 16)))
            except ValueError:
                result.append(t)
        elif t < ' ':
            # 未映射的控制字符: 无还原依据, 直接丢弃 (与旧分词规则行为一致)
            continue
        else:
            result.append(t)
    return ''.join(result)


def _looks_like_content(text):
    """验证解码结果是否为有效正文 (含 HTML 标签或足够中文)"""
    if not text:
        return False
    if '<p' in text or '<br' in text:
        return True
    chinese = len(re.findall(r'[\u4e00-\u9fff]', text))
    return chinese > 20 or (chinese > 5 and len(text) > 100)


# ============================================================
# 4. 数据文件多格式解码
# ============================================================

def decode_data(raw):
    """尝试多种数据格式解码, 返回 (正文文本, 使用的方法名)。

    依次尝试:
      1. _txt_call({content, replace}) 码点流 (tanmixs 风格)
      2. 直接 JSON 对象含 content 字段
      3. 纯文本 (本身即正文)
      4. Base64 编码文本
    """
    if not raw:
        return None, None
    stripped = raw.strip()

    # 1. 函数包装 JSON: _txt_call({...}) / loadTxt({...}) 等
    m = re.search(r'[a-zA-Z_]\w*\s*\(\s*(\{.*\})\s*\)\s*$', stripped, flags=re.S)
    if m:
        try:
            data = json.loads(_json_safe(m.group(1)))
            content = data.get('content', '')
            if content:
                text = parse_codepoint_stream(content, data.get('replace'))
                if _looks_like_content(text):
                    return text, 'codepoint_stream'
                # content 可能是纯文本
                if _looks_like_content(content):
                    return content, 'json_content'
        except Exception:
            pass

    # 2. 直接 JSON 对象
    try:
        data = json.loads(_json_safe(stripped))
        if isinstance(data, dict):
            for key in ('content', 'text', 'chapter', 'body', 'data'):
                val = data.get(key)
                if isinstance(val, str) and _looks_like_content(val):
                    return val, f'json.{key}'
    except Exception:
        pass

    # 3. 纯文本
    if _looks_like_content(stripped):
        return stripped, 'plain_text'

    # 4. Base64
    try:
        decoded = base64.b64decode(stripped + '=' * (-len(stripped) % 4))
        for enc in ('utf-8', 'gbk', 'gb18030'):
            try:
                text = decoded.decode(enc)
                if _looks_like_content(text):
                    return text, 'base64'
            except Exception:
                continue
    except Exception:
        pass

    return None, None


# ============================================================
# 5. 统一入口
# ============================================================

def decode_chapter_data(chapter_url, page_html=None, page=1, headers=None):
    """对章节页自动探测并解码数据文件正文。

    Args:
        chapter_url: 章节页 URL
        page_html: 章节页 HTML (用于探测数据文件引用); None 时自动请求获取
        page: 分页页码 (1=第一页; 数据文件分页时替换末尾页码)
        headers: 请求头 (None 使用默认)

    Returns:
        (text, method): 解码正文与方法名; 无数据文件/失败返回 (None, None)
    """
    if page_html is None:
        # 自动请求章节页 (仅用于探测数据文件引用)
        # 安全校验: 协议 + 主机 + 公网地址 (防 SSRF)
        _p = urlparse(chapter_url)
        if _p.scheme not in ('http', 'https') or not _p.hostname:
            return None, None
        try:
            _ip = ipaddress.ip_address(_p.hostname)
            if _ip.is_private or _ip.is_loopback or _ip.is_link_local \
                    or _ip.is_reserved or _ip.is_multicast or _ip.is_unspecified:
                return None, None
        except ValueError:
            pass  # 域名, 按公网处理
        try:
            r = requests.get(chapter_url, timeout=30, headers=headers or {
                'User-Agent': 'Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 '
                              '(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
                'Referer': chapter_url,
            }, proxies={'http': None, 'https': None})  # 直连, 忽略系统代理
            if r.status_code != 200:
                return None, None
            page_html = r.text
        except Exception:
            return None, None
    refs = detect_data_refs(page_html)
    if not refs:
        return None, None
    hdrs = headers or {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
        'Referer': chapter_url,
    }
    for data_url, kind in refs:
        try:
            url = validate_data_url(chapter_url, data_url)
        except ValueError as e:
            print(f"[数据文件] 跳过非法引用 ({kind}): {e}")
            continue
        # 分页: 页码形式的文件名 (如 1.xs -> 2.xs, 1.book -> 2.book)
        if page > 1:
            url = re.sub(r'/(\d+)\.(xs|data|txt|json|book)$', f'/{page}.\\2', url)
        try:
            r = requests.get(url, timeout=30, headers=hdrs,
                             proxies={'http': None, 'https': None})  # 直连, 忽略系统代理
            if r.status_code != 200 or not r.text.strip():
                continue
            text, method = decode_data(r.text)
            if text:
                print(f"[数据文件] {kind} 解码成功: {method}, {len(text)} 字符")
                return text, method
        except Exception as e:
            print(f"[数据文件] 下载/解码失败 ({kind}): {e}")
    return None, None
