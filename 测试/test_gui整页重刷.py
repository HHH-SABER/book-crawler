# -*- coding: utf-8 -*-
"""整页重刷契约 (2026-11-10 v2.7.2 残影自愈)。

事故: v2.7.1 修卡顿后把空闲 tick 改成零 patch, 结果 Flet 客户端在
「主题切换 → 打开关闭弹窗」后只重绘局部, 旧帧像素留在未覆盖区域:
同一个窗口里出现两份「内容库」、左上角白色残块、遮罩只盖住一块矩形。
实机把窗口边框轻拖一下残影立刻消失 ⇒ 客户端重绘问题, 非数据/多开问题。

本文件钉住两条契约:
  ① 空闲 tick 仍然零整页 diff (不能为了修残影退回每秒 page.update());
  ② 结构性事件 (主题/尺寸/切页/弹层/托盘恢复) 登记一次性整页重绘,
     另有低频心跳兜底, 由 1s 刷新循环统一消费。
"""
import pathlib
import unittest
from unittest.mock import Mock

import _沙箱  # noqa: F401  (把 源码/ 挂进 sys.path)

from gui_components.整页重刷 import 整页重刷器

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_GUI_APP = (_ROOT / '源码' / 'gui_app.py').read_text(encoding='utf-8')
_关闭行为 = (_ROOT / '源码' / 'gui_components' / '关闭行为.py').read_text(
    encoding='utf-8')


def _块(文本, 起始锚点, 结束锚点):
    return 文本.split(起始锚点, 1)[1].split(结束锚点, 1)[0]


class Test整页重刷器(unittest.TestCase):
    """纯逻辑: 假时钟 + Mock page, 不依赖 Flet 事件循环。"""

    def setUp(self):
        self.钟 = [0.0]
        self.page = Mock()
        self.page.opacity = 1.0      # Flet Page.opacity 默认值
        self.r = 整页重刷器(self.page, 心跳秒=20.0, 时钟=lambda: self.钟[0])

    def _走一拍(self, 秒=1):
        self.钟[0] += 秒
        return self.r.服务()

    def test_空闲拍零整页刷新(self):
        for _ in range(19):
            self.assertFalse(self._走一拍(), '无请求时不得发整页 diff')
        self.assertEqual(self.page.update.call_count, 0)

    def test_心跳兜底且只发一次(self):
        for _ in range(19):
            self._走一拍()
        self.assertTrue(self._走一拍(2))       # 累计 21s > 20s 心跳
        self.assertEqual(self.page.update.call_count, 1)
        self.assertFalse(self._走一拍(), '心跳后须重新计时')
        self.assertEqual(self.page.update.call_count, 1)

    def test_请求一次只刷一拍(self):
        self.r.请求()
        self.assertTrue(self._走一拍())
        self.assertEqual(self.page.update.call_count, 1)
        self.assertFalse(self._走一拍())
        self.assertEqual(self.page.update.call_count, 1)

    def test_连续两拍请求覆盖迟到帧(self):
        self.r.请求(2)
        self.assertTrue(self._走一拍())
        self.assertTrue(self._走一拍())
        self.assertFalse(self._走一拍())
        self.assertEqual(self.page.update.call_count, 2)

    def test_同一拍多事件不叠加成风暴(self):
        for _ in range(8):
            self.r.请求()
        self.assertEqual(self.r.剩余, 1, '多个事件同拍登记只算一次')
        self._走一拍()
        self.assertFalse(self._走一拍())

    def test_update异常不中断循环且不每秒重试(self):
        self.page.update.side_effect = RuntimeError('窗口尚未挂载')
        self.r.请求()
        self.assertFalse(self._走一拍())
        self.assertFalse(self._走一拍(), '异常后不得退化成每拍重试')
        self.assertEqual(self.page.update.call_count, 1)
        # 心跳到期才允许再试一次
        for _ in range(20):
            self._走一拍()
        self.assertEqual(self.page.update.call_count, 2)

    def test_心跳不得退回一秒一次(self):
        self.assertGreaterEqual(self.r.心跳秒, 10,
                                '心跳太密就退回 v2.7.0 的卡顿根因')

    def test_整页刷新必须产生真实属性变更(self):
        """Flet 0.86: 控件树没变时 page.update() 下发空消息 = 不会重绘。

        所以每次整页重刷都要把 page.opacity (Prop 字段) 在 1.0 与
        0.999999 之间翻一次 (视觉等价), 让 page 根节点有 patch 可发。
        """
        self.r.请求()
        self.assertTrue(self._走一拍())
        self.assertNotEqual(self.page.opacity, 1.0,
                            '必须制造一条真实变更, 否则客户端收不到整页 patch')
        self.assertFalse(self._走一拍(), '无请求的空闲拍仍须零 patch')
        self.r.请求()
        self.assertTrue(self._走一拍(), '第二次整页刷')
        self.assertEqual(self.page.opacity, 1.0, '交替翻回, 不累积透明度偏移')

    def test_空闲拍不改属性(self):
        for _ in range(5):
            self._走一拍()
        self.assertEqual(self.page.opacity, 1.0)

    def test_非数值opacity不制造未知视觉变化(self):
        page = Mock()
        page.opacity = 'unknown'
        r = 整页重刷器(page, 心跳秒=20.0, 时钟=lambda: self.钟[0])
        self.assertFalse(r._可翻转)
        r.请求()
        r.服务()
        self.assertEqual(page.opacity, 'unknown')


class Test真实Session下发(unittest.TestCase):
    """用 Flet 真实 Session + 假连接, 钉住「整页重刷确有 patch 发出」。

    只靠 Mock 断言 page.update() 被调用会漏掉最致命的退化: 控件树没变化时
    Flet 根本不发消息 (patch 长度 1), 调用次数再对也不会重绘。
    """

    def test_翻转opacity确实产生PATCH_CONTROL(self):
        from unittest.mock import Mock, patch
        from flet.messaging.session import Session

        发送 = []
        conn = Mock()
        conn.pubsubhub = Mock()
        with patch.object(Session, '_Session__send_message',
                          new=lambda _s, m: 发送.append(m)):
            s = Session(conn)
            p = s.page
            s.get_page_patch()          # 模拟客户端注册, 建立 prev 快照
            p.update()
            self.assertEqual(len(发送), 0, '无变化时 Flet 应不下发任何消息')

            r = 整页重刷器(p, 心跳秒=20.0, 时钟=lambda: 0.0)
            r.请求()
            self.assertTrue(r.服务(), '有请求时应执行整页重刷')
            self.assertEqual(len(发送), 1, '必须真的发出一条整页 patch')
            self.assertIn('opacity', str(发送[-1]),
                          'patch 内容应是 page.opacity 的变更')



class Test接入点(unittest.TestCase):
    """静态护栏: 结构性事件必须登记整页重绘, 且刷新循环不能自己整页刷。"""

    def test_刷新循环只在服务里整页刷(self):
        块 = _块(_GUI_APP, 'async def _tick_loop():', 'page.run_task(_tick_loop)')
        self.assertIn('重刷器.服务()', 块)
        # 注释里解释了旧实现的 page.update(), 只检查真正的代码行
        代码 = '\n'.join(行.split('#', 1)[0] for 行 in 块.splitlines())
        self.assertNotIn('page.update()', 代码,
                         'tick 里出现裸 page.update() 就是每秒全树 diff 回归')

    def test_主题切换登记两拍(self):
        块 = _块(_GUI_APP, 'def toggle_theme():', '# ---- 图标导航栏 ----')
        self.assertIn('请求整页重刷(2)', 块)

    def test_尺寸落地登记(self):
        块 = _块(_GUI_APP, 'def _尺寸落地():', 'def _on_page_resize(')
        self.assertIn('请求整页重刷(1)', 块)
        self.assertIn('threading.Timer(0.12, _尺寸落地)', _GUI_APP)

    def test_切页登记且不同步整页刷(self):
        块 = _块(_GUI_APP, 'def _switch_page(key: str):', '# ---- 底部状态栏 ----')
        self.assertIn('content_stack.update()', 块)
        self.assertIn('请求整页重刷(1)', 块)

    def test_关闭行为接到请求器(self):
        self.assertIn('_安装关闭行为(page, task_manager, 请求整页重刷=请求整页重刷)',
                      _GUI_APP)
        self.assertIn('def 安装(page, task_manager, 请求整页重刷=None)', _关闭行为,
                      '可选参数须保留, 冒烟脚本仍用 安装(page, tm) 两参调用')

    def test_弹层开关都登记(self):
        弹层关闭 = _块(_关闭行为, 'def _弹层关闭():', 'def _切换记住(e):')
        self.assertIn('_全刷(2)', 弹层关闭)
        询问 = _块(_关闭行为, 'page.show_dialog(dlg)', 'def _处理关闭(e):')
        self.assertIn('_全刷(2)', 询问)

    def test_托盘恢复登记(self):
        恢复 = _块(_关闭行为, 'async def _显示主窗():', 'def _停远控服务():')
        self.assertIn('_全刷(2)', 恢复)


if __name__ == '__main__':
    unittest.main(verbosity=2)
