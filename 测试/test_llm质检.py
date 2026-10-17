# -*- coding: utf-8 -*-
"""LLM 增强质检测试 (C6 Roadmap P4, 2026-10-17)。

锁定契约:
  ① **默认关闭**: 缺配置/未启用时 启用中()=False, 判定章节直接 None 且
     **零 HTTP 调用** (抓取热路径不受影响);
  ② 三提供者调用形态 (ollama/openai_api/custom) 与请求体关键字段;
  ③ 判决解析: 三种响应形态取文本 / 严格 JSON 抽取 / 类别不合法→None;
  ④ 失败容错: 网络错/超时/坏 JSON/无判决 → 一律 None 不抛;
  ⑤ 触发分数线: 高于分数线的章节不送 (调用方闸, 这里测配置读取);
  ⑥ **只告警不改判铁律**: LLM建议 字段不影响 得分/有效;
  ⑦ 生成建议 文案格式。
运行: python -m unittest discover -s 测试
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

import LLM质检 as L   # noqa: E402


class 夹具(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._配置 = self.tmp / 'LLM质检配置.json'
        # 配置路径与 _path_utils 都指到临时目录 (不碰真状态根)
        self._补丁 = mock.patch.object(
            L, '取配置', lambda: L.取配置.__wrapped__(self) if False else self._读配置())
        self._补丁.start()

    def tearDown(self):
        self._补丁.stop()
        self._tmp.cleanup()

    def _读配置(self):
        cfg = dict(L._缺省)
        if self._配置.is_file():
            try:
                磁盘 = json.loads(self._配置.read_text(encoding='utf-8'))
                if isinstance(磁盘, dict):
                    cfg.update({k: v for k, v in 磁盘.items() if k in L._缺省})
            except Exception:
                pass
        return cfg

    def _写配置(self, **kw):
        底 = {'启用': True, 'provider': 'openai_api',
              'endpoint': 'http://127.0.0.1:9/v1', 'api_key': 'k',
              'model': 'm', '触发分数线': 60, '超时秒': 5, '每次最多字数': 100}
        底.update(kw)
        self._配置.write_text(json.dumps(底, ensure_ascii=False), encoding='utf-8')


class Test默认关闭(夹具):

    def test_无配置文件时全缺省且关闭(self):
        cfg = L.取配置()
        self.assertFalse(cfg['启用'])
        self.assertEqual(cfg['触发分数线'], 60)
        self.assertFalse(L.启用中())

    def test_未启用时判定章节零HTTP调用(self):
        """铁律: 默认关闭 ⇒ 一次 requests.post 都不许发"""
        with mock.patch('requests.post') as m:
            self.assertIsNone(L.判定章节('标题', '正文内容' * 50))
        m.assert_not_called()

    def test_启用但端点为空不调用(self):
        self._写配置(endpoint='')
        with mock.patch('requests.post') as m:
            self.assertIsNone(L.判定章节('标题', '正文内容' * 50))
        m.assert_not_called()
        self.assertFalse(L.启用中())

    def test_坏配置文件按关闭处理(self):
        self._配置.write_text('这不是JSON', encoding='utf-8')
        self.assertFalse(L.启用中())


class Test三提供者调用(夹具):

    def test_openai_api请求体(self):
        self._写配置(provider='openai_api', endpoint='http://x/v1',
                     api_key='sek', model='mm')
        with mock.patch('requests.post') as m:
            m.return_value.json.return_value = {
                'choices': [{'message': {'content': '{"类别":"乱码","原因":"r","建议":"s"}'}}]}
            m.return_value.raise_for_status.return_value = None
            判决 = L.判定章节('题', '正文' * 80)
        self.assertEqual(判决['类别'], '乱码')
        url = m.call_args[0][0]
        self.assertEqual(url, 'http://x/v1/chat/completions')
        self.assertEqual(m.call_args[1]['headers']['Authorization'], 'Bearer sek')
        负载 = m.call_args[1]['json']
        self.assertEqual(负载['model'], 'mm')

    def test_ollama请求体(self):
        self._写配置(provider='ollama', endpoint='http://x', model='q')
        with mock.patch('requests.post') as m:
            m.return_value.json.return_value = {
                'message': {'content': '{"类别":"广告","原因":"r","建议":"s"}'}}
            m.return_value.raise_for_status.return_value = None
            判决 = L.判定章节('题', '正文' * 80)
        self.assertEqual(判决['类别'], '广告')
        self.assertEqual(m.call_args[0][0], 'http://x/api/chat')

    def test_custom请求体(self):
        self._写配置(provider='custom', endpoint='http://x/judge', api_key='')
        with mock.patch('requests.post') as m:
            m.return_value.json.return_value = {
                'data': [{'content': '{"类别":"正文","原因":"r","建议":"s"}'}]}
            m.return_value.raise_for_status.return_value = None
            判决 = L.判定章节('题', '正文' * 80)
        self.assertEqual(判决['类别'], '正文')
        self.assertEqual(m.call_args[0][0], 'http://x/judge')


class Test判决解析(unittest.TestCase):

    def test_严格JSON抽取(self):
        d = L._抽取判决('前言废话 {"类别":"乱码","原因":"编码残留","建议":"重抓"} 后记')
        self.assertEqual(d['类别'], '乱码')
        self.assertEqual(d['建议'], '重抓')

    def test_类别不合法判失败(self):
        self.assertIsNone(L._抽取判决('{"类别":"色情","原因":"x","建议":"y"}'))
        self.assertIsNone(L._抽取判决('{"类别":"","原因":"x","建议":"y"}'))

    def test_无JSON判失败(self):
        self.assertIsNone(L._抽取判决('这一章看起来没问题'))
        self.assertIsNone(L._抽取判决(''))
        self.assertIsNone(L._抽取判决(None))

    def test_截断长度上限(self):
        d = L._抽取判决('{"类别":"正文","原因":"' + '原' * 200 + '","建议":"s"}')
        self.assertLessEqual(len(d['原因']), 120)


class Test失败容错(夹具):

    def test_网络异常返回None(self):
        import requests as _rq
        self._写配置()
        with mock.patch('requests.post', side_effect=_rq.ConnectionError('boom')):
            self.assertIsNone(L.判定章节('题', '正文' * 80))

    def test_超时返回None(self):
        import requests as _rq
        self._写配置()
        with mock.patch('requests.post', side_effect=_rq.Timeout('slow')):
            self.assertIsNone(L.判定章节('题', '正文' * 80))

    def test_坏JSON响应返回None(self):
        self._写配置()
        with mock.patch('requests.post') as m:
            m.return_value.json.side_effect = ValueError('not json')
            m.return_value.raise_for_status.return_value = None
            self.assertIsNone(L.判定章节('题', '正文' * 80))

    def test_空正文不送(self):
        self._写配置()
        with mock.patch('requests.post') as m:
            self.assertIsNone(L.判定章节('题', '   '))
        m.assert_not_called()


class Test生成建议(unittest.TestCase):

    def test_文案含类别与建议(self):
        文 = L.生成建议({'类别': '乱码', '原因': 'Base64 残留', '建议': '重抓'}, 42.0)
        self.assertIn('乱码', 文)
        self.assertIn('Base64 残留', 文)
        self.assertIn('42', 文)

    def test_空判决返回空(self):
        self.assertEqual(L.生成建议(None, 42.0), '')


class Test只告警不改判(unittest.TestCase):
    """铁律: LLM建议 是独立展示字段, 不影响质检评分 (与 P1 同族)"""

    def test_建议不影响质检结果(self):
        from 内容质检器 import 质检器
        正常正文 = ('这是完整的章节正文内容，情节连贯，句子通顺，长度充足。'
                    '他推门而入，屋里一片昏暗，只有桌上的一盏灯还亮着。'
                    '她站起身，脸上的表情看不出是惊讶还是早已等候多时。')
        r1 = 质检器.质检(正常正文, '测试章')
        r2 = 质检器.质检(正常正文, '测试章')
        r2.LLM建议 = 'LLM 复核: 判为「乱码」(42 分) — Base64 残留；建议: 重抓'
        self.assertEqual(r1.得分, r2.得分)
        self.assertEqual(r1.有效, r2.有效)

    def test_报告字段默认空(self):
        from 内容质检器 import 质检报告
        self.assertEqual(质检报告().LLM建议, '')


if __name__ == '__main__':
    unittest.main(verbosity=2)
