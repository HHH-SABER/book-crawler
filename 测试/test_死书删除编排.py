# -*- coding: utf-8 -*-
"""死书删除编排回归 (2026-10-02 新增, 站点脱钩: 纯占位域 + 沙箱隔离)。

锁定 删除书记录() 的编排契约:
  三项独立执行/子集范围/任务项恒 delete_file=False (产物安全)/
  单项异常不阻断其余/幂等/绝不动 爬取历史 与 站点历史。
运行: python -m unittest discover -s 测试
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))
sys.path.insert(0, str(_根 / '测试'))

import _沙箱          # noqa: E402,F401  状态根沙箱
import 死书处理 as D   # noqa: E402

_URL = 'https://example.com/book/1'


def _假mgr(成功=True):
    mgr = mock.MagicMock()
    mgr.delete_task.return_value = 成功
    return mgr


class Test删除书记录(unittest.TestCase):

    def setUp(self):
        self.patches = [
            mock.patch.dict('sys.modules'),
        ]
        # 三个被编排的模块全部替换为 mock (不触真实数据文件)
        self.p书架 = mock.MagicMock()
        self.p书架.移除.return_value = True
        self.p清单 = mock.MagicMock()
        self.p清单.移除.return_value = True
        self.mods = mock.patch.dict('sys.modules', {'书架': self.p书架,
                                                    '网站清单': self.p清单})
        self.mods.start()
        self.mgr = _假mgr(True)
        self.addCleanup(self.mods.stop)

    def test_三项全成功(self):
        r = D.删除书记录(_URL, 'task_1', task_manager=self.mgr)
        self.assertTrue(r['全部成功'])
        self.assertTrue(r['任务'][0] and r['书架'][0] and r['网站清单'][0])

    def test_范围子集只删书架(self):
        r = D.删除书记录(_URL, 'task_1', 范围=('书架',), task_manager=self.mgr)
        self.assertTrue(r['全部成功'])
        self.assertIn('书架', r)
        self.assertNotIn('任务', r, '范围外的项不得出现在结果里')
        self.p书架.移除.assert_called_once_with(_URL)
        self.p清单.移除.assert_not_called()
        self.mgr.delete_task.assert_not_called()

    def test_任务项恒传delete_file_false(self):
        """产物文件安全: 绝不因删除记录而删掉已抓 txt"""
        D.删除书记录(_URL, 'task_1', task_manager=self.mgr)
        self.mgr.delete_task.assert_called_once_with('task_1', delete_file=False)

    def test_无任务id时任务项失败但不阻断(self):
        r = D.删除书记录(_URL, '', task_manager=self.mgr)
        self.assertFalse(r['任务'][0])
        self.assertTrue(r['书架'][0], '其余项仍应执行')
        self.assertFalse(r['全部成功'])

    def test_单项抛异常不阻断其余(self):
        self.p书架.移除.side_effect = RuntimeError('模拟书架 IO 失败')
        r = D.删除书记录(_URL, 'task_1', task_manager=self.mgr)
        self.assertFalse(r['书架'][0])
        self.assertTrue(r['网站清单'][0], '异常项之后的项仍须执行')
        self.assertFalse(r['全部成功'])

    def test_幂等_重跑不抛且如实返回False(self):
        """三项都是"删不到即已删"语义, 重复执行安全"""
        self.p书架.移除.return_value = False
        self.p清单.移除.return_value = False
        self.mgr = _假mgr(False)
        r = D.删除书记录(_URL, 'task_1', task_manager=self.mgr)
        self.assertFalse(r['全部成功'])
        r2 = D.删除书记录(_URL, 'task_1', task_manager=self.mgr)
        self.assertFalse(r2['全部成功'])

    def test_绝不动爬取历史与站点历史(self):
        """需求明确: 只删任务/书架/网站清单"""
        with mock.patch.dict('sys.modules', {'爬取历史': mock.MagicMock(),
                                             '站点历史': mock.MagicMock()}):
            D.删除书记录(_URL, 'task_1', task_manager=self.mgr)
        for 名称 in ('爬取历史', '站点历史'):
            mod = sys.modules.get(名称)
            if mod is not None and hasattr(mod, '记录请求'):
                self.assertFalse(mod.记录请求.called, f'不得调用 {名称}')

    def test_结果含全部成功键(self):
        r = D.删除书记录(_URL, 'task_1', task_manager=self.mgr)
        self.assertIn('全部成功', r)

    def test_未指定task_manager时任务项失败(self):
        """没传 mgr 时不应凭空删真实任务 (宁缺勿滥)"""
        r = D.删除书记录(_URL, 'task_1', 范围=('任务',), task_manager=None)
        self.assertIn('任务', r)


if __name__ == '__main__':
    unittest.main(verbosity=2)
