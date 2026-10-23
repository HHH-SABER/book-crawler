# -*- coding: utf-8 -*-
"""系统剪贴板 —— 全项目唯一实现 (2026-10-23 用户实测"复制按钮没用"后统一)。

历史问题:
  · `远控`: 用 flet 的 `Clipboard().set()` (异步服务) —— 但新建实例**没挂到 page**,
    协程内部异常被吞 → 点复制毫无反应 (用户实测);
  · `日志页`: 直接用 `clip` + locale 编码 —— 中文在部分环境会乱码;
  · `插件安装`: 自己写了一份 (Set-Clipboard + tkinter 兜底), 能工作但三套实现。

本模块统一为一条可靠链路 (逐级降级, 全程不抛):
  ① 系统剪贴板命令行 (Set-Clipboard, 走环境变量传文本 → 无引号/编码坑)
  ② clip.exe (按本地代码页编码, 兼容老环境)
  ③ tkinter (最后兜底)
调用方只需 `if 剪贴板.复制(文本): 提示成功 else: 提示失败`。
"""
import os
import subprocess
import sys


def _系统剪贴板命令(文本: str) -> bool:
    try:
        subprocess.run(
            ['powershell', '-NoProfile', '-Command', 'Set-Clipboard -Value $env:NC_CLIP'],
            env={**os.environ, 'NC_CLIP': 文本}, timeout=10,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return True
    except Exception:
        return False


def _clip命令(文本: str) -> bool:
    """clip.exe 读的是控制台输入, 按本地代码页编码 (中文 Windows 为 GBK)。"""
    try:
        import locale
        enc = locale.getpreferredencoding(False) or 'gbk'
        proc = subprocess.Popen('clip', stdin=subprocess.PIPE, shell=False,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        proc.communicate(文本.encode(enc, errors='replace'), timeout=10)
        return proc.returncode == 0
    except Exception:
        return False


def _tkinter(文本: str) -> bool:
    try:
        import tkinter
        r = tkinter.Tk()
        r.withdraw()
        r.clipboard_clear()
        r.clipboard_append(文本)
        r.update()
        r.destroy()
        return True
    except Exception:
        return False


def 复制(文本: str) -> bool:
    """把文本放进系统剪贴板。返回是否成功 (永不抛异常)。"""
    if not 文本:
        return False
    for 实现 in (_系统剪贴板命令, _clip命令, _tkinter):
        try:
            if 实现(文本):
                return True
        except Exception:
            continue    # 刻意静默: 降级到下一实现, 最终返回 False 由调用方提示
    return False


def 读取() -> str:
    """读剪贴板 (诊断/测试用; 失败返回空串)。

    ⚠️ 不能直接读子进程 stdout: 控制台输出走本地代码页, 中文会乱码
    (2026-10-23 实测)。改走**文件中转** —— UTF-8 落盘再读, 与编码无关。
    """
    import tempfile
    from pathlib import Path
    try:
        临时 = Path(tempfile.gettempdir()) / f'nc_clip_{os.getpid()}.txt'
        subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             'Get-Clipboard -Raw | Set-Content -LiteralPath $env:NC_OUT -Encoding UTF8'],
            env={**os.environ, 'NC_OUT': str(临时)}, timeout=10,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if 临时.is_file():
            文本 = 临时.read_text(encoding='utf-8-sig', errors='replace')
            try:
                临时.unlink()
            except OSError:
                pass    # 刻意静默: 临时文件删不掉不影响返回值
            return 文本.rstrip('\r\n')
    except Exception:
        pass    # 刻意静默: 读剪贴板只是诊断能力, 失败返回空串即可
    return ''


if __name__ == '__main__':
    # 手工自检: python 剪贴板.py "要复制的文本"
    样本 = sys.argv[1] if len(sys.argv) > 1 else '剪贴板自检 OK'
    print('写入:', 复制(样本))
    print('读回:', 读取())
