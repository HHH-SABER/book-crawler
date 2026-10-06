# -*- coding: utf-8 -*-
"""备用源数据层回归（2026-10-06 新功能：死书时给这本书添加新网站）。

需求来源：用户「死书询问是否要添加书籍新网站，没有的话就询问是否删除」。
本文件只管**数据层**（`源码/备用源.py`）：登记/查询/去重/校验/坏配置保护；
交互流程见 `测试/test_死书补址流程.py`。

最要紧的一条契约：**写入的键必须与抓取侧读取的键逐字节一致**——
`爬虫.py:7073` 会先把目录 URL 过一遍 `_规范化目录URL`，再在 `:7130` 精确匹配。
故这里直接拿 `爬虫._规范化目录URL` 当判据，而不是自己另写一套。
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

import _沙箱  # noqa: F401  沙箱: 状态根 → 一次性临时目录

import 备用源


class Test备用源(unittest.TestCase):

    def setUp(self):
        根 = Path(tempfile.mkdtemp(prefix='备用源_'))
        self.配置 = 根 / 'captcha_config.json'
        os.environ[备用源.环境覆盖变量] = str(self.配置)
        # 隔离自检: 配置落点必须真的是临时文件 —— 否则测试会写用户的真实配置
        # (2026-10-06 真的发生过一次: 首轮测试尚未加隔离, 把 a.example.com 写进了项目根)
        self.assertEqual(备用源.配置路径(), str(self.配置))
        self.addCleanup(lambda: os.environ.pop(备用源.环境覆盖变量, None))
        self.addCleanup(lambda: __import__('shutil').rmtree(根, ignore_errors=True))

    def _写配置(self, 内容):
        self.配置.write_text(json.dumps(内容, ensure_ascii=False), encoding='utf-8')

    def _读配置(self):
        return json.loads(self.配置.read_text(encoding='utf-8'))

    书 = 'https://a.example.com/book/1'
    镜像 = 'https://b.example.com/novel/1'

    def test_登记后可查到(self):
        结果 = 备用源.添加备用源(self.书, self.镜像)
        self.assertTrue(结果['可以'], 结果['原因'])
        self.assertEqual(备用源.取备用源(self.书), [self.镜像])
        self.assertEqual(self._读配置()['fallback_sources'], {备用源._规范化键(self.书): [self.镜像]})

    def test_键与消费侧同源(self):
        """写入的键 == 抓取侧 `fs.get(catalog_url)` 会用的键（用真实现算, 不自造）。"""
        import 爬虫
        self.assertEqual(备用源._规范化键(self.书), 爬虫._规范化目录URL(self.书),
                         '写入键必须与 爬虫 读取时的规范化结果一致, 否则登记了也查不到')
        备用源.添加备用源(self.书, self.镜像)
        登记表 = 备用源.全部()
        self.assertIn(爬虫._规范化目录URL(self.书), 登记表,
                      '消费侧按 爬虫._规范化目录URL(url) 精确取值, 键不一致 = 功能静默失效')
        self.assertEqual(登记表[爬虫._规范化目录URL(self.书)], [self.镜像])

    def test_重复登记幂等且不重复写(self):
        备用源.添加备用源(self.书, self.镜像)
        第一次 = self.配置.read_bytes()
        结果 = 备用源.添加备用源(self.书, self.镜像)
        self.assertTrue(结果['可以'])
        self.assertEqual(结果['原因'], '已登记过')
        self.assertEqual(备用源.取备用源(self.书), [self.镜像], '不得重复登记同一条')
        self.assertEqual(self.配置.read_bytes(), 第一次, '幂等命中时不该改写文件')

    def test_可登记多个备用源(self):
        备用源.添加备用源(self.书, self.镜像)
        备用源.添加备用源(self.书, 'https://c.example.com/book/1')
        self.assertEqual(len(备用源.取备用源(self.书)), 2)

    def test_非法网址被拒且不写文件(self):
        坏 = ['', '   ', 'ftp://x.example.com/a', 'example.com/book', 'https://',
              self.书, self.书 + '/']
        for u in 坏:
            with self.subTest(网址=u):
                结果 = 备用源.添加备用源(self.书, u)
                self.assertFalse(结果['可以'], f'{u!r} 不该被接受')
                self.assertTrue(结果['原因'], '拒绝时必须给人话原因')
        self.assertFalse(self.配置.exists() and 备用源.取备用源(self.书),
                         '非法输入不得写进配置')

    def test_配置损坏时拒绝写入且不覆盖(self):
        """关键安全: 配置解析不了 → 绝不原子覆盖, 否则用户的整份配置会被抹掉。"""
        原文 = '{ 这不是合法 JSON'
        self.配置.write_text(原文, encoding='utf-8')
        结果 = 备用源.添加备用源(self.书, self.镜像)
        self.assertFalse(结果['可以'])
        self.assertIn('无法解析', 结果['原因'])
        self.assertEqual(self.配置.read_text(encoding='utf-8'), 原文, '坏配置必须原样保留')

    def test_外部文件形态不覆盖(self):
        """`fallback_sources` 是"指向 JSON 文件"的字符串时（消费侧支持），不得改写。"""
        self._写配置({'fallback_sources': 'D:/some/fallback.json'})
        结果 = 备用源.添加备用源(self.书, self.镜像)
        self.assertFalse(结果['可以'])
        self.assertEqual(self._读配置()['fallback_sources'], 'D:/some/fallback.json')

    def test_保留其他配置字段(self):
        """只增改 fallback_sources, 其余字段（含用户自定义）必须原样保留。"""
        self._写配置({'enabled': True, 'strategies': ['a'], '我的自定义': {'x': 1}})
        备用源.添加备用源(self.书, self.镜像)
        配置 = self._读配置()
        self.assertEqual(配置['enabled'], True)
        self.assertEqual(配置['strategies'], ['a'])
        self.assertEqual(配置['我的自定义'], {'x': 1})
        self.assertIn(self.镜像, 配置['fallback_sources'][备用源._规范化键(self.书)])

    def test_多本书互不影响(self):
        另一本 = 'https://a.example.com/book/2'
        备用源.添加备用源(self.书, self.镜像)
        备用源.添加备用源(另一本, 'https://d.example.com/x')
        self.assertEqual(备用源.取备用源(self.书), [self.镜像])
        self.assertEqual(备用源.取备用源(另一本), ['https://d.example.com/x'])

    def test_移除备用源(self):
        备用源.添加备用源(self.书, self.镜像)
        备用源.添加备用源(self.书, 'https://c.example.com/book/1')
        结果 = 备用源.移除备用源(self.书, self.镜像)
        self.assertTrue(结果['可以'])
        self.assertEqual(备用源.取备用源(self.书), ['https://c.example.com/book/1'])
        备用源.移除备用源(self.书, 'https://c.example.com/book/1')
        self.assertEqual(备用源.取备用源(self.书), [])
        self.assertNotIn(备用源._规范化键(self.书), self._读配置().get('fallback_sources', {}),
                         '最后一个移除后不留空键')
        self.assertFalse(备用源.移除备用源(self.书, self.镜像)['可以'], '移除不存在的应如实报否')

    def test_读不到配置时不报错(self):
        self.assertFalse(self.配置.exists())
        self.assertEqual(备用源.取备用源(self.书), [])
        self.assertEqual(备用源.全部(), {})

    def test_测试沙箱内绝不落到真实配置(self):
        """系统性安全网: 未显式隔离时, 落点也必须跟着测试沙箱走。

        2026-10-06 实测事故: `captcha_config.json` 走 BASE_DIR(项目根),
        而 `测试/_沙箱.py` 只重定向了 LOCALAPPDATA(状态根) → 首轮 gate 把
        `a.example.com` 写进了**用户真实配置**。此断言防它复发。
        """
        os.environ.pop(备用源.环境覆盖变量, None)      # 刻意**不**显式隔离
        沙箱 = os.environ.get('_QWEN_TEST_SANDBOX_ROOT', '')
        self.assertTrue(沙箱, '前提: 测试沙箱环境变量应已由 测试/_沙箱.py 设好')
        路径 = 备用源.配置路径()
        self.assertTrue(os.path.abspath(路径).startswith(os.path.abspath(沙箱)),
                        f'未隔离时配置落点必须进沙箱, 实际: {路径}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
