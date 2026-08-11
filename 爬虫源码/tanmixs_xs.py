# -*- coding: utf-8 -*-
"""tanmixs .xs 正文数据文件解析器

机制: tanmixs 章节正文存放在 js.tanmixs.com/data/chapter/.../N.xs,
格式为 _txt_call({"content":"..."}) 的 JSON, content 为编码后的字符流:
  - 4 位十六进制 = 单个字符的 Unicode 码点
  - ASCII 明文直接保留 (标点/数字/英文)
  - 高频常用字被压缩为控制字符 (\x05-\x10 等), 映射表在文件末尾的 JSON 中
  - 分隔符: \x01 (码点间), \x02 (字组开始), \x03, \x04 (换行)

解析后可直接获得与网站阅读页一致的完整正文 (不丢字), 无需浏览器渲染。

安全: 所有动态 URL 均经过域名白名单 + 公网地址校验 (防 SSRF)。
"""

import re
import json
import requests

try:
    from sites_config import validate_public_url
except ImportError:
    def validate_public_url(url):
        """本地兜底: 仅允许公网 http/https"""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            raise ValueError("仅允许 http/https")
        if not parsed.hostname:
            raise ValueError("缺少 host")


# 允许的数据文件域名白名单 (防 SSRF: 只信任站点自身 CDN)
_ALLOWED_XS_HOSTS = ('js.tanmixs.com',)


def _validate_xs_url(url):
    """校验 .xs 数据 URL: 协议合法 + 域名白名单 + 公网地址"""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        raise ValueError(f"仅允许 http/https: {url}")
    host = (parsed.hostname or '').lower()
    if host not in _ALLOWED_XS_HOSTS:
        raise ValueError(f"数据文件域名不在白名单: {host}")
    validate_public_url(url)


def _json_safe(text):
    """将 JSON 字符串中的字面控制字符转为 \\uXXXX 转义 (json.loads 拒绝裸控制字符)"""
    return re.sub(
        r'[\x00-\x1f]',
        lambda m: '\\u%04x' % ord(m.group(0)),
        text)


def parse_xs(raw):
    """解析 .xs 文件内容, 返回完整正文文本。

    数据结构: _txt_call({"content":"...","replace":{...}})
      - content: 压缩字符流 (\x01=\\;&#x, \x02=&#x 为 HTML 实体分隔,
        4位hex=Unicode码点, 高频字被压缩为控制字符)
      - replace: 高频字压缩映射 {"码点":"\\xNN"}

    Args:
        raw: .xs 文件原始文本

    Returns:
        str: 还原后的完整正文; 失败返回 ''
    """
    if not raw:
        return ''
    # 1. 整体 JSON 解析 (content + replace), 需先转义裸控制字符
    m = re.search(r'_txt_call\((\{.*\})\)\s*$', raw, flags=re.S)
    if not m:
        return ''
    try:
        data = json.loads(_json_safe(m.group(1)))
    except Exception:
        return ''
    content = data.get('content', '')
    replace = data.get('replace', {})
    if not content:
        return ''

    # 2. 构建 控制字符->原字 映射 (replace: {码点: 控制字符})
    mapping = {}
    for code, ctrl in replace.items():
        if isinstance(ctrl, str) and len(ctrl) == 1 and ord(ctrl) < 32:
            if re.fullmatch(r'[0-9a-fA-F]{2,6}', code):
                mapping[ctrl] = chr(int(code, 16))

    # 3. 还原字符流
    # 码点识别规则: 4位hex仅在其前一个是实体分隔符(\x01/\x02/\x03)或 ( 时才是码点,
    # 避免把明文数字(如 2016/6836)误判为十六进制码点
    tokens = re.findall(r'[\x00-\x1f]|[0-9a-fA-F]{4}|[^\x00-\x1f]', content)
    result = []
    prev = ''
    for t in tokens:
        if t in mapping:
            result.append(mapping[t])  # 高频字压缩还原 (的/我/一/了/,/。/不)
        elif t in ('\x01', '\x02', '\x03'):
            prev = t
            continue  # 实体分隔符
        elif t == '\x04':
            result.append('\n')  # 换行
        elif t == ';':
            prev = t
            continue  # 实体结构残留分号, 渲染时不显示
        elif re.fullmatch(r'[0-9a-fA-F]{4}', t):
            if prev in ('\x01', '\x02', '\x03', '('):
                try:
                    result.append(chr(int(t, 16)))
                except Exception:
                    pass
            else:
                result.append(t)  # 明文数字/字母
        else:
            result.append(t)  # ASCII 明文
        prev = t if t not in ('\x01', '\x02', '\x03', ';') else prev
    return ''.join(result)


def _fetch(url, headers=None):
    """受限 GET: 仅白名单公网域名 (防 SSRF)"""
    _validate_xs_url(url)
    return requests.get(url, timeout=30, headers=headers or {})


def fetch_chapter_content(chapter_id_url, page=1):
    """按章节页 URL 获取正文 (自动解析 .xs 数据文件)。

    Args:
        chapter_id_url: 章节页 URL (如 https://m.tanmixs.com/YzN6/1.html)
        page: 分页页码 (1=第一页)

    Returns:
        str: 完整正文; 失败返回 ''
    """
    try:
        # 0. 章节页 URL 本身也必须合法公网地址
        validate_public_url(chapter_id_url)
        if 'tanmixs.com' not in chapter_id_url:
            return ''

        # 1. 获取章节页 HTML, 提取 .xs 数据 URL
        resp = requests.get(chapter_id_url, timeout=30, headers={
            'User-Agent': 'Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
            'Referer': chapter_id_url,
        })
        if resp.status_code != 200:
            return ''
        m = re.search(r'(https?://js\.tanmixs\.com/data/chapter/[^"\']+?\.xs)', resp.text)
        if not m:
            m = re.search(r'(//js\.tanmixs\.com/data/chapter/[^"\']+?\.xs)', resp.text)
            if not m:
                return ''
            xs_url = 'https:' + m.group(1)
        else:
            xs_url = m.group(1)
        # 分页: 第N页的 xs URL 是 第1页URL 替换末尾页码
        if page > 1:
            xs_url = re.sub(r'/(\d+)\.xs$', f'/{page}.xs', xs_url)

        # 2. 下载 .xs 数据文件 (白名单 + 公网校验)
        r = _fetch(xs_url, headers={
            'User-Agent': 'Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
            'Referer': chapter_id_url,
        })
        if r.status_code != 200 or not r.text.strip():
            return ''
        return parse_xs(r.text)
    except Exception:
        return ''
