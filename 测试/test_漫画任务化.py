# -*- coding: utf-8 -*-
"""漫画任务化最小闭环（统一内容库改造 D/6，2026-11-10）。

全部离线：网络、浏览器、导出都被 patch，只验证「接线」是否正确。
核心不变量：小说主链路零改动、漫画可停止/可显示进度、小说专属
bookkeeping（死书清单 / 网站清单）不被漫画污染。
"""
import io
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(根 / '源码'))

import _path_utils                                      # noqa: E402
import 品类执行器                                        # noqa: E402
import 漫画抓取                                          # noqa: E402
import 漫画任务                                          # noqa: E402
from gui_components.task_manager import (               # noqa: E402
    TaskInfo, TaskManager, TaskLogRedirector)

URL = 'https://example.com/book/123'


def _隔离状态根(case):
    tmp = tempfile.mkdtemp(prefix='manga_task_')
    case._旧env = os.environ.get('LOCALAPPDATA')
    case._旧根 = getattr(_path_utils, '_STATE_ROOT', None)
    os.environ['LOCALAPPDATA'] = tmp
    _path_utils._STATE_ROOT = None
    case.addCleanup(lambda: _还原(case, tmp))


def _还原(case, tmp):
    _path_utils._STATE_ROOT = case._旧根
    if case._旧env is None:
        os.environ.pop('LOCALAPPDATA', None)
    else:
        os.environ['LOCALAPPDATA'] = case._旧env
    shutil.rmtree(tmp, ignore_errors=True)


def _漫画任务(**kw):
    参 = dict(task_id='t_manga', url=URL, mode='full', status='pending',
              品类='漫画', 品类参数={'导出格式': 'pages', '卷界': ''})
    参.update(kw)
    return TaskInfo(**参)


class 假管理器:
    """只实现漫画执行器用到的终态入口，避免真实响铃/通知。"""

    def __init__(self):
        self.终态 = []

    def _set_terminal(self, task, status):
        task.status = status
        self.终态.append(status)


class Test执行器注册表(unittest.TestCase):

    def test_漫画已注册_小说不走注册表(self):
        self.assertIn('漫画', 品类执行器.已注册())
        with self.assertRaises(ValueError):
            品类执行器.执行(假管理器(), _漫画任务(品类='小说'), {})

    def test_未知品类明确报错(self):
        with self.assertRaisesRegex(ValueError, '尚未注册执行器'):
            品类执行器.执行(假管理器(), _漫画任务(品类='文章'), {})

    def test_分派到模块的执行函数(self):
        管理器 = 假管理器()
        with mock.patch('漫画任务.执行') as m:
            品类执行器.执行(管理器, _漫画任务(), {'x': 1})
        self.assertTrue(m.called)
        self.assertEqual(m.call_args.args[2]['x'], 1)

    def test_可动态注册新品类而不改TaskManager(self):
        品类执行器.注册('测试品类', '漫画任务')
        try:
            self.assertIn('测试品类', 品类执行器.已注册())
            with mock.patch('漫画任务.执行') as m:
                品类执行器.执行(假管理器(), _漫画任务(品类='测试品类'), {})
            self.assertTrue(m.called)
        finally:
            品类执行器._模块表.pop('测试品类', None)


class Test执行分派不碰小说链路(unittest.TestCase):

    def setUp(self):
        _隔离状态根(self)

    def _跑执行抓取(self, task):
        # 小说分支会真的 import 爬虫并调 run_crawl：拦掉网络，只验证"没被分派"
        with mock.patch('品类执行器.执行') as m, \
             mock.patch('爬虫.run_crawl') as 跑:
            TaskManager._执行抓取(
                object(), task, task.url, task.mode, task.chapter_range,
                None, None, True, None, True, False)
        return m, 跑

    def test_漫画分派且带齐参数(self):
        m, 跑 = self._跑执行抓取(_漫画任务())
        self.assertTrue(m.called)
        self.assertFalse(跑.called, '漫画不得进入小说 run_crawl')
        参数 = m.call_args.args[2]
        self.assertEqual(参数['url'], URL)
        self.assertIn('输出目录', 参数)

    def test_小说仍走原主链路且不分派(self):
        m, 跑 = self._跑执行抓取(TaskInfo(task_id='t_novel', url=URL))
        self.assertFalse(m.called)
        self.assertTrue(跑.called, '小说主链路必须保持原样')

    def test_源码里早退分支在爬虫import之前(self):
        源码 = (根 / '源码' / 'gui_components' / 'task_manager.py') \
            .read_text(encoding='utf-8')
        分支 = 源码.find('from 品类执行器 import 执行 as 执行品类')
        导入 = 源码.find('from 爬虫 import run_crawl, CrawlOptions')
        self.assertGreater(分支, 0)
        self.assertLess(分支, 导入, '小说 import 必须在漫画早退之后')


class Test漫画执行器(unittest.TestCase):

    def setUp(self):
        _隔离状态根(self)
        self.tmp = Path(tempfile.mkdtemp(prefix='manga_out_'))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.管理器 = 假管理器()

    def _执行(self, task, 统计=None):
        默认 = {'书名': '测试漫画', '目录': str(self.tmp / '书'),
                '章节数': 3, '总页数': 30, '新下载': 30, '跳过': 0,
                '已停止': False}
        默认.update(统计 or {})
        with mock.patch('漫画抓取.抓整本', return_value=默认) as 抓, \
             mock.patch('漫画导出.导出') as 导, \
             mock.patch('漫画导出.找话目录', return_value=[1, 2, 3]), \
             mock.patch('漫画导出.解析卷界', return_value=[3]):
            导.return_value = {'册s': [Path('x.cbz')], '输出目录': 'out',
                              '格式': 'cbz'}
            漫画任务.执行(self.管理器, task, {'输出目录': str(self.tmp)})
        return 抓, 导

    def test_成功设标题进度与终态(self):
        task = _漫画任务()
        抓, 导 = self._执行(task)
        self.assertEqual(self.管理器.终态, ['completed'])
        self.assertEqual(task.output_file, str(self.tmp / '书'))
        self.assertEqual(task.progress_current, 3)
        self.assertEqual(task.progress_total, 3)
        self.assertFalse(导.called, '逐页格式不应打包')
        参数 = 抓.call_args.kwargs
        self.assertIsNotNone(参数['停止事件'])
        self.assertTrue(callable(参数['标题回调']))
        # 标题回调立即生效，不等整本跑完
        参数['标题回调']('提前书名')
        self.assertEqual(task.title, '提前书名')

    def test_停止置stopped且保留已完成内容(self):
        task = _漫画任务()
        抓, 导 = self._执行(task, {'已停止': True})
        self.assertEqual(self.管理器.终态, ['stopped'])
        self.assertFalse(导.called)

    def test_CBZ按卷导出(self):
        task = _漫画任务(品类参数={'导出格式': 'cbz', '卷界': '3'})
        _, 导 = self._执行(task)
        self.assertTrue(导.called)
        self.assertEqual(导.call_args.kwargs['单位'], '卷')
        self.assertEqual(导.call_args.kwargs['卷界'], [3])

    def test_PDF按话导出_无卷界(self):
        task = _漫画任务(品类参数={'导出格式': 'pdf', '卷界': ''})
        _, 导 = self._执行(task)
        self.assertEqual(导.call_args.kwargs['单位'], '话')
        self.assertFalse(导.call_args.kwargs['写索引'])

    def test_异常向上抛给任务收尾(self):
        task = _漫画任务()
        with mock.patch('漫画抓取.抓整本', side_effect=RuntimeError('站点挂了')):
            with self.assertRaisesRegex(RuntimeError, '站点挂了'):
                漫画任务.执行(self.管理器, task, {'输出目录': str(self.tmp)})
        self.assertEqual(self.管理器.终态, [])


class Test漫画路径契约(unittest.TestCase):

    def test_站点配置优先取BASE_DIR而非模块目录(self):
        """打包后 __file__ 指向 _MEIPASS，必须靠 get_app_base_dir()。"""
        临时 = Path(tempfile.mkdtemp(prefix='manga_cfg_'))
        try:
            配 = 临时 / '站点适配_本地' / '漫画站点.json'
            配.parent.mkdir(parents=True, exist_ok=True)
            配.write_text('{}', encoding='utf-8')
            with mock.patch('_path_utils.get_app_base_dir', return_value=str(临时)), \
                 mock.patch('_path_utils.get_resource_dir',
                            return_value=str(临时 / 'none')):
                self.assertEqual(漫画抓取.站点配置路径(), 配)
        finally:
            shutil.rmtree(临时, ignore_errors=True)

    def test_源码态能定位到真实私有配置(self):
        路径 = 漫画抓取.站点配置路径()
        self.assertEqual(路径.name, '漫画站点.json')
        self.assertEqual(路径.parent.name, '站点适配_本地')

    def test_CLI默认输出根不再硬编码项目根(self):
        源码 = (根 / '源码' / '漫画抓取.py').read_text(encoding='utf-8')
        self.assertIn('get_default_output_dir()', 源码)
        self.assertNotIn("parent.parent / '抓取结果' / '漫画'", 源码)


class Test漫画抓取可停止(unittest.TestCase):

    def test_下载时停止事件已置位不发请求(self):
        事件 = threading.Event()
        事件.set()
        会话 = mock.Mock()
        会话.get = mock.Mock(side_effect=AssertionError('不应发请求'))
        成功, 跳过 = 漫画抓取.下载章节图片(
            ['https://a.invalid/1.jpg'], Path(tempfile.gettempdir()),
            会话, URL, 0, None, 停止事件=事件)
        self.assertEqual((成功, 跳过), (0, 0))
        self.assertFalse(会话.get.called)

    def test_抓整本停止标志进入统计(self):
        事件 = threading.Event()
        事件.set()
        站 = mock.Mock(需渲染=False)
        临时根 = Path(tempfile.mkdtemp(prefix='manga_stop_'))
        try:
            with mock.patch('漫画抓取.识别站点', return_value='x'), \
                 mock.patch('漫画抓取.加载站点表', return_value={'x': 站}), \
                 mock.patch('漫画抓取.解析章节列表', return_value=[
                     mock.Mock(序号=1, 标题='第1话', url=URL + '/1')]), \
                 mock.patch('漫画抓取.requests.Session.get') as g:
                g.return_value = mock.Mock(text='<title>测试</title>')
                统计 = 漫画抓取.抓整本(
                    URL, 临时根, 日志=lambda m: None, 停止事件=事件)
        finally:
            shutil.rmtree(临时根, ignore_errors=True)
        self.assertTrue(统计['已停止'])
        self.assertEqual(统计['新下载'], 0)


class Test漫画进度解析(unittest.TestCase):

    def setUp(self):
        _隔离状态根(self)
        self.task = _漫画任务()
        self.r = TaskLogRedirector(self.task, io.StringIO())

    def test_章节总数(self):
        self.r._解析漫画进度('[章节] 共 47 话')
        self.assertEqual(self.task.progress_total, 47)
        self.assertEqual(self.task.progress_current, 0)

    def test_逐话进度(self):
        self.r._解析漫画进度('[第3/47话] 21 页 → 新下 21, 跳过 0')
        self.assertEqual((self.task.progress_current, self.task.progress_total),
                         (3, 47))

    def test_小说正则不误伤漫画日志(self):
        self.r._parse_progress('[章节] 共 47 话')
        self.assertEqual(self.task.progress_total, 47)

    def test_书名日志补标题(self):
        self.r._解析漫画进度('[书名] 测试漫画')
        self.assertEqual(self.task.title, '测试漫画')


class Test线程级闭环(unittest.TestCase):
    """不走方法级 mock：真的起一个任务线程，验证整条链能跑通。"""

    def setUp(self):
        _隔离状态根(self)

    def test_创建漫画任务能跑完并到completed(self):
        import time
        临时 = Path(tempfile.mkdtemp(prefix='manga_e2e_'))
        self.addCleanup(lambda: shutil.rmtree(临时, ignore_errors=True))
        mgr = TaskManager(page=None)

        def 假抓取(详情url, 输出根, **kw):
            print('[章节] 共 2 话', flush=True)
            print('[第1/2话] 10 页 → 新下 10, 跳过 0', flush=True)
            kw['标题回调']('集成测试漫画')
            return {'书名': '集成测试漫画', '目录': str(临时 / '书'),
                    '章节数': 2, '总页数': 20, '新下载': 20, '跳过': 0,
                    '已停止': False}

        # patch 必须覆盖到线程跑完：create_task 只启动线程就返回
        with mock.patch('漫画抓取.抓整本', side_effect=假抓取), \
             mock.patch('界面偏好.取', return_value=False):
            tid = mgr.create_task(url=URL, mode='full', 品类='漫画',
                                  品类参数={'导出格式': 'pages', '卷界': ''},
                                  output_dir=str(临时))
            任务 = mgr.tasks[tid]
            for _ in range(100):
                if 任务.status in ('completed', 'failed', 'stopped',
                                   'dead_pending'):
                    break
                time.sleep(0.05)
        self.assertEqual(任务.status, 'completed', f'错误: {任务.error}')
        self.assertEqual(任务.title, '集成测试漫画')
        self.assertEqual(任务.progress_total, 2)
        self.assertTrue(any('共 2 话' in 行['msg'] for 行 in 任务.logs),
                        '漫画日志应进统一任务日志')
        # 死书清单/网站清单未被写入
        self.assertIsNone(getattr(任务, 'dead', None))

    def test_漫画任务可被停止(self):
        import time
        临时 = Path(tempfile.mkdtemp(prefix='manga_stop_e2e_'))
        self.addCleanup(lambda: shutil.rmtree(临时, ignore_errors=True))
        mgr = TaskManager(page=None)
        开始 = threading.Event()

        def 假抓取(详情url, 输出根, **kw):
            开始.set()
            kw['停止事件'].wait(timeout=5)
            return {'书名': '停', '目录': str(临时 / '书'), '章节数': 1,
                    '总页数': 1, '新下载': 1, '跳过': 0, '已停止': True}

        with mock.patch('漫画抓取.抓整本', side_effect=假抓取), \
             mock.patch('界面偏好.取', return_value=False):
            tid = mgr.create_task(url='https://example.org/book/9',
                                  mode='full', 品类='漫画',
                                  output_dir=str(临时))
            任务 = mgr.tasks[tid]
            self.assertTrue(开始.wait(timeout=5), '抓取线程未启动')
            mgr.stop_task(tid)
            for _ in range(100):
                if 任务.status in ('stopped', 'completed', 'failed'):
                    break
                time.sleep(0.05)
            self.assertEqual(任务.status, 'stopped')


class Test小说bookkeeping不被污染(unittest.TestCase):

    def setUp(self):
        _隔离状态根(self)
        self.mgr = TaskManager(page=None)

    def test_漫画成功不写死书清单与网站清单(self):
        with mock.patch('死书处理.标记已恢复') as 死, \
             mock.patch('网站清单.记录') as 站:
            self.mgr._收尾成功(_漫画任务(), URL)
        self.assertFalse(死.called)
        self.assertFalse(站.called)

    def test_小说成功仍走原收尾(self):
        with mock.patch('死书处理.标记已恢复', return_value={'移除': False}) as 死, \
             mock.patch('网站清单.记录') as 站, \
             mock.patch('网站清单.域名网站名', return_value='x'):
            self.mgr._收尾成功(TaskInfo(task_id='n', url=URL), URL)
        self.assertTrue(死.called)
        self.assertTrue(站.called)

    def test_漫画失败不进死书清单(self):
        with mock.patch('死书处理.记录死书') as 记:
            self.mgr._记死书(_漫画任务(), RuntimeError('普通失败'))
        self.assertFalse(记.called)


if __name__ == '__main__':
    unittest.main()
