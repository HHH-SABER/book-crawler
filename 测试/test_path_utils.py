# -*- coding: utf-8 -*-
"""_path_utils 状态根建目录回归: LOCALAPPDATA 被外部重定向到空目录时,
get_state_root 必须保证 数据/日志 子目录存在 —— 爬取历史等消费者直接
open 落盘不再报 No such file or directory。

全程不联网; 所有产物落在临时目录, 测试结束恢复原环境变量与缓存。

运行方式 (项目根目录):
    python -m unittest discover -s 测试 -v
    python 测试/test_path_utils.py
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '源码'))

import _path_utils


class Test状态根建目录(unittest.TestCase):
    """状态根重定向场景: 首次调用必须把 数据/日志 两个子目录建出来"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix='nsl_state_root_')
        self._旧根 = _path_utils._STATE_ROOT
        self._旧env = os.environ.get('LOCALAPPDATA')
        _path_utils._STATE_ROOT = None          # 重置缓存, 强制重新解析
        os.environ['LOCALAPPDATA'] = self._tmp

    def tearDown(self):
        if self._旧env is None:
            os.environ.pop('LOCALAPPDATA', None)
        else:
            os.environ['LOCALAPPDATA'] = self._旧env
        _path_utils._STATE_ROOT = self._旧根    # 还原缓存, 不影响其他用例
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_空状态根_数据日志子目录必存在且可写(self):
        root = _path_utils.get_state_root()
        self.assertEqual(root, os.path.join(self._tmp, '小说爬虫'))
        for name in ('数据', '日志'):
            self.assertTrue(os.path.isdir(os.path.join(root, name)),
                            f'{name} 子目录未创建')
        # 直接 open 落盘不再报 No such file or directory
        目标 = os.path.join(root, '数据', '爬取历史.json')
        with open(目标, 'w', encoding='utf-8') as f:
            f.write('{}')
        self.assertTrue(os.path.isfile(目标))

    def test_迁移失败后子目录仍存在(self):
        # copytree 中途抛 OSError (如旧文件被占用) 时, 建目录逻辑不应被跳过
        原copytree = _path_utils.shutil.copytree

        def _炸(*args, **kwargs):
            raise OSError('模拟迁移失败: 文件被占用')

        _path_utils.shutil.copytree = _炸
        try:
            root = _path_utils.get_state_root()
            for name in ('数据', '日志'):
                self.assertTrue(os.path.isdir(os.path.join(root, name)),
                                f'迁移失败后 {name} 子目录未创建')
        finally:
            _path_utils.shutil.copytree = 原copytree


if __name__ == '__main__':
    unittest.main()
