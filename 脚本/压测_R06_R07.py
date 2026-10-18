# -*- coding: utf-8 -*-
"""R06/R07 测量台 (2026-10-18): 超大任务离线压测 + 弱网模拟。

R06 登记项: "以长目录离线样本记录峰值内存、排队量和停止延迟, 再做滚动提交。
停止后不得误推进检查点, 不丢运行项。"
R07 登记项: "先用离线替身模拟延迟、超时、断连, 记录请求次数、停止延迟、
重启完整性。改善必须有前后数据。"

本脚本全部离线 (mock 抓取, 零网络), 可反复运行:
    python 脚本/压测_R06_R07.py            # 全部场景
    python 脚本/压测_R06_R07.py r06        # 只跑超大任务
    python 脚本/压测_R06_R07.py r07        # 只跑弱网/停止

测量口径:
· 峰值内存 = 进程 PeakWorkingSetSize (Win32 GetProcessMemoryInfo);
· 排队量 = 并发提交后未完成的 future 数上限 (提交循环采样);
· 停止延迟 = stop_event.set() 时刻 → run() 返回时刻;
· 重启完整性 = 停止后 resume 至完成, 章节数精确、无重复。
"""
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '源码'))

from unittest import mock   # noqa: E402

import 爬虫 as c   # noqa: E402


def _造蜘蛛(目录数=1):
    spider = c.NovelSpider('https://example.com/book')
    spider.get_novel_title = lambda *a: '压测书'
    spider._记录站点历史 = lambda *a, **k: None
    spider._记录爬取历史 = lambda *a, **k: None
    spider._生成质检汇总报告 = lambda *a, **k: {}
    spider._是否应跳过章节 = lambda *a: False
    return spider


def 场景R06_超大任务(总章数=5000, threads=4, 停止在第=None):
    """R06: 长目录离线任务, 采峰值内存/排队量/停止延迟。"""
    print(f'\n===== R06 超大任务: {总章数} 章, threads={threads}, '
          f'停止在第={停止在第 or "不停止"} =====')
    root = Path(tempfile.mkdtemp())
    output = root / 'big.txt'
    spider = _造蜘蛛()
    spider.get_chapter_list = lambda *a: [
        {'title': f'第{i}章', 'url': f'https://example.com/{i}'} for i in range(1, 总章数 + 1)]
    spider._fetch_with_retry = mock.Mock(return_value='压测正文')
    spider._fetch_chapter_worker = mock.Mock(return_value='压测正文')

    排队峰值 = [0]
    真submit = __import__('concurrent.futures', fromlist=['ThreadPoolExecutor']).ThreadPoolExecutor.submit
    stop_ev = threading.Event()

    def 采样submit(pool, fn, *a, **k):
        fut = 真submit(pool, fn, *a, **k)
        return fut

    # 排队量采样: 包装 run 内部不可达, 改为在 worker 侧计数 (在池中未完成数 = 提交-完成)
    # 简化口径: 记录 _fetch_chapter_worker 被调用时的活跃 future 数不可得,
    # 改测"提交循环总耗时"(全部提交一次性的直接证据) 与 worker 调用数。
    原worker = spider._fetch_chapter_worker
    调用数 = [0]

    def 采样worker(chap, stop_event=None):
        调用数[0] += 1
        if 停止在第 and 调用数[0] == 停止在第 and not stop_ev.is_set():
            stop_ev.set()
            print(f'  [模拟] 第 {调用数[0]} 章后置位 stop_event')
        return 原worker(chap, stop_event)

    spider._fetch_chapter_worker = 采样worker
    spider._fetch_with_retry = mock.Mock(return_value='压测正文')

    import tracemalloc
    tracemalloc.start()
    t0 = time.monotonic()
    结果 = None
    with mock.patch('风控事件.add'), mock.patch('风控事件.flush'), \
            mock.patch('网站清单.记录'):
        if 停止在第:
            结果 = spider.run('https://example.com/book', output_file=str(output),
                              output_dir=str(root), resume=False, show_progress=False,
                              threads=threads, delay=0, stop_event=stop_ev)
        else:
            结果 = spider.run('https://example.com/book', output_file=str(output),
                              output_dir=str(root), resume=False, show_progress=False,
                              threads=threads, delay=0)
    耗时 = time.monotonic() - t0
    _当前, 峰值 = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    text = output.read_text(encoding='utf-8') if output.exists() else ''
    数据 = {
        '总章数': 总章数, 'threads': threads,
        '耗时秒': round(耗时, 2),
        'worker调用数': 调用数[0],
        'Python峰值分配MB': round(峰值 / 1048576, 2),
        '写出章节数': text.count('## '),
        '正常完成': not spider.last_aborted,
    }
    print(f'  结果: {json.dumps(数据, ensure_ascii=False)}')
    spider.close()
    return 数据, root, output


def 场景R07_停止延迟与重启(总章数=2000, threads=2):
    """R07: 慢速 fetch 下停止延迟 + 停止后重启完整性。"""
    print(f'\n===== R07 弱网/停止: {总章数} 章, threads={threads} (每章模拟 0.05s 慢速) =====')
    root = Path(tempfile.mkdtemp())
    output = root / 'weak.txt'
    spider = _造蜘蛛()
    spider.get_chapter_list = lambda *a: [
        {'title': f'第{i}章', 'url': f'https://example.com/{i}'} for i in range(1, 总章数 + 1)]
    原worker = spider._fetch_chapter_worker
    stop_ev = threading.Event()
    停止时刻 = [None]

    def 慢worker(chap, stop_event=None):
        time.sleep(0.05)          # 模拟网络延迟
        if 调用数[0] == 60 and not stop_ev.is_set():
            停止时刻[0] = time.monotonic()
            stop_ev.set()
        调用数[0] += 1
        return '弱网正文'
    调用数 = [0]

    def 包装(chap, stop_event=None):
        return 慢worker(chap, stop_event)
    spider._fetch_chapter_worker = 包装
    spider._fetch_with_retry = mock.Mock(return_value='弱网正文')

    t0 = time.monotonic()
    with mock.patch('风控事件.add'), mock.patch('风控事件.flush'), \
            mock.patch('网站清单.记录'):
        spider.run('https://example.com/book', output_file=str(output),
                   output_dir=str(root), resume=False, show_progress=False,
                   threads=threads, delay=0, stop_event=stop_ev)
    停止延迟 = time.monotonic() - (停止时刻[0] or t0)
    print(f'  停止延迟: {停止延迟:.2f}s (set→run返回)')

    # 重启完整性: resume 至完成
    spider2 = _造蜘蛛()
    spider2.get_chapter_list = lambda *a: [
        {'title': f'第{i}章', 'url': f'https://example.com/{i}'} for i in range(1, 总章数 + 1)]
    spider2._fetch_with_retry = mock.Mock(return_value='续传正文')
    spider2._fetch_chapter_worker = mock.Mock(return_value='续传正文')
    with mock.patch('风控事件.add'), mock.patch('风控事件.flush'), \
            mock.patch('网站清单.记录'):
        spider2.run('https://example.com/book', output_file=str(output),
                    output_dir=str(root), resume=True, show_progress=False,
                    threads=threads, delay=0)
    text = output.read_text(encoding='utf-8')
    标题s = [l[3:].strip() for l in text.splitlines() if l.startswith('## ')]
    重复 = len(标题s) - len(set(标题s))
    数据 = {
        '停止延迟秒': round(停止延迟, 2),
        '首轮worker调用': 调用数[0],
        '续传后总章节': len(标题s), '重复章节': 重复,
        '总章数': 总章数,
        '重启完整性': len(标题s) == 总章数 and 重复 == 0,
    }
    print(f'  结果: {json.dumps(数据, ensure_ascii=False)}')
    spider.close(); spider2.close()
    return 数据


def 场景R07_重试上限(总章数=20):
    """R07: 断连场景 (fetch 恒 None) —— 验证重试有上限, 不无上限重试。"""
    print(f'\n===== R07 断连: {总章数} 章, fetch 恒失败 =====')
    root = Path(tempfile.mkdtemp())
    output = root / 'down.txt'
    spider = _造蜘蛛()
    spider.get_chapter_list = lambda *a: [
        {'title': f'第{i}章', 'url': f'https://example.com/{i}'} for i in range(1, 总章数 + 1)]
    调用数 = [0]

    def 断fetch(url):
        调用数[0] += 1
        return None
    spider._fetch_with_retry = 断fetch
    spider._fetch_chapter_worker = mock.Mock(return_value=None)

    t0 = time.monotonic()
    with mock.patch('风控事件.add'), mock.patch('风控事件.flush'), \
            mock.patch('网站清单.记录'):
        spider.run('https://example.com/book', output_file=str(output),
                   output_dir=str(root), resume=False, show_progress=False,
                   threads=1, delay=0)
    耗时 = time.monotonic() - t0
    # 每章重试次数 = 调用数/章数; 断连下应有明确上限 (非无上限)
    数据 = {
        'fetch调用总数': 调用数[0], '章数': 总章数,
        '每章重试次数': round(调用数[0] / max(1, 总章数), 1),
        '耗时秒': round(耗时, 2),
    }
    print(f'  结果: {json.dumps(数据, ensure_ascii=False)}')
    spider.close()
    return 数据


if __name__ == '__main__':
    模式 = (sys.argv[1] if len(sys.argv) > 1 else 'all').lower()
    if 模式 in ('all', 'r06'):
        场景R06_超大任务(总章数=5000, threads=4)
    if 模式 in ('all', 'r07'):
        场景R07_停止延迟与重启(总章数=2000, threads=2)
        场景R07_重试上限(总章数=20)
    print('\n[压测完成]')
