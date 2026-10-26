# -*- coding: utf-8 -*-
"""多机同步共用常量与收集规则（2026-10-24）。

私有仓的 `--work-tree` 就是项目根，因此 git 会读到**公开仓的 `.gitignore`**，
且它的优先级高于 `info/exclude` ⇒ 白名单必须靠 `git add -f` 强制纳入。

`:(glob)` 魔法是必需的：git 默认 pathspec 里的 `*` 会**跨目录**匹配，
用 `.runtime/*.py` 会把 `.runtime/python314/Lib/**/*.py` 也一起吞进来（实测 193MB）。
另外缓存/字节码/浏览器 profile 属可再生成物，显式排除。
"""
import os
import pathlib

根 = pathlib.Path(__file__).resolve().parent.parent
#: 允许用环境变量改私有仓位置（换机/测试/放到其它盘时用）
_私有仓覆盖 = os.environ.get('NC_PRIVATE_GIT_DIR', '').strip()
私有仓 = pathlib.Path(_私有仓覆盖) if _私有仓覆盖 else (根.parent / '小说爬虫-私有资产.git')

#: 只收这些路径（相对项目根，glob 语义）
白名单目录 = ('站点适配_本地', '测试样本_本地', '测试_本地', '数据')

#: 显式排除（可再生成物）
排除模式 = (
    ':(exclude,glob)**/__pycache__/**',
    ':(exclude,glob)**/browser_profile_*/**',
    ':(exclude,glob)**/*.pyc',
    ':(exclude,glob)**/*.log',
    ':(exclude,glob)**/Cache/**',
    # Mimosa 安全扫描的 hook 运行时状态 (10-26 实测被误收进私有仓):
    # 每会话/每文件的基线缓存, 纯工具链产物, 换机即失效
    ':(exclude,glob)**/.mimosa/**',
)


def 收集pathspec() -> list:
    """返回 `git add -f -- <pathspec...>` 用的完整参数列表。"""
    paths = [f':(glob){x}/**' for x in 白名单目录]
    paths += [':(glob).runtime/*.py', ':(glob)HANDOFF.md']
    return paths + list(排除模式)
