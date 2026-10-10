# -*- coding: utf-8 -*-
"""C10 第一步: 「还原被隔离副本」的回归用例 (离线)。

背景: `执行清理(模式='隔离')` 与自动去重都号称"可反悔"地移入 `_已去重/`,
但此前**没有任何代码路径能把文件取回来** —— 界面也不展示已清理记录。
本用例守 `去重处理.还原副本()` 的语义与三条安全边界。

运行方式 (项目根目录):
    python -m unittest discover -s 测试 -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '源码'))
sys.path.insert(0, str(_PROJECT_ROOT / '测试'))

import _沙箱                      # noqa: E402,F401  状态根沙箱 (清单落在临时目录)
import 去重处理 as D              # noqa: E402


class Test还原副本(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.结果 = Path(self._tmp.name) / '抓取结果'
        self.结果.mkdir()
        self.隔离 = self.结果 / D.隔离目录名
        self.隔离.mkdir()
        # 代表项 (保留项) 真实存在 —— 还原目录由它推导
        self.代表 = self.结果 / '示例书名甲.txt'
        self.代表.write_text('正文' * 50, encoding='utf-8')

    def _写隔离(self, 名: str, 内容: str = '副本正文'):
        路径 = self.隔离 / 名
        路径.write_text(内容, encoding='utf-8')
        return 路径

    def _存记录(self, 可自动清理, 待确认=None, 键='k1'):
        记录 = {
            '键': 键,
            '代表': {'路径': str(self.代表), '名': self.代表.name,
                     '字数': 100, '字节': 200},
            '可自动清理': 可自动清理,
            '待确认': 待确认 or [],
            '状态': D.状态_已清理,
            '最近时间': '2026-10-11 00:00',
            '次数': 1,
            '首次时间': '2026-10-11 00:00',
        }
        D.保存([记录])
        return 记录

    # ---------------------------------------------------------- 正常路径
    def test_还原把文件移回原位置(self):
        self._写隔离('示例书名甲(1).txt')
        self._存记录([{'路径': str(self.结果 / '示例书名甲(1).txt'),
                    '名': '示例书名甲(1).txt', '字数': 50, '字节': 100,
                    '判定': '真子集', '理由': 'r', '指标': {}}])
        r = D.还原副本('k1', '示例书名甲(1).txt')
        self.assertEqual(r['失败'], '', r)
        self.assertEqual(r['还原'], '示例书名甲(1).txt')
        self.assertTrue((self.结果 / '示例书名甲(1).txt').is_file(), '应已移回原位置')
        self.assertFalse((self.隔离 / '示例书名甲(1).txt').exists(), '隔离区不应再有它')
        self.assertEqual(r['剩余条目'], 0)
        # 该组已无可跟踪项 → 记录整条移除
        self.assertEqual([x for x in D.载入() if x.get('键') == 'k1'], [])

    def test_组内还有其它条目时记录保留(self):
        self._写隔离('甲.txt')
        self._写隔离('乙.txt')
        self._存记录([
            {'路径': str(self.结果 / '甲.txt'), '名': '甲.txt', '字数': 1,
             '字节': 1, '判定': '真子集', '理由': 'r', '指标': {}},
            {'路径': str(self.结果 / '乙.txt'), '名': '乙.txt', '字数': 1,
             '字节': 1, '判定': '真子集', '理由': 'r', '指标': {}},
        ])
        r = D.还原副本('k1', '甲.txt')
        self.assertEqual(r['失败'], '')
        self.assertEqual(r['剩余条目'], 1)
        剩 = [x for x in D.载入() if x.get('键') == 'k1']
        self.assertEqual(len(剩), 1, '记录应保留')
        self.assertEqual([x['名'] for x in 剩[0]['可自动清理']], ['乙.txt'])

    def test_待确认项也能还原(self):
        self._写隔离('灰区.txt')
        self._存记录([], [{'路径': str(self.结果 / '灰区.txt'), '名': '灰区.txt',
                        '字数': 1, '字节': 1, '判定': '疑似(待人工确认)',
                        '理由': 'r', '指标': {}}])
        r = D.还原副本('k1', '灰区.txt')
        self.assertEqual(r['失败'], '')
        self.assertTrue((self.结果 / '灰区.txt').is_file())

    # ---------------------------------------------------------- 安全边界
    def test_目标同名不覆盖_加还原序号(self):
        self._写隔离('示例书名甲(1).txt', '隔离里的副本')
        # 原位置已被别的内容占住
        占 = self.结果 / '示例书名甲(1).txt'
        占.write_text('原有正文, 不许被覆盖', encoding='utf-8')
        self._存记录([{'路径': str(占), '名': '示例书名甲(1).txt', '字数': 1,
                    '字节': 1, '判定': '真子集', '理由': 'r', '指标': {}}])
        r = D.还原副本('k1', '示例书名甲(1).txt')
        self.assertEqual(r['失败'], '', r)
        self.assertEqual(占.read_text(encoding='utf-8'), '原有正文, 不许被覆盖',
                         '既有正文绝不能被覆盖')
        self.assertTrue(Path(r['目标']).is_file())
        self.assertIn('(还原1)', r['目标'])

    def test_拒绝越界名(self):
        记录 = self._存记录([{'路径': str(self.结果 / 'x.txt'), '名': '../x.txt',
                          '字数': 1, '字节': 1, '判定': '真子集', '理由': 'r',
                          '指标': {}}])
        self.assertIsNotNone(记录)
        r = D.还原副本('k1', '../x.txt')
        self.assertNotEqual(r['失败'], '', '越界必须被拒')

    def test_隔离区没有该文件时失败(self):
        self._存记录([{'路径': str(self.结果 / '缺.txt'), '名': '缺.txt', '字数': 1,
                    '字节': 1, '判定': '真子集', '理由': 'r', '指标': {}}])
        r = D.还原副本('k1', '缺.txt')
        self.assertIn('没有这个文件', r['失败'])

    def test_无此键或无此名时失败(self):
        self._写隔离('甲.txt')
        self._存记录([{'路径': str(self.结果 / '甲.txt'), '名': '甲.txt', '字数': 1,
                    '字节': 1, '判定': '真子集', '理由': 'r', '指标': {}}])
        self.assertIn('无此键', D.还原副本('不存在的键', '甲.txt')['失败'])
        self.assertIn('没有这个文件名', D.还原副本('k1', '不存在.txt')['失败'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
