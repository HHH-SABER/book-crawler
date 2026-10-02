# -*- coding: utf-8 -*-
"""死书机制 阶段2: dead_pending 状态贯通回归 (2026-10-02)

背景: 死书处理 阶段1 落地了数据层 (判定/清单/删除编排) 并把任务置为终态
dead_pending, 但状态值散落在多个显示层。任一处漏改就是线上 bug, 且多数
是"静默降级"型 —— 界面回落灰色/ 显示裸英文 / 耗时列每秒疯涨 / 手机收不到
推送, 不抛异常, 只能靠肉眼发现。本文件把 8+3 处逐条钉死。

HANDOFF 阶段2 清单与本文件用例的对应:
  task_manager.py:90   状态声明注释      -> test_状态声明含死书
  ui_theme.py           样式/标签/状态色   -> test_样式与标签与状态色
  task_manager.py 序列化 dead 键         -> test_序列化含死书字段
  task_table.py _sig    刷新签名          -> test_刷新签名含死书标记
  row_detail.py         耗时冻结          -> test_死书耗时冻结
  task_table.py         清空历史终态元组  -> test_死书属可清空终态
  gui_app.py            状态栏计数        -> test_状态栏不把死书当就绪
  远控/服务.py          终态元组 + 状态词  -> test_远控终态含死书
  远控/面板.html        CSS + 标签字典    -> test_面板含死书样式与标签
"""
import os
import re
import sys
import time
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / '源码'
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _读源码(相对: str) -> str:
    return (_SRC / 相对).read_text(encoding='utf-8')


class Test死书状态贯通静态(unittest.TestCase):
    """静态契约: 源码文本必须含新状态值。

    这些断言的价值在于"锁住字符串": 有人把 dead_pending 从某处删掉时
    这里立刻红, 而不用等到用户抱怨界面显示裸英文。
    """

    def test_状态声明含死书(self):
        文本 = _读源码('gui_components/task_manager.py')
        行 = [ln for ln in 文本.splitlines() if 'status: str' in ln]
        self.assertTrue(行, 'TaskInfo.status 声明行未找到')
        self.assertIn('dead_pending', 行[0],
                      'TaskInfo.status 声明注释未含 dead_pending (状态取值集合失真)')

    def test_样式与标签与状态色(self):
        文本 = _读源码('gui_components/ui_theme.py')
        样式 = re.search(r'STATUS_STYLES\s*=\s*\{(.*?)\n\}', 文本, re.S)
        标签 = re.search(r'STATUS_LABELS\s*=\s*\{(.*?)\n\}', 文本, re.S)
        self.assertTrue(样式 and 标签, 'STATUS_STYLES/STATUS_LABELS 结构变了')
        self.assertIn('dead_pending', 样式.group(1),
                      'STATUS_STYLES 缺 dead_pending -> 状态胶囊回落灰色 pending 样式')
        self.assertIn('dead_pending', 标签.group(1),
                      'STATUS_LABELS 缺 dead_pending -> 界面显示裸英文 dead_pending')
        # status_color 供进度环/圆点用, 漏了会取默认灰
        self.assertIn('dead_pending', 文本.split('def status_color')[1],
                      'status_color 缺 dead_pending -> 进度环/圆点显灰')

    def test_序列化含死书字段(self):
        文本 = _读源码('gui_components/task_manager.py')
        白名单块 = 文本.split('白名单序列化')[1][:1200]
        self.assertRegex(白名单块, r"['\"]dead['\"]",
                         '序列化未落 dead 键 -> 重启后死书标记丢失')

    def test_刷新签名含死书标记(self):
        文本 = _读源码('gui_components/task_table.py')
        sig = 文本.split('def _refresh(self)')[1][:2000]
        self.assertRegex(sig, r'getattr\(\s*t\s*,\s*["\']dead["\']',
                         '_sig 未含 dead -> 阶段3 行内按钮分流不触发, 加了字段界面也不刷新')

    def test_面板含死书样式与标签(self):
        文本 = _读源码('远控/面板.html')
        self.assertIn('st-dead_pending', 文本,
                      '面板缺 st-dead_pending CSS -> 手机端状态无颜色')
        m = re.search(r'td2\.textContent\s*=\s*\(\{(.*?)\}\)\[', 文本, re.S)
        self.assertTrue(m, '面板状态标签字典结构变了')
        self.assertIn('dead_pending', m.group(1),
                      '面板标签字典缺 dead_pending -> 手机端显示裸英文')


class Test死书耗时冻结(unittest.TestCase):
    """row_detail._fmt_elapsed: 死书是终态, 耗时必须冻结。

    这是阶段2 最隐蔽的一处 bug: 漏判时耗时列每秒疯涨, 且不抛异常。
    """

    def setUp(self):
        from gui_components.row_detail import _fmt_elapsed
        self._fmt = _fmt_elapsed

    def _任务(self, status, end_time=None, start_time=None):
        class _M:
            pass
        from gui_components.task_manager import TaskInfo
        t = TaskInfo(task_id='t1', url='https://example.com/a')
        t.status = status
        t.metrics.start_time = start_time if start_time is not None else (time.time() - 500)
        t.metrics.end_time = end_time
        return t

    def test_死书耗时冻结(self):
        冻结时刻 = time.time() - 60
        t = self._任务('dead_pending', end_time=冻结时刻)
        第一次 = self._fmt(t)
        time.sleep(1.2)
        第二次 = self._fmt(t)
        self.assertEqual(第一次, 第二次,
                         '死书任务耗时仍在增长: _fmt_elapsed 未把 dead_pending '
                         '当终态冻结 (end_time 已置却被忽略)')

    def test_死书终态对比已完成行为一致(self):
        """死书与已完成同为终态, 冻结行为必须一致(防只改一半)。"""
        冻结时刻 = time.time() - 30
        死书 = self._任务('dead_pending', end_time=冻结时刻)
        完成 = self._任务('completed', end_time=冻结时刻)
        self.assertEqual(self._fmt(死书), self._fmt(完成))

    def test_死书无结束时间不崩(self):
        """end_time 缺失(极端情况)应回落到当前时间而非抛异常。"""
        t = self._任务('dead_pending', end_time=None)
        self.assertIsInstance(self._fmt(t), str)


class Test死书属可清空终态(unittest.TestCase):
    """任务表"清空历史"必须能清掉死书行, 否则点了没反应。"""

    def test_死书属可清空终态(self):
        文本 = _读源码('gui_components/task_table.py')
        块 = 文本.split('def 清空历史')[1][:1500] if 'def 清空历史' in 文本 else \
            文本.split('清空历史: 批量删除终态任务记录')[1][:1500]
        m = re.search(r't\.status in \(([^)]*)\)', 块, re.S)
        self.assertTrue(m, '清空历史的终态元组未找到')
        self.assertIn('dead_pending', m.group(1),
                      '清空历史终态元组缺 dead_pending -> 死书行点了"清空历史"没反应')


class Test远控推送含死书(unittest.TestCase):
    """远控是单向广播: 死书不推 = 用户在手机上完全不知情。"""

    def test_远控终态含死书(self):
        文本 = _读源码('远控/服务.py')
        块 = 文本.split('_已推终态')[1] if '_已推终态' in 文本 else 文本
        m = re.search(r't\.status not in \(([^)]*)\)', 块, re.S)
        self.assertTrue(m, '远控推送终态元组未找到')
        self.assertIn('dead_pending', m.group(1),
                      '远控终态元组缺 dead_pending -> 手机端收不到死书推送')
        self.assertRegex(文本, r'"dead_pending"\s*:\s*"[^"]+"',
                         '远控状态词字典缺 dead_pending -> 推送正文显示裸英文')


class Test状态栏死书分支(unittest.TestCase):
    """gui_app._status_loop: 死书既非 running 也非 failed。

    漏统计时状态栏显示"就绪", 而表里躺着一行待确认死书 —— 用户以为无事发生。
    """

    def test_状态栏不把死书当就绪(self):
        文本 = _读源码('gui_app.py')
        块 = 文本.split('def _status_loop')[1][:2500]
        self.assertIn('dead_pending', 块,
                      '_status_loop 未统计 dead_pending -> 有待确认死书却显示"就绪"')
        # 死书分支必须排在 failed 之前: 死书不该被红"失败 N 项"吞掉
        序 = 块.find('dead_pending')
        失败位 = 块.find('MORANDI_ERROR')
        self.assertTrue(序 >= 0 and 失败位 >= 0)
        self.assertLess(序, 失败位,
                        '死书分支应排在失败分支之前, 否则死书被误报为失败')


if __name__ == '__main__':
    unittest.main(verbosity=2)
