# -*- coding: utf-8 -*-
"""备用源登记: 书目录URL → [备用目录URL, ...]（多源回退的数据层）。

## 为什么有这个模块（需求）
"死书时询问用户要不要给这本书添加一个新网站；没有就问是否删除"。
项目**早已有**多源回退机制（`爬虫.py:7119-7136`）：主源被验证码拦死 / 章节大面积失败时，
按 `captcha_config.json` 的 `fallback_sources` 自动切换备用源继续抓。
但该字段**只有消费方、没有 UI** —— 用户只能手工编辑 JSON。
本模块负责读写与校验，交互交给 `gui_components/补址弹窗.py`。

## ⚠️ 键必须与消费侧**逐字节**一致
`爬虫.py:7073` 在读取备用源**之前**会先把目录 URL 过一遍 `_规范化目录URL`
（适配器的"章节页 → 目录页"能力），再在 `:7130` 用 `fs.get(catalog_url)` **精确匹配**。
所以本模块写入前也走同一函数；否则键对不上，登记了也永远查不到。

## 配置落点
`captcha_config.json`（程序基目录 = EXE 旁 / 项目根）。
测试与探针用环境变量 `NC_FALLBACK_CONFIG` 指向隔离文件
（与 `网站清单.py` 的 `NC_LEDGER_PATH` 同一范式）。

## 数据形状
```json
{"fallback_sources": {"https://站点/书目录页": ["https://另一站点/同书目录页"]}}
```
值也允许是"指向一个 JSON 文件"的字符串（消费侧 `爬虫.py:7127` 支持），
本模块**只读不写**那种形态：遇到字符串时按"无法追加"处理，不改写用户的手工配置。
"""
import json
import os
import threading
from pathlib import Path
from urllib.parse import urlsplit

import 日志 as _app_log

_log = _app_log.get('备用源')

# 测试/探针/多实例隔离: 指向另一份 captcha_config.json
环境覆盖变量 = 'NC_FALLBACK_CONFIG'
_配置文件 = 'captcha_config.json'

_锁 = threading.RLock()


def 配置路径() -> str:
    """配置文件的真实落点（环境变量优先，便于测试隔离）。"""
    覆盖 = os.environ.get(环境覆盖变量, '').strip()
    if 覆盖:
        return 覆盖
    try:
        from _path_utils import resolve_data_file
        return resolve_data_file(_配置文件, copy_default_from_resource_if_missing=True)
    except Exception as _e:
        _log.info(f"[备用源] 路径解析降级为程序根: {type(_e).__name__}: {_e}")
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), _配置文件)


def _规范化键(网址: str) -> str:
    """与消费侧同源的键规范化（章节页 → 目录页；不可用时按原样）。

    消费侧 = `爬虫.py:7073` 的 `_规范化目录URL`。这里**必须**复用同一实现，
    否则写入的键与 `fs.get(catalog_url)` 查的键可能不同 → 登记了也查不到。
    """
    u = (网址 or '').strip()
    if not u:
        return ''
    try:
        from 爬虫 import _规范化目录URL
        归一 = _规范化目录URL(u)
        return (归一 or u).strip()
    except Exception as _e:
        # 降级: 按原样（多数字典 URL 本来就是目录页, 规范化是恒等）
        _log.info(f"[备用源] 规范化不可用, 按原样式登记: {type(_e).__name__}: {_e}")
        return u


def _校验新网址(新网址: str, 目录URL: str) -> str:
    """返回空串 = 合法；否则返回人话原因（供弹窗直接展示）。"""
    u = (新网址 or '').strip()
    if not u:
        return '请先填写新的目录页网址'
    if not u.lower().startswith(('http://', 'https://')):
        return '网址必须以 http:// 或 https:// 开头'
    try:
        sp = urlsplit(u)
    except Exception:
        return '网址格式无法解析'
    if not sp.netloc:
        return '网址缺少站点名（例如 https://example.com/book/1）'
    if u.rstrip('/') == (目录URL or '').strip().rstrip('/'):
        return '新网址与原网址相同, 无需作为备用源'
    return ''


def _读(严格: bool = False) -> dict:
    """读配置。严格模式解析失败时抛异常 —— 写路径必须用它, 绝不覆盖坏文件。"""
    路径 = 配置路径()
    if not os.path.exists(路径):
        return {}
    try:
        return json.loads(Path(路径).read_text(encoding='utf-8')) or {}
    except Exception as e:
        _log.info(f"[备用源] 配置读取失败: {type(e).__name__}: {e}")
        if 严格:
            raise
        return {}


def _原子写(数据: dict) -> None:
    """原子写（tmp + os.replace，tmp 带 pid 防多进程互截）。范式同 captcha_module.Config.save。"""
    目标 = Path(配置路径()).resolve()
    临时 = 目标.with_name(目标.name + f'.tmp.{os.getpid()}')
    临时.write_text(json.dumps(数据, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(临时, 目标)


def 全部() -> dict:
    """当前登记的所有备用源（规范化键 → [URL, ...]）；非字典形态返回 {}。"""
    fs = _读().get('fallback_sources')
    if not isinstance(fs, dict):
        return {}
    return {k: list(v) for k, v in fs.items() if isinstance(v, (list, tuple))}


def 取备用源(目录URL: str) -> list:
    """查这本书登记过的备用源（消费侧同一口径）。"""
    键 = _规范化键(目录URL)
    if not 键:
        return []
    return list(全部().get(键, []))


def 添加备用源(目录URL: str, 新网址: str) -> dict:
    """登记一个备用源。

    Returns:
        {'可以': bool, '原因': str, '键': str, '备用源': [...]}
        —— 原因在失败时是给用户看的人话；成功且已存在时 '原因' 为 '已登记过'（幂等）。
    """
    键 = _规范化键(目录URL)
    if not 键:
        return {'可以': False, '原因': '缺少原目录页网址, 无法登记备用源',
                '键': '', '备用源': []}
    原因 = _校验新网址(新网址, 目录URL)
    if 原因:
        return {'可以': False, '原因': 原因, '键': 键, '备用源': 取备用源(目录URL)}
    新址 = (新网址 or '').strip()
    with _锁:
        try:
            配置 = _读(严格=True)
        except Exception as e:
            # 关键安全: 配置坏了就**不写**, 否则会把用户手工配置整体覆盖掉
            return {'可以': False,
                    '原因': f'配置文件无法解析, 已保护未写入 ({type(e).__name__})',
                    '键': 键, '备用源': []}
        fs = 配置.get('fallback_sources')
        if isinstance(fs, str):
            # 用户手工配置成"指向 JSON 文件"的形态: 不动它 (消费侧支持该形态)
            return {'可以': False,
                    '原因': '备用源已配置为外部文件, 请在文件里手工添加',
                    '键': 键, '备用源': []}
        if not isinstance(fs, dict):
            fs = {}
        现有 = fs.get(键)
        if not isinstance(现有, (list, tuple)):
            现有 = []
        现有 = [x for x in 现有 if isinstance(x, str)]
        if 新址 in 现有:
            return {'可以': True, '原因': '已登记过', '键': 键, '备用源': list(现有)}
        更新 = list(现有) + [新址]
        fs[键] = 更新
        配置['fallback_sources'] = fs
        try:
            _原子写(配置)
        except OSError as e:
            _log.info(f"[备用源] 写入失败: {type(e).__name__}: {e}")
            return {'可以': False, '原因': f'写入配置失败 ({type(e).__name__})',
                    '键': 键, '备用源': list(现有)}
    _log.info(f"[备用源] 已登记备用源: {键} ← {新址} (共 {len(更新)} 个)")
    return {'可以': True, '原因': '', '键': 键, '备用源': 更新}


def 移除备用源(目录URL: str, 新网址: str) -> dict:
    """注销一个备用源（用户反悔 / 备用源也失效了）。"""
    键 = _规范化键(目录URL)
    新址 = (新网址 or '').strip()
    if not 键 or not 新址:
        return {'可以': False, '原因': '参数不完整', '备用源': []}
    with _锁:
        try:
            配置 = _读(严格=True)
        except Exception as e:
            return {'可以': False, '原因': f'配置文件无法解析, 已保护未写入 ({type(e).__name__})',
                    '备用源': []}
        fs = 配置.get('fallback_sources')
        if not isinstance(fs, dict):
            return {'可以': False, '原因': '没有可移除的备用源', '备用源': []}
        现有 = fs.get(键)
        if not isinstance(现有, (list, tuple)) or 新址 not in 现有:
            return {'可以': False, '原因': '该备用源不存在', '备用源': list(现有 or [])}
        更新 = [x for x in 现有 if x != 新址]
        if 更新:
            fs[键] = 更新
        else:
            fs.pop(键, None)      # 最后一个移除后不留空键 (消费侧空列表无害, 但保持干净)
        配置['fallback_sources'] = fs
        try:
            _原子写(配置)
        except OSError as e:
            return {'可以': False, '原因': f'写入配置失败 ({type(e).__name__})',
                    '备用源': list(现有)}
    _log.info(f"[备用源] 已移除备用源: {键} ← {新址} (剩 {len(更新)} 个)")
    return {'可以': True, '原因': '', '备用源': 更新}
