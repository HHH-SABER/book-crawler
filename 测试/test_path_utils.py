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


class Test只读基目录容错(unittest.TestCase):
    """BASE_DIR 不可写时**不得抛异常** (2026-10-03 修)。

    原缺陷: get_default_output_dir / resolve_output_dir 里的
    os.makedirs 是裸调用无 try, 而同文件 get_state_root 内 3 处 makedirs
    都有 `except OSError: pass` —— 风格不一致, 且这是启动路径上唯一会抛的
    建目录。get_default_output_dir 被 爬虫.py:6733 模块级调用(导入期执行)
    → BASE_DIR 不可写时 PermissionError 直接崩在 import 阶段, 用户连界面
    都看不到, 日志里也只有一句 makedirs traceback。

    触发场景与"是否装成安装版"无关, 现在就能踩到:
      · EXE 放在只读介质 / U 盘只读分区 / C 盘根目录
      · 便携模式.flag 状态下 EXE 位于受保护目录
    """

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix='nc_ro_')
        # 让 BASE_DIR 指向一个**文件**(而非目录): 建其子目录必然 OSError,
        # 比 mock 掉 makedirs 更接近真实的"路径存在但不可写"现场
        self._占位 = os.path.join(self._tmp, '占位')
        Path(self._占位).write_text('x', encoding='utf-8')

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_默认输出目录不抛(self):
        with unittest.mock.patch('_path_utils.get_app_base_dir',
                                 return_value=self._占位):
            路径 = _path_utils.get_default_output_dir()
        self.assertTrue(路径.endswith('抓取结果'),
                        f'返回值应仍指向抓取结果, 实为 {路径}')

    def test_默认输出目录已存在时正常(self):
        """可写场景不得被容错改动行为 (回归护栏)。"""
        正常 = os.path.join(self._tmp, '正常')
        with unittest.mock.patch('_path_utils.get_app_base_dir',
                                 return_value=正常):
            路径 = _path_utils.get_default_output_dir()
        self.assertTrue(os.path.isdir(路径), '可写时应正常建出目录')

    def test_resolve_output_相对路径不抛(self):
        with unittest.mock.patch('_path_utils.get_app_base_dir',
                                 return_value=self._占位):
            路径 = _path_utils.resolve_output_dir('子目录/书名')
        self.assertTrue(路径.endswith(os.path.join('子目录', '书名')),
                        f'相对路径应仍按 BASE_DIR 解析, 实为 {路径}')

    def test_resolve_output_绝对路径不抛(self):
        绝对 = os.path.join(self._占位, '绝对子目录')
        路径 = _path_utils.resolve_output_dir(绝对)
        self.assertEqual(路径, os.path.normpath(绝对))

    def test_resolve_output_空值走默认(self):
        with unittest.mock.patch('_path_utils.get_app_base_dir',
                                 return_value=self._占位):
            路径 = _path_utils.resolve_output_dir('')
        self.assertTrue(路径.endswith('抓取结果'), '空值应回落默认输出目录')

    def test_两处makedirs都有容错(self):
        """源码级钉死: 防止后人"统一风格"时把 try 又摘掉。"""
        import inspect
        for 名 in ('get_default_output_dir', 'resolve_output_dir'):
            源码 = inspect.getsource(getattr(_path_utils, 名))
            self.assertIn('except OSError', 源码,
                          f'{名} 的 makedirs 又变回裸调用了 (只读目录会崩在 import)')


class Test模式解析与数据文件(unittest.TestCase):
    """阶段一 #2 补齐: 模式解析 (frozen/源码) + 迁移语义 + 缓存 + 数据文件解析。

    与上面几个类的关系: 上面守"状态根/便携/容错"的行为回归, 本类补
    "双模式路径解析"与"读写配置入口"的契约 —— 后者此前无任何覆盖。
    """

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix='nsl_mode_')
        self._旧exe = sys.executable
        self._旧根 = _path_utils._STATE_ROOT
        self._旧env = os.environ.get('LOCALAPPDATA')
        _path_utils._STATE_ROOT = None
        # frozen 模式: EXE 在 tmp/base, LOCALAPPDATA 指 tmp/local
        os.makedirs(os.path.join(self._tmp, 'base'), exist_ok=True)
        sys.executable = os.path.join(self._tmp, 'base', '小说爬虫.exe')
        os.environ['LOCALAPPDATA'] = os.path.join(self._tmp, 'local')

    def tearDown(self):
        sys.executable = self._旧exe
        if self._旧env is None:
            os.environ.pop('LOCALAPPDATA', None)
        else:
            os.environ['LOCALAPPDATA'] = self._旧env
        _path_utils._STATE_ROOT = self._旧根
        shutil.rmtree(self._tmp, ignore_errors=True)

    # ---- 双模式解析 ----
    def test_frozen_base取exe旁(self):
        with unittest.mock.patch('_path_utils.is_frozen', return_value=True):
            self.assertEqual(
                _path_utils.get_app_base_dir(),
                os.path.join(self._tmp, 'base'))

    def test_frozen_resource取_MEIPASS(self):
        with unittest.mock.patch('_path_utils.is_frozen', return_value=True), \
             unittest.mock.patch.object(sys, '_MEIPASS',
                                        os.path.join(self._tmp, 'mei'), create=True):
            self.assertEqual(_path_utils.get_resource_dir(),
                             os.path.join(self._tmp, 'mei'))

    def test_frozen_默认输出目录在exe旁(self):
        with unittest.mock.patch('_path_utils.is_frozen', return_value=True):
            出 = _path_utils.get_default_output_dir()
            self.assertEqual(出, os.path.join(self._tmp, 'base', '抓取结果'))
            self.assertTrue(os.path.isdir(出))

    # ---- 状态根 ----
    def test_无LOCALAPPDATA回退base(self):
        os.environ.pop('LOCALAPPDATA', None)
        os.environ.pop('APPDATA', None)
        with unittest.mock.patch('_path_utils.is_frozen', return_value=True):
            self.assertEqual(_path_utils.get_state_root(),
                             os.path.join(self._tmp, 'base'))

    def test_迁移旧数据_复制非移动(self):
        os.makedirs(os.path.join(self._tmp, 'base', '数据'), exist_ok=True)
        Path(self._tmp, 'base', '数据', '爬取历史.json').write_text(
            '{"urls": []}', encoding='utf-8')
        with unittest.mock.patch('_path_utils.is_frozen', return_value=True):
            root = _path_utils.get_state_root()
        self.assertTrue(Path(root, '数据', '爬取历史.json').is_file(),
                        '旧数据必须复制到新根')
        self.assertTrue(Path(self._tmp, 'base', '数据', '爬取历史.json').is_file(),
                        '迁移必须是复制不是移动 —— 旧位置数据仍可用 (U 盘/换目录场景)')

    def test_状态根缓存(self):
        with unittest.mock.patch('_path_utils.is_frozen', return_value=True):
            a = _path_utils.get_state_root()
            b = _path_utils.get_state_root()
        self.assertEqual(a, b)
        self.assertIsNotNone(_path_utils._STATE_ROOT, '第二次必须命中缓存')

    # ---- resolve_data_file (读写配置入口) ----
    def test_数据文件_BASE有则直接返回(self):
        Path(self._tmp, 'base', '站点表.json').write_text('{}', encoding='utf-8')
        with unittest.mock.patch('_path_utils.is_frozen', return_value=True):
            p = _path_utils.resolve_data_file('站点表.json')
        self.assertEqual(p, os.path.join(self._tmp, 'base', '站点表.json'))

    def test_数据文件_从资源目录复制默认值(self):
        res = os.path.join(self._tmp, 'res')
        os.makedirs(res, exist_ok=True)
        Path(res, '默认.txt').write_text('x', encoding='utf-8')
        with unittest.mock.patch('_path_utils.is_frozen', return_value=True), \
             unittest.mock.patch('_path_utils.get_resource_dir', return_value=res):
            p = _path_utils.resolve_data_file('默认.txt')
        self.assertTrue(Path(self._tmp, 'base', '默认.txt').is_file(),
                        'RESOURCE_DIR 有默认值时应复制到 BASE_DIR')

    def test_数据文件_两处都没有返回目标路径(self):
        with unittest.mock.patch('_path_utils.is_frozen', return_value=True), \
             unittest.mock.patch('_path_utils.get_resource_dir', return_value=self._tmp):
            p = _path_utils.resolve_data_file('不存在.json')
        self.assertEqual(p, os.path.join(self._tmp, 'base', '不存在.json'))


if __name__ == '__main__':
    unittest.main()
