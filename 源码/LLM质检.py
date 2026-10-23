# -*- coding: utf-8 -*-
"""LLM 增强质检 (C6 Roadmap P4, 2026-10-17): 质检低分章节可选送 LLM 判定
"乱码/广告/正文", 给**人工复核建议** —— 云端增强, **默认关闭**。

Roadmap 定调 (文档/实施计划.md §C6-P4): "质检低分章节可选送 LLM 判定
'乱码/广告/正文'并给人工复核建议; **不进默认路径、不自动改写正文**"
(对齐 §P7 定调)。

**边界 (与 captcha_module 的点选模型同范式, 同口径)**:
  · 默认关闭 —— 需在 数据/LLM质检配置.json 显式 `"启用": true`;
  · 只送**质检未通过**的章节 (触发分数线可调), 正常章节零调用、零流量;
  · **只告警不改判**: LLM 结论写 质检报告.LLM建议 (人读文案), 绝不改
    得分/有效, 绝不自动重抓/改写正文 (与 P1"只告警不扣分"同族);
  · 任何失败/超时/未配置/解析失败 → None, 上层当没发生过 (不卡任务);
  · 端点是**用户自选** (本地 ollama/vLLM 或云厂商), 章节文本只会去用户
    配置的那里; api_key 只存本地配置 (gitignored), **绝不进仓库/日志**。

**配置** (数据/LLM质检配置.json, 缺文件=全部缺省=关闭):
  {
    "启用": false,
    "provider": "openai_api",        // ollama | openai_api | custom
    "endpoint": "http://127.0.0.1:11434",   // ollama 填到端口; openai 填到 /v1
    "api_key": "",                   // 仅 openai_api/custom 需要; 不记日志
    "model": "qwen2.5:7b",
    "触发分数线": 60,                // 得分 < 此值才送 (0-100)
    "超时秒": 60,
    "每次最多字数": 2000             // 正文截断 (控流量/成本)
  }
"""
import json
import os
import re
import threading

import 日志 as _app_log
_log = _app_log.get('LLM质检')

_LOCK = threading.Lock()

# 缺省配置 (缺文件/缺键全按此; 启用默认 False = 不进默认路径)
_缺省 = {
    '启用': False,
    'provider': 'openai_api',
    'endpoint': '',
    'api_key': '',
    'model': '',
    '触发分数线': 60,
    '超时秒': 60,
    '每次最多字数': 2000,
}

# LLM 必须在这三类里选 (解析后校验; 不在内的当解析失败)
_合法类别 = ('乱码', '广告', '正文')


def 取配置() -> dict:
    """读配置 (数据/LLM质检配置.json; 任何异常都回退缺省=关闭)。"""
    cfg = dict(_缺省)
    try:
        import _path_utils
        p = _path_utils.resolve_data_file('LLM质检配置.json',
                                          copy_default_from_resource_if_missing=False)
    except Exception:
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         '数据', 'LLM质检配置.json')
    try:
        磁盘 = json.loads(open(p, encoding='utf-8').read())
        if isinstance(磁盘, dict):
            cfg.update({k: v for k, v in 磁盘.items() if k in _缺省})
    except Exception:
        pass    # 文件不存在/坏 JSON → 保持缺省 (关闭)
    # 类型兜底 (配置文件是人手的, 脏数据不许炸)
    cfg['启用'] = bool(cfg['启用'])
    for 键 in ('触发分数线', '超时秒', '每次最多字数'):
        try:
            cfg[键] = max(1, int(cfg[键]))
        except (TypeError, ValueError):
            cfg[键] = _缺省[键]
    return cfg


def 启用中() -> bool:
    """快捷判定: 配置启用且端点非空 (抓取热路径每章问一次, 必须便宜)。"""
    try:
        cfg = 取配置()
        return bool(cfg['启用'] and str(cfg['endpoint']).strip())
    except Exception:
        return False


def _构造提示(标题: str, 正文: str, 最多字: int) -> str:
    """判定提示词: 只要三选一分类 + 原因 + 人工复核建议, 严格 JSON 回复。"""
    片段 = (正文 or '')[:最多字]
    return (
        '你是小说章节质检助手。下面给出一个从小说站点抓取的章节, 它的自动质检'
        '得分偏低。请判断这个章节的正文属于哪一类: "乱码"(编码错误/Base64 残留/'
        '乱码字符)、"广告"(整章都是推广/导航/无关内容)、"正文"(基本是正常小说'
        '正文, 低分可能只是短小或格式问题)。\n'
        f'章节标题: {标题 or "(无)"}\n'
        f'章节正文 (可能被截断):\n{片段}\n\n'
        '只回复一个 JSON 对象, 不要任何别的文字: '
        '{"类别": "乱码|广告|正文", "原因": "一句话", "建议": "给人工复核者的一句话"}'
    )


def _抽取判决(文本: str):
    """从 LLM 回复里抽 JSON 判决; 失败/类别不合法 → None。"""
    if not 文本:
        return None
    m = re.search(r'\{[^{}]*\}', 文本, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    类别 = str(d.get('类别', '')).strip()
    if 类别 not in _合法类别:
        return None
    return {
        '类别': 类别,
        '原因': str(d.get('原因', '')).strip()[:120],
        '建议': str(d.get('建议', '')).strip()[:120],
    }


def 判定章节(标题: str, 正文: str) -> dict | None:
    """送一个低分章节给 LLM 判定 (默认关闭/未配置/失败 → None)。

    Returns:
        {"类别": "乱码|广告|正文", "原因": ..., "建议": ...} 或 None。
        永不抛异常 —— 任何一步失败都只记 debug 并返回 None。
    """
    cfg = 取配置()
    if not cfg['启用'] or not str(cfg['endpoint']).strip():
        return None
    if not (正文 or '').strip():
        return None
    提示 = _构造提示(标题, 正文, cfg['每次最多字数'])
    try:
        import requests
        provider = str(cfg['provider']).strip().lower()
        endpoint = str(cfg['endpoint']).strip().rstrip('/')
        模型 = str(cfg['model']).strip()
        超时 = (10, cfg['超时秒'])
        if provider == 'ollama':
            resp = requests.post(
                f'{endpoint}/api/chat',
                json={'model': 模型 or 'qwen2.5:7b', 'stream': False,
                      'messages': [{'role': 'user', 'content': 提示}]},
                timeout=超时)
        elif provider == 'openai_api':
            resp = requests.post(
                f'{endpoint}/chat/completions',
                json={'model': 模型 or 'gpt-4o-mini',
                      'messages': [{'role': 'user', 'content': 提示}]},
                headers={'Authorization': f"Bearer {cfg['api_key'] or 'sk-local'}"},
                timeout=超时)
        else:   # custom: 直接 POST JSON
            头 = {}
            if cfg['api_key']:
                头['Authorization'] = f"Bearer {cfg['api_key']}"
            resp = requests.post(
                endpoint, json={'model': 模型, 'prompt': 提示},
                headers=头, timeout=超时)
        resp.raise_for_status()
        数据 = resp.json()
    except Exception as _e:
        # 网络/超时/坏 JSON: 只记类型不记内容 (章节文本与密钥都别进日志)
        _log.debug(f'裸 except 吞异常: {type(_e).__name__}: {_e} (LLM 判定失败, 按未启用处理)')
        return None
    # 取回复文本: OpenAI 兼容 / ollama / custom 三种形态 (2026-10-17 修:
    # ollama /api/chat 的 message 是 **dict** 不是 list, 旧解析只认 list 会漏)
    文本 = ''
    try:
        if isinstance(数据, dict):
            # OpenAI 兼容: choices[0].message.content
            for k in ('choices', 'messages', 'data'):
                v = 数据.get(k)
                项 = v[0] if isinstance(v, list) and v else (
                    v if isinstance(v, dict) else None)
                if isinstance(项, dict):
                    msg = 项.get('message')
                    if isinstance(msg, dict):
                        文本 = str(msg.get('content', '') or '')
                    else:
                        文本 = str(项.get('content', '') or 项.get('response', '') or '')
                    if 文本:
                        break
            # ollama 现行: {"message": {"content": ...}} (dict)
            if not 文本 and isinstance(数据.get('message'), dict):
                文本 = str((数据['message'] or {}).get('content', '') or '')
            # ollama 旧式/custom: {"response": "..."}
            if not 文本 and isinstance(数据.get('response'), str):
                文本 = 数据['response']
    except Exception as _e:
        _log.debug(f'裸 except 吞异常: {type(_e).__name__}: {_e} (LLM 回复结构异常)')
        return None
    判决 = _抽取判决(文本 or '')
    if 判决 is None:
        _log.debug('LLM 回复无可解析判决 (要求严格 JSON), 按未启用处理')
    return 判决


def 生成建议(判决: dict | None, 得分: float) -> str:
    """判决 → 人读的一行复核建议 (空判决返回 '')。"""
    if not 判决:
        return ''
    类别 = 判决.get('类别', '')
    尾 = f'LLM 复核: 判为「{类别}」({得分:.0f} 分)'
    if 判决.get('原因'):
        尾 += f' — {判决["原因"]}'
    if 判决.get('建议'):
        尾 += f'；建议: {判决["建议"]}'
    return 尾


def _自检():
    """模块自检: 默认关闭 + 未配置零调用 (供测试/排查)。"""
    cfg = 取配置()
    assert cfg['启用'] is False, '默认必须关闭'
    assert 启用中() is False, '未配置时必须判定为未启用'
    return cfg


if __name__ == '__main__':
    print('缺省配置:', json.dumps(_自检(), ensure_ascii=False))
