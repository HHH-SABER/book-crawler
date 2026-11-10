# -*- coding: utf-8 -*-
"""漫画导出统一层 —— **唯一**决定"导出什么格式、怎么组织"的地方。

为什么要有这一层（2026-11-10）
--------------------------------
此前有两套各写各的导出：
· `漫画抓取.导出CBZ`      —— 按**话**打包, ZIP_STORED,  输出在话目录旁;
· `漫画卷册.打包单行本`    —— 按**卷**打包, ZIP_DEFLATED, 输出到 `<书名>_单行本/`。
同一份图, 换个入口就得到不同压缩方式、不同命名、不同落点的产物, 用户看到
"一处 webp 一处 cbz" 的割裂感。现统一到本模块, 两个旧入口只做委托。

格式
----
· `pages` —— 逐页图片目录（保持源目录, 不生成新文件）
· `cbz`   —— ZIP 打包（图片原样, **ZIP_STORED** 不二次压缩: webp/jpg 已压缩,
             DEFLATE 只多耗 CPU 换 1% 体积）
· `pdf`   —— 每册一个 PDF（PIL 逐页排版, RGB, JPEG 质量 90）

打包单位
--------
· `卷` —— 按卷界把多话合成一册（单行本形态）, 命名 `第01卷.cbz|pdf`
· `话` —— 一话一册（追更形态）,            命名 `001_第1话.cbz|pdf`

行为约定（与格式无关, 三种格式一致）
------------------------------------
1. 只读源图, 绝不修改/移动原始文件;
2. 跳过非图片与 <1KB 的坏图;
3. 页序按文件名排序（补零命名保证）;
4. 输出先写 `.tmp` 再原子替换, 中断不会留下半个文件;
5. 返回生成的册文件列表（`pages` 返回空列表, 因为不产新文件）。
"""
import re
import zipfile
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

图片后缀 = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.avif'}
格式名s = ('pages', 'cbz', 'pdf')
单位名s = ('卷', '话')

_PDF_质量 = 90           # PDF 内页 JPEG 质量
_PDF_分辨率 = 96         # 决定页面物理尺寸 (px / 96 = 英寸)


# ------------------------------------------------------------------ 目录扫描
def 话序(目录名: str) -> Tuple[int, str]:
    """`007_第7话` → (7, '第7话'); 无序号时排到最后但保持稳定。"""
    m = re.match(r'^(\d+)[_\-.]?(.*)$', 目录名)
    if m:
        return int(m.group(1)), (m.group(2) or 目录名)
    return 10 ** 9, 目录名


def 找话目录(根: Path) -> List[Path]:
    """含图片的子目录, 按话序排列（不是字典序, 否则 10 会排到 2 前）。"""
    根 = Path(根)
    结果 = [d for d in 根.iterdir()
            if d.is_dir() and any(p.is_file() and p.suffix.lower() in 图片后缀
                                  for p in d.iterdir())]
    return sorted(结果, key=lambda p: 话序(p.name))


def 列页(话目录: Path) -> List[Path]:
    """一话内的有效图片页（升序, 过滤坏图）。"""
    return sorted(p for p in 话目录.iterdir()
                  if p.is_file() and p.suffix.lower() in 图片后缀
                  and p.stat().st_size > 1024)


# ------------------------------------------------------------------ 分组
def 解析卷界(文本: str, 总话数: int) -> List[int]:
    """`8,16,24` → [8,16,24]; 校验严格递增且末位等于总话数。"""
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


def 分组(话目录s: Sequence[Path], 单位: str = '卷',
         卷界: Optional[Sequence[int]] = None,
         每卷话数: int = 8) -> List[Tuple[str, List[Path]]]:
    """把话目录分成若干"册": [(册名, [话目录...]), ...]。

    `单位='话'` 时一话一册, 册名取话目录名（去掉补零前缀外的原样）。
    """
    if 单位 not in 单位名s:
        raise ValueError(f'未知打包单位: {单位!r}（可选 {单位名s}）')
    if 单位 == '话':
        return [(p.name, [p]) for p in 话目录s]

    if not 话目录s:
        return []
    界 = list(卷界) if 卷界 else 均分卷界(len(话目录s), 每卷话数)
    册s, 起 = [], 0
    for 卷号, 止 in enumerate(界, start=1):
        本卷 = list(话目录s[起:止])
        起 = 止
        if 本卷:
            册s.append((f'第{卷号:02d}卷', 本卷))
    return 册s


# ------------------------------------------------------------------ 导出
def 导出册(册名: str, 话目录s: Sequence[Path], 输出目录: Path, 格式: str) -> Optional[Path]:
    """导出一册。格式 pages 返回 None（不产文件）。"""
    if 格式 not in 格式名s:
        raise ValueError(f'未知导出格式: {格式!r}（可选 {格式名s}）')
    if 格式 == 'pages':
        return None

    输出目录 = Path(输出目录)
    输出目录.mkdir(parents=True, exist_ok=True)
    目标 = 输出目录 / f'{册名}.{格式}'
    临时 = 目标.with_name(目标.name + '.tmp')

    页s = [(话.name, p) for 话 in 话目录s for p in 列页(话)]
    if not 页s:
        return None

    # 一册只有一话（话级导出）→ 内部扁平, 不套同名目录; 多话（卷级）→ 分层
    分层 = len(话目录s) > 1

    if 格式 == 'cbz':
        # ZIP_STORED: webp/jpg 本身已压缩, DEFLATE 只多耗 CPU
        with zipfile.ZipFile(临时, 'w', zipfile.ZIP_STORED) as z:
            for 话名, p in 页s:
                z.write(p, f'{册名}/{话名}/{p.name}' if 分层 else p.name)
    else:
        from PIL import Image
        首 = Image.open(页s[0][1]).convert('RGB')
        其余 = [Image.open(p).convert('RGB') for _, p in 页s[1:]]
        try:
            首.save(临时, 'PDF', save_all=True, append_images=其余,
                    quality=_PDF_质量, resolution=_PDF_分辨率)
        finally:
            for im in 其余:
                im.close()
            首.close()

    临时.replace(目标)
    return 目标


def 导出(源目录, 输出目录=None, 格式: str = 'cbz', 单位: str = '卷',
         卷界: Optional[Sequence[int]] = None, 每卷话数: int = 8,
         写索引: bool = True) -> dict:
    """统一导出入口。

    返回 {'格式', '单位', '输出目录', '册s': [Path], '话数', '页数'}。
    `pages` 不产新文件（源目录就是逐页目录）, 册s 为空。
    """
    源目录 = Path(源目录)
    if not 源目录.is_dir():
        raise FileNotFoundError(f'目录不存在: {源目录}')
    话目录s = 找话目录(源目录)
    if not 话目录s:
        raise ValueError(f'没有找到话目录（含图片的子目录）: {源目录}')

    册s分组 = 分组(话目录s, 单位, 卷界, 每卷话数)
    输出 = Path(输出目录) if 输出目录 else (
        源目录 if 格式 == 'pages' else 源目录.parent / (源目录.name + '_单行本'))

    册s = []
    for 册名, 本册话 in 册s分组:
        产物 = 导出册(册名, 本册话, 输出, 格式)
        if 产物:
            册s.append(产物)

    页数 = sum(len(列页(话)) for 话 in 话目录s)
    if 写索引 and 格式 != 'pages' and 单位 == '卷':
        写目录索引(话目录s, [len(本册) for _, 本册 in 册s分组], 输出)

    return {'格式': 格式, '单位': 单位, '输出目录': str(输出),
            '册s': 册s, '话数': len(话目录s), '页数': 页数}


def 写目录索引(话目录s: Sequence[Path], 各册话数: Sequence[int], 输出目录) -> Path:
    """生成 卷-话 对照表（只含结构信息, 不含任何站点/来源）。"""
    输出目录 = Path(输出目录)
    输出目录.mkdir(parents=True, exist_ok=True)
    行s = ['# 单行本卷话对照', '', '| 卷 | 收录话 | 页数 |', '|---|---|---|']
    起 = 0
    for 卷号, 话数 in enumerate(各册话数, start=1):
        本卷 = list(话目录s[起:起 + 话数])
        起 += 话数
        if not 本卷:
            continue
        首 = 话序(本卷[0].name)[1]
        末 = 话序(本卷[-1].name)[1]
        页 = sum(len(列页(话)) for 话 in 本卷)
        行s.append(f'| 第{卷号:02d}卷 | {首} ~ {末}（{len(本卷)} 话） | {页} |')
    行s += ['', f'共 {len(话目录s)} 话 / {len(各册话数)} 卷。']
    目标 = 输出目录 / '卷目录.md'
    目标.write_text('\n'.join(行s) + '\n', encoding='utf-8')
    return 目标
