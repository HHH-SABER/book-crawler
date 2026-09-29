# -*- coding: utf-8 -*-
"""历史 TXT 离线重排工具 (2026-09-29): 分段修复 + 段首缩进, 不重抓即可受益。

## 为什么需要它

修复前的抓取链路存在多处"段落压扁"缺陷 (Base64 解密后 get_text 无 separator、
clean_content 删空行等, 详见 文档/内容清洗评估与改进方案-2026-09-29.md)，
历史 TXT 因此存在两类问题:
  - 整章/大段被压成无换行长文本 (分段信息在源头丢失);
  - 段落有换行但无缩进无空行 (仅排版缺失)。
本工具对**已抓好的文件**做离线重排: 按 `## ` 章节标题切块 → 压扁块句级重切 →
统一"段首两个全角空格 + 段间空行"排版 (与新版抓取的输出格式一致)。

## 用法

    python 脚本/重排历史TXT.py <文件或目录> [--备份目录 DIR] [--dry-run]
                              [--no-缩进] [--min N] [--max N] [--encoding auto]

  - 目录: 递归处理其中所有 *.txt (自动跳过备份目录自身)
  - --dry-run: 只统计不写盘 (先看段落数变化再决定)
  - 默认强制备份到 --备份目录 (默认: 数据/重排备份/文件名.bak-时间戳)

## 重切算法 (只对"压扁块"触发, 宁过拆勿粘连)

触发条件 (满足其一判定为压扁块):
  - 非空行长度中位数 > max (说明段落被压成长文本);
  - ≥90% 的非空行不含句末标点 (。！？…”』」)。

重切规则 (句级累进缓冲):
  - 终结符 (。！？…”』」!?) 连同后置引号归前句;
  - 断段: 缓冲 ≥min 且下一句以开引号/对话符起始 (对话起新段强信号);
          缓冲 ≥max (硬上限);
          缓冲 ≥min 且当前句以强终结符收尾 (。！？”)。
  - 防误切: 引号未配对 (开引号多于闭引号) 时禁止断段;
            开引号后未出现任何终结符前禁止断段。

## 可靠性

  - 原子写: tmp (带 pid) + os.replace (范式同 爬取历史._落盘);
  - 强制备份: shutil.copy2 → 备份目录 (文件名.bak-YYYYmmdd-HHMMSS);
  - 幂等: 已排版文件只做排版归一 (去旧缩进/统一空行), 不重复重切;
  - 纯函数 重排正文() 与 IO 分离, 便于单测 (测试/test_重排历史TXT.py)。
"""
import argparse
import os
import re
import shutil
import sys
import time
from pathlib import Path

# 句末终结符集合 (触发判定/断段判定用)
_终结符 = '。！？…”』」!?'
_强终结符 = '。！？”'
_开引号 = '“『「"\''
_闭引号 = '”』」"\''
# 句切正则: 非终结符串 + 紧随的终结符/闭引号串 (引号自然归前句, 不单独成句)
_句切RE = re.compile(r'[^。！？…”』」!?]+[。！？…”』」!?]*')


def _统计行(文本: str):
    """非空行列表 + (中位行长度, 无句末标点行占比)"""
    lines = [ln.strip() for ln in 文本.split('\n') if ln.strip()]
    if not lines:
        return lines, 0, 0.0
    lens = sorted(len(ln) for ln in lines)
    mid = lens[len(lens) // 2]
    无标点 = sum(1 for ln in lines if not any(c in _终结符 for c in ln))
    return lines, mid, 无标点 / len(lines)


def _is_压扁块(文本: str, min_len: int, max_len: int) -> bool:
    """触发判定: 中位行长超限 / 单行长文本 / 九成行无句末标点。

    单行 >min_len 也判定为压扁: 正常章节必有段落换行, 单行长文本
    基本是压扁产物; 重切本身有 min_len 断段保护, 切不出多段即原样
    归一 (幂等无害)。
    """
    lines, mid, 无标点占比 = _统计行(文本)
    if not lines:
        return False
    if mid > max_len or 无标点占比 >= 0.9:
        return True
    return len(lines) == 1 and mid > min_len


def _句列表(文本: str):
    """按终结符切句, 终结符连同紧随的闭引号归前句 (正则归并, 不单独成句)"""
    return [m.group(0).strip() for m in _句切RE.finditer(文本 or '')
            if m.group(0).strip()]


def _重切长文本(文本: str, min_len: int, max_len: int):
    """压扁块句级重切为段落列表 (防误切: 引号配对守卫)"""
    段落 = []
    缓冲 = ''
    开引号数 = 0
    句子 = _句列表(文本)
    for i, 句 in enumerate(句子):
        缓冲 += 句
        开引号数 += sum(1 for c in 句 if c in _开引号)
        开引号数 -= sum(1 for c in 句 if c in _闭引号)
        可断 = True
        强终结收尾 = any(c in _强终结符 for c in 缓冲[-4:])
        if 开引号数 > 0:          # 有未闭合引号 → 禁止断
            可断 = False
        elif not 强终结收尾:
            # 缓冲尾部不是强终结收尾 (逗号续句/闭引号刚开) → 仅当下一句是对话起始才可断
            可断 = (i + 1 < len(句子)
                    and 句子[i + 1][:1] in _开引号)
        if 缓冲 and len(缓冲) >= max_len:
            可断 = True            # 硬上限兜底
        # 对话起新段 (强规则, 无视 min_len): 中文排版规范里对话必然独立成段 ——
        # 当前缓冲以强终结收尾、无未闭合引号、下一句以开引号开头 → 立即断段
        对话强断 = (开引号数 == 0 and 强终结收尾
                    and i + 1 < len(句子) and 句子[i + 1][:1] in _开引号)
        if 可断 and (对话强断 or len(缓冲) >= min_len):
            段落.append(缓冲)
            缓冲 = ''
            开引号数 = 0
        elif 可断 and i == len(句子) - 1:
            段落.append(缓冲)
            缓冲 = ''
    if 缓冲:
        段落.append(缓冲)
    return 段落


def 重排正文(正文: str, 缩进: bool = True, min_len: int = 50,
             max_len: int = 200) -> str:
    """单章正文重排 (纯函数): 压扁块重切 + 统一段落排版。

    排版规范与新版抓取输出一致: 段首两个全角空格 + 段间空行;
    缩进=False 时只做分段与空行归一。
    """
    正文 = (正文 or '').strip()
    if not 正文:
        return ''
    if _is_压扁块(正文, min_len, max_len):
        # 重切前先剥旧缩进/空白干扰
        压扁文本 = re.sub(r'[\u3000 \t]+', '', 正文)
        压扁文本 = re.sub(r'\n+', '', 压扁文本)      # 压扁块当作单流处理
        段落 = _重切长文本(压扁文本, min_len, max_len)
    else:
        段落 = [ln.strip() for ln in 正文.split('\n') if ln.strip()]
        段落 = [re.sub(r'^[\u3000]+', '', p) for p in 段落]   # 剥旧缩进
    if 缩进:
        段落 = ['\u3000\u3000' + p for p in 段落]
    return '\n\n'.join(段落)


def 重排文件(路径: Path, 备份目录: Path, 缩进: bool = True,
             min_len: int = 50, max_len: int = 200, 编码: str = 'auto',
             dry_run: bool = False):
    """重排单个 TXT 文件。返回 (状态, 原段数, 新段数, 说明)。

    状态: '重切' / '归一' / '跳过' / '失败'
    """
    # 读 (编码 auto: utf-8 严格 → gbk 回退)
    原文 = None
    for enc in (('utf-8', 'gbk') if 编码 == 'auto' else (编码,)):
        try:
            原文 = 路径.read_text(encoding=enc)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
        except OSError as e:
            return ('失败', 0, 0, f'读取失败 {type(e).__name__}: {e}')
    if 原文 is None:
        return ('失败', 0, 0, 'utf-8/gbk 均解码失败')

    # 按 ## 章节标题切块 (无标题文件整本一块)
    blocks = re.split(r'(?m)^(?=## )', 原文)
    原段数 = sum(len([ln for ln in b.split('\n') if ln.strip()]) for b in blocks)
    new_blocks = []
    重切数 = 0
    for b in blocks:
        if not b.strip():
            continue
        m = re.match(r'(?m)^(## .*)$', b)
        if m:
            标题行 = m.group(1)
            body = b[m.end():].strip()
        else:
            标题行 = None
            body = b.strip()
        if body:
            before = body
            body = 重排正文(body, 缩进=缩进, min_len=min_len, max_len=max_len)
            if _is_压扁块(before, min_len, max_len):
                重切数 += 1
        new_blocks.append((标题行, body))

    新段数 = sum(len([ln for ln in body.split('\n') if ln.strip()])
                 for _, body in new_blocks)
    if dry_run:
        状态 = '重切' if 重切数 else '归一'
        return (状态, 原段数, 新段数, f'{重切数} 块重切 (dry-run 未写盘)')

    # 组装 (对齐抓取产物格式: 每章块 = '## 标题\n\n正文段落…\n\n', 块间不额外空行)
    parts = []
    for 标题行, body in new_blocks:
        if 标题行:
            parts.append(标题行 + '\n\n' + body)
        else:
            parts.append(body)
    新文 = ''.join(p + '\n\n' for p in parts)

    if 新文 == 原文:
        return ('跳过', 原段数, 新段数, '内容已是目标格式')

    # 备份 (强制)
    try:
        备份目录.mkdir(parents=True, exist_ok=True)
        bak = 备份目录 / f'{路径.name}.bak-{time.strftime("%Y%m%d-%H%M%S")}'
        shutil.copy2(路径, bak)
    except OSError as e:
        return ('失败', 原段数, 新段数, f'备份失败 {type(e).__name__}: {e}')

    # 原子写 (范式同 爬取历史._落盘)
    try:
        目标 = 路径.resolve()
        tmp = 目标.with_name(目标.name + f'.tmp.{os.getpid()}')
        tmp.write_text(新文, encoding='utf-8')
        os.replace(tmp, 目标)
    except OSError as e:
        return ('失败', 原段数, 新段数, f'写入失败 {type(e).__name__}: {e}')
    状态 = '重切' if 重切数 else '归一'
    return (状态, 原段数, 新段数, f'{重切数} 块重切, 备份: {bak.name}')


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='历史 TXT 离线重排: 分段修复 + 段首缩进 (段落间空行)')
    ap.add_argument('目标', help='TXT 文件或目录 (目录=递归处理全部 *.txt)')
    ap.add_argument('--备份目录', default=None,
                    help='备份目录 (默认: 数据/重排备份)')
    ap.add_argument('--dry-run', action='store_true', help='只统计不写盘')
    ap.add_argument('--no-缩进', action='store_true', help='不加段首缩进')
    ap.add_argument('--min', type=int, default=50, help='重切段最小字数 (默认50)')
    ap.add_argument('--max', type=int, default=200, help='重切段硬上限 (默认200)')
    ap.add_argument('--encoding', default='auto', choices=['auto', 'utf-8', 'gbk'],
                    help='文件编码 (默认 auto: utf-8 优先, gbk 回退)')
    args = ap.parse_args(argv)

    目标 = Path(args.目标)
    if not 目标.exists():
        print(f'❌ 路径不存在: {目标}')
        return 2

    # 收集文件 (目录递归 *.txt, 跳过备份目录与临时文件)
    备份目录 = Path(args.备份目录) if args.备份目录 else Path('数据') / '重排备份'
    备份目录 = 备份目录.resolve()
    if 目标.is_file():
        files = [目标]
    else:
        files = [p for p in 目标.rglob('*.txt')
                 if 备份目录 not in p.resolve().parents
                 and not p.name.endswith('.tmp')]

    print(f'共 {len(files)} 个文件, 模式: {"dry-run" if args.dry_run else "写入"}'
          f' (缩进={"关" if args.no_缩进 else "开"}, 备份: {备份目录})')
    统计 = {'重切': 0, '归一': 0, '跳过': 0, '失败': 0}
    for p in files:
        状态, 原, 新, 说明 = 重排文件(
            p, 备份目录, 缩进=not args.no_缩进,
            min_len=args.min, max_len=args.max,
            编码=args.encoding, dry_run=args.dry_run)
        统计[状态] += 1
        print(f'  [{状态}] {p.name}: 段落 {原} → {新} ({说明})')
    print(f'汇总: 重切 {统计["重切"]} / 归一 {统计["归一"]} / '
          f'跳过 {统计["跳过"]} / 失败 {统计["失败"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
