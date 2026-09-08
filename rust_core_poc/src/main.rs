// -*- coding: utf-8 -*-
// Rust 移植: content_decoder.parse_codepoint_stream
// =================================================
// 对 Python 实现逐 token 复原 (含 P1-7 / P2-7 回归细节), 零第三方依赖。
//
// 用法:
//   poc_ab <input_file> <replace_file> <out_file> <iters>
//     input_file   : content 字符串的 UTF-8 字节 (=输入码点流)
//     replace_file : 每行 "控制字符码点,hex码"  如 "7,66f0" (码点≤0x1f 才生效)
//     out_file     : 解码结果写入(UTF-8)
//     iters        : 计时循环次数
//   标准输出打印 RUST_DECODE_MS=<耗时毫秒>

use std::collections::HashMap;
use std::env;
use std::fs;
use std::process;
use std::time::Instant;

fn is_hex(c: char) -> bool {
    c.is_ascii_hexdigit()
}

// 构造 mapping: 控制字符 -> 还原汉字 (与 Python replace_map 处理一致)
fn build_mapping(text: &str) -> HashMap<char, char> {
    let mut m = HashMap::new();
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let (ctrl_s, code_s) = match line.split_once(',') {
            Some(p) => p,
            None => continue,
        };
        let ctrl_s = ctrl_s.trim();
        let code_s = code_s.trim();
        let ctrl: u32 = match ctrl_s.parse() {
            Ok(v) => v,
            Err(_) => continue,
        };
        // 仅 1 个字符且 code<32 的控制字符才作为压缩占位符
        let ok_ctrl = ctrl < 32;
        // hex 码需为 2..=6 位十六进制
        let ok_code = (2..=6).contains(&code_s.len())
            && code_s.chars().all(|c| is_hex(c));
        if ok_ctrl && ok_code {
            if let Some(c) = char::from_u32(ctrl) {
                if let Some(v) = u32::from_str_radix(code_s, 16)
                    .ok()
                    .and_then(char::from_u32)
                {
                    m.insert(c, v);
                }
            }
        }
    }
    m
}

// 4 位十六进制字符串判断 (用于 pending marker 分支)
fn is_hex4(s: &str) -> bool {
    s.len() == 4 && s.chars().all(|c| is_hex(c))
}

fn char_vec_of(s: &str) -> Vec<char> {
    s.chars().collect()
}

// 高精度计时: 喂给 Vec<char> 派生出的 &[char]
fn parse_codepoint_stream(content_chars: &[char], mapping: &HashMap<char, char>) -> String {
    let n = content_chars.len();
    let mut out = String::with_capacity(n);
    let mut i = 0usize;
    let mut pending_marker = false;

    while i < n {
        let c = content_chars[i];

        // (a) x + 4 位十六进制  (=Python token `x[0-9a-fA-F]{4}`)
        if c == 'x' && i + 4 < n {
            let mut ok = true;
            for k in 1..=4 {
                if !is_hex(content_chars[i + k]) {
                    ok = false;
                    break;
                }
            }
            if ok {
                let hex: String = content_chars[i + 1..i + 5].iter().collect();
                i += 5;
                if pending_marker && is_hex4(&hex) {
                    pending_marker = false;
                    if let Some(v) = u32::from_str_radix(&hex, 16)
                        .ok()
                        .and_then(char::from_u32)
                    {
                        out.push(v);
                    } else {
                        out.push_str(&hex);
                    }
                } else {
                    pending_marker = false;
                    // len==5 且 t[0]=='x': 解码码点, 失败回退原 token
                    if let Some(v) = u32::from_str_radix(&hex, 16)
                        .ok()
                        .and_then(char::from_u32)
                    {
                        out.push(v);
                    } else {
                        out.push_str("x");
                        out.push_str(&hex);
                    }
                }
                continue;
            }
        }

        // (b) 4 位十六进制 (=Python token `[0-9a-fA-F]{4}`)
        if i + 3 < n {
            let mut ok = true;
            for k in 0..4 {
                if !is_hex(content_chars[i + k]) {
                    ok = false;
                    break;
                }
            }
            if ok {
                let hex: String = content_chars[i..i + 4].iter().collect();
                i += 4;
                if pending_marker && is_hex4(&hex) {
                    pending_marker = false;
                    if let Some(v) = u32::from_str_radix(&hex, 16)
                        .ok()
                        .and_then(char::from_u32)
                    {
                        out.push(v);
                    } else {
                        out.push_str(&hex);
                    }
                } else {
                    pending_marker = false;
                    // 4 位 hex token 不会是单控制字符, 也不匹配 x 前缀/换行/分号,
                    // 直接原样输出 (与 Python 落入 else 一致)
                    out.push_str(&hex);
                }
                continue;
            }
        }

        // (c) 单个字符
        i += 1;
        pending_marker = false;
        if let Some(&rep) = mapping.get(&c) {
            out.push(rep);
        } else if c == '\x01' || c == '\x02' || c == '\x03' {
            pending_marker = true;
        } else if c == '\x04' {
            out.push('\n');
        } else if c == ';' {
            // 孤立分号是实体残留, 丢弃
        } else if c < ' ' {
            // 未映射控制字符: 无还原依据, 丢弃
        } else {
            out.push(c);
        }
    }
    out
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() != 5 {
        eprintln!("usage: poc_ab <input_file> <replace_file> <out_file> <iters>");
        process::exit(2);
    }
    let input_path = &args[1];
    let replace_path = &args[2];
    let out_path = &args[3];
    let iters: usize = args[4].parse().unwrap_or(1);

    let content_bytes = fs::read(input_path).expect("read input");
    let content_str = String::from_utf8(content_bytes).expect("input must be valid UTF-8");
    let replace_text = fs::read_to_string(replace_path).expect("read replace");
    let mapping = build_mapping(&replace_text);
    let content_chars = char_vec_of(&content_str);

    // 先跑一次得到正确输出
    let decoded = parse_codepoint_stream(&content_chars, &mapping);
    fs::write(out_path, decoded.as_bytes()).expect("write out");

    // 计时 iters 次 (不重建 mapping/tokens, 仅核心循环)
    let t0 = Instant::now();
    let mut acc = 0usize;
    for _ in 0..iters {
        let s = parse_codepoint_stream(&content_chars, &mapping);
        acc += s.len();
    }
    let ms = t0.elapsed().as_secs_f64() * 1000.0;
    println!("RUST_DECODE_MS={:.3}", ms);
    println!("RUST_CHARS={}", acc);
}