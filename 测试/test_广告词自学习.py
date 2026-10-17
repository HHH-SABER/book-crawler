# -*- coding: utf-8 -*-
"""广告词自学习测试 (C6 Roadmap P2, 2026-10-17)。

闭环: 删除 (clean_content 采样) → 观察 (计数聚合) → 审核 (待审清单) →
固化 (人工采纳并入 ad_rules + 热重载)。

锁定的契约:
  ① 记录删除批次: 域提取/次数累加/短文本前置过滤/空样本容忍/开关可关;
  ② 候选门槛: <3 次不候选 / 短文本不候选 / **已被规则覆盖不候选**
     (内置关键词子串 / 该域 ad_rules 关键词 / 行正则);
  ③ flush: 合并累加 (不清零) / 每域上限 / 总域上限 / 原子写;
  ④ 列出待审广告词 / 待审词条 (按次数降序);
  ⑤ 采纳: 并入 ad_rules.关键词 (无 ad_rules 则建) / 不动行正则 /
     配置无该域条目时拒绝且不擅自建 / 成功后移除候选;
  ⑥ 拒绝: 仅移除候选, 配置零触碰;
  ⑦ **方案 A 铁律**: 全程无"自动生效"路径 —— 只有 采纳广告词 (人工) 写配置。

运行: python -m unittest discover -s 测试
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

import 广告词自学习 as A   # noqa: E402


class 夹具(unittest.TestCase):
    """每个用例: 独立临时状态根 + 干净的内存计数。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._旧计数 = A._计数
        self._旧启用 = A.启用
        A._计数 = {}
        A.启用 = True
        # 待审文件与配置路径都指到临时目录
        self._待审 = self.tmp / '数据' / '待审广告词.json'
        self._配置 = self.tmp / '站点配置.json'
        self._配置.write_text('[]', encoding='utf-8')
        (self.tmp / '数据').mkdir(exist_ok=True)
        self._补丁 = [
            mock.patch.object(A, '_待审文件', lambda: str(self._待审)),
            mock.patch.object(A, '_配置路径', lambda: str(self._配置)),
        ]
        for p in self._补丁:
            p.start()

    def tearDown(self):
        for p in self._补丁:
            p.stop()
        A._计数 = self._旧计数
        A.启用 = self._旧启用
        self._tmp.cleanup()

    def _记(self, 行, 次数=1, 类别='广告行', url='https://site-a.example/x/'):
        A.记录删除批次(url, [(行, 类别)] * 次数)


class Test记录删除批次(夹具):

    def test_次数累加与域提取(self):
        self._记('站点装饰文案甲', 次数=2)
        self._记('站点装饰文案甲', 次数=3)
        键 = ('site-a.example', '站点装饰文案甲')
        self.assertIn(键, A._计数)
        self.assertEqual(A._计数[键][0], 5)

    def test_空URL与空样本容忍(self):
        A.记录删除批次('', [('词甲内容', '广告行')] * 5)
        A.记录删除批次('https://a.example/', [])
        A.记录删除批次('https://a.example/', None)
        self.assertEqual(A._计数, {})

    def test_短文本前置过滤(self):
        """<4 字的删除行是正文残片不是规则 —— 录入时即弃 (省内存)"""
        self._记('好的', 次数=10)
        self.assertEqual(A._计数, {})

    def test_空白归一与截断(self):
        self._记('广告  文案\t内容' * 20, 次数=3)   # 超长 → 截断到 50
        键 = list(A._计数)[0]
        self.assertLessEqual(len(键[1]), 50)
        self.assertNotIn('\t', 键[1])

    def test_开关可关(self):
        A.启用 = False
        self._记('站点装饰文案甲', 次数=5)
        self.assertEqual(A._计数, {})


class Test候选门槛(夹具):

    def test_不足三次不候选(self):
        self._记('站点装饰文案甲', 次数=2)
        self.assertEqual(A._候选(), {})

    def test_达三次是候选(self):
        self._记('站点装饰文案甲', 次数=3)
        出 = A._候选()
        self.assertIn('site-a.example', 出)
        self.assertEqual(出['site-a.example'][0][0], '站点装饰文案甲')

    def test_内置关键词覆盖的不候选(self):
        """删除行里含内置关键词 (如'请收藏本站') ⇒ 既定行为, 无新增价值"""
        self._记('请收藏本站并记住域名哦', 次数=10)
        self.assertEqual(A._候选(), {}, '被内置关键词覆盖的行不应候选')

    def test_域规则覆盖的不候选(self):
        with mock.patch('sites_config.获取广告规则',
                        return_value={'关键词': ['站点装饰文案甲'],
                                      '正则': []}):
            self._记('站点装饰文案甲补充说明', 次数=10)
            self.assertEqual(A._候选(), {}, '被该域 ad_rules 覆盖的不应候选')

    def test_域行正则覆盖的不候选(self):
        import re as _re
        with mock.patch('sites_config.获取广告规则',
                        return_value={'关键词': [],
                                      '正则': [_re.compile('装饰')]}):
            self._记('站点装饰文案甲', 次数=10)
            self.assertEqual(A._候选(), {}, '被该域行正则覆盖的不应候选')


class TestFlush(夹具):

    def test_合并累加不清零(self):
        self._记('站点装饰文案甲', 次数=3)
        self.assertEqual(A.flush(), 1)
        self._记('站点装饰文案甲', 次数=4)
        self.assertEqual(A.flush(), 1)
        词 = A.待审词条('site-a.example')[0]
        self.assertEqual(词['次数'], 7, 'flush 是合并累加, 不是覆盖')

    def test_每域上限淘汰次数最少(self):
        for i in range(35):
            self._记(f'候选长文本编号{i:02d}', 次数=3 + i)
        A.flush()
        词条 = A.待审词条('site-a.example')
        self.assertLessEqual(len(词条), 30)
        self.assertEqual(词条[0]['词'], '候选长文本编号34', '次数最多的应保留')

    def test_总域上限(self):
        for i in range(55):
            A.记录删除批次(f'https://site-{i:02d}.example/x/',
                          [('站点装饰文案甲', '广告行')] * 3)
        A.flush()
        全部 = A.列出待审广告词()
        self.assertLessEqual(len(全部), 50)

    def test_无候选返回0(self):
        self.assertEqual(A.flush(), 0)


class Test审核闭环(夹具):

    def _预置候选(self, 词='站点装饰文案甲', 次数=3):
        self._记(词, 次数=次数)
        A.flush()
        return 词

    def test_列出与降序(self):
        self._预置候选('站点装饰文案甲', 3)
        self._预置候选('另一条推广文案乙', 9)
        词条 = A.待审词条('site-a.example')
        self.assertEqual(词条[0]['词'], '另一条推广文案乙')

    def test_采纳并入ad_rules(self):
        词 = self._预置候选()
        self._配置.write_text(json.dumps(
            [{'domain': 'site-a.example', 'pattern': 'site-a.example'}],
            ensure_ascii=False), encoding='utf-8')
        with mock.patch.object(A, '_热重载', lambda: ''):
            ok, msg = A.采纳广告词('site-a.example', 词)
        self.assertTrue(ok, msg)
        配置 = json.loads(self._配置.read_text(encoding='utf-8'))
        self.assertEqual(配置[0]['ad_rules']['关键词'], [词])
        self.assertEqual(A.待审词条('site-a.example'), [], '采纳后候选应移除')

    def test_采纳_无ad_rules则新建且不碰行正则(self):
        词 = self._预置候选()
        self._配置.write_text(json.dumps(
            [{'domain': 'site-a.example',
              'ad_rules': {'行正则': ['^广告']}}], ensure_ascii=False),
            encoding='utf-8')
        with mock.patch.object(A, '_热重载', lambda: ''):
            ok, _ = A.采纳广告词('site-a.example', 词)
        self.assertTrue(ok)
        配置 = json.loads(self._配置.read_text(encoding='utf-8'))
        self.assertEqual(配置[0]['ad_rules']['关键词'], [词])
        self.assertEqual(配置[0]['ad_rules']['行正则'], ['^广告'], '行正则不得被动')

    def test_采纳_配置无该域拒绝且不擅自建(self):
        词 = self._预置候选()
        ok, msg = A.采纳广告词('site-a.example', 词)
        self.assertFalse(ok)
        self.assertIn('不擅自新建', msg)
        self.assertEqual(A.待审词条('site-a.example')[0]['词'], 词,
                         '失败时候选必须保留')

    def test_采纳_词不在候选中拒绝(self):
        ok, _ = A.采纳广告词('site-a.example', '不存在的词文本')
        self.assertFalse(ok)

    def test_拒绝仅移除候选配置零触碰(self):
        词 = self._预置候选()
        原文 = self._配置.read_text(encoding='utf-8')
        ok, msg = A.拒绝广告词('site-a.example', 词)
        self.assertTrue(ok, msg)
        self.assertEqual(self._配置.read_text(encoding='utf-8'), 原文)
        self.assertEqual(A.待审词条('site-a.example'), [])

    def test_拒绝不存在词返回失败(self):
        ok, _ = A.拒绝广告词('site-a.example', '不存在的词文本')
        self.assertFalse(ok)


class Test方案A铁律(夹具):
    """铁律: 除了人工 采纳广告词, 没有任何路径会写 站点配置.json。"""

    def test_收集与flush都不碰配置(self):
        self._记('站点装饰文案甲', 次数=10)
        A.flush()
        原文 = self._配置.read_text(encoding='utf-8')
        self.assertEqual(self._配置.read_text(encoding='utf-8'), '[]',
                         '待审流程不得改配置')
        self.assertEqual(原文, '[]')


if __name__ == '__main__':
    unittest.main(verbosity=2)
