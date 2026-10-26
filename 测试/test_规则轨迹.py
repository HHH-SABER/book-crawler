# -*- coding: utf-8 -*-
"""规则轨迹的用例（S1 第二步）。

钉死四条契约：
1. **默认关闭**：不开开关时零记录；
2. **开着不改行为**：`适配器策略` 的返回值语义（True/False/None/异常→None）不受影响；
3. **确定性 + 隐私**：快照同输入两次逐字节一致，且**不含域名/URL**（只存主机指纹）；
4. **记录层绝不反噬**：记录函数自己抛异常时，分发照常返回。
"""
import json
import pathlib
import sys
import unittest
from unittest import mock

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '源码'))
sys.path.insert(0, str(_PROJECT_ROOT / '测试'))

import _沙箱  # noqa: E402,F401  状态根沙箱
import sites_config  # noqa: E402
import 规则轨迹  # noqa: E402

真域URL = 'https://very-real-site-name.example.net/read/1/1.html'


def _带钩子(钩子):
    return mock.patch.object(sites_config, 'get_adapter',
                             lambda url: {'站点策略': 钩子} if 钩子 else {})


def _无适配器():
    return mock.patch.object(sites_config, 'get_adapter', lambda url: None)


class 开关用例(unittest.TestCase):
    def setUp(self):
        import 规则轨迹 as 轨
        轨.清空()
        轨.停用()
        self.addCleanup(轨.停用)
        p = mock.patch.object(sites_config, 'load_adapters', lambda: None)
        p.start()
        self.addCleanup(p.stop)

    def test_默认关闭不记录(self):
        with _带钩子(lambda u, 阶段, **k: True):
            sites_config.适配器策略(真域URL, '目录规范化')
        self.assertEqual(规则轨迹.取记录(), [])
        self.assertFalse(规则轨迹.启用中())

    def test_启用后记录阶段与摘要(self):
        规则轨迹.启用()
        with _带钩子(lambda u, 阶段, **k: {'a': 1, 'b': 2}):
            sites_config.适配器策略(真域URL, '专属选择器', soup='<p>')
        记录 = 规则轨迹.取记录()
        self.assertEqual(len(记录), 1)
        条 = 记录[0]
        self.assertEqual(条['阶段'], '专属选择器')
        self.assertTrue(条['命中适配器'])
        self.assertEqual(条['返回摘要'], 'dict(2)')
        self.assertEqual(条['上下文键'], ['soup'])
        self.assertEqual(len(条['主机指纹']), 12)

    def test_未命中适配器也记一条(self):
        规则轨迹.启用()
        with _无适配器():
            sites_config.适配器策略(真域URL, '正文清理')
        记录 = 规则轨迹.取记录()
        self.assertEqual(len(记录), 1)
        self.assertFalse(记录[0]['命中适配器'])
        self.assertEqual(记录[0]['返回摘要'], 'None')


class 行为不变用例(unittest.TestCase):
    def setUp(self):
        规则轨迹.清空()
        规则轨迹.启用()
        self.addCleanup(规则轨迹.停用)
        p = mock.patch.object(sites_config, 'load_adapters', lambda: None)
        p.start()
        self.addCleanup(p.stop)

    def test_True透传(self):
        with _带钩子(lambda u, 阶段, **k: True):
            self.assertTrue(sites_config.适配器策略(真域URL, '目录'))

    def test_False透传(self):
        with _带钩子(lambda u, 阶段, **k: False):
            self.assertFalse(sites_config.适配器策略(真域URL, '目录'))

    def test_专用结果同一对象(self):
        值 = {'章节': [1, 2, 3]}
        with _带钩子(lambda u, 阶段, **k: 值):
            self.assertIs(sites_config.适配器策略(真域URL, '目录'), 值)

    def test_钩子异常仍返回None且留痕记录(self):
        def 炸(u, 阶段, **k):
            raise RuntimeError('适配器缺陷')
        with _带钩子(炸):
            self.assertIsNone(sites_config.适配器策略(真域URL, '目录'))
        记录 = 规则轨迹.取记录()
        self.assertEqual(记录[-1]['返回摘要'], '异常:RuntimeError')

    def test_记录层抛异常不影响分发(self):
        with mock.patch.object(规则轨迹, '记录', side_effect=RuntimeError('记录坏了')):
            with _带钩子(lambda u, 阶段, **k: 'ok'):
                self.assertEqual(sites_config.适配器策略(真域URL, '目录'), 'ok')


class 摘要与隐私用例(unittest.TestCase):
    def setUp(self):
        规则轨迹.清空()
        self.addCleanup(规则轨迹.停用)

    def test_上下文键排序保证确定性(self):
        规则轨迹.启用()
        规则轨迹.记录('目录', 'https://a.example.com/x', True, 结果=None,
                   上下文={'z': 1, 'a': 2, 'm': 3})
        规则轨迹.记录('目录', 'https://a.example.com/x', True, 结果=None,
                   上下文={'m': 3, 'a': 2, 'z': 1})
        记录 = 规则轨迹.取记录()
        self.assertEqual(记录[0]['上下文键'], 记录[1]['上下文键'])
        self.assertEqual(记录[0]['上下文键'], ['a', 'm', 'z'])

    def test_快照两次一致(self):
        规则轨迹.启用()
        for i in range(5):
            规则轨迹.记录('阶段' + str(i % 2), f'https://s{i}.example.com/x', i % 2 == 0,
                       结果={'k': i}, 上下文={'b': 1, 'a': 2})
        甲 = json.dumps(规则轨迹.快照(), ensure_ascii=False, sort_keys=True)
        规则轨迹.清空()
        for i in range(5):
            规则轨迹.记录('阶段' + str(i % 2), f'https://s{i}.example.com/x', i % 2 == 0,
                       结果={'k': i}, 上下文={'b': 1, 'a': 2})
        乙 = json.dumps(规则轨迹.快照(), ensure_ascii=False, sort_keys=True)
        self.assertEqual(甲, 乙)

    def test_快照不含域名与URL(self):
        规则轨迹.启用()
        规则轨迹.记录('目录', 真域URL, True, 结果='x' * 100, 上下文={'url': 真域URL})
        文 = json.dumps(规则轨迹.快照(), ensure_ascii=False)
        self.assertNotIn('example.net', 文, '真实域名绝不能进轨迹')
        self.assertNotIn('http', 文, 'URL 绝不能进轨迹')

    def test_摘要不含内容(self):
        规则轨迹.启用()
        规则轨迹.记录('目录', 真域URL, True, 结果='正文' * 500)
        self.assertEqual(规则轨迹.取记录()[0]['返回摘要'], 'str(1000)')

    def test_主机指纹稳定且不可逆(self):
        a = 规则轨迹.主机指纹('https://AbC.example.com/path?x=1')
        b = 规则轨迹.主机指纹('https://abc.example.com/other')
        self.assertEqual(a, b, '同主机（大小写不敏感）指纹应一致')
        self.assertNotIn('abc', a)
        self.assertEqual(len(a), 12)


class 快照元信息与比对用例(unittest.TestCase):
    """第三步：快照要能识别"过期"，比对要容忍历史格式。"""

    def test_元信息含版本时间HEAD与样本数(self):
        元 = 规则轨迹.生成元信息(样本数={'目录': 5, '正文': 7}, head='abc1234')
        self.assertEqual(元['工具版本'], 规则轨迹.版本)
        self.assertEqual(元['HEAD'], 'abc1234')
        self.assertEqual(元['样本数'], {'目录': 5, '正文': 7})
        self.assertRegex(元['生成时间'], r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$')

    def test_比对忽略元信息只比轨迹(self):
        轨 = {'记录数': 1, '记录': [{'序号': 1, '阶段': '目录', '主机指纹': 'a' * 12,
                                '命中适配器': True, '返回摘要': 'None', '上下文键': []}]}
        旧 = {'元信息': {'生成时间': '2026-01-01 00:00:00', 'HEAD': 'old1234'}, '轨迹': 轨}
        新 = {'元信息': {'生成时间': '2026-10-26 18:00:00', 'HEAD': 'new5678'}, '轨迹': 轨}
        self.assertEqual(规则轨迹.对比快照(旧, 新), [], '元信息差异不该判失败')

    def test_比对能定位条数与字段差异(self):
        基线 = {'轨迹': {'记录': [{'序号': 1, '阶段': '目录', '主机指纹': 'a' * 12,
                               '命中适配器': True, '返回摘要': 'None', '上下文键': []}]}}
        改后 = {'轨迹': {'记录': [{'序号': 1, '阶段': '目录', '主机指纹': 'a' * 12,
                               '命中适配器': False, '返回摘要': 'True', '上下文键': []}]}}
        差 = 规则轨迹.对比快照(基线, 改后)
        self.assertEqual(len(差), 1)
        self.assertIn('命中适配器', 差[0])
        self.assertIn('返回摘要', 差[0])

    def test_旧格式快照不崩(self):
        """历史格式（无 轨迹/记录 字段）只报条数变化，不抛异常。"""
        差 = 规则轨迹.对比快照({}, {'轨迹': {'记录': [{'序号': 1, '阶段': '目录'}]}})
        self.assertEqual(len(差), 1)
        self.assertIn('记录条数变化', 差[0])
        self.assertEqual(规则轨迹.对比快照({'轨迹': {'记录': []}},
                                    {'轨迹': {'记录': []}}), [])


if __name__ == '__main__':
    unittest.main()
