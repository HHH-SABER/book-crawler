# -*- coding: utf-8 -*-
"""新机器环境自检（2026-10-24，配合多机同步）。

在**任何一台电脑**上接手项目时先跑这个：它只做只读检查，告诉你"现在处于哪种形态、
缺什么、下一步该干什么"，避免接手者上来就误判（最常见：把"公开形态多跳过几个用例"
当成门禁坏了，或者不知道私有资产没拉）。

用法
----
    .runtime\\python314\\python.exe 脚本\\环境自检.py
    python 脚本\\环境自检.py            # 还没复制 .runtime 时（用系统 Python）

检查项
------
① 解释器（.runtime 随包 / 系统 python / py -3）
② 关键依赖（flet / bs4 / requests / lxml / cloudscraper 等）
③ 私有资产（站点适配_本地 / 测试样本_本地 / 测试_本地 / 数据）
④ 私有仓（是否存在 / 有无远端 / 是否落后）
⑤ 形态判定 + **该形态下门禁的期望结果**（结论看 OK，不看数字）
"""
import importlib.util
import pathlib
import subprocess
import sys

根 = pathlib.Path(__file__).resolve().parent.parent
私有仓 = 根.parent / '小说爬虫-私有资产.git'

依赖 = ['flet', 'bs4', 'requests', 'lxml', 'cloudscraper', 'PIL', 'yaml']
私有资产 = ['站点适配_本地', '测试样本_本地', '测试_本地', '数据']

结果 = []   # (是否OK, 文本, 建议)


def 记(ok, 文本, 建议=''):
    结果.append((ok, 文本, 建议))


def 检查解释器():
    候选 = [根 / '.runtime' / 'python314' / 'python.exe', 根 / '.venv' / 'Scripts' / 'python.exe']
    现有 = [p for p in 候选 if p.is_file()]
    if 现有:
        记(True, f'解释器: {现有[0].relative_to(根)}（随包，首选）')
    else:
        记(False, '解释器: 项目内没有 .runtime/.venv',
            '从旧机器整包复制 .runtime + .venv（二者互相依赖，不可只拷一个），或装 Python 3.14 + requirements.txt')
    return 现有[0] if 现有 else None


def 检查依赖(py):
    缺 = []
    for 名 in 依赖:
        try:
            有 = importlib.util.find_spec(名) is not None
        except (ImportError, ValueError):
            有 = False
        if not 有:
            缺.append(名)
    if 缺:
        记(False, f'依赖: 缺 {", ".join(缺)}',
            '在项目根执行：.venv\\Scripts\\python.exe -m pip install -r requirements.txt')
    else:
        记(True, f'依赖: {len(依赖)} 个关键包齐全')


def 检查私有资产():
    有 = [x for x in 私有资产 if (根 / x).is_dir()]
    缺 = [x for x in 私有资产 if x not in 有]
    if not 缺:
        记(True, '私有资产: 全部就位（全功能形态）')
    else:
        记(False, f'私有资产: 缺 {", ".join(缺)}（公开形态）',
            '跑：脚本/多机初始化.py --私有远端 <私有仓URL>（或已有仓时直接 脚本/多机同步.py）')


def 检查私有仓():
    if not 私有仓.is_dir():
        记(False, f'私有仓: 不存在（{私有仓.name}）', '首次需 脚本/多机初始化.py')
        return
    远端 = subprocess.run(['git', f'--git-dir={私有仓}', 'remote'], capture_output=True,
                       text=True, encoding='utf-8', errors='replace').stdout.strip()
    if not 远端:
        记(False, '私有仓: 无远端', '按初始化脚本提示 add remote，或重跑带 --私有远端')
        return
    落后 = subprocess.run(['git', f'--git-dir={私有仓}', f'--work-tree={根}',
                        'rev-list', '--count', 'HEAD..@{u}'], capture_output=True,
                       text=True, encoding='utf-8', errors='replace').stdout.strip()
    记(True, f'私有仓: 远端已配，落后 {落后 or "0"} 个提交',
        '若有落后：脚本/多机同步.py')


def 判定形态():
    全功能 = all((根 / x).is_dir() for x in 私有资产)
    print()
    print('=' * 62)
    if 全功能:
        print('当前形态: 【全功能】（私有资产齐全）')
        print('  门禁期望: 约 1553 用例 / 8 skipped，结果 **OK**')
    else:
        print('当前形态: 【公开】（缺私有资产，属正常）')
        print('  门禁期望: 用例数略少、**skipped 会明显增多**（缺失 fixture 时 skipTest），')
        print('  但只要最后一行是 **OK** 就算绿 —— 不要因为数字比文档小就判门禁坏。')
    print('  判定标准始终是最后一行的 OK / FAILED，不是用例数字。')
    print('=' * 62)


def main() -> int:
    print('=== 环境自检 ===')
    py = 检查解释器()
    检查依赖(py)
    检查私有资产()
    检查私有仓()

    for ok, 文本, 建议 in 结果:
        print(f'  [{"OK" if ok else "缺"}] {文本}')
        if 建议:
            print(f'         → {建议}')
    判定形态()
    差 = [x for x in 结果 if not x[0]]
    if 差:
        print(f'\n还有 {len(差)} 项待处理（见上方 → 建议）。处理完再跑：')
        print('  .runtime\\python314\\python.exe 脚本\\多机同步.py --全量')
        return 1
    print('\n全部就绪。下一步：.runtime\\python314\\python.exe 脚本\\多机同步.py --全量')
    return 0


if __name__ == '__main__':
    sys.exit(main())
