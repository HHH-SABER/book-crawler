# -*- coding: utf-8 -*-
"""chromedriver 自动管理回归 (2026-10-13, 需求 #7)。

锁 `源码/驱动管理.py` 的行为契约。**全部离线**: 网络/注册表/文件系统都靠注入
替身, 不真下载 (真下载的端到端验证由开发期手工完成, 见模块 docstring)。

覆盖:
  ① 版本解析与 API 选版本 (含 per-milestone dict 结构 —— 实测踩过的坑);
  ② 本地驱动查找优先级;
  ③ zip 解包路径 (chromedriver-win64/ 一层目录);
  ④ 编排分支: 已有→直接用 / 无 Chrome→清晰报错 / 版本不匹配→清晰报错 /
     下载失败→清晰报错 (**不猜版本**);
  ⑤ 下载器可注入 (本模块可测性的基础)。
运行: python -m unittest discover -s 测试
"""
import io
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

import 驱动管理 as D   # noqa: E402


def _造zip(内层目录='chromedriver-win64') -> bytes:
    """造一个与真实发布形态一致的驱动 zip (内有一层目录)。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr(f'{内层目录}/chromedriver.exe', b'FAKE-EXE' * 100)
        z.writestr(f'{内层目录}/LICENSE.chromedriver', b'license')
    return buf.getvalue()


class Test纯函数(unittest.TestCase):

    def test_解析主版本(self):
        self.assertEqual(D.解析主版本('154.0.8037.99'), 154)
        self.assertEqual(D.解析主版本('120.0.6099.109'), 120)
        self.assertEqual(D.解析主版本('abc'), 0)
        self.assertEqual(D.解析主版本(''), 0)
        self.assertEqual(D.解析主版本(None), 0)

    def test_选版本_per_milestone_dict结构(self):
        """★ 真实 API 结构是 dict (实测: 顶层只有 timestamp/milestones,
        后者是 {主版本号: {version, downloads}}) —— 曾按 list 写导致全不匹配。"""
        api = {'milestones': {
            '154': {'version': '154.0.8037.92',
                    'downloads': {'chromedriver': [{'platform': 'win64'}]}},
            '155': {'version': '155.0.8059.39',
                    'downloads': {'chromedriver': [{'platform': 'win64'}]}},
        }}
        self.assertEqual(D.从API选版本(api, 154), '154.0.8037.92')
        self.assertEqual(D.从API选版本(api, 155), '155.0.8059.39')
        self.assertEqual(D.从API选版本(api, 140), '', '没有的版本必须返回空(不猜)')

    def test_选版本_无chromedriver条目的milestone跳过(self):
        api = {'milestones': {'154': {'version': '154.0.8037.92',
                                      'downloads': {}}}}
        self.assertEqual(D.从API选版本(api, 154), '')

    def test_选版本_兼容channels结构(self):
        api = {'channels': {'Stable': {'version': '154.0.8037.92',
                                       'downloads': {'chromedriver': [
                                           {'platform': 'win64'}]}}}}
        self.assertEqual(D.从API选版本(api, 154), '154.0.8037.92')

    def test_选版本_坏输入不炸(self):
        self.assertEqual(D.从API选版本({}, 154), '')
        self.assertEqual(D.从API选版本(None, 154), '')
        self.assertEqual(D.从API选版本({'milestones': 'x'}, 154), '')


class Test本地查找与解包(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_找本地驱动_目标目录优先(self):
        目录 = self.tmp / 'cd'
        目录.mkdir()
        (目录 / 'chromedriver.exe').write_bytes(b'x')
        self.assertEqual(D.找本地驱动(str(目录)),
                         str(目录 / 'chromedriver.exe'))

    def test_找本地驱动_显式路径优先于目录(self):
        目录 = self.tmp / 'cd'
        目录.mkdir()
        (目录 / 'chromedriver.exe').write_bytes(b'x')
        显式 = self.tmp / 'mycd.exe'
        显式.write_bytes(b'y')
        self.assertEqual(D.找本地驱动(str(目录), 路径们=[str(显式)]),
                         str(显式))

    def test_找本地驱动_都没有返回空(self):
        self.assertEqual(D.找本地驱动(str(self.tmp / 'none')), '')

    def test_下载并解压_剥一层目录(self):
        """真实 zip 是 chromedriver-win64/chromedriver.exe ⇒ 必须剥到目标路径"""
        目录 = self.tmp / 'out'
        路径 = D.下载并解压('154.0.8037.92', str(目录),
                            下载器=lambda url: _造zip())
        self.assertTrue(路径.endswith('chromedriver.exe'))
        self.assertTrue(os.path.isfile(路径))
        self.assertIn(b'FAKE-EXE', Path(路径).read_bytes())

    def test_下载并解压_太小响应判失败(self):
        with self.assertRaises(RuntimeError):
            D.下载并解压('154.0.0', str(self.tmp / 'o'),
                        下载器=lambda url: b'too-small')


class Test编排分支(unittest.TestCase):
    """确保可用() 的四条分支 (全部注入, 不真下载)"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _已有驱动(self):
        if not hasattr(self, '_缓存路径'):
            目录 = self.tmp / 'cd'
            目录.mkdir(exist_ok=True)
            p = 目录 / 'chromedriver.exe'
            p.write_bytes(b'LOCAL')
            self._缓存路径 = str(p)
        return self._缓存路径

    def test_已有驱动不下载(self):
        路径 = D.确保可用(程序根=str(self.tmp),
                          找=lambda d: self._已有驱动())
        self.assertEqual(路径, self._已有驱动(), '本地有就绝不再下载')
        self.assertIn(b'LOCAL', Path(路径).read_bytes())

    def test_无Chrome报清晰错误(self):
        with self.assertRaises(RuntimeError) as ctx:
            D.确保可用(程序根=str(self.tmp),
                       找=lambda d: '',
                       取版本=lambda: '')
        self.assertIn('Chrome', str(ctx.exception))

    def test_版本不匹配报清晰错误且不猜(self):
        with self.assertRaises(RuntimeError) as ctx:
            D.确保可用(程序根=str(self.tmp),
                       找=lambda d: '',
                       取版本=lambda: '154.0.8037.99',
                       取API=lambda: {'milestones': {}})
        self.assertIn('匹配', str(ctx.exception))

    def test_下载失败报清晰错误(self):
        def 坏下载(版本, 目录):
            raise RuntimeError('network down')
        with self.assertRaises(RuntimeError):
            D.确保可用(程序根=str(self.tmp),
                       找=lambda d: '',
                       取版本=lambda: '154.0.8037.99',
                       取API=lambda: {'milestones': {
                           '154': {'version': '154.0.8037.92',
                                   'downloads': {'chromedriver': []}}}},
                       下载=坏下载)

    def test_完整走通_下载分支(self):
        提示 = []
        路径 = D.确保可用(
            程序根=str(self.tmp),
            提示回调=提示.append,
            找=lambda d: '',
            取版本=lambda: '154.0.8037.99',
            取API=lambda: {'milestones': {
                '154': {'version': '154.0.8037.92',
                        'downloads': {'chromedriver': [
                            {'platform': 'win64'}]}}}},
            下载=lambda 版本, 目录: D.下载并解压(
                版本, 目录, 下载器=lambda url: _造zip()))
        self.assertTrue(os.path.isfile(路径))
        self.assertTrue(any('下载' in t for t in 提示),
                        f'下载前必须给用户提示, 实际: {提示}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
