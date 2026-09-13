# -*- coding: utf-8 -*-
"""生成/刷新 requirements-lock.txt (pip constraints 依赖精确锁定)。

## 为什么需要

`requirements.txt` 全是 `>=` 约束、无锁定文件。CI 每次发布都现场
`pip install -r requirements.txt` + 现场编译 Rust + onefile 打包 —— 上游依赖
跳一个版本就可能让"今天能打的 EXE 下周打不出"(且失败现场难复现, 因为本机
装的是旧版本)。本脚本把当前 .venv 的精确版本快照固化为 constraints 文件。

## 用法

    .venv\\Scripts\\python.exe 脚本\\gen_lock.py            # 生成/刷新 lock
    .venv\\Scripts\\python.exe 脚本\\gen_lock.py --check    # 只校验不写入

CI 与本地打包统一用:
    pip install -r requirements.txt -c requirements-lock.txt

## 设计

- **constraints 而非 requirements**: 本文件只钉版本, 不决定装哪些包。
  `requirements.txt` 仍是唯一的"意图声明"(带注释与上界), 两者职责分离 ——
  升级依赖时改 requirements, 再跑本脚本刷新 lock。
- pip constraints 语义保证: 列出但未被依赖的包不会被主动安装, 故本文件可以
  放心包含完整 freeze 快照(含传递依赖), 不会污染安装结果。
- 平台绑定: 快照来自 Windows + Python 3.14 的 .venv, 与 CI
  (windows-latest / 3.14) 一致。**不要在 Linux/macOS 上生成本文件**。
"""
import io
import os
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOCK = os.path.join(_ROOT, 'requirements-lock.txt')
_REQ = os.path.join(_ROOT, 'requirements.txt')

_HEADER = '''# ============================================================
# 小说爬虫 — 依赖精确锁定 (pip constraints)
# ============================================================
# 平台: Windows + Python 3.14 (与 CI windows-latest / 3.14 一致)
# 生成: {date}, 由 `脚本/gen_lock.py` 从当前 .venv 的 pip freeze 导出
#
# 用法 (CI 与本地打包均如此, 见 .github/workflows/*.yml):
#     pip install -r requirements.txt -c requirements-lock.txt
#
# 说明:
# - requirements.txt 是"意图声明"(带 >= 上界与注释), 本文件只"钉精确版本":
#   requirements 决定装哪些包, 本文件决定装哪个版本。
# - pip constraints 语义: 只约束版本, 不会主动安装本文件里列出但未被依赖的包。
# - 为何需要: requirements 全 >= 无锁定, 上游跳版本会让"今天能打的 EXE 下周
#   打不出"(CI 现场编译 Rust + onefile 打包对依赖版本敏感)。
# - 何时更新: 升级任何依赖后重跑 `python 脚本/gen_lock.py` 刷新本文件。
# - 本文件由脚本生成, 勿手工逐行编辑 (易与 freeze 不一致)。
# ============================================================
'''


def _freeze():
    """取当前解释器环境的精确版本快照"""
    r = subprocess.run([sys.executable, '-m', 'pip', 'freeze', '--exclude-editable'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode != 0:
        raise SystemExit(f'pip freeze 失败: {r.stderr}')
    out = []
    for ln in (r.stdout or '').splitlines():
        ln = ln.strip()
        # 跳过本地路径安装(-e / file://)与非 == 行
        if ln and '==' in ln and not ln.startswith('-'):
            out.append(ln)
    return sorted(out, key=lambda s: s.lower())


def _check(pkgs):
    """离线校验: lock 钉的版本是否满足 requirements.txt 的范围约束"""
    try:
        from packaging.requirements import Requirement
        from packaging.version import Version
    except ImportError:
        print('[跳过校验] packaging 不可用')
        return True

    lock = {}
    for ln in pkgs:
        n, v = ln.split('==', 1)
        lock[n.strip().lower().replace('_', '-')] = v.strip()

    ok = True
    with io.open(_REQ, encoding='utf-8') as f:
        for raw in f:
            line = raw.split('#', 1)[0].strip()
            if not line:
                continue
            import re
            base = re.split(r'[\[<>=!~; ]', line)[0].strip().lower().replace('_', '-')
            pinned = lock.get(base)
            if pinned is None:
                print(f'  [MISS] {base}: requirements 要求 {line}, lock 中无此包')
                ok = False
                continue
            try:
                if not Requirement(line).specifier.contains(Version(pinned), prereleases=True):
                    print(f'  [BAD]  {base}: lock={pinned} 不满足 {line}')
                    ok = False
            except Exception as e:
                print(f'  [ERR]  {base}: 解析失败 {e}')
                ok = False
    return ok


def main():
    pkgs = _freeze()
    if not pkgs:
        raise SystemExit('pip freeze 未返回任何包, 中止 (不写空 lock)')

    import time
    header = _HEADER.format(date=time.strftime('%Y-%m-%d'))
    content = header + '\n'.join(pkgs) + '\n'

    if '--check' in sys.argv:
        print(f'[check] lock 包数={len(pkgs)} (内存中, 未读盘)')
        sys.exit(0 if _check(pkgs) else 1)

    if os.path.exists(_LOCK):
        old = io.open(_LOCK, encoding='utf-8').read()
        if old == content:
            print(f'[无变化] {_LOCK} 已是最新 ({len(pkgs)} 包)')
            sys.exit(0)

    with io.open(_LOCK, 'w', encoding='utf-8', newline='\n') as f:
        f.write(content)
    print(f'[已写入] {_LOCK} ({len(pkgs)} 包)')

    if not _check(pkgs):
        print('[警告] lock 与 requirements 范围有不一致, 请人工核对后再提交')
        sys.exit(1)
    print('[校验通过] lock 钉版全部满足 requirements.txt 范围')


if __name__ == '__main__':
    main()
