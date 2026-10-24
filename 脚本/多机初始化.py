# -*- coding: utf-8 -*-
"""多机同步 · 一次性初始化（每台机器跑一次，2026-10-24）。

## 两种场景，脚本自动区分

| 场景 | 判断 | 动作 |
|---|---|---|
| **本机首次**（还没私有仓） | `--私有远端` 为空，或远端是空的 | `git init --bare` + 白名单 `add -f` + 首提交（给了 URL 就推送）|
| **第二台机器**（远端已有内容） | `--私有远端` 有值且 `git ls-remote` 非空 | **`git clone --bare` 拉到本地仓 + `checkout -f` 落地文件**（不新建、不推送）|
| 已有私有仓 | 本地仓已存在 | 只提示，不重复初始化 |

**原理**：私有仓用 `git --git-dir=<父目录>/小说爬虫-私有资产.git --work-tree=<项目根>`，
工作区直接指向项目根，只跟踪被公开仓忽略的那几个路径（详见 `_多机共用.py`）。
文件位置不变 ⇒ 代码/打包脚本零改动，也不会有目录联接（junction）的兼容问题。

## 用法

    # 本机首次（源头机）：建仓并推送
    .runtime\\python314\\python.exe 脚本\\多机初始化.py --私有远端 https://github.com/<你>/<私有仓>.git

    # 第二台机器：从远端拉私有资产
    .runtime\\python314\\python.exe 脚本\\多机初始化.py --私有远端 https://github.com/<你>/<私有仓>.git

（同一命令，脚本自己判断走哪条路。）

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


def 远端已有内容(url: str) -> bool:
    """远端是否已有分支（= 另一台机器已经推过私有资产）。"""
    r = subprocess.run(['git', 'ls-remote', '--heads', url],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=120)
    return r.returncode == 0 and bool((r.stdout or '').strip())


def 写排除文件() -> None:
    info = 私有仓 / 'info'
    info.mkdir(parents=True, exist_ok=True)
    (info / 'exclude').write_text(排除模板, encoding='utf-8')


def 统计(前缀列表) -> None:
    ls = git('-c', 'core.quotepath=false', 'ls-files')
    文件s = [x for x in (ls.stdout or '').splitlines() if x.strip()]
    总字节 = sum((根 / x).stat().st_size for x in 文件s if (根 / x).is_file())
    print(f'  私有仓跟踪 {len(文件s)} 个文件 / {总字节 / 1024 / 1024:.1f} MB')
    for 前缀 in 前缀列表:
        n = sum(1 for x in 文件s if x.startswith(前缀))
        print(f'    {前缀:<16} {n} 个文件')
    危险 = [x for x in 文件s
         if any(k in x for k in ('python314/', 'flet_client/', '__pycache__', 'browser_profile_'))]
    print('  混入大件/缓存:', 危险[:3] if 危险 else '无 OK')


def 从远端克隆(url: str) -> int:
    """第二台机器：克隆私有仓到本地，并把文件落地到项目根。"""
    print(f'  [模式] 远端已有内容 ⇒ 克隆（不新建、不推送）')
    r = subprocess.run(['git', 'clone', '--bare', url, str(私有仓)],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode != 0:
        print(f'  [失败] 克隆失败: {(r.stderr or r.stdout)[:300]}')
        print('         可能原因：私有仓地址错 / 无权限（私有仓需要登录）/ 网络')
        return 1
    print('  [OK] 私有仓已克隆')
    for 参数 in (['config', 'core.bare', 'false'],
                ['symbolic-ref', 'HEAD', 'refs/heads/main']):
        subprocess.run(['git', f'--git-dir={私有仓}', *参数], capture_output=True)
    写排除文件()
    出 = git('checkout', '-f', 'main')
    if 出.returncode != 0:
        print(f'  [失败] 落地文件失败: {(出.stderr or 出.stdout)[:300]}')
        return 1
    print('  [OK] 私有资产已落地到项目根（文件位置不变）')
    统计(('站点适配_本地/', '测试样本_本地/', '测试_本地/', '数据/', '.runtime/'))
    print('\n下一步：.runtime\\python314\\python.exe 脚本\\多机同步.py --全量')
    return 0


def 本机首次(url: str) -> int:
    print('  [模式] 本地无私有仓且远端为空 ⇒ 新建并纳入白名单')
    r = subprocess.run(['git', 'init', '--bare', str(私有仓)],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode != 0:
        print(f'  [失败] 创建私有仓失败: {r.stderr[:300]}')
        return 1
    subprocess.run(['git', f'--git-dir={私有仓}', 'config', 'core.bare', 'false'],
                   capture_output=True)
    print('  [OK] 私有仓已创建')
    写排除文件()

    git('add', '-f', '--', *收集pathspec(), check=True)
    计 = git('status', '--short')
    文件数 = len([x for x in (计.stdout or '').splitlines() if x.strip()])
    if 文件数 == 0:
        print('  [警告] 没抓到任何文件 —— 检查路径与项目根')
        return 1
    git('-c', 'user.name=小说爬虫', '-c', 'user.email=noreply@local',
        'commit', '-m', 'chore(私有资产): 初始化多机同步仓', check=True)
    print(f'  [OK] 首次提交完成，纳入 {文件数} 个路径')
    统计(('站点适配_本地/', '测试样本_本地/', '测试_本地/', '数据/', '.runtime/'))

    if url:
        git('remote', 'remove', 'origin')
        git('remote', 'add', 'origin', url, check=True)
        print(f'  [OK] 远端 = {url}')
        r = git('push', '-u', 'origin', 'HEAD:refs/heads/main')
        if r.returncode == 0:
            print('  [OK] 已推送（这台机是"源头机"）')
        else:
            print(f'  [提示] 推送失败: {(r.stderr or r.stdout)[:200]}')
            return 1
    else:
        print('\n未给 --私有远端：稍后按下面命令绑定（或重跑本脚本带该参数）：')
        print(f'  git --git-dir="{私有仓}" --work-tree="{根}" remote add origin <私有仓URL>')
        print(f'  git --git-dir="{私有仓}" --work-tree="{根}" push -u origin HEAD:refs/heads/main')
        print('\n⚠️ 私有仓含真实站点信息与用户数据 —— 必须 Private，严禁公开。')
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='多机同步 · 初始化/拉取私有资产仓（每台机器一次）')
    ap.add_argument('--私有远端', default='', help='私有仓远端 URL')
    a = ap.parse_args(argv)

    print(f'项目根: {根}')
    print(f'私有仓: {私有仓}')
    if 私有仓.exists():
        print('  [跳过] 本地私有仓已存在（日常请用 脚本/多机同步.py）')
        return 0

    if a.私有远端 and 远端已有内容(a.私有远端):
        return 从远端克隆(a.私有远端)
    return 本机首次(a.私有远端)


if __name__ == '__main__':
    sys.exit(main())
