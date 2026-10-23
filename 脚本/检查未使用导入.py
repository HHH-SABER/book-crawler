# -*- coding: utf-8 -*-
"""未使用导入检查 (F401) —— 2026-10-24 审查 W4 入门禁。

为什么单独立脚本: 项目的 AST 引用检查 (check_undefined_refs) 管"引用了不存在
的名字", 但管不了"导入了没用" —— 那正是 2026-10-24 审查发现的 50 处。

规则:
· 只查 源码/ (测试目录允许为可读性保留导入);
· gui_app.py 的 PyInstaller 依赖收集导入带 `# noqa: F401` (ruff 原生尊重),
  不受影响 —— 那是正确的打包实践, 不是坏味道;
· ruff 缺失时明确报错并给出安装命令 (不在门禁里静默跳过)。
"""
import subprocess
import sys
from pathlib import Path

项目根 = Path(__file__).resolve().parent.parent
源码目录 = 项目根 / '源码'


def main() -> int:
    try:
        import ruff  # noqa: F401
    except ImportError:
        print('[F401] ruff 未安装: 请运行 '
              '".runtime/python314/python.exe -m pip install ruff"')
        return 2
    结果 = subprocess.run(
        [sys.executable, '-m', 'ruff', 'check', '--select', 'F401',
         '--output-format', 'concise', str(源码目录)],
        capture_output=True, text=True, encoding='utf-8', errors='replace')
    输出 = (结果.stdout or '').strip()
    if 结果.returncode == 0:
        print(f'[F401] 未使用导入检查通过 ({源码目录.name}/)')
        return 0
    print(f'[F401] 发现未使用导入:\n{输出}')
    print('\n修复: python -m ruff check --select F401 源码/ --fix')
    return 1


if __name__ == '__main__':
    sys.exit(main())
