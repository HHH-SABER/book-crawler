# -*- coding: utf-8 -*-
"""死书 meta 行数据缺口收口回归 (2026-10-07, 批 3 收尾)。

**缺口是什么**: 设计稿死书卡片的 meta 行是
`URL · HTTP 码 · 判定于 <时间> · 已抓 N 章`, 而 `死书处理` 的记录里
**没有 HTTP 状态码 / 已抓章节这两个字段** —— 设计会话明确留作数据缺口,
并要求"在判定时写进记录, 不要在 UI 层猜"。

**修法 (本文件锁的就是这条链)**:
    爬虫.py 采集 last_status_code + 输出文件已写章节数
      → 死书处理.判定死书(状态码=, 已抓章节=)   [纯函数]
      → 死书处理.死书错误(…, 状态码, 已抓章节)  [结构化携带]
      → task_manager._记死书
      → 死书处理.记录死书(…)                    [落盘]

⚠️ 这条链的失效模式是**静默**的: 任何一环漏传, 页面只是"少显示一段",
不抛异常、日志也不报 —— 所以必须有跨环节的用例, 只测每个函数各自的
入参出参**发现不了**"没人把值传下来"(与 #3 双失效标志当年潜伏同因)。

运行: python -m unittest discover -s 测试
"""
import sys
import unittest
from pathlib import Path

import _沙箱  # noqa: F401  沙箱: LOCALAPPDATA → 一次性临时目录

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / '源码'
for _p in (str(_ROOT), str(_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _读(相对: str) -> str:
    return (_SRC / 相对).read_text(encoding='utf-8')


class Test链路_判定到落盘(unittest.TestCase):
    """端到端: 判定 → 死书错误 → _记死书 → 记录落盘。"""

    def setUp(self):
        from gui_components.task_manager import TaskManager, TaskInfo
        import 死书处理
        self.死书 = 死书处理
        self.mgr = TaskManager(page=None)
        self._TaskInfo = TaskInfo

    def _跑一遍(self, url: str, **判定参数):
        t = self._TaskInfo(task_id='td_gap', url=url, title='测试书')
        死 = self.死书.判定死书(章节数=0, **判定参数)
        self.assertIsNotNone(死)
        self.mgr._记死书(t, self.死书.死书错误(
            死['类型'], 死['原因'], url, 死['网站失效'],
            死['状态码'], 死['已抓章节'], 死['页面为空']))
        return t

    def _落盘记录(self, url: str) -> dict:
        return next(r for r in self.死书.载入() if r.get('网址') == url)

    def test_状态码与已抓章节贯通到记录(self):
        url = 'https://gap1.example.com/book'
        t = self._跑一遍(url, 页面为空=False, 书名='正常书名',
                        状态码=404, 已抓章节=412)
        self.assertEqual(t.status, 'dead_pending')
        self.assertEqual(t.dead['HTTP状态码'], 404, 'task.dead 应带状态码')
        记录 = self._落盘记录(url)
        self.assertEqual(记录['HTTP状态码'], 404, '状态码必须落盘 (重启后仍可见)')
        self.assertEqual(记录['已抓章节'], 412, '已抓章节必须落盘')

    def test_网络层失败记零而非编造(self):
        """页面为空 (没拿到响应) → 状态码 0; 页面靠"键存在"区分真 0 与老记录"""
        url = 'https://gap2.example.com/book'
        self._跑一遍(url, 页面为空=True, 书名='x', 状态码=0, 已抓章节=0)
        记录 = self._落盘记录(url)
        self.assertEqual(记录['HTTP状态码'], 0)
        self.assertEqual(记录['已抓章节'], 0)
        self.assertIn('已抓章节', 记录, '键必须存在 (否则页面无法区分"真 0"与老记录)')

    def test_页面为空贯通到记录(self):
        """设计稿第 2 槽的用词 (连接超时 / 内容为空) 全靠这个事实 —— 漏传就全变一个词"""
        url = 'https://gap5.example.com/book'
        self._跑一遍(url, 页面为空=True, 书名='x', 状态码=0, 已抓章节=0)
        self.assertTrue(self._落盘记录(url)['页面为空'], '页面为空 必须落盘')
        url2 = 'https://gap6.example.com/book'
        self._跑一遍(url2, 页面为空=False, 书名='正常书名',
                    状态码=0, 已抓章节=47)
        self.assertFalse(self._落盘记录(url2)['页面为空'])

    def test_已抓章节反映上轮部分进度(self):
        """判定发生在"目录 0 章节"这一步, 但输出文件可能已有上一轮的进度 ——
        这个数正是用户决定"该不该删这本书"的依据, 不能被想当然填 0。"""
        url = 'https://gap3.example.com/book'
        self._跑一遍(url, 页面为空=False, 书名='正常书名',
                    状态码=200, 已抓章节=87)
        self.assertEqual(self._落盘记录(url)['已抓章节'], 87)

    def test_旧记录无这两个键时页面侧可识别(self):
        """补字段之前写下的老记录: 键不存在 = 无从显示 (页面据此跳过)。"""
        self.死书.保存([])
        self.死书.记录死书('https://gap4.example.com/b', '书',
                          self.死书.类型_无章节, '原因')
        记录 = self._落盘记录('https://gap4.example.com/b')
        # 新写入的记录一定带键 (0 也是真值); 老记录才会缺键 —— 此处锁的是
        # "缺键 → 页面跳过" 这条判据的另一半: page 侧用 `'已抓章节' in r`。
        page = _读('gui_components/pages/dead_book_page.py')
        self.assertIn("'已抓章节' in r", page,
                      '页面必须用"键是否存在"区分真 0 与老记录')


class Test爬虫侧接线(unittest.TestCase):
    """`爬虫.py` 的采集点与传递点 —— 只测纯函数覆盖不到这一层。"""

    def setUp(self):
        self.src = _读('爬虫.py')

    # 请求路径的锚点: __init__ 里也有一处 `last_request_error = ''`,
    # 直接按它切会切到构造函数 (段落里当然没有采集点) → 用这行的注释锚。
    _锚 = '# 每次进入请求路径先清零'

    def _请求路径块(self, 长: int = 3000) -> str:
        self.assertIn(self._锚, self.src, '未找到请求路径锚点 (代码被改过?)')
        return self.src.split(self._锚)[1][:长]

    def test_状态码有初始化(self):
        self.assertIn('self.last_status_code = 0', self.src,
                      '缺 last_status_code 初始化 → getattr 兜底恒 0, 字段永远为空')

    def test_状态码在请求路径被采集(self):
        self.assertIn('self.last_status_code = int(', self._请求路径块(),
                      '请求路径未采集状态码 → 该字段恒 0')

    def test_采集点在5xx置空之前(self):
        """顺序是关键: 5xx 分支会把 response 置 None, 采集必须早于它 ——
        否则 502 这类"最该显示 HTTP 码"的场景反而记成"未知"。"""
        块 = self._请求路径块()
        i采集 = 块.find('self.last_status_code = int(')
        i置空 = 块.find('response = None')
        self.assertGreater(i采集, -1, '未找到状态码采集点')
        self.assertGreater(i置空, -1, '未找到 5xx 置空点')
        self.assertLess(i采集, i置空,
                        '状态码采集必须在 5xx 把 response 置 None 之前')

    def test_判定死书调用带两个新参数(self):
        # 已抓章节在调用前先算好 (_已抓), 故段落要包含调用点**之前**几行
        块 = self.src.split('from 死书处理 import 判定死书')[1][:1400]
        self.assertIn('self.last_dead = 判定死书(', 块, '未找到判定死书调用点')
        # 断言**具体取值表达式**, 不只断言"出现了 状态码=" ——
        # 否则把实参改成常量 0 也能骗过测试 (变异 M3 实测抓到过这一漏洞)。
        self.assertIn("状态码=getattr(self, 'last_status_code', 0),", 块,
                      '判定死书 未收到真实状态码 → 记录里永远是 0')
        self.assertIn('已抓章节=_已抓)', 块,
                      '判定死书 未收到已抓章节 (或改成了常量)')
        self.assertIn('_count_written_chapters', 块,
                      '已抓章节应取真实输出文件计数, 不是想当然的 0')

    def test_多源回退透传两个字段(self):
        """走备用源时死书错误在另一处重建 —— 漏了这里, 多源场景字段全丢。"""
        块 = self.src.split('last_error = 死书错误(')[1][:400]
        self.assertIn("_死.get('状态码'", 块, '多源回退未透传状态码')
        self.assertIn("_死.get('已抓章节'", 块, '多源回退未透传已抓章节')
        self.assertIn("_死.get('页面为空'", 块, '多源回退未透传页面为空')

    def test_task_manager透传(self):
        src = _读('gui_components/task_manager.py')
        self.assertIn("getattr(exc, '状态码'", src)
        self.assertIn("getattr(exc, '已抓章节'", src)
        self.assertIn("getattr(exc, '页面为空'", src)
        块 = src.split('记录死书(task.url')[1][:400]
        self.assertIn('状态码=状态码', 块)
        self.assertIn('已抓章节=已抓章节', 块)
        self.assertIn('页面为空=页面为空', 块)

    def test_页面不得自比类型名推词(self):
        """UI 只许读结构化字段 —— 比类型名推失败短语会在判定变更时静默说错话"""
        page = _读('gui_components/pages/dead_book_page.py')
        段 = page.split('失败短语')[1][:900]
        for 禁 in ('类型 ==', '类型 in ('):
            self.assertNotIn(禁, 段, f'第 2 槽不得靠比类型名推词 ({禁})')


if __name__ == '__main__':
    unittest.main(verbosity=2)
