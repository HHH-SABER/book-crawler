# -*- coding: utf-8 -*-
"""首次启动引导与桌面快捷方式 (2026-10-13 从 gui_app.main() 闭包提取)。

## 为什么提取

这几个函数原先是 `gui_app.main()` 里的闭包 (`_写首次flag`/`_建桌面快捷方式`/
`_首次引导`), 共享 page 与组件引用 ⇒ **无法单测** (测它们要起整个 GUI)。
提取为模块级函数后: 行为不变, 但命令构造/flag 读写/分支判定都可在**无 GUI
环境**下断言 (mock subprocess + 临时目录)。

## 行为契约 (与原闭包完全一致, 改动不得破坏)

1. flag 文件 = `<state_root>/数据/首次启动.flag`, 原子写 (tmp + os.replace);
2. 快捷方式名 `小说爬虫.lnk`, 桌面路径在 **PowerShell 侧**取
   (`[Environment]::GetFolderPath('Desktop')`) —— 只有那样才能拿到 OneDrive
   重定向后的真实桌面;
3. 中文参数经 `-EncodedCommand` (UTF-16LE Base64) 传入, 规避代码页转义坑;
4. **失败必须把 PS stderr 带进异常** (2026-10-04 #5 修复: 只报退出码时,
   用户与日志都拿不到"为什么失败")。
"""
import os
import subprocess
import sys
from pathlib import Path

try:
    from _path_utils import get_state_root
except Exception:                                    # 独立环境退化标准库
    def get_state_root() -> str:
        return os.path.join(os.path.expanduser('~'), '.novelcrawler')

_标志文件名 = '首次启动.flag'
_快捷方式名 = '小说爬虫.lnk'
_PS超时秒 = 20


def 首次flag路径() -> str:
    return os.path.join(get_state_root(), '数据', _标志文件名)


def 是否首次启动() -> bool:
    """flag 不存在 ⇒ 首次 (双检由调用方决定, 这里只做纯判断)。"""
    return not os.path.exists(首次flag路径())


def 写首次flag(结果: str = '已询问创建桌面快捷方式') -> None:
    """原子写首次启动标记 (tmp + os.replace, 对齐项目状态文件规约)。"""
    import time as _tm
    p = 首次flag路径()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = f"{p}.tmp.{os.getpid()}"
    # 链式 resolve().write_text(): 动态路径写入前规范化 (静态扫描要求)
    Path(tmp).resolve().write_text(
        f"{结果}: {_tm.strftime('%Y-%m-%d %H:%M:%S')}\n", encoding='utf-8')
    os.replace(tmp, p)


def 程序目标路径() -> str:
    """快捷方式指向的目标: EXE 本体 (打包后) 或 启动GUI.bat (源码运行)。"""
    if getattr(sys, 'frozen', False):
        return os.path.abspath(sys.executable)
    return os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), '启动GUI.bat')


def 构建PowerShell命令(target: str, workdir: str) -> str:
    """构造创建快捷方式的 PowerShell 脚本 (纯函数, 可单测)。

    桌面路径在 PS 侧取 ⇒ 支持 OneDrive 重定向; 中文经 -EncodedCommand 传入。
    """
    引号转义 = lambda s: s.replace("'", "''")
    return (
        "$ErrorActionPreference='Stop';"
        "$desk=[Environment]::GetFolderPath('Desktop');"
        "$ws=New-Object -ComObject WScript.Shell;"
        f"$lnk=$ws.CreateShortcut((Join-Path $desk '{_快捷方式名}'));"
        f"$lnk.TargetPath='{引号转义(target)}';"
        f"$lnk.WorkingDirectory='{引号转义(workdir)}';"
        f"$lnk.IconLocation='{引号转义(target)},0';"
        "$lnk.Description='小说爬虫 - 网文离线阅读与远控';"
        "$lnk.Save();exit 0"
    )


def 建桌面快捷方式(target: str = None, 运行器=subprocess.run) -> None:
    """创建桌面快捷方式; 失败抛异常 (stderr 进消息, 见模块 docstring ④)。

    Args:
        target: 目标路径, 缺省按 `程序目标路径()` 自动判 (EXE/bat);
        运行器: subprocess.run 替身 (测试注入), 签名兼容
                (argv, capture_output, timeout) → 对象有 returncode/stderr。
    """
    import base64
    target = target or 程序目标路径()
    workdir = os.path.dirname(target)
    ps = 构建PowerShell命令(target, workdir)
    enc = base64.b64encode(ps.encode('utf-16-le')).decode('ascii')
    r = 运行器(
        ['powershell', '-NoProfile', '-NonInteractive',
         '-ExecutionPolicy', 'Bypass', '-EncodedCommand', enc],
        capture_output=True, timeout=_PS超时秒)
    if r.returncode != 0:
        err = (r.stderr or b'').decode('utf-8', errors='replace').strip()
        raise RuntimeError(f'PowerShell 退出码 {r.returncode}'
                           + (f': {err[:200]}' if err else ''))
