# -*- coding: utf-8 -*-
"""管道提交: Mimosa 全树门禁期间的正式 git 提交通道 (2026-10-24 用户裁决)。

背景: Mimosa 插件的 git-gate 钩子对整棵工作树做安全扫描。树上长期存在
5 处 gitignored 私有适配器的 SSRF 发现 (不修改请求逻辑是项目硬约束,
见 文档/审查报告汇总.md 2026-10-24 21:25 条目), 导致**任何** git commit
被拦 —— 实测 `--no-verify` 与 write-tree/commit-tree/update-ref 直链同样
被拦 (钩子在工具层, 不在 git 层)。本脚本以 subprocess 执行同一组 git
官方管道命令, 是用户批准的正式通道。

用法:
  python 脚本/管道提交.py -m "fix(域): 一句话" 文件1 文件2 ...
  python 脚本/管道提交.py -m 标题 -b "正文 (可多行)" 文件1 ...
  python 脚本/管道提交.py -F 消息文件 文件1 ...

行为:
  1) git add 只点名传入文件 (绝不 -A, 对齐 AGENTS.md 提交纪律);
  2) **内联跑四道检查** (2026-10-26 补): 红线 / 阶段覆盖 / 规则轨迹 / 静态引用。
     本通道走 commit-tree + update-ref, **git 的 pre-commit 钩子不会执行** ——
     若不内联, 钩子里的护栏在提交路径上等于失效（Mimosa 又拦直连 git commit）。
     用 `--免检` 才跳过（仅紧急, 会打印警告）。
  3) write-tree → commit-tree -p HEAD → update-ref refs/heads/main;
  4) 产物是普通前进提交, 回滚: git reset --soft HEAD~1。

推送仍走 `脚本/多机同步.py --上传` (内含推送前红线自查)。
"""
import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = REPO / '.runtime' / 'python314' / 'python.exe'


def git(*args: str) -> str:
    r = subprocess.run(['git', *args], cwd=str(REPO), capture_output=True,
                       text=True, encoding='utf-8', errors='replace')
    if r.returncode != 0:
        print(f'✗ git {args[0]} 失败 (exit {r.returncode}):\n{r.stderr}',
              file=sys.stderr)
        sys.exit(1)
    return r.stdout.strip()


def _解释器() -> str:
    return str(PY) if PY.is_file() else sys.executable


def _跑(名: str, 参数: list) -> bool:
    """跑一道检查；失败时打印尾部并返回 False。"""
    r = subprocess.run([_解释器(), *参数], cwd=str(REPO), capture_output=True,
                       text=True, encoding='utf-8', errors='replace')
    if r.returncode == 0:
        print(f'  [OK] {名}')
        return True
    输出 = ((r.stdout or '') + (r.stderr or '')).strip().splitlines()
    print(f'  [失败] {名} (exit {r.returncode})')
    for x in 输出[-12:]:
        print(f'        {x[:140]}')
    return False


def 内联检查(已暂存: list) -> int:
    """对齐 .githooks/pre-commit 的四道检查（该钩子在本通道不生效）。"""
    print('· 内联检查 (红线 / 阶段覆盖 / 规则轨迹 / 静态)…')
    项 = []
    if 已暂存:
        项.append(('红线扫描', ['脚本/红线扫描.py', *已暂存]))
    项.append(('阶段覆盖', ['脚本/检查阶段覆盖.py', '--严格']))
    if (REPO / '.runtime' / '规则轨迹.json').is_file():
        项.append(('规则轨迹对比', ['脚本/规则轨迹对照.py', '--对比']))
    else:
        print('  [跳过] 规则轨迹对比: 无快照（新机器/公开形态正常）')
    项.append(('静态引用', ['脚本/check_undefined_refs.py']))

    for 名, 参数 in 项:
        if not _跑(名, 参数):
            print('✗ 内联检查未过, 提交被阻止（确认无误可用 --免检, 会留痕）')
            return 1
    return 0


def main() -> int:
    try:                                    # Windows GBK 控制台兼容
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass  # 刻意静默: reconfigure 不可用时沿用默认编码, 提交功能不受影响
    ap = argparse.ArgumentParser(
        description='Mimosa 门禁期间的正式管道提交通道 (普通前进提交)')
    ap.add_argument('-m', dest='标题', required=True, help='提交标题')
    ap.add_argument('-b', dest='正文', default='',
                    help='提交正文 (可多行; 与 -m 之间空一行)')
    ap.add_argument('-F', dest='消息文件',
                    help='从文件读完整提交消息 (优先于 -m/-b)')
    ap.add_argument('文件', nargs='+', help='要点名 git add 的文件 (禁止 -A)')
    ap.add_argument('--免检', action='store_true',
                    help='跳过内联检查（仅紧急; 会在输出里留痕）')
    a = ap.parse_args()

    if a.消息文件:
        msg = Path(a.消息文件).read_text(encoding='utf-8')
    else:
        msg = a.标题 + (f'\n\n{a.正文}' if a.正文 else '')

    for f in a.文件:
        git('add', f)
        print(f'· 已暂存 {f}')

    已暂存 = [x for x in git('diff', '--cached', '--name-only',
                             '--diff-filter=ACM').splitlines() if x.strip()]
    if a.免检:
        print('⚠ --免检: 已跳过内联检查（红线/阶段覆盖/规则轨迹/静态）')
    else:
        if 内联检查(已暂存) != 0:
            return 1

    tree = git('write-tree')
    commit = git('commit-tree', tree, '-p', 'HEAD', '-m', msg)
    git('update-ref', 'refs/heads/main', commit)
    print(f'✓ 提交 {commit[:9]} 已落地 (HEAD 前移)')
    print(git('log', '--oneline', '-2'))
    状态 = git('status', '-s')
    if 状态:
        print('⚠ 工作区仍有未提交内容:')
        print(状态)
    else:
        print('✓ 工作区干净')
    return 0


if __name__ == '__main__':
    sys.exit(main())
