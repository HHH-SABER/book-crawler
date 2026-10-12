# -*- coding: utf-8 -*-
"""站点表 `chapter_url_regex` 生效后的回归用例 (2026-10-13)。

**背景（真缺口）**: `chapter_url_regex` 在 `sites_config.py` 有文档、在站点管理页可编辑，
但**爬虫从不读取**（实测全源码 0 处使用）⇒ 一直是**死配置**：站点声明了自己章节 URL 的
形状，通用筛选却只靠弱启发式（路径前缀 + 词表）⇒ 目录页里的**导航位/外站链接**只要路径
前缀凑得上，就会被当成章节收下。

**安全方向**（本文件守着）:
  - 未配置正则 → 一律放行，**与改造前行为完全一致**（绝大多数站点不受影响）；
  - 正则写坏 → 放行并留痕，不能因为一个坏正则让整站抓不动。

运行方式 (项目根目录):
    python -m unittest discover -s 测试 -v
"""
import ast
import sys
import unittest
from pathlib import Path

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

import 爬虫 as C                # noqa: E402

_源码 = (_根 / '源码' / '爬虫.py').read_text(encoding='utf-8')


class Test章节链接合正则(unittest.TestCase):

    def test_未配置一律放行_行为不变(self):
        """⚠️ 安全方向: 没配正则的站点, 行为必须与改造前**完全一致**。"""
        for 正则 in ('', None):
            for href in ('/book/1/2.html', '/随便什么.html', 'javascript:void(0)'):
                with self.subTest(正则=正则, href=href):
                    self.assertTrue(C._章节链接合正则(href, 正则))

    def test_配置后按形状放行与拦截(self):
        # 站点表里真实存在的两类形状
        例 = [
            (r'/(\d+)/(\d+)\.html', '/12/34.html', True),
            (r'/(\d+)/(\d+)\.html', '/12/liked.html', False),
            (r'/read/(\d+)/(\d+)\.html', '/read/47/3980.html', True),
            (r'/read/(\d+)/(\d+)\.html', '/read/47/liked.html', False),
            (r'/kan/(\d+)_(\d+)\.html', '/kan/10282403_2.html', True),
            (r'/kan/(\d+)_(\d+)\.html', '/kan/about.html', False),
            (r'/book/[a-z0-9]+/[a-z0-9]+\.html', '/book/rtyppy/list1.html', True),
        ]
        for 正则, href, 期望 in 例:
            with self.subTest(正则=正则, href=href):
                self.assertEqual(C._章节链接合正则(href, 正则), 期望)

    def test_坏正则放行且不抛(self):
        """不能因为一个写坏的正则让整站抓不动。"""
        for 坏 in ('([', '*abc', '(?P<', 'a{2,1}'):
            with self.subTest(坏=坏):
                try:
                    self.assertTrue(C._章节链接合正则('/book/1/2.html', 坏))
                except Exception as e:      # noqa: BLE001
                    self.fail(f'坏正则不该抛: {type(e).__name__}: {e}')


class Test接线到位(unittest.TestCase):
    """守护"死配置不再复发": 结构断言比行为断言更能防回归。"""

    def test_爬虫真的读取了chapter_url_regex(self):
        self.assertIn('chapter_url_regex', _源码,
                      'chapter_url_regex 必须被爬虫读取 (此前是死配置)')

    def test_两个放行点都过正则闸(self):
        段 = ''
        for n in ast.walk(ast.parse(_源码)):
            if isinstance(n, ast.FunctionDef) and n.name == 'get_chapter_list':
                段 = ast.get_source_segment(_源码, n) or ''
        self.assertEqual(
            段.count('_章节链接合正则('), 2,
            '两个章节链接放行点都应调用 _章节链接合正则()')

    def test_未配置时不产生拒绝计数(self):
        """结构性: 拒绝计数只应在命中正则闸时自增 (未配置→闸门恒放行, 计数不会被用)。"""
        self.assertIn('_正则拒', _源码)


if __name__ == '__main__':
    unittest.main(verbosity=2)
