# -*- coding: utf-8 -*-
"""任务指标解析单测: TaskLogRedirector._parse_metrics 各分支"""
import sys, os
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '源码', 'gui_components'))
import task_manager as tm


def new_task():
    return tm.TaskInfo(task_id='t1', url='https://example.com/book/1')


def feed(task, lines):
    rd = tm.TaskLogRedirector(task, Path(os.devnull).open('w'))  # 防路径穿越
    for ln in lines:
        rd._parse_metrics(ln)
    rd.original.close()


def test_engine_success():
    t = new_task()
    feed(t, ['[反爬] ✅ curl_cffi 引擎请求成功 (耗时1.2s)'])
    assert t.metrics.engine == 'curl_cffi', t.metrics.engine


def test_engine_fallback_chain():
    t = new_task()
    feed(t, [
        '[引擎] requests 请求异常: 超时',
        '[反爬] ⚠️ cloudscraper 引擎请求失败 (403)',
        '[引擎] requests 请求异常: 超时',  # 重复, 不应重复记录
        '[反爬] ✅ curl_cffi 引擎请求成功',
    ])
    assert t.metrics.engine_fallback_chain == ['requests', 'cloudscraper'], \
        t.metrics.engine_fallback_chain
    assert t.metrics.engine == 'curl_cffi'


def test_anti_spider_types():
    t = new_task()
    feed(t, [
        '[反爬] 频率限制, 退避 30 秒后重试 (第1次)',
        '[反爬] 命中 rate_limit, 尝试成熟反爬库引擎重发...',
        '[反爬检测] 命中 WAF JS 挑战页, 用浏览器渲染获取令牌 cookie...',
    ])
    assert t.metrics.anti_spider_type == 'waf_js_challenge', t.metrics.anti_spider_type
    t2 = new_task()
    feed(t2, ['[反爬检测] 命中 WAF 图片验证码页 (3000字节)，尝试自动解决...'])
    assert t2.metrics.anti_spider_type == 'waf_captcha'
    t3 = new_task()
    feed(t3, ['[反爬检测] 第1次请求命中JS cookie校验页面(5000字节)，提取cookie后重试...'])
    assert t3.metrics.anti_spider_type == 'js_cookie'


def test_quality_score():
    t = new_task()
    feed(t, ['[质检] 第3章 得分92 通过'])
    assert t.metrics.quality_score == 92.0
    assert t.metrics.quality_passed is True
    feed(t, ['[质检] 第4章 得分45 失败(乱码率过高)'])
    assert t.metrics.quality_score == 45.0
    assert t.metrics.quality_passed is False
    # 不匹配行不更新
    feed(t, ['[质检] 抓取异常: 超时'])
    assert t.metrics.quality_score == 45.0


def test_incremental_skip():
    t = new_task()
    feed(t, [
        '[增量] 跳过第 1/100 章 (未变化): 第一章',
        '[增量] 跳过第 2/100 章 (未变化): 第二章',
        '正在抓取第 3/100 章',
    ])
    assert t.metrics.incremental_skipped == 2


def test_task_manager_select():
    mgr = tm.TaskManager(page=None)
    mgr.tasks['a'] = new_task(); mgr.tasks['a'].task_id = 'a'
    mgr.tasks['b'] = new_task(); mgr.tasks['b'].task_id = 'b'
    seen = []
    mgr.on_selected_change(lambda tid: seen.append(tid))
    mgr.select_task('a')
    assert seen == ['a']
    assert mgr.tasks['a'].selected and not mgr.tasks['b'].selected
    mgr.select_task('a')          # 重复选择不触发
    assert seen == ['a']
    mgr.select_task('b')
    assert seen == ['a', 'b']
    assert mgr.selected_task_id == 'b'


def test_update_metrics():
    mgr = tm.TaskManager(page=None)
    t = new_task(); mgr.tasks['t1'] = t
    mgr.update_metrics('t1', engine='cloudscraper', quality_score=88.0)
    assert t.metrics.engine == 'cloudscraper' and t.metrics.quality_score == 88.0
    mgr.update_metrics('t1', 不存在字段='x')  # 静默忽略
    mgr.update_metrics('nope', engine='x')     # 不存在的任务, 静默


if __name__ == '__main__':
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print(f'  PASS {name}')
            except AssertionError as e:
                fails += 1
                print(f'  FAIL {name}: {e}')
    print('全部通过' if fails == 0 else f'{fails} 项失败')
    sys.exit(0 if fails == 0 else 1)
