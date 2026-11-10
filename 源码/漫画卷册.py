# -*- coding: utf-8 -*-
"""漫画单行本分卷导出 —— **兼容适配层**（2026-11-10 起统一到 `漫画导出`）。

本模块原来自己实现了一套"按卷打包 CBZ"（ZIP_DEFLATED、输出到 `<书名>_单行本/`），
与 `漫画抓取.导出CBZ`（按话、ZIP_STORED、输出在话目录旁）各写各的 —— 同一份图
换个入口就得到不同压缩方式、命名与落点。现所有导出逻辑收敛到 `漫画导出.py`，
本模块只保留**原有公开签名**做委托，旧调用方与测试无需修改。

用法（不变）::

    python 源码/漫画卷册.py <已抓目录> --每卷话数 8
    python 源码/漫画卷册.py <已抓目录> --卷界 8,16,24,32,40,47 --输出 <目录>
    python 源码/漫画卷册.py <已抓目录> --卷界 8,16,24,32,40,47 --格式 pdf
"""
import argparse
import sys
from pathlib import Path
from typing import List, Optional, Sequence

import 漫画导出 as E

# 兼容：旧代码从本模块 import 这些常量/函数
图片后缀 = E.图片后缀
解析卷界 = E.解析卷界
均分卷界 = E.均分卷界
找话目录 = E.找话目录
话序 = E.话序


def 打包单行本(源根, 输出目录=None, 卷界: Optional[Sequence[int]] = None,
               每卷话数: int = 8, 卷名前缀: str = '第') -> List[Path]:
    """按卷导出（默认 CBZ）。返回生成的册文件列表。

    签名与旧版一致；`卷名前缀` 仅为兼容保留（新层统一 `第NN卷`，传非默认值时
    对产物做一次重命名）。
    """
    结果 = E.导出(源根, 输出目录, 格式='cbz', 单位='卷',
                  卷界=卷界, 每卷话数=每卷话数)
    册s = 结果['册s']
    if 卷名前缀 and 卷名前缀 != '第':
        改名 = []
        for p in 册s:
            新名 = p.with_name(p.name.replace('第', 卷名前缀, 1))
            p.rename(新名)
            改名.append(新名)
        册s = 改名
    return 册s


def 写目录索引(源根, 卷界: Sequence[int], 输出目录=None) -> Path:
    """生成 卷-话 对照表（签名与旧版一致）。"""
    话目录s = E.找话目录(Path(源根))
    各册 = E.分组(话目录s, '卷', 卷界)
    输出 = Path(输出目录) if 输出目录 else (
        Path(源根).parent / (Path(源根).name + '_单行本'))
    return E.写目录索引(话目录s, [len(本册) for _, 本册 in 各册], 输出)


def main(argv=None) -> int:
    解析器 = argparse.ArgumentParser(description='漫画单行本分卷导出 (cbz / pdf)')
    解析器.add_argument('源目录', help='已抓好的按话目录（内含 001_xxx/ 图片）')
    解析器.add_argument('--输出', default='', help='输出目录（默认 源目录_单行本）')
    解析器.add_argument('--每卷话数', type=int, default=0, help='等分卷（如 8）')
    解析器.add_argument('--卷界', default='', help='显式卷界，如 8,16,24,32,40,47')
    解析器.add_argument('--格式', default='cbz', choices=list(E.格式名s),
                    help='导出格式: cbz（默认）/ pdf / pages')
    参数 = 解析器.parse_args(argv)

    源 = Path(参数.源目录)
    话 = E.找话目录(源)
    if not 话:
        print(f'没有找到话目录（含图片的子目录）: {源}', file=sys.stderr)
        return 2

    if 参数.卷界:
        界 = E.解析卷界(参数.卷界, len(话))
    elif 参数.每卷话数:
        界 = E.均分卷界(len(话), 参数.每卷话数)
    else:
        界 = None

    结果 = E.导出(源, 参数.输出 or None, 格式=参数.格式, 单位='卷', 卷界=界)
    print(f"[OK] {结果['话数']} 话 / {结果['页数']} 页 → "
          f"{len(结果['册s'])} 册 ({结果['格式']})")
    for p in 结果['册s']:
        print(f'  {p.name}  {p.stat().st_size / 1048576:.1f} MB')
    print(f"  目录: {结果['输出目录']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
