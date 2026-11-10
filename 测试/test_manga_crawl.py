# -*- coding: utf-8 -*-
"""漫画抓取回归 (2026-11-09, P8 §H 横向 H1/H2 首个落地品类)。

全部离线且**不依赖私有站点配置**: 测试注入假站点表 + 占位域名
(example.invalid)；真实站点配置在 `站点适配_本地/漫画站点.json`（不入库）。
覆盖: 站点识别 / 章节列表(去重·序号·导航词回落) / 图片列表(过滤 logo·相对补全) /
      文件名补零与后缀 / 断点续传 / 坏图跳过 / CBZ 打包。
"""
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

import 漫画抓取 as M   # noqa: E402

_图正则 = r'(?:src|data-src|data-original|data-echo)="([^"]+\.(?:jpg|jpeg|png|webp)(?:\?[^"]*)?)"'

# 假站点表: 一个纯 HTTP 站 + 一个渲染站 (占位域名, 与真实站点无关)
_假表 = {
    'http站': M.站点(名='http站', 详情正则=r'/chapter/(\d+)', 图片正则=_图正则,
                需渲染=False, 图选择器='', referer='manga.example.invalid'),
    '渲染站': M.站点(名='渲染站', 详情正则=r'/chapter/(\d+)', 图片正则='',
                需渲染=True, 图选择器='img[data-src]', referer='render.example.invalid'),
}

_详情HTML = '''
<html><head><title>示例漫画_漫画_示例站</title></head><body>
<a href="/chapter/101">开始阅读</a>
<a href="/chapter/101">开始阅读</a>
<a href="/chapter/102">第2话 两个人的旅行</a>
<a href="/chapter/103">第3话 路</a>
<a href="/other/9">无关链接</a>
<a href="/chapter/104"><span>第4话</span> 雨</a>
</body></html>'''

_章HTML = '''
<html><body>
<img src="/static/img/logo.png">
<img data-src="https://img.example.invalid/1.jpg">
<img src="https://img.example.invalid/2.png">
<img data-original="https://img.example.invalid/3.webp?x=1">
<img src="https://img.example.invalid/icon-close.png">
</body></html>'''

_详情URL = 'https://manga.example.invalid/book/1'


class _基底(unittest.TestCase):

    def setUp(self):
        p = mock.patch.object(M, '_站点表', dict(_假表))
        p.start()
        self.addCleanup(p.stop)


class Test站点识别(_基底):

    def test_按域名识别(self):
        self.assertEqual(M.识别站点('https://manga.example.invalid/book/1'), 'http站')
        self.assertEqual(M.识别站点('https://render.example.invalid/book/2'), '渲染站')

    def test_未知站点(self):
        self.assertIsNone(M.识别站点('https://other.example.invalid/x'))


class Test章节列表(_基底):

    def test_解析与去重(self):
        章节s = M.解析章节列表(_详情HTML, _详情URL, 'http站')
        self.assertEqual(len(章节s), 4, '4 个不同章节, 重复链接去重')
        self.assertEqual([c.序号 for c in 章节s], [1, 2, 3, 4])

    def test_导航词回落为第N话(self):
        章节s = M.解析章节列表(_详情HTML, _详情URL, 'http站')
        self.assertEqual(章节s[0].标题, '第1话')

    def test_保留真实章名(self):
        章节s = M.解析章节列表(_详情HTML, _详情URL, 'http站')
        self.assertIn('第2话', 章节s[1].标题)
        self.assertIn('雨', 章节s[3].标题, '内层标签剥掉、文本保留')

    def test_无关链接被排除(self):
        章节s = M.解析章节列表(_详情HTML, _详情URL, 'http站')
        self.assertFalse(any('/other/' in c.url for c in 章节s))

    def test_相对链接补全(self):
        章节s = M.解析章节列表(_详情HTML, _详情URL, 'http站')
        self.assertTrue(all(c.url.startswith('https://manga.example.invalid/chapter/')
                            for c in 章节s))


class Test图片列表(_基底):

    def test_解析与过滤(self):
        urls = M.解析图片列表(_章HTML, 'https://manga.example.invalid/chapter/101', 'http站')
        self.assertEqual(len(urls), 3, 'logo/icon 必须被过滤')
        self.assertFalse(any('logo' in u or 'icon' in u for u in urls))

    def test_相对路径补全(self):
        夹具 = '<img src="/pics/5.jpg"><img data-src="../pics/6.png">'
        urls = M.解析图片列表(夹具, 'https://manga.example.invalid/chapter/101', 'http站')
        self.assertEqual(urls, ['https://manga.example.invalid/pics/5.jpg',
                                'https://manga.example.invalid/pics/6.png'])

    def test_渲染站不走正则(self):
        self.assertEqual(M.解析图片列表(_章HTML, 'https://render.example.invalid/c/1', '渲染站'), [])


class Test文件名(unittest.TestCase):

    def test_补零宽度随总页数(self):
        self.assertEqual(M.图片文件名(1, 'https://a/1.jpg', 22), '001.jpg')
        self.assertEqual(M.图片文件名(1, 'https://a/1.jpg', 1200), '0001.jpg')

    def test_后缀归一(self):
        self.assertEqual(M.图片文件名(2, 'https://a/x.jpeg', 10), '002.jpg')
        self.assertEqual(M.图片文件名(3, 'https://a/x.webp?t=1', 10), '003.webp')


class _假响应:
    def __init__(self, 内容: bytes, 状态: int = 200):
        self.content = 内容
        self.status_code = 状态


class Test下载(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_下载与断点续传(self):
        会话 = mock.Mock()
        会话.get.return_value = _假响应(b'x' * 4096)
        成功, 跳过 = M.下载章节图片(['https://a/1.jpg', 'https://a/2.jpg'], self.dir,
                              会话, 'https://a/ch1', 间隔=0)
        self.assertEqual((成功, 跳过), (2, 0))
        成功2, 跳过2 = M.下载章节图片(['https://a/1.jpg', 'https://a/2.jpg'], self.dir,
                                会话, 'https://a/ch1', 间隔=0)
        self.assertEqual((成功2, 跳过2), (0, 2), '已存在且非空必须跳过')

    def test_坏图与异常不中断(self):
        会话 = mock.Mock()
        会话.get.side_effect = [_假响应(b'x' * 4096), _假响应(b'x' * 10), OSError('boom')]
        记录 = []
        成功, _ = M.下载章节图片(
            ['https://a/1.jpg', 'https://a/2.jpg', 'https://a/3.jpg'], self.dir,
            会话, 'https://a/ch1', 间隔=0, 日志=记录.append)
        self.assertEqual(成功, 1, '只有第 1 张成功')
        self.assertEqual(len(记录), 2, '坏图与异常各记一条')

    def test_HTTP错误不落盘(self):
        会话 = mock.Mock()
        会话.get.return_value = _假响应(b'x' * 4096, 状态=404)
        成功, _ = M.下载章节图片(['https://a/1.jpg'], self.dir, 会话, 'https://a/ch1', 间隔=0)
        self.assertEqual(成功, 0)
        self.assertEqual(list(self.dir.glob('*')), [])


class TestCBZ(unittest.TestCase):

    def test_打包每章(self):
        with tempfile.TemporaryDirectory() as tmp:
            根 = Path(tmp)
            for 章 in ('001_第1话', '002_第2话'):
                d = 根 / 章
                d.mkdir()
                (d / '001.jpg').write_bytes(b'x' * 4096)
                (d / '002.jpg').write_bytes(b'x' * 4096)
            cbzs = M.导出CBZ(根)
            self.assertEqual(len(cbzs), 2)
            with zipfile.ZipFile(cbzs[0]) as z:
                self.assertEqual(sorted(z.namelist()), ['001.jpg', '002.jpg'])

    def test_空章不生成(self):
        with tempfile.TemporaryDirectory() as tmp:
            根 = Path(tmp)
            (根 / '001_空章').mkdir()
            self.assertEqual(M.导出CBZ(根), [])


class Test未配置站点(unittest.TestCase):

    def test_未识别站点给配置指引(self):
        with mock.patch.object(M, '_站点表', {}):
            with self.assertRaises(ValueError) as ctx:
                M.抓整本('https://nope.example.invalid/x', Path(tempfile.gettempdir()))
            self.assertIn('漫画站点.json', str(ctx.exception))


class Test长任务稳定(unittest.TestCase):
    """2026-11-10 实测: 同一浏览器连跑约 30 章后渲染退化, 之后每章都取不到图
    (手动重开浏览器立刻恢复)。抓整本必须周期性重建 + 失败重试。"""

    def test_有周期性重建与失败重试(self):
        源码 = (Path(__file__).resolve().parent.parent / '源码' / '漫画抓取.py')             .read_text(encoding='utf-8')
        self.assertIn('已渲染章数', 源码)
        self.assertIn('重建浏览器', 源码)
        self.assertIn('>= 15', 源码, '每 15 章重建一次')
        self.assertIn('取图为空, 重建浏览器重试', 源码, '失败要重试一次')


if __name__ == '__main__':
    unittest.main(verbosity=2)
