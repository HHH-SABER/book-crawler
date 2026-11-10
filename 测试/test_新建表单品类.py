# -*- coding: utf-8 -*-
"""新建任务表单按内容品类切换（统一内容库改造 C/6, 2026-11-10）。

品类是「表单形态」而不是「页面」：同一个输入条在小说/漫画之间切换字段，
任务表筛选状态不受影响（筛选=漫画时仍可新建小说）。
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(根 / '源码'))

import _path_utils                                     # noqa: E402
from gui_components.input_bar import InputBar          # noqa: E402
from gui_components.task_manager import TaskInfo, TaskManager  # noqa: E402

URL = 'https://example.com/book/123'


def _隔离状态根(case):
    tmp = tempfile.mkdtemp(prefix='cat_form_')
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


class Test表单品类切换(unittest.TestCase):

    def setUp(self):
        _隔离状态根(self)
        self.条 = InputBar(TaskManager(page=None))
        self.条.build()

    # ------------------------------------------------------------ 可见性
    def test_默认小说且漫画字段隐藏(self):
        self.assertEqual(self.条.品类, '小说')
        self.assertTrue(self.条.mode_dropdown.visible)
        self.assertTrue(self.条.resume_switch.visible)
        self.assertTrue(self.条.epub_switch.visible)
        self.assertFalse(self.条.导出格式_dd.visible)
        self.assertFalse(self.条.卷界_input.visible)
        self.assertEqual(self.条.start_chapter.label, '起始章')

    def test_切漫画换字段文案与输出目录(self):
        self.条.设置品类('漫画')
        self.assertEqual(self.条.品类, '漫画')
        self.assertFalse(self.条.mode_dropdown.visible)
        self.assertFalse(self.条.resume_switch.visible)
        self.assertFalse(self.条.epub_switch.visible)
        self.assertFalse(self.条._导入_btn.visible)
        self.assertFalse(self.条._粘贴_btn.visible)
        self.assertTrue(self.条.导出格式_dd.visible)
        self.assertTrue(self.条.start_chapter.visible)
        self.assertEqual(self.条.start_chapter.label, '起始话')
        self.assertEqual(self.条.end_chapter.label, '结束话')
        self.assertEqual(self.条.url_input.label, '漫画详情页URL')
        self.assertEqual(self.条.output_dir_input.value, '抓取结果/漫画')

    def test_逐页不显示卷界_CBZ与PDF显示(self):
        self.条.设置品类('漫画')
        self.assertFalse(self.条.卷界_input.visible)
        for 格式 in ('CBZ', 'PDF'):
            self.条.导出格式_dd.value = 格式
            self.条._刷品类可见性()
            self.assertTrue(self.条.卷界_input.visible, 格式)
        self.条.导出格式_dd.value = '逐页'
        self.条._刷品类可见性()
        self.assertFalse(self.条.卷界_input.visible)

    def test_切回小说完全复原(self):
        self.条.设置品类('漫画')
        self.条.导出格式_dd.value = 'CBZ'
        self.条.卷界_input.value = '8,16'
        self.条.设置品类('小说')
        self.assertTrue(self.条.mode_dropdown.visible)
        self.assertTrue(self.条._导入_btn.visible)
        self.assertFalse(self.条.导出格式_dd.visible)
        self.assertFalse(self.条.卷界_input.visible)
        self.assertEqual(self.条.start_chapter.label, '起始章')
        self.assertEqual(self.条.output_dir_input.value, '抓取结果')
        self.assertFalse(self.条.start_chapter.visible)   # full 模式不带区间

    def test_未知品类或同值被忽略(self):
        self.条.设置品类('文章')
        self.assertEqual(self.条.品类, '小说')
        self.条.设置品类('小说')
        self.assertEqual(self.条.品类, '小说')


class Test漫画任务参数(unittest.TestCase):

    def setUp(self):
        _隔离状态根(self)
        self.条 = InputBar(TaskManager(page=None))
        self.条.build()
        self.条.url_input.value = URL
        self.条.设置品类('漫画')

    def _启动(self):
        """拦截任务创建，返回 (是否调用, kwargs)。"""
        with mock.patch.object(self.条.task_manager, 'create_task',
                               return_value='t1') as m, \
             mock.patch.object(self.条.task_manager, 'select_task'):
            self.条.on_start_click(None)
            if not m.called:
                return False, {}
            return True, m.call_args.kwargs

    def test_漫画恒full且不带小说专属开关(self):
        调用, kw = self._启动()
        self.assertTrue(调用)
        self.assertEqual(kw['品类'], '漫画')
        self.assertEqual(kw['mode'], 'full')
        self.assertFalse(kw['export_epub'])
        self.assertEqual(kw['chapter_range'], None)
        self.assertEqual(kw['品类参数']['导出格式'], 'pages')

    def test_CBZ格式与卷界进入品类参数(self):
        self.条.导出格式_dd.value = 'CBZ'
        self.条.卷界_input.value = '8,16,24'
        调用, kw = self._启动()
        self.assertTrue(调用)
        self.assertEqual(kw['品类参数'],
                         {'导出格式': 'cbz', '卷界': '8,16,24'})

    def test_PDF格式映射(self):
        self.条.导出格式_dd.value = 'PDF'
        _, kw = self._启动()
        self.assertEqual(kw['品类参数']['导出格式'], 'pdf')

    def test_话范围复用区间字段(self):
        self.条.start_chapter.value = '3'
        self.条.end_chapter.value = '9'
        _, kw = self._启动()
        self.assertEqual(kw['chapter_range'], (3, 9))

    def test_话号非法或倒挂被拒(self):
        for 起, 止 in (('abc', '9'), ('0', '9'), ('9', '3')):
            self.条.start_chapter.value = 起
            self.条.end_chapter.value = 止
            调用, _ = self._启动()
            self.assertFalse(调用, f'{起}-{止} 应被拒绝')

    def test_空URL提示按品类区分(self):
        self.条.url_input.value = ''
        调用, _ = self._启动()
        self.assertFalse(调用)

    def test_回调带品类(self):
        收到 = []
        self.条.on_task_created = lambda 品类: 收到.append(品类)
        with mock.patch.object(self.条.task_manager, 'create_task',
                               return_value='t1'), \
             mock.patch.object(self.条.task_manager, 'select_task'):
            self.条.on_start_click(None)
        self.assertEqual(收到, ['漫画'])

    def test_批量入口仅小说(self):
        with mock.patch.object(self.条.task_manager, 'create_task') as m:
            self.条._start_batch([URL])
            self.assertFalse(m.called)
        self.条.设置品类('小说')

    def test_同URL跨品类不复用旧任务(self):
        """小说任务与漫画任务共存：复用分支必须限定品类。"""
        旧 = TaskInfo(task_id='old', url=URL, mode='full',
                      status='completed', 品类='小说')
        self.条.task_manager.tasks['old'] = 旧
        with mock.patch.object(self.条.task_manager, 'create_task',
                               return_value='t1') as m, \
             mock.patch.object(self.条.task_manager, 'restart_task') as r, \
             mock.patch.object(self.条.task_manager, 'select_task'):
            self.条.on_start_click(None)
        self.assertFalse(r.called, '不应重启小说任务')
        self.assertTrue(m.called, '漫画应新建自己的任务')


class Test源码契约(unittest.TestCase):
    """防止后续重构把品类链路悄悄改回硬编码。"""

    def setUp(self):
        self.源码 = (根 / '源码' / 'gui_components' / 'input_bar.py') \
            .read_text(encoding='utf-8')
        self.管理 = (根 / '源码' / 'gui_components' / 'task_manager.py') \
            .read_text(encoding='utf-8')

    def test_查找任务带品类(self):
        self.assertIn('品类: str = None', self.管理)
        self.assertIn('find_task_by_url(url, mode, 品类)', self.源码)

    def test_创建任务带品类(self):
        self.assertIn('品类=品类, 品类参数=品类参数', self.源码)

    def test_可见性收敛到单一函数(self):
        self.assertIn('def _刷品类可见性', self.源码)
        self.assertLessEqual(self.源码.count('导出格式_dd.visible ='), 2)


if __name__ == '__main__':
    unittest.main()
