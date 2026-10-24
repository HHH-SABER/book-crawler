# -*- coding: utf-8 -*-
"""`源码/_path_utils.py` 契约冻结测试（P9 阶段 0 · 冻结与护栏）。

为什么补这个: `_path_utils` 扇入 **36**，是路径底座。P9 阶段 0 规定
「冻结，禁止大改，只允许增量」—— 但冻结只写在文档里没有约束力。
本文件把**公开 API 与解析语义**锁成断言: 任何"重构顺手改签名 / 改解析规则"
都会在这里变红，而不是等到打包后才发现输出目录跑偏。

覆盖:
  ① 公开 API 存在性（逐个点名，删名/改名即红）；
  ② 源码模式的 RESOURCE_DIR / BASE_DIR 语义；
  ③ `resolve_output_dir` 相对/绝对路径归一；
  ④ `resolve_data_file` 缺失时从资源目录复制默认值；
  ⑤ `托盘图标候选` 去重保序、永不为空；
  ⑥ 状态根: LOCALAPPDATA 重定向到临时目录，`数据/`、`日志/` 子目录必存在。

全程不碰真实用户状态: BASE_DIR / RESOURCE_DIR / LOCALAPPDATA 一律指向
临时目录，结束后恢复 `_STATE_ROOT` 全局缓存。
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

import _path_utils as PU   # noqa: E402


class _临时基类(unittest.TestCase):
    """把 BASE_DIR / RESOURCE_DIR 重定向到临时目录"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.临时 = Path(self._tmp.name)
        self.基 = self.临时 / 'base'
        self.资源 = self.临时 / 'resource'
        self.基.mkdir()
        self.资源.mkdir()
        self._补丁 = mock.patch.multiple(
            PU,
            get_app_base_dir=lambda: str(self.基),
            get_resource_dir=lambda: str(self.资源),
        )
        self._补丁.start()

    def tearDown(self):
        self._补丁.stop()
        self._tmp.cleanup()


class Test公开API冻结(unittest.TestCase):
    """名字就是契约: 这些函数被 36 个模块调用，不许悄悄消失"""

    必须存在 = (
        'is_frozen', 'get_resource_dir', 'get_app_base_dir',
        'get_default_output_dir', 'is_portable_mode', 'get_state_root',
        'resolve_output_dir', 'resolve_data_file', '托盘图标候选',
    )

    def test_公开函数齐全且可调用(self):
        for 名 in self.必须存在:
            函数 = getattr(PU, 名, None)
            self.assertTrue(callable(函数), f'_path_utils.{名} 缺失或不可调用')

    def test_源码模式判定(self):
        self.assertFalse(PU.is_frozen(), '测试进程不应被识别为 PyInstaller 产物')
        self.assertFalse(PU.is_portable_mode(), '源码模式不支持便携开关')

    def test_资源目录就是源码目录(self):
        self.assertEqual(
            os.path.normcase(PU.get_resource_dir()),
            os.path.normcase(str(Path(PU.__file__).resolve().parent)),
            '源码模式 RESOURCE_DIR 必须等于 源码/ 目录')


class Test路径解析语义(_临时基类):
    """解析规则一旦变化，用户的抓取结果/配置就会写错地方"""

    def test_相对输出目录挂在基目录下(self):
        路径 = PU.resolve_output_dir('抓取结果')
        self.assertEqual(Path(路径).resolve(), (self.基 / '抓取结果').resolve())
        self.assertTrue(Path(路径).is_dir(), 'resolve_output_dir 应顺手建目录')

    def test_绝对输出目录原样保留(self):
        绝对 = str(self.临时 / '绝对输出')
        路径 = PU.resolve_output_dir(绝对)
        self.assertEqual(Path(路径).resolve(), Path(绝对).resolve())

    def test_空输出目录回落到默认(self):
        路径 = PU.resolve_output_dir('')
        self.assertEqual(Path(路径).resolve(), (self.基 / '抓取结果').resolve())

    def test_缺省配置文件从资源目录复制(self):
        (self.资源 / '站点配置.json').write_text('{"站点": []}', encoding='utf-8')
        路径 = Path(PU.resolve_data_file('站点配置.json'))
        self.assertEqual(路径.resolve(), (self.基 / '站点配置.json').resolve())
        self.assertEqual(路径.read_text(encoding='utf-8'), '{"站点": []}')

    def test_无默认值时只给目标路径不报错(self):
        路径 = Path(PU.resolve_data_file('不存在的配置.json'))
        self.assertEqual(路径.resolve(), (self.基 / '不存在的配置.json').resolve())
        self.assertFalse(路径.exists(), '无默认值不应凭空造文件')

    def test_已存在文件不被默认值覆盖(self):
        (self.基 / '站点配置.json').write_text('{"用户": 1}', encoding='utf-8')
        (self.资源 / '站点配置.json').write_text('{"默认": 1}', encoding='utf-8')
        路径 = Path(PU.resolve_data_file('站点配置.json'))
        self.assertEqual(路径.read_text(encoding='utf-8'), '{"用户": 1}')


class Test托盘图标候选(_临时基类):
    """2026-10-24 刚修过纯色块: 候选列表顺序错不得"""

    def test_去重保序(self):
        候选 = PU.托盘图标候选(str(self.资源), str(self.资源))
        self.assertEqual(len(候选), len(set(候选)), '同一根目录不应产生重复项')
        self.assertEqual(候选[0], os.path.normpath(
            os.path.join(str(self.资源), '脚本', '图标.ico')))

    def test_资源根优先于基根(self):
        候选 = PU.托盘图标候选(str(self.资源), str(self.基))
        self.assertIn(os.path.normpath(os.path.join(str(self.资源), '图标.ico')), 候选)
        self.assertIn(os.path.normpath(os.path.join(str(self.基), '图标.ico')), 候选)
        self.assertLess(候选.index(os.path.join(str(self.资源), '图标.ico')),
                        候选.index(os.path.join(str(self.基), '图标.ico')))

    def test_空输入也有兜底(self):
        self.assertEqual(PU.托盘图标候选('', ''), ['图标.ico'])


class Test状态根(_临时基类):
    """状态根错位 = 抓取历史/书架直接丢，必须锁死"""

    def setUp(self):
        super().setUp()
        self._旧状态根 = PU._STATE_ROOT
        PU._STATE_ROOT = None
        self._local = self.临时 / 'localappdata'
        self._local.mkdir()
        self._env = mock.patch.dict(os.environ, {'LOCALAPPDATA': str(self._local)})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        PU._STATE_ROOT = self._旧状态根
        super().tearDown()

    def test_默认根落在LOCALAPPDATA下(self):
        根 = Path(PU.get_state_root())
        self.assertEqual(根.resolve(), (self._local / '小说爬虫').resolve())
        for 子 in ('数据', '日志'):
            self.assertTrue((根 / 子).is_dir(), f'状态根缺少 {子}/ 子目录')

    def test_二次调用复用缓存(self):
        第一次 = PU.get_state_root()
        第二次 = PU.get_state_root()
        self.assertIs(第一次, 第二次, '状态根应缓存，不应重复解析/迁移')


if __name__ == '__main__':
    unittest.main()
