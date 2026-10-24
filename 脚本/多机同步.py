# -*- coding: utf-8 -*-
"""多机同步 · 日常一条命令（2026-10-24）。

做四件事（顺序固定，任一步失败即停并说明原因）：

1. **拉公开仓**（源码/测试/脚本/文档）—— `git pull --ff-only`（不做 merge commit，冲突即停）；
2. **拉私有仓**（真实站点适配器/样本/测试_本地/数据/HANDOFF/辅助脚本）——
   `git --git-dir=../小说爬虫-私有资产.git --work-tree=项目根 pull --ff-only`；
3. **一致性校验**：静态引用检查 + 阶段覆盖检查（默认）；加 `--全量` 再跑完整单测；
4. **报表**：版本 / HEAD / 未推送 / 私有仓状态 / 校验结论。

安全约定：
- 两台机器**不要同时改同一个仓**；本脚本只做 `pull`，不 `push`、不 `stash`、不覆盖本地改动；
- 任一侧有未提交改动时 `pull --ff-only` 会失败 —— 这是**故意的**，先提交或手工处理再同步；
- 私有仓没初始化过（第一次）时，第 2 步会提示先跑 `脚本/多机初始化.py`，不算失败。

用法
----
    .runtime\\python314\\python.exe 脚本\\多机同步.py
    .runtime\\python314\\python.exe 脚本\\多机同步.py --全量     # 顺带跑完整门禁
    .runtime\\python314\\python.exe 脚本\\多机同步.py --只拉取   # 跳过校验
"""
import argparse
import pathlib
import subprocess
import sys

根 = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(根 / '脚本'))
from _多机共用 import 私有仓, 收集pathspec  # noqa: E402


def 取解释器():
    """优先用项目自带运行时；新机器还没复制 .runtime 时回退到当前解释器。

    这样"刚 clone 下来、环境还没备齐"的机器也能先拉代码，而不是一上来就报错。
    """
    for 候选 in (根 / '.runtime' / 'python314' / 'python.exe',
                根 / '.venv' / 'Scripts' / 'python.exe'):
        if 候选.is_file():
            return 候选
    return sys.executable or 'python'


py = 取解释器()


def 跑(命令, cwd=根, timeout=1800):
    return subprocess.run(命令, cwd=str(cwd), capture_output=True, text=True,
                          encoding='utf-8', errors='replace', timeout=timeout)


def git(*参数, 私有=False):
    前缀 = ['git', f'--git-dir={私有仓}', f'--work-tree={根}'] if 私有 else ['git']
    return 跑([*前缀, *参数])


def 段(名, r, 成功提示=''):
    尾 = [x for x in ((r.stdout or '') + (r.stderr or '')).splitlines() if x.strip()]
    摘要 = 尾[-1] if 尾 else '(无输出)'
    if r.returncode == 0:
        print(f'  [OK] {名}  {摘要[:110]}  {成功提示}')
        return True
    print(f'  [失败] {名}  exit={r.returncode}')
    for x in 尾[-6:]:
        print(f'        {x[:120]}')
    return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='多机同步（拉公开仓 + 拉私有仓 + 校验）')
    ap.add_argument('--全量', action='store_true', help='顺带跑完整单测（约 90 秒）')
    ap.add_argument('--只拉取', action='store_true', help='只拉取，不跑校验')
    ap.add_argument('--推送', action='store_true',
                    help='把本机私有资产（新增/修改）收集提交并推送私有仓（在"源头机"上跑）')
    a = ap.parse_args(argv)

    print('=== 1/4 拉公开仓 ===')
    公开有改动 = 跑(['git', 'status', '--porcelain']).stdout.strip()
    if 公开有改动:
        print('  [注意] 公开仓有未提交改动，pull --ff-only 可能失败：')
        for x in 公开有改动.splitlines()[:6]:
            print(f'        {x}')
    if not 段('git pull（公开仓）', git('pull', '--ff-only')):
        return 1

    print('\n=== 2/4 拉私有仓 ===')
    if not 私有仓.exists():
        print('  [跳过] 私有仓尚未初始化 —— 先跑: python 脚本/多机初始化.py')
    else:
        私改 = git('status', '--porcelain', 私有=True).stdout.strip()
        if 私改:
            print('  [注意] 私有仓有未提交改动：')
            for x in 私改.splitlines()[:6]:
                print(f'        {x}')
        远端 = git('remote', 私有=True).stdout.strip()
        if not 远端:
            print('  [跳过] 私有仓还没配远端（照 多机初始化.py 的提示 add remote）')
        elif not 段('git pull（私有仓）', git('pull', '--ff-only', 私有=True)):
            return 1

    if a.推送:
        print('\n=== 收集并推送私有资产 ===')
        if not 私有仓.exists():
            print('  [失败] 私有仓未初始化，先跑 脚本/多机初始化.py')
            return 1
        白名单路径 = 收集pathspec()
        # 必须 -f：公开仓 .gitignore 会忽略这些路径；排除项挡掉缓存/字节码/浏览器 profile
        收脚本 = 跑(['git', f'--git-dir={私有仓}', f'--work-tree={根}',
                    'add', '-f', '--', *白名单路径])
        if 收脚本.returncode != 0:
            print(f'  [失败] 收集失败: {(收脚本.stderr or 收脚本.stdout)[:300]}')
            return 1
        差异 = 跑(['git', f'--git-dir={私有仓}', f'--work-tree={根}', 'status', '--short'])
        行s = [x for x in (差异.stdout or '').splitlines() if x.strip()]
        if not 行s:
            print('  [OK] 私有资产无变化，无需推送')
        else:
            print(f'  变更 {len(行s)} 项，样例:')
            for x in 行s[:6]:
                print(f'        {x[:100]}')
            提 = 跑(['git', f'--git-dir={私有仓}', f'--work-tree={根}',
                    '-c', 'user.name=小说爬虫', '-c', 'user.email=noreply@local',
                    'commit', '-m', 'chore(私有资产): 多机同步收集'])
            if 提.returncode != 0:
                print(f'  [失败] 提交失败: {(提.stderr or 提.stdout)[:300]}')
                return 1
            推 = 跑(['git', f'--git-dir={私有仓}', f'--work-tree={根}', 'push'])
            print(f'  [{"OK" if 推.returncode == 0 else "失败"}] 推送私有仓'
                  f'  {(推.stderr or 推.stdout).strip().splitlines()[-1][:100] if (推.stdout or 推.stderr).strip() else ""}')
            if 推.returncode != 0:
                return 1

    if a.只拉取:
        print('\n[完成] 只拉取模式，跳过校验')
        return 0

    print('\n=== 3/4 一致性校验 ===')
    解释器 = str(py)
    探测 = 跑([解释器, '-c', 'import sys; print(sys.version.split()[0])'])
    if 探测.returncode != 0:
        print(f'  [失败] 解释器不可用: {解释器}')
        print('        新机器请先备好环境（见 脚本/环境自检.py 的建议）')
        return 1
    print(f'  解释器: {解释器}（Python {(探测.stdout or '').strip()}）')
    if not 段('静态引用检查', 跑([解释器, '脚本/check_undefined_refs.py'])):
        return 1
    if not 段('阶段覆盖检查', 跑([str(py), '脚本/检查阶段覆盖.py', '--严格'])):
        return 1
    if a.全量:
        r = 跑([str(py), '-m', 'unittest', 'discover', '-s', '测试'])
        尾 = [x for x in ((r.stdout or '') + (r.stderr or '')).splitlines()
              if x.startswith(('Ran ', 'OK', 'FAILED'))]
        print(f'  [{"OK" if r.returncode == 0 else "失败"}] 全量门禁  {" | ".join(尾)[:120]}')
        if r.returncode != 0:
            return 1

    print('\n=== 4/4 报表 ===')
    head = (git('rev-parse', '--short', 'HEAD').stdout or '').strip()
    未推 = (git('rev-list', '--count', '@{u}..HEAD').stdout or '').strip() or '0'
    版本json = 根 / '脚本' / '版本.json'
    版本 = '(读不到)'
    if 版本json.is_file():
        try:
            import json
            版本 = json.loads(版本json.read_text(encoding='utf-8')).get('版本', '?')
        except (OSError, ValueError):
            pass  # 刻意静默: 版本号读不到只是报表少一项, 不影响同步结论
    print(f'  版本 {版本} / HEAD {head} / 未推送 {未推}')
    if 私有仓.exists():
        ls = git('-c', 'core.quotepath=false', 'ls-files', 私有=True).stdout or ''
        print(f'  私有仓跟踪 {len([x for x in ls.splitlines() if x.strip()])} 个文件')
    print('\n[完成] 两台机器现在一致（私有仓若跳过，见上方提示）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
