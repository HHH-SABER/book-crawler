# -*- coding: utf-8 -*-
"""隔离区 (`_已去重/`) 盘点与清理 (B5, 2026-10-13)。

## 为什么需要这个脚本

`去重处理.py` 的设计原则是**"移入隔离目录而非直接删, 用户可反悔"**
(`还原副本()` 可把副本移回原位)。但隔离区会**无限增长**, 且用户不会主动
想起来清理 —— 于是需要一条**显式、可预览**的清理路径。

## 策略 (与去重处理.py 的"可反悔"原则一致)

1. **绝不自动删**: 程序运行时不碰隔离区; 清理只由用户显式执行本脚本。
2. **默认 dry-run**: 只打印清单 (体积 / 文件数 / 最后修改时间 / 原路径),
   加 `--确认删除` 才真删 —— 避免手滑丢后悔药。
3. **按天保留**: `--保留天数 N` (默认 30) 只删超过 N 天的; 传 0 表示全删。
4. **成对删**: 隔离区里常见 `书名.txt` + `书名.txt.质检报告.txt` 成对存在,
   按前缀成组处理, 避免只删正文留下报告 (或反之)。

## 用法

```bash
# 盘点 (默认, 不删)
.runtime\\python314\\python.exe 脚本\\清理隔离区.py

# 指定结果目录 (默认扫 项目/抓取结果 与 dist/抓取结果)
.runtime\\python314\\python.exe 脚本\\清理隔离区.py --结果目录=dist/抓取结果

# 真删 (超过 30 天的)
.runtime\\python314\\python.exe 脚本\\清理隔离区.py --确认删除

# 真删全部
.runtime\\python314\\python.exe 脚本\\清理隔离区.py --确认删除 --保留天数=0
```
"""
import argparse
import os
import shutil
import sys
import time
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass  # 刻意静默: 控制台编码重配置失败不该中断脚本 (Windows GBK 控制台常见)

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

try:
    import 日志 as _app_log
    _log = _app_log.get('清理隔离区')
except Exception:                                    # 独立环境退化标准 logging
    import logging
    _log = logging.getLogger('清理隔离区')

隔离目录名 = '_已去重'
# 隔离区里成组出现的后缀 (正文 + 质检报告); 同前缀的算一组
_组后缀 = ('.质检报告.txt', '.checkpoint.json', '.txt')


def _找隔离区(结果根: Path) -> list:
    """在给定结果根下找隔离区目录 (含一层子目录, 如 全站重爬_20261010/_已去重)。"""
    出 = []
    if not 结果根.is_dir():
        return 出
    for p in sorted(结果根.rglob(隔离目录名)):
        if p.is_dir():
            出.append(p)
    return 出


def _分组(隔离: Path) -> dict:
    """按"去掉已知后缀"的主名分组 → {主名: [文件...]}。

    注意后缀要**连续剥离且不 break**: `书名.txt.质检报告.txt` 先剥 `.质检报告.txt`
    得 `书名.txt`, 还需再剥 `.txt` 才与正文同组 —— 否则正文与自己的质检报告会被
    分成两组 (首次实现就踩了这个: 输出里出现 0.00 MB 的孤立组)。
    """
    组 = {}
    for f in sorted(隔离.iterdir()):
        if not f.is_file():
            continue
        主名 = f.name
        for 后缀 in _组后缀:
            if 主名.endswith(后缀) and len(主名) > len(后缀):
                主名 = 主名[:-len(后缀)]
        组.setdefault(主名, []).append(f)
    return 组


def _体积(路径) -> str:
    try:
        return f"{路径.stat().st_size / 1048576:.2f} MB"
    except Exception:
        return '?'


def 盘点(结果根: Path, 保留天数: int) -> dict:
    """扫描隔离区, 返回 {'可删': [...], '保留': [...], '字节': int}"""
    截止 = time.time() - 保留天数 * 86400 if 保留天数 > 0 else None
    可删, 保留 = [], []
    总字节 = 0
    for 隔离 in _找隔离区(结果根):
        for 主名, 文件们 in _分组(隔离).items():
            最新 = max(f.stat().st_mtime for f in 文件们 if f.exists())
            体积 = sum(f.stat().st_size for f in 文件们 if f.exists())
            总字节 += 体积
            条目 = {'隔离区': 隔离, '主名': 主名, '文件': 文件们,
                    '字节': 体积, '最新': 最新,
                    '天前': int((time.time() - 最新) / 86400)}
            if 截止 is None or 最新 < 截止:
                可删.append(条目)
            else:
                保留.append(条目)
    return {'可删': 可删, '保留': 保留, '字节': 总字节}


def 执行删除(条目列表: list) -> int:
    """真删 (只由 --确认删除 触发)。返回删除的文件数。"""
    n = 0
    for 条目 in 条目列表:
        for f in 条目['文件']:
            try:
                if f.is_file():
                    f.unlink()
                    n += 1
            except Exception as e:
                _log.info(f'删除失败 {f.name[:40]}: {type(e).__name__}: {e}')
    return n


def _打印(结果: dict, 保留天数: int, 结果根: Path) -> None:
    print(f'=== 隔离区盘点: {结果根} ===')
    print(f'总计 {len(结果["可删"]) + len(结果["保留"])} 组 / '
          f'{结果["字节"] / 1048576:.2f} MB')
    if 结果['可删']:
        print(f'\n--- 超过保留期({保留天数} 天), 可删 {len(结果["可删"])} 组 ---')
        for e in 结果['可删'][:30]:
            print(f'  {e["主名"][:34]:36} {e["字节"] / 1048576:7.2f} MB  '
                  f'{e["天前"]:>4} 天前  {len(e["文件"])} 文件')
        if len(结果['可删']) > 30:
            print(f'  … 另有 {len(结果["可删"]) - 30} 组')
    if 结果['保留']:
        print(f'\n--- 保留期内, 不动 {len(结果["保留"])} 组 ---')
        for e in 结果['保留'][:10]:
            print(f'  {e["主名"][:34]:36} {e["字节"] / 1048576:7.2f} MB  '
                  f'{e["天前"]:>4} 天前')
        if len(结果['保留']) > 10:
            print(f'  … 另有 {len(结果["保留"]) - 10} 组')
    if not 结果['可删'] and not 结果['保留']:
        print('  (无隔离文件)')


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='隔离区 (_已去重) 盘点与清理')
    ap.add_argument('--结果目录', default='', help='结果根目录 (默认扫两处)')
    ap.add_argument('--保留天数', type=int, default=30,
                    help='保留天数, 0 = 全删 (默认 30)')
    ap.add_argument('--确认删除', action='store_true',
                    help='真删 (不给则只 dry-run 打印清单)')
    args = ap.parse_args(argv)

    根 = Path(args.结果目录) if args.结果目录 else _根
    根 = 根 if 根.is_absolute() else (_根 / 根)
    结果根s = [根] if args.结果目录 else [_根 / '抓取结果', _根 / 'dist' / '抓取结果']

    汇总 = {'可删': [], '保留': [], '字节': 0}
    for r in 结果根s:
        if not r.is_dir():
            continue
        部 = 盘点(结果根=r, 保留天数=args.保留天数)
        _打印(部, args.保留天数, r)
        汇总['可删'] += 部['可删']
        汇总['保留'] += 部['保留']
        汇总['字节'] += 部['字节']

    if not args.确认删除:
        n = len(汇总['可删'])
        print(f'\n[DRY-RUN] 合计可删 {n} 组 / {汇总["字节"] / 1048576:.2f} MB '
              f'(未删除任何文件)')
        print('  真删请加 --确认删除')
        return 0

    if not 汇总['可删']:
        print('\n没有超过保留期的隔离文件, 未删除任何内容')
        return 0
    删了 = 执行删除(汇总['可删'])
    print(f'\n[已删除] {删了} 个文件 / {len(汇总["可删"])} 组 / '
          f'{汇总["字节"] / 1048576:.2f} MB')
    _log.info(f'清理隔离区: 删除 {删了} 文件 ({len(汇总["可删"])} 组)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
