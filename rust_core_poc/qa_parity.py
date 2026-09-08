# -*- coding: utf-8 -*-
"""在不编译的情况下验证 Rust qa_ab 算法的 parity:
纯 Python 逐行镜像 rust_core_poc/src/bin/qa_ab.rs, 与真实 内容质检器.质检 对比。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / '源码'))
from 内容质检器 import 质检器

PUNCT = set('，。！？；：、…—·,!?;:~()（）[]【】《》.-“”‘’"' "'")


def is_cjk(c):
    v = ord(c)
    return (0x4e00 <= v <= 0x9fff) or (0x3400 <= v <= 0x4dbf)


def is_乱码_char(c):
    v = ord(c)
    return v == 0xfffd or (0xe000 <= v <= 0xf8ff) or (0xfff0 <= v <= 0xffff)


def is_标点(c):
    return c in PUNCT


def 乱码串总长(text):
    n = len(text)
    total = 0
    run = 0
    for i in range(n + 1):
        c = text[i] if i < n else '\n'
        allowed = is_cjk(c) or (c.isascii() and c.isalnum()) or c.isspace() or is_标点(c)
        if not allowed:
            run += 1
        else:
            if run >= 4:
                total += run
            run = 0
    return total


def qa_stat(text):
    总 = len(text)
    if 总 == 0:
        return dict(净=0, 行=0, 中=0.0, 乱=1.0, 重=1.0, 标=0.0)
    cjk = 乱c = 标 = 0
    for c in text:
        if is_cjk(c):
            cjk += 1
        if is_乱码_char(c):
            乱c += 1
        if is_标点(c):
            标 += 1
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    行 = len(lines)
    去 = len(set(lines))
    乱串 = 乱码串总长(text)
    return dict(净=总, 行=行, 中=cjk / 总, 乱=(乱c + 乱串) / 总,
                重=1.0 - 去 / 行 if 行 else 1.0, 标=标 / 总)


W25 = 25.0
W乱 = 20.0
W重 = 15.0
W标 = 15.0


def r1(x):
    m = 10.0
    return round(x * m) / m


def s_len(s):
    if s['净'] >= 500:
        return W25
    if s['净'] >= 200:
        return r1(W25 * (s['净'] - 200) / 300.0)
    return 0.0


def s_zh(s):
    if s['中'] >= 0.60:
        return W25
    if s['中'] >= 0.30:
        return r1(W25 * (s['中'] - 0.30) / 0.30)
    return 0.0


def s_luan(s):
    if s['乱'] <= 0.05:
        return W乱
    if s['乱'] <= 0.30:
        return r1(W乱 * (0.30 - s['乱']) / 0.25)
    return 0.0


def s_ch(s):
    return W重 if s['重'] <= 0.40 else 0.0


def s_bd(s):
    if 0.02 <= s['标'] <= 0.25:
        return W标
    if 0.005 <= s['标'] < 0.02:
        return r1(W标 * 0.5)
    if 0.25 < s['标'] <= 0.40:
        return r1(W标 * 0.5)
    return 0.0


def rust_qa(text):
    if not text or not text.strip():
        return (0.0, False, ['正文为空'])
    s = qa_stat(text)
    得分 = r1(s_len(s) + s_zh(s) + s_luan(s) + s_ch(s) + s_bd(s))
    rea = []
    if s['乱'] > 0.30:
        rea.append('乱码率%.0f%%>30%%' % (s['乱'] * 100))
    if s['中'] < 0.30:
        rea.append('中文占比%.0f%%<30%%' % (s['中'] * 100))
    if s_len(s) == 0 and not rea:
        rea.append('长度不足(%d字)' % s['净'])
    if s_zh(s) == 0 and 0.30 <= s['中'] and not rea:
        rea.append('中文占比%.0f%%' % (s['中'] * 100))
    if s_luan(s) == 0 and s['乱'] <= 0.30:
        rea.append('乱码率%.0f%%' % (s['乱'] * 100))
    if s_ch(s) == 0:
        rea.append('重复率%.0f%%' % (s['重'] * 100))
    if s_bd(s) == 0:
        rea.append('标点密度%.1f%%' % (s['标'] * 100))
    有效 = 得分 >= 60.0 and not rea
    return (得分, 有效, rea)


def main():
    samples = [
        Path(__file__).resolve().parent / 'py_out.txt',
    ]
    txts = [p.read_text('utf-8') if hasattr(p, 'read_text') else p for p in samples]
    txts += [
        '这是一段完全正常的中文内容，没有任何噪声。',
        '', '   ', '网a网b网c网d', '第%d章' % 123,
        '正常' * 50, '某' * 3,
    ]
    ok = True
    for i, t in enumerate(txts):
        py = 质检器.质检(t)
        pyk = (py.得分, py.有效, list(py.原因))
        rs = rust_qa(t)
        same = (abs(pyk[0] - rs[0]) < 1e-9) and pyk[1] == rs[1] and pyk[2] == rs[2]
        if not same:
            ok = False
            print(f'[样本{i}] 不一致\n  python={pyk}\n  rust ={rs}')
        else:
            print(f'[样本{i}] 一致 score={rs[0]} eff={rs[1]} reasons={rs[2]}')
    print('PARITY:', 'PASS' if ok else 'FAIL')


if __name__ == '__main__':
    main()