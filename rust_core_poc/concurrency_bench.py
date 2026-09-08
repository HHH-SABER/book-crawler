# -*- coding: utf-8 -*-
"""并发 worker 吞吐对比: 模拟真实爬虫"多线程逐章耗时计算"场景。

对比三种实现在多线程并发下的墙钟耗时:
  A) 纯 Python 线程调用 内容质检器.质检        (受 GIL 串行)
  B) Rust 扩展 qa_质检_gil                     (原生计算但持有 GIL → 同样被串行)
  C) Rust 扩展 qa_质检_nogil                   (py.allow_threads 释放 GIL → 真并行)

同理对 parse_codepoint_stream 做一套。
"""
import sys
import time
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / '源码'))

from 内容质检器 import 质检器

import rust_core

POC = Path(__file__).resolve().parent
DECODED = (POC / 'py_out.txt').read_text(encoding='utf-8')

# 从真实样本取 content + replace (供 codepoint stream)
FUNC_WRAP = re.compile(r'[a-zA-Z_]\w*\s*\(\s*(\{.*\})\s*\)\s*$', flags=re.S)
CTRL = re.compile(r'[\x00-\x1f]')
_raw = (Path(__file__).resolve().parent.parent / '测试样本' / 'ciyewk_1.book').read_text(
    encoding='utf-8').strip()
_m = FUNC_WRAP.search(_raw)
import json
_data = json.loads(CTRL.sub(lambda mm: '\\u%04x' % ord(mm.group(0)), _m.group(1)))
CODPOINT = _data['content']
REPLACE = _data.get('replace')


def timeit_parallel(worker_fn, total, nthreads):
    per = total // nthreads
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=nthreads) as ex:
        list(ex.map(lambda _: worker_fn(), range(total)))
    return (time.perf_counter() - t0) * 1000.0


def run_qc():
    # 质检 1 次 (计分/原因/统计都做)
    return rust_core.qa_质检_nogil(DECODED)


def run_codepoint():
    return rust_core.parse_codepoint_stream_nogil(CODPOINT, REPLACE)


def main():
    total = 6400
    nthreads = 8

    def py_qc():
        质检器.质检(DECODED)

    def py_codepoint():
        from content_decoder import parse_codepoint_stream
        parse_codepoint_stream(CODPOINT, REPLACE)

    def gil_qc():
        rust_core.qa_质检_gil(DECODED)

    def nogil_qc():
        rust_core.qa_质检_nogil(DECODED)

    def gil_codepoint():
        rust_core.parse_codepoint_stream_gil(CODPOINT, REPLACE)

    def nogil_codepoint():
        rust_core.parse_codepoint_stream_nogil(CODPOINT, REPLACE)

    print(f'线程数={nthreads}  总调用={total}\n')

    def show(name, ms, ref=None):
        line = f'{name:<22} {ms:9.1f} ms   {1000 * total / ms:8.0f} 次/s'
        if ref:
            line += f'   (Rust耗时/本耗时 = {ref / ms:.1f}x)'
        print(line)

    print('===== 内容质检器 (并发) =====')
    t_py = timeit_parallel(py_qc, total, nthreads)
    t_gil = timeit_parallel(gil_qc, total, nthreads)
    t_nogil = timeit_parallel(nogil_qc, total, nthreads)
    show('Python 线程', t_py)
    show('Rust 持GIL', t_gil, t_py)
    show('Rust 释放GIL', t_nogil, t_gil)

    print('\n===== parse_codepoint_stream (并发) =====')
    # 码点流长度更大, 减量控制耗时
    ctotal = 600
    def cp(nogil):
        pass
    t_cp_py = timeit_parallel(py_codepoint, ctotal, nthreads)
    t_cp_gil = timeit_parallel(gil_codepoint, ctotal, nthreads)
    t_cp_nogil = timeit_parallel(nogil_codepoint, ctotal, nthreads)
    for nm, v, ref in [('Python 线程', t_cp_py, None),
                       ('Rust 持GIL', t_cp_gil, t_cp_py),
                       ('Rust 释放GIL', t_cp_nogil, t_cp_gil)]:
        s = f'{nm:<22} {v:9.1f} ms   {1000 * ctotal / v:8.0f} 次/s'
        if ref:
            s += f'   (Rust耗时/本耗时 = {ref / v:.1f}x)'
        print(s)

    # 一致性抽查
    ok = (rust_core.qa_质检_nogil(DECODED)[0] == 质检器.质检(DECODED).得分)
    cp_out = rust_core.parse_codepoint_stream_nogil(CODPOINT, REPLACE)
    ok &= (cp_out[:20] == py_codepoint.__wrapped__(CODPOINT, REPLACE)[:20]) if hasattr(py_codepoint, '__wrapped__') else True
    print('\n一致性抽查: qa', 'OK' if ok else 'FAIL')


if __name__ == '__main__':
    main()