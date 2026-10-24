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
  2) write-tree → commit-tree -p HEAD → update-ref refs/heads/main;
  3) 产物是普通前进提交, 回滚: git reset --soft HEAD~1。

推送仍走 `脚本/多机同步.py --上传` (内含推送前红线自查)。
"""
import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def git(*args: str) -> str:
    r = subprocess.run(['git', *args], cwd=str(REPO), capture_output=True,
                       text=True, encoding='utf-8', errors='replace')
    if r.returncode != 0:
        print(f'✗ git {args[0]} 失败 (exit {r.returncode}):\n{r.stderr}',
              file=sys.stderr)
        sys.exit(1)
    return r.stdout.strip()


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
    a = ap.parse_args()

    if a.消息文件:
        msg = Path(a.消息文件).read_text(encoding='utf-8')
    else:
        msg = a.标题 + (f'\n\n{a.正文}' if a.正文 else '')

    for f in a.文件:
        git('add', f)
        print(f'· 已暂存 {f}')
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
