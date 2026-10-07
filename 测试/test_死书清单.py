# -*- coding: utf-8 -*-
"""死书清单存储回归 (2026-10-02 新增, 站点脱钩: 纯占位数据)。

锁定: 落盘位置/原子写/损坏容错/URL 规范化同键/首次与重复的"是否弹窗"契约/
状态流转(已删除重开、已忽略不复活)/500 条上限裁剪/多线程并发写。
运行: python -m unittest discover -s 测试
"""
import json
import sys
import threading
import unittest
from pathlib import Path

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))
sys.path.insert(0, str(_根 / '测试'))

import _沙箱          # noqa: E402,F401  状态根沙箱 (LOCALAPPDATA 隔离)
import 死书处理 as D   # noqa: E402

_URL = 'https://example.com/book/1'


class Test死书清单(unittest.TestCase):

    def setUp(self):
        D.保存([])   # 每个用例从空清单开始

    def _清(self):
        D.保存([])

    def test_落盘位置在状态根数据目录(self):
        p = D.清单路径()
        self.assertTrue(p.endswith('死书清单.json'))
        self.assertIn('数据', p)

    def test_记录死书_首次返回True且落盘待确认(self):
        记录, 首次 = D.记录死书(_URL, '示例书', D.类型_书已删除, '目录页无章节', 'task_x')
        self.assertTrue(首次)
        self.assertEqual(记录['状态'], D.状态_待确认)
        self.assertEqual(记录['次数'], 1)
        self.assertEqual(记录['任务id'], ['task_x'])
        self.assertEqual(记录['域名'], 'example.com')
        条目 = D.载入()
        self.assertEqual(len(条目), 1)
        self.assertEqual(条目[0]['网址'], _URL)

    def test_原子写无残留tmp文件(self):
        D.记录死书(_URL, '示例书', D.类型_书已删除, '原因')
        目录 = Path(D.清单路径()).parent
        self.assertEqual(list(目录.glob('死书清单.json.tmp*')), [],
                         '原子写后不得残留 tmp 文件')

    def test_状态码与已抓章节随记录落盘(self):
        """批 3 数据缺口 (2026-10-07): 两个新字段必须**真的落盘**。

        旧实现把 网站失效 在 保存() 之后才补进内存记录 → 既不落盘也读不回来
        (八项需求 #3 的根因)。本用例按同一纪律锁死: 重新 载入() 必须读得到。
        """
        D.记录死书(_URL, '示例书', D.类型_书已删除, '原因',
                   状态码=404, 已抓章节=412)
        条目 = D.载入()
        self.assertEqual(条目[0]['HTTP状态码'], 404)
        self.assertEqual(条目[0]['已抓章节'], 412)

    def test_状态码与已抓章节按最近一次判定覆盖(self):
        """两个值描述"最近一次判定时的事实", 不是历史累计量 (与 次数 语义不同)"""
        D.记录死书(_URL, '书', D.类型_无章节, '原因', 状态码=200, 已抓章节=0)
        D.记录死书(_URL, '书', D.类型_无章节, '原因', 状态码=404, 已抓章节=87)
        条目 = D.载入()
        self.assertEqual(len(条目), 1)
        self.assertEqual(条目[0]['次数'], 2, '次数仍应累加')
        self.assertEqual(条目[0]['HTTP状态码'], 404, '状态码取最近一次')
        self.assertEqual(条目[0]['已抓章节'], 87, '已抓章节取最近一次')

    def test_缺省为零而非缺失(self):
        """不传时也要写出 0 (页面靠 "键是否存在" 区分"真 0"与"老记录无此字段")"""
        D.记录死书(_URL, '书', D.类型_无章节, '原因')
        条目 = D.载入()
        self.assertEqual(条目[0]['HTTP状态码'], 0)
        self.assertEqual(条目[0]['已抓章节'], 0)

    def test_非法值归零不抛(self):
        for v in (None, '', 'x'):
            self._清()
            D.记录死书(_URL, '书', D.类型_无章节, '原因', 状态码=v, 已抓章节=v)
            条目 = D.载入()
            self.assertEqual((条目[0]['HTTP状态码'], 条目[0]['已抓章节']),
                             (0, 0), f'值 {v!r}')

    def test_载入_文件缺失返回空(self):
        import os
        p = D.清单路径()
        if os.path.isfile(p):
            os.remove(p)
        self.assertEqual(D.载入(), [])

    def test_载入_损坏JSON返回空不抛(self):
        Path(D.清单路径()).write_text('{这不是合法 JSON', encoding='utf-8')
        self.assertEqual(D.载入(), [])

    def test_网址规范化_同键去重(self):
        """尾斜杠/fragment/大小写差异视为同一本书 (清单是用户可手改的文本)"""
        D.记录死书('https://example.com/book/1/', '书', D.类型_书已删除, '原因')
        记录2, 首次2 = D.记录死书('https://EXAMPLE.com/book/1#第一页', '书',
                                   D.类型_书已删除, '原因')
        self.assertFalse(首次2, '规范化后应命中同一条记录')
        self.assertEqual(len(D.载入()), 1)
        self.assertEqual(记录2['次数'], 2)

    def test_重复失败_次数累加且首次为False(self):
        D.记录死书(_URL, '书', D.类型_书已删除, '原因', 'task_1')
        记录, 首次 = D.记录死书(_URL, '书', D.类型_书已删除, '原因', 'task_2')
        self.assertFalse(首次, '已有待确认记录 → 不应再弹窗')
        self.assertEqual(记录['次数'], 2)
        self.assertEqual(记录['任务id'], ['task_1', 'task_2'])
        self.assertEqual(记录['状态'], D.状态_待确认)

    def test_首次时间不随重复刷新(self):
        r1, _ = D.记录死书(_URL, '书', D.类型_书已删除, '原因')
        r2, _ = D.记录死书(_URL, '书', D.类型_书已删除, '原因')
        self.assertEqual(r1['首次时间'], r2['首次时间'])

    def test_已删除态被再次提交则重开待确认(self):
        记录, 首次 = D.记录死书(_URL, '书', D.类型_书已删除, '原因')
        D.设状态(记录['键'], D.状态_已删除)
        记录2, 首次2 = D.记录死书(_URL, '书', D.类型_书已删除, '原因')
        self.assertTrue(首次2, '已删除的书被重新提交 → 视为首次(要再问一次)')
        self.assertEqual(记录2['状态'], D.状态_待确认)

    def test_已忽略态不被复活(self):
        记录, _ = D.记录死书(_URL, '书', D.类型_书已删除, '原因')
        D.设状态(记录['键'], D.状态_已忽略)
        记录2, 首次2 = D.记录死书(_URL, '书', D.类型_书已删除, '原因')
        self.assertFalse(首次2, '用户已表态忽略 → 不再打扰')
        self.assertEqual(记录2['状态'], D.状态_已忽略)

    def test_设状态与移除记录(self):
        记录, _ = D.记录死书(_URL, '书', D.类型_书已删除, '原因')
        self.assertTrue(D.设状态(记录['键'], D.状态_已忽略))
        self.assertFalse(D.设状态('不存在的键', D.状态_已忽略))
        self.assertTrue(D.移除记录(记录['键']))
        self.assertEqual(D.载入(), [])
        self.assertFalse(D.移除记录(记录['键']))

    def test_记录死书_空网址报错(self):
        with self.assertRaises(ValueError):
            D.记录死书('', '书', D.类型_书已删除, '原因')

    def test_列出_按状态与类型筛选(self):
        D.记录死书('https://a.example.com/1', '书A', D.类型_书已删除, 'r')
        D.记录死书('https://b.example.com/1', '书B', D.类型_站点不可达, 'r')
        self.assertEqual(len(D.列出()), 2)
        self.assertEqual(len(D.列出(类型=D.类型_书已删除)), 1)
        self.assertEqual(len(D.列出(状态=D.状态_待确认)), 2)
        self.assertEqual(len(D.列出(状态=D.状态_已删除)), 0)
        self.assertEqual(len(D.列出(状态=D.状态_待确认, 类型=D.类型_站点不可达)), 1)

    def _造记录(self, i, 状态):
        return {'键': f'k{i}', '网址': f'https://example.com/{i}', '书名': '',
                '域名': 'example.com', '类型': D.类型_书已删除, '原因': '',
                '可询问删除': True, '状态': 状态,
                '首次时间': f'2026-01-01 00:00:{i % 60:02d}',
                '最近时间': f'2026-01-01 00:00:{i % 60:02d}', '次数': 1,
                '任务id': [], '备注': ''}

    def test_上限裁剪先裁已结项(self):
        """超限时优先裁 已删除/已忽略, 保留待确认。

        ⚠️ 必须构造**真超限**的输入: 旧版此用例只造了 `_上限` 条, 恰好命中
        `if len <= _上限: return 记录列表` 早返回 —— 裁剪分支从未被执行,
        于是掩盖了下面的数据丢失 bug (2026-10-07 发现并修复)。
        """
        条目 = [self._造记录(i, D.状态_待确认) for i in range(D._上限)]
        条目 += [self._造记录(10000 + i, D.状态_已删除) for i in range(20)]
        self.assertEqual(len(条目), D._上限 + 20)
        裁后 = D._裁剪(条目)
        self.assertEqual(len(裁后), D._上限)
        待确认数 = sum(1 for r in 裁后 if r['状态'] == D.状态_待确认)
        self.assertEqual(待确认数, D._上限, '待确认项应全部保留, 裁掉的是已结项')

    def test_上限裁剪不清空清单(self):
        """回归 (2026-10-07): 旧实现算 `溢出量` 当保留额度, 超限即近乎清空清单。

        实测旧代码: 520 条全已结 → 只返回 20 条; 501 条 → 只返回 1 条。
        而 `记录死书()` 每次落盘都调 `保存(_裁剪(...))`, 故超 500 条后清单
        会被静默清空 —— 本条用例锁死"总量恒为 min(len, 上限)"。
        """
        for 总数 in (501, 520, 1000):
            条目 = [self._造记录(i, D.状态_已删除) for i in range(总数)]
            裁后 = D._裁剪(条目)
            self.assertEqual(len(裁后), D._上限, f'{总数} 条应裁到 {D._上限} 条')
        # 待确认项本身就超限时, 也只留 _上限 条 (不能撑爆)
        活跃 = [self._造记录(i, D.状态_待确认) for i in range(D._上限 + 30)]
        self.assertEqual(len(D._裁剪(活跃)), D._上限)
        # 已结项保留的是**最近**的
        条目 = [self._造记录(i, D.状态_已忽略) for i in range(D._上限 + 5)]
        for i, r in enumerate(条目):
            r['最近时间'] = f'2026-01-{(i % 28) + 1:02d} 00:00:00'
        裁后 = D._裁剪(条目)
        self.assertEqual(len(裁后), D._上限)
        最近时间集 = {r['最近时间'] for r in 裁后}
        self.assertIn('2026-01-28 00:00:00', 最近时间集)

    def test_并发写不丢条目(self):
        def 写(i):
            D.记录死书(f'https://example.com/c{i}', f'书{i}', D.类型_书已删除, 'r')
        线程 = [threading.Thread(target=写, args=(i,)) for i in range(8)]
        for t in 线程:
            t.start()
        for t in 线程:
            t.join()
        self.assertEqual(len(D.载入()), 8, '并发写不得丢条目')


if __name__ == '__main__':
    unittest.main(verbosity=2)
