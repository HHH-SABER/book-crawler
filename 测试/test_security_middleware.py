# -*- coding: utf-8 -*-
"""远控安全中间件回归 (R-M01/R-M02/R-M03, 2026-11-09)。

用独立 FastAPI app 装配同一套中间件 (不导入 远控.服务 的完整 app, 避免
副作用), 锁住三件事:
  ① 所有响应都带安全头 (含 400/429 这类中间件产生的响应);
  ② Host 放行/拒绝语义 (私网IP/回环/localhost/*.ts.net 放行; 公网域名拒绝);
  ③ 认证失败限流: 同 IP 超 30 次 401 → 429; 正常请求不受影响。
"""
import sys
import unittest
from pathlib import Path

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

from fastapi import FastAPI, HTTPException   # noqa: E402
from fastapi.testclient import TestClient   # noqa: E402

from 远控.安全中间件 import (安装, 主机是否允许, 失败限流中间件,   # noqa: E402
                         _安全头, _失败上限, _跟踪IP上限)


def _建应用() -> TestClient:
    app = FastAPI()

    @app.get('/')
    def 首页():
        return {'ok': True}

    @app.get('/auth')
    def 鉴权(k: str = ''):
        if k != 'right-token':
            raise HTTPException(status_code=401, detail='未授权')
        return {'ok': True}

    安装(app)
    return TestClient(app, client=('192.168.1.5', 40000))


class Test安全头(unittest.TestCase):

    def test_正常响应带全套安全头(self):
        r = _建应用().get('/')
        self.assertEqual(r.status_code, 200)
        for 名, 值 in _安全头.items():
            self.assertEqual(r.headers.get(名), 值, f'缺安全头 {名}')

    def test_CSP必须允许内联脚本(self):
        """面板有 onclick + 内联 <script>, 不允许 inline 会白屏 (回归守护)。"""
        csp = _建应用().get('/').headers['Content-Security-Policy']
        self.assertIn("script-src 'self' 'unsafe-inline'", csp)
        self.assertIn("frame-ancestors 'none'", csp)

    def test_拒绝响应也带安全头(self):
        r = _建应用().get('/', headers={'Host': 'evil.example.com'})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.headers.get('X-Content-Type-Options'), 'nosniff')


class Test主机校验(unittest.TestCase):

    def test_放行本机与私网与Tailscale(self):
        for host in ('127.0.0.1:8760', 'localhost:8760', '[::1]:8760',
                     '192.168.1.5:8760', '10.0.0.8:8760', '172.20.1.2',
                     'myhost.tail1234.ts.net', 'macbook.local', 'testserver'):
            with self.subTest(host):
                self.assertTrue(主机是否允许(host), f'{host} 应放行')

    def test_拒绝公网域名与空Host(self):
        for host in ('evil.example.com', 'book.example.invalid', '', '   ',
                     '192.168.1.5.evil.com'):
            with self.subTest(host):
                self.assertFalse(主机是否允许(host), f'{host} 应拒绝')

    def test_配置里的人为放行(self):
        self.assertTrue(主机是否允许('novel.home.lan',
                                     ('novel.home.lan',)), '配置项应放行')

    def test_接口层拦截(self):
        c = _建应用()
        self.assertEqual(c.get('/', headers={'Host': 'evil.example.com'}).status_code, 400)
        ok = c.get('/', headers={'Host': '192.168.1.5:8760'})
        self.assertEqual(ok.status_code, 200)
        self.assertIn('允许主机', c.get('/', headers={'Host': 'evil.example.com'}).json()['detail'])


class Test失败限流(unittest.TestCase):

    def test_超限后429(self):
        应用 = _建应用()
        中间件 = next(m for m in 应用.app.user_middleware
                      if '失败限流' in str(m))
        self.assertIn('失败限流', str(中间件))
        # 直接构造中间件实例做行为断言 (TestClient 每次新建栈, 状态不共享)
        mw = 失败限流中间件(app=None)
        客户端 = '10.1.2.3'
        import time as _t
        now = _t.monotonic()
        mw._记录[客户端] = [now] * _失败上限
        self.assertTrue(mw._是否超限(客户端, now), '满额后应判超限')
        mw.重置()
        self.assertFalse(mw._是否超限(客户端, now), '重置后不超限')

    def test_401计数与401以下不计数(self):
        mw = 失败限流中间件(app=None)
        import time as _t
        now = _t.monotonic()
        mw._记失败('1.2.3.4', now)
        self.assertEqual(len(mw._记录['1.2.3.4']), 1)
        self.assertEqual(len(mw._记录.get('5.6.7.8', [])), 0)

    def test_IP条目上限保护(self):
        mw = 失败限流中间件(app=None)
        import time as _t
        now = _t.monotonic()
        for i in range(_跟踪IP上限 + 50):
            mw._记失败(f'10.0.{i // 250}.{i % 250}', now)
        self.assertLessEqual(len(mw._记录), _跟踪IP上限 + 1, '不得无界增长')

    def test_端到端_连续401触发429(self):
        """真实接线: 同 IP 连续错 token → 超限后 429 (不只测辅助函数)。"""
        c = _建应用()
        for i in range(_失败上限):
            r = c.get('/auth', params={'k': 'wrong'})
            self.assertEqual(r.status_code, 401, f'第 {i + 1} 次应 401')
        r = c.get('/auth', params={'k': 'wrong'})
        self.assertEqual(r.status_code, 429, '超过上限必须 429')
        self.assertIn('过多', r.json()['detail'])
        # 429 之后正确 token 也被挡 (限流生效期间) —— 这正是限流的意义
        self.assertEqual(c.get('/auth', params={'k': 'right-token'}).status_code, 429)

    def test_正常请求不被限流(self):
        c = _建应用()
        for _ in range(_失败上限 + 5):
            self.assertEqual(c.get('/').status_code, 200)


if __name__ == '__main__':
    unittest.main(verbosity=2)
