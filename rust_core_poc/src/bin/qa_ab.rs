// -*- coding: utf-8 -*-
// Rust 移植: 内容质检器.py 的五维评分 (无依赖, 纯标准库)
// =================================================
// 逐项复刻 Python 的 _统计 + 五个 _评分 + 硬伤/原因/有效 判定 (含 round 到 1 位)。
//
// 用法:
//   qa_ab <input_file> <iters>
//     input_file : 章节正文文本 (UTF-8)
//     iters      : 计时循环次数
//   标准输出打印一行结果用于 parity 比对:
//     SCORE=<1位> EFFECTIVE=<0/1> REASONS=<"; "拼接> STATS=<净字符数,中文占比,乱码率,重复率,标点密度>
//   并打印 QD_MS=<耗时> 供基准。

use std::collections::HashSet;
use std::env;
use std::fs;
use std::process;
use std::time::Instant;

// ---- 常量 (与内容质检器.py 顶部保持一致) ----
const W_长度: f64 = 25.0;
const W_中文: f64 = 25.0;
const W_乱码: f64 = 20.0;
const W_重复: f64 = 15.0;
const W_标点: f64 = 15.0;
const 及格分: f64 = 60.0;
const 硬伤乱码: f64 = 0.30;
const 硬伤中文: f64 = 0.30;
const 阈值长: usize = 500;
const 阈值短长: usize = 200;
const 阈值中文: f64 = 0.60;
const 阈值乱码: f64 = 0.05;
const 阈值重复: f64 = 0.40;
const 标点下限: f64 = 0.02;
const 标点上限: f64 = 0.25;

fn is_cjk(c: char) -> bool {
    matches!(c as u32, 0x4e00..=0x9fff | 0x3400..=0x4dbf)
}
fn is_乱码_char(c: char) -> bool {
    matches!(c as u32, 0xfffd | 0xe000..=0xf8ff | 0xfff0..=0xffff)
}
fn is_标点(c: char) -> bool {
    matches!(c,
        '，'|'。'|'！'|'？'|'；'|'：'|'、'|'…'|'—'|'·'|','|'!'|'?'|';'|':'|'~'|'.'|'-'
        |'('|')'|'（'|'）'|'['|']'|'【'|'】'|'《'|'》'|'\u{201c}'|'\u{201d}'|'\u{2018}'|'\u{2019}'|'"'|'\'')
}

// 连续异常串: 4 个以上非常见字符 (非中文/拉丁数字空白/标点) 视为乱码噪声, 返回各串总长
fn 乱码串总长(text: &str) -> usize {
    let chars: Vec<char> = text.chars().collect();
    let mut total = 0usize;
    let mut run = 0usize;
    let n = chars.len();
    for i in 0..=n {
        let c = if i < n { chars[i] } else { '\n' }; // 边界用普通字符收尾
        let allowed = is_cjk(c)
            || c.is_ascii_alphanumeric()
            || c.is_whitespace()
            || is_标点(c);
        if !allowed {
            run += 1;
        } else {
            if run >= 4 {
                total += run;
            }
            run = 0;
        }
    }
    total
}

#[derive(Clone, Copy)]
struct 统计 {
    净字符数: usize,
    行数: usize,
    中文占比: f64,
    乱码率: f64,
    重复率: f64,
    标点密度: f64,
}

fn 统计(text: &str) -> 统计 {
    let 总 = text.chars().count();
    if 总 == 0 {
        return 统计 { 净字符数: 0, 行数: 0, 中文占比: 0.0, 乱码率: 1.0, 重复率: 1.0, 标点密度: 0.0 };
    }
    let mut cjk = 0usize;
    let mut 乱码c = 0usize;
    let mut 标点 = 0usize;
    for c in text.chars() {
        if is_cjk(c) { cjk += 1; }
        if is_乱码_char(c) { 乱码c += 1; }
        if is_标点(c) { 标点 += 1; }
    }
    let nl = text.matches('\n').count();
    let lines: Vec<&str> = text.lines().map(|l| l.trim()).filter(|l| !l.is_empty()).collect();
    let 行数 = lines.len();
    let mut seen = HashSet::new();
    for l in &lines { seen.insert(*l); }
    let 去重 = seen.len();
    let 乱码串 = 乱码串总长(text);

    统计 {
        净字符数: 总,
        行数,
        中文占比: cjk as f64 / 总 as f64,
        乱码率: (乱码c + 乱码串) as f64 / 总 as f64,
        重复率: if 行数 > 0 { 1.0 - 去重 as f64 / 行数 as f64 } else { 1.0 },
        标点密度: 标点 as f64 / 总 as f64,
    }
}

fn 取round(x: f64, d: i32) -> f64 {
    let m = 10f64.powi(d);
    (x * m).round() / m
}

fn 评分长度(s: &统计) -> f64 {
    if s.净字符数 >= 阈值长 { W_长度 }
    else if s.净字符数 >= 阈值短长 {
        取round(W_长度 * (s.净字符数 as f64 - 阈值短长 as f64) / (阈值长 as f64 - 阈值短长 as f64), 1)
    } else { 0.0 }
}
fn 评分中文(s: &统计) -> f64 {
    if s.中文占比 >= 阈值中文 { W_中文 }
    else if s.中文占比 >= 硬伤中文 {
        取round(W_中文 * (s.中文占比 - 硬伤中文) / (阈值中文 - 硬伤中文), 1)
    } else { 0.0 }
}
fn 评分乱码(s: &统计) -> f64 {
    if s.乱码率 <= 阈值乱码 { W_乱码 }
    else if s.乱码率 <= 硬伤乱码 {
        取round(W_乱码 * (硬伤乱码 - s.乱码率) / (硬伤乱码 - 阈值乱码), 1)
    } else { 0.0 }
}
fn 评分重复(s: &统计) -> f64 {
    if s.重复率 <= 阈值重复 { W_重复 } else { 0.0 }
}
fn 评分标点(s: &统计) -> f64 {
    if 标点下限 <= s.标点密度 && s.标点密度 <= 标点上限 { W_标点 }
    else if 0.005 <= s.标点密度 && s.标点密度 < 标点下限 { 取round(W_标点 * 0.5, 1) }
    else if 标点上限 < s.标点密度 && s.标点密度 <= 0.40 { 取round(W_标点 * 0.5, 1) }
    else { 0.0 }
}

fn fmt0(x: f64) -> String { format!("{:.0}", x * 100.0) }
fn fmt1(x: f64) -> String { format!("{:.1}", x * 100.0) }

// 完整质检, 返回 (得分, 有效, 原因列表)
fn 质检(text: &str) -> (f64, bool, Vec<String>) {
    if text.is_empty() || text.trim().is_empty() {
        return (0.0, false, vec![String::from("正文为空")]);
    }
    let s = 统计(text);
    let 得分 = 取round(评分长度(&s) + 评分中文(&s) + 评分乱码(&s) + 评分重复(&s) + 评分标点(&s), 1);

    let mut 原因: Vec<String> = Vec::new();
    if s.乱码率 > 硬伤乱码 { 原因.push(format!("乱码率{:.0}%>{:.0}%", s.乱码率 * 100.0, 硬伤乱码 * 100.0)); }
    if s.中文占比 < 硬伤中文 { 原因.push(format!("中文占比{:.0}%<{:.0}%", s.中文占比 * 100.0, 硬伤中文 * 100.0)); }

    if 评分长度(&s) == 0.0 && 原因.is_empty() { 原因.push(format!("长度不足({}字)", s.净字符数)); }
    if 评分中文(&s) == 0.0 && 硬伤中文 <= s.中文占比 && 原因.is_empty() { 原因.push(format!("中文占比{:.0}%", s.中文占比 * 100.0)); }
    if 评分乱码(&s) == 0.0 && s.乱码率 <= 硬伤乱码 { 原因.push(format!("乱码率{:.0}%", s.乱码率 * 100.0)); }
    if 评分重复(&s) == 0.0 { 原因.push(format!("重复率{:.0}%", s.重复率 * 100.0)); }
    if 评分标点(&s) == 0.0 { 原因.push(format!("标点密度{:.1}%", s.标点密度 * 100.0)); }

    let 有效 = 得分 >= 及格分 && 原因.is_empty();
    (得分, 有效, 原因)
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() != 3 {
        eprintln!("usage: qa_ab <input_file> <iters>");
        process::exit(2);
    }
    let text = fs::read_to_string(&args[1]).expect("read input");
    let iters: usize = args[2].parse().unwrap_or(1);

    let (得分, 有效, 原因) = 质检(&text);
    let s = 统计(&text);
    let reason_join = 原因.join("; ");
    println!(
        "SCORE={:.1} EFFECTIVE={} REASONS={} STATS={},{:.4},{:.4},{:.4},{:.4}",
        得分,
        if 有效 { 1 } else { 0 },
        reason_join,
        s.净字符数, s.中文占比, s.乱码率, s.重复率, s.标点密度
    );

    let t0 = Instant::now();
    let mut acc = 0u64;
    for _ in 0..iters {
        let (_, _, r) = 质检(&text);
        acc += r.len() as u64;
    }
    let ms = t0.elapsed().as_secs_f64() * 1000.0;
    println!("QD_MS={:.3}", ms);
    println!("QD_REASONS_TOTAL={}", acc);
}