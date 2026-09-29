# -*- coding: utf-8 -*-
"""build_exe dist 用户数据保护回归 (2026-09-29, R4 定案)。

背景: 每次重打包 rmtree(dist) 连带删掉 dist/抓取结果/ (小说正文+检查点)
与 dist 旁用户手改的 站点配置.json / captcha_config.json (含 ddddocr 开关,
"更新 EXE 后成功率降低"的根因)。修复: 清理前 stash 到临时目录, 构建结束
(无论成败) 原样恢复; 目录级恢复为逐文件合并且不覆盖已存在文件。

运行 (项目根): python -m unittest discover -s 测试 -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '脚本'))

import build_exe                        # noqa: E402


class Test保护与恢复dist用户数据(unittest.TestCase):
    """stash → 清空 → restore 的数据保全契约"""

    def setUp(self):
        self.dist = tempfile.mkdtemp(prefix='preserve_dist_')
        self.addCleanup(lambda: _强行清理(self.dist))
        # 造用户数据: 目录 (抓取结果含子目录) + 两份用户 JSON
        抓取 = Path(self.dist, '抓取结果')
        (抓取 / '子目录').mkdir(parents=True)
        (抓取 / '某书.txt').write_text('正文内容', encoding='utf-8')
        (抓取 / '某书.txt.checkpoint.json').write_text('{"total": 9}',
                                                       encoding='utf-8')
        (抓取 / '子目录' / '报告.txt').write_text('子目录文件', encoding='utf-8')
        Path(self.dist, '站点配置.json').write_text('{"sites": {"a": 1}}',
                                                   encoding='utf-8')
        Path(self.dist, 'captcha_config.json').write_text(
            '{"strategies": {"ddddocr": {"enabled": true}}}', encoding='utf-8')
        # 非保护条目 (构建产物): 不应被 stash
        Path(self.dist, '小说爬虫.exe').write_bytes(b'MZ')

    def test_保护暂存并移出dist(self):
        stash = build_exe.保护dist用户数据(self.dist)
        self.assertTrue(stash and os.path.isdir(stash))
        # 用户数据已离开 dist
        self.assertFalse(os.path.exists(Path(self.dist, '抓取结果')))
        self.assertFalse(os.path.exists(Path(self.dist, '站点配置.json')))
        self.assertFalse(os.path.exists(Path(self.dist, 'captcha_config.json')))
        # 构建产物不在保护范围
        self.assertTrue(os.path.isfile(Path(self.dist, '小说爬虫.exe')))
        # stash 内数据完整
        self.assertEqual(
            Path(stash, '抓取结果', '某书.txt').read_text(encoding='utf-8'),
            '正文内容')
        self.assertEqual(
            Path(stash, 'captcha_config.json').read_text(encoding='utf-8'),
            '{"strategies": {"ddddocr": {"enabled": true}}}')

    def test_空dist返回空stash(self):
        空 = tempfile.mkdtemp(prefix='preserve_empty_')
        self.addCleanup(lambda: _强行清理(空))
        self.assertEqual(build_exe.保护dist用户数据(空), '')

    def test_恢复往返字节级一致(self):
        stash = build_exe.保护dist用户数据(self.dist)
        # 模拟重打包: 清掉整个 dist 再重建空目录 (构建只会生成 exe)
        import shutil as _sh
        _sh.rmtree(self.dist)
        os.makedirs(self.dist, exist_ok=True)
        Path(self.dist, '小说爬虫.exe').write_bytes(b'MZ-new')
        build_exe.恢复dist用户数据(self.dist, stash)
        self.assertEqual(
            Path(self.dist, '抓取结果', '某书.txt').read_text(encoding='utf-8'),
            '正文内容')
        self.assertEqual(
            Path(self.dist, '抓取结果', '某书.txt.checkpoint.json').read_text(
                encoding='utf-8'), '{"total": 9}')
        self.assertEqual(
            Path(self.dist, '抓取结果', '子目录', '报告.txt').read_text(
                encoding='utf-8'), '子目录文件')
        self.assertEqual(
            Path(self.dist, '站点配置.json').read_text(encoding='utf-8'),
            '{"sites": {"a": 1}}')
        self.assertTrue(
            Path(self.dist, 'captcha_config.json').read_text(
                encoding='utf-8').count('ddddocr'), 'ddddocr 配置应保留')
        self.assertTrue(os.path.isfile(Path(self.dist, '小说爬虫.exe')),
                        '构建产物不应被恢复动作影响')
        self.assertFalse(os.path.isdir(stash), 'stash 应被清理')

    def test_恢复不覆盖已存在文件(self):
        stash = build_exe.保护dist用户数据(self.dist)
        # dist 侧同名文件已存在 (如新构建生成) → 保留新文件
        Path(self.dist, '站点配置.json').write_text('{"new": true}',
                                                   encoding='utf-8')
        build_exe.恢复dist用户数据(self.dist, stash)
        self.assertEqual(
            Path(self.dist, '站点配置.json').read_text(encoding='utf-8'),
            '{"new": true}', '同名已存在时不得覆盖')

    def test_无效stash参数时无操作不抛错(self):
        build_exe.恢复dist用户数据(self.dist, '')          # 空 stash
        build_exe.恢复dist用户数据(self.dist, 'Z:/不存在的目录')  # 不存在
        self.assertTrue(os.path.isfile(Path(self.dist, '站点配置.json')))


def _强行清理(path):
    import shutil
    shutil.rmtree(path, ignore_errors=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
