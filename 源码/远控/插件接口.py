# -*- coding: utf-8 -*-
"""浏览器插件协作接口 —— P1 凭据中继 (2026-10-20)。

方案依据: `文档/浏览器插件可行性方案.md`。本期只做 P1:
浏览器插件把目标站的真实 Cookie 推给爬虫, 写入**既有**域 COOKIE 库
(`站点适配_本地/域名cookies.json`) —— 三引擎经 `注入COOKIE()` 直接受益,
爬虫主流程零改动。解决 js_cookie 类反爬 / WAF 放行 Cookie 拿不到的问题。

## 安全护栏 (本机接口必须有的三条)

1. **仅本机**: 手机远控需要 0.0.0.0, 但本组接口额外校验
   `request.client.host ∈ {127.0.0.1, ::1}` —— 局域网/手机不能推 Cookie;
2. **token**: 复用远控 token (`hmac.compare_digest` 常时比较);
3. **白名单**: 只接受用户**明确添加过**的域 (`数据/插件白名单.json`)。
   任意网页借 localhost 把自己域的 Cookie "推"进来是无效的 —— 必须先在
   插件里点"加入白名单"。

## 端点

- GET  /api/v1/ext/ping       连通性 + 版本 (插件加载时探测)
- GET  /api/v1/ext/whitelist  读白名单 (插件定期同步)
- POST /api/v1/ext/whitelist  {domains: ["a.com", ...]} 覆盖式设置
- POST /api/v1/ext/cookies    {domain, cookies: [{name, value}] 或 cookie_string}

## 路径覆盖 (测试/多实例隔离, 同 NC_FALLBACK_CONFIG 范式)

- `NC_EXT_COOKIES`   域 COOKIE 库路径
- `NC_EXT_WHITELIST` 白名单路径
"""
import hmac
import json
import os
import threading
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request

import 日志 as _app_log

_log = _app_log.get('插件接口')

router = APIRouter(prefix='/api/v1/ext', tags=['extension'])

_环境_库 = 'NC_EXT_COOKIES'
_环境_白名单 = 'NC_EXT_WHITELIST'
_锁 = threading.RLock()


def _基目录() -> str:
    try:
        from _path_utils import get_app_base_dir
        return get_app_base_dir()
    except Exception:
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def 库路径() -> str:
    """域 COOKIE 库 (= 请求引擎 _加载域COOKIE 读的那个文件)。"""
    覆盖 = os.environ.get(_环境_库, '').strip()
    if 覆盖:
        return 覆盖
    return os.path.join(_基目录(), '站点适配_本地', '域名cookies.json')


def 白名单路径() -> str:
    覆盖 = os.environ.get(_环境_白名单, '').strip()
    if 覆盖:
        return 覆盖
    return os.path.join(_基目录(), '数据', '插件白名单.json')


def _读json(路径: str, 默认):
    try:
        return json.loads(Path(路径).read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return 默认


def _原子写(路径: str, 内容: str) -> None:
    """tmp + os.replace, 带文件锁 (与 网站清单/备用源 同范式)。"""
    from 文件锁 import 写锁
    os.makedirs(os.path.dirname(路径) or '.', exist_ok=True)
    with 写锁(路径):
        tmp = 路径 + f'.tmp.{os.getpid()}'
        Path(tmp).write_text(内容, encoding='utf-8')
        os.replace(tmp, 路径)


def _规范化域(域: str) -> str:
    域 = (域 or '').strip().lower()
    if 域.startswith('www.'):
        域 = 域[4:]
    return 域


def 取白名单() -> list:
    数据 = _读json(白名单路径(), [])
    if isinstance(数据, dict):
        数据 = 数据.get('domains', [])
    if not isinstance(数据, list):
        return []
    return [_规范化域(x) for x in 数据 if str(x).strip()]


def _在白名单(域名: str) -> bool:
    """域名或其注册父域在白名单内 (白名单存 'example.com' 可覆盖 book.example.com)。"""
    域名 = _规范化域(域名)
    for 项 in 取白名单():
        if 域名 == 项 or 域名.endswith('.' + 项):
            return True
    return False


def _拼cookie串(条目) -> str:
    """[{name,value}, ...] → 'k=v; k2=v2' (过滤空值/过期)。"""
    对s = []
    for x in 条目 or []:
        if not isinstance(x, dict):
            continue
        名, 值 = str(x.get('name', '')).strip(), str(x.get('value', ''))
        if not 名:
            continue
        过期 = x.get('expirationDate')
        if isinstance(过期, (int, float)) and 过期 > 0:
            import time
            if 过期 < time.time():
                continue
        对s.append(f'{名}={值}')
    return '; '.join(对s)


def _取token() -> str:
    try:
        from .配置 import 取配置
        return str(取配置().get('token', '') or '')
    except Exception:
        return ''


def _要求token(k: Optional[str] = None,
              authorization: Optional[str] = Header(default=None)) -> None:
    """与远控同口径: ?k= 或 Authorization: Bearer <token>, 常时比较。"""
    token = _取token()
    supplied = (k or '').strip()
    if not supplied and authorization:
        v = authorization.strip()
        if v.lower().startswith('bearer '):
            supplied = v[7:].strip()
    if not token or not supplied or not hmac.compare_digest(
            supplied.encode('utf-8'), token.encode('utf-8')):
        raise HTTPException(status_code=403, detail='token 无效')


def _要求本机(request: Request) -> None:
    """仅 127.0.0.1/::1 可调用 (手机远控不受影响: 它走的是 /api/v1/tasks)。"""
    客户端 = getattr(getattr(request, 'client', None), 'host', '') or ''
    if 客户端 not in ('127.0.0.1', '::1'):
        raise HTTPException(status_code=403, detail='该接口仅限本机调用')


@router.get('/ping')
def ext_ping(request: Request, k: Optional[str] = None,
             authorization: Optional[str] = Header(default=None)):
    _要求token(k, authorization)
    _要求本机(request)
    return {'ok': True, 'service': '小说爬虫·凭据中继', 'version': 1,
            'cookies_path': 库路径(), 'whitelist': 取白名单()}


@router.get('/whitelist')
def ext_get_whitelist(request: Request, k: Optional[str] = None,
                      authorization: Optional[str] = Header(default=None)):
    _要求token(k, authorization)
    _要求本机(request)
    return {'domains': 取白名单()}


@router.post('/whitelist')
def ext_set_whitelist(request: Request, payload: dict, k: Optional[str] = None,
                      authorization: Optional[str] = Header(default=None)):
    _要求token(k, authorization)
    _要求本机(request)
    域s = payload.get('domains') if isinstance(payload, dict) else None
    if not isinstance(域s, list):
        raise HTTPException(status_code=400, detail='domains 必须是字符串数组')
    清洗 = sorted({_规范化域(str(x)) for x in 域s if str(x).strip()})
    _原子写(白名单路径(), json.dumps({'domains': 清洗}, ensure_ascii=False, indent=1))
    _log.info(f'[插件白名单] 更新为 {len(清洗)} 个域: {清洗[:6]}')
    return {'ok': True, 'domains': 清洗}


@router.post('/cookies')
def ext_push_cookies(request: Request, payload: dict, k: Optional[str] = None,
                     authorization: Optional[str] = Header(default=None)):
    """插件推送某域的全部 Cookie → 写入域 COOKIE 库 (替换该域旧串)。

    请求体: {'domain': 'book.example.com',
             'cookies': [{'name':'a','value':'1','expirationDate':...}]}
     或   {'domain': ..., 'cookie_string': 'a=1; b=2'}
    """
    _要求token(k, authorization)
    _要求本机(request)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail='请求体必须是 JSON 对象')
    域名 = _规范化域(str(payload.get('domain', '')))
    if not 域名 or '/' in 域名 or ' ' in 域名:
        raise HTTPException(status_code=400, detail='domain 非法')
    if not _在白名单(域名):
        raise HTTPException(status_code=403,
                            detail=f'域名 {域名} 不在插件白名单内 (先在插件里加入白名单)')
    if isinstance(payload.get('cookies'), list):
        串 = _拼cookie串(payload['cookies'])
    else:
        串 = str(payload.get('cookie_string', '') or '').strip()
    if not 串:
        raise HTTPException(status_code=400, detail='没有可写入的 Cookie (全部为空或已过期)')
    with _锁:
        库 = _读json(库路径(), {})
        if not isinstance(库, dict):
            库 = {}
        库[域名] = 串
        _原子写(库路径(), json.dumps(库, ensure_ascii=False, indent=1))
    _log.info(f'[凭据中继] {域名} ← {len(串.split("; "))} 条 Cookie (来源: 浏览器插件)')
    return {'ok': True, 'domain': 域名, 'count': len(串.split('; '))}
