# -*- coding: utf-8 -*-
"""日志模块回归 (2026-09-27 排查批):

① 轮转字节精确记账: Windows 文本模式默认把 \n 译成 \r\n, 磁盘字节比
   _cur_size 逐行多 1 字节 —— 65960 行累计多出 ~66KB, 轮转点从 5MB 漂移到
   5.30MB (washai 全本实测)。修复后 newline='\n' 直写 LF, 记账必须与磁盘一致。
② 高频 HTML 预览降级: 爬虫 inspect_page 的 "解码后内容前500个字符" 原为
   INFO 级 (每页 1 次 × 500 字符), 是日志洪流与 GUI 实时面板刷屏的主源,
   契约锁定其为 debug 级, 防回退。

运行 (项目根): python -m unittest discover -s 测试 -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '源码'))

import 日志 as log_mod                       # noqa: E402


class Test轮转字节记账(unittest.TestCase):
    """newline='\n' 后 _cur_size 必须与磁盘字节数严格一致"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='log_rotate_')
        self.logger = log_mod.AppLogger()
        # 单例现场保护: 换日志目录 + 重置轮转状态, 退出后恢复
        self._saved = {k: getattr(self.logger, k, None)
                       for k in ('_file', '_file_path', '_cur_date', '_cur_size',
                                 '_level')}
        self._saved_console = log_mod._console_enabled
        try:
            self.logger._file.close()
        except Exception:
            pass
        self.logger._file = None
        self.logger._file_path = None
        self.logger._cur_date = None
        self.logger._cur_size = 0
        self.logger._level = log_mod.INFO
        log_mod._console_enabled = False
        patcher = mock.patch.object(log_mod, 'get_log_dir',
                                    return_value=self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        try:
            self.logger._file.close()
        except Exception:
            pass
        for k, v in self._saved.items():
            setattr(self.logger, k, v)
        log_mod._console_enabled = self._saved_console

    def _路径(self, name):
        return os.path.join(self.tmp, name)

    def test_记账与磁盘字节严格一致(self):
        """含中文/内嵌换行的多行消息, _cur_size 必须等于 getsize (修复前每行少计1字节)"""
        多行消息 = '第一行内容\n第二行内容 with ascii\n第三行中文标签[任务task_1]'
        for _ in range(50):
            self.logger.info('测试源', 多行消息)
            self.logger.debug('测试源', '单行 debug 消息 Chinese+ascii 123')
        path = self._路径(time_name(0))
        self.assertEqual(os.path.getsize(path), self.logger._cur_size,
                         '日志记账字节数与磁盘实际大小不一致 (CRLF 漂移?)')

    def test_轮转在5MB边界触发且不超写(self):
        """写满 5MB 后轮转: 基础文件不超过 5MB+单行上限, 序号文件出现"""
        big = 'x' * 9000 + '中' * 500   # ~10KB/行 (UTF-8 中文 3 字节/字)
        写入 = 0
        for _ in range(560):            # 560 × ~10KB ≈ 5.6MB > 5MB, 必触发轮转
            self.logger.info('测试源', big)
            写入 += 1
        base = self._路径(time_name(0))
        seq1 = self._路径(time_name(1))
        self.assertTrue(os.path.exists(seq1), '超过 5MB 未发生轮转')
        self.assertLessEqual(os.path.getsize(base), 5 * 1024 * 1024 + len(big.encode()) * 3,
                             '轮转前基础文件超写超过单行上限 (记账漂移)')
        # 记账依旧精确 (轮转后的当前文件)
        self.assertEqual(os.path.getsize(seq1), self.logger._cur_size)


def time_name(seq):
    import time as _t
    d = _t.strftime('%Y-%m-%d')
    return f'{d}.log' if seq == 0 else f'{d}_{seq}.log'


class Test高频预览日志级别契约(unittest.TestCase):
    """inspect_page 的原始 HTML 预览必须保持 debug 级 (日志洪流防护)"""

    def test_解码预览为debug级(self):
        src = (_PROJECT_ROOT / '源码' / '爬虫.py').read_text(encoding='utf-8')
        self.assertIn('_log.debug(f"解码后内容前500个字符', src,
                      'HTML 预览被改回 INFO 级会重建日志洪流 (66k 行/全本)')
        self.assertNotIn('_log.info(f"解码后内容前500个字符', src)


if __name__ == '__main__':
    unittest.main(verbosity=2)
