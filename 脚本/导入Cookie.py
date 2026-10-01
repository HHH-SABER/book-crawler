# -*- coding: utf-8 -*-
"""Cookie 导入工具: 把浏览器复制的 Cookie 串写入 域名cookies.json。

用法 (项目根):
    python 脚本\\导入Cookie.py example.com
然后按提示粘贴从浏览器复制的 Cookie 串 (整行, 带不带 "Cookie: " 前缀都行),
回车即写入。写入后 30 秒内自动生效, 无需重启程序。

适用于任何需要登录态的站点 (域名作参数); 数据文件不入库。
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '源码'))
from _path_utils import get_app_base_dir   # noqa: E402


def main():
    域 = (sys.argv[1] if len(sys.argv) > 1 else '').strip().lower()
    if not 域:
        print('用法: python 脚本\\导入Cookie.py <域名>   (例: python 脚本\\导入Cookie.py example.com)')
        return 1
    print(f'== 导入 {域} 的登录 Cookie ==')
    print('粘贴从浏览器复制的 Cookie 串 (整行; 带 "Cookie: " 前缀或引号都可以), 然后回车:')
    try:
        raw = input('> ').strip()
    except EOFError:
        print('未读到输入, 退出')
        return 1
    if not raw:
        print('空输入, 退出')
        return 1
    # 清洗: 去 "Cookie:" 前缀 / 引号 / 首尾空白
    s = raw.strip()
    if s.lower().startswith('cookie:'):
        s = s[7:].strip()
    s = s.strip('"').strip("'").strip()
    if not s:
        print('清洗后为空 (只复制了 "Cookie:" 前缀?), 退出')
        return 1
    if '=' not in s:
        print('⚠ 内容里没有 "=" —— 浏览器 Cookie 至少是 name=value 形态, 请确认复制的是 Cookie 值而不是别的头')
        return 1

    目标 = os.path.join(get_app_base_dir(), '站点适配_本地', '域名cookies.json')
    os.makedirs(os.path.dirname(目标), exist_ok=True)
    表 = {}
    if os.path.isfile(目标):
        try:
            with open(目标, 'r', encoding='utf-8') as f:
                表 = json.load(f)
            if not isinstance(表, dict):
                表 = {}
        except Exception:
            表 = {}   # 原文件损坏时重建 (Cookie 串可随时从浏览器重取, 无历史价值)
    表[域] = s
    tmp = 目标 + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(表, f, ensure_ascii=False, indent=1)
    os.replace(tmp, 目标)
    print(f'✅ 已写入 {目标} (键: {域}, 长度 {len(s)} 字符)')
    print('30 秒内自动生效 (热加载), 无需重启程序。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
