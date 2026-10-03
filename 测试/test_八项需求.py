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

    def test_滚动条四处ALWAYS(self):
        cases = [
            ('gui_components/pages/dead_book_page.py', 'self._列表 = ft.Column('),
            ('gui_components/pages/site_manage_page.py', 'return ft.Column([header, banner'),
            ('gui_components/task_table.py', '横滚 = ft.Row('),
            ('gui_components/detail_drawer.py', 'self._detail_view = ft.Column('),
        ]
        for rel, anchor in cases:
            文本 = _读(rel)
            段 = 文本.split(anchor)[1][:800]
            self.assertIn('ft.ScrollMode.ALWAYS', 段, f'{rel} 的滚动条未改 ALWAYS')

    def test_组装发布脚本隐私排除(self):
        脚本 = (_ROOT / '脚本' / '组装发布.py').read_text(encoding='utf-8')
        for 词 in ('抓取结果', '站点配置.json', 'captcha_config.json', '站点适配_本地'):
            self.assertIn(词, 脚本, f'组装发布脚本缺 {词} 处置')

    def test_发布目录已入gitignore(self):
        gi = (_ROOT / '.gitignore').read_text(encoding='utf-8')
        self.assertIn('/发布/', gi, '发布/ 目录必须忽略 (290MB EXE + 私有适配)')


if __name__ == '__main__':
    unittest.main()
