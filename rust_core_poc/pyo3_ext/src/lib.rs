// -*- coding: utf-8 -*-
// PyO3 扩展: 将 parse_codepoint_stream 与 内容质检器 暴露给 Python。
// 每个算法各提供 _gil / _nogil 两个入口, 用于对照"释放 GIL 与否对并发的影响":
//   <fn>_gil   : 计算在持有 GIL 的原生线程中做 (与 CPython 执行器同等地被 GIL 串行)
//   <fn>_nogil : 用 py.allow_threads 释放 GIL, 让多个 worker 真正并行
use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::collections::{HashMap, HashSet};

// =====================================================================
// parse_codepoint_stream
// =====================================================================
fn is_hex(c: char) -> bool {
    c.is_ascii_hexdigit()
}

fn build_mapping(map: Option<&HashMap<String, String>>) -> HashMap<char, char> {
    let mut m = HashMap::new();
    if let Some(d) = map {
        for (code, ctrl) in d {
            let mut cs = ctrl.chars();
            if let (Some(c), None) = (cs.next(), cs.next()) {
                if (c as u32) < 32
                    && (2..=6).contains(&code.len())
                    && code.chars().all(is_hex)
                {
                    if let Some(v) = u32::from_str_radix(code, 16)
                        .ok()
                        .and_then(char::from_u32)
                    {
                        m.insert(c, v);
                    }
                }
            }
        }
    }
    m
}

fn is_hex4(s: &str) -> bool {
    s.len() == 4 && s.chars().all(is_hex)
}

fn parse_codepoint_stream_core(content: &str, mapping: &HashMap<char, char>) -> String {
    let chars: Vec<char> = content.chars().collect();
    let n = chars.len();
    let mut out = String::with_capacity(n);
    let mut i = 0usize;
    let mut pending_marker = false;
    while i < n {
        let c = chars[i];
        // x + 4 hex
        if c == 'x' && i + 4 < n && (1..=4).all(|k| is_hex(chars[i + k])) {
            let hex: String = chars[i + 1..i + 5].iter().collect();
            i += 5;
            if pending_marker && is_hex4(&hex) {
                pending_marker = false;
                if let Some(v) = u32::from_str_radix(&hex, 16).ok().and_then(char::from_u32) {
                    out.push(v);
                } else {
                    out.push_str(&hex);
                }
            } else {
                pending_marker = false;
                match u32::from_str_radix(&hex, 16).ok().and_then(char::from_u32) {
                    Some(v) => out.push(v),
                    None => {
                        out.push('x');
                        out.push_str(&hex);
                    }
                }
            }
            continue;
        }
        // 4 hex
        if i + 3 < n && (0..4).all(|k| is_hex(chars[i + k])) {
            let hex: String = chars[i..i + 4].iter().collect();
            i += 4;
            if pending_marker && is_hex4(&hex) {
                pending_marker = false;
                if let Some(v) = u32::from_str_radix(&hex, 16).ok().and_then(char::from_u32) {
                    out.push(v);
                } else {
                    out.push_str(&hex);
                }
            } else {
                pending_marker = false;
                out.push_str(&hex);
            }
            continue;
        }
        // 单字符
        i += 1;
        pending_marker = false;
        if let Some(&rep) = mapping.get(&c) {
            out.push(rep);
        } else if c == '\x01' || c == '\x02' || c == '\x03' {
            pending_marker = true;
        } else if c == '\x04' {
            out.push('\n');
        } else if c == ';' || c < ' ' {
        } else {
            out.push(c);
        }
    }
    out
}

#[pyfunction]
fn parse_codepoint_stream_gil(
    py: Python<'_>,
    content: &str,
    replace_map: Option<HashMap<String, String>>,
) -> PyResult<String> {
    let mapping = build_mapping(replace_map.as_ref());
    // 持有 GIL 下同步执行 (与纯 Python 同等受 GIL 约束)
    let _ = py;
    Ok(parse_codepoint_stream_core(content, &mapping))
}

#[pyfunction]
fn parse_codepoint_stream_nogil(
    py: Python<'_>,
    content: &str,
    replace_map: Option<HashMap<String, String>>,
) -> PyResult<String> {
    let mapping = build_mapping(replace_map.as_ref());
    let s = content.to_string();
    // 释放 GIL: 计算在原生线程中, 其他 worker 的 Python 字节码可并行
    let r = py.allow_threads(|| parse_codepoint_stream_core(&s, &mapping));
    Ok(r)
}

// =====================================================================
// 内容质检器 (五维评分)
// =====================================================================
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
    matches!(c, '，'|'。'|'！'|'？'|'；'|'：'|'、'|'…'|'—'|'·'|','|'!'|'?'|';'|':'|'~'|'.'|'-'|'('|')'|'（'|'）'|'['|']'|'【'|'】'|'《'|'》'|'\u{201c}'|'\u{201d}'|'\u{2018}'|'\u{2019}'|'"'|'\'')
}
fn 乱码串总长(text: &str) -> usize {
    let chars: Vec<char> = text.chars().collect();
    let n = chars.len();
    let mut total = 0usize;
    let mut run = 0usize;
    for i in 0..=n {
        let c = if i < n { chars[i] } else { '\n' };
        let allowed = is_cjk(c) || (c.is_ascii() && c.is_alphanumeric()) || c.is_whitespace() || is_标点(c);
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
fn 取round(x: f64, d: i32) -> f64 {
    let m = 10f64.powi(d);
    (x * m).round() / m
}
fn 评分长度(净: usize) -> f64 {
    if 净 >= 阈值长 {
        W_长度
    } else if 净 >= 阈值短长 {
        取round(W_长度 * (净 as f64 - 阈值短长 as f64) / (阈值长 as f64 - 阈值短长 as f64), 1)
    } else {
        0.0
    }
}
fn 评分中文(中: f64) -> f64 {
    if 中 >= 阈值中文 {
        W_中文
    } else if 中 >= 硬伤中文 {
        取round(W_中文 * (中 - 硬伤中文) / (阈值中文 - 硬伤中文), 1)
    } else {
        0.0
    }
}
fn 评分乱码(率: f64) -> f64 {
    if 率 <= 阈值乱码 {
        W_乱码
    } else if 率 <= 硬伤乱码 {
        取round(W_乱码 * (硬伤乱码 - 率) / (硬伤乱码 - 阈值乱码), 1)
    } else {
        0.0
    }
}
fn 评分重复(率: f64) -> f64 {
    if 率 <= 阈值重复 {
        W_重复
    } else {
        0.0
    }
}
fn 评分标点(密度: f64) -> f64 {
    if 标点下限 <= 密度 && 密度 <= 标点上限 {
        W_标点
    } else if (0.005..标点下限).contains(&密度) || (标点上限 < 密度 && 密度 <= 0.40) {
        取round(W_标点 * 0.5, 1)
    } else {
        0.0
    }
}

#[derive(Clone, Copy)]
struct 统计 {
    净: usize,
    行: usize,
    中: f64,
    乱: f64,
    重: f64,
    标: f64,
}
fn 统计(text: &str) -> 统计 {
    let 总 = text.chars().count();
    if 总 == 0 {
        return 统计 { 净: 0, 行: 0, 中: 0.0, 乱: 1.0, 重: 1.0, 标: 0.0 };
    }
    let mut cjk = 0usize;
    let mut 乱c = 0usize;
    let mut 标 = 0usize;
    for c in text.chars() {
        if is_cjk(c) {
            cjk += 1;
        }
        if is_乱码_char(c) {
            乱c += 1;
        }
        if is_标点(c) {
            标 += 1;
        }
    }
    let lines: Vec<&str> = text.lines().map(|l| l.trim()).filter(|l| !l.is_empty()).collect();
    let 行 = lines.len();
    let mut seen = HashSet::new();
    for l in &lines {
        seen.insert(*l);
    }
    let 去 = seen.len();
    统计 {
        净: 总,
        行,
        中: cjk as f64 / 总 as f64,
        乱: (乱c + 乱码串总长(text)) as f64 / 总 as f64,
        重: if 行 > 0 { 1.0 - 去 as f64 / 行 as f64 } else { 1.0 },
        标: 标 as f64 / 总 as f64,
    }
}

fn 质检_core(text: &str) -> (f64, bool, Vec<String>) {
    if text.is_empty() || text.trim().is_empty() {
        return (0.0, false, vec![String::from("正文为空")]);
    }
    let s = 统计(text);
    let 得分 = 取round(
        评分长度(s.净) + 评分中文(s.中) + 评分乱码(s.乱) + 评分重复(s.重) + 评分标点(s.标),
        1,
    );
    let mut 原因: Vec<String> = Vec::new();
    if s.乱 > 硬伤乱码 {
        原因.push(format!("乱码率{:.0}%>{:.0}%", s.乱 * 100.0, 硬伤乱码 * 100.0));
    }
    if s.中 < 硬伤中文 {
        原因.push(format!("中文占比{:.0}%<{:.0}%", s.中 * 100.0, 硬伤中文 * 100.0));
    }
    if 评分长度(s.净) == 0.0 && 原因.is_empty() {
        原因.push(format!("长度不足({}字)", s.净));
    }
    if 评分中文(s.中) == 0.0 && 硬伤中文 <= s.中 && 原因.is_empty() {
        原因.push(format!("中文占比{:.0}%", s.中 * 100.0));
    }
    if 评分乱码(s.乱) == 0.0 && s.乱 <= 硬伤乱码 {
        原因.push(format!("乱码率{:.0}%", s.乱 * 100.0));
    }
    if 评分重复(s.重) == 0.0 {
        原因.push(format!("重复率{:.0}%", s.重 * 100.0));
    }
    if 评分标点(s.标) == 0.0 {
        原因.push(format!("标点密度{:.1}%", s.标 * 100.0));
    }
    let 有效 = 得分 >= 及格分 && 原因.is_empty();
    (得分, 有效, 原因)
}

#[pyfunction]
fn qa_质检_gil(py: Python<'_>, text: &str) -> PyResult<(f64, bool, Vec<String>)> {
    let _ = py;
    Ok(质检_core(text))
}

#[pyfunction]
fn qa_质检_nogil(py: Python<'_>, text: &str) -> PyResult<(f64, bool, Vec<String>)> {
    let t = text.to_string();
    Ok(py.allow_threads(|| 质检_core(&t)))
}

// 全量接口: 返回 (得分, 有效, 原因, 统计dict). 统计字段与 _空统计/统计 完全一致,
// 供 Python 端直接构造质检报告, 保证报告结构与纯 Python 实现逐字段一致。
fn 质检_full_core(text: &str) -> (f64, bool, Vec<String>, usize, usize, f64, f64, f64, f64, f64) {
    let (得分, 有效, 原因) = 质检_core(text);
    let s = 统计(text);
    let nl = text.matches('\n').count();
    let 空白 = if nl > 0 {
        (nl + 1 - s.行) as f64 / (nl + 1) as f64
    } else {
        0.0
    };
    (得分, 有效, 原因, s.净, s.行, s.中, s.乱, s.重, s.标, 空白)
}

#[pyfunction]
fn qa_质检_full_nogil(py: Python<'_>, text: &str) -> PyResult<PyObject> {
    let (得分, 有效, 原因, 净, 行, 中, 乱, 重, 标, 空白) = {
        let t = text.to_string();
        py.allow_threads(|| 质检_full_core(&t))
    };
    let st = PyDict::new(py);
    st.set_item("净字符数", 净)?;
    st.set_item("行数", 行)?;
    st.set_item("中文占比", 中)?;
    st.set_item("乱码率", 乱)?;
    st.set_item("重复率", 重)?;
    st.set_item("标点密度", 标)?;
    st.set_item("空白行比", 空白)?;
    let d = PyDict::new(py);
    d.set_item("得分", 得分)?;
    d.set_item("有效", 有效)?;
    d.set_item("原因", 原因)?;
    d.set_item("统计", st)?;
    Ok(d.unbind().into_any())
}

// =====================================================================
#[pymodule]
fn rust_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(parse_codepoint_stream_gil, m)?)?;
    m.add_function(wrap_pyfunction!(parse_codepoint_stream_nogil, m)?)?;
    m.add_function(wrap_pyfunction!(qa_质检_gil, m)?)?;
    m.add_function(wrap_pyfunction!(qa_质检_nogil, m)?)?;
    m.add_function(wrap_pyfunction!(qa_质检_full_nogil, m)?)?;
    Ok(())
}