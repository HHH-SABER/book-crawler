# -*- coding: utf-8 -*-
"""U19 · 结构化任务事件通道测试。

背景: GUI 的运行时数据原先只靠"爬虫 print 中文日志 → TaskManager 正则解析回填",
日志文案即隐式数据协议。U19 增加显式事件通道 (事件优先、正则兜底, 并行不替换)。

本文件守住三条性质:
  1. **双通道等价** —— 同一语义的"日志行"与"事件"必须把任务状态改成一模一样
     (否则两条通道会漂移, 界面行为取决于走了哪条路);
  2. **通道自身健壮** —— 无订阅方零成本、订阅方异常不外溢、按线程隔离、可退订;
  3. **不破坏原有契约** —— 正则路径行为不变 (由 test_log_contract.py 继续守)。

运行方式 (项目根目录):
    python -m unittest discover -s 测试 -v
"""
import inspect
import sys
import threading
import unittest
from pathlib import Path

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))
sys.path.insert(0, str(_根 / '源码' / 'gui_components'))

import task_manager as tm            # noqa: E402
import 任务事件                        # noqa: E402


def _新任务():
    return tm.TaskInfo(task_id='t1', url='https://example.com/book/1')


def _快照(task):
    m = task.metrics
    return {
        'progress_current': task.progress_current,
        'progress_total': task.progress_total,
        'output_file': task.output_file,
        'engine': m.engine,
        'engine_fallback_chain': list(m.engine_fallback_chain),
        'anti_spider_type': m.anti_spider_type,
        'quality_score': m.quality_score,
        'quality_passed': m.quality_passed,
        'incremental_skipped': m.incremental_skipped,
    }


def _重定向器(task):
    """只用于驱动解析逻辑; original_stdout 传 None (本用例不落文件日志)"""
    return tm.TaskLogRedirector(task, None)


# (说明, 日志行, 事件类型, 事件字段)
_等价对 = [
    ('标题', '提取到小说名称: 宿命之环',
     '标题', {'标题': '宿命之环'}),
    ('进度', '=== 正在抓取第 7/20 章: 第七章 ===',
     '进度', {'当前': 7, '总数': 20}),
    ('进度(进度条格式)', '  7/20 (35%)',
     '进度', {'当前': 7, '总数': 20}),
    ('章节总数', '共找到 20 个章节（已去重并排序）',
     '章节总数', {'总数': 20}),
    ('输出文件', r'抓取完成，共20章，已保存至 D:\out\书.txt',
     '输出文件', {'路径': r'D:\out\书.txt'}),
    ('增量跳过', '[增量] 跳过第 3/20 章 (未变化): 第三章',
     '增量跳过', {}),
    ('引擎成功', '[反爬] ✅ cloudscraper 引擎请求成功 (状态 200), 交由反爬层校验',
     '引擎成功', {'引擎': 'cloudscraper'}),
    ('引擎失败', '[反爬] ⚠️ cloudscraper 引擎请求失败 (状态 403), 保留原响应走现有流程',
     '引擎失败', {'引擎': 'cloudscraper'}),
    ('引擎异常', '[引擎] curl_cffi 请求异常: timeout',
     '引擎失败', {'引擎': 'curl_cffi'}),
    ('反爬-命中机制', '[反爬] 命中 js_cookie, 尝试成熟反爬库引擎重发...',
     '反爬', {'机制': 'js_cookie'}),
    ('反爬-频率限制', '[反爬] 频率限制, 退避 5 秒后重试 (第1次连续限频)',
     '反爬', {'机制': 'rate_limit'}),
    ('反爬-WAF图片', '[反爬检测] 命中 WAF 图片验证码页 (1234字节)，尝试自动解决...',
     '反爬', {'机制': 'waf_captcha'}),
    ('反爬-JS挑战', '[反爬检测] 命中 WAF JS 挑战页, 用浏览器渲染获取令牌 cookie...',
     '反爬', {'机制': 'waf_js_challenge'}),
    ('反爬-JS cookie', '[反爬检测] 检测到JS cookie校验页面(500字符)，等待reload后重试...',
     '反爬', {'机制': 'js_cookie'}),
    ('质检-通过', '[质检] 第一章 得分92 通过',
     '质检', {'得分': 92, '通过': True}),
    ('质检-失败', '[质检] 第一章 得分43 失败(乱码率80%>30%)',
     '质检', {'得分': 43, '通过': False}),
]


class Test双通道等价(unittest.TestCase):
    """核心回归: 同一语义下, 正则路径与事件路径必须产出相同状态"""

    def test_每条语义两条通道结果一致(self):
        for 说明, 日志行, 类型, 字段 in _等价对:
            with self.subTest(说明=说明):
                # 正则路径
                t1 = _新任务()
                _重定向器(t1)._parse_progress(日志行)
                # 事件路径
                t2 = _新任务()
                _重定向器(t2).处理任务事件(类型, 字段)
                self.assertEqual(_快照(t1), _快照(t2),
                                 f'[{说明}] 两条通道结果不一致')

    def test_重复事件与重复日志行为一致(self):
        """引擎失败/增量跳过是"追加/累加"语义, 重复输入也必须同结果"""
        for 说明, 日志行, 类型, 字段 in _等价对:
            if 类型 not in ('引擎失败', '增量跳过'):
                continue
            with self.subTest(说明=说明):
                t1 = _新任务()
                t2 = _新任务()
                r1, r2 = _重定向器(t1), _重定向器(t2)
                for _ in range(3):
                    r1._parse_progress(日志行)
                    r2.处理任务事件(类型, 字段)
                self.assertEqual(_快照(t1), _快照(t2))

    def test_进度事件不因总数缺失而清空总数(self):
        t = _新任务()
        r = _重定向器(t)
        r.处理任务事件('进度', {'当前': 5, '总数': 20})
        r.处理任务事件('进度', {'当前': 6})
        self.assertEqual(t.progress_total, 20)
        self.assertEqual(t.progress_current, 6)

    def test_质检得分非法时保持原值不抛异常(self):
        t = _新任务()
        r = _重定向器(t)
        r.处理任务事件('质检', {'得分': 88, '通过': True})
        r.处理任务事件('质检', {'得分': None, '通过': False})
        self.assertEqual(t.metrics.quality_score, 88)


class Test通道自身健壮(unittest.TestCase):

    def tearDown(self):
        任务事件.退订()

    def test_无订阅方时发布不报错(self):
        任务事件.退订()
        self.assertFalse(任务事件.有订阅方())
        任务事件.发布('进度', 当前=1, 总数=2)      # 不应抛异常

    def test_订阅后能收到事件(self):
        收到 = []

        class 收:
            def 处理任务事件(self, 类型, 数据):
                收到.append((类型, 数据))

        任务事件.订阅(收())
        任务事件.发布('进度', 当前=3, 总数=9)
        self.assertEqual(收到, [('进度', {'当前': 3, '总数': 9})])

    def test_重复订阅同一对象只收一次(self):
        class 收:
            def __init__(self):
                self.次数 = 0

            def 处理任务事件(self, 类型, 数据):
                self.次数 += 1

        o = 收()
        任务事件.订阅(o)
        任务事件.订阅(o)
        任务事件.发布('增量跳过')
        self.assertEqual(o.次数, 1)

    def test_订阅方异常不影响发布方与其他订阅方(self):
        正常收到 = []

        class 坏:
            def 处理任务事件(self, 类型, 数据):
                raise RuntimeError('模拟订阅方炸了')

        class 好:
            def 处理任务事件(self, 类型, 数据):
                正常收到.append(类型)

        任务事件.订阅(坏())
        任务事件.订阅(好())
        任务事件.发布('增量跳过')          # 不应把异常抛给调用方
        self.assertEqual(正常收到, ['增量跳过'], '坏订阅方不得阻断好订阅方')

    def test_退订后不再收到(self):
        收到 = []

        class 收:
            def 处理任务事件(self, 类型, 数据):
                收到.append(类型)

        o = 收()
        任务事件.订阅(o)
        任务事件.退订(o)
        任务事件.发布('增量跳过')
        self.assertEqual(收到, [])

    def test_按线程隔离(self):
        """A 线程订阅, B 线程发布 → A 不应收到 (多任务并发不串台)"""
        主线程收到 = []
        子线程结果 = []

        class 收:
            def 处理任务事件(self, 类型, 数据):
                主线程收到.append(类型)

        任务事件.订阅(收())

        def 子():
            子线程结果.append(任务事件.有订阅方())
            任务事件.发布('增量跳过')      # 子线程无订阅方 → 不应送到主线程

        t = threading.Thread(target=子)
        t.start()
        t.join(timeout=10)
        self.assertEqual(子线程结果, [False], '子线程不应继承主线程的订阅方')
        self.assertEqual(主线程收到, [], '主线程不应收到子线程发布的事件')

    def test_退订全部(self):
        class 收:
            def 处理任务事件(self, 类型, 数据):
                pass

        任务事件.订阅(收())
        self.assertTrue(任务事件.有订阅方())
        任务事件.退订()
        self.assertFalse(任务事件.有订阅方())


class Test接线存在(unittest.TestCase):
    """防止"模块加好了但没人用"——接线断了这里会红"""

    def test_重定向器实现了事件接收接口(self):
        self.assertTrue(callable(getattr(_重定向器(_新任务()), '处理任务事件', None)))

    def test_任务管理器在运行任务时订阅事件(self):
        源码 = inspect.getsource(tm.TaskManager._run_task)
        self.assertIn('任务事件.订阅', 源码, '_run_task 未订阅事件通道')
        self.assertIn('任务事件.退订', 源码, '_run_task 未退订事件通道 (线程复用会串台)')

    def test_爬虫在关键节点发布事件(self):
        """抽查爬虫侧确实发出了事件 (防发出点被误删)"""
        import 爬虫
        源码 = inspect.getsource(爬虫)
        for 类型 in ('进度', '章节总数', '输出文件', '增量跳过', '完成',
                     '引擎成功', '引擎失败', '反爬', '质检', '标题'):
            self.assertIn(f"发布('{类型}'", 源码, f'爬虫未发布 {类型} 事件')


class Test事件覆盖契约(unittest.TestCase):
    """U19 第二阶段准备: 逐条核对日志契约的"事件覆盖"状态。

    摘除正则路径的前提是"每条契约都有事件覆盖"。本表把该判断显式化 ——
    **新增一条契约却忘了决定它的事件覆盖, `test_覆盖表与契约测试同步` 会红**。
    """

    # (契约用例名, 是否有事件通道, 说明)
    覆盖表 = {
        'test_novel_title': (True, "事件 '标题' (爬虫在确认书名后发布)"),
        'test_chapter_progress': (True, "事件 '进度'"),
        'test_progress_bar_format': (True, "同 '进度' —— 解析的是同一对字段; "
                                          "进度条本身由 print_progress_bar 打印, 无需单独事件"),
        'test_total_found': (True, "事件 '章节总数' 发布在 get_chapter_list 的公共出口, "
                                  "覆盖全部站点分支 (各站 '[站点] 共提取 N 个章节' 只是中间日志)"),
        'test_saved_to_and_completed': (True, "事件 '输出文件'; completed 终态由 "
                                             "_set_terminal 直接置位, 不经文案"),
        'test_stopped_wont_mark_completed': (False, "与事件无关: 停止语义由 stop_task "
                                                   "的状态白名单保证 (U5)"),
        'test_engine_success': (True, "事件 '引擎成功'"),
        'test_engine_fallback_chain': (True, "事件 '引擎失败'"),
        'test_anti_spider_types': (True, "事件 '反爬' —— 5 种机制值均有发出点"),
        'test_quality_score': (True, "事件 '质检'"),
        'test_incremental_skip_counts_per_line': (True, "事件 '增量跳过' 逐次累加 "
                                                       "(不发送汇总行, 与契约的按行计数一致)"),
    }

    def test_覆盖表与契约测试同步(self):
        """契约测试新增/改名内容必须在本表里表态, 否则这里失败"""
        契约文件 = _根 / '测试' / 'test_log_contract.py'
        文本 = 契约文件.read_text(encoding='utf-8')
        import re
        用例 = set(re.findall(r'def (test_\w+)\(self\)', 文本))
        契约用例 = {n for n in 用例
                    if n.startswith(('test_novel', 'test_chapter', 'test_progress',
                                     'test_total', 'test_saved', 'test_stopped',
                                     'test_engine', 'test_anti', 'test_quality',
                                     'test_incremental'))}
        未表态 = 契约用例 - set(self.覆盖表)
        多余 = set(self.覆盖表) - 契约用例
        self.assertEqual(未表态, set(),
                         f'这些契约用例没有表态事件覆盖: {sorted(未表态)}')
        self.assertEqual(多余, set(),
                         f'覆盖表里有已不存在的契约用例: {sorted(多余)}')

    def test_反爬机制值都有发出点(self):
        """契约里的 5 种机制值, 爬虫侧必须真的发得出来"""
        import 爬虫
        源码 = inspect.getsource(爬虫)
        for 值 in ('rate_limit', 'waf_captcha', 'waf_js_challenge', 'js_cookie'):
            self.assertIn(f"发布('反爬', 机制='{值}'", 源码,
                          f'爬虫未发布 {值} 机制事件')
        # 'dynamic_token' 等由 结果.机制 变量透传, 无法字面匹配 → 断言变量形式存在
        self.assertIn("发布('反爬', 机制=结果.机制)", 源码,
                      '爬虫未发布"按识别结果"透传的反爬机制事件')

    def test_标题事件有发出点(self):
        import 爬虫
        self.assertIn("发布('标题'", inspect.getsource(爬虫))


class Test覆盖率诊断(unittest.TestCase):
    """U19 第二阶段决策依据: 统计"事件生效"与"正则仍在改写状态"的次数"""

    def test_只用事件时摘要报覆盖完整(self):
        t = _新任务()
        r = _重定向器(t)
        r.启用正则兜底 = True            # 本用例测的是"开启时"的诊断口径
        r.处理任务事件('进度', {'当前': 5, '总数': 10})
        self.assertEqual(r.正则兜底数, 0)
        self.assertGreaterEqual(r.事件应用数, 1)
        self.assertIn('覆盖完整', r.覆盖率摘要())

    def test_停用时不把构造出的0当作可删证据(self):
        """自查发现的漏洞: 开关关掉后计数恒为 0, 不能据此宣称'覆盖完整可删正则'"""
        t = _新任务()
        r = _重定向器(t)                  # 默认停用
        r.处理任务事件('进度', {'当前': 5, '总数': 10})
        self.assertEqual(r.正则兜底数, 0)
        摘要 = r.覆盖率摘要()
        self.assertIn('已停用', 摘要)
        self.assertNotIn('具备删除正则的条件', 摘要,
                         '停用时不得输出"可删"结论 (自证式误读)')

    def test_正则改动状态会被计数并记录字段(self):
        t = _新任务()
        r = _重定向器(t)
        r.启用正则兜底 = True          # U19 后默认停用, 本用例显式打开
        r.write('=== 正在抓取第 2/10 章: 第二章 ===\n')
        self.assertEqual(r.正则兜底数, 1)
        self.assertIn('progress_current', r.正则兜底字段)
        self.assertIn('progress_total', r.正则兜底字段)
        self.assertIn('正则仍在改写状态', r.覆盖率摘要())

    def test_事件与正则值相同时不重复计数(self):
        """事件先填好状态后, 随后的同值日志行不应被计为"正则改动了状态" """
        t = _新任务()
        r = _重定向器(t)
        r.启用正则兜底 = True
        r.处理任务事件('进度', {'当前': 7, '总数': 20})
        基线 = r.正则兜底数
        r.write('=== 正在抓取第 7/20 章: 第七章 ===\n')   # 同值, 状态未变
        self.assertEqual(r.正则兜底数, 基线, '同值日志行不应被计为兜底')
        self.assertGreaterEqual(r.事件应用数, 1)

    def test_摘要口径说明已写清上界语义(self):
        """防止后人误把 ">0" 直接读成"该字段缺事件" (指标是上界)"""
        doc = (tm.TaskLogRedirector.覆盖率摘要.__doc__ or '').replace(' ', '')
        self.assertIn('上界', doc)
        self.assertIn('==0', doc)


class Test正则停用(unittest.TestCase):
    """U19 第二阶段: 正则兜底默认停用 —— 日志文案从此不再是数据协议。

    依据: ①离线端到端(停用正则后事件仍正确驱动状态);
          ②真实运行差分(322zw.com 51 章, 停用后终态与开启时完全一致)。
    置 True 可一行回退, 故正则代码与 test_log_contract.py 都保留着。
    """

    def test_默认停用(self):
        self.assertIs(tm.TaskLogRedirector.启用正则兜底, False,
                      '正则兜底应默认停用 (U19 第二阶段)')

    def test_停用时日志行不再改动状态(self):
        """核心: 停用后, 契约日志行走 write() 也不得影响任务状态"""
        t = _新任务()
        r = _重定向器(t)
        r.write('=== 正在抓取第 2/10 章: 第二章 ===\n')
        r.write('共找到 10 个章节\n')
        r.write('抓取完成，共10章，已保存至D:\\out\\书.txt\n')
        self.assertEqual(t.progress_current, 0)
        self.assertEqual(t.progress_total, 0)
        self.assertEqual(t.output_file, '')
        self.assertNotEqual(t.status, 'completed')
        self.assertEqual(r.正则兜底数, 0)

    def test_停用时事件仍能驱动同一批字段(self):
        t = _新任务()
        r = _重定向器(t)
        r.处理任务事件('进度', {'当前': 2, '总数': 10})
        r.处理任务事件('输出文件', {'路径': r'D:\out\书.txt'})
        r.处理任务事件('完成', {'章节数': 10})
        self.assertEqual(t.progress_current, 10)
        self.assertEqual(t.progress_total, 10)
        self.assertEqual(t.output_file, r'D:\out\书.txt')
        self.assertEqual(t.status, 'completed')

    def test_完成事件与正则完成终态等价(self):
        """两条通道的"完成"语义必须一致 (都走 _应用完成终态)"""
        t1 = _新任务()
        t1.progress_total = 7
        r1 = _重定向器(t1)
        r1.启用正则兜底 = True
        r1.write('抓取完成，共7章\n')

        t2 = _新任务()
        t2.progress_total = 7
        r2 = _重定向器(t2)
        r2.处理任务事件('完成', {'章节数': 7})

        self.assertEqual(_快照(t1), _快照(t2), '完成语义两条通道不一致')
        self.assertEqual(t1.status, 'completed')
        self.assertEqual(t2.status, 'completed')

    def test_启用开关可回退(self):
        """回退路径: 置 True 后正则立刻恢复工作"""
        t = _新任务()
        r = _重定向器(t)
        r.启用正则兜底 = True
        r.write('=== 正在抓取第 3/10 章: 第三章 ===\n')
        self.assertEqual(t.progress_current, 3)


if __name__ == '__main__':
    unittest.main(verbosity=2)
