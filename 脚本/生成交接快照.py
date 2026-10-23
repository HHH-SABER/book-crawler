# -*- coding: utf-8 -*-
"""生成交接快照状态块 (P8-C8, 2026-10-24 夜)。

解决的实测痛点 (评估报告原话): "交接快照反复过期 (10-20 写 2.5.47 实际
2.5.55)" —— 人肉维护 HANDOFF 七要素必然漂移。本脚本把其中**可机械获取**
的部分自动化, 作为收尾必查项。

用法:
    python 脚本/生成交接快照.py            # 打印状态块 (默认快, 读门禁缓存)
    python 脚本/生成交接快照.py --gate     # 先实跑门禁再打印 (约 90 秒)
    python 脚本/生成交接快照.py --json     # 机器可读输出

退出码 (供收尾仪式用): 0 = 干净可交接; 1 = 存在未推送/未发布/在途改动/门禁未跑。
只读: 不写仓库任何文件 (门禁结果写 .workbuddy/ 缓存, gitignored)。
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

项目根 = Path(__file__).resolve().parent.parent
版本文件 = 项目根 / '脚本' / '版本.json'
门禁缓存 = 项目根 / '.workbuddy' / '门禁状态.json'


def _跑git(参数: list) -> str:
    """跑 git 取 stdout (core.quotepath=false: 中文路径不转义成八进制)。"""
    try:
        r = subprocess.run(['git', '-c', 'core.quotepath=false'] + 参数,
                           cwd=项目根, capture_output=True,
                           text=True, encoding='utf-8', errors='replace',
                           timeout=30)
        return (r.stdout or '').strip()
    except Exception:
        return ''


def _解析版本(文本: str):
    """'2.5.57' / 'v2.5.55' → (2,5,57); 失败返回 None。"""
    文本 = 文本.strip().lstrip('vV')
    部分 = 文本.split('.')
    if len(部分) < 3 or not all(p.isdigit() for p in 部分[:3]):
        return None
    return tuple(int(p) for p in 部分[:3])


def 未发布版本数(当前: str, 最新tag: str):
    """当前版本相对最新 tag 领先几个补丁号 (0 = 已发布; None = 无法判定)。"""
    当 = _解析版本(当前 or '')
    tag = _解析版本(最新tag or '')
    if 当 is None:
        return None
    if tag is None:
        return None                      # 无 tag: 调用方另行提示"从未发布"
    if 当 <= tag:
        return 0
    if 当[:2] != tag[:2]:
        return None                      # 跨次版本/小版本, 不适合用差值表达
    return 当[2] - tag[2]


def 采集(gate: bool = False) -> dict:
    数据 = {}
    try:
        数据['版本'] = json.loads(版本文件.read_text(encoding='utf-8')).get('版本', '?')
    except Exception:
        数据['版本'] = '?'
    数据['HEAD'] = _跑git(['rev-parse', '--short', 'HEAD'])
    数据['origin'] = _跑git(['rev-parse', '--short', 'origin/main'])
    领先 = _跑git(['rev-list', '--count', 'origin/main..HEAD'])
    落后 = _跑git(['rev-list', '--count', 'HEAD..origin/main'])
    数据['领先'] = int(领先) if 领先.isdigit() else 0
    数据['落后'] = int(落后) if 落后.isdigit() else 0
    数据['未推送提交'] = [l for l in _跑git(
        ['log', '--oneline', 'origin/main..HEAD']).splitlines() if l.strip()]
    数据['工作区在途'] = [l for l in _跑git(
        ['status', '--porcelain']).splitlines() if l.strip()]
    数据['最新tag'] = _跑git(['describe', '--tags', '--abbrev=0'])
    数据['未发布版本数'] = 未发布版本数(数据['版本'], 数据['最新tag'])

    if gate:
        结果 = subprocess.run(
            [sys.executable, '-m', 'unittest', 'discover', '-s', '测试'],
            cwd=项目根, capture_output=True, text=True, encoding='utf-8',
            errors='replace', timeout=900)
        # unittest 的 TextTestRunner 写 **stderr** (不是 stdout), 两路都取
        合并输出 = (结果.stdout or '') + '\n' + (结果.stderr or '')
        行 = [l for l in 合并输出.splitlines() if l.startswith('Ran ')]
        数据['门禁'] = {'通过': 结果.returncode == 0,
                      '摘要': 行[-1] if 行 else '(无输出)'}
        try:
            门禁缓存.parent.mkdir(parents=True, exist_ok=True)
            门禁缓存.write_text(json.dumps(数据['门禁'], ensure_ascii=False),
                             encoding='utf-8')
        except OSError:
            pass    # 刻意静默: 缓存写不了不影响本次输出
    else:
        try:
            数据['门禁'] = json.loads(门禁缓存.read_text(encoding='utf-8'))
            数据['门禁来源'] = '缓存'
        except Exception:
            数据['门禁'] = None
            数据['门禁来源'] = '未跑过 (加 --gate 实跑)'
    return 数据


def 状态块(数据: dict) -> str:
    未发布 = 数据['未发布版本数']
    if 数据['最新tag'] and 未发布:
        未发布行 = f'**{未发布} 个版本未发布** (最新 tag {数据["最新tag"]})'
    elif not 数据['最新tag']:
        未发布行 = '**从未打 tag 发布**'
    else:
        未发布行 = f'0 (已发布至 {数据["最新tag"]})'
    门禁 = 数据.get('门禁')
    if 门禁:
        门禁行 = ('✅ ' if 门禁['通过'] else '❌ ') + 门禁['摘要']
    else:
        门禁行 = f'⚠️ {数据.get("门禁来源", "未跑")}'
    return '\n'.join([
        f'- 版本: **{数据["版本"]}**; 未发布: {未发布行}',
        f'- HEAD: `{数据["HEAD"]}` / origin/main: `{数据["origin"]}` '
        f'(领先 {数据["领先"]} / 落后 {数据["落后"]})',
        f'- 未推送提交: {len(数据["未推送提交"])} 个'
        + (f' — ' + '; '.join(数据['未推送提交'][:5]) if 数据['未推送提交'] else ''),
        f'- 工作区在途: {len(数据["工作区在途"])} 项'
        + (f' — ' + '; '.join(l.strip() for l in 数据['工作区在途'][:5])
           if 数据['工作区在途'] else ''),
        f'- 门禁: {门禁行}',
    ])


def 是否干净(数据: dict) -> bool:
    return (数据['领先'] == 0 and not 数据['未推送提交']
            and not 数据['工作区在途'] and 数据['未发布版本数'] == 0
            and (数据.get('门禁') or {}).get('通过'))


def main() -> int:
    ap = argparse.ArgumentParser(description='生成交接快照状态块 (P8-C8)')
    ap.add_argument('--gate', action='store_true', help='先实跑门禁再打印')
    ap.add_argument('--json', action='store_true', help='机器可读输出')
    参数 = ap.parse_args()

    数据 = 采集(gate=参数.gate)
    if 参数.json:
        print(json.dumps(数据, ensure_ascii=False, indent=1))
    else:
        print('== 交接快照 (P8-C8 生成, 可粘进 HANDOFF 顶部) ==')
        print(状态块(数据))
    return 0 if 是否干净(数据) else 1


if __name__ == '__main__':
    sys.exit(main())
