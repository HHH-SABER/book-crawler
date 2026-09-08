# -*- coding: utf-8 -*-
"""parse_codepoint_stream Rust 移植 A/B 对比驱动
=================================================

用法 (两种模式):
  1) 仅 Python 基线(本机暂无 Rust 链接器时):  python run_bench.py --python-only
  2) 完整 A/B (需先构建出 poc_ab 可执行文件):
         cargo build --release            # 在有 MSVC/MinGW 链接器的环境
         python run_bench.py --ab <poc_ab路径>
  两种模式都会先生成输入文件 (input_content.bin / replace.txt) 供 Rust 使用。

依赖:  content_decoder.py 的 parse_codepoint_stream (作为被移植的基准实现)。
样本:  测试样本/ciyewk_1.book (真实 .book 码点流, 含 \x01/\x02 引导裸码点)。
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / '测试样本'
SRC = ROOT / '源码'
sys.path.insert(0, str(SRC))

POC = Path(__file__).resolve().parent
INPUT_BIN = POC / 'input_content.bin'
REPLACE_TXT = POC / 'replace.txt'
PY_OUT = POC / 'py_out.txt'
RS_OUT = POC / 'rs_out.txt'

ITERS = 300

_DATA_EXT = r'(?:xs|book|data|txt|json)'
_FUNC_WRAP = re.compile(
    r'[a-zA-Z_]\w*\s*\(\s*(\{.*\})\s*\)\s*$', flags=re.S)
_CTRL = re.compile(r'[\x00-\x1f]')


def _json_safe(text):
    """JSON 字符串里的裸控制字符转 \\uXXXX 转义 (json.loads 拒绝裸控制字符)。"""
    return _CTRL.sub(lambda m: '\\u%04x' % ord(m.group(0)), text)


def prepare():
    """从 ciyewk_1.book 提取 content + replace, 写出供 Rust 使用的输入/替换文件。"""
    raw = (SAMPLES / 'ciyewk_1.book').read_text(encoding='utf-8').strip()
    m = _FUNC_WRAP.search(raw)
    assert m, '样本应为 _txt_call({...}) 包装'
    data = json.loads(_json_safe(m.group(1)))
    content = data.get('content', '')
    replace = data.get('replace') or {}
    assert content, '未提取到 content'

    INPUT_BIN.write_bytes(content.encode('utf-8'))

    lines = []
    for code, ctrl in replace.items():
        if (isinstance(ctrl, str) and len(ctrl) == 1 and ord(ctrl) < 32
                and re.fullmatch(r'[0-9a-fA-F]{2,6}', code)):
            lines.append(f'{ord(ctrl)},{code}')
    REPLACE_TXT.write_text('\n'.join(lines) + '\n', encoding='utf-8')

    return content, replace


def run_python(content, replace):
    from content_decoder import parse_codepoint_stream
    # 预热
    out = parse_codepoint_stream(content, replace)
    PY_OUT.write_text(out, encoding='utf-8')
    t0 = time.perf_counter()
    for _ in range(ITERS):
        parse_codepoint_stream(content, replace)
    dt = (time.perf_counter() - t0) * 1000.0
    return out, dt


def run_rust(exe: Path):
    cp = subprocess.run(
        [str(exe), str(INPUT_BIN), str(REPLACE_TXT), str(RS_OUT), str(ITERS)],
        capture_output=True, text=True)
    ms = None
    for line in cp.stdout.splitlines():
        if line.startswith('RUST_DECODE_MS='):
            ms = float(line.split('=', 1)[1])
    if cp.returncode != 0:
        raise RuntimeError(f'rust 运行失败 rc={cp.returncode}:\n{cp.stderr}')
    return ms, (RS_OUT.read_text(encoding='utf-8') if ms is not None else None)


def report(tag, ms):
    print(f'{tag:<10} 耗时 {ms:8.3f} ms / {ITERS} 次  '
          f'({ms / ITERS:.3f} ms/次, {1000 * ITERS / ms:.0f} 次/s)')


def main():
    python_only = '--python-only' in sys.argv
    ab = False
    exe = None
    if '--ab' in sys.argv:
        ab = True
        i = sys.argv.index('--ab')
        exe = Path(sys.argv[i + 1]) if i + 1 < len(sys.argv) else POC / 'target' / 'release' / 'poc_ab.exe'
        if not exe.exists():
            print(f'[warn] 未找到 rust 可执行文件: {exe}')
            ab = False

    print(f'样本: 测试样本/ciyewk_1.book   ITERS={ITERS}')
    content, replace = prepare()
    print(f'提取到 content 长度 {len(content)}, replace 条目 {len(replace)}')
    print(f'输入已写出: {INPUT_BIN.name}, {REPLACE_TXT.name}')

    py_out, py_ms = run_python(content, replace)
    report('Python', py_ms)

    if ab:
        rs_ms, rs_out = run_rust(exe)
        report('Rust', rs_ms)
        same = (rs_out == py_out)
        print(f'输出一致性: {"一致 ✔" if same else "不一致 ✘"}')
        if same:
            print(f'加速比: Python/Rust ≈ {py_ms / rs_ms:.1f}x')
        else:
            # 定位首个差异
            for k in range(min(len(py_out), len(rs_out))):
                if py_out[k] != rs_out[k]:
                    print(f'首个差异 @{k}: python={py_out[k]!r} rust={rs_out[k]!r}')
                    break
            else:
                print(f'长度不同: python={len(py_out)} rust={len(rs_out)}')
    else:
        print('(未提供 Rust 二进制, 跳过 A/B; '
              '有链接器后执行: cargo build --release 加上 --ab 重跑)')
    print(f'Python 输出: {PY_OUT.name}\nRust 输出: {RS_OUT.name}')


if __name__ == '__main__':
    main()