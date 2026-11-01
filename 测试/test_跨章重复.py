# -*- coding: utf-8 -*-
"""跨章重复检测测试 (2026-11-01)。

背景 (真实缺陷, 不是推测): `爬虫.deduplicate_paragraphs` 只在**单章内**去重
(一章调一次), 章与章之间没有任何比对 —— 实测一本 107 章的书出现 **9 组整章重复**,
成品里完全看不出异常。

根因 (2026-11-02 真机取证): **源站把同一份正文载荷重复发布** —— 两章 URL/HTML 都
不同, 但页面内 Base64 块序列完全相同 (37/37); 对照组第 28/29 章块数 31/22 且载荷
不同。抓取链无 bug, 被命中的章在源站本就没有独立正文。本组用例守的是**检测能力**
本身: 相邻两章正文逐字相同 → 置空并告警, 不把重复正文写第二遍。

覆盖:
  ① 章指纹: 排版差异 (缩进/空行/全角空格) 不影响判定; 空正文/纯空白 → '';
  ② 检测重复章: 首次 None / 重复回首次 / 短章不判 / 非法入参容错;
  ③ 爬虫 `_跨章重复处理`: 命中置空 + 记清单; 增量搬运只记录不置空;
  ④ 事件通道: '重复章' 写 metrics.duplicate_chapter_warning, 坏负载不改原值。

运行: python -m unittest discover -s 测试
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))
sys.path.insert(0, str(_根 / '源码' / 'gui_components'))


def _正文(n=300, 前缀=''):
    """造一段长度可控的正文 (每 20 字重复一次, 保证超过 200 字阈值)。"""
    return 前缀 + '这是一段用来测试跨章重复检测的正文内容。' * (n // 20 + 1)


def _造爬虫():
    import 爬虫 as C
    with mock.patch.object(C.NovelSpider, '__init__', lambda self, *a, **k: None):
        s = C.NovelSpider()
    s._章指纹表 = {}
    s._重复章清单 = []
    return s


class Test章指纹(unittest.TestCase):
    """章指纹只按实义字符判定 —— 排版差异不得影响"""

    def test_排版差异不影响指纹(self):
        from 内容清洗 import 章指纹
        基准 = 章指纹('第一段。第二段。')
        self.assertTrue(基准)
        self.assertEqual(章指纹('第一段。\n\n　　第二段。'), 基准,
                         '全角缩进+空行不得改变指纹')
        self.assertEqual(章指纹('第一段。\n第二段。   '), 基准,
                         '行尾空格不得改变指纹')
        self.assertEqual(章指纹('\u3000\u3000第一段。\t第二段。'), 基准,
                         '制表符/全角空格不得改变指纹')

    def test_空与纯空白返回空串(self):
        from 内容清洗 import 章指纹
        for 值 in ('', None, '\n\n', '　　\u3000', ' \t\r\n'):
            self.assertEqual(章指纹(值), '', f'{值!r} 应是空指纹 (不参与判定)')

    def test_不同内容指纹不同(self):
        from 内容清洗 import 章指纹
        self.assertNotEqual(章指纹('甲' * 300), 章指纹('乙' * 300))


class Test检测重复章(unittest.TestCase):
    """纯函数口径: 阈值 / 首次 / 重复 / 容错"""

    def setUp(self):
        from 内容清洗 import 检测重复章, 章去重_最小字数
        self.检测 = 检测重复章
        self.最小 = 章去重_最小字数

    def test_首次出现给指纹且无首次记录(self):
        指纹, 首次 = self.检测(_正文(), {})
        self.assertTrue(指纹, '首次出现必须给出可记录的指纹')
        self.assertIsNone(首次, '首次出现不得报重复')

    def test_重复返回首次记录(self):
        正文 = _正文()
        首次指纹 = self.检测(正文, {})[0]
        指纹, 首次 = self.检测(正文, {首次指纹: (7, '第七章')})
        self.assertEqual(指纹, 首次指纹, '同内容必须同指纹')
        self.assertEqual(首次, (7, '第七章'))

    def test_短章不参与判定(self):
        正文 = _正文(100)
        self.assertLess(len(正文), self.最小, '前置条件: 样本要短于阈值')
        self.assertEqual(self.检测(正文, {}), ('', None),
                         '一句话章节撞车是噪声, 不得判定')

    def test_阈值边界(self):
        刚好 = '字' * self.最小
        self.assertTrue(self.检测(刚好, {})[0],
                        f'{self.最小} 字应参与判定 (>= 阈值)')
        self.assertEqual(self.检测('字' * (self.最小 - 1), {}), ('', None),
                         f'{self.最小 - 1} 字应不参与判定')

    def test_空正文与非dict容错(self):
        self.assertEqual(self.检测('', {}), ('', None))
        self.assertEqual(self.检测(_正文(), None), ('', None),
                         '已见指纹不是 dict 时按"不判定"处理, 不得抛异常')
        self.assertEqual(self.检测(_正文(), '坏数据'), ('', None))


class Test爬虫跨章重复处理(unittest.TestCase):
    """爬虫侧处置: 新抓的重复章置空 (走空占位口径), 增量搬运的只记录"""

    def setUp(self):
        self.spider = _造爬虫()

    def test_首次保留并记入指纹表(self):
        正文 = _正文()
        出 = self.spider._跨章重复处理(1, '第一章', 正文)
        self.assertEqual(出, 正文, '首次出现的章必须原样保留')
        self.assertEqual(len(self.spider._章指纹表), 1, '指纹应记入表')
        self.assertEqual(self.spider._重复章清单, [], '不得误报')

    def test_命中置空并记清单(self):
        正文 = _正文()
        self.spider._跨章重复处理(1, '第一章', 正文)
        出 = self.spider._跨章重复处理(2, '第二章', 正文)
        self.assertEqual(出, '', '重复章必须置空 (不留第二份错内容)')
        self.assertEqual(len(self.spider._重复章清单), 1)
        章, 标题, 首章, 首标题, 字数 = self.spider._重复章清单[0]
        self.assertEqual((章, 标题, 首章, 首标题), (2, '第二章', 1, '第一章'))
        self.assertEqual(字数, len(正文))

    def test_增量搬运只记录不置空(self):
        正文 = _正文()
        self.spider._跨章重复处理(1, '第一章', 正文, 允许置空=False)
        出 = self.spider._跨章重复处理(2, '第二章', 正文, 允许置空=False)
        self.assertEqual(出, 正文, '文件里的既有数据不得被删')
        self.assertEqual(len(self.spider._重复章清单), 1,
                         '但重复事实仍要记清单 (供汇总告警)')

    def test_短章不置空(self):
        正文 = _正文(100)
        self.spider._跨章重复处理(1, '第一章', 正文)
        出 = self.spider._跨章重复处理(2, '第二章', 正文)
        self.assertEqual(出, 正文, '短章撞车不判定, 不得置空')
        self.assertEqual(self.spider._重复章清单, [])

    def test_指纹表未初始化时原样返回(self):
        s = _造爬虫()
        del s._章指纹表
        正文 = _正文()
        self.assertEqual(s._跨章重复处理(1, '第一章', 正文), 正文,
                         '状态缺失时按"不检测"降级, 不得丢内容')

    def test_发布重复章事件(self):
        from 任务事件 import 订阅, 退订
        收到 = []

        class _收件人:
            def 处理任务事件(self, 类型, 数据):
                收到.append((类型, 数据))

        订阅(_收件人())
        try:
            正文 = _正文()
            self.spider._跨章重复处理(1, '第一章', 正文)
            self.spider._跨章重复处理(2, '第二章', 正文)
        finally:
            退订()
        命中 = [数据 for 类型, 数据 in 收到 if 类型 == '重复章']
        self.assertEqual(len(命中), 1, f'应发 1 条重复章事件, 实际收到 {收到}')
        self.assertEqual(命中[0]['章'], 2)
        self.assertEqual(命中[0]['首次章'], 1)
        self.assertEqual(命中[0]['字数'], len(正文))


class Test事件通道(unittest.TestCase):
    """GUI 侧: '重复章' 事件写告警字段, 坏负载保持原值"""

    def _重定向器(self, task):
        import task_manager as tm
        return tm.TaskLogRedirector(task, None)

    def _新任务(self):
        import task_manager as tm
        return tm.TaskInfo(task_id='t1', url='https://example.com/book/1')

    def test_重复章事件写入告警字段(self):
        t = self._新任务()
        r = self._重定向器(t)
        self.assertEqual(t.metrics.duplicate_chapter_warning, '', '默认无告警')
        r.处理任务事件('重复章', {'章': 2, '首次章': 1, '字数': 320})
        self.assertIn('第 2 章', t.metrics.duplicate_chapter_warning)
        self.assertIn('第 1 章', t.metrics.duplicate_chapter_warning)

    def test_坏负载不改原值(self):
        t = self._新任务()
        r = self._重定向器(t)
        r.处理任务事件('重复章', {'章': 2, '首次章': 1})
        原值 = t.metrics.duplicate_chapter_warning
        for 坏 in ({'章': '文本', '首次章': 1}, {'章': None}, {}, {'章': 0, '首次章': 0}):
            r.处理任务事件('重复章', 坏)
            self.assertEqual(t.metrics.duplicate_chapter_warning, 原值,
                             f'坏负载 {坏} 不得覆盖原告警')

    def test_字段默认空且不影响质检分(self):
        import task_manager as tm
        mt = tm.TaskMetrics()
        self.assertEqual(mt.duplicate_chapter_warning, '')
        self.assertEqual(mt.quality_score, -1.0, '新增字段不得改变质检默认值')


if __name__ == '__main__':
    unittest.main(verbosity=2)
