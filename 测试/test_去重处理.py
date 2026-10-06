# -*- coding: utf-8 -*-
"""去重处理回归 (2026-10-07 新增, 全离线: 纯占位正文 + 临时目录)。

锁定 去重处理 的核心契约:
  - 句子级指纹对"分章/分段不同"免疫 (A 站 34 章 vs B 站 100 章, 同一本)
  - 阈值三分支: 同一本 / 真子集 / 灰区(待确认) / 不同
  - **灰区绝不自动清理**; 不同书即使标题同名也不误判
  - 保留项按归一化正文字数, 不看字节数/章数
  - 清单原子写 + 三态 + 已处置不倒退 + 上限裁剪
  - 清理默认**移入隔离目录**(可反悔); 拒绝越界/拒绝删代表项
运行: python -m unittest discover -s 测试
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))
sys.path.insert(0, str(_根 / '测试'))

import _沙箱          # noqa: E402,F401  状态根沙箱 (LOCALAPPDATA 隔离)
import 去重处理 as D   # noqa: E402


def _写文本(路径, 内容=''):
    with open(路径, 'w', encoding='utf-8') as f:
        f.write(内容)
    return 路径


def _句(i: int) -> str:
    """造一句长度足够、内容唯一的正文句 (归一化后 >= 句长下限)。"""
    return f"第{i}句这是用于去重判定测试的正文内容编号{i}各不相同。"


def _造书(句子编号, 每章句数=1):
    """把句子拼成正文, 每 N 句一行 —— 模拟不同站点的分章/分段方式。"""
    行 = []
    for i in range(0, len(句子编号), 每章句数):
        块 = 句子编号[i:i + 每章句数]
        行.append(''.join(_句(x) for x in 块))
    return '\n'.join(行)


class _底座(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.目录 = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _写(self, 名, 编号列表, 每章句数=1):
        路径 = os.path.join(self.目录, 名)
        with open(路径, 'w', encoding='utf-8') as f:
            f.write(_造书(编号列表, 每章句数))
        return 路径


class Test归一化标题(unittest.TestCase):

    def test_去站点装饰后缀与括号(self):
        表 = {
            '(雨夜带刀不带伞)爆乳性奴养成记TXT下载.txt': '爆乳性奴养成记',
            '(雨夜带刀不带伞)爆乳性奴养成记免费全文.txt': '爆乳性奴养成记',
            '爆乳性奴养成记(雨夜带刀不带伞)免费全文.txt': '爆乳性奴养成记',
            '全本解锁：十日终焉（TXT+云书架）.txt': '全本解锁：十日终焉',
            '蜜母（纯爱修改版 ）.txt': '蜜母',
            '蜜母.txt': '蜜母',
        }
        for 原名, 期望 in 表.items():
            self.assertEqual(D.归一化标题(原名), 期望, 原名)


class Test指纹与判定(_底座):

    def test_分章不同仍是同一本(self):
        """A 站 3 句一章 (34 章) vs B 站 1 句一章 (100 章) —— 内容一致。"""
        self._写('A站版.txt', range(100), 每章句数=3)
        self._写('B站版.txt', range(100), 每章句数=1)
        条目 = D.扫描(self.目录)
        self.assertEqual(len(条目), 2)
        r = D.判定对(条目[0], 条目[1])
        self.assertEqual(r['判定'], D.判定_同一本, r['理由'])
        self.assertGreaterEqual(r['指标']['Jaccard'], 0.99)

    def test_章节数少但被包含判真子集(self):
        """10 章版是 12 章版的子集 → 删子集、留全的。"""
        self._写('全本.txt', range(100))
        self._写('缺章.txt', range(50))
        条目 = {e['名']: e for e in D.扫描(self.目录)}
        r = D.判定对(条目['缺章.txt'], 条目['全本.txt'])
        self.assertEqual(r['判定'], D.判定_子集, r['理由'])
        self.assertEqual(r['保留']['名'], '全本.txt')
        self.assertEqual(r['删除']['名'], '缺章.txt')

    def test_部分重叠落灰区不自动清理(self):
        self._写('前一百.txt', range(100))
        self._写('后一百.txt', range(50, 150))
        条目 = {e['名']: e for e in D.扫描(self.目录)}
        r = D.判定对(条目['前一百.txt'], 条目['后一百.txt'])
        self.assertEqual(r['判定'], D.判定_灰区, r['理由'])

    def test_完全不同判不同(self):
        self._写('甲书.txt', range(100))
        self._写('乙书.txt', range(1000, 1100))
        条目 = D.扫描(self.目录)
        r = D.判定对(条目[0], 条目[1])
        self.assertEqual(r['判定'], D.判定_不同)
        self.assertIsNone(r['保留'])
        self.assertIsNone(r['删除'])

    def test_标题同名但内容不同不误判(self):
        """`蜜母` 与 `蜜母（纯爱修改版 ）` 实测仅 8.5% 重叠 → 必须判不同。"""
        self._写('蜜母.txt', range(100))
        self._写('蜜母（纯爱修改版 ）.txt', range(5000, 5100))
        条目 = D.扫描(self.目录)
        r = D.判定对(条目[0], 条目[1])
        self.assertEqual(r['判定'], D.判定_不同)

    def test_标题同前缀且部分重叠落灰区(self):
        """同书不同站源文本: 包含度中等 + 标题同前缀 → 灰区待人工。"""
        self._写('某书片段.txt', list(range(20)) + list(range(9000, 9020)))
        self._写('某书.txt', range(400))
        条目 = {e['名']: e for e in D.扫描(self.目录)}
        r = D.判定对(条目['某书片段.txt'], 条目['某书.txt'])
        self.assertEqual(r['判定'], D.判定_灰区, r['理由'])

    def test_保留项按正文字数而非字节数(self):
        """字节数更大但正文字数更少的那份不该被保留 (换行/广告灌水)。"""
        self._写('正文多.txt', range(200))
        # 同样 100 句正文, 但塞满空行与广告 -> 字节数更大、正文字数更少
        路径 = os.path.join(self.目录, '灌水多.txt')
        with open(路径, 'w', encoding='utf-8') as f:
            f.write('\n\n\n' + _造书(range(100)) + '\n\n\n')
            f.write('请收藏本站最快更新www.example.com\n' * 200)
        self.assertGreater(os.path.getsize(路径),
                           os.path.getsize(os.path.join(self.目录, '正文多.txt')) * 0.5)
        条目 = {e['名']: e for e in D.扫描(self.目录)}
        self.assertGreater(条目['正文多.txt']['字数'], 条目['灌水多.txt']['字数'])
        r = D.判定对(条目['灌水多.txt'], 条目['正文多.txt'])
        if r['判定'] != D.判定_不同:
            self.assertEqual(r['保留']['名'], '正文多.txt')

    def test_扫描排除质检报告与非txt(self):
        self._写('甲.txt', range(50))
        self._写('甲.txt.质检报告.txt', range(50))
        with open(os.path.join(self.目录, '站点配置.json'), 'w', encoding='utf-8') as f:
            f.write('{}')
        列表 = D.扫描(self.目录)
        self.assertEqual([e['名'] for e in 列表], ['甲.txt'])

    def test_空目录与无正文不崩(self):
        self.assertEqual(D.扫描重复(self.目录), [])
        open(os.path.join(self.目录, '空.txt'), 'w').close()
        self.assertEqual(D.扫描重复(self.目录), [])
        条目 = D.扫描(self.目录)
        self.assertEqual(条目[0]['字数'], 0)
        self.assertEqual(len(条目[0]['句集']), 0)


class Test分组(_底座):

    def test_三方副本聚成一组并只留最全(self):
        """6 份副本场景: 不同命名 (含尾缀 1) + 不同分章, 应聚成一组的 1 留 5 删。"""
        self._写('(站A)某书TXT下载.txt', range(100), 每章句数=2)
        self._写('某书1.txt', range(100), 每章句数=5)
        self._写('某书免费全文.txt', range(100), 每章句数=1)
        组 = D.分组(D.扫描(self.目录))
        self.assertGreaterEqual(len(组), 1)
        最大组 = max(组, key=lambda g: g['组成员数'])
        self.assertEqual(最大组['组成员数'], 3)
        # 代表是正文最全的 (这里三份内容一致, 取字数最大者, 不应有 0 长)
        self.assertGreater(最大组['代表']['字数'], 0)
        self.assertEqual(len(最大组['可自动清理']), 2)

    def test_链式传染被代表项复核挡住(self):
        """A~B、B~C 但 A 与 C 无关时, C 不该被并进 A 的组。"""
        self._写('甲.txt', range(100))
        self._写('乙.txt', range(0, 100))
        self._写('丙.txt', range(8000, 8100))
        组 = D.分组(D.扫描(self.目录))
        for g in 组:
            成员名 = {g['代表']['名']} | {x['名'] for x in g['可自动清理']} \
                | {x['名'] for x in g['待确认']}
            self.assertNotIn('丙.txt', 成员名)


class Test清单(unittest.TestCase):

    def setUp(self):
        D.保存([])

    def tearDown(self):
        D.保存([])

    def test_落盘位置在状态根数据目录(self):
        p = D.清单路径()
        self.assertTrue(p.endswith(D.清单文件名))
        self.assertIn('数据', p)

    def test_写出与载入(self):
        with tempfile.TemporaryDirectory() as d:
            甲 = os.path.join(d, 'a.txt')
            _写文本(甲, '')
            组 = [{'键': 'k1', '代表': {'路径': 甲, '名': 'a.txt', '字数': 10, '字节': 0},
                   '可自动清理': [{'路径': os.path.join(d, 'b.txt'), '名': 'b.txt',
                                '字数': 1, '字节': 0, '判定': D.判定_同一本,
                                '理由': 'x', '指标': {}}],
                   '待确认': []}]
            self.assertEqual(D.写出清单(组), 1)
            记录 = D.载入()
            self.assertEqual(len(记录), 1)
            self.assertEqual(记录[0]['状态'], D.状态_待确认)
            self.assertEqual(记录[0]['次数'], 1)
            D.写出清单(组)
            self.assertEqual(D.载入()[0]['次数'], 2)

    def test_已处置状态不倒退(self):
        with tempfile.TemporaryDirectory() as d:
            组 = [{'键': 'k2', '代表': {'路径': os.path.join(d, 'a.txt'), '名': 'a',
                                      '字数': 1, '字节': 0},
                   '可自动清理': [], '待确认': []}]
            D.写出清单(组)
            self.assertTrue(D.设状态('k2', D.状态_已忽略))
            D.写出清单(组)          # 再扫一次不应把 已忽略 拉回 待确认
            self.assertEqual(D.载入()[0]['状态'], D.状态_已忽略)

    def _组(self, 键, 可清理=(), 待确认=()):
        return [{'键': 键,
                 '代表': {'路径': f'X:/代表-{键}.txt', '名': f'代表-{键}.txt',
                         '字数': 100, '字节': 1},
                 '可自动清理': [{'路径': f'X:/{n}', '名': n, '字数': 9, '字节': 1,
                             '判定': D.判定_同一本, '理由': '', '指标': {}} for n in 可清理],
                 '待确认': [{'路径': f'X:/{n}', '名': n, '字数': 9, '字节': 1,
                          '判定': D.判定_灰区, '理由': '', '指标': {}} for n in 待确认]}]

    def test_已清理的组又冒出新重复要退回待确认(self):
        D.写出清单(self._组('k_re'))
        D.设状态('k_re', D.状态_已清理)
        D.写出清单(self._组('k_re'))                 # 已无待办 → 保持 已清理
        self.assertEqual(D.载入()[0]['状态'], D.状态_已清理)
        D.写出清单(self._组('k_re', 可清理=['又一份.txt']))   # 冒出新的
        self.assertEqual(D.载入()[0]['状态'], D.状态_待确认,
                         '新出现的重复必须重新提醒, 不能被"已清理"静默吃掉')

    def test_已忽略的组保持忽略(self):
        D.写出清单(self._组('k_ig'))
        D.设状态('k_ig', D.状态_已忽略)
        D.写出清单(self._组('k_ig', 待确认=['新项.txt']))
        self.assertEqual(D.载入()[0]['状态'], D.状态_已忽略,
                         '用户明确忽略过的组不该反复打扰')

    def test_非法状态被拒(self):
        self.assertFalse(D.设状态('不存在', '乱状态'))

    def test_损坏清单按空处理(self):
        p = D.清单路径()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8') as f:
            f.write('{ 这不是 json')
        self.assertEqual(D.载入(), [])

    def test_上限裁剪(self):
        记录 = [{'键': f'k{i}', '状态': D.状态_已清理, '最近时间': f'2026-01-{i:02d}'}
                for i in range(D._清单上限 + 20)]
        self.assertEqual(len(D._裁剪(记录)), D._清单上限)
        活跃 = [{'键': 'live', '状态': D.状态_待确认, '最近时间': '2020-01-01'}]
        裁剪后 = D._裁剪(记录[:D._清单上限 + 5] + 活跃)
        self.assertIn('live', [r['键'] for r in 裁剪后])


class Test清理编排(_底座):

    def setUp(self):
        super().setUp()
        D.保存([])

    def tearDown(self):
        D.保存([])
        super().tearDown()

    def _造组(self):
        self._写('全本.txt', range(100))
        self._写('缺章.txt', range(50))
        组 = D.分组(D.扫描(self.目录))
        D.写出清单(组)
        键 = 组[0]['键']
        return 键, 组[0]

    def test_隔离模式移走副本且保留代表(self):
        键, 组 = self._造组()
        r = D.执行清理(键, '隔离')
        self.assertEqual(len(r['清理']), 1)
        self.assertEqual(r['清理'][0], '缺章.txt')
        self.assertTrue(os.path.isfile(os.path.join(self.目录, '全本.txt')))
        self.assertFalse(os.path.exists(os.path.join(self.目录, '缺章.txt')))
        隔离 = os.path.join(self.目录, D.隔离目录名)
        self.assertTrue(os.path.isfile(os.path.join(隔离, '缺章.txt')))
        self.assertEqual(D.载入()[0]['状态'], D.状态_已清理)

    def test_重复调用不崩且报告失败(self):
        键, _ = self._造组()
        D.执行清理(键, '隔离')
        r2 = D.执行清理(键, '隔离')
        self.assertEqual(r2['清理'], [])
        self.assertTrue(r2['失败'])

    def test_删除模式真删(self):
        键, _ = self._造组()
        r = D.执行清理(键, '删除')
        self.assertEqual(r['清理'], ['缺章.txt'])
        self.assertFalse(os.path.exists(os.path.join(self.目录, '缺章.txt')))

    def test_拒绝越界路径(self):
        with tempfile.TemporaryDirectory() as 外部:
            越界 = os.path.join(外部, '外面.txt')
            _写文本(越界, 'x')
            代表 = os.path.join(self.目录, '代表.txt')
            _写文本(代表, 'y')
            D.保存([{'键': 'k_out', '状态': D.状态_待确认,
                     '代表': {'路径': 代表, '名': '代表.txt', '字数': 9, '字节': 1},
                     '可自动清理': [{'路径': 越界, '名': '外面.txt', '字数': 1,
                                  '字节': 1, '判定': D.判定_同一本, '理由': '', '指标': {}}],
                     '待确认': [], '最近时间': ''}])
            r = D.执行清理('k_out', '删除')
            self.assertEqual(r['清理'], [])
            self.assertTrue(os.path.isfile(越界), '越界文件不该被删')

    def test_拒绝删除代表项(self):
        with tempfile.TemporaryDirectory() as d:
            代表 = os.path.join(self.目录, '代表.txt')
            _写文本(代表, 'y')
            D.保存([{'键': 'k_rep', '状态': D.状态_待确认,
                     '代表': {'路径': 代表, '名': '代表.txt', '字数': 9, '字节': 1},
                     '可自动清理': [{'路径': 代表, '名': '代表.txt', '字数': 9,
                                  '字节': 1, '判定': D.判定_同一本, '理由': '', '指标': {}}],
                     '待确认': [], '最近时间': ''}])
            r = D.执行清理('k_rep', '删除')
            self.assertEqual(r['清理'], [])
            self.assertTrue(os.path.isfile(代表), '代表项不该被删')

    def _造灰区组(self):
        """造一个「只有待确认项」的组 (模拟 Jaccard 落在灰区的两组文件)。"""
        代表 = _写文本(os.path.join(self.目录, '全本.txt'), 'x' * 50)
        灰 = _写文本(os.path.join(self.目录, '疑似.txt'), 'y' * 40)
        D.保存([{'键': 'k_grey', '状态': D.状态_待确认,
                 '代表': {'路径': 代表, '名': '全本.txt', '字数': 1000, '字节': 50},
                 '可自动清理': [],
                 '待确认': [{'路径': 灰, '名': '疑似.txt', '字数': 900, '字节': 40,
                           '判定': D.判定_灰区, '理由': 'r', '指标': {}}],
                 '最近时间': ''}])
        return 代表, 灰

    def test_灰区项未点名批准时不得被动(self):
        代表, 灰 = self._造灰区组()
        r = D.执行清理('k_grey', '隔离')
        self.assertEqual(r['清理'], [])
        self.assertTrue(r['失败'])
        self.assertTrue(os.path.isfile(灰), '未批准的灰区项必须原地不动')
        self.assertTrue(os.path.isfile(代表))

    def test_灰区项点名批准后按隔离模式清理(self):
        代表, 灰 = self._造灰区组()
        r = D.执行清理('k_grey', '隔离', 额外确认项=['疑似.txt'])
        self.assertEqual(r['清理'], ['疑似.txt'])
        self.assertEqual(r['失败'], [])
        self.assertFalse(os.path.exists(灰))
        self.assertTrue(os.path.isfile(
            os.path.join(self.目录, D.隔离目录名, '疑似.txt')), '应移入隔离区')
        self.assertTrue(os.path.isfile(代表), '代表项不得被动')

    def test_点名未列在待确认里的项不生效(self):
        代表, 灰 = self._造灰区组()
        r = D.执行清理('k_grey', '隔离', 额外确认项=['别的书.txt'])
        self.assertEqual(r['清理'], [])
        self.assertTrue(os.path.isfile(灰), '点名不存在的项不该误伤别的文件')

    def test_点名代表项仍被硬保护拒绝(self):
        """即便用户点名, 代表项 (保留项) 也不得被删。"""
        代表 = _写文本(os.path.join(self.目录, '全本.txt'), 'x' * 50)
        D.保存([{'键': 'k_rep2', '状态': D.状态_待确认,
                 '代表': {'路径': 代表, '名': '全本.txt', '字数': 1000, '字节': 50},
                 '可自动清理': [],
                 '待确认': [{'路径': 代表, '名': '全本.txt', '字数': 1000, '字节': 50,
                           '判定': D.判定_灰区, '理由': 'r', '指标': {}}],
                 '最近时间': ''}])
        r = D.执行清理('k_rep2', '删除', 额外确认项=['全本.txt'])
        self.assertEqual(r['清理'], [])
        self.assertTrue(r['失败'])
        self.assertTrue(os.path.isfile(代表), '代表项不该被删, 即使被点名')

    def test_未知键返回失败(self):
        r = D.执行清理('不存在的键', '隔离')
        self.assertEqual(r['清理'], [])
        self.assertTrue(r['失败'])


if __name__ == '__main__':
    unittest.main()
