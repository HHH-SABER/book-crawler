# -*- coding: utf-8 -*-
"""GUI print 正则数据通道契约测试 (M11)。

TaskManager 以爬虫 print 文本的正则解析为唯一数据通道 (task_manager.py
TaskLogRedirector) — 爬虫侧改动以下任何文案都会**静默失效** (进度冻结/
指标列空白/"删除文件"失灵)。本文件把契约固化为单测: 改动爬虫文案或
task_manager 正则时, 必须同步更新这里, CI 门禁才会放行。

运行方式 (项目根目录):
    python -m unittest discover -s 测试 -v
"""

import os
import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '源码' / 'gui_components'))

import task_manager as tm


def _new_task() -> tm.TaskInfo:
    return tm.TaskInfo(task_id='t1', url='https://example.com/book/1')


def _feed(lines) -> tm.TaskInfo:
    """走真实 write() 管道喂入日志行 (含 标题/完成 终态解析)。"""
    task = _new_task()
    rd = tm.TaskLogRedirector(task, Path(os.devnull).open('w', encoding='utf-8'))
    for ln in lines:
        rd.write(ln + '\n')
    rd.original.close()
    return task


class TestProgressContract(unittest.TestCase):
    """进度/标题/输出文件/完成 终态的文案契约"""

    def test_novel_title(self):
        t = _feed(['提取到小说名称: 宿命之环'])
        self.assertEqual(t.title, '宿命之环')

    def test_chapter_progress(self):
        t = _feed(['=== 正在抓取第 3/120 章: 第一章 俗语 ==='])
        self.assertEqual(t.progress_current, 3)
        self.assertEqual(t.progress_total, 120)

    def test_progress_bar_format(self):
        t = _feed(['50/120 (41.7%)|----|'])
        self.assertEqual(t.progress_current, 50)
        self.assertEqual(t.progress_total, 120)

    def test_total_found(self):
        self.assertEqual(_feed(['共找到 88 个章节']).progress_total, 88)
        self.assertEqual(_feed(['共提取 120 个章节']).progress_total, 120)

    def test_saved_to_and_completed(self):
        t = _feed(['共找到 88 个章节',
                   '已保存至E:\\out\\书名.txt',
                   '抓取完成，共88章'])
        self.assertTrue(t.output_file.endswith('书名.txt'),
                        '"已保存至" 文案改动会破坏"删除文件"功能')
        self.assertEqual(t.status, 'completed')
        self.assertEqual(t.progress_total, 88)
        self.assertEqual(t.progress_current, 88)

    def test_stopped_wont_mark_completed(self):
        """M7 停止文案绝不能命中 '抓取完成' 正则 (否则停止任务被误标 completed)"""
        t = _feed(['任务已停止/中断: 目标100章, 失败3章, 进度检查点已保存'])
        self.assertNotEqual(t.status, 'completed')


class TestMetricsContract(unittest.TestCase):
    """引擎/反爬/质检/增量 指标列的文案契约"""

    def test_engine_success(self):
        t = _feed(['[反爬] ✅ curl_cffi 引擎请求成功 (耗时1.2s)'])
        self.assertEqual(t.metrics.engine, 'curl_cffi')

    def test_engine_fallback_chain(self):
        t = _feed(['[引擎] requests 请求异常: 超时',
                   '[反爬] ⚠️ cloudscraper 引擎请求失败 (403)',
                   '[反爬] ✅ curl_cffi 引擎请求成功'])
        self.assertEqual(t.metrics.engine_fallback_chain, ['requests', 'cloudscraper'])
        self.assertEqual(t.metrics.engine, 'curl_cffi')

    def test_anti_spider_types(self):
        cases = [
            ('[反爬] 频率限制, 退避 30 秒后重试 (第1次)', 'rate_limit'),
            ('[反爬] 命中 rate_limit, 尝试成熟反爬库引擎重发...', 'rate_limit'),
            ('[反爬检测] 命中 WAF 图片验证码页 (3000字节)，尝试自动解决...', 'waf_captcha'),
            ('[反爬检测] 命中 WAF JS 挑战页, 用浏览器渲染获取令牌 cookie...', 'waf_js_challenge'),
            ('[反爬检测] 第1次请求命中JS cookie校验页面(5000字节)，提取cookie后重试...', 'js_cookie'),
        ]
        for line, expect in cases:
            with self.subTest(line=line):
                t = _feed([line])
                self.assertEqual(t.metrics.anti_spider_type, expect)

    def test_quality_score(self):
        t = _feed(['[质检] 第3章 得分92 通过', '[质检] 第4章 得分45 失败(乱码率过高)'])
        self.assertEqual(t.metrics.quality_score, 45.0)
        self.assertIs(t.metrics.quality_passed, False)

    def test_incremental_skip_counts_per_line(self):
        """按行出现次数 +1 — 若爬虫把逐章日志合并为 '共跳过N章' 汇总行, 计数即错"""
        t = _feed(['[增量] 跳过第 1/100 章 (未变化): 第一章',
                   '[增量] 跳过第 2/100 章 (未变化): 第二章'])
        self.assertEqual(t.metrics.incremental_skipped, 2)


class TestTaskIdSortContract(unittest.TestCase):
    """任务列表排序契约: task_id 不保证是纯数字后缀。

    回归背景: 旧实现 get_all_tasks 用 int(task_id.split('_')[-1]) 排序, 而
    远控/服务.py 把从 checkpoint 恢复的中断任务写成 "resume_<md5前8位>" 型
    task_id → int() 抛 ValueError; 该异常从 get_all_tasks 冒出后被 GUI 刷新
    循环外层 try 吞掉, 导致任务表/状态栏/远控页整体静默停摆 (重启才恢复)。
    """

    @staticmethod
    def _mgr():
        return tm.TaskManager(page=object())

    def _add(self, mgr, task_id):
        t = tm.TaskInfo(task_id=task_id, url='https://example.com/book/1')
        mgr.tasks[task_id] = t
        return t

    def test_远控恢复任务id不使排序崩溃(self):
        mgr = self._mgr()
        want = ['task_1', 'task_2', 'task_10', 'resume_ab12cd34']
        for tid in want:
            self._add(mgr, tid)
        got = [t.task_id for t in mgr.get_all_tasks()]   # 旧实现此处抛 ValueError
        self.assertEqual(sorted(got), sorted(want))

    def test_数字后缀仍按数值排序(self):
        """M5 修复不得回退: 字典序会把 task_10 排到 task_2 之前"""
        mgr = self._mgr()
        for tid in ('task_10', 'task_2', 'task_1'):
            self._add(mgr, tid)
        self.assertEqual([t.task_id for t in mgr.get_all_tasks()],
                         ['task_1', 'task_2', 'task_10'])

    def test_无下划线task_id也能排序(self):
        mgr = self._mgr()
        for tid in ('abc', 'task_1'):
            self._add(mgr, tid)
        self.assertEqual(len(mgr.get_all_tasks()), 2)


class TestLogRingContract(unittest.TestCase):
    """日志环形缓冲: 上限 500 条, 且保留的是**最近** 500 条。"""

    def test_超限后保留最近500条(self):
        task = _new_task()
        rd = tm.TaskLogRedirector(task, Path(os.devnull).open('w', encoding='utf-8'))
        rd._log_to_file = lambda line: None      # 不污染真实日志文件
        for i in range(600):
            rd.write(f'第{i}行\n')
        rd.original.close()
        self.assertEqual(len(task.logs), 500)
        self.assertEqual(task.logs[0]['msg'], '第100行')
        self.assertEqual(task.logs[-1]['msg'], '第599行')


if __name__ == '__main__':
    unittest.main(verbosity=2)
