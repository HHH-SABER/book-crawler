# -*- coding: utf-8 -*-
"""死书判定回归 (2026-10-02 新增, 站点脱钩: 纯占位数据, 零 IO)。

锁定 死书处理.判定死书() 的三信号判定契约:
  页面为空 (inspect_page 重试耗尽 → 空 soup) → 站点不可达, 不可询问删除
  书名退化 (爬虫回退 novel/小说) + 0 章节    → 书已删除, 可询问删除
  书名正常 + 0 章节                          → 目录无章节, 不可询问删除
  章节数 > 0                                  → 不是死书
不变式: 可询问删除 ⟺ 类型 in 可询问删除类型 (UI 层的唯一分叉依据)
运行: python -m unittest discover -s 测试
"""
import sys
import unittest
from pathlib import Path

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

import 死书处理 as D   # noqa: E402


class Test判定死书(unittest.TestCase):

    def test_章节数大于零不是死书(self):
        self.assertIsNone(D.判定死书(页面为空=False, 书名='某书', 章节数=100))
        self.assertIsNone(D.判定死书(页面为空=True, 书名='某书', 章节数=1))

    def test_页面为空判站点不可达(self):
        r = D.判定死书(页面为空=True, 书名='某书', 章节数=0)
        self.assertEqual(r['类型'], D.类型_站点不可达)
        self.assertFalse(r['可询问删除'], '站点不可达不得询问删除 (删了可惜)')
        self.assertTrue(r['原因'])

    def test_书名退化判书已删除(self):
        for 书名 in D.书名退化集合:
            r = D.判定死书(页面为空=False, 书名=书名, 章节数=0)
            self.assertEqual(r['类型'], D.类型_书已删除, f'书名={书名!r}')
            self.assertTrue(r['可询问删除'], '书已删除应询问用户是否删除')

    def test_书名正常判目录无章节(self):
        r = D.判定死书(页面为空=False, 书名='正常书名', 章节数=0)
        self.assertEqual(r['类型'], D.类型_无章节)
        self.assertFalse(r['可询问删除'], '疑似选择器失效, 不应诱导用户删记录')

    def test_书名退化集合内容(self):
        """退化集合必须覆盖爬虫.py:5525-5531 的全部回退值 + None/空串"""
        for v in (None, '', 'novel', '小说'):
            self.assertIn(v, D.书名退化集合)

    def test_不变式_可询问删除等价类型(self):
        """可询问删除 ⟺ 类型在可询问删除类型里 (UI 不得自己判类型)"""
        for 页面为空 in (True, False):
            for 书名 in ('某书', 'novel', ''):
                r = D.判定死书(页面为空=页面为空, 书名=书名, 章节数=0)
                self.assertEqual(r['可询问删除'],
                                 r['类型'] in D.可询问删除类型)

    def test_优先级_页面为空优先于书名退化(self):
        """页面为空 + 书名退化 → 站点不可达 (而非书已删除)"""
        r = D.判定死书(页面为空=True, 书名='novel', 章节数=0)
        self.assertEqual(r['类型'], D.类型_站点不可达)

    def test_可询问删除类型只含书已删除(self):
        self.assertEqual(D.可询问删除类型, (D.类型_书已删除,))

    def test_死书错误三属性与文案(self):
        e = D.死书错误(D.类型_书已删除, '目录页无章节', 'https://example.com/book/1')
        self.assertIsInstance(e, RuntimeError)
        self.assertEqual(e.类型, D.类型_书已删除)
        self.assertEqual(e.原因, '目录页无章节')
        self.assertEqual(e.网址, 'https://example.com/book/1')
        self.assertIn(D.类型_书已删除, str(e))
        self.assertIn('目录页无章节', str(e))

    def test_死书错误网址可省(self):
        e = D.死书错误(D.类型_站点不可达, '页面为空')
        self.assertEqual(e.网址, '')

    def test_返回键完整(self):
        """三个返回分支的键集合必须一致 (UI 读键不会 KeyError)"""
        for 页面为空, 书名 in ((True, 'x'), (False, 'novel'), (False, 'x')):
            r = D.判定死书(页面为空=页面为空, 书名=书名, 章节数=0)
            self.assertEqual(set(r), {'类型', '原因', '可询问删除', '网站失效',
                                      '状态码', '已抓章节', '页面为空'})

    def test_章节数为零或负都判死书(self):
        for n in (0, -1):
            r = D.判定死书(页面为空=True, 书名='x', 章节数=n)
            self.assertIsNotNone(r)


class Test错误页标题K36(unittest.TestCase):
    """K36 (2026-10-03): 5xx 错误页标题被当书名时判 站点不可达。

    站点R 源站间歇 502, 目录页 <title> 是 "502 Bad Gateway" →
    书名提取拿到错误页标题 → 旧判定书名"正常" → 误判 目录无章节
    (误导用户查选择器)。修后归 站点不可达, 提示稍后重新检测。
    """

    def test_502标题判站点不可达(self):
        r = D.判定死书(页面为空=False, 书名='502 Bad Gateway', 章节数=0)
        self.assertEqual(r['类型'], D.类型_站点不可达)
        self.assertFalse(r['可询问删除'])
        self.assertIn('错误页', r['原因'])

    def test_各错误页短语都识别(self):
        for 书名 in ('502 Bad Gateway', '503 Service Unavailable',
                     '504 Gateway Time-out', 'Internal Server Error',
                     'Service Temporarily Unavailable'):
            self.assertTrue(D.是错误页标题(书名), f'书名={书名!r}')

    def test_正常书名不误伤(self):
        for 书名 in ('平凡的世界', '502号房客', '第503章 风暴', '我的504室友'):
            self.assertFalse(D.是错误页标题(书名), f'书名={书名!r}')

    def test_空书名不判错误页(self):
        self.assertFalse(D.是错误页标题(''))
        self.assertFalse(D.是错误页标题(None))

    def test_错误页优先级在退化之前_互斥性(self):
        """错误页标题不在退化集合中, 两分支互斥; 退化书名不受影响"""
        for v in D.书名退化集合:
            if not v:
                continue
            self.assertFalse(D.是错误页标题(v), f'退化值 {v!r} 不应同时命中错误页特征')
            r = D.判定死书(页面为空=False, 书名=v, 章节数=0)
            self.assertEqual(r['类型'], D.类型_书已删除)

    def test_返回键完整_错误页分支(self):
        r = D.判定死书(页面为空=False, 书名='502 Bad Gateway', 章节数=0)
        self.assertEqual(set(r), {'类型', '原因', '可询问删除', '网站失效',
                                  '状态码', '已抓章节', '页面为空'})


class Test数据缺口_状态码与已抓章节(unittest.TestCase):
    """批 3 数据缺口收口 (2026-10-07)。

    设计稿死书卡片 meta 行 = `URL · HTTP 码 · 判定于 <时间> · 已抓 N 章`,
    而记录里原本**没有**这两个字段 (设计会话明确留的缺口, 不许在 UI 层猜)。
    修法: 判定侧采集 → 判定死书 返回 → 死书错误 携带 → 记录死书 落盘。
    """

    def test_判定死书携带状态码与已抓章节(self):
        r = D.判定死书(页面为空=False, 书名='normal', 章节数=0,
                      状态码=404, 已抓章节=412)
        self.assertEqual(r['状态码'], 404)
        self.assertEqual(r['已抓章节'], 412)

    def test_每个分支都携带(self):
        """四条分支都必须带上 (漏一条 → UI 读到 0, 静默显示不全)"""
        分支 = [dict(页面为空=True, 书名='x'),
                dict(页面为空=False, 书名='502 Bad Gateway'),
                dict(页面为空=False, 书名='novel'),
                dict(页面为空=False, 书名='正常书名')]
        for kw in 分支:
            r = D.判定死书(章节数=0, 状态码=410, 已抓章节=7, **kw)
            self.assertEqual((r['状态码'], r['已抓章节']), (410, 7), f'分支 {kw}')

    def test_缺省即零不编造(self):
        r = D.判定死书(页面为空=True, 书名='x', 章节数=0)
        self.assertEqual(r['状态码'], 0)
        self.assertEqual(r['已抓章节'], 0)

    def test_页面为空随判定结果带走(self):
        """设计稿第 2 槽的词 (连接超时 / 内容为空) 取决于这个事实, 而非类型名"""
        self.assertTrue(D.判定死书(页面为空=True, 书名='x', 章节数=0)['页面为空'])
        # 5xx 错误页: 页面**拿到了** (只是内容是错误页) → 页面为空=False 且带状态码
        r = D.判定死书(页面为空=False, 书名='502 Bad Gateway', 章节数=0, 状态码=502)
        self.assertFalse(r['页面为空'])
        self.assertEqual(r['状态码'], 502)
        self.assertFalse(D.判定死书(页面为空=False, 书名='正常书名',
                                   章节数=0)['页面为空'])

    def test_页面为空非布尔值也被规整(self):
        for v, 期望 in ((1, True), (0, False), (None, False), ('', False)):
            r = D.判定死书(页面为空=v, 书名='x', 章节数=0)
            self.assertIs(r['页面为空'], 期望, f'值 {v!r}')

    def test_非法值归零(self):
        """None/空串不得让 int() 抛, 也不得写成假值"""
        for v in (None, '', 'x', 0):
            r = D.判定死书(页面为空=True, 书名='x', 章节数=0,
                          状态码=v, 已抓章节=v)
            self.assertEqual((r['状态码'], r['已抓章节']), (0, 0), f'值 {v!r}')

    def test_死书错误结构化携带(self):
        e = D.死书错误(D.类型_书已删除, '原因', 'https://example.com/b',
                       False, 404, 412, True)
        self.assertEqual(e.状态码, 404)
        self.assertEqual(e.已抓章节, 412)
        self.assertTrue(e.页面为空)

    def test_死书错误旧调用方式不破(self):
        """向后兼容: 老的三/四参位置调用仍可用, 新字段缺省为 0/False"""
        e = D.死书错误(D.类型_站点不可达, '页面为空', 'https://example.com/b', True)
        self.assertTrue(e.网站失效)
        self.assertEqual((e.状态码, e.已抓章节), (0, 0))
        self.assertFalse(e.页面为空)

    def test_死书错误脏值不抛(self):
        """异常对象在**工作线程**里构造 —— 脏值抛出去会连死书记录都落不下"""
        for v in (None, '', 'x', [1], {}):
            e = D.死书错误(D.类型_书已删除, '原因', 'https://e.example.com/b',
                           False, v, v)
            self.assertEqual((e.状态码, e.已抓章节), (0, 0), f'值 {v!r}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
