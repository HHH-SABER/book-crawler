# -*- coding: utf-8 -*-
"""死书机制 阶段3: 行内按钮 + 弹窗分流 回归 (2026-10-03)

阶段2 把 dead_pending 贯通到显示层, 阶段3 让用户真正能处置它:
  行内: 死书行的 EPUB 按钮 (必然恒 disabled 的死重) 换成 忽略/删记录
  弹窗: 由记录里的 可询问删除 单字段决定 modal 询问 还是 仅 SnackBar 提示

本文件重点锁三条**契约**(都是"看起来对、实际错"的类型):
  ① 弹窗分流必须由 可询问删除 决定, UI 不得自己判类型
  ② 删除编排必须传 task_manager (无参 TaskManager() 必 TypeError)
  ③ EXE 弹窗文字必须显式 color (v2.4.19 G-H1 教训, 缺色=不可见)
"""
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


class _假页:
    """最小 Page 替身: 记录弹窗调用, 供分流断言。"""

    def __init__(self):
        self.弹出的 = []
        self.update次数 = 0

    def show_dialog(self, ctrl):
        self.弹出的.append(ctrl)

    def update(self):
        self.update次数 += 1


class _假管理器:
    def __init__(self, task):
        self._t = task
        self.删除调用 = []

    def get_task(self, task_id):
        return self._t

    def delete_task(self, task_id, delete_file=False):
        self.删除调用.append((task_id, delete_file))
        return True

    def refresh(self):
        pass


def _造任务(死=None, 状态='dead_pending', 标题='测试书'):
    from gui_components.task_manager import TaskInfo
    t = TaskInfo(task_id='t_dead_1', url='https://example.com/book/9', title=标题)
    t.status = 状态
    t.dead = 死
    return t


class Test删除编排契约(unittest.TestCase):
    """① 删除书记录 必须传 task_manager。

    TaskManager.__init__(self, page) 需要 page, 无参构造必 TypeError
    ("missing 1 required positional argument: 'page'") —— 这是阶段3 实测
    发现的既有地雷: 原实现在 task_manager=None 时去构造一个"临时"管理器,
    必然抛错且被逐项 try 吞成 (False, 说明), 用户看到"删除失败"却查不出原因。
    """

    def test_无管理器时诚实失败而非伪构造(self):
        import 死书处理
        结果 = 死书处理.删除书记录(
            'https://example.com/book/9', 任务id='t_dead_1', task_manager=None)
        成功, 说明 = 结果['任务']
        self.assertFalse(成功, '无管理器却报成功 = 伪成功 (任务行实际删不掉)')
        self.assertTrue(说明, '失败必须带原因, 否则用户无从排查')
        self.assertNotIn('TaskManager()', (说明 or ''),
                         '不应再无参构造 TaskManager (必 TypeError)')

    def test_传管理器时删除且恒不删产物(self):
        import 死书处理
        t = _造任务()
        mgr = _假管理器(t)
        结果 = 死书处理.删除书记录(
            'https://example.com/book/9', 任务id='t_dead_1', task_manager=mgr)
        self.assertTrue(结果['任务'][0], '传了管理器仍应失败 = 传参没生效')
        self.assertEqual(mgr.删除调用, [('t_dead_1', False)],
                         'delete_file 必须恒为 False: 已抓产物绝不可删')

    def test_逐项不回滚且如实报告(self):
        """部分成功必须如实呈现, 不能伪"已删除"。"""
        import 死书处理
        t = _造任务()
        mgr = _假管理器(t)
        原移除 = None
        import 书架
        原移除 = 书架.移除
        try:
            # 模拟书架无该书 (返回 False) → 任务成功/书架失败/网站清单或也失败
            书架.移除 = lambda url: False
            结果 = 死书处理.删除书记录(
                'https://example.com/book/9', 任务id='t_dead_1', task_manager=mgr)
        finally:
            书架.移除 = 原移除
        self.assertFalse(结果['全部成功'],
                         '书架失败时全部成功应为 False, 否则 UI 会伪报已删除')
        self.assertFalse(结果['书架'][0])
        self.assertTrue(结果['任务'][0], '任务项应独立成功(逐项不回滚)')


class Test行内按钮(unittest.TestCase):
    """② 死书行的操作按钮: EPUB(死重) → 忽略; 删除 → 死书编排。"""

    def setUp(self):
        from gui_components.task_table import TaskTable
        self.table = TaskTable(_假管理器(_造任务()))
        self.table.page = _假页()

    def test_死书信息类型防御(self):
        """Mock 陷阱: getattr 返回 Mock 是 truthy, 直接当 dict 读会炸。"""
        from gui_components.task_table import TaskTable

        class _假任务:
            class dead:      # 非 dict, 且 bool 为真
                pass
            status = 'failed'
            task_id = 'x'
        self.assertEqual(TaskTable._死书信息(_假任务()), {},
                         '非 dict 的 dead 必须退化为空 dict, 不能当死书')

    def test_忽略清标记且不动其他数据(self):
        t = self.table.task_manager.get_task('t_dead_1')
        t.dead = {'键': 'k1', '类型': '书已删除或不可读', '可询问删除': True}
        import 死书处理
        原设状态 = 死书处理.设状态
        记录 = []
        try:
            死书处理.设状态 = lambda 键, 状态: (记录.append((键, 状态)), True)[1]
            self.table._on_ignore_dead('t_dead_1')
        finally:
            死书处理.设状态 = 原设状态
        self.assertEqual(记录, [('k1', 死书处理.状态_已忽略)],
                         '忽略必须按清单键置 已忽略')
        self.assertIsNone(t.dead, '忽略后必须清 dead 标记, 否则行内按钮不切回 EPUB')

    def test_忽略无键时不动手(self):
        t = self.table.task_manager.get_task('t_dead_1')
        t.dead = {'类型': '书已删除或不可读'}      # 无 键
        import 死书处理
        原设状态 = 死书处理.设状态
        记录 = []
        try:
            死书处理.设状态 = lambda 键, 状态: (记录.append(键), True)[1]
            self.table._on_ignore_dead('t_dead_1')
        finally:
            死书处理.设状态 = 原设状态
        self.assertEqual(记录, [], '无清单键时不得调用设状态 (不能改错记录)')

    def test_死书删除走编排且如实提示部分失败(self):
        t = self.table.task_manager.get_task('t_dead_1')
        t.dead = {'键': 'k1', '类型': '书已删除或不可读', '可询问删除': True}
        self.table.task_manager = _假管理器(t)
        import 死书处理
        原删除 = 死书处理.删除书记录
        原设状态 = 死书处理.设状态
        收到 = {}

        def _假删除(网址, 任务id='', 范围=None, task_manager=None):
            收到['网址'] = 网址
            收到['任务id'] = 任务id
            收到['task_manager'] = task_manager
            return {'任务': (True, ''), '书架': (False, '书架中无该书记录'),
                    '网站清单': (False, '网站清单中无该网址'), '全部成功': False}
        try:
            死书处理.删除书记录 = _假删除
            死书处理.设状态 = lambda *a, **k: True
            self.table._do_delete_dead('t_dead_1')
        finally:
            死书处理.删除书记录 = 原删除
            死书处理.设状态 = 原设状态
        # 编排函数必须拿到真实 task_manager —— 无参 TaskManager() 必 TypeError
        self.assertIs(收到.get('task_manager'), self.table.task_manager,
                      '未把 task_manager 传给 删除书记录 (无参构造必 TypeError)')
        self.assertEqual(收到.get('任务id'), 't_dead_1')
        self.assertEqual(收到.get('网址'), t.url)
        # 通知文案必须体现"部分删除", 不能报成功。
        # 注意: str(SnackBar) 只有 repr 不含内部文本, 须取 .content.value 真值
        文本集 = []
        for c in getattr(self.table.page, '弹出的', []):
            内容 = getattr(c, 'content', None)
            if 内容 is not None and hasattr(内容, 'value'):
                文本集.append(str(内容.value))
        self.assertTrue(文本集, '删除后必须有用户可见反馈')
        self.assertTrue(any('部分删除' in p for p in 文本集),
                        f'部分失败应走"部分删除"提示, 实际: {文本集}')
        self.assertFalse(any('已删除记录' in p for p in 文本集),
                         '部分失败时不得报"已删除"(伪成功, 用户会以为干净了)')


class Test弹窗分流契约(unittest.TestCase):
    """③ 分流由 可询问删除 决定 —— 源码级契约。

    为什么必须如此: 判错类型会让用户误删**仍可恢复**的书。
    站点不可达/目录无章节 书可能只是暂时抓不到, 误删代价远高于多问一句。
    """

    def setUp(self):
        self.文本 = _读源码('gui_app.py')
        块 = self.文本.split('def _提示死书')[1][:3000]
        self.块 = 块

    def test_分流依据是字段而非类型名(self):
        self.assertIn('可询问删除', self.块,
                      '_提示死书 未读 可询问删除 字段')
        self.assertIn('if not 可询问', self.块,
                      '未按 可询问删除 分流')
        # UI 层不得自己拿类型名去判断该不该询问
        for 禁 in ('类型 ==', '类型 in (', '类型 in ('):
            self.assertNotIn(禁, self.块,
                             f'UI 层不得自行比较类型 ({禁}); 只认 可询问删除')

    def test_两类分流形态正确(self):
        self.assertIn('SnackBar', self.块,
                      '不可询问删除的类型应只给 SnackBar 提示, 不弹 modal')
        self.assertIn('AlertDialog', self.块,
                      '可询问删除的类型应弹 AlertDialog 询问')
        self.assertIn('modal=True', self.块, '确认弹窗应为模态')

    def test_弹窗三按钮语义(self):
        for 文案 in ('删除记录', '忽略此书', '稍后处理'):
            self.assertIn(文案, self.块, f'弹窗缺少按钮: {文案}')

    def test_弹窗文字显式颜色(self):
        """EXE 契约: 弹窗文字不显式 color 会渲染成不可见 (v2.4.19)。"""
        弹窗块 = self.块.split('ft.AlertDialog')[1][:1200] if 'ft.AlertDialog' in self.块 else ''
        self.assertIn('MORANDI_ON_SURFACE', 弹窗块,
                      'AlertDialog 文字未显式指定颜色 → EXE 中不可见')
        # 切 ft.SnackBar 而非裸 "SnackBar": 后者首次出现在 "ft.SnackBar" 的
        # 中间, split 后拿到的是 "Bar(ft..." 残片, 断言会假红
        snack块 = self.块.split('ft.SnackBar')[1][:800] if 'ft.SnackBar' in self.块 else ''
        self.assertIn('MORANDI_ON_SURFACE', snack块,
                      'SnackBar 文字未显式指定颜色 → EXE 中不可见')

    def test_提示内容含不动产物承诺(self):
        self.assertRegex(self.块, r'不会删除|不会被删除',
                         '弹窗必须告知用户已下载文件不会被删除')

    def test_队列每tick至多一条(self):
        self.assertIn('取一条待弹死书', self.文本,
                      '刷新循环未接死书队列')
        self.assertIn('page.run_task', self.文本.split('_排空死书队列')[1][:600],
                      '必须经 page.run_task 调度 (唯一跨线程入口, 不能直接碰控件)')


class Test按钮布局不变(unittest.TestCase):
    """操作列宽度不变: 死书态只是换按钮, 不是加按钮。"""

    def test_列宽仍为200且按钮数不变(self):
        文本 = _读源码('gui_components/task_table.py')
        self.assertIn('("操作", 200, True),', 文本,
                      '操作列宽度被改动 (应为 200px, 死书态换按钮不改列宽)')
        ops = 文本.split('ops_cell = _cell(ft.Row([')[1][:200]
        # 末位 del_btn 无逗号, 故 count('btn,') 只能数到 4 → +1 补末位
        self.assertEqual(ops.count('btn,') + 1, 5,
                         '操作按钮数应恒为 5 (死书态替换而非追加)')

    def test_死书态判定用isinstance防御(self):
        文本 = _读源码('gui_components/task_table.py')
        行 = 文本.split('_是死书 = ')[1][:120]
        self.assertIn('isinstance', 行,
                      '_是死书 判定须 isinstance 防御 (Mock truthy 会误入死书分支)')


if __name__ == '__main__':
    unittest.main(verbosity=2)
