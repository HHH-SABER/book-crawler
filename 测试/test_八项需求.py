# -*- coding: utf-8 -*-
"""八项需求改造回归 (2026-10-03, v2.4.45)

覆盖: #2 终态通知+音效 / #3 双失效标记 / #4 组装发布脚本 / #5 首次引导 /
#6 常显滚动条 / #7 远控局域网直连 / K37 死书弹窗 async 修复。
静态契约用例锁字符串防倒退; 行为用例经 _沙箱 隔离状态根。
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import _沙箱  # noqa: F401  沙箱: LOCALAPPDATA → 一次性临时目录

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / '源码'


def _读(相对: str) -> str:
    return (_SRC / 相对).read_text(encoding='utf-8')


def _去整行注释(文本: str) -> str:
    """去掉**整行**注释后返回, 供静态契约断言使用。

    否则"注释里提到某函数名/某写法"会让断言误报 (2026-10-04 实际踩到:
    失败分支的说明注释里写了 `_写首次flag`, 被当成"失败分支调用了它")。
    只去整行注释 —— 行尾 `#` 不能碰: 代码里有颜色字面量 `'#AD5710'` 之类。
    """
    return '\n'.join(l for l in 文本.splitlines() if not l.strip().startswith('#'))


def _控件树含(根, 目标) -> bool:
    """递归遍历 Flet 控件树, 判断 `目标` 是否真的被挂载 (content / controls)。

    用途: "控件建了但没放进布局"是静默失败 —— 用户看不到、测试也只 `hasattr` 就过。
    这里真构建一次控件树再走一遍, 把这类孤儿控件钉死。
    """
    待查 = [根]
    已见 = set()
    while 待查:
        当前 = 待查.pop()
        if 当前 is None or id(当前) in 已见:
            continue
        已见.add(id(当前))
        if 当前 is 目标:
            return True
        for 子 in (getattr(当前, 'controls', None) or []):
            待查.append(子)
        内容 = getattr(当前, 'content', None)
        if 内容 is not None:
            待查.append(内容)
    return False


class Test终态通知行为(unittest.TestCase):
    """#2: _set_terminal 入队 + 音效静默 + 队列 FIFO 消费"""

    def setUp(self):
        from gui_components.task_manager import TaskManager
        self.mgr = TaskManager(page=None)

    def _任务(self, title='测试书'):
        from gui_components.task_manager import TaskInfo
        return TaskInfo(task_id='t1', url='https://example.com/book',
                        title=title)

    def test_completed入队成功通知(self):
        t = self._任务()
        self.mgr._set_terminal(t, 'completed')
        n = self.mgr.取一条待弹通知()
        self.assertIsNotNone(n)
        self.assertEqual(n['状态'], 'success')
        self.assertEqual(n['书名'], '测试书')
        self.assertEqual(n['原因'], '')

    def test_failed带error原因(self):
        t = self._任务()
        t.error = '目录页返回 404'
        self.mgr._set_terminal(t, 'failed')
        n = self.mgr.取一条待弹通知()
        self.assertEqual(n['状态'], 'fail')
        self.assertIn('404', n['原因'])

    def test_dead_pending带判定原因(self):
        t = self._任务()
        t.dead = {'类型': '书已删除', '原因': '目录 0 章节'}
        self.mgr._set_terminal(t, 'dead_pending')
        n = self.mgr.取一条待弹通知()
        self.assertEqual(n['状态'], 'fail')
        self.assertIn('书已删除', n['原因'])
        self.assertIn('0 章节', n['原因'])

    def test_stopped不通知(self):
        t = self._任务()
        self.mgr._set_terminal(t, 'stopped')
        self.assertIsNone(self.mgr.取一条待弹通知())

    def test_空队列返回None(self):
        self.assertIsNone(self.mgr.取一条待弹通知())

    def test_音效异常静默(self):
        # 非 Windows 无 winsound / 声音设备缺失: 不抛异常即通过
        t = self._任务()
        self.mgr._播放终态音效('completed')
        self.mgr._播放终态音效('failed')
        self.mgr._播放终态音效('stopped')

    def test_通知队列FIFO(self):
        a = self._任务('甲')
        b = self._任务('乙')
        self.mgr._set_terminal(a, 'completed')
        self.mgr._set_terminal(b, 'completed')
        self.assertEqual(self.mgr.取一条待弹通知()['书名'], '甲')
        self.assertEqual(self.mgr.取一条待弹通知()['书名'], '乙')


class Test通知队列与静音(unittest.TestCase):
    """#2 (2026-10-04 修复): 有界队列 / 相邻去重 / 幂等 / 状态白名单 / 静音开关

    旧实现的四个缺口: 队列无上限(集中结束会长时间连弹)、append 不持锁、
    `else` 把任何非 completed/stopped 都当失败通知、无静音入口。
    """

    def setUp(self):
        from gui_components.task_manager import TaskManager
        self.mgr = TaskManager(page=None)

    def _任务(self, tid, title):
        from gui_components.task_manager import TaskInfo
        return TaskInfo(task_id=tid, url='https://example.com/b', title=title)

    def test_队列有界_只留最近N条(self):
        上限 = self.mgr._通知上限
        for i in range(上限 + 7):
            self.mgr._入队通知({'书名': f'书{i}', '状态': 'success', '原因': ''})
        self.assertEqual(len(self.mgr._通知待弹), 上限)
        self.assertEqual(self.mgr._通知待弹[-1]['书名'], f'书{上限 + 6}',
                         '有界裁剪必须保留最新的那条')

    def test_相邻同书同状态合并为一条(self):
        self.mgr._入队通知({'书名': 'A', '状态': 'fail', '原因': '第一次'})
        self.mgr._入队通知({'书名': 'A', '状态': 'fail', '原因': '第二次'})
        self.assertEqual(len(self.mgr._通知待弹), 1, '相邻同书同状态应合并')
        self.assertEqual(self.mgr._通知待弹[0]['原因'], '第二次', '合并须保留最新原因')

    def test_未知状态不再被当失败通知(self):
        t = self._任务('t1', '书')
        self.mgr._set_terminal(t, 'queued')      # 未来新增的状态
        self.assertIsNone(self.mgr.取一条待弹通知(),
                          '非白名单状态不得走"失败"分支 (旧实现 else 通吃)')

    def test_重复置同终态幂等(self):
        t = self._任务('t1', '书')
        self.mgr._set_terminal(t, 'completed')
        self.mgr._set_terminal(t, 'completed')
        self.assertIsNotNone(self.mgr.取一条待弹通知())
        self.assertIsNone(self.mgr.取一条待弹通知(), '重复置同终态不得重复通知')

    def test_偏好往返与持久化(self):
        import 界面偏好
        界面偏好.清空缓存()
        self.assertTrue(界面偏好.设置('提示音', False))
        界面偏好.清空缓存()                      # 丢缓存, 强制重新读盘
        self.assertFalse(界面偏好.取('提示音', True), '偏好应真的落盘')

    def test_静音后不播放音效_开启后播放(self):
        import 界面偏好
        界面偏好.清空缓存()
        播放 = []
        假模块 = mock.MagicMock()
        假模块.MessageBeep = lambda *a, **k: 播放.append(a)
        with mock.patch.dict(sys.modules, {'winsound': 假模块}):
            界面偏好.设置('提示音', False)
            self.mgr._播放终态音效('completed')
            self.assertEqual(播放, [], '静音后不得播放提示音')
            界面偏好.设置('提示音', True)
            self.mgr._播放终态音效('completed')
            self.assertEqual(len(播放), 1, '开启后应播放提示音')

    def test_输入条有提示音开关且真的在布局里并能持久化(self):
        from gui_components.input_bar import InputBar
        import 界面偏好
        界面偏好.清空缓存()
        bar = InputBar(self.mgr)
        根 = bar.build()                     # 只建一次, 之后属性引用才有效
        self.assertTrue(hasattr(bar, '提示音_switch'), '输入条应提供静音入口')
        self.assertTrue(_控件树含(根, bar.提示音_switch),
                        '提示音开关必须真的挂进布局 —— 建了不挂=孤儿控件, 用户看不到')
        bar._on_提示音切换(mock.Mock(control=mock.Mock(value=False)))
        界面偏好.清空缓存()
        self.assertFalse(界面偏好.取('提示音', True), '开关切换应持久化')


class Test异常路径顺序(unittest.TestCase):
    """#2 顺序修正: task.error 先于 _记死书 先于 _set_terminal。

    旧序 _set_terminal 先跑, 通知入队时 task.error 尚为空 → 失败原因恒 ''。
    """

    def test_异常路径顺序(self):
        文本 = _读('gui_components/task_manager.py')
        块 = 文本.split('except Exception as e:')[1][:2000]
        i_err = 块.find('task.error = str(e)')
        i_记 = 块.find('self._记死书(task, e)')
        i_ter = 块.find('self._set_terminal(')
        self.assertGreaterEqual(i_err, 0, '异常路径未找到 task.error 赋值')
        self.assertLess(i_err, i_记, 'task.error 必须先于 _记死书 (通知要展示原因)')
        self.assertLess(i_记, i_ter, '_记死书 必须先于 _set_terminal (dead 原因入通知)')
        self.assertIn("task.status if task.status == 'dead_pending'", 块,
                      '终态调用未按 dead_pending 传参 → 死书终态被改写为 failed')


class Test网站失效判定(unittest.TestCase):
    """#3: 是网站失效异常 特征判定 (纯函数, 双失效分支的数据信号)"""

    def test_DNS特征命中(self):
        from 死书处理 import 是网站失效异常
        self.assertTrue(是网站失效异常('[Errno 11001] getaddrinfo failed'))
        self.assertTrue(是网站失效异常(
            "NameResolutionError: Failed to resolve 'example.com'"))
        self.assertTrue(是网站失效异常('Temporary failure in name resolution'))
        self.assertTrue(是网站失效异常('no address associated with hostname'))

    def test_临时故障不命中(self):
        from 死书处理 import 是网站失效异常
        self.assertFalse(是网站失效异常('Service Temporarily Unavailable'))
        self.assertFalse(是网站失效异常('502 Bad Gateway'))
        self.assertFalse(是网站失效异常('目录无章节'))
        self.assertFalse(是网站失效异常(''))
        self.assertFalse(是网站失效异常(None))

    # ---- 2026-10-04 修复补充: 标志必须在**判定侧**算出并结构化带走 ----
    # 此前只测了纯函数, 没有任何用例验证"标志真的会置位、并被下游读到",
    # 于是该需求自上线起从未生效却一路绿灯 (见 文档/审查报告汇总.md 2026-10-04 条目)。

    def test_判定死书_域名死时置标志(self):
        from 死书处理 import 判定死书
        死 = 判定死书(页面为空=True, 书名='某书', 章节数=0,
                      网络异常文本="ConnectionError: HTTPSConnectionPool(host='x'): "
                                   '[Errno 11001] getaddrinfo failed')
        self.assertTrue(死['网站失效'])
        self.assertEqual(死['类型'], '站点不可达')

    def test_判定死书_临时5xx不置标志(self):
        from 死书处理 import 判定死书
        死 = 判定死书(页面为空=True, 书名='某书', 章节数=0,
                      网络异常文本='HTTP 502 服务器错误')
        self.assertFalse(死['网站失效'])

    def test_判定死书_非页面为空分支一律不置标志(self):
        from 死书处理 import 判定死书
        for kw in (dict(页面为空=False, 书名='占位值', 章节数=0),
                   dict(页面为空=False, 书名='502 Bad Gateway', 章节数=0),
                   dict(页面为空=False, 书名='正常书名', 章节数=0)):
            死 = 判定死书(网络异常文本='[Errno 11001] getaddrinfo failed', **kw)
            self.assertIsNotNone(死)
            self.assertFalse(死['网站失效'], f'{kw} 不应置位')

    def test_死书错误结构化携带标志(self):
        from 死书处理 import 死书错误
        e = 死书错误('站点不可达', '目录页三次重试均未取到内容 (页面为空), 站点不可达或网络受限',
                    'https://x.example.com/b', True)
        self.assertTrue(e.网站失效)
        self.assertFalse(
            死书错误('站点不可达', '原因', 'https://x.example.com/b').网站失效)


class Test双失效链路集成(unittest.TestCase):
    """#3 修复的**端到端**用例: 判定 → 死书错误 → _记死书 → 落盘 + 入待弹队列。

    这正是此前缺失的那一类测试 —— 只测纯函数与源码字符串存在性, 无法发现
    "标志在真实链路上永远不会被置位", 死代码因此长期潜伏。
    """

    def setUp(self):
        from gui_components.task_manager import TaskManager, TaskInfo
        self.mgr = TaskManager(page=None)
        self._TaskInfo = TaskInfo

    def _喂一次(self, url, 网络异常文本):
        from 死书处理 import 判定死书, 死书错误
        t = self._TaskInfo(task_id='td1', url=url, title='测试书')
        死 = 判定死书(页面为空=True, 书名='测试书', 章节数=0,
                      网络异常文本=网络异常文本)
        self.mgr._记死书(t, 死书错误(死['类型'], 死['原因'], url, 死['网站失效']))
        return t

    def test_域名死_标志贯通到task并落盘且入队(self):
        url = 'https://dead1.example.com/book'
        t = self._喂一次(url, "ConnectionError: [Errno 11001] getaddrinfo failed")
        self.assertTrue(t.dead['网站失效'], 'task.dead 应带标志 (GUI 据此分流补址弹窗)')
        self.assertEqual(t.status, 'dead_pending')
        self.assertEqual(self.mgr.取一条待弹死书(), t.task_id)
        from 死书处理 import 载入
        记录 = next(r for r in 载入() if r.get('网址') == url)
        self.assertTrue(记录['网站失效'], '标志应随记录落盘 (清单页/重启后仍可见)')

    def test_临时故障_标志为假不误弹(self):
        url = 'https://flaky2.example.com/book'
        t = self._喂一次(url, 'HTTP 502 服务器错误')
        self.assertFalse(t.dead.get('网站失效'))
        self.assertFalse(t.dead['网站失效'])


class Test远控局域网直连(unittest.TestCase):
    """#7: 默认 0.0.0.0 + 旧默认 127.0.0.1 迁移 + 展示地址解析"""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix='nc_rq7_')

    def _取配置(self, disk: dict):
        import json
        cfg_file = os.path.join(self.tmp, '远控配置.json')
        with open(cfg_file, 'w', encoding='utf-8') as f:
            json.dump(disk, f, ensure_ascii=False)
        from 远控 import 配置
        with mock.patch.object(配置, '_配置路径', lambda: cfg_file), \
                mock.patch.object(配置, '_CONFIG', None):
            return 配置.取配置(), cfg_file

    def test_首建默认绑定0_0_0_0(self):
        cfg, _ = self._取配置({'token': 'x' * 32})
        self.assertEqual(cfg['绑定'], '0.0.0.0')

    def test_旧默认127迁移为0_0_0_0并回写(self):
        import json
        cfg, cfg_file = self._取配置({'绑定': '127.0.0.1', 'token': 'x' * 32})
        self.assertEqual(cfg['绑定'], '0.0.0.0')
        with open(cfg_file, encoding='utf-8') as f:
            self.assertEqual(json.load(f)['绑定'], '0.0.0.0', '迁移未回写磁盘')

    def test_用户手改的其他绑定不受影响(self):
        cfg, _ = self._取配置({'绑定': '192.168.1.5', 'token': 'x' * 32})
        self.assertEqual(cfg['绑定'], '192.168.1.5')

    def test_展示地址0_0_0_0解析为局域网IP(self):
        from 远控 import 服务
        with mock.patch.object(服务, '取配置',
                               lambda: {'绑定': '0.0.0.0', '端口': 8760}), \
                mock.patch.object(服务, '局域网地址们',
                                  lambda: ['192.168.1.7', '10.0.0.3']):
            self.assertEqual(服务.展示地址(), 'http://192.168.1.7:8760/')

    def test_展示地址自定绑定原样(self):
        from 远控 import 服务
        with mock.patch.object(服务, '取配置',
                               lambda: {'绑定': '127.0.0.1', '端口': 9001}):
            self.assertEqual(服务.展示地址(), 'http://127.0.0.1:9001/')

    def test_局域网地址排除回环(self):
        from 远控 import 服务
        for ip in 服务.局域网地址们():
            self.assertFalse(ip.startswith('127.'), f'回环地址混入: {ip}')

    # ---- 2026-10-04 修 (#7 边界): 迁移一次性 + 地址可用性提示 ----

    def test_已迁移标记后_用户有意设回环不再被改(self):
        """迁移必须是一次性的: 否则用户日后有意只在本机开放会被每次启动改回 0.0.0.0

        (旧实现只比值不看历史 → 静默扩大暴露面, 见 文档/审查报告汇总.md 2026-10-04)
        """
        cfg, _ = self._取配置({'绑定': '127.0.0.1', '_绑定迁移v2': True, 'token': 'x' * 32})
        self.assertEqual(cfg['绑定'], '127.0.0.1', '已迁移过 → 应尊重用户当前选择')


class Test远控地址提示(unittest.TestCase):
    """#7 (2026-10-04): 地址"看着能用其实连不上"时必须给出原因"""

    def test_回环绑定给出提示(self):
        from 远控 import 服务
        with mock.patch.object(服务, '取配置',
                               lambda: {'绑定': '127.0.0.1', '端口': 8760}):
            self.assertIn('仅本机可访问', 服务.地址提示())

    def test_未探测到局域网地址给出提示(self):
        from 远控 import 服务
        with mock.patch.object(服务, '取配置', lambda: {'绑定': '0.0.0.0', '端口': 8760}), \
                mock.patch.object(服务, '局域网地址们', lambda: []):
            self.assertIn('未探测到局域网地址', 服务.地址提示())

    def test_一切正常时不提示(self):
        from 远控 import 服务
        with mock.patch.object(服务, '取配置', lambda: {'绑定': '0.0.0.0', '端口': 8760}), \
                mock.patch.object(服务, '局域网地址们', lambda: ['192.168.1.5']):
            self.assertEqual(服务.地址提示(), '')

    def test_远控页能真正显示提示(self):
        """真构建控件树: 提示行接错/漏接都会让这条断言失败 (非字符串检查)"""
        from gui_components.pages.remote_page import RemotePage

        class _TM:
            def get_all_tasks(self):
                return []

        p = RemotePage()
        p.build()                      # 控件树在 build() 里创建, 不在 __init__
        p.task_manager = _TM()
        p.取信息 = lambda: {'运行': True, '地址': 'http://192.168.1.5:8760/',
                          'token': 'x' * 32, '提示': '未探测到局域网地址: 测试'}
        p.refresh()
        self.assertEqual(p._hint.value, '未探测到局域网地址: 测试')
        self.assertTrue(p._hint.visible)

    def test_远控页无提示时隐藏该行(self):
        from gui_components.pages.remote_page import RemotePage

        class _TM:
            def get_all_tasks(self):
                return []

        p = RemotePage()
        p.build()
        p.task_manager = _TM()
        p.取信息 = lambda: {'运行': True, '地址': 'http://192.168.1.5:8760/',
                          'token': 'x' * 32, '提示': ''}
        p.refresh()
        self.assertFalse(p._hint.visible)


class Test静态契约(unittest.TestCase):
    """锁字符串防倒退: K37 async / 通知排空挂点 / 首次引导 / 滚动条 / 组装发布"""

    def test_K37_死书弹窗必须async(self):
        self.assertIn('async def _提示死书', _读('gui_app.py'),
                      'page.run_task 要求协程函数; 同步 def 会让死书弹窗永不弹出 (K37)')

    def test_通知排空已挂刷新循环(self):
        文本 = _读('gui_app.py')
        self.assertIn('def _排空通知', 文本)
        self.assertIn('_排空通知()', 文本.split('async def _refresh_loop')[1],
                      '终态通知未接入 _refresh_loop → 通知永不展示')

    def test_双失效弹窗分支存在(self):
        文本 = _读('gui_app.py')
        self.assertIn('def _弹双失效', 文本)
        self.assertIn("死.get('网站失效')", 文本,
                      '双失效分流缺失 → 网站失效时走不到补址弹窗')

    def test_首次引导存在且写flag(self):
        文本 = _读('gui_app.py')
        self.assertIn('首次启动.flag', 文本)
        self.assertIn('_建桌面快捷方式', 文本)
        self.assertIn('page.run_task(_首次引导)', 文本)

    def test_滚动条常显覆盖全部主内容区(self):
        """#6 (2026-10-04 加固): 覆盖**全部 12 处**常显, 而不是只锁 4 个锚点。

        旧用例对 4 个锚点做"锚点后 800 字符内含 ALWAYS"的字符串检查 —— 其余 6 处
        (history_page / remote_page / log_tab / site_manage_page 的两处 / task_table 纵滚)
        无论回退成 AUTO 还是被删掉都不会被发现。
        现改为: ①逐文件统计 ALWAYS 数量下限 (新增不算回归, 变少即红);
        ②这 7 个文件内**禁止** AUTO/HIDDEN 残留 (主内容区必须常显)。
        """
        预期下限 = {
            'gui_components/detail_drawer.py': 3,
            'gui_components/log_tab.py': 1,
            'gui_components/task_table.py': 2,
            'gui_components/pages/dead_book_page.py': 1,
            'gui_components/pages/history_page.py': 1,
            'gui_components/pages/remote_page.py': 1,
            'gui_components/pages/site_manage_page.py': 3,
        }
        for 相对, 至少 in 预期下限.items():
            文本 = _读(相对)
            实际 = 文本.count('ScrollMode.ALWAYS')
            self.assertGreaterEqual(
                实际, 至少, f'{相对} 常显滚动条数量 {实际} < 预期 {至少} (有位置回退了)')
            for 禁 in ('ScrollMode.AUTO', 'ScrollMode.HIDDEN'):
                self.assertNotIn(禁, 文本, f'{相对} 出现 {禁} —— 主内容区不得回退')

    def test_首次引导失败不烧flag且flag原子写(self):
        """#5 (2026-10-04 修复): 一次瞬时失败不得让引导永久消失; 标记文件必须原子写"""
        文本 = _去整行注释(_读('gui_app.py'))   # 注释里提到函数名不算调用
        写段 = 文本.split('def _写首次flag', 1)[1][:700]
        self.assertIn('os.replace', 写段, 'flag 写入必须是原子写 (tmp + os.replace)')
        创段 = 文本.split('async def _创建', 1)[1].split('def _跳过', 1)[0]
        self.assertIn('_写首次flag(', 创段, '创建成功后应写 flag')
        # 失败分支 = except 之后到 `return` 之前; 其中不得出现写 flag
        失败段 = 创段.split('except Exception as e:', 1)[1].split('return', 1)[0]
        self.assertNotIn('_写首次flag', 失败段,
                         '失败分支不得写 flag —— 旧实现写在 finally, 一次瞬时失败就永久放弃引导')
        跳段 = 文本.split('def _跳过', 1)[1][:400]
        self.assertIn('_写首次flag(', 跳段, '用户明确拒绝也应写 flag (只问一次)')

    def test_组装发布脚本已改为默认清空私有适配(self):
        """静态锁: 私有适配目录必须挂在显式开关后面 (行为验证见 test_组装发布隐私.py)

        2026-10-04 改: 原用例只断言脚本文本里出现 '站点适配_本地' 等四个词 ——
        那**反而把"复制私有适配"锁成了契约**(脚本跑不跑都通过, 且不校验产物)。
        现改为锁定"必须由开关控制 + 必须有组装后自检", 真正的产物验证交给新行为测试。
        """
        脚本 = (_ROOT / '脚本' / '组装发布.py').read_text(encoding='utf-8')
        self.assertIn('--含本地适配器', 脚本, '私有适配必须由显式开关控制')
        self.assertIn('_隐私自检', 脚本, '组装后必须有隐私自检兜底')
        self.assertIn('_公开包禁入', 脚本, '公开包必须显式禁止私有适配目录')

    def test_发布目录已入gitignore(self):
        gi = (_ROOT / '.gitignore').read_text(encoding='utf-8')
        self.assertIn('/发布/', gi, '发布/ 目录必须忽略 (290MB EXE + 私有适配)')


if __name__ == '__main__':
    unittest.main()
