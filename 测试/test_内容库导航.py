# -*- coding: utf-8 -*-
"""内容库导航契约 (2026-11-10)。

改名「抓取工作台」→「内容库」不能动导航结构: 品类靠筛选, 不靠页面。
本文件钉住: 键仍是 crawl、顺序不变、页头文案已改、设计稿同步。
"""
import re
import sys
import unittest
from pathlib import Path

根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(根 / '源码'))

from gui_components.icon_rail import NAV_PAGES   # noqa: E402


class Test导航结构未变(unittest.TestCase):

    def test_首项仍是crawl且文案为内容库(self):
        key, 图标, 文案, 序 = NAV_PAGES[0]
        self.assertEqual(key, 'crawl', '首屏 key 必须仍是 crawl（改动会改首屏）')
        self.assertEqual(文案, '内容库')
        self.assertEqual(序, 0)

    def test_导航仍是六项且顺序不变(self):
        self.assertEqual([k for k, _, _, _ in NAV_PAGES],
                         ['crawl', 'history', 'deadbook', 'sites', 'log', 'remote'],
                         '品类靠筛选, 不得新增导航项')

    def test_pages_map键序与导航一致(self):
        源码 = (根 / '源码' / 'gui_app.py').read_text(encoding='utf-8')
        块 = 源码.split('pages_map = {')[1].split('}')[0]
        键 = re.findall(r'"([a-z]+)":', 块)
        self.assertEqual(键, [k for k, _, _, _ in NAV_PAGES],
                         'pages_map 键序必须与 NAV_PAGES 一致（否则首屏错页）')


class Test文案同步(unittest.TestCase):

    def test_页头已改名(self):
        源码 = (根 / '源码' / 'gui_app.py').read_text(encoding='utf-8')
        self.assertIn("page_header('内容库'", 源码)
        self.assertNotIn("page_header('抓取工作台'", 源码)

    def test_副标题不谎称自动识别品类(self):
        """品类由用户点胶囊决定，页头不得宣称「自动识别品类」(2026-11-10 截图发现)。"""
        源码 = (根 / '源码' / 'gui_app.py').read_text(encoding='utf-8')
        行 = [l for l in 源码.splitlines() if "page_header('内容库'" in l]
        self.assertEqual(len(行), 1)
        self.assertNotIn('自动识别品类', 行[0])
        self.assertIn('选好品类', 行[0])

    def test_侧栏源码不再含旧名(self):
        源码 = (根 / '源码' / 'gui_components' / 'icon_rail.py').read_text(
            encoding='utf-8')
        self.assertNotIn('抓取工作台', 源码)

    def test_设计稿与实现一致(self):
        设计稿 = 根 / '_agent' / '设计预览' / 'index.html'
        if not 设计稿.is_file():
            self.skipTest('设计稿未随仓库分发（_agent 为本地目录）')
        文本 = 设计稿.read_text(encoding='utf-8', errors='replace')
        self.assertIn('class="nav-label">内容库<', 文本)
        self.assertNotIn('class="nav-label">抓取工作台<', 文本)


if __name__ == '__main__':
    unittest.main(verbosity=2)
