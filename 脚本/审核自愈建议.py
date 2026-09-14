# -*- coding: utf-8 -*-
"""选择器自愈建议审核 CLI (批3 PoC-B, 方案 A 的人工审核入口)。

用法 (在仓库根, .venv 环境):
    python 脚本/审核自愈建议.py list              # 查看待审建议 (置信度降序)
    python 脚本/审核自愈建议.py adopt <域名>      # 采纳: 并入 站点配置.json 并热重载
    python 脚本/审核自愈建议.py reject <域名>     # 拒绝: 仅移除建议, 配置不动

工作流: 抓取中规则选择器全部落空 → 选择器自愈.py 把候选写入
数据/选择器建议.json (待审) → 本脚本审核。采纳后 content_selectors 前插
新选择器 (旧选择器保留兜底), reload_runtime_config() 当前进程立即生效。

(未来站点管理页可内嵌同一审核闭环; CLI 先行, 核心逻辑在 选择器自愈.列出待审/
采纳建议/拒绝建议, 脚本只做展示与参数解析。)
"""
import io
import os
import sys

# 中文输出防御 (cp1252 控制台 print 中文会 UnicodeEncodeError, 同 release CI 教训)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass  # 刻意静默: stdout 已被重定向时 reconfigure 必然失败, 仅丢 UTF-8 优化不影响构建

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, '源码'))

import 选择器自愈 as heal  # noqa: E402


def _fmt(item: dict) -> str:
    旧 = ', '.join(item.get('原选择器') or []) or '—'
    return (f"  域名      : {item.get('域名')}\n"
            f"  建议选择器: {item.get('建议选择器')}\n"
            f"  原选择器  : {旧}\n"
            f"  置信度    : {item.get('置信度')}  容器: 中文 {item.get('容器中文数')} 字"
            f" / {item.get('段落数')} 段\n"
            f"  发现时间  : {item.get('生成时间', '(旧条目)')}\n")


def cmd_list():
    items = heal.列出待审()
    if not items:
        print('✔ 无待审建议 (数据/选择器建议.json 为空或不存在)')
        return 0
    print(f'待审建议 {len(items)} 条 (置信度降序):\n')
    for it in items:
        print(_fmt(it))
        print('  ' + '-' * 56)
    print('\n处理: python 脚本/审核自愈建议.py adopt <域名> | reject <域名>')
    return 0


def cmd_adopt(domain: str):
    ok, msg = heal.采纳建议(domain)
    print(('✔ ' if ok else '✘ ') + msg)
    return 0 if ok else 1


def cmd_reject(domain: str):
    ok, msg = heal.拒绝建议(domain)
    print(('✔ ' if ok else '✘ ') + msg)
    return 0 if ok else 1


def main(argv):
    if len(argv) < 2 or argv[1] in ('-h', '--help'):
        print(__doc__)
        return 0
    action = argv[1].lower()
    if action == 'list':
        return cmd_list()
    if action in ('adopt', 'reject'):
        if len(argv) < 3:
            print(f'用法: {os.path.basename(__file__)} {action} <域名>')
            return 2
        domain = argv[2].strip()
        return cmd_adopt(domain) if action == 'adopt' else cmd_reject(domain)
    print(f'未知操作: {action} (可用: list / adopt / reject)')
    return 2


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
