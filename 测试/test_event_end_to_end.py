# -*- coding: utf-8 -*-
"""U19 端到端验证: **把正则路径停掉**, 只靠事件通道驱动任务状态。

为什么需要它: `test_event_channel.py` 证明的是"事件与正则在**同一输入**下结果相同";
但摘除正则的前提是更强的性质 —— **在真实爬取流程里, 仅靠事件也能把状态填对**。
本文件用项目真实的 `NovelSpider.run()` 流程验证这一点:

    把 TaskLogRedirector 的 _parse_progress / _parse_metrics 换成空实现
    (= 模拟"正则已摘除"的世界), 然后跑一次离线抓取 (网络调用全部替换),
    断言任务状态依然被正确填充。

这是 U19 第二阶段(真正摘除正则)的**前置证据**: 本例通过 = 主要路径不再依赖文案解析。

运行方式 (项目根目录):
    python -m unittest discover -s 测试 -v
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))
sys.path.insert(0, str(_根 / '源码' / 'gui_components'))

import task_manager as tm            # noqa: E402
import 任务事件                        # noqa: E402


class Test事件通道端到端(unittest.TestCase):
    """真实 run() 流程 + 正则停用 → 状态仍正确"""

    def test_离线抓取仅靠事件驱动状态(self):
        from 爬虫 import NovelSpider

        任务 = tm.TaskInfo(task_id='e2e_1', url='https://example.com')
        重定向器 = tm.TaskLogRedirector(任务, None)
        # 关键: 停掉正则通道 —— 之后只有事件能改状态
        重定向器._parse_progress = lambda line: None
        重定向器._parse_metrics = lambda line: None

        任务事件.订阅(重定向器)
        输出目录 = Path(tempfile.mkdtemp(prefix='nc_e2e_')).resolve()
        书籍文件 = 输出目录 / '端到端测试书.txt'
        蜘蛛 = None
        try:
            蜘蛛 = NovelSpider('https://example.com')
            蜘蛛.get_novel_title = lambda url: '端到端测试书'
            蜘蛛.get_chapter_list = lambda url, sort=False: [
                {'title': f'第{i}章', 'url': f'https://example.com/{i}'}
                for i in range(1, 4)]
            # 不联网: 正文直接给足量内容, 使质检/落盘流程照常走
            蜘蛛.get_chapter_content = lambda url, *a, **k: ('正文内容。' * 300)
            蜘蛛._记录站点历史 = lambda *a, **k: None
            蜘蛛._记录爬取历史 = lambda *a, **k: None

            with mock.patch('风控事件.add'), mock.patch('风控事件.flush'):
                蜘蛛.run('https://example.com/book/1',
                         output_file=str(书籍文件), output_dir=str(输出目录),
                         resume=False, show_progress=False)
        finally:
            任务事件.退订(重定向器)
            if 蜘蛛 is not None:
                try:
                    蜘蛛.close()
                except Exception:
                    pass
            shutil.rmtree(输出目录, ignore_errors=True)

        # ---- 断言: 这些字段在正则停用后依然被填对, 说明事件通道真的在工作 ----
        self.assertEqual(任务.title, '端到端测试书',
                         '标题未被事件填上 (正则已停用)')
        self.assertEqual(任务.progress_total, 3,
                         f'总章数未被事件填上: {任务.progress_total}')
        self.assertEqual(任务.progress_current, 3,
                         f'当前进度未被事件填上: {任务.progress_current}')
        self.assertTrue((任务.output_file or '').endswith('.txt'),
                        f'输出文件未被事件填上: {任务.output_file!r}')

    def test_增量跳过事件在真实流程里累加(self):
        """增量模式: 跳过事件必须逐章累加 (契约要求按行/按次计数)"""
        from 爬虫 import NovelSpider

        任务 = tm.TaskInfo(task_id='e2e_2', url='https://example.com')
        重定向器 = tm.TaskLogRedirector(任务, None)
        重定向器._parse_progress = lambda line: None
        重定向器._parse_metrics = lambda line: None

        任务事件.订阅(重定向器)
        输出目录 = Path(tempfile.mkdtemp(prefix='nc_e2e2_')).resolve()
        书籍文件 = 输出目录 / '增量书.txt'
        # 预置"上次抓取"的内容, 让增量判定命中"未变化"
        书籍文件.write_text(
            ''.join(f'## 第{i}章\n\n第{i}章的旧正文内容{i * 111}\n\n'
                    for i in range(1, 4)), encoding='utf-8')
        蜘蛛 = None
        try:
            蜘蛛 = NovelSpider('https://example.com')
            蜘蛛.get_novel_title = lambda url: '增量书'
            蜘蛛.get_chapter_list = lambda url, sort=False: [
                {'title': f'第{i}章', 'url': f'https://example.com/{i}'}
                for i in range(1, 4)]
            蜘蛛._是否应跳过章节 = lambda url: True
            蜘蛛._记录站点历史 = lambda *a, **k: None
            蜘蛛._记录爬取历史 = lambda *a, **k: None

            with mock.patch('风控事件.add'), mock.patch('风控事件.flush'):
                蜘蛛.run('https://example.com/book/1',
                         output_file=str(书籍文件), output_dir=str(输出目录),
                         resume=True, show_progress=False,
                         incremental=True, incremental_max_age_hours=24)
        finally:
            任务事件.退订(重定向器)
            if 蜘蛛 is not None:
                try:
                    蜘蛛.close()
                except Exception:
                    pass
            shutil.rmtree(输出目录, ignore_errors=True)

        self.assertEqual(任务.metrics.incremental_skipped, 3,
                         f'增量跳过计数未经事件累加: '
                         f'{任务.metrics.incremental_skipped}')

    def test_未订阅时发布事件不产生任何副作用(self):
        """纯爬虫/CLI 场景: 无订阅方时必须零影响 (本例只需跑通不抛异常)"""
        from 爬虫 import NovelSpider

        任务事件.退订()
        输出目录 = Path(tempfile.mkdtemp(prefix='nc_e2e3_')).resolve()
        书籍文件 = 输出目录 / '无订阅.txt'
        蜘蛛 = None
        try:
            蜘蛛 = NovelSpider('https://example.com')
            蜘蛛.get_novel_title = lambda url: '无订阅'
            蜘蛛.get_chapter_list = lambda url, sort=False: [
                {'title': '第1章', 'url': 'https://example.com/1'}]
            蜘蛛.get_chapter_content = lambda url, *a, **k: '正文内容。' * 300
            蜘蛛._记录站点历史 = lambda *a, **k: None
            蜘蛛._记录爬取历史 = lambda *a, **k: None
            with mock.patch('风控事件.add'), mock.patch('风控事件.flush'):
                蜘蛛.run('https://example.com/book/1',
                         output_file=str(书籍文件), output_dir=str(输出目录),
                         resume=False, show_progress=False)
            内容 = 书籍文件.read_text(encoding='utf-8')
            self.assertIn('第1章', 内容)
        finally:
            if 蜘蛛 is not None:
                try:
                    蜘蛛.close()
                except Exception:
                    pass
            shutil.rmtree(输出目录, ignore_errors=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
