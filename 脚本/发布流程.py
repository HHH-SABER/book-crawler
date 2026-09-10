# -*- coding: utf-8 -*-
"""标准升级/发版流程 (门禁化, 每步验证通过才进入下一步)。

流程 (任一步失败立即中止, 不进入下一步):

    ① 离线回归      python -m unittest discover -s 测试        必须 OK
    ② 手写回归      python 测试/回归测试_修复验证.py            必须 0 失败
    ③ 静态检查      python 脚本/check_undefined_refs.py         必须无告警
    ④ 打包 EXE      python 脚本/build_exe.py [--bump=...]       需产物存在
    ⑤ 冒烟          build_exe.py 内置 (启动 EXE 验活, 失败即构建失败)
    ⑥ 提交          git add -A && git commit                    需工作区干净进入
    ⑦ 推送          git push origin <分支>                      需与远端一致

为什么把 ①②③ 放在打包之前: 打包一次要几分钟且会改版本号与 CHANGELOG,
门禁不过就打包 = 白烧时间还把版本号消耗掉 (历史踩过的坑)。

用法:
    python 脚本/发布流程.py                # 只跑门禁 + 打包 (不提交不推送)
    python 脚本/发布流程.py --push          # 门禁 + 打包 + 提交 + 推送
    python 脚本/发布流程.py --push --no-bump
    python 脚本/发布流程.py --仅门禁        # 只跑 ①②③
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

根目录 = Path(__file__).resolve().parent.parent
PY = str(根目录 / '.venv' / 'Scripts' / 'python.exe')
if not Path(PY).exists():
    PY = sys.executable


def 标题(文本):
    print('\n' + '=' * 64)
    print(文本)
    print('=' * 64, flush=True)


def 跑(命令, **kw):
    """跑一条命令, 返回 (是否成功, 输出文本)"""
    环境 = os.environ.copy()
    环境['PYTHONUTF8'] = '1'
    环境['PYTHONIOENCODING'] = 'utf-8'
    try:
        r = subprocess.run(命令, cwd=str(根目录), env=环境,
                           capture_output=True, text=True,
                           encoding='utf-8', errors='replace', **kw)
    except Exception as e:
        return False, f'启动失败: {type(e).__name__}: {e}'
    out = (r.stdout or '') + (r.stderr or '')
    # 过滤已知无害噪音, 保持输出可读
    out = '\n'.join(l for l in out.splitlines()
                    if 'shell-runtime-bash-env.sh' not in l
                    and 'command not found' not in l)
    return r.returncode == 0, out


def 尾部(文本, 行数=18):
    lines = [l for l in 文本.splitlines() if l.strip()]
    return '\n'.join(lines[-行数:])


def 门禁():
    """①②③: 三项门禁, 全部通过返回 True"""
    标题('① 离线回归测试 (unittest discover -s 测试)')
    ok, out = 跑([PY, '-m', 'unittest', 'discover', '-s', '测试'])
    print(尾部(out))
    if not ok:
        print('\n❌ 步骤①失败: 离线回归测试未通过, 已中止。')
        return False
    if 'Ran ' not in out or 'OK' not in out:
        print('\n❌ 步骤①失败: 未看到 "Ran N tests / OK" 结论, 判定为异常。')
        return False
    print('✅ 步骤①通过')

    标题('② 手写回归脚本 (测试/回归测试_修复验证.py)')
    ok, out = 跑([PY, '测试/回归测试_修复验证.py'])
    print(尾部(out, 8))
    if not ok or '0 失败' not in out:
        print('\n❌ 步骤②失败: 手写回归未全通过 (或未打印 "0 失败"), 已中止。')
        return False
    print('✅ 步骤②通过')

    标题('③ 静态检查 (脚本/check_undefined_refs.py)')
    ok, out = 跑([PY, '脚本/check_undefined_refs.py'])
    print(尾部(out, 10))
    if not ok or '全部干净' not in out:
        print('\n❌ 步骤③失败: 存在未定义引用, 已中止 (打包会产出运行时崩溃的 EXE)。')
        return False
    print('✅ 步骤③通过')
    return True


def 打包(参数):
    标题('④⑤ 打包 EXE (脚本/build_exe.py, 内置启动冒烟)')
    cmd = [PY, '脚本/build_exe.py']
    if 参数.no_bump:
        cmd.append('--no-bump')
    elif 参数.bump:
        cmd.append(f'--bump={参数.bump}')
    ok, out = 跑(cmd)
    print(尾部(out, 30))
    产物 = list((根目录 / 'dist').glob('*.exe'))
    if not ok:
        print('\n❌ 步骤④失败: 打包未成功, 已中止 (未提交, 工作区保持可修状态)。')
        return False
    if not 产物:
        print('\n❌ 步骤④失败: 打包命令报成功但 dist/ 下没有 .exe 产物, 已中止。')
        return False
    最大 = max(产物, key=lambda p: p.stat().st_size)
    print(f'✅ 步骤④⑤通过: 产物 {最大.name} ({最大.stat().st_size/1024/1024:.1f} MB)')
    return True


def 提交推送(参数):
    标题('⑥ 提交')
    ok, out = 跑(['git', 'add', '-A'])
    if not ok:
        print(f'❌ git add 失败: {尾部(out, 6)}')
        return False
    ok, out = 跑(['git', 'commit', '-m', 参数.message])
    print(尾部(out, 12))
    if not ok and 'nothing to commit' not in out:
        print('\n❌ 步骤⑥失败: 提交失败, 已中止 (不推送未提交的改动)。')
        return False
    print('✅ 步骤⑥通过')

    标题('⑦ 推送')
    分支 = 参数.branch
    # 环境注入的 http(s)_proxy 对大连接不稳 (push 挂起/502), 推送前剥掉
    环境 = os.environ.copy()
    for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
        环境.pop(k, None)
    环境['GCM_INTERACTIVE'] = 'none'
    try:
        r = subprocess.run(['git', 'push', 'origin', 分支],
                           cwd=str(根目录), env=环境,
                           capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=600)
        out = (r.stdout or '') + (r.stderr or '')
    except subprocess.TimeoutExpired:
        print('\n❌ 步骤⑦失败: 推送超时 (>10 分钟), 已中止。')
        return False
    print(尾部(out, 14))
    if r.returncode != 0:
        print('\n❌ 步骤⑦失败: 推送被拒绝或失败, 已中止。')
        return False
    print('✅ 步骤⑦通过: 已推送到 origin/' + 分支)
    return True


def main():
    p = argparse.ArgumentParser(description='标准升级/发版流程 (门禁化)')
    p.add_argument('--push', action='store_true', help='打包后提交并推送')
    p.add_argument('--仅门禁', dest='only_gate', action='store_true',
                   help='只跑 ①②③ 三项门禁')
    p.add_argument('--no-bump', dest='no_bump', action='store_true',
                   help='打包不递增版本号')
    p.add_argument('--bump', choices=['patch', 'minor', 'major'],
                   default=None, help='版本号递增级别 (默认由 build_exe 决定)')
    p.add_argument('--branch', default='main', help='推送分支 (默认 main)')
    p.add_argument('--message', default='chore(release): 发版校验通过后提交',
                   help='提交信息')
    参数 = p.parse_args()

    print(f'项目根目录: {根目录}')
    print(f'Python    : {PY}')

    if not 门禁():
        sys.exit(1)
    if 参数.only_gate:
        print('\n🎉 仅门禁模式: 三项门禁全部通过。')
        return

    if not 打包(参数):
        sys.exit(1)

    if not 参数.push:
        print('\n🎉 门禁 + 打包全部通过 (未提交未推送)。')
        print('   需要提交并推送时重跑: python 脚本/发布流程.py --push')
        return

    if not 提交推送(参数):
        sys.exit(1)
    print('\n🎉 全流程通过: 测试 → 打包 → 提交 → 推送。')


if __name__ == '__main__':
    main()
