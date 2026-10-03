# -*- coding: utf-8 -*-
"""组装发布目录的**行为**验证 (2026-10-04, 八项需求 #4 隐私整改)。

背景: 旧 `脚本/组装发布.py` 把 `站点适配_本地/`(真实适配器 + 域名映射 + cookies)
复制进名为"正式发布版"的目录, 且 `--zip` 会一并打包 —— 与脚本自身"严禁外传"文案矛盾。
旧测试只断言脚本文本里出现若干部位名, **反而把该行为锁成了契约**。

本文件改为端到端验证真实产物:
  1. 默认产出**公开包**: 无私有适配目录 / 无用户数据 / 清单为空模板 / 自检通过;
  2. `--含本地适配器` 才产**本机包**(目录名带 `_本机`), 且对其打 zip 需二次确认;
  3. 自检能**真的抓到**混进产物的隐私文件(兜底而非摆设)。
"""
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import _沙箱  # noqa: F401  沙箱: LOCALAPPDATA → 一次性临时目录

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / '脚本'))

import 组装发布  # noqa: E402


class Test组装发布隐私(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix='nc_rel_'))
        # 假 dist: 程序本体 + 公开适配 + 私有适配 + 用户数据
        (self.tmp / '脚本').mkdir(parents=True, exist_ok=True)
        (self.tmp / '脚本' / '版本.json').write_text(
            json.dumps({'版本': '9.9.9'}, ensure_ascii=False), encoding='utf-8')
        dist = self.tmp / 'dist'
        (dist / '站点适配').mkdir(parents=True)
        (dist / '站点适配' / '_模板.py').write_text('# 公开占位', encoding='utf-8')
        (dist / '站点适配_本地').mkdir(parents=True)
        (dist / '站点适配_本地' / '某站.py').write_text('# 真实适配器', encoding='utf-8')
        (dist / '站点适配_本地' / '域名映射.json').write_text('{"a":"b"}', encoding='utf-8')
        (dist / '小说爬虫.exe').write_bytes(b'MZ' + b'\0' * 1024)
        (dist / '站点配置.json').write_text('{"本机":"配置"}', encoding='utf-8')
        (dist / 'captcha_config.json').write_text('{}', encoding='utf-8')
        (dist / '抓取结果').mkdir()
        (dist / '抓取结果' / '某书.txt').write_text('正文', encoding='utf-8')

        self._备份 = (组装发布.ROOT, 组装发布.DIST, 组装发布.发布根)
        组装发布.ROOT = self.tmp
        组装发布.DIST = dist
        组装发布.发布根 = self.tmp / '发布'

    def tearDown(self):
        组装发布.ROOT, 组装发布.DIST, 组装发布.发布根 = self._备份
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _跑(self, *argv):
        with mock.patch.object(sys, 'argv', ['组装发布.py', *argv]):
            with redirect_stdout(io.StringIO()) as buf:
                code = 组装发布.main()
        return code, buf.getvalue()

    def test_默认产出公开包_不含私有适配与用户数据(self):
        code, out = self._跑('--版本=9.9.9')
        self.assertEqual(code, 0, out)
        pkg = self.tmp / '发布' / '小说爬虫_v9.9.9'
        self.assertTrue((pkg / '小说爬虫.exe').is_file())
        self.assertTrue((pkg / '站点适配' / '_模板.py').is_file(), '公开适配目录应保留')
        self.assertFalse((pkg / '站点适配_本地').exists(), '公开包不得含私有适配目录')
        for 禁 in ('站点配置.json', 'captcha_config.json', '抓取结果'):
            self.assertFalse((pkg / 禁).exists(), f'公开包不得含 {禁}')
        self.assertEqual((pkg / '网站清单.txt').read_text(encoding='utf-8'),
                         组装发布._网站清单模板(), '清单必须是空模板')

    def test_含本地开关才产本机包且目录名带本机(self):
        code, out = self._跑('--版本=9.9.9', '--含本地适配器')
        self.assertEqual(code, 0, out)
        pkg = self.tmp / '发布' / '小说爬虫_v9.9.9_本机'
        self.assertTrue(pkg.is_dir(), '本机包目录名应带 _本机 以便一眼识别')
        self.assertTrue((pkg / '站点适配_本地' / '域名映射.json').is_file())
        self.assertFalse((self.tmp / '发布' / '小说爬虫_v9.9.9').exists(),
                         '两种形态不应混在同一目录')

    def test_本机包打zip需二次确认(self):
        code, out = self._跑('--版本=9.9.9', '--含本地适配器', '--zip')
        self.assertEqual(code, 5, f'应拒绝为本机包打 zip, 实际 {code}\n{out}')
        self.assertIn('拒绝', out)

    def test_隐私自检能抓到混入的checkpoint(self):
        """兜底有效性: 白名单复制之外, 自检必须真的拦得住"""
        (组装发布.DIST / '站点适配' / '_x.checkpoint.json').write_text('{}', encoding='utf-8')
        code, out = self._跑('--版本=9.9.9')
        self.assertEqual(code, 3, f'自检应拦下 checkpoint, 实际 {code}\n{out}')
        self.assertIn('隐私自检未通过', out)

    def test_重建保护_目录非本脚本生成时中止(self):
        pkg = self.tmp / '发布' / '小说爬虫_v9.9.9'
        pkg.mkdir(parents=True)
        (pkg / '用户自己的文件.txt').write_text('x', encoding='utf-8')
        code, out = self._跑('--版本=9.9.9')
        self.assertEqual(code, 2, out)
        self.assertIn('疑似非本脚本生成', out)
        self.assertTrue((pkg / '用户自己的文件.txt').is_file(), '不得删掉用户目录')


if __name__ == '__main__':
    unittest.main(verbosity=2)
