# -*- coding: utf-8 -*-
"""C8 同名不同文检测 (换字/防盗版副本) 的回归用例 (离线)。

背景 (2026-10-10 实测): 两份各约 18 MB、各约 2020 章的同一部小说, **句集重合仅 J=0.002**
—— 换字副本把每个字都换了, 内容指纹**天然抓不到**, 走 `判定对` 只会得到「不同」而完全静默。
只能靠"标题相同 + 体量相当 + 正文几乎不重合"三条一起提示人工。

本文件守三件事:
  ① 三条信号**同时成立**才报 (任一不成立都不报 —— 宁可漏报不可误报);
  ② **两条独立守护**保证这类项绝不会被清理 (判定不在可清理集 + 执行清理显式拒绝);
  ③ 与 扫描重复 的集成 (组键带 `同名不同文:` 命名空间, 不与正常重复组撞键)。

运行方式 (项目根目录):
    python -m unittest discover -s 测试 -v
"""
import sys
import tempfile
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '源码'))
sys.path.insert(0, str(_PROJECT_ROOT / '测试'))

import _沙箱                      # noqa: E402,F401  状态根沙箱
import 去重处理 as D              # noqa: E402


def _条目(名, 句集, 字数):
    return {'路径': f'X:/{名}', '名': 名, '字数': 字数,
            '句集': set(句集), '字节': 1000}


def _造正文(前缀: str, 句数: int = 60) -> str:
    """造一段**与其他前缀完全不重合**的正文 (每句都足够长)。"""
    return '\n'.join(f'{前缀}第{i}句的正文内容示例文字。' for i in range(句数))


class Test检测同名不同文(unittest.TestCase):

    def test_同名_正文不重合_体量相当_报出(self):
        甲 = _条目('示例书名甲.txt', range(0, 300), 2000)
        乙 = _条目('示例书名甲（另版）.txt', range(5000, 5300), 1900)
        组 = D.检测同名不同文([甲, 乙])
        self.assertEqual(len(组), 1, '应报出 1 组')
        组0 = 组[0]
        self.assertTrue(组0['键'].startswith('同名不同文:'), '组键要带命名空间')
        self.assertEqual(组0['可自动清理'], [], '⚠️ 可自动清理必须恒空 (守护①)')
        self.assertEqual(len(组0['待确认']), 1)
        项 = 组0['待确认'][0]
        self.assertEqual(项['判定'], D.判定_同名不同文)
        self.assertIn('几乎不重合', 项['理由'])
        self.assertIn(D.判定_同名不同文, D.仅提示判定)

    def test_正文几乎相同则不报(self):
        """那是"同一本", 归正常重复路 —— 不该在这里重复报一次。"""
        甲 = _条目('示例书名甲.txt', range(0, 300), 2000)
        乙 = _条目('示例书名甲（另版）.txt', range(0, 300), 2000)
        self.assertEqual(D.检测同名不同文([甲, 乙]), [])

    def test_体量悬殊则不报(self):
        """18 MB 与 2 MB 不是"同一本的另一版", 规模差太多。"""
        甲 = _条目('示例书名甲.txt', range(0, 300), 2000)
        乙 = _条目('示例书名甲（另版）.txt', range(5000, 5300), 200)
        self.assertEqual(D.检测同名不同文([甲, 乙]), [])

    def test_标题不同则不报(self):
        """C8 是"**同名**不同文" —— 标题不同就不是它管的范围。"""
        甲 = _条目('示例书名甲.txt', range(0, 300), 2000)
        乙 = _条目('示例书名乙.txt', range(5000, 5300), 2000)
        self.assertEqual(D.检测同名不同文([甲, 乙]), [])

    def test_标题互为子串也报(self):
        """`书名` vs `书名修订版` —— 归一化后不相等, 但互为子串。"""
        甲 = _条目('示例书名甲.txt', range(0, 300), 2000)
        乙 = _条目('示例书名甲修订版.txt', range(5000, 5300), 2000)
        组 = D.检测同名不同文([甲, 乙])
        self.assertEqual(len(组), 1)

    def test_小样本不判(self):
        """小样本上的 Jaccard 没有意义 (项目前车之鉴: 3 字夹具被整篇当成一句话)。"""
        甲 = _条目('示例书名甲.txt', range(0, 3), D.同名不同文最小字数 - 1)
        乙 = _条目('示例书名甲（另版）.txt', range(5000, 5003), 2000)
        self.assertEqual(D.检测同名不同文([甲, 乙]), [])

    def test_单条目与空输入不炸(self):
        self.assertEqual(D.检测同名不同文([]), [])
        self.assertEqual(D.检测同名不同文([_条目('a.txt', range(3), 2000)]), [])

    def test_代表取字数更全的那份(self):
        甲 = _条目('示例书名甲.txt', range(0, 300), 2000)
        乙 = _条目('示例书名甲（另版）.txt', range(5000, 5300), 1900)
        组 = D.检测同名不同文([甲, 乙])[0]
        self.assertEqual(组['代表']['名'], '示例书名甲.txt', '代表应是字数更多的')
        self.assertEqual(组['待确认'][0]['名'], '示例书名甲（另版）.txt')


class Test守护_绝不清理(unittest.TestCase):
    """⚠️ 这类项**两份都该留**(不同版本) —— 两条独立守护缺一不可。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.结果 = Path(self._tmp.name) / '抓取结果'
        self.结果.mkdir()
        self.文件 = self.结果 / '示例书名甲（另版）.txt'
        self.文件.write_text('另版正文' * 50, encoding='utf-8')

    def _存记录(self):
        D.保存([{
            '键': '同名不同文:abc123',
            '代表': {'路径': str(self.结果 / '示例书名甲.txt'),
                     '名': '示例书名甲.txt', '字数': 2000, '字节': 1},
            '可自动清理': [],
            '待确认': [{'路径': str(self.文件), '名': self.文件.name,
                     '字数': 1900, '字节': 1,
                     '判定': D.判定_同名不同文,
                     '理由': 'r', '指标': {}}],
            '状态': D.状态_待确认,
            '最近时间': '2026-10-11 13:00', '次数': 1, '首次时间': '2026-10-11 13:00',
        }])

    def test_判定不在可清理集里_守护1(self):
        self.assertIn(D.判定_同名不同文, D.仅提示判定)
        self.assertNotIn(D.判定_同名不同文, (D.判定_同一本, D.判定_子集))

    def test_执行清理拒绝仅提示项_守护2(self):
        """即便界面出错把它当"点名批准"传进来, 也必须拦住且**不动文件**。"""
        self._存记录()
        r = D.执行清理('同名不同文:abc123', '隔离', 额外确认项=[self.文件.name])
        self.assertEqual(r['清理'], [], '不得清理任何东西')
        self.assertTrue(r['失败'], '应报告失败')
        self.assertIn('仅提示', r['失败'][0][1])
        self.assertTrue(self.文件.is_file(), '⚠️ 文件必须原地不动')
        self.assertFalse((self.结果 / D.隔离目录名).exists(),
                         '不该建隔离目录')


class Test与扫描重复集成(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.目录 = Path(self._tmp.name) / '抓取结果'
        self.目录.mkdir()
        (self.目录 / '示例书名甲.txt').write_text(_造正文('甲版'), encoding='utf-8')
        (self.目录 / '示例书名甲（另版）.txt').write_text(_造正文('乙版'),
                                                  encoding='utf-8')

    def test_扫描重复会带上同名不同文组(self):
        组 = D.扫描重复(str(self.目录))
        同名 = [g for g in 组 if g['键'].startswith('同名不同文:')]
        self.assertEqual(len(同名), 1, f'应带上同名不同文组, 实得 {[g["键"] for g in 组]}')
        self.assertEqual(同名[0]['可自动清理'], [])
        self.assertEqual(同名[0]['待确认'][0]['判定'], D.判定_同名不同文)

    def test_同名不同文组不会与正常重复组撞键(self):
        """同一份文件既当重复组代表、又当本组代表时, 两键必须不同 (否则清单互相覆盖)。"""
        重复组键 = D.组键(str(self.目录 / '示例书名甲.txt'))
        同名键 = D.检测同名不同文(D.扫描(str(self.目录)))[0]['键']
        self.assertNotEqual(重复组键, 同名键)


if __name__ == '__main__':
    unittest.main(verbosity=2)
