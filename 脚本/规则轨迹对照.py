# -*- coding: utf-8 -*-
"""规则轨迹：离线产出 / 比对「站点策略决策轨迹」快照（S1 第二步，2026-10-26）。

它回答的问题
------------
"我改了 `爬虫.py` / 适配器 / 站点表之后，**每个阶段的决策**还和以前一样吗？"
—— 这是把 S1 从"静态导出"推进到"可重放对照"的那一步。

两条驱动链（都不触网、只读本地样本）
------------------------------------
1. **目录链**：`解析基线._快照()` × 目录样本（触发 `目录规范化 / 目录兜底解析 /
   目录附加URL / 目录分页URL / 专属选择器 / 章节链接接受` 等阶段）；
2. **正文链**：`正文基线.快照()` × 章节样本（触发 `正文清理 / 专属选择器 /
   抓取路径` 等阶段）。

快照只记"阶段 / 主机指纹 / 是否命中 / 返回值摘要 / 上下文键名"，**不含域名、URL、正文**，
写 `.runtime/规则轨迹.json`（gitignored，永不入库）。快照自带 `元信息`（工具版本 /
生成时间 / HEAD / 样本数），用于识别"这条快照是不是过期了"——**元信息不参与比对**。

用法
----
    .runtime\\python314\\python.exe 脚本\\规则轨迹对照.py            # 采样写快照（默认）
    .runtime\\python314\\python.exe 脚本\\规则轨迹对照.py --对比      # 与快照比对，有差异退 1
    .runtime\\python314\\python.exe 脚本\\规则轨迹对照.py --自检      # 连跑两遍验确定性

门禁：`--对比` 已挂 `.githooks/pre-commit`（快照存在时才跑；新机器无快照则跳过）。
"""
import argparse
import json
import pathlib
import subprocess
import sys

_根 = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))
sys.path.insert(0, str(_根 / '脚本'))

快照文件 = _根 / '.runtime' / '规则轨迹.json'


def _当前HEAD() -> str:
    r = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=str(_根),
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return (r.stdout or '').strip()


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
    """开轨迹 → 跑两条链 → 关轨迹 → 返回带元信息的快照。"""
    import 规则轨迹
    规则轨迹.清空()
    规则轨迹.启用()
    try:
        目录数 = _跑目录链()
        正文数 = _跑正文链()
    finally:
        规则轨迹.停用()
    样本数 = {'目录': 目录数, '正文': 正文数}
    return {
        '元信息': 规则轨迹.生成元信息(样本数=样本数, head=_当前HEAD()),
        '样本数': 样本数,
        '轨迹': 规则轨迹.快照(),
    }


def _阶段分布(轨迹: dict) -> list:
    计 = {}
    for 条 in (轨迹 or {}).get('记录', []):
        计[条['阶段']] = 计.get(条['阶段'], 0) + 1
    return sorted(计.items(), key=lambda kv: (-kv[1], kv[0]))


def _打印摘要(数据: dict) -> None:
    轨迹 = 数据.get('轨迹') or {}
    样本 = 数据.get('样本数') or {}
    print(f'  样本: 目录 {样本.get("目录", 0)} / 正文 {样本.get("正文", 0)}'
          f'；轨迹记录 {轨迹.get("记录数", 0)} 条')
    分布 = _阶段分布(轨迹)
    if 分布:
        print('  阶段分布（前 12）: ' + '、'.join(f'{k}×{v}' for k, v in 分布[:12]))
    else:
        print('  [提示] 轨迹为空 —— 公开形态（缺本地样本）或阶段未被触发')


def _隐私自检(数据: dict) -> list:
    """快照里绝不允许出现 URL / 域名 / 正文特征。"""
    文 = json.dumps(数据, ensure_ascii=False)
    return [禁 for 禁 in ('http://', 'https://', '.com', '.net', '.org', 'www.') if 禁 in 文]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='规则轨迹（离线采样 / 比对 / 确定性自检）')
    ap.add_argument('--写', action='store_true', help='采样并写入 .runtime/规则轨迹.json（默认）')
    ap.add_argument('--对比', action='store_true', help='采样并与快照比对，有差异退 1')
    ap.add_argument('--自检', action='store_true', help='连跑两遍，验证轨迹确定性')
    a = ap.parse_args(argv)

    import 规则轨迹 as 内核

    if a.自检:
        甲, 乙 = 跑一遍(), 跑一遍()
        print('=== 确定性自检 ===')
        _打印摘要(甲)
        差 = 内核.对比快照(甲, 乙)     # 只比轨迹；元信息含生成时间，天然不同
        if 差:
            print('  [FAIL] 两次采样不一致（非确定性）:')
            for x in 差:
                print(f'    {x}')
            return 1
        print('  [PASS] 两次采样轨迹逐字节一致（确定性 OK）')
        return 0

    if a.对比:
        新 = 跑一遍()
        print('=== 规则轨迹对比 ===')
        _打印摘要(新)
        if not 快照文件.is_file():
            print(f'  [FAIL] 没有快照: {快照文件}（先跑一次不带 --对比 的）')
            return 1
        旧 = json.loads(快照文件.read_text(encoding='utf-8'))
        元 = 旧.get('元信息') or {}
        if 元:
            print(f'  快照: 生成于 {元.get("生成时间", "?")} / HEAD {元.get("HEAD", "?")}'
                  f' / 样本 {元.get("样本数", {})}')
            if 元.get('HEAD') and 元.get('HEAD') != _当前HEAD():
                print(f'  [提示] 快照 HEAD({元.get("HEAD")}) 与当前({_当前HEAD()}) 不同'
                      f' —— 属正常（快照是上次确认无误的锚点）；差异需逐条确认后再 --写')
        else:
            print('  [提示] 旧格式快照（无元信息），按轨迹比对')
        差 = 内核.对比快照(旧, 新)
        if 差:
            print(f'  [FAIL] 与快照有 {len(差)} 处差异:')
            for x in 差:
                print(f'    {x}')
            print('  处置：确认是有意改动 ⇒ `脚本\\规则轨迹对照.py --写` 更新快照'
                  '（快照 gitignored，不进提交）；否则回退改动')
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
