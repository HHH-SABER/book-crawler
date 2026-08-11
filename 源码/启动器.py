# -*- coding: utf-8 -*-
"""ASCII 启动入口: 运行 爬虫.py 主程序。

用途: Windows bat 文件无法安全包含中文字符 (cmd 的 UTF-8/GBK 编码错位 bug),
因此 bat 调用本文件 (纯 ASCII 文件名), 由 Python 以 UTF-8 源码正确加载中文文件名。

命令行参数原样透传 (如 URL / --list / --threads 等)。
"""

import os
import sys
import runpy

HERE = os.path.dirname(os.path.abspath(__file__))
MAIN = os.path.join(HERE, '爬虫.py')

if __name__ == '__main__':
    # 将入口脚本路径指向主程序, 使 sys.argv[0] 语义正确
    sys.argv[0] = MAIN
    # run_path 执行主程序的 __main__ 块, 返回值是其模块全局命名空间, 不作为退出码
    runpy.run_path(MAIN, run_name='__main__')
