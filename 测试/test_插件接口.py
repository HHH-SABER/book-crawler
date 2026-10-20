# -*- coding: utf-8 -*-
"""浏览器插件协作接口回归 (P1 凭据中继, 2026-10-20)。

覆盖三层护栏 + 落地效果:
  ① 鉴权: 无 token / 错 token → 403; 正确 → 通;
  ② 仅本机: 非 127.0.0.1 来源 → 403 (手机/局域网推不进 Cookie);
  ③ 白名单: 未加白 → 403; 加白后可推; 注册父域覆盖子域;
  ④ 写入: 域 COOKIE 库格式 (域→'k=v; k2=v2'), 过期剔除, 空 → 400;
  ⑤ 端到端: 推送后 请求引擎.注入COOKIE() 真的带上 Cookie 头。

全程临时文件 (NC_EXT_COOKIES / NC_EXT_WHITELIST), 绝不碰真实配置。
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

from fastapi import FastAPI                       # noqa: E402
from fastapi.testclient import TestClient         # noqa: E402

from 远控.插件接口 import router as 插件路由        # noqa: E402
import 远控.插件接口 as 接口                       # noqa: E402

_TOKEN = 'test-token-0123456789'


def _应用() -> TestClient:
    app = FastAPI()
    app.include_router(插件路由)
    # 本机来源 (护栏 ② 的放行侧); 拒绝侧另建 client
    return TestClient(app, client=('127.0.0.1', 51234))


class _基座(unittest.TestCase):
    def setUp(self):
        根 = Path(tempfile.mkdtemp(prefix='插件接口_'))
        self.库 = str(根 / '域名cookies.json')
        self.名单 = str(根 / '插件白名单.json')
        os.environ[接口._环境_库] = self.库
        os.environ[接口._环境_白名单] = self.名单
        self.addCleanup(lambda: os.environ.pop(接口._环境_库, None))
        self.addCleanup(lambda: os.environ.pop(接口._环境_白名单, None))
        self.addCleanup(lambda: __import__('shutil').rmtree(根, ignore_errors=True))
        # token 替身 (不依赖真实 远控配置.json)
        p = mock.patch.object(接口, '_取token', return_value=_TOKEN)
        p.start()
        self.addCleanup(p.stop)
        self.c = _应用()
        self.头 = {'Authorization': f'Bearer {_TOKEN}'}

    def 加白(self, *域s):
        r = self.c.post('/api/v1/ext/whitelist', json={'domains': list(域s)}, headers=self.头)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()


class Test护栏(_基座):

    def test_无token拒绝(self):
        self.assertEqual(self.c.get('/api/v1/ext/ping').status_code, 403)

    def test_错token拒绝(self):
        r = self.c.get('/api/v1/ext/ping', headers={'Authorization': 'Bearer wrong'})
        self.assertEqual(r.status_code, 403)

    def test_正确token连通(self):
        r = self.c.get('/api/v1/ext/ping', headers=self.头)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['ok'])

    def test_非本机来源拒绝(self):
        app = FastAPI()
        app.include_router(插件路由)
        外网 = TestClient(app, client=('192.168.1.5', 40000))
        r = 外网.get('/api/v1/ext/ping', headers=self.头)
        self.assertEqual(r.status_code, 403, '局域网/手机不得推 Cookie')
        self.assertIn('本机', r.json()['detail'])

    def test_url参数k也认(self):
        r = self.c.get(f'/api/v1/ext/ping?k={_TOKEN}')
        self.assertEqual(r.status_code, 200)


class Test白名单(_基座):

    def _推(self, 域, 串='a=1; b=2'):
        return self.c.post('/api/v1/ext/cookies',
                           json={'domain': 域, 'cookie_string': 串}, headers=self.头)

    def test_未加白推送被拒(self):
        r = self._推('book.example.com')
        self.assertEqual(r.status_code, 403)
        self.assertIn('白名单', r.json()['detail'])

    def test_加白后可推且父域覆盖子域(self):
        self.加白('example.com')
        r = self._推('book.example.com')
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['count'], 2)
        库 = json.loads(Path(self.库).read_text(encoding='utf-8'))
        self.assertEqual(库['book.example.com'], 'a=1; b=2')

    def test_白名单读回规范化(self):
        self.加白('WWW.Example.com', 'other.example')
        r = self.c.get('/api/v1/ext/whitelist', headers=self.头)
        self.assertEqual(r.json()['domains'], ['example.com', 'other.example'])


class Test写入(_基座):

    def test_数组形式与过期剔除(self):
        self.加白('example.com')
        import time
        r = self.c.post('/api/v1/ext/cookies', headers=self.头, json={
            'domain': 'www.example.com',
            'cookies': [
                {'name': 'session', 'value': 'abc'},
                {'name': 'waf', 'value': 'xyz'},
                {'name': 'expired', 'value': 'gone', 'expirationDate': time.time() - 100},
                {'name': '', 'value': 'no-name'},
            ],
        })
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['domain'], 'example.com')       # www 归一
        库 = json.loads(Path(self.库).read_text(encoding='utf-8'))
        self.assertEqual(库['example.com'], 'session=abc; waf=xyz')

    def test_空Cookie拒绝(self):
        self.加白('example.com')
        r = self.c.post('/api/v1/ext/cookies', headers=self.头,
                        json={'domain': 'example.com', 'cookies': []})
        self.assertEqual(r.status_code, 400)

    def test_重复推送覆盖旧串(self):
        self.加白('example.com')
        self.c.post('/api/v1/ext/cookies', headers=self.头,
                    json={'domain': 'example.com', 'cookie_string': 'old=1'})
        self.c.post('/api/v1/ext/cookies', headers=self.头,
                    json={'domain': 'example.com', 'cookie_string': 'new=2'})
        库 = json.loads(Path(self.库).read_text(encoding='utf-8'))
        self.assertEqual(库['example.com'], 'new=2')


class Test端到端注入(_基座):
    """推送 → 请求引擎.注入COOKIE() 真的带上 Cookie 头 (P1 的核心价值)。"""

    def test_推送后引擎注入(self):
        import 请求引擎
        self.加白('example.com')
        r = self.c.post('/api/v1/ext/cookies', headers=self.头,
                        json={'domain': 'example.com', 'cookie_string': 'session=abc; waf=xyz'})
        self.assertEqual(r.status_code, 200)
        # 让引擎从本测试的库目录读 (引擎按 BASE_DIR/站点适配_本地/域名cookies.json 找文件)
        根 = Path(self.库).parent
        _站点目录 = 根 / '站点适配_本地'
        _站点目录.mkdir(exist_ok=True)
        (_站点目录 / '域名cookies.json').write_text(
            Path(self.库).read_text(encoding='utf-8'), encoding='utf-8')
        with mock.patch('_path_utils.get_app_base_dir', return_value=str(根)), \
                mock.patch.object(请求引擎, '_COOKIE热检间隔', 0):
            请求引擎._域COOKIE.clear()
            请求引擎._COOKIE文件状态['检查'] = 0
            headers = 请求引擎.注入COOKIE({}, 'https://book.example.com/chapter/1.html')
        self.assertEqual(headers.get('Cookie'), 'session=abc; waf=xyz',
                         '引擎必须带上插件推送的 Cookie')
        # 非白名单域不应被注入
        with mock.patch('_path_utils.get_app_base_dir', return_value=str(根)), \
                mock.patch.object(请求引擎, '_COOKIE热检间隔', 0):
            请求引擎._COOKIE文件状态['检查'] = 0
            h2 = 请求引擎.注入COOKIE({}, 'https://other-site.org/x')
        self.assertNotIn('Cookie', h2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
