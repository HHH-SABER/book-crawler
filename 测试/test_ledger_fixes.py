# -*- coding: utf-8 -*-
"""台账修复项回归用例 (2026-09-11 批次)。

覆盖当日台账 §2.2 / §2.3 落地的修复:
  U1  请求引擎降级链 —— 连接级失败(None)必须计入失败计数
  U5  stop_task 状态白名单 —— 终态任务不得被改写成"已停止"
  U6  站点历史 int() 容错
  U7  站点适配器同域判断 —— startswith 前缀绕过
  U8  ensure_flet_cache 内网地址校验不被自己吞掉
  U13 质检报告 摘要() 在原因为空时的兜底(死分支删除后的行为契约)
  U14 人工兜底浏览器工厂注入
  U15 请求引擎单例并发唯一 + 会话缓存加锁
  U16/U17 历史落盘: 唯一临时文件名 + 写前合并磁盘新数据

均为离线用例 (网络/浏览器相关一律用桩替身)。
"""
import asyncio
import json
import os
import sys
import threading
import time
import unittest
from pathlib import Path

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))
sys.path.insert(0, str(_根 / '源码' / 'gui_components'))
sys.path.insert(0, str(_根 / '站点适配'))
sys.path.insert(0, str(_根 / '脚本'))

import task_manager as tm            # noqa: E402
import 请求引擎                        # noqa: E402


# ====================================================================
# U5 · stop_task 状态白名单
# ====================================================================
class TestStopTask状态白名单(unittest.TestCase):

    def setUp(self):
        self.mgr = tm.TaskManager(page=object())

    def _加任务(self, status):
        t = tm.TaskInfo(task_id='task_1', url='https://example.com/b/1')
        t.status = status
        self.mgr.tasks['task_1'] = t
        return t

    def test_运行中可停止(self):
        t = self._加任务('running')
        self.assertTrue(self.mgr.stop_task('task_1'))
        self.assertTrue(t.stop_flag.is_set())
        self.assertEqual(t.status, 'stopped')

    def test_已完成不得被改写(self):
        """回归: 旧实现对任何状态都置 stopped, 把"已完成"改写掉"""
        t = self._加任务('completed')
        self.assertFalse(self.mgr.stop_task('task_1'))
        self.assertEqual(t.status, 'completed', '终态任务不得被改写')
        self.assertFalse(t.stop_flag.is_set())

    def test_已失败不得被改写(self):
        t = self._加任务('failed')
        self.assertFalse(self.mgr.stop_task('task_1'))
        self.assertEqual(t.status, 'failed')

    def test_不存在的任务返回False(self):
        self.assertFalse(self.mgr.stop_task('没有这个任务'))


# ====================================================================
# U6 · 站点历史 int 容错
# ====================================================================
class Test站点历史整数容错(unittest.TestCase):

    def test_非数字回退缺省(self):
        import 站点历史
        self.assertEqual(站点历史._安全整数('abc'), 0)
        self.assertEqual(站点历史._安全整数(None), 0)
        self.assertEqual(站点历史._安全整数([1]), 0)
        self.assertEqual(站点历史._安全整数('7'), 7)
        self.assertEqual(站点历史._安全整数(3.9), 3)
        self.assertEqual(站点历史._安全整数('x', 缺省=5), 5)


# ====================================================================
# U7 · 适配器同域判断
# ====================================================================
class Test同域判断(unittest.TestCase):

    def setUp(self):
        import uuwxw
        self.uuwxw = uuwxw

    def test_伪装子域被识别为不同域(self):
        """回归: startswith 会让 uuwxw.cc.evil.com 冒充 uuwxw.cc"""
        self.assertFalse(self.uuwxw._同域(
            'https://uuwxw.cc.evil.com/book/1/list1.html', 'https://uuwxw.cc'))

    def test_同域为真(self):
        self.assertTrue(self.uuwxw._同域(
            'https://uuwxw.cc/book/1/list1.html', 'https://uuwxw.cc'))

    def test_端口不同视为不同域(self):
        self.assertFalse(self.uuwxw._同域(
            'https://uuwxw.cc:8443/book/1', 'https://uuwxw.cc'))

    def test_大小写与非法输入(self):
        self.assertTrue(self.uuwxw._同域(
            'HTTPS://UUWXW.CC/book/1', 'https://uuwxw.cc'))
        self.assertFalse(self.uuwxw._同域('', 'https://uuwxw.cc'))
        self.assertFalse(self.uuwxw._同域('not a url', 'https://uuwxw.cc'))


# ====================================================================
# U8 · 内网地址校验不被自己吞掉
# ====================================================================
class Test内网地址校验(unittest.TestCase):

    def setUp(self):
        import ensure_flet_cache
        self.m = ensure_flet_cache

    def test_白名单内的内网IP被拒绝(self):
        """回归: 旧实现把"内网地址"的 raise 和解析失败放同一个 except: pass"""
        原白名单 = self.m._ALLOWED_DL_HOSTS
        try:
            self.m._ALLOWED_DL_HOSTS = {'127.0.0.1', '192.168.1.10'}
            for 地址 in ('http://127.0.0.1/x', 'http://192.168.1.10/x'):
                with self.assertRaises(ValueError) as c:
                    self.m.benchmark_sample(地址, timeout=1)
                self.assertIn('内网地址', str(c.exception))
        finally:
            self.m._ALLOWED_DL_HOSTS = 原白名单

    def test_非白名单域名仍被拒(self):
        with self.assertRaises(ValueError) as c:
            self.m.benchmark_sample('https://example.com/x', timeout=1)
        self.assertIn('非法下载地址', str(c.exception))


# ====================================================================
# U1 · 引擎降级链: 连接级失败也计数
# ====================================================================
class Test引擎降级链(unittest.TestCase):

    def _管理器(self):
        m = 请求引擎.请求引擎管理器()
        m.可用.update({'requests': True, 'curl_cffi': True, 'cloudscraper': True})
        return m

    def test_返回None也计入失败(self):
        """回归: 旧实现只在"拿到响应但非成功"时计数, 连接级失败永不降级"""
        m = self._管理器()
        m._请求_cloudscraper = lambda *a, **k: None
        self.assertIsNone(m.请求('https://example.com/x', 引擎='cloudscraper'))
        self.assertEqual(m._失败计数.get('cloudscraper'), 1)

    def test_连续失败达阈值后切换引擎(self):
        m = self._管理器()
        m._请求_cloudscraper = lambda *a, **k: None
        self.assertEqual(m._选择引擎('waf_js_challenge'), 'cloudscraper')
        for _ in range(m._降级阈值):
            m.请求('https://example.com/x', 引擎='cloudscraper')
        self.assertEqual(m._选择引擎('waf_js_challenge'), 'curl_cffi',
                         'cloudscraper 连续连接级失败后应降级到 curl_cffi')

    def test_成功会清零失败计数(self):
        m = self._管理器()
        m._失败计数['cloudscraper'] = 5
        m._请求_cloudscraper = lambda *a, **k: 请求引擎.引擎响应(
            status_code=200, headers={}, text='ok', content=b'ok',
            url='https://example.com/x', 引擎='cloudscraper')
        m.请求('https://example.com/x', 引擎='cloudscraper')
        self.assertEqual(m._失败计数.get('cloudscraper'), 0)


# ====================================================================
# U15 · 单例并发唯一 + 会话缓存
# ====================================================================
class Test引擎管理器单例(unittest.TestCase):

    def test_并发首调只创建一个实例(self):
        """回归: 旧实现单例初始化无锁, 并发首调会各建一个管理器"""
        原 = 请求引擎._默认管理器
        请求引擎._默认管理器 = None
        try:
            结果 = []
            锁 = threading.Lock()
            开始 = threading.Barrier(16)

            def _取():
                开始.wait(timeout=10)
                x = 请求引擎.获取引擎管理器()
                with 锁:
                    结果.append(id(x))

            ts = [threading.Thread(target=_取) for _ in range(16)]
            for t in ts:
                t.start()
            for t in ts:
                t.join(timeout=20)
            self.assertEqual(len(结果), 16)
            self.assertEqual(len(set(结果)), 1, '并发首调产生了多个管理器实例')
        finally:
            请求引擎._默认管理器 = 原

    def test_会话缓存有锁(self):
        self.assertTrue(hasattr(请求引擎.请求引擎管理器(), '_会话缓存锁'))


# ====================================================================
# U16 / U17 · 历史落盘
# ====================================================================
class Test历史落盘(unittest.TestCase):
    """直接用 __new__ 构造, 绕开单例与真实数据目录 (绝不碰 数据/爬取历史.json)"""

    def _造实例(self, 文件, 数据=None):
        import 爬取历史 as ch
        h = ch.爬取历史.__new__(ch.爬取历史)
        h._file = str(文件)
        h._数据 = 数据 if 数据 is not None else {}
        h._io_lock = threading.Lock()
        h._上次落盘 = 0.0
        h._脏 = False
        h._最小落盘间隔 = 5.0
        return h

    def test_临时文件名带pid(self):
        """回归: 两进程共用 .tmp 会互相截断出损坏文件"""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / '爬取历史.json'
            h = self._造实例(f, {'a.com': {'URLs': {}}})
            h._落盘('{"a.com": {}}')
            self.assertTrue(f.exists())
            self.assertFalse((Path(td) / '爬取历史.json.tmp').exists(),
                             '不应存在不带 pid 的公共 .tmp')

    def test_写前合并磁盘上别的进程写入的新域(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / '爬取历史.json'
            f.write_text(json.dumps({'别的进程.com': {'URLs': {}}},
                                    ensure_ascii=False), encoding='utf-8')
            time.sleep(0.01)          # 保证 mtime 比实例记录的更新
            h = self._造实例(f, {'我的.com': {'URLs': {}}})
            快照 = h._快照(force=True)
            数据 = json.loads(快照)
            self.assertIn('我的.com', 数据)
            self.assertIn('别的进程.com', 数据,
                          '磁盘上另一进程写入的域必须被合并, 不能被整片覆盖')

    def test_自己写入后不回灌自己(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / '爬取历史.json'
            h = self._造实例(f, {'a.com': {'URLs': {}}})
            h._落盘(json.dumps({'a.com': {'URLs': {}}}, ensure_ascii=False))
            磁盘 = json.loads(f.read_text(encoding='utf-8'))
            self.assertEqual(list(磁盘), ['a.com'])


# ====================================================================
# U13 · 摘要兜底 (死分支删除后的行为契约)
# ====================================================================
class Test质检摘要兜底(unittest.TestCase):

    def test_无原因时摘要兜底为综合得分不足(self):
        import 内容质检器
        报告 = 内容质检器.质检报告(章节='第1章', 得分=42.0, 有效=False, 原因=[])
        self.assertIn('综合得分不足', 报告.摘要())
        self.assertIn('第1章', 报告.摘要())

    def test_有原因时优先展示原因(self):
        import 内容质检器
        报告 = 内容质检器.质检报告(章节='第2章', 得分=42.0, 有效=False,
                                原因=['乱码率80%>30%'])
        self.assertIn('乱码率', 报告.摘要())
        self.assertNotIn('综合得分不足', 报告.摘要())


# ====================================================================
# U14 · 人工兜底浏览器工厂注入
# ====================================================================
class Test人工浏览器工厂注入(unittest.TestCase):

    def test_注入成功(self):
        from 爬虫 import 注入人工浏览器工厂

        class 假管理器:
            pass

        m = 假管理器()
        self.assertTrue(注入人工浏览器工厂(m))
        self.assertTrue(callable(m.driver_factory))

    def test_管理器为空返回False(self):
        from 爬虫 import 注入人工浏览器工厂
        self.assertFalse(注入人工浏览器工厂(None))


class TestWAF人工兜底(unittest.TestCase):
    """用户需求: WAF 验证码自动识别 5 次失败 → 可见浏览器人工输入 → cookie 回灌"""

    def test_回灌cookie写入条数与域路径(self):
        import waf_captcha

        class 假Jar:
            def __init__(self):
                self.calls = []

            def set(self, name, value, domain=None, path=None):
                self.calls.append((name, value, domain, path))

        class 假Session:
            def __init__(self):
                self.cookies = 假Jar()

        s = 假Session()
        n = waf_captcha.回灌cookie(s, [
            {'name': 'waform', 'value': 'ok1', 'domain': '.example.com', 'path': '/'},
            {'name': 'uid', 'value': 'u2'},                      # 缺 domain/path
        ])
        self.assertEqual(n, 2)
        self.assertEqual(s.cookies.calls[0], ('waform', 'ok1', '.example.com', '/'))
        self.assertEqual(s.cookies.calls[1][0:2], ('uid', 'u2'))

    def test_回灌cookie空列表与坏条目不抛异常(self):
        import waf_captcha

        class 假Jar:
            def __init__(self):
                self.calls = []

            def set(self, name, value, domain=None, path=None):
                if name == 'bad':
                    raise RuntimeError('模拟 set 失败')
                self.calls.append(name)

        class 假Session:
            def __init__(self):
                self.cookies = 假Jar()

        s = 假Session()
        self.assertEqual(waf_captcha.回灌cookie(s, None), 0)
        self.assertEqual(waf_captcha.回灌cookie(s, []), 0)
        n = waf_captcha.回灌cookie(s, [{'name': 'bad', 'value': 'x'},
                                       {'name': 'good', 'value': 'y'}])
        self.assertEqual(n, 1)          # bad 双路径均失败被跳过, good 正常
        self.assertEqual(s.cookies.calls, ['good'])

    def test_爬虫WAF分支接线了人工兜底(self):
        """防"加了函数没人调": 爬虫 WAF 分支必须调用 solve_waf_captcha_manual"""
        import inspect
        import 爬虫
        源码 = inspect.getsource(爬虫)
        self.assertIn('solve_waf_captcha_manual', 源码,
                      '爬虫 WAF 分支未接线人工兜底')
        self.assertIn('_waf_manual_failed', 源码,
                      '人工兜底缺少每任务一次的弹窗记忆')

    def test_人工兜底模块可导入且签名完备(self):
        import inspect
        import waf_captcha
        sig = inspect.signature(waf_captcha.solve_waf_captcha_manual)
        self.assertIn('session', sig.parameters)
        self.assertIn('url', sig.parameters)
        self.assertEqual(sig.parameters['wait_minutes'].default, 5)


if __name__ == '__main__':
    unittest.main(verbosity=2)
