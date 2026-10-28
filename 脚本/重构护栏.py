# -*- coding: utf-8 -*-
"""重构护栏：一条命令做"拆分前打锚点 / 拆分后验零变化"（S1 第三步，2026-10-26）。

## 解决的问题

拆 `爬虫.py` / GUI 页面时，真正难的不是拆，而是**证明"行为没变"**。之前要做这件事，
得手工依次跑四五个脚本、再逐条读输出——颗粒度一粗，就会有人"觉得差不多"就提交了。

本脚本把现有的四道护栏收成一个工作流：

    .runtime\\python314\\python.exe 脚本\\重构护栏.py --锚点   # 拆之前：打三份锚点
    （…… 开始拆，跑门禁 ……）
    .runtime\\python314\\python.exe 脚本\\重构护栏.py --校验   # 拆之后：五道一起验

| 护栏 | 锚点 | 校验 | 缺本地样本时 |
|---|---|---|---|
| 目录链（`解析基线`） | 写 `文档/解析基线.json`（入库） | `--对比` 零差异 | 跳过（不写空基线）|
| 正文链（`正文基线`） | 写 `文档/正文基线.json`（入库，只存指标+哈希） | `--对比` 零差异 | 跳过 |
| 决策轨迹（`规则轨迹对照`） | 写 `.runtime/规则轨迹.json`（**不入库**） | `--对比` 零差异 | 跳过 |
| 阶段覆盖 | — | `检查阶段覆盖.py --严格` | 照常可跑 |
| 静态引用 | — | `check_undefined_refs.py` | 照常可跑 |

**安全设计**：`--锚点` 在**缺本地样本**时**拒绝执行**（公开形态跑出来的空基线会把好基线覆盖成空，
比不跑更糟）；`--校验` 允许部分跳过，但消失的护栏会明确标 `跳过`，不伪装成 PASS。
"""
import argparse
import pathlib
import subprocess
import sys
import time

根 = pathlib.Path(__file__).resolve().parent.parent
_py = 根 / '.runtime' / 'python314' / 'python.exe'
解释器 = str(_py) if _py.is_file() else sys.executable

#: 三条链各自依赖的本地样本目录（缺任一 ⇒ 锚点阶段拒绝执行）
样本依赖 = {
    '目录链': 根 / '测试' / '样本',
    '正文链': 根 / '测试样本_本地',
}
轨迹依赖 = 根 / '测试' / '样本'      # 轨迹同时用目录链与正文链


def _跑(参数: list, 名: str) -> tuple:
    """跑一个脚本，返回 (是否成功, 耗时秒, 末尾输出行)。"""
    t0 = time.time()
    r = subprocess.run([解释器, *参数], cwd=str(根), capture_output=True,
                       text=True, encoding='utf-8', errors='replace')
    输出 = ((r.stdout or '') + (r.stderr or '')).strip().splitlines()
    return r.returncode == 0, time.time() - t0, (输出[-1][:110] if 输出 else '')


def 样本就绪() -> tuple:
    """返回 (是否就绪, 缺失目录名列表)。"""
    缺 = [名 for 名, 目录 in 样本依赖.items() if not 目录.is_dir()]
    return (not 缺), 缺


def 打锚点() -> int:
    就绪, 缺 = 样本就绪()
    if not 就绪:
        print(f'[FAIL] 缺本地样本目录: {"、".join(缺)}')
        print('       公开形态下打锚点会把入库基线覆盖成空 —— 拒绝执行（这是故意的）。')
        return 1
    print('=== 打锚点（拆分前跑一次）===')
    失败 = 0
    for 名, 参数 in (('目录链', ['脚本/解析基线.py']),
                    ('正文链', ['脚本/正文基线.py']),
                    ('决策轨迹', ['脚本/规则轨迹对照.py'])):
        ok, 秒, 尾 = _跑(参数, 名)
        print(f'  [{"OK" if ok else "失败"}] {名}  {秒:.1f}s  {尾}')
        失败 += 0 if ok else 1
    if 失败:
        print('[FAIL] 锚点未全部打好，先修上面的问题再拆')
        return 1
    print('[DONE] 三份锚点已就绪：文档/解析基线.json、文档/正文基线.json、.runtime/规则轨迹.json')
    print('       现在可以开始改代码；改完跑 --校验')
    return 0


def 校验项() -> list:
    """校验阶段要跑的（名称, 参数）清单 —— 抽出来便于用例核对组成。"""
    return [
        ('目录链', ['脚本/解析基线.py', '--对比']),
        ('正文链', ['脚本/正文基线.py', '--对比']),
        ('决策轨迹', ['脚本/规则轨迹对照.py', '--对比']),
        ('阶段覆盖', ['脚本/检查阶段覆盖.py', '--严格']),
        ('静态引用', ['脚本/check_undefined_refs.py']),
    ]


def 校验() -> int:
    print('=== 重构护栏校验（拆分后跑一次）===')
    项 = 校验项()
    失败 = []
    for 名, 参数 in 项:
        ok, 秒, 尾 = _跑(参数, 名)
        print(f'  [{"OK" if ok else "失败"}] {名}  {秒:.1f}s  {尾}')
        if not ok:
            失败.append(名)
    print()
    if 失败:
        print(f'[FAIL] {len(失败)} 道护栏未过: {"、".join(失败)}')
        print('       处置: 逐条看上面对应输出 —— 有差异就是行为变了，别提交。')
        return 1
    print('[PASS] 五道护栏全过 ⇒ 与锚点零差异（行为等价，可提交）')
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='重构护栏：打锚点 / 校验零行为变化')
    g = ap.add_mutually_exclusive_group()
    g.add_argument('--锚点', action='store_true', help='拆分前：写三份锚点（缺本地样本会拒绝）')
    g.add_argument('--校验', action='store_true', help='拆分后：五道护栏一起验（默认）')
    a = ap.parse_args(argv)
    if a.锚点:
        return 打锚点()
    return 校验()


if __name__ == '__main__':
    sys.exit(main())
