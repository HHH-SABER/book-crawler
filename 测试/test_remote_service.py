# -*- coding: utf-8 -*-
"""远控服务 API 单测: TestClient 进程内验证, 不起真实爬虫/不联网。

运行方式 (项目根目录):
    python -m unittest discover -s 测试 -v
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '源码'))
sys.path.insert(0, str(_PROJECT_ROOT / '测试'))

import _沙箱                              # noqa: E402,F401  状态根沙箱 (2026-10-02)
from 远控 import 服务   # noqa: E402


def _client():
    """每个用例独立 TestClient + 固定 token 配置 (绕过磁盘配置)"""
    服务._CONFIG = None
    patcher = mock.patch.object(服务, '取配置',
                                return_value={'token': 'testtoken',
                                              '端口': 0, '绑定': '127.0.0.1'})
    patcher.start()
    from fastapi.testclient import TestClient
    return TestClient(服务.app), patcher


class Test远控服务(unittest.TestCase):
    def setUp(self):
        self.client, self._patcher = _client()
        self.addCleanup(self._patcher.stop)
        # 清空服务内 TaskManager 单例的任务表
        self.mgr = 服务._任务管理器()
        self.mgr.tasks.clear()

    # ------------------------------------------------------------ 鉴权
    def test_无token_401(self):
        self.assertEqual(self.client.get('/api/v1/tasks').status_code, 401)

    def test_错误token_401(self):
        self.assertEqual(
            self.client.get('/api/v1/tasks?k=wrong').status_code, 401)

    def test_正确token_200_and_healthz免鉴权(self):
        self.assertEqual(
            self.client.get('/api/v1/tasks?k=testtoken').status_code, 200)
        self.assertEqual(self.client.get('/api/v1/healthz').status_code, 200)

    # ------------------------------------------------------------ 任务
    def test_空任务列表(self):
        r = self.client.get('/api/v1/tasks?k=testtoken')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {'任务': []})

    def test_注入任务后列表可见(self):
        from gui_components.task_manager import TaskInfo
        t = TaskInfo(task_id='t1', url='https://example.com/b/1',
                     title='测试书', status='running')
        t.progress_current, t.progress_total = 3, 10
        self.mgr.tasks['t1'] = t
        r = self.client.get('/api/v1/tasks?k=testtoken').json()
        self.assertEqual(len(r['任务']), 1)
        snap = r['任务'][0]
        self.assertEqual(snap['id'], 't1')
        self.assertEqual(snap['进度'], [3, 10])

    def test_发任务_非法URL_400且不建任务(self):
        r = self.client.post('/api/v1/tasks?k=testtoken',
                             json={'url': 'http://127.0.0.1/x'})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(len(self.mgr.tasks), 0, '非法 URL 不得创建任务')

    def test_发任务_合法URL_走create_task(self):
        with mock.patch.object(self.mgr, 'create_task',
                               return_value='task_9') as m:
            r = self.client.post('/api/v1/tasks?k=testtoken',
                                 json={'url': 'https://example.com/b/1',
                                       'mode': 'test', 'resume': False})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json(), {'task_id': 'task_9'})
            m.assert_called_once()
            self.assertEqual(m.call_args.kwargs.get('mode'), 'test')
            self.assertIs(m.call_args.kwargs.get('resume'), False)

    def test_发任务_缺url_400(self):
        r = self.client.post('/api/v1/tasks?k=testtoken', json={})
        self.assertEqual(r.status_code, 400)

    def test_发任务_增量透传(self):
        """EXE 批量(增量模式): body.incremental 必须透传给 create_task;
        且 incremental=True 时 unique_title 默认 False —— 增量语义是续写原文件,
        True 会另存 书名(1).txt 使旧正文无法参与增量搬运 (书架曾出现 (1) 后缀混淆)。"""
        with mock.patch.object(self.mgr, 'create_task',
                               return_value='task_10') as m:
            r = self.client.post('/api/v1/tasks?k=testtoken',
                                 json={'url': 'https://example.com/b/10',
                                       'incremental': True})
            self.assertEqual(r.status_code, 200)
            self.assertIs(m.call_args.kwargs.get('incremental'), True)
            self.assertIs(m.call_args.kwargs.get('unique_title'), False,
                          '增量任务默认 unique_title=False (续写原文件)')

    def test_发任务_默认非增量(self):
        """不传 incremental → False, 既有调用方行为零变化。"""
        with mock.patch.object(self.mgr, 'create_task',
                               return_value='task_11') as m:
            self.client.post('/api/v1/tasks?k=testtoken',
                             json={'url': 'https://example.com/b/11'})
            self.assertIs(m.call_args.kwargs.get('incremental'), False)
            self.assertIs(m.call_args.kwargs.get('unique_title'), True,
                          '非增量保持原默认 unique_title=True')

    def test_发任务_增量但显式unique_title优先(self):
        with mock.patch.object(self.mgr, 'create_task',
                               return_value='task_12') as m:
            self.client.post('/api/v1/tasks?k=testtoken',
                             json={'url': 'https://example.com/b/12',
                                   'incremental': True, 'unique_title': True})
            self.assertIs(m.call_args.kwargs.get('incremental'), True)
            self.assertIs(m.call_args.kwargs.get('unique_title'), True,
                          '显式传入优先于增量默认')

    def test_日志增量与截断标志(self):
        from gui_components.task_manager import TaskInfo
        t = TaskInfo(task_id='t2', url='https://example.com/b/2')
        t.logs.extend([{'time': '0', 'msg': f'行{i}'} for i in range(5)])
        self.mgr.tasks['t2'] = t
        r = self.client.get('/api/v1/tasks/t2/logs?after=3&k=testtoken').json()
        self.assertEqual(r['total'], 5)
        self.assertEqual(len(r['entries']), 2)
        self.assertFalse(r['截断'])
        # after 超界 (如日志被 500 条截断) → 从 0 重发并置截断
        r2 = self.client.get('/api/v1/tasks/t2/logs?after=999&k=testtoken').json()
        self.assertTrue(r2['截断'])
        self.assertEqual(len(r2['entries']), 5)

    def test_发任务_标记来源为手机(self):
        """远控页按 来源=手机 过滤展示 — API 创建的任务必须带标记"""
        from gui_components.task_manager import TaskInfo

        def _建并返回(url, **kw):
            t = TaskInfo(task_id='src_1', url=url)
            self.mgr.tasks['src_1'] = t
            return 'src_1'
        with mock.patch.object(self.mgr, 'create_task', side_effect=_建并返回):
            r = self.client.post('/api/v1/tasks?k=testtoken',
                                 json={'url': 'https://example.com/b/3'})
            self.assertEqual(r.status_code, 200)
        self.assertEqual(self.mgr.tasks['src_1'].来源, '手机')

    def test_停止不存在任务_404(self):
        self.assertEqual(
            self.client.post('/api/v1/tasks/nope/stop?k=testtoken').status_code,
            404)

    # ------------------------------------------------------------ 书架
    def setUp_books(self, tmp: Path):
        (tmp / '测试书.txt').write_text(
            '## 第一章\n\n内容一。\n\n## 第二章\n\n内容二。\n', encoding='utf-8')
        return mock.patch.object(服务, 'get_default_output_dir',
                                 lambda: str(tmp))

    def test_书架列表(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with self.setUp_books(tmp):
                r = self.client.get('/api/v1/books?k=testtoken').json()
            self.assertEqual(len(r['书籍']), 1)
            b = r['书籍'][0]
            self.assertEqual(b['标题'], '测试书')
            self.assertNotIn('路径', b, '服务器路径不得泄露给客户端')

    def test_epub下载_按id反查_错误id_404(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with self.setUp_books(tmp):
                books = self.client.get(
                    '/api/v1/books?k=testtoken').json()['书籍']
                bid = books[0]['id']
                r = self.client.get(f'/api/v1/books/{bid}/epub?k=testtoken')
                self.assertEqual(r.status_code, 200)
                self.assertIn('epub', r.headers.get('content-type', ''))
                self.assertGreater(len(r.content), 100)
                r404 = self.client.get(
                    '/api/v1/books/deadbeefdead/epub?k=testtoken')
                self.assertEqual(r404.status_code, 404)

    # ------------------------------------------------------------ 二期: 阅读
    def test_章节列表与内容(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with self.setUp_books(tmp):
                bid = self.client.get(
                    '/api/v1/books?k=testtoken').json()['书籍'][0]['id']
                ch = self.client.get(
                    f'/api/v1/books/{bid}/chapters?k=testtoken').json()
                self.assertEqual(ch['总章数'], 2)
                self.assertEqual(ch['进度'], 0)
                self.assertEqual(ch['章节'][1]['标题'], '第二章')
                c0 = self.client.get(
                    f'/api/v1/books/{bid}/content/0?k=testtoken').json()
                self.assertEqual(c0['标题'], '第一章')
                self.assertIn('内容一', c0['内容'])
                r404 = self.client.get(
                    f'/api/v1/books/{bid}/content/99?k=testtoken')
                self.assertEqual(r404.status_code, 404)

    def test_阅读进度存取(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with self.setUp_books(tmp):
                bid = self.client.get(
                    '/api/v1/books?k=testtoken').json()['书籍'][0]['id']
                r = self.client.post(
                    f'/api/v1/books/{bid}/progress?k=testtoken',
                    json={'章节': 1})
                self.assertEqual(r.status_code, 200)
                r2 = self.client.get(
                    f'/api/v1/books/{bid}/progress?k=testtoken')
                self.assertEqual(r2.json(), {'章节': 1})
                r3 = self.client.post(
                    f'/api/v1/books/{bid}/progress?k=testtoken',
                    json={'章节': -5})
                self.assertEqual(r3.status_code, 400)

    def test_中断任务恢复_列表可见并可删除(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / '某书.txt.checkpoint.json').write_text(
                '{"catalog_url": "https://example.com/b/9", '
                '"completed": 7, "total": 20}', encoding='utf-8')
            with mock.patch.object(服务, 'get_default_output_dir',
                                   lambda: str(td)):
                self.mgr.tasks.clear()
                服务._已扫中断 = False        # 允许重扫 (服务启动后只扫一次)
                r = self.client.get('/api/v1/tasks?k=testtoken').json()
                恢复项 = [t for t in r['任务'] if t['id'].startswith('resume_')]
                self.assertEqual(len(恢复项), 1)
                t = 恢复项[0]
                self.assertEqual(t['状态'], 'interrupted')
                self.assertEqual(t['进度'], [7, 20])
                self.assertEqual(t['url'], 'https://example.com/b/9')
                # 清理: DELETE 移除展示项
                self.assertEqual(
                    self.client.delete(
                        f"/api/v1/tasks/{t['id']}?k=testtoken").status_code, 200)
                self.assertNotIn(t['id'], self.mgr.tasks)
                服务._已扫中断 = True   # 还原, 免污染其他用例

    def test_删除运行中任务_拒绝(self):
        from gui_components.task_manager import TaskInfo
        t = TaskInfo(task_id='t9', url='https://example.com/b/9',
                     status='running')
        self.mgr.tasks['t9'] = t
        self.assertEqual(
            self.client.delete('/api/v1/tasks/t9?k=testtoken').status_code,
            404)

    # ------------------------------------------------------------ 三期: 推送
    def test_终态推送_触发一次且去重_中断项不推(self):
        import time as _t
        from gui_components.task_manager import TaskInfo
        已发 = []
        with mock.patch.object(服务, '_发送推送',
                               lambda 标题, 内容: 已发.append((标题, 内容))):
            # 1) running → completed 的翻转: 推一次, 二次扫描去重
            t = TaskInfo(task_id='p1', url='https://example.com/b/1',
                         title='某书', status='running')
            t.progress_current, t.progress_total = 10, 10
            t.metrics.end_time = _t.time()          # _set_terminal 的痕迹
            t.status = 'completed'
            self.mgr.tasks['p1'] = t
            服务._已推终态.clear()
            fired = 服务._扫描终态()
            self.assertEqual(fired, [('p1', 'completed')])
            self.assertEqual(len(已发), 1)
            self.assertIn('某书', 已发[0][0])
            self.assertEqual(服务._扫描终态(), [], '重复扫描不得重复推送')
            # 2) 启动恢复的 interrupted (end_time=0) 不推
            r = TaskInfo(task_id='resume_x', url='https://example.com/b/2',
                         title='旧书', status='interrupted')
            self.mgr.tasks['resume_x'] = r
            self.assertEqual(服务._扫描终态(), [], 'interrupted 项不得触发推送')
            self.assertEqual(len(已发), 1)


    def test_章节缓存并发淘汰不抛异常(self):
        """并发读章节时缓存淘汰须互斥。

        回归背景: 旧实现在 len(_章节缓存) > 8 时执行
        pop(next(iter(_章节缓存))), len() 与 pop 之间无锁 — 另一线程把缓存
        清空后 next(iter({})) 抛 StopIteration, 或迭代中被改抛 RuntimeError,
        两者都没被捕获 → 阅读页 500。
        """
        import tempfile
        import threading
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            items = []
            for i in range(12):     # 12 > 缓存上限 8, 必然触发淘汰
                p = tmp / f'b{i}.txt'
                p.write_text('## 第一章\n\n内容。\n', encoding='utf-8')
                items.append({'路径': str(p), '标题': f'b{i}'})
            with 服务._章节缓存锁:
                服务._章节缓存.clear()
            self.addCleanup(服务._章节缓存.clear)

            errs = []

            def _work():
                try:
                    for it in items:
                        服务._解析章节(it)
                except Exception as e:          # noqa: BLE001
                    errs.append(f'{type(e).__name__}: {e}')

            ts = [threading.Thread(target=_work) for _ in range(6)]
            for t in ts:
                t.start()
            for t in ts:
                t.join(timeout=20)
            self.assertEqual(errs, [])
            self.assertLessEqual(len(服务._章节缓存), 8)


class Test远控开关与生命周期(unittest.TestCase):
    """v2.4.3 新增: 开关后端 (保存配置/设置启用) 与 服务生命周期。

    实起真实 uvicorn (8763 端口) 验证 运行中/healthz/停止 全链路 —
    mock 内部状态测不出"停止后端口真的释放"。"""

    def setUp(self):
        from 远控 import 服务
        import socket as _sock
        self.服务 = 服务
        self.addCleanup(服务.停止后台)
        服务._server = None
        服务._server_thread = None
        # 随机空闲端口: 固定端口会被上轮测试客户端的 TIME_WAIT 残留咬住
        # (Windows 下监听套接字无法绑定含 TIME_WAIT 的端口 → WinError 10048)
        _s = _sock.socket()
        _s.bind(('127.0.0.1', 0))
        self.端口 = _s.getsockname()[1]
        _s.close()
        self._cfg = mock.patch.object(
            服务, '取配置',
            return_value={'token': 'testtoken', '启用': True,
                          '端口': self.端口, '绑定': '127.0.0.1'})
        self._cfg.start()
        self.addCleanup(self._cfg.stop)

    def test_设置启用_写盘与内存同步(self):
        import json as _j
        import tempfile
        from 远控 import 配置
        with tempfile.TemporaryDirectory() as td:
            cfg_file = td + '/cfg.json'
            with mock.patch.object(配置, '_配置路径', lambda: cfg_file), \
                    mock.patch.object(配置, '_CONFIG',
                                      {'token': 't', '启用': True}):
                self.assertTrue(配置.设置启用(False))
                self.assertFalse(配置.取配置()['启用'], '内存单例未同步')
                with open(cfg_file, encoding='utf-8') as f:
                    self.assertFalse(_j.load(f)['启用'], '未写盘')

    def test_禁用时后台启动返回None(self):
        with mock.patch.object(self.服务, '取配置',
                               return_value={'启用': False}):
            self.assertIsNone(self.服务.后台启动())

    def _等健康(self, 端口: int, 上限秒=15) -> bool:
        """轮询 healthz 直到可访问 — 不假设'线程活着'等于'端口已绑定'
        (uvicorn 冷启动导入+绑定需数秒, 固定 sleep/早打请求都会假失败)"""
        import time as _t
        import urllib.request as _u
        for _ in range(int(上限秒 * 2)):
            try:
                r = _u.urlopen(f'http://127.0.0.1:{端口}/api/v1/healthz',
                               timeout=2)
                if r.status == 200:
                    return True
            except Exception:
                pass
            _t.sleep(0.5)
        return False

    def test_启动_运行中_healthz_停止_再启动(self):
        import time as _t
        self.assertIsNotNone(self.服务.后台启动(), '启动未返回线程')
        self.assertTrue(self._等健康(self.端口), '服务未在 15s 内可访问')
        self.assertTrue(self.服务.运行中())
        # 已在运行: 重复启动应被拒绝 (防双绑定)
        self.assertIsNone(self.服务.后台启动())
        # 关 → 线程退出 (端口释放由 asyncio 收尾; 不再裸 bind 探测,
        #  自身客户端连接的 TIME_WAIT 会让该探测假失败)
        self.服务.停止后台()
        for _ in range(24):
            if not self.服务.运行中():
                break
            _t.sleep(0.5)
        self.assertFalse(self.服务.运行中(), '停止后 运行中() 应为 False')
        # 关 → 开 再来一次 (开关切换路径)。换新随机端口: Windows 下快速重绑
        # 同一端口可能撞上本测试自身客户端连接的 TIME_WAIT (OS 语义, 与开关无关)
        import socket as _sock
        _s2 = _sock.socket()
        _s2.bind(('127.0.0.1', 0))
        端口2 = _s2.getsockname()[1]
        _s2.close()
        self.assertIsNotNone(self.服务.后台启动(port=端口2))
        self.assertTrue(self._等健康(端口2), '重启后服务未可访问')


class Test推送Scheme校验(unittest.TestCase):
    """_发送推送 的推送服务器地址仅允许 http/https (2026-09-26 加固)。

    远控配置的 bark/ntfy 地址可经配置 API 写入, 任意 scheme 会扩大
    urllib.urlopen 的攻击面 (file:// 等); 限 http/https 不影响自建
    局域网推送 (内网 http 地址仍放行)。
    """

    def _发(self, bark地址=None, ntfy服务器=None):
        cfg = {'推送': {}}
        if bark地址 is not None:
            cfg['推送']['bark'] = {'启用': True, '地址': bark地址}
        if ntfy服务器 is not None:
            cfg['推送']['ntfy'] = {'启用': True, '主题': 'books',
                                   '服务器': ntfy服务器}
        with mock.patch.object(服务, '取配置', return_value=cfg), \
                mock.patch('requests.get') as mget, \
                mock.patch('requests.post') as mpost:
            服务._发送推送('标题', '内容')
            return mget, mpost

    def test_非http_scheme拒绝且不发请求(self):
        mget, mpost = self._发(bark地址='ftp://192.0.2.1/x',
                               ntfy服务器='file:///tmp/x')
        mget.assert_not_called()
        mpost.assert_not_called()

    def test_内网字面IP拒绝且不发请求(self):
        """validate_public_url 边界: 私网字面 IP 的推送地址不发请求"""
        mget, mpost = self._发(bark地址='http://192.168.1.5:2586/x')
        mget.assert_not_called()
        mpost.assert_not_called()

    def test_http与https公网地址放行(self):
        mget, mpost = self._发(bark地址='https://bark.example.com/',
                               ntfy服务器='http://ntfy.example.com:8080')
        self.assertEqual(1, mget.call_count, 'bark 渠道应发起请求')
        self.assertEqual(1, mpost.call_count, 'ntfy 渠道应发起请求')


class Test教程端点与md转换(unittest.TestCase):
    """/tutorial 教程页 (2026-09-29 教程入 UI) 与 _md转html 极简转换"""

    def setUp(self):
        self.client, self._patcher = _client()
        self.addCleanup(self._patcher.stop)

    def test_tutorial端点200且含教程标题(self):
        """源码环境直接读 文档/远控使用教程.md"""
        r = self.client.get('/tutorial?k=testtoken')
        self.assertEqual(r.status_code, 200)
        self.assertIn('text/html', r.headers['content-type'])
        # 教程 md 的一级标题应出现在渲染结果中
        self.assertIn('远控使用教程', r.text)

    def test_tutorial需鉴权(self):
        """2026-10-07 起 /tutorial 纳入鉴权 (回归用例)。

        改动背景: 服务默认绑定 0.0.0.0 (同 Wi-Fi 可达), 而教程正文会讲出配置
        文件路径、token 存放位置、默认端口与绑定 —— 是原先三个免鉴权端点里唯一
        泄露**运维细节**的一个。面板外壳 `/` 不含凭据且要承担"手机首次访问入口"
        职责, 故保持免鉴权; healthz 只回 ok+时间戳, 留给看门狗。
        ⚠️ 本用例原先叫 test_tutorial免鉴权 且断言 200 —— 属**有意变更**,
        不是被顺手改绿 (GUI「使用教程」按钮与面板链接已同步带上 ?k=)。
        """
        self.assertEqual(self.client.get('/tutorial').status_code, 401,
                         '不带 token 必须 401')
        self.assertEqual(self.client.get('/tutorial?k=wrong').status_code, 401,
                         '错误 token 必须 401')
        self.assertEqual(self.client.get('/tutorial?k=testtoken').status_code, 200)

    def test_面板与healthz仍免鉴权(self):
        """只有这两处免鉴权: 面板外壳 (手机首次访问入口) 与 healthz (看门狗)。"""
        self.assertEqual(self.client.get('/').status_code, 200,
                         '面板外壳必须免鉴权, 否则手机首次访问无从输入 token')
        self.assertEqual(self.client.get('/api/v1/healthz').status_code, 200)

    def test_面板教程链接带token(self):
        """面板的「📖 使用教程」是 <a target=_blank>, 发不出 Authorization 头 ——
        必须由 JS 拼 ?k=, 否则点开就是 401 (收紧 /tutorial 时最容易漏的一环)。"""
        html = (Path(服务.__file__).parent / '面板.html').read_text(encoding='utf-8')
        self.assertIn("id=\"教程链接\"", html, '教程链接缺 id, JS 找不到它')
        self.assertIn("/tutorial?k=", html, '面板未给教程链接拼 token')
        self.assertIn('同步教程链接', html, '缺同步函数')
        # 登录成功与启动各要同步一次 (否则"先登录再看教程"仍是旧 href)
        self.assertGreaterEqual(html.count('同步教程链接();'), 2,
                                '至少要在 提交token() 与启动处各调一次')

    def test_md转html_标题与段落(self):
        html = 服务._md转html('# 一级\n\n正文段落\n## 二级\n### 三级')
        self.assertIn('<h1>一级</h1>', html)
        self.assertIn('<p>正文段落</p>', html)
        self.assertIn('<h2>二级</h2>', html)
        self.assertIn('<h3>三级</h3>', html)

    def test_md转html_列表与代码块与表格(self):
        md = ('- 项目甲\n- 项目乙\n\n'
              '```\ncode line\n```\n\n'
              '| 列1 | 列2 |\n|---|---|\n| a | b |\n\n'
              '这是 **加粗** 和 `内联码`\n')
        html = 服务._md转html(md)
        self.assertIn('<ul>', html)
        self.assertIn('<li>项目甲</li>', html)
        self.assertIn('<li>项目乙</li>', html)
        self.assertIn('</ul>', html)
        self.assertIn('<pre><code>\ncode line\n</code></pre>', html)
        self.assertIn('<th>列1</th>', html)
        self.assertIn('<td>a</td>', html)
        self.assertIn('<b>加粗</b>', html)
        self.assertIn('<code>内联码</code>', html)

    def test_md转html_防注入(self):
        """HTML 特殊字符先转义, 站点内容中的标签不会变成活标记"""
        html = 服务._md转html('<script>alert(1)</script>')
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)

    def test_md转html_表格分隔行跳过(self):
        html = 服务._md转html('| a | b |\n|---|---|\n| 1 | 2 |')
        self.assertIn('<th>a</th>', html)
        self.assertIn('<td>1</td>', html)
        self.assertNotIn('<td>---</td>', html)


class Test桌面教程入口(unittest.TestCase):
    """远控页"使用教程"按钮 (2026-09-29 用户反馈 EXE 里找不到使用说明):
    运行中 → 系统浏览器打开 <本机地址>/tutorial; 未启用 → toast 提示不发 open"""

    def setUp(self):
        from gui_components.pages.remote_page import RemotePage
        self.rp = RemotePage()
        self.rp.build()

    def test_运行中打开教程页(self):
        """2026-10-07: /tutorial 需鉴权 → GUI 入口必须带上 ?k=<token>"""
        self.rp.取信息 = lambda: {'运行': True,
                                 '地址': 'http://127.0.0.1:8760/', 'token': 'x'}
        with mock.patch('webbrowser.open') as op:
            self.rp._open_tutorial(None)
        op.assert_called_once_with('http://127.0.0.1:8760/tutorial?k=x')

    def test_运行中但取不到token_提示且不开浏览器(self):
        """取不到 token 时打开只会得到 401 页 → 改成给一句能查的话"""
        self.rp.取信息 = lambda: {'运行': True,
                                 '地址': 'http://127.0.0.1:8760/', 'token': ''}
        with mock.patch('webbrowser.open') as op, \
                mock.patch.object(self.rp, '_toast') as tt:
            self.rp._open_tutorial(None)
        op.assert_not_called()
        tt.assert_called_once()

    def test_未启用时提示且不开浏览器(self):
        self.rp.取信息 = lambda: {'运行': False, '地址': '', 'token': ''}
        with mock.patch('webbrowser.open') as op, \
                mock.patch.object(self.rp, '_toast') as tt:
            self.rp._open_tutorial(None)
        op.assert_not_called()
        tt.assert_called_once()

    def test_取信息异常走未启用分支(self):
        def _炸():
            raise RuntimeError('信息源炸了')
        self.rp.取信息 = _炸
        with mock.patch('webbrowser.open') as op, \
                mock.patch.object(self.rp, '_toast') as tt:
            self.rp._open_tutorial(None)
        op.assert_not_called()
        tt.assert_called_once()


if __name__ == '__main__':
    unittest.main(verbosity=2)
