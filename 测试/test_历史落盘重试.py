# -*- coding: utf-8 -*-
"""爬取历史落盘重试测试 (2026-10-17, 实测倒逼)。

背景: EXE 抓取回归时日志反复出现 "[历史] 保存失败 (保留脏标记供重试):
[WinError 5] 拒绝访问" (10-14 六次 / 10-15 两次 / 10-17 两次)。
根因: `_合并磁盘新数据` (U16) 每次落盘前 open() 读目标文件 (9.5MB, 几百毫秒),
读句柄默认不带 FILE_SHARE_DELETE, 与锁外的 os.replace (U17) 重叠 ⇒ 拒绝访问。

本文件锁定 `_原子替换` 的契约:
  ① 正常路径一次成功, 无多余调用;
  ② 遇 ERROR_ACCESS_DENIED(5)/SHARING_VIOLATION(32)/EACCES(13)/EBUSY(16)
     退避重试后成功 (竞态自愈);
  ③ **不可重试错误立即抛** (如磁盘满 ENOSPC=28), 不浪费 0.6s;
  ④ 持续可重试失败抛最后一次异常 (由调用方走脏标记降级, 不吞异常);
  ⑤ 成功路径不留临时文件。
运行: python -m unittest discover -s 测试
"""
import errno
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

import 爬取历史 as H   # noqa: E402


def _win错误(号):
    """造一个带 winerror 的 OSError (Windows 语义)。"""
    return OSError(号, f'模拟 WinError {号}', None, 号)


class Test原子替换重试(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.目标 = self.tmp / '爬取历史.json'
        self.目标.write_text('{}', encoding='utf-8')
        self.源 = self.tmp / 'src.tmp'
        self.源.write_text('{"a":1}', encoding='utf-8')

    def tearDown(self):
        self._tmp.cleanup()

    def test_正常路径一次成功(self):
        with mock.patch('爬取历史.os.replace') as m:
            H._原子替换(self.源, self.目标)
        self.assertEqual(m.call_count, 1, '无竞争时不应重试')

    def test_拒绝访问后重试成功(self):
        """竞态自愈: 第一次 WinError 5, 第二次成功"""
        with mock.patch('爬取历史.os.replace',
                        side_effect=[_win错误(5), None]) as m:
            H._原子替换(self.源, self.目标)
        self.assertEqual(m.call_count, 2)

    def test_共享冲突也重试(self):
        with mock.patch('爬取历史.os.replace',
                        side_effect=[_win错误(32), None]) as m:
            H._原子替换(self.源, self.目标)
        self.assertEqual(m.call_count, 2)

    def test_持续失败抛最后一次(self):
        错误序列 = [_win错误(5)] * 4
        with mock.patch('爬取历史.os.replace', side_effect=错误序列) as m:
            with self.assertRaises(OSError) as ctx:
                H._原子替换(self.源, self.目标)
        self.assertEqual(m.call_count, 4, '最多 4 次 (立即+50/150/400ms)')
        self.assertEqual(getattr(ctx.exception, 'winerror', None), 5,
                         '应抛最后一次异常, 不吞 (调用方要靠它走脏标记降级)')

    def test_不可重试错误立即抛(self):
        """磁盘满 (ENOSPC=28) 之类重试无意义 —— 立即抛, 不白等 0.6s"""
        with mock.patch('爬取历史.os.replace',
                        side_effect=OSError(errno.ENOSPC, 'No space left')) as m:
            with self.assertRaises(OSError):
                H._原子替换(self.源, self.目标)
        self.assertEqual(m.call_count, 1, '不可重试错误不得重试')

    def test_真实替换行为保持(self):
        """不 mock: 真替换生效, 源消失, 内容正确, 无 tmp 残留"""
        H._原子替换(self.源, self.目标)
        self.assertFalse(self.源.exists(), '替换后源应消失')
        self.assertEqual(self.目标.read_text(encoding='utf-8'), '{"a":1}')
        残留 = list(self.tmp.glob('*.tmp*'))
        self.assertEqual(残留, [], f'不应留临时文件: {残留}')

    @unittest.skipIf(os.name != 'nt', '仅 Windows: 读句柄挡 replace 的语义')
    def test_真实读句柄竞争机制实锤(self):
        """**机制测试** (不是逻辑测试): 持读句柄时裸 os.replace 真的报
        WinError 5 —— 这正是 "[历史] 保存失败" 的成因, 也是 _原子替换 存在
        的理由。若将来有人想删重试, 本用例会告诉他删了会怎样。
        (Python 的 open() 在 Windows 上默认不带 FILE_SHARE_DELETE。)"""
        句柄 = open(self.目标, 'r', encoding='utf-8')
        try:
            with self.assertRaises(OSError) as ctx:
                os.replace(self.源, self.目标)
            self.assertIn(getattr(ctx.exception, 'winerror', None), (5, 32),
                          f'预期拒绝访问/共享冲突, 实得: {ctx.exception!r}')
        finally:
            句柄.close()
        # 句柄关闭后竞争消失, 重试版立即可用 (自愈路径的真实对应)
        H._原子替换(self.源, self.目标)
        self.assertEqual(self.目标.read_text(encoding='utf-8'), '{"a":1}')


class Test落盘接线(unittest.TestCase):
    """_落盘 确实走 _原子替换 (防将来被改回裸 os.replace)"""

    def test_落盘调用原子替换(self):
        实例 = object.__new__(H.爬取历史)
        实例._file = str(self.tmp / 'h.json')
        实例._落盘锁 = __import__('threading').Lock()
        实例._io_lock = __import__('threading').Lock()
        实例._版本 = 1
        实例._已落盘版本 = -1
        实例._上次落盘 = 0.0
        实例._脏 = False
        with mock.patch('爬取历史._原子替换') as m:
            实例._落盘(H._版本快照('{"x":1}', 1))
        m.assert_called_once()
        目标 = Path(m.call_args[0][1]).name
        self.assertEqual(目标, 'h.json')

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


if __name__ == '__main__':
    unittest.main(verbosity=2)
