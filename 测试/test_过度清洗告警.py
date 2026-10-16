# -*- coding: utf-8 -*-
"""过度清洗告警测试 (C6 Roadmap P1 半程 A, 2026-10-17)。

P1 定调 (文档/实施计划.md): 删除行占比异常 (>30%) 时质检报告加
"疑似过度清洗"标记, **只告警不扣分** —— 误报不得影响自动判定。

覆盖:
  ① 判定过度清洗 纯函数: 阈值上下 / 小样本不判 / 缺键容错 / 水印不计入分子 /
     明细拆分 / 非 dict 容错;
  ② clean_content 产出 原始行数 (分母) 且口径正确 (非空行);
  ③ 端到端: 广告居多的内容 ⇒ 统计可算 ⇒ 告警非空;
  ④ **不扣分铁律**: 告警触发时 得分/有效 与无告警时一致。
运行: python -m unittest discover -s 测试
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))


def _造爬虫():
    import 爬虫 as C
    with mock.patch.object(C.NovelSpider, '__init__', lambda self, *a, **k: None):
        s = C.NovelSpider()
    s.base_url = ''
    s.last_request_error = ''
    s.last_status_code = 200
    s._目录页为空 = False
    s._目录页被质询 = False
    import threading
    s._inspect_cache = {}
    s._inspect_cache_lock = threading.Lock()
    return s


class Test判定过度清洗纯函数(unittest.TestCase):
    """内容质检器.判定过度清洗: 阈值/样本/口径/容错"""

    def setUp(self):
        from 内容质检器 import 判定过度清洗
        self.判 = 判定过度清洗

    def test_占比超阈告警(self):
        s = {'原始行数': 20, '关键词行': 4, '广告行': 3, '推广行': 1}
        告警 = self.判(s)
        self.assertTrue(告警, '删 8/20 = 40% > 30% 应告警')
        self.assertIn('8/20', 告警)
        self.assertIn('40%', 告警)
        self.assertIn('关键词行4', 告警, '明细应含各维度计数')

    def test_占比正常不告警(self):
        s = {'原始行数': 20, '关键词行': 2, '广告行': 1}
        self.assertEqual(self.判(s), '', '删 3/20 = 15% 不应告警')

    def test_恰好等于阈值不告警(self):
        """边界: 30% 整不算超 (定调是 >30%)"""
        s = {'原始行数': 10, '关键词行': 3}
        self.assertEqual(self.判(s), '')

    def test_小样本不判(self):
        """短章节删 1 行就 33% —— 噪声不是信号"""
        s = {'原始行数': 5, '关键词行': 2}
        self.assertEqual(self.判(s), '')

    def test_水印不计入分子(self):
        """水印是字符级替换计数, 不是行 —— 计入会虚报"""
        s = {'原始行数': 20, '水印': 15}
        self.assertEqual(self.判(s), '', '纯水印替换不得触发过度清洗告警')

    def test_缺键容错(self):
        self.assertEqual(self.判({}), '')
        self.assertEqual(self.判({'关键词行': 5}), '', '缺 原始行数 按 0 处理')
        self.assertEqual(self.判({'原始行数': 'x', '关键词行': 5}), '',
                         '非数字 原始行数 不炸')
        self.assertEqual(self.判(None), '', '非 dict 不炸')

    def test_无删除不告警(self):
        self.assertEqual(self.判({'原始行数': 100}), '')


class Test统计分母(unittest.TestCase):
    """clean_content 必须产出 原始行数 (非空行), 否则占比无从谈起"""

    def setUp(self):
        self.spider = _造爬虫()

    def test_原始行数为非空行(self):
        from 爬虫 import _最近清洗统计
        正文 = ('第一段完整叙事内容，句子完整并以句号收尾，长度足够跨越阈值判定。\n'
                '\n'
                '一秒记住本站最新域名，请收藏备用\n'
                '\n'
                '第二段完整叙事内容，同样以句号收尾，长度也足够跨过阈值独立成段。')
        self.spider.clean_content(正文)
        stats = _最近清洗统计.get()
        self.assertIn('原始行数', stats, '统计缺 原始行数 (分母)')
        self.assertEqual(stats['原始行数'], 3, '分母应为非空行数 (空行不计)')

    def test_端到端广告居多触发告警(self):
        from 爬虫 import _最近清洗统计
        from 内容质检器 import 判定过度清洗
        行 = []
        for i in range(8):
            行.append(f'一秒记住本站最新域名第{i}组，请收藏备用并转发给朋友')
        for i in range(12):
            行.append(f'第{i}段完整叙事内容，句子完整并以句号收尾，长度足够跨阈值。')
        self.spider.clean_content('\n'.join(行))
        stats = _最近清洗统计.get()
        告警 = 判定过度清洗(stats)
        self.assertTrue(告警, f'删 8/20=40% 应告警; stats={stats}')


class Test不扣分铁律(unittest.TestCase):
    """告警触发时, 得分/有效 必须与无告警时一致 (P1 定调)"""

    def test_告警不影响质检结果(self):
        from 内容质检器 import 质检器, 判定过度清洗
        正常正文 = ('这是完整的章节正文内容，情节连贯，句子通顺，长度充足。'
                    '他推门而入，屋里一片昏暗，只有桌上的一盏灯还亮着。'
                    '她站起身，脸上的表情看不出是惊讶还是早已等候多时。')
        无告警统计 = {'原始行数': 10, '关键词行': 1}
        有告警统计 = {'原始行数': 10, '关键词行': 9}
        self.assertEqual(判定过度清洗(无告警统计), '')
        self.assertTrue(判定过度清洗(有告警统计), '前置条件: 后者应告警')
        r1 = 质检器.质检(正常正文, '测试章')
        r2 = 质检器.质检(正常正文, '测试章')
        self.assertEqual(r1.得分, r2.得分)
        self.assertEqual(r1.有效, r2.有效)
        # 告警只写字段, 不动评分
        r2.疑似过度清洗 = 判定过度清洗(有告警统计)
        self.assertEqual(r1.得分, r2.得分, '告警不得影响得分')
        self.assertEqual(r1.有效, r2.有效, '告警不得影响有效')


class Test任务卡展示(unittest.TestCase):
    """GUI 侧: 摘要过滤分母键 + 告警字段默认值 (C6/P1 半程 A 收尾)"""

    def test_清洗摘要过滤原始行数(self):
        """'原始行数' 是分母不是删除量 —— 展示出来是噪声 (如 '原始行数20')"""
        from gui_components.row_detail import _清洗摘要文本
        出 = _清洗摘要文本({'关键词行': 2, '水印': 1, '原始行数': 20})
        self.assertEqual(出, '关键词行2 水印1')
        self.assertNotIn('原始行数', 出)

    def test_清洗摘要空与None(self):
        from gui_components.row_detail import _清洗摘要文本
        self.assertEqual(_清洗摘要文本({}), '无删除')
        self.assertEqual(_清洗摘要文本(None), '无删除')
        self.assertEqual(_清洗摘要文本({'原始行数': 20}), '无删除',
                         '只有分母键时等价于无删除')

    def test_任务指标有告警字段且默认空(self):
        """TaskMetrics.over_clean_warning 默认 '' (老任务/未接线时不炸)"""
        from gui_components.task_manager import TaskMetrics
        mt = TaskMetrics()
        self.assertEqual(mt.over_clean_warning, '')
        self.assertEqual(mt.clean_summary, {}, 'clean_summary 默认空 dict')


if __name__ == '__main__':
    unittest.main(verbosity=2)
