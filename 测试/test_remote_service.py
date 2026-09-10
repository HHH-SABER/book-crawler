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


if __name__ == '__main__':
    unittest.main(verbosity=2)
