# -*- coding: utf-8 -*-
"""浏览器插件内置安装回归 (2026-10-20)。

覆盖:
  ① 安装源解析: 源码/打包/EXE 旁 三种形态的目录候选;
  ② 安装: 复制到状态根/插件/<浏览器>, 返回 4 步引导;
  ③ 心跳: 记心跳 → 状态 已连接; 旧心跳 → 过期; 无文件 → 未安装;
  ④ 双版本产物: chrome/edge 的 manifest 差异与共享文件一致性
     (功能一致是需求硬要求 —— 两版只差 name/description);
  ⑤ 打包接线: build_exe 收录 插件/dist (静态断言)。
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

import 插件安装 as I     # noqa: E402


def _造源(根: Path, 浏览器: str) -> Path:
    源 = 根 / '插件' / 'dist' / 浏览器
    源.mkdir(parents=True)
    (源 / 'manifest.json').write_text(
        json.dumps({'manifest_version': 3, 'name': f'test-{浏览器}'}), encoding='utf-8')
    (源 / 'background.js').write_text('// bg', encoding='utf-8')
    (源 / 'popup.html').write_text('<html></html>', encoding='utf-8')
    return 源


class Test安装(unittest.TestCase):

    def setUp(self):
        根 = Path(tempfile.mkdtemp(prefix='插件安装_'))
        self.根 = 根
        self.addCleanup(lambda: __import__('shutil').rmtree(根, ignore_errors=True))

    def test_安装源解析(self):
        _造源(self.根, 'chrome')
        with mock.patch.object(I, '_基目录', return_value=self.根):
            self.assertEqual(I.安装源('chrome'), self.根 / '插件' / 'dist' / 'chrome')
            self.assertIsNone(I.安装源('edge'), 'edge 没造源, 应返回 None')

    def test_安装复制与步骤(self):
        _造源(self.根, 'edge')
        目标根 = self.根 / '状态'
        with mock.patch.object(I, '_基目录', return_value=self.根), \
                mock.patch.object(I, '_浏览器exe', return_value='C:/fake/msedge.exe'), \
                mock.patch.object(I, '_状态根', return_value=目标根):
            结果 = I.安装('edge')
        self.assertTrue(结果['ok'], 结果)
        目标 = 目标根 / '插件' / 'edge'
        self.assertTrue((目标 / 'manifest.json').is_file())
        self.assertTrue((目标 / 'background.js').is_file())
        self.assertEqual(len(结果['步骤']), 4)
        self.assertIn(str(目标), 结果['步骤'][2])

    def test_缺源时给人话原因(self):
        with mock.patch.object(I, '_基目录', return_value=self.根), \
                mock.patch.object(I, '_浏览器exe', return_value='C:/fake/chrome.exe'), \
                mock.patch.object(I, '_状态根', return_value=self.根 / '状态'):
            结果 = I.安装('chrome')
        self.assertFalse(结果['ok'])
        self.assertIn('找不到', 结果['原因'])

    def test_未安装浏览器明确拒绝(self):
        _造源(self.根, 'chrome')
        with mock.patch.object(I, '_基目录', return_value=self.根), \
                mock.patch.object(I, '_浏览器exe', return_value=None), \
                mock.patch.object(I, '_状态根', return_value=self.根 / '状态'):
            结果 = I.安装('chrome')
        self.assertFalse(结果['ok'])
        self.assertIn('未检测到', 结果['原因'])

    def test_非法浏览器名(self):
        self.assertFalse(I.安装('firefox')['ok'])
        self.assertFalse(I.打开扩展页('firefox')['ok'])


class Test心跳(unittest.TestCase):

    def setUp(self):
        根 = Path(tempfile.mkdtemp(prefix='心跳_'))
        self.addCleanup(lambda: __import__('shutil').rmtree(根, ignore_errors=True))
        p = mock.patch.object(I, '心跳路径', return_value=str(根 / '插件心跳.json'))
        p.start()
        self.addCleanup(p.stop)

    def test_记心跳后已连接(self):
        I.记心跳('127.0.0.1')
        s = I.心跳状态()
        self.assertTrue(s['已连接'])
        self.assertLess(s['秒前'], 5)
        self.assertIn('已连接', I.状态文案())

    def test_旧心跳判过期(self):
        Path(I.心跳路径()).write_text(
            json.dumps({'ts': time.time() - 3600, '来源': ''}), encoding='utf-8')
        self.assertFalse(I.心跳状态()['已连接'])
        self.assertIn('最后活跃', I.状态文案())

    def test_无心跳判未安装(self):
        self.assertFalse(I.心跳状态()['已连接'])
        self.assertIn('未安装', I.状态文案())


class Test扫描(unittest.TestCase):
    """扫描 → 列表 → 选择 的数据层 (用户验收意见: 先扫描再选择)。"""

    def test_只装Chrome时的列表(self):
        def 假exe(名):
            return 'C:/fake/chrome.exe' if 名 == 'chrome' else None
        with mock.patch.object(I, '_浏览器exe', side_effect=假exe), \
                mock.patch.object(I, '_文件版本', return_value='141.0.7390.55'):
            项s = I.扫描()
        self.assertEqual([x['浏览器'] for x in 项s], ['chrome', 'edge', 'firefox'],
                         '已装且支持的排最前')
        c, e, f = 项s
        self.assertTrue(c['已安装'] and c['支持'])
        self.assertEqual(c['版本'], '141.0.7390.55')
        self.assertFalse(e['已安装'])
        self.assertFalse(f['支持'])
        self.assertIn('Chromium', f['说明'], '不支持的浏览器必须给出原因')

    def test_Firefox已装也标不支持(self):
        def 假exe(名):
            return 'C:/fake/firefox.exe' if 名 == 'firefox' else None
        with mock.patch.object(I, '_浏览器exe', side_effect=假exe):
            项s = I.扫描()
        f = next(x for x in 项s if x['浏览器'] == 'firefox')
        self.assertTrue(f['已安装'])
        self.assertFalse(f['支持'])
        self.assertTrue(f['说明'])

    def test_全未装时全部给出提示数据(self):
        with mock.patch.object(I, '_浏览器exe', return_value=None):
            项s = I.扫描()
        self.assertTrue(all(not x['已安装'] for x in 项s))
        self.assertEqual(len(项s), 3, '未装也要列出 (供明确提示)')


class Test双版本产物(unittest.TestCase):
    """需求硬要求: 两版功能一致, 只差浏览器标注。"""

    def setUp(self):
        self.dist = _根 / '插件' / 'dist'
        if not (self.dist / 'chrome' / 'manifest.json').is_file():
            self.skipTest('插件/dist 未构建 (先运行 插件/构建两版.py)')

    def test_两版manifest只差名称(self):
        载 = {}
        for 版 in ('chrome', 'edge'):
            m = json.loads((self.dist / 版 / 'manifest.json').read_text(encoding='utf-8'))
            载[版] = m
            self.assertIn(版.capitalize(), m['name'], f'{版} 版 name 应标注浏览器')
        for 键 in ('manifest_version', 'version', 'permissions', 'host_permissions',
                  'background', 'action'):
            self.assertEqual(载['chrome'][键], 载['edge'][键], f'{键} 必须两版一致')

    def test_共享文件齐全且一致(self):
        for 版 in ('chrome', 'edge'):
            for f in ('background.js', 'popup.html', 'popup.js', 'README.md'):
                self.assertTrue((self.dist / 版 / f).is_file(), f'{版}/{f}')
            for f in ('background.js', 'popup.html', 'popup.js'):
                self.assertEqual(
                    (self.dist / 'chrome' / f).read_text(encoding='utf-8'),
                    (self.dist / 'edge' / f).read_text(encoding='utf-8'),
                    f'{f} 两版必须逐字节一致')


class Test打包接线(unittest.TestCase):

    def test_build_exe收录插件dist(self):
        源码 = (_根 / '脚本' / 'build_exe.py').read_text(encoding='utf-8')
        self.assertIn("'插件', 'dist'", 源码)
        self.assertIn('插件/dist', 源码)


if __name__ == '__main__':
    unittest.main(verbosity=2)
