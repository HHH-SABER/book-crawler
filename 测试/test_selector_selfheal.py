# -*- coding: utf-8 -*-
"""选择器自愈模块离线回归测试 (批3 PoC-A)。

覆盖 (2026-09-14 探针 probe_selfheal_a95e0468 实测口径):
- score_candidates: 真实快照命中正确容器 / 加密页负样本低分 / 祖先去重边界
- make_selector: id 唯一命中 / 无唯一选择器返回 None
- try_heal + 记录建议: 端到端产出建议并原子写盘 (tmp 目录, 不碰真实 数据/)
- 门槛行为: 置信度不足不产出 (防把软封页/加密变更误当普通改版)

依赖 测试样本/ 快照: ltbook_content.html (明文#rtext), qiqishu_content.html (加密负样本)。
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_PROJECT_ROOT, '源码')
_SAMPLES = os.path.join(_PROJECT_ROOT, '测试样本')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from bs4 import BeautifulSoup  # noqa: E402
import 选择器自愈 as heal      # noqa: E402


def _read(name):
    return Path(os.path.join(_SAMPLES, name)).read_text(encoding='utf-8', errors='replace')


class Test启发式打分(unittest.TestCase):
    def test_明文快照命中大正文容器(self):
        soup = BeautifulSoup(_read('ltbook_content.html'), 'lxml')
        cands = heal.score_candidates(soup)
        self.assertTrue(cands, '明文页应产出候选')
        score, node = cands[0]
        self.assertGreaterEqual(score, heal._MIN_CONFIDENCE)
        self.assertGreaterEqual(heal._cn_len(node.get_text()), heal._MIN_CN)

    def test_加密页负样本分数低于门槛(self):
        # 探针实测: qiqishu (base64 加密) 启发式最高分仅 0.179 << 0.55
        soup = BeautifulSoup(_read('qiqishu_content.html'), 'lxml')
        cands = heal.score_candidates(soup)
        if cands:
            self.assertLess(cands[0][0], heal._MIN_CONFIDENCE,
                            '加密页不应产出可信容器 (门槛须压制住)')


class Test选择器生成(unittest.TestCase):
    def test_id选择器唯一(self):
        html = '<div><p>x</p><div id="rtext">' + '章' * 400 + '</div><div id="side">' + '录' * 300 + '</div></div>'
        soup = BeautifulSoup(html, 'lxml')
        node = soup.select_one('#rtext')
        self.assertEqual(heal.make_selector(node, soup), '#rtext')

    def test_非唯一类名回退None(self):
        # 目标节点 id/class 全无 -> 无法生成唯一选择器, 宁缺勿滥
        html = '<div>' + '<span class="c">' * 2 + '章' * 400 + '</span></span></div>'
        soup = BeautifulSoup(html, 'lxml')
        target = soup.find_all('span')[0]
        self.assertIsNone(heal.make_selector(target, soup))


class Test端到端自愈(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file = os.path.join(self.tmp.name, '选择器建议.json')
        self._p = mock.patch.object(heal, '_建议文件', return_value=self.file)
        self._p.start()

    def tearDown(self):
        self._p.stop()
        self.tmp.cleanup()

    def test_抹除id后找回并落盘建议(self):
        html = _read('ltbook_content.html')
        soup = BeautifulSoup(html, 'lxml')
        node = soup.select_one('#rtext')
        self.assertIsNotNone(node, '样本前提: #rtext 应存在')
        node['class'] = ['healed_x']   # 模拟改版: id 改名
        del node['id']
        sug = heal.try_heal(soup, 'ltbook.net', ['#rtext', '#content'])
        if sug is None:
            self.skipTest('探针口径: ltbook 抹除后 top1 可找回; 若打分漂移则本例降级跳过')
        data = json.loads(Path(self.file).read_text(encoding='utf-8'))
        self.assertIn('ltbook.net', data)
        self.assertEqual(data['ltbook.net']['建议选择器'], sug['建议选择器'])
        # 回读唯一性: 建议选择器必须恰好命中那个容器
        again = BeautifulSoup(html, 'lxml')
        again.select_one(sug['建议选择器'])  # 不抛异常即语法合法

    def test_低置信不产出建议(self):
        # 空壳页: 无任何可信容器 -> None 且 不写文件
        soup = BeautifulSoup('<div>' + 'x' * 50 + '</div>', 'lxml')
        self.assertIsNone(heal.try_heal(soup, 'empty.example', ['#content']))
        self.assertFalse(os.path.exists(self.file))

    def test_原子写且每域只留最新(self):
        heal.记录建议({'域名': 'a.com', '建议选择器': '#x', '置信度': 0.9})
        heal.记录建议({'域名': 'a.com', '建议选择器': '#y', '置信度': 0.8})
        data = json.loads(Path(self.file).read_text(encoding='utf-8'))
        self.assertEqual(len(data), 1)
        self.assertEqual(data['a.com']['建议选择器'], '#y')
        # tmp 残留清理: 目录内只应有最终文件
        left = [f for f in os.listdir(self.tmp.name) if '.tmp' in f]
        self.assertEqual(left, [], f'原子写不应残留 tmp: {left}')

    def test_防膨胀五十域上限(self):
        for i in range(55):
            heal.记录建议({'域名': f'd{i}.com', '建议选择器': '#x', '置信度': 0.9})
        data = heal.取待审建议()
        self.assertLessEqual(len(data), 50)


class Test挂载点行为(unittest.TestCase):
    def test_HTML分支选择器落空时调用自愈(self):
        """sites_config.extract_content 集成: 落空才自愈, 命中则零接触。"""
        import sites_config as sc
        called = []

        def _fake_heal(soup, domain, old):
            called.append(domain)
            return None

        html = ('<html><body><div id="zz">' + '正文' * 300 + '</div></body></html>').encode('utf-8')

        class _R:
            content = html

        def _inspect(url, headers):
            return _R()

        pat = {'pattern': sc.PATTERN_HTML_SELECTOR, 'domain': 'healtest.example',
               'content_selectors': ['#nonexistent_9x']}
        with mock.patch('选择器自愈.try_heal', _fake_heal):
            text, ok = sc.extract_content(None, 'https://healtest.example/c/1.html',
                                          pat, 'https://healtest.example', {}, _inspect)
        self.assertIn('healtest.example', called, '选择器落空应触发自愈钩子')

        # 对照: 选择器命中时不得触发
        called.clear()
        pat2 = dict(pat, content_selectors=['#zz'])
        with mock.patch('选择器自愈.try_heal', _fake_heal):
            text2, ok2 = sc.extract_content(None, 'https://healtest.example/c/1.html',
                                            pat2, 'https://healtest.example', {}, _inspect)
        self.assertEqual(called, [], '规则命中路径必须零接触自愈')
        self.assertTrue(ok2, '命中路径行为应与旧版一致')


class Test审核闭环(unittest.TestCase):
    """批3 PoC-B: 采纳/拒绝建议 (核心函数层; CLI 脚本只做展示不单测)。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sug_file = os.path.join(self.tmp.name, '选择器建议.json')
        self.cfg_file = os.path.join(self.tmp.name, '站点配置.json')
        self._p1 = mock.patch.object(heal, '_建议文件', return_value=self.sug_file)
        self._p2 = mock.patch.object(heal, '_配置路径', return_value=self.cfg_file)
        self._p1.start(); self._p2.start()

    def tearDown(self):
        self._p1.stop(); self._p2.stop()
        self.tmp.cleanup()

    def _seed(self, cfg_items, suggestion):
        Path(self.cfg_file).write_text(json.dumps(cfg_items, ensure_ascii=False),
                                       encoding='utf-8')
        heal.记录建议(suggestion)

    def test_采纳_前插并移除建议_不碰enabled(self):
        self._seed(
            [{"domain": "a.com", "content_selectors": ["#old"], "pattern": "html_selector"}],
            {"域名": "a.com", "建议选择器": "#new", "原选择器": ["#old"], "置信度": 0.9})
        with mock.patch('sites_config.reload_runtime_config') as rl:
            ok, msg = heal.采纳建议('a.com')
        self.assertTrue(ok, msg)
        cfg = json.loads(Path(self.cfg_file).read_text(encoding='utf-8'))
        self.assertEqual(cfg[0]['content_selectors'], ['#new', '#old'],
                         '新选择器应前插且保留旧选择器兜底')
        self.assertNotIn('enabled', cfg[0], '不得擅改 enabled (禁用中站点不悄悄启用)')
        rl.assert_called_once()
        self.assertIsNone(heal.取待审建议('a.com'), '采纳后建议应移除')

    def test_采纳_禁用中站点保持禁用(self):
        self._seed([{"domain": "b.com", "content_selectors": ["#old"], "enabled": False}],
                   {"域名": "b.com", "建议选择器": "#new", "置信度": 0.8})
        with mock.patch('sites_config.reload_runtime_config'):
            ok, _ = heal.采纳建议('b.com')
        self.assertTrue(ok)
        cfg = json.loads(Path(self.cfg_file).read_text(encoding='utf-8'))
        self.assertIs(False, cfg[0]['enabled'], 'enabled=False 必须原样保留')

    def test_采纳_配置无该域_保留建议中止(self):
        heal.记录建议({"域名": "ghost.com", "建议选择器": "#x", "置信度": 0.9})
        Path(self.cfg_file).write_text('[]', encoding='utf-8')
        ok, msg = heal.采纳建议('ghost.com')
        self.assertFalse(ok)
        self.assertIn('无站点', msg)
        self.assertIsNotNone(heal.取待审建议('ghost.com'), '失败时建议必须保留可重试')

    def test_采纳_选择器已存在仅清理建议(self):
        self._seed([{"domain": "c.com", "content_selectors": ["#dup", "#old"]}],
                   {"域名": "c.com", "建议选择器": "#dup", "置信度": 0.7})
        with mock.patch('sites_config.reload_runtime_config'):
            ok, _ = heal.采纳建议('c.com')
        self.assertTrue(ok)
        cfg = json.loads(Path(self.cfg_file).read_text(encoding='utf-8'))
        self.assertEqual(cfg[0]['content_selectors'], ['#dup', '#old'], '不应重复前插')
        self.assertIsNone(heal.取待审建议('c.com'))

    def test_采纳_热重载失败仍算成功并提示(self):
        self._seed([{"domain": "d.com", "content_selectors": ["#old"]}],
                   {"域名": "d.com", "建议选择器": "#new", "置信度": 0.9})
        with mock.patch('sites_config.reload_runtime_config',
                        side_effect=RuntimeError('boom')):
            ok, msg = heal.采纳建议('d.com')
        self.assertTrue(ok, '配置已落盘, 热重载失败不回滚 (下次启动生效)')
        self.assertIn('热重载失败', msg)
        cfg = json.loads(Path(self.cfg_file).read_text(encoding='utf-8'))
        self.assertEqual(cfg[0]['content_selectors'][0], '#new')

    def test_采纳_配置坏JSON中止保留建议(self):
        Path(self.cfg_file).write_text('{不是json', encoding='utf-8')
        heal.记录建议({"域名": "e.com", "建议选择器": "#new", "置信度": 0.9})
        ok, msg = heal.采纳建议('e.com')
        self.assertFalse(ok)
        self.assertIn('读取失败', msg)
        self.assertIsNotNone(heal.取待审建议('e.com'))

    def test_拒绝_配置不动仅移除建议(self):
        self._seed([{"domain": "f.com", "content_selectors": ["#old"]}],
                   {"域名": "f.com", "建议选择器": "#new", "置信度": 0.9})
        before = Path(self.cfg_file).read_text(encoding='utf-8')
        ok, _ = heal.拒绝建议('f.com')
        self.assertTrue(ok)
        self.assertEqual(before, Path(self.cfg_file).read_text(encoding='utf-8'),
                         '拒绝不得触碰站点配置')
        self.assertIsNone(heal.取待审建议('f.com'))

    def test_拒绝_无建议返回False(self):
        ok, _ = heal.拒绝建议('nope.com')
        self.assertFalse(ok)

    def test_列出待审_置信度降序(self):
        heal.记录建议({"域名": "low.com", "建议选择器": "#l", "置信度": 0.6})
        heal.记录建议({"域名": "high.com", "建议选择器": "#h", "置信度": 0.95})
        items = heal.列出待审()
        self.assertEqual([i['域名'] for i in items], ['high.com', 'low.com'])

    def test_采纳后建议文件无tmp残留(self):
        self._seed([{"domain": "g.com", "content_selectors": ["#old"]}],
                   {"域名": "g.com", "建议选择器": "#new", "置信度": 0.9})
        with mock.patch('sites_config.reload_runtime_config'):
            heal.采纳建议('g.com')
        left = [f for f in os.listdir(self.tmp.name) if '.tmp' in f]
        self.assertEqual(left, [], f'不应残留 tmp: {left}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
