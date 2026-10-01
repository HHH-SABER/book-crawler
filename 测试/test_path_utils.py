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
from unittest import mock  # noqa: F401 (Test便携数据开关 使用 unittest.mock.patch)

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
        # 直接落盘不再报 No such file or directory
        目标 = Path(root) / '数据' / '爬取历史.json'
        目标.write_text('{}', encoding='utf-8')
        self.assertTrue(目标.is_file())

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


class Test便携数据开关(unittest.TestCase):
    """P1 便携数据开关: EXE 旁 便携模式.flag → 状态根切 EXE 旁 (仅打包模式生效)。

    全程 mock is_frozen/get_app_base_dir, BASE_DIR 指向临时目录, 零真实副作用。
    """

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix='nsl_portable_')
        self._旧根 = _path_utils._STATE_ROOT
        self._旧env = os.environ.get('LOCALAPPDATA')
        _path_utils._STATE_ROOT = None
        os.environ['LOCALAPPDATA'] = self._tmp

    def tearDown(self):
        if self._旧env is None:
            os.environ.pop('LOCALAPPDATA', None)
        else:
            os.environ['LOCALAPPDATA'] = self._旧env
        _path_utils._STATE_ROOT = self._旧根
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_flag生效_状态根切EXE旁(self):
        Path(self._tmp, '便携模式.flag').write_text('', encoding='utf-8')
        with unittest.mock.patch('_path_utils.is_frozen', return_value=True), \
             unittest.mock.patch('_path_utils.get_app_base_dir',
                                 return_value=self._tmp):
            root = _path_utils.get_state_root()
            self.assertEqual(root, self._tmp, '便携模式状态根应为 EXE 旁 (BASE_DIR)')
            self.assertTrue(_path_utils.is_portable_mode())
        for name in ('数据', '日志'):
            self.assertTrue(os.path.isdir(os.path.join(root, name)),
                            f'便携模式 {name} 子目录未创建')

    def test_无flag默认根不变(self):
        with unittest.mock.patch('_path_utils.is_frozen', return_value=True), \
             unittest.mock.patch('_path_utils.get_app_base_dir',
                                 return_value=self._tmp):
            root = _path_utils.get_state_root()
        self.assertEqual(root, os.path.join(self._tmp, '小说爬虫'),
                         '无 flag 时必须维持默认状态根')
        self.assertFalse(_path_utils.is_portable_mode())

    def test_源码模式flag不生效_隔离保护(self):
        """flag 只在打包模式生效 —— 源码/测试环境的 LOCALAPPDATA 重定向隔离
        (踩坑 K27/K28) 绝不被项目根/临时目录里的 flag 破坏"""
        Path(self._tmp, '便携模式.flag').write_text('', encoding='utf-8')
        with unittest.mock.patch('_path_utils.get_app_base_dir',
                                 return_value=self._tmp):
            root = _path_utils.get_state_root()
        self.assertEqual(root, os.path.join(self._tmp, '小说爬虫'),
                         '源码模式下 flag 不得生效 (隔离保护)')
        self.assertFalse(_path_utils.is_portable_mode())


if __name__ == '__main__':
    unittest.main()
