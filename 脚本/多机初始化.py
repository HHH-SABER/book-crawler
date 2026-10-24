# -*- coding: utf-8 -*-
"""多机同步 · 一次性初始化（每台机器跑一次，2026-10-24）。

## 为什么需要它

项目分两层：
- **公开层**（源码/测试/脚本/文档）→ 已在 GitHub 公开仓，`git pull` 即可；
- **私有层**（真实站点适配器、真实样本、测试_本地、数据/、HANDOFF、辅助脚本）→
  被 `.gitignore` 挡在公开仓外，**换机器就没了**。

本脚本给私有层单开一个**独立 git 仓**，但**不搬动任何文件**：
用 `git --git-dir=<私有仓> --work-tree=<项目根>`，让私有仓的工作区直接指向项目根，
靠白名单只跟踪那几个被忽略的路径。好处：文件位置不变、与公开仓互不干扰、
之后一条 `python 脚本/多机同步.py` 即可拉齐。

## 用法

    .runtime\\python314\\python.exe 脚本\\多机初始化.py
    # 已有私有远端（推荐 GitHub 私有仓，免费）：
    .runtime\\python314\\python.exe 脚本\\多机初始化.py --私有远端 https://github.com/<你>/<私有仓>.git

⚠️ 私有仓内含**真实站点域名/站名/样本/用户数据**，**必须设为 Private**，严禁公开。
"""
import argparse
import pathlib
import subprocess
import sys

根 = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(根 / '脚本'))
from _多机共用 import 私有仓, 收集pathspec  # noqa: E402

排除模板 = '''# 私有资产仓：默认忽略一切。真正的纳入靠 脚本/多机初始化.py 的 `git add -f`
# （本仓 --work-tree 是项目根，git 会优先读公开仓的 .gitignore，见 _多机共用.py）。
*
!/HANDOFF.md
!/站点适配_本地/
!/测试样本_本地/
!/测试_本地/
!/数据/
!/.runtime/
!.runtime/*.py
'''


def git(*参数, check=False) -> subprocess.CompletedProcess:
    r = subprocess.run(['git', f'--git-dir={私有仓}', f'--work-tree={根}', *参数],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', cwd=str(根))
    if check and r.returncode != 0:
        raise SystemExit(f'私有仓 git 失败: {" ".join(参数)}\n{(r.stderr or r.stdout)[:500]}')
    return r


def 初始化() -> int:
    print(f'项目根: {根}')
    print(f'私有仓: {私有仓}')
    if 私有仓.exists():
        print('  [跳过] 私有仓已存在')
    else:
        r = subprocess.run(['git', 'init', '--bare', str(私有仓)],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
        if r.returncode != 0:
            raise SystemExit(f'创建私有仓失败: {r.stderr[:300]}')
        subprocess.run(['git', f'--git-dir={私有仓}', 'config', 'core.bare', 'false'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
        print('  [OK] 私有仓已创建（工作区指向项目根，文件位置不变）')

    info = 私有仓 / 'info'
    info.mkdir(parents=True, exist_ok=True)
    (info / 'exclude').write_text(排除模板, encoding='utf-8')

    head = git('rev-parse', '--verify', 'HEAD')
    if head.returncode != 0:
        git('add', '-f', '--', *收集pathspec(), check=True)
        计 = git('status', '--short')
        文件数 = len([x for x in (计.stdout or '').splitlines() if x.strip()])
        if 文件数 == 0:
            print('  [警告] 私有仓没抓到任何文件 —— 检查路径与项目根')
            return 1
        git('-c', 'user.name=小说爬虫', '-c', 'user.email=noreply@local',
            'commit', '-m', 'chore(私有资产): 初始化多机同步仓', check=True)
        print(f'  [OK] 首次提交完成，纳入 {文件数} 个路径')
    else:
        print('  [跳过] 已有提交历史')

    ls = git('-c', 'core.quotepath=false', 'ls-files')
    文件s = [x for x in (ls.stdout or '').splitlines() if x.strip()]
    总字节 = sum((根 / x).stat().st_size for x in 文件s if (根 / x).is_file())
    print(f'  私有仓跟踪 {len(文件s)} 个文件 / {总字节 / 1024 / 1024:.1f} MB')
    for 前缀 in ('站点适配_本地/', '测试样本_本地/', '测试_本地/', '数据/', '.runtime/'):
        n = sum(1 for x in 文件s if x.startswith(前缀))
        print(f'    {前缀:<16} {n} 个文件')
    危险 = [x for x in 文件s
         if any(k in x for k in ('python314/', 'flet_client/', '__pycache__', 'browser_profile_'))]
    print('  混入大件/缓存:', 危险[:3] if 危险 else '无 OK')
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='多机同步 · 初始化私有资产仓（一次性）')
    ap.add_argument('--私有远端', default='', help='私有仓远端 URL（留空则稍后手工 add remote）')
    a = ap.parse_args(argv)

    rc = 初始化()
    if rc != 0:
        return rc

    if a.私有远端:
        git('remote', 'remove', 'origin')
        git('remote', 'add', 'origin', a.私有远端, check=True)
        print(f'  [OK] 远端 = {a.私有远端}')
        r = git('push', '-u', 'origin', 'HEAD:refs/heads/main')
        if r.returncode == 0:
            print('  [OK] 已推送（这台机是"源头机"）')
        else:
            print(f'  [提示] 推送失败: {(r.stderr or r.stdout)[:200]}')
    else:
        print('\n下一步（三选一）：')
        print('  ① 建一个 **私有** GitHub 仓，然后执行：')
        print(f'     git --git-dir="{私有仓}" --work-tree="{根}" remote add origin <私有仓URL>')
        print(f'     git --git-dir="{私有仓}" --work-tree="{根}" push -u origin HEAD:refs/heads/main')
        print('  ② 另一台机器已建好私有仓 ⇒ 直接 `python 脚本/多机同步.py`')
        print('  ③ 重跑本脚本加 --私有远端 <URL>（会覆盖 origin）')
        print('\n⚠️ 私有仓含真实站点信息与用户数据 —— 必须 Private，严禁公开。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
