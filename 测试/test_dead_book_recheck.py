# -*- coding: utf-8 -*-
"""死书机制 阶段5: 重新检测 回归 (2026-10-03)

阶段5 让用户能对「稍后处理」的书重跑抓取判定, 确认是否恢复。本阶段的核心
风险不在按钮本身, 而在三个**静默失败点**:

  ① **清理挂在 UI 上** —— 若"抓成功后清死书记录"只在死书清单页刷新时做,
     而重检后用户直接切去任务表看进度(不在本页), 记录会一直躺在清单里
     → 用户点完按钮看着记录纹丝不动, 认定功能坏了。故必须在数据层落点。
  ② **无上限批量** —— 每本都要真发一轮请求, "全选就检"会在点一下的瞬间
     对同一站点并发轰击几十次(被封 + 堵死同域闸门)。必须有上限并如实报数。
  ③ **重复发起** —— 对正在运行/收尾中的任务再点检测, 会并发两个线程抓同一
     本书(页面上还恒一行, 用户完全看不见), 抢写同一输出文件。

另: 恢复判定**不能由本页决定** —— 本页发起, 抓取结果才决定是"清记录"还是
"次数+1"; 本页若擅自改状态就是在替抓取结果下结论, 必然错。
"""
import inspect
import re
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / '源码')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _沙箱  # noqa: F401,E402  import 即把状态根钉到临时目录


def _读源码(相对: str) -> str:
    return (_ROOT / '源码' / 相对).read_text(encoding='utf-8')


class Test恢复清理落点(unittest.TestCase):
    """① 抓成功 → 死书记录必须被清, 且必须由**数据层**清(非 UI)"""

    def setUp(self):
        self.tm = _读源码('gui_components/task_manager.py')
        self.死书 = _读源码('死书处理.py')
        self.page = _读源码('gui_components/pages/dead_book_page.py')

    def test_有标记已恢复接口(self):
        self.assertIn('def 标记已恢复', self.死书, '缺 标记已恢复 → 无处落恢复清理')

    def test_数据层调标记已恢复(self):
        """completed 分支必须调它。漏了 = 记录永不清 = 功能看似无效。"""
        块 = self.tm.split('if self._is_task_thread_owner(task) and task.status == "running"')[1][:2000]
        self.assertIn('标记已恢复', 块,
                      '抓成功分支未清死书记录 → 重检成功也不会移出清单')
        self.assertIn('_set_terminal(task, "completed")', 块,
                      '自检锚点丢失(completed 分支结构变了, 请同步更新本测试)')

    def test_清理不因失败中断抓取(self):
        """清理是 bookkeeping, 异常不得冒泡把整轮抓取判失败。"""
        块 = self.tm.split('from 死书处理 import 标记已恢复')[1][:800]
        self.assertIn('except Exception', 块,
                      '清理死书记录未容错 → 一次写盘失败会毁掉已成功的抓取')

    def test_清理同步清任务标记(self):
        """task.dead 也要清, 否则任务表那行仍显示死书态(数据不一致)。"""
        块 = self.tm.split('from 死书处理 import 标记已恢复')[1][:800]
        self.assertIn('task.dead = None', 块, '重检成功后未清 task.dead')

    def test_页面不自己判恢复(self):
        """本页只发起, 不改记录状态 —— 状态由抓取结果决定。"""
        块 = self.page.split('def _重新检测')[1].split('def _批量重检')[0]
        self.assertNotIn('死书处理.设状态', 块,
                         '重新检测不得自行改记录状态(抓成功/仍死由数据层判)')

    def test_已删除记录不被恢复清除(self):
        """已删除是用户已处置的终态账目, 不该被重检悄悄抹掉。"""
        块 = self.死书.split('def 标记已恢复')[1].split('# ------')[0]
        self.assertIn('状态_已删除', 块, '未保护 已删除 态记录')


class Test标记已恢复行为(unittest.TestCase):
    """② 标记已恢复 的真实行为 (落盘级, 非源码断言)"""

    def setUp(self):
        import 死书处理
        self.死书 = 死书处理
        self.url = 'https://样例站点.test/book/1001'

    def _清(self):
        for r in self.死书.载入():
            self.死书.移除记录(r.get('键'))

    def test_待确认被清除(self):
        self._清()
        self.死书.记录死书(self.url, '测试书', self.死书.类型_书已删除, '原因')
        结果 = self.死书.标记已恢复(self.url)
        self.assertTrue(结果['移除'], '待确认记录应被清除')
        self.assertEqual(self.死书.列出(状态=self.死书.状态_待确认), [])

    def test_已忽略也被清除(self):
        """用户点过"忽略"不等于这本书不该被恢复 —— 站点可能真的修好了。"""
        self._清()
        _, 首次 = self.死书.记录死书(self.url, '测试书',
                                  self.死书.类型_书已删除, '原因')
        键 = self.死书._键(self.url)
        self.死书.设状态(键, self.死书.状态_已忽略)
        结果 = self.死书.标记已恢复(self.url)
        self.assertTrue(结果['移除'], '已忽略记录也应被清除')
        self.assertEqual(self.死书.列出(状态=self.死书.状态_已忽略), [])

    def test_已删除不被清除(self):
        self._清()
        self.死书.记录死书(self.url, '测试书', self.死书.类型_书已删除, '原因')
        键 = self.死书._键(self.url)
        self.死书.设状态(键, self.死书.状态_已删除)
        结果 = self.死书.标记已恢复(self.url)
        self.assertFalse(结果['移除'], '已删除是终态账目, 不应被恢复流程抹掉')
        self.assertEqual(len(self.死书.列出(状态=self.死书.状态_已删除)), 1)

    def test_无记录不报错(self):
        """幂等: 成功路径上没有死书记录是常态(比如普通的新书抓取成功),
        不能因此抛异常。"""
        self._清()
        结果 = self.死书.标记已恢复('https://从未抓过.test/book/9999')
        self.assertFalse(结果['移除'])
        self.assertEqual(结果['键'], '')

    def test_空网址不炸(self):
        self.assertFalse(self.死书.标记已恢复('')['移除'])
        self.assertFalse(self.死书.标记已恢复(None)['移除'])

    def test_不影响其他记录(self):
        self._清()
        self.死书.记录死书('https://甲.test/b/1', '甲书',
                        self.死书.类型_书已删除, '原因')
        self.死书.记录死书('https://乙.test/b/2', '乙书',
                        self.死书.类型_站点不可达, '原因')
        self.死书.标记已恢复('https://甲.test/b/1')
        剩余 = self.死书.列出()
        self.assertEqual(len(剩余), 1)
        self.assertEqual(剩余[0].get('网址'), 'https://乙.test/b/2')

    def test_网址归一化后仍能匹配(self):
        """判定与清理都必须走同一套 _键 归一化, 否则尾斜杠差异会漏匹配。"""
        self._清()
        self.死书.记录死书('https://丙.test/b/3/', '丙书',
                        self.死书.类型_书已删除, '原因')
        结果 = self.死书.标记已恢复('https://丙.test/b/3')
        self.assertTrue(结果['移除'], '归一化后仍须能匹配上记录')


class Test重新检测UI(unittest.TestCase):
    """③ 页面上的重新检测动作"""

    def setUp(self):
        self.src = _读源码('gui_components/pages/dead_book_page.py')

    def test_两态都有重新检测(self):
        块 = self.src.split('def _行内动作')[1].split('def ')[0]
        self.assertIn('重新检测', 块, '行内无重新检测按钮')
        # 已删除态不得给检测按钮(已结项, 检测无意义)
        self.assertIn("if 状态 != '已删除'", 块,
                      '重新检测未排除已删除态')

    def test_有批量入口(self):
        self.assertIn('重检当前筛选', self.src, '缺批量重检入口')
        self.assertIn('def _批量重检', self.src)

    def test_批量有上限(self):
        self.assertIn('_批量上限', self.src, '批量重检无上限 → 一次轰击全站')
        块 = self.src.split('def _批量重检')[1].split('def _设状态')[0]
        self.assertIn('_批量上限]', 块, '批量未按上限截断')
        self.assertIn('条未发起', 块, '超限未如实报数 → 用户以为全都检了')

    def test_批量跳过已删除(self):
        """用白名单 ('待确认','已忽略') 排除已删除 —— 断言这个白名单本身,
        而不是断言源码里出现 '已删除' 字面量(那样会奖励"逐个 if 排除"的写法,
        漏一个新状态就静默把已结项送去重检)。"""
        块 = self.src.split('def _批量重检')[1].split('def _设状态')[0]
        白名单 = re.search(r"in \(([^)]*)\)\]", 块)
        self.assertTrue(白名单, '批量未用状态白名单筛出待检记录')
        self.assertIn("'待确认'", 白名单.group(1))
        self.assertIn("'已忽略'", 白名单.group(1))
        self.assertNotIn("'已删除'", 白名单.group(1),
                         '已删除是终态账目, 不得送去重检')

    def test_重新检测不进轮询(self):
        """最高优先级的性能红线: 检测要真发请求, 绝不能挂在 2s 轮询里。"""
        块 = self.src.split('def refresh')[1].split('def _行(')[0]
        self.assertNotIn('_重新检测', 块,
                         '重新检测被挂进 refresh/轮询 → 定时烧流量且可能并发轰站')

    def test_跳过运行中任务(self):
        块 = self.src.split('def _重新检测')[1].split('def _批量重检')[0]
        self.assertIn('running', 块, '未跳过运行中任务 → 会并发两线程抓同一本书')
        self.assertIn('is_alive', 块, '未检查线程存活 → 收尾中的任务会被重复发起')

    def test_复用restart不新建(self):
        """有对应任务行时复用 restart_task(保持"一个 URL 恒一行"约定)。"""
        块 = self.src.split('def _重新检测')[1].split('def _批量重检')[0]
        self.assertIn('find_task_by_url', 块, '未查找对应任务')
        self.assertIn('restart_task', 块, '有旧任务时应原任务内重启')
        self.assertIn('create_task', 块, '无对应任务时应新建任务')

    def test_新建时关续传(self):
        """死书从没抓到章节, 续传无意义且可能撞上残留半成品文件。"""
        块 = self.src.split('def _重新检测')[1].split('def _批量重检')[0]
        self.assertIn('resume=False', 块, '新建重检任务未关续传')

    def test_无manager诚实报失败(self):
        块 = self.src.split('def _重新检测')[1].split('def _批量重检')[0]
        self.assertIn('task_manager is None', 块,
                      '未接入任务管理器时未诚实报失败')
        self.assertIn('⚠️', 块, '失败提示须有明确标记')

    def test_提示说明后续归属(self):
        """须告诉用户"抓成功会自动移出、仍失败则次数+1", 否则不知去哪儿看。"""
        块 = self.src.split('def _重新检测')[1].split('def _批量重检')[0]
        self.assertIn('次数', 块, '未说明失败后次数会累加')
        self.assertIn('移出清单', 块, '未说明成功后自动移出清单')

    def test_异常不外抛(self):
        """on_click 里抛异常会静默吞掉点击(用户以为按钮坏了)。"""
        块 = self.src.split('def _重新检测')[1].split('def _批量重检')[0]
        self.assertIn('except Exception', 块, '_重新检测 未容错 → 点击静默失败')
        批量 = self.src.split('def _批量重检')[1].split('def _设状态')[0]
        self.assertIn('except Exception', 批量,
                      '批量单项失败未逐项容错 → 一本失败拖垮整批')

    def test_参数名用关键字(self):
        """create_task 关键字传参: 位置参数一旦签名调序就静默串位。"""
        块 = self.src.split('def _重新检测')[1].split('def _批量重检')[0]
        self.assertIn("mode='full'", 块, 'create_task 应用关键字传参')


class Test签名稳定性(unittest.TestCase):
    """④ 冒烟: 方法签名没写错 (冒烟前先静态自查, 少跑一轮)"""

    def test_方法签名存在(self):
        from gui_components.pages.dead_book_page import DeadBookPage
        for 名 in ('_重新检测', '_批量重检'):
            self.assertTrue(callable(getattr(DeadBookPage, 名, None)),
                            f'缺 {名} 方法')
        参数 = inspect.signature(DeadBookPage._重新检测).parameters
        self.assertIn('网址', 参数, '_重新检测 未接网址参数')

    def test_批量上限是正整数(self):
        from gui_components.pages import dead_book_page as m
        self.assertIsInstance(m._批量上限, int)
        self.assertGreater(m._批量上限, 0, '批量上限必须为正, 否则批量功能形同虚设')
        self.assertLessEqual(m._批量上限, 50, '上限过大失去保护意义')


if __name__ == '__main__':
    unittest.main(verbosity=2)
