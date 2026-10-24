# -*- coding: utf-8 -*-
"""正文基线：对章节样本离线跑「正文抽取 + 清洗」全链路，输出可对比的**指标快照**。

用途（拆 `爬虫.py` 的安全网，S1 第三步）
---------------------------------------
`get_chapter_content()` 728 行 + `_extract_content_from_html()` 481 行是第二块要拆的大肉。
拆前必须能证明"零行为变化"。`脚本/解析基线.py` 只覆盖**目录解析**链路，本脚本补**正文**链路：
抽取前后各跑一次，`--对比` 的 JSON diff 必须为空。

红线（重要）
------------
入库的 `文档/正文基线.json` **只存指标与哈希，绝不存正文/首尾文字** ——
正文是项目的硬红线（禁抓取内容入库）。所以每条只记：
字数 / 段落数 / 图片数 / 归一化正文的 `blake2b` 哈希 / 是否为空。

用法
----
    .runtime\\python314\\python.exe 脚本\\正文基线.py          # 跑并写 文档/正文基线.json
    .runtime\\python314\\python.exe 脚本\\正文基线.py --对比    # 跑并与入库基线对比
"""
import hashlib
import json
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / '源码'))
sys.path.insert(0, str(_ROOT / '脚本'))

样本目录 = _ROOT / '测试样本_本地'
基线文件 = _ROOT / '文档' / '正文基线.json'

#: 样本清单**不放代码里**（避免真实站点代号入库）：从 gitignored 的
#: `测试样本_本地/正文基线样本.json` 读取，格式 `[[样本文件名, 章节页URL], ...]`；
#: 文件缺失（公开形态）⇒ 无样本可跑，脚本安全跳过。
样本清单文件 = 样本目录 / '正文基线样本.json'


def 读样本清单(样本根=None) -> list:
    清单 = (pathlib.Path(样本根) / '正文基线样本.json') if 样本根 else 样本清单文件
    if not 清单.is_file():
        return []
    try:
        data = json.loads(清单.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    出 = []
    for 项 in data if isinstance(data, list) else []:
        if isinstance(项, (list, tuple)) and len(项) >= 2:
            出.append((str(项[0]), str(项[1])))
    return 出


class _假响应:
    """替代 requests.Response（正文抽取只用到 .content 做二进制级扫描）。"""

    def __init__(self, 原始: bytes):
        self.content = 原始
        self.text = 原始.decode('utf-8', 'replace')
        self.status_code = 200
        self.headers = {'Content-Type': 'text/html; charset=utf-8'}
        self.encoding = 'utf-8'
        self.url = ''
        self.apparent_encoding = 'utf-8'


def _归一化(文本: str) -> str:
    """只用于算哈希：去行首尾空白 + 折叠连续空白（不影响字数口径）。"""
    行s = [' '.join(x.split()) for x in (文本 or '').splitlines()]
    return '\n'.join(x for x in 行s if x)


def _哈希(文本: str) -> str:
    归一 = _归一化(文本)
    return hashlib.blake2b(归一.encode('utf-8'), digest_size=16).hexdigest()


def 快照(样本文件: str, url: str, 样本根: pathlib.Path = None) -> dict:
    """跑一份章节样本的正文链路，返回**纯指标**快照。"""
    import 解析基线  # 复用"不触网络的 NovelSpider 实例"
    from bs4 import BeautifulSoup
    根 = pathlib.Path(样本根) if 样本根 else 样本目录
    原始 = (根 / 样本文件).read_bytes()
    html = 原始.decode('utf-8', 'replace')
    soup = BeautifulSoup(html, 'lxml')
    s = 解析基线._造爬虫()
    正文 = s._extract_content_from_html(soup, _假响应(原始), url, url, text=html) or ''
    清洗后 = 正文
    try:
        import 内容清洗
        结果 = 内容清洗.清洗(正文, url)
        if isinstance(结果, tuple):
            清洗后 = 结果[0] or ''
        elif isinstance(结果, str):
            清洗后 = 结果
    except Exception:
        pass  # 刻意静默: 基线只记录链路结果, 清洗失败即"未清洗"口径
    return {
        '抽取字数': len(正文),
        '抽取段落数': (正文.count('\n') + 1) if 正文 else 0,
        '抽取哈希': _哈希(正文),
        '清洗字数': len(清洗后),
        '清洗哈希': _哈希(清洗后),
        '是否为空': not 正文,
        'html长度': len(原始),
    }


def 跑全部(样本根: pathlib.Path = None) -> dict:
    """对全部正文样本跑一遍；样本缺失的项跳过（公开形态无本地样本属正常）。"""
    结果 = {}
    根 = pathlib.Path(样本根) if 样本根 else 样本目录
    for 文件, url in 读样本清单(根):
        if not (根 / 文件).is_file():
            continue
        结果[f'样本{len(结果) + 1}'] = 快照(文件, url, 根)
    return 结果


def main() -> int:
    对比 = '--对比' in sys.argv[1:]
    现 = 跑全部()
    if not 现:
        print(f'[SKIP] 本地样本目录为空或不含正文样本: {样本目录}')
        print('       （公开形态属正常；本机全功能形态才有基线价值）')
        return 0
    for 文件, 指标 in 现.items():
        print(f"[基线] {文件}: 抽取 {指标['抽取字数']} 字 / 清洗后 {指标['清洗字数']} 字 "
              f"/ 空={指标['是否为空']}")
    if 对比:
        if not 基线文件.is_file():
            print('[FAIL] 无入库基线可比 (先跑一次不带 --对比 的)')
            return 1
        旧 = json.loads(基线文件.read_text(encoding='utf-8'))
        if 旧 == 现:
            print('[PASS] 与入库基线完全一致 (拆正文链路零行为变化)')
            return 0
        print('[FAIL] 与入库基线有差异:')
        for 键 in sorted(set(旧) | set(现)):
            if 旧.get(键) != 现.get(键):
                print(f'  {键}:\n    旧={json.dumps(旧.get(键), ensure_ascii=False)[:200]}'
                      f'\n    新={json.dumps(现.get(键), ensure_ascii=False)[:200]}')
        return 1
    基线文件.write_text(json.dumps(现, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'[DONE] 基线已写入 {基线文件}（仅指标与哈希，不含正文）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
