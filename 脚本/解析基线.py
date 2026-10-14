# -*- coding: utf-8 -*-
"""解析基线: 对真实形态样本跑 get_chapter_list 全链路, 输出可对比的 JSON 快照。

用途 (阶段二 拆爬虫.py 的安全网): 拆分前后各跑一次, diff 必须为空 ——
证明拆分**零行为变化**。基线文件入库 (文档/解析基线.json), 是回归资产。

覆盖 5 份形态样本 (全部脱敏, URL 一律 siteN.example.com):
  siteq_目录_真实页   完整大目录 (通用路径)
  tianqiu_目录        折叠目录 (宣称远大于首页可见)
  washai_目录         分页目录首页
  siteg_访问验证页    验证页 (质询信号)
  siteg_软封页        软封页 (非验证)

用法:
    .runtime\\python314\\python.exe 脚本\\解析基线.py            # 跑并写 文档/解析基线.json
    .runtime\\python314\\python.exe 脚本\\解析基线.py --对比      # 跑并与入库基线对比
"""
import io
import json
import os
import sys
from pathlib import Path
from unittest import mock

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

样本目录 = _根 / '测试' / '样本'
基线文件 = _根 / '文档' / '解析基线.json'

样本们 = [
    # (样本文件, 占位目录 URL)
    ('siteq_目录_真实页.html', 'https://site1.example.com/read/588165/'),
    ('tianqiu_目录.html', 'https://site31.example.com/wenku/147-147006.html'),
    ('washai_目录.html',
     'https://site61.example.com/book/indexList-1262260513468564878.html'),
    ('siteg_访问验证页.html', 'https://siteg.example.com/verify'),
    ('siteg_软封页.html', 'https://siteg.example.com/soft-block'),
]


def _造爬虫():
    """不触网络的 NovelSpider 实例 (mock __init__, 补齐链路必要属性)。"""
    import 爬虫 as C
    import threading
    with mock.patch.object(C.NovelSpider, '__init__', lambda self, *a, **k: None):
        s = C.NovelSpider()
    s.base_url = ''
    s.last_request_error = ''
    s.last_status_code = 200
    s._目录页为空 = False
    s._目录页被质询 = False
    s._inspect_cache = {}
    s._inspect_cache_lock = threading.Lock()
    return s


def _快照(样本文件: str, url: str) -> dict:
    from bs4 import BeautifulSoup
    s = _造爬虫()
    html = (样本目录 / 样本文件).read_bytes().decode('utf-8', errors='replace')

    def _假inspect(u, *a, **k):
        # 一律返回样本 (2026-10-14 实测: 链路会对目录 URL 请求多次 ——
        # #a-list 锚点/折叠站"完整目录"二次请求, 按书号或计数判断都会漏)。
        # 多页样本 (washai) 的第 2 页会重复首页 ⇒ 章数虚高, 但**前后一致**,
        # 作为"拆分零行为变化"的对比基线仍然有效 (要的是 diff 为空)。
        return BeautifulSoup(html, 'lxml')

    with mock.patch.object(s, 'inspect_page', side_effect=_假inspect):
        chapters = s.get_chapter_list(url, sort_chapters=False)
    摘 = [{'title': c.get('title', '')[:40], 'url': c.get('url', '')[-60:]}
          for c in (chapters[:3] + chapters[-2:] if chapters else [])]
    return {
        '章数': len(chapters),
        '前3后2': 摘,
        '目录页为空': bool(s._目录页为空),
        '目录页被质询': bool(s._目录页被质询),
        'html长度': len(html),
    }


def main() -> int:
    对比 = '--对比' in sys.argv
    结果 = {}
    for 样本文件, url in 样本们:
        结果[样本文件] = _快照(样本文件, url)
        print(f"[基线] {样本文件}: {结果[样本文件]['章数']} 章 "
              f"(为空={结果[样本文件]['目录页为空']}, "
              f"被质询={结果[样本文件]['目录页被质询']})")
    if 对比:
        if not 基线文件.is_file():
            print('[FAIL] 无入库基线可比 (先跑一次不带 --对比 的)')
            return 1
        旧 = json.loads(基线文件.read_text(encoding='utf-8'))
        if 旧 == 结果:
            print('[PASS] 与入库基线完全一致 (拆分零行为变化)')
            return 0
        print('[FAIL] 与入库基线有差异:')
        for k in set(旧) | set(结果):
            if 旧.get(k) != 结果.get(k):
                print(f'  {k}:\n    旧={json.dumps(旧.get(k), ensure_ascii=False)[:200]}'
                      f'\n    新={json.dumps(结果.get(k), ensure_ascii=False)[:200]}')
        return 1
    基线文件.parent.mkdir(parents=True, exist_ok=True)
    基线文件.write_text(json.dumps(结果, ensure_ascii=False, indent=2),
                        encoding='utf-8')
    print(f'[DONE] 基线已写入 {基线文件}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
