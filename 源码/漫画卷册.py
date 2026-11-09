# -*- coding: utf-8 -*-
"""漫画单行本分卷打包 (CBZ)。

用途
----
站点通常按"话"发布，单行本是"卷"。本模块把已抓好的按话目录，按**卷界**
（每卷收录哪些话）重新组织成 6 个 CBZ（或任意卷数），供阅读器直接翻阅。

不依赖任何站点：只认 `<书名目录>/<话目录>/<页码图片>` 这种结构；
卷标题/卷界由调用方给（可选 `卷界` 或 `每卷话数`）。

CBZ 内结构（ComicInfo 兼容惯例）::

    第01卷/
      001_第1话/0001.webp
      001_第1话/0002.webp
      ...

用法
----
    python 源码/漫画卷册.py <已抓目录> --每卷话数 8
    python 源码/漫画卷册.py <已抓目录> --卷界 8,16,24,32,40,47 --输出 <目录>
"""
import argparse
import re
import sys
import zipfile
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

图片后缀 = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.avif'}


def 解析卷界(文本: str, 总话数: int) -> List[int]:
    """'8,16,24' → [8,16,24]，校验递增且不超过总话数。"""
    界 = []
    for 段 in str(文本).replace('，', ',').split(','):
        段 = 段.strip()
        if not 段:
            continue
        if not 段.isdigit():
            raise ValueError(f'卷界必须是正整数: {段!r}')
        界.append(int(段))
    if not 界:
        raise ValueError('卷界为空')
    if 界 != sorted(界) or len(set(界)) != len(界):
        raise ValueError('卷界必须严格递增')
    if 界[-1] != 总话数:
        raise ValueError(f'最后一卷应止于第 {总话数} 话（当前 {界[-1]}）')
    return 界


def 均分卷界(总话数: int, 每卷话数: int) -> List[int]:
    if 每卷话数 <= 0:
        raise ValueError('每卷话数必须为正')
    界 = list(range(每卷话数, 总话数, 每卷话数))
    界.append(总话数)
    return 界


def 找话目录(根: Path) -> List[Path]:
    """一章一目录；只取含图片的子目录（排除 CBZ 输出目录等）。"""
    结果 = []
    # 按话序排（字典序会把 10 排在 2 前，分卷就错位）
    for d in sorted(根.iterdir(), key=lambda p: 话序(p.name)):
        if not d.is_dir():
            continue
        if any(p.suffix.lower() in 图片后缀 for p in d.iterdir() if p.is_file()):
            结果.append(d)
    return 结果


def 话序(目录名: str) -> Tuple[int, str]:
    """'007_第7话' → (7, '第7话')；无序号时退回大数保序。"""
    m = re.match(r'^(\d+)[_\-.]?(.*)$', 目录名)
    if m:
        return int(m.group(1)), (m.group(2) or 目录名)
    return 10 ** 9, 目录名


def 打包单行本(源根, 输出目录=None, 卷界: Optional[Sequence[int]] = None,
               每卷话数: int = 8, 卷名前缀: str = '第') -> List[Path]:
    """把按话目录打成按卷 CBZ。返回生成的 CBZ 路径列表。"""
    源根 = Path(源根)
    if not 源根.is_dir():
        raise FileNotFoundError(f'目录不存在: {源根}')
    话目录 = 找话目录(源根)
    if not 话目录:
        raise ValueError(f'没有找到话目录（含图片的子目录）: {源根}')
    总 = len(话目录)
    界 = list(卷界) if 卷界 else 均分卷界(总, 每卷话数)
    输出 = Path(输出目录) if 输出目录 else 源根.parent / (源根.name + '_单行本')
    输出.mkdir(parents=True, exist_ok=True)

    卷s = []
    起 = 0
    for 卷号, 止 in enumerate(界, start=1):
        本卷 = 话目录[起:止]
        起 = 止
        if not 本卷:
            continue
        名 = f'{卷名前缀}{卷号:02d}卷'
        cbz = 输出 / f'{名}.cbz'
        临时 = cbz.with_suffix('.cbz.tmp')
        with zipfile.ZipFile(临时, 'w', zipfile.ZIP_DEFLATED) as z:
            for 话 in 本卷:
                图s = sorted(p for p in 话.iterdir()
                            if p.is_file() and p.suffix.lower() in 图片后缀)
                for 图 in 图s:
                    z.write(图, f'{名}/{话.name}/{图.name}')
        临时.replace(cbz)
        卷s.append(cbz)
    return 卷s


def 写目录索引(源根, 卷界: Sequence[int], 输出目录=None) -> Path:
    """生成 卷-话 对照表（纯结构信息，不含站点）。"""
    源根 = Path(源根)
    话目录 = 找话目录(源根)
    输出 = Path(输出目录) if 输出目录 else 源根.parent / (源根.name + '_单行本')
    输出.mkdir(parents=True, exist_ok=True)
    行s = ['# 单行本卷话对照', '', '| 卷 | 收录话 | 页数 |', '|---|---|---|']
    起 = 0
    for 卷号, 止 in enumerate(卷界, start=1):
        本卷 = 话目录[起:止]
        起 = 止
        if not 本卷:
            continue
        首 = 话序(本卷[0].name)[1]
        末 = 话序(本卷[-1].name)[1]
        页 = sum(1 for 话 in 本卷 for p in 话.iterdir()
                if p.is_file() and p.suffix.lower() in 图片后缀)
        行s.append(f'| 第{卷号:02d}卷 | {首} ~ {末}（{len(本卷)} 话） | {页} |')
    行s += ['', f'共 {len(话目录)} 话 / {len(卷界)} 卷。']
    目标 = 输出 / '卷目录.md'
    目标.write_text('\n'.join(行s) + '\n', encoding='utf-8')
    return 目标


def main(argv=None) -> int:
    解析器 = argparse.ArgumentParser(description='漫画单行本分卷打包 (CBZ)')
    解析器.add_argument('源目录', help='已抓好的按话目录（内含 001_xxx/ 图片）')
    解析器.add_argument('--输出', default='', help='输出目录（默认 源目录_单行本）')
    解析器.add_argument('--每卷话数', type=int, default=0, help='等分卷（如 8）')
    解析器.add_argument('--卷界', default='', help='显式卷界，如 8,16,24,32,40,47')
    参数 = 解析器.parse_args(argv)

    源 = Path(参数.源目录)
    话 = 找话目录(源)
    if 参数.卷界:
        界 = 解析卷界(参数.卷界, len(话))
    elif 参数.每卷话数:
        界 = 均分卷界(len(话), 参数.每卷话数)
    else:
        print('需要 --每卷话数 或 --卷界', file=sys.stderr)
        return 2

    卷s = 打包单行本(源, 参数.输出 or None, 界)
    索引 = 写目录索引(源, 界, 参数.输出 or None)
    print(f'[OK] {len(话)} 话 → {len(卷s)} 卷')
    for c in 卷s:
        print(f'  {c.name}  {c.stat().st_size / 1048576:.1f} MB')
    print(f'  索引: {索引}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
