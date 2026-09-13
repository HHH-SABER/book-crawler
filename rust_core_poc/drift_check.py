# -*- coding: utf-8 -*-
"""Rust 镜像一致性校验 (漂移检测)

同一批样本上对比两份实现:
  A) Rust 路径  : 正常 import, 内容质检器.质检 走 rust_core.pyd (GIL 释放)
  B) 纯 Python  : import-hook 模拟 rust_core 缺失, 回退纯 Python 实现
要求 得分/有效/原因/统计 七个字段逐项一致 —— 任何差异都视为镜像漂移。

用法:  python rust_core_poc/drift_check.py
"""
import builtins
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / '源码'))

# ---------- 样本: 真实解码章节 + 边界 ----------
from content_decoder import decode_data  # noqa: E402

_samples = []
raw = (ROOT / '测试样本' / 'ciyewk_1.book').read_text('utf-8')
real, _method = decode_data(raw)
_samples.append(('real_codepoint', real))
_samples += [
    ('empty', ''),
    ('blank', '   '),
    ('short', '这是很短。'),
    ('normal_filled', '第5章正常中文内容，标点齐全、长度充足，用于通过性校验。' * 8),
    ('garbage', '网a网b网c网d' * 5),
    ('punct_heavy', '，，，，！！！！————……' * 10),
]


def load_质检(block_rust: bool):
    """加载 内容质检器 模块; block_rust=True 时模拟 rust_core 缺失(纯 Python 路径)"""
    real_import = builtins.__import__
    if block_rust:
        def fake(name, *a, **k):
            if name == 'rust_core':
                raise ImportError('simulated missing rust_core')
            return real_import(name, *a, **k)
        builtins.__import__ = fake
    try:
        spec = importlib.util.spec_from_file_location(
            'qa_impl_py' if block_rust else 'qa_impl_rs', ROOT / '源码' / '内容质检器.py')
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod
    finally:
        builtins.__import__ = real_import


def dump(r):
    return (r.得分, r.有效, list(r.原因),
            {k: round(v, 6) if isinstance(v, float) else v for k, v in r.统计.items()})


def main():
    rs_mod = load_质检(block_rust=False)
    py_mod = load_质检(block_rust=True)
    assert rs_mod._RUST_质检可用, 'Rust 路径应生效 (缺少 rust_core.pyd?)'
    assert not py_mod._RUST_质检可用, '兜底模块应回退纯 Python'

    bad = 0
    for name, text in _samples:
        a = dump(rs_mod.质检器.质检(text))
        b = dump(py_mod.质检器.质检(text))
        ok = a == b
        if not ok:
            bad += 1
            print(f'[漂移] {name}\n  Rust   : {a}\n  Python : {b}')
        else:
            print(f'[一致] {name:<18} score={a[0]} eff={a[1]}')
    print('-' * 50)
    print(f'样本 {len(_samples)} 个, 漂移 {bad} 个 → {"PASS ✔ (镜像未漂移)" if bad == 0 else "FAIL ✘ (需同步 Rust 镜像)"}')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()