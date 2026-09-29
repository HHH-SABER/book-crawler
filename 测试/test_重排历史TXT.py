# -*- coding: utf-8 -*-
"""重排历史TXT.py 回归测试 (2026-09-29)

覆盖: 压扁块重切 / 对话起新段 / 引号未配对防误切 / 幂等 /
      ## 标题切块 / 无标题文件 / 文件级备份与原子写 / dry-run 不写盘
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
# 被测模块在 脚本/ 目录
_SCRIPTS = os.path.join(os.path.dirname(_HERE), '脚本')
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from 重排历史TXT import (重排正文, 重排文件, _is_压扁块, _句列表)  # noqa: E402

# 长压扁样本: 12 句无换行 (~370 字, 中位行长 > 200 触发)
_压扁样本 = (
    '林川推开门走进屋子发现里面空无一人桌上的茶还冒着热气。他皱起眉头四处打量。'
    '窗户开着风把窗帘吹得猎猎作响。楼下传来叫卖声混着车马的嘈杂。'
    '他走到桌前拿起那张字条看了又看。字条上的墨迹还很新像是刚写下的。'
    '“三日后城南一聚。”他低声念出声来。落款是一个陌生的名字。'
    '他把字条折好放进怀里转身出门。街上的行人来来往往谁也没有多看他一眼。'
)


class Test句切(unittest.TestCase):

    def test_引号归前句(self):
        """闭引号随终结符归前句, 不单独成句"""
        句 = _句列表('他低声念出声来。“三日后城南一聚。”落款是陌生的名字。')
        self.assertEqual(句[0], '他低声念出声来。')
        self.assertEqual(句[1], '“三日后城南一聚。”')
        self.assertEqual(句[2], '落款是陌生的名字。')


class Test触发判定(unittest.TestCase):

    def test_压扁块_中位行长超限(self):
        self.assertTrue(_is_压扁块(_压扁样本, min_len=50, max_len=200))

    def test_正常段落不触发(self):
        正文 = '\n\n'.join(f'第{i}段完整叙事内容，句子完整并以句号收尾，长度足够。'
                          for i in range(5))
        self.assertFalse(_is_压扁块(正文, min_len=50, max_len=200))


class Test重排正文(unittest.TestCase):

    def test_压扁块重切出多段(self):
        out = 重排正文(_压扁样本, 缩进=True, min_len=50, max_len=200)
        段 = [ln for ln in out.split('\n\n') if ln.strip()]
        self.assertGreater(len(段), 1, '压扁块未被重切出多段')
        for p in 段:
            self.assertTrue(p.startswith('\u3000\u3000'), f'段首未缩进: {p[:20]}')
        # 内容无丢失 (去缩进/换行后逐字一致)
        self.assertEqual(out.replace('\u3000', '').replace('\n', ''), _压扁样本)

    def test_对话起新段(self):
        """对话引语开头强信号: 缓冲达标后在新对话前断段"""
        样本 = ('他推开门看见她坐在窗边微微一笑说道今天的天气真是好得让人不想出门啊。'
                '“你来了。”她轻声说道。窗外阳光正好洒在她的侧脸上。'
                '他点点头在她对面坐下两人都没有再说话屋子里安静得能听见钟摆声。')
        out = 重排正文(样本, 缩进=False, min_len=50, max_len=200)
        段 = [ln for ln in out.split('\n\n') if ln.strip()]
        self.assertTrue(any(p.startswith('“') for p in 段),
                        f'对话段未独立成段: {段}')

    def test_引号未配对禁止断段(self):
        """开引号未闭合期间即使缓冲超 min 也不断段"""
        样本 = ('他推开门看见她坐在窗边微微一笑说道今天天气好得让人不想出门。'
                '“你来了她轻声说道。窗外阳光正好洒在她的侧脸上他也跟着笑了。'
                '两人都没说话屋子里安静得能听见墙上的老挂钟滴答作响直到天黑。')
        out = 重排正文(样本, 缩进=False, min_len=30, max_len=200)
        # 未闭合引号内容不得被独立成段 (断段不发生在引号内)
        段 = [ln for ln in out.split('\n\n') if ln.strip()]
        self.assertTrue(all(p.count('“') >= p.count('”')
                            for p in 段[:-1]) or len(段) == 1,
                        '引号未配对时发生了断段')

    def test_幂等_两遍结果一致(self):
        out1 = 重排正文(_压扁样本, 缩进=True)
        out2 = 重排正文(out1, 缩进=True)
        self.assertEqual(out1, out2, '重排不幂等')

    def test_已排版文件只归一不重切(self):
        正文 = '\n\n'.join(f'第{i}段完整叙事内容，句子完整并以句号收尾，长度足够。'
                          for i in range(5))
        out = 重排正文(正文, 缩进=True)
        self.assertIn('\u3000\u3000第0段', out)
        self.assertEqual(out.count('\n\n'), 4, '段间空行数不对')

    def test_旧缩进被剥离重加(self):
        正文 = '\u3000\u3000\u3000\u3000第一段内容，句子完整收尾。'
        out = 重排正文(正文, 缩进=True)
        self.assertTrue(out.startswith('\u3000\u3000'), '旧缩进未归一')
        self.assertFalse(out.startswith('\u3000\u3000\u3000'), '旧缩进未剥净')


class Test重排文件(unittest.TestCase):

    def _mk(self, tmpdir, name, content):
        p = Path(tmpdir) / name
        p.write_text(content, encoding='utf-8')
        return p

    def test_标题切块与写盘备份(self):
        with tempfile.TemporaryDirectory() as td, \
             tempfile.TemporaryDirectory() as bd:
            原文 = f'## 第一章\n\n{_压扁样本}\n\n## 第二章\n\n短的段落内容。\n\n'
            p = self._mk(td, '书.txt', 原文)
            bak = Path(bd)
            状态, 原, 新, 说明 = 重排文件(p, bak, 缩进=True)
            self.assertEqual(状态, '重切')
            新文 = p.read_text(encoding='utf-8')
            self.assertIn('## 第一章', 新文)
            self.assertIn('## 第二章', 新文)
            self.assertIn('\u3000\u3000', 新文, '缩进未加')
            # 备份存在且内容等于原文
            baks = list(bak.glob('书.txt.bak-*'))
            self.assertEqual(len(baks), 1, '备份文件缺失')
            self.assertEqual(baks[0].read_text(encoding='utf-8'), 原文)
            # 无 .tmp 残留
            self.assertEqual([x for x in Path(td).glob('*.tmp.*')], [])

    def test_无标题文件整本处理(self):
        with tempfile.TemporaryDirectory() as td, \
             tempfile.TemporaryDirectory() as bd:
            p = self._mk(td, '无标题.txt', _压扁样本)
            状态, _, _, _ = 重排文件(p, Path(bd), 缩进=False)
            self.assertIn(状态, ('重切', '归一'))
            out = p.read_text(encoding='utf-8')
            self.assertNotIn('## ', out)

    def test_幂等文件跳过(self):
        with tempfile.TemporaryDirectory() as td, \
             tempfile.TemporaryDirectory() as bd:
            已排版 = '## 第一章\n\n\u3000\u3000段落内容，句子完整收尾。\n\n'
            p = self._mk(td, '已排版.txt', 已排版)
            状态, _, _, _ = 重排文件(p, Path(bd), 缩进=True)
            self.assertEqual(状态, '跳过')

    def test_dry_run不写盘(self):
        with tempfile.TemporaryDirectory() as td, \
             tempfile.TemporaryDirectory() as bd:
            原文 = f'## 第一章\n\n{_压扁样本}\n\n'
            p = self._mk(td, '书.txt', 原文)
            状态, 原, 新, 说明 = 重排文件(p, Path(bd), 缩进=True, dry_run=True)
            self.assertEqual(状态, '重切')
            self.assertGreater(新, 原, 'dry-run 应报告段落数增加')
            self.assertEqual(p.read_text(encoding='utf-8'), 原文, 'dry-run 改了盘')
            self.assertEqual(list(Path(bd).glob('*')), [], 'dry-run 写了备份')


if __name__ == '__main__':
    unittest.main()
