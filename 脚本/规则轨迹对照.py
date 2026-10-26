# -*- coding: utf-8 -*-
"""规则轨迹：离线产出 / 比对「站点策略决策轨迹」快照（S1 第二步，2026-10-26）。

它回答的问题
------------
"我改了 `爬虫.py` / 适配器 / 站点表之后，**每个阶段的决策**还和以前一样吗？"
—— 这是把 S1 从"静态导出"推进到"可重放对照"的那一步。

两条驱动链（都不触网、只读本地样本）
------------------------------------
1. **目录链**：`解析基线._快照()` × 5 份目录样本（触发 `目录规范化 / 目录兜底解析 /
   目录附加URL / 目录分页URL / 专属选择器 / 章节链接接受` 等阶段）；
2. **正文链**：`正文基线.快照()` × 7 份章节样本（触发 `正文清理 / 专属选择器 /
   抓取路径` 等阶段）。

快照只记"阶段 / 主机指纹 / 是否命中 / 返回值摘要 / 上下文键名"，**不含域名、URL、正文**，
写 `.runtime/规则轨迹.json`（gitignored，永不入库）。

用法
----
    .runtime\\python314\\python.exe 脚本\\规则轨迹.py            # 写快照（默认）
    .runtime\\python314\\python.exe 脚本\\规则轨迹.py --对比      # 与快照逐字节比对，有差异退 1
    .runtime\\python314\\python.exe 脚本\\规则轨迹.py --自检      # 连跑两遍验确定性
"""
import argparse
import json
import pathlib
import sys

_根 = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))
sys.path.insert(0, str(_根 / '脚本'))

快照文件 = _根 / '.runtime' / '规则轨迹.json'


def _跑目录链() -> int:
    import 解析基线
    跑数 = 0
    for 文件, url in 解析基线.样本们:
        if not (解析基线.样本目录 / 文件).is_file():
            continue
        try:
            解析基线._快照(文件, url)
            跑数 += 1
        except Exception as e:      # noqa: BLE001 — 单样本失败不该中断整轮采样
            print(f'    [跳过] 目录样本 {文件}: {type(e).__name__}: {e}')
    return 跑数


def _跑正文链() -> int:
    import 正文基线
    样本根 = 正文基线.样本目录
    跑数 = 0
    for 文件, url in 正文基线.读样本清单(样本根):
        if not (样本根 / 文件).is_file():
            continue
        try:
            正文基线.快照(文件, url, 样本根)
            跑数 += 1
        except Exception as e:      # noqa: BLE001 — 同上
            print(f'    [跳过] 正文样本 {文件}: {type(e).__name__}: {e}')
    return 跑数


def 跑一遍() -> dict:
    """开轨迹 → 跑两条链 → 关轨迹 → 返回快照（含样本计数）。"""
    import 规则轨迹
    规则轨迹.清空()
    规则轨迹.启用()
    try:
        目录数 = _跑目录链()
        正文数 = _跑正文链()
    finally:
        规则轨迹.停用()
    return {
        '目录样本数': 目录数,
        '正文样本数': 正文数,
        '轨迹': 规则轨迹.快照(),
    }


def _阶段分布(轨迹: dict) -> list:
    计 = {}
    for 条 in 轨迹.get('记录', []):
        计[条['阶段']] = 计.get(条['阶段'], 0) + 1
    return sorted(计.items(), key=lambda kv: (-kv[1], kv[0]))


def _打印摘要(数据: dict) -> None:
    轨迹 = 数据.get('轨迹', {})
    print(f'  样本: 目录 {数据["目录样本数"]} / 正文 {数据["正文样本数"]}'
          f'；轨迹记录 {轨迹.get("记录数", 0)} 条')
    分布 = _阶段分布(轨迹)
    if 分布:
        print('  阶段分布（前 12）: ' + '、'.join(f'{k}×{v}' for k, v in 分布[:12]))
    else:
        print('  [提示] 轨迹为空 —— 公开形态（缺本地样本）或阶段未被触发')


def _隐私自检(数据: dict) -> list:
    """快照里绝不允许出现 URL / 域名 / 正文特征。"""
    文 = json.dumps(数据, ensure_ascii=False)
    问题 = []
    for 禁 in ('http://', 'https://', '.com', '.net', '.org', 'www.'):
        if 禁 in 文:
            问题.append(禁)
    return 问题


def _对比(旧: dict, 新: dict) -> list:
    """逐条比对，返回人类可读差异列表（空 = 完全一致）。"""
    差 = []
    旧轨 = (旧.get('轨迹') or {}).get('记录') or []
    新轨 = (新.get('轨迹') or {}).get('记录') or []
    if len(旧轨) != len(新轨):
        差.append(f'记录条数变化: {len(旧轨)} → {len(新轨)}')
    for i in range(min(len(旧轨), len(新轨))):
        a, b = 旧轨[i], 新轨[i]
        键s = [k for k in ('阶段', '主机指纹', '命中适配器', '返回摘要', '上下文键')
              if a.get(k) != b.get(k)]
        if 键s:
            差.append(f'第 {i + 1} 条差异 {键s}: 旧={ {k: a.get(k) for k in 键s} }'
                     f' 新={ {k: b.get(k) for k in 键s} }')
    return 差[:20]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='规则轨迹（离线采样 / 比对 / 确定性自检）')
    ap.add_argument('--写', action='store_true', help='采样并写入 .runtime/规则轨迹.json（默认）')
    ap.add_argument('--对比', action='store_true', help='采样并与快照比对，有差异退 1')
    ap.add_argument('--自检', action='store_true', help='连跑两遍，验证快照逐字节一致')
    a = ap.parse_args(argv)

    if a.自检:
        甲, 乙 = 跑一遍(), 跑一遍()
        print('=== 确定性自检 ===')
        _打印摘要(甲)
        差 = _对比(甲, 乙)
        if 差:
            print('  [FAIL] 两次采样不一致（非确定性）:')
            for x in 差:
                print(f'    {x}')
            return 1
        print('  [PASS] 两次采样逐字节一致（确定性 OK）')
        return 0

    if a.对比:
        新 = 跑一遍()
        print('=== 规则轨迹对比 ===')
        _打印摘要(新)
        if not 快照文件.is_file():
            print(f'  [FAIL] 没有入库快照: {快照文件}（先跑一次不带 --对比 的）')
            return 1
        旧 = json.loads(快照文件.read_text(encoding='utf-8'))
        差 = _对比(旧, 新)
        if 差:
            print(f'  [FAIL] 与快照有 {len(差)} 处差异:')
            for x in 差:
                print(f'    {x}')
            return 1
        print('  [PASS] 决策轨迹与快照完全一致（改动零行为变化）')
        return 0

    数据 = 跑一遍()
    print('=== 规则轨迹采样 ===')
    _打印摘要(数据)
    问题 = _隐私自检(数据)
    if 问题:
        print(f'  [FAIL] 快照含敏感特征 {问题}，拒绝写入')
        return 1
    快照文件.parent.mkdir(parents=True, exist_ok=True)
    快照文件.write_text(json.dumps(数据, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'  [DONE] 已写入 {快照文件}（只读快照，gitignored，永不入库）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
