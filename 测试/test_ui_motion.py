# -*- coding: utf-8 -*-
"""ui_motion 动效令牌回归 (2026-10-14)

覆盖:
  ① 时长三档单调递增且为整数 (节奏口径的护栏)
  ② 曲线名必须是 FAST_OUT_SLOWIN (0.86 没有 FAST_OUT_SLOW_IN, 写错静默失效)
  ③ 动效开关: 开启返回 Animation, 关闭返回 None
  ④ 进场(): 挂上 opacity/offset/animate_*; 动效关闭时不动控件
  ⑤ 降级安全: 控件不支持动画属性时, 必须复位成**可见**, 不留 opacity=0
  ⑥ 接线护栏: gui_app._switch_page 必须走 ui_motion (禁 page.update / 禁自造)

运行 (项目根): python -m unittest discover -s 测试 -v
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / '源码'))

import flet as ft                              # noqa: E402
from gui_components import ui_motion as M      # noqa: E402
import 界面偏好                                # noqa: E402


def _关动效():
    """把界面偏好里的「动效」临时设为 False 的补丁器"""
    return mock.patch.object(界面偏好, '取',
                             side_effect=lambda k, d=None: False)


class Test动效令牌(unittest.TestCase):

    def test_时长三档单调递增(self):
        self.assertLess(M.MOTION_快, M.MOTION_中)
        self.assertLess(M.MOTION_中, M.MOTION_慢)
        for v in (M.MOTION_快, M.MOTION_中, M.MOTION_慢):
            self.assertIsInstance(v, int, '时长必须是整数毫秒')
            self.assertGreater(v, 0)

    def test_幅度在合理区间(self):
        self.assertTrue(0 < M.MOTION_进场上移 < 0.1,
                        '进场位移应克制 (<10%), 过大会像整页在滑')
        self.assertTrue(0.8 < M.MOTION_按压缩放 <= 1.0)

    def test_曲线名是FAST_OUT_SLOWIN(self):
        """⚠️ Flet 0.86 没有 FAST_OUT_SLOW_IN (Flutter 原名), 写错不报错也不生效"""
        anim = M.动画()
        self.assertIsNotNone(anim)
        self.assertEqual(anim.curve, ft.AnimationCurve.FAST_OUT_SLOWIN)
        self.assertFalse(hasattr(ft.AnimationCurve, 'FAST_OUT_SLOW_IN'),
                         '若此断言失败, 说明 Flet 版本变了, 需重核 ui_motion 文档')

    def test_动效开启默认True(self):
        with mock.patch.object(界面偏好, '取', side_effect=lambda k, d=None: d):
            self.assertTrue(M.动效开启())

    def test_动效关闭时动画返回None(self):
        with _关动效():
            self.assertIsNone(M.动画())
            self.assertIsNone(M.动画(M.MOTION_慢))


class _假页:
    """最小 page 替身: 捕获 run_task 的协程供测试驱动二阶段。"""

    def __init__(self):
        self.协程 = None
        self.更新次数 = 0

    def run_task(self, handler, *args, **kwargs):
        import asyncio
        self.协程 = handler(*args, **kwargs)   # 拿协程对象 (未 await)
        return None

    def update(self):
        self.更新次数 += 1

    def 跑完二阶段(self):
        import asyncio
        assert self.协程 is not None, '二阶段协程未注册'
        asyncio.run(self.协程)


class Test进场(unittest.TestCase):

    def test_二段式_起点与终点(self):
        """0.86 两段式: 先落起点, 协程里挂动画改终点 (2026-10-20 修复)"""
        c = ft.Container(content=ft.Text('x'))
        页 = _假页()
        self.assertTrue(M.进场(c, page=页))
        # ① 起点 (随调用方 update 刷出)
        self.assertEqual(c.opacity, 0.0)
        self.assertEqual(c.offset.y, M.MOTION_进场上移)
        # ② 跑二阶段: 挂动画 + 终点
        页.跑完二阶段()
        self.assertEqual(c.opacity, 1.0, '二阶段必须回到全不透明 (可见性)')
        self.assertEqual(c.offset.y, 0.0)

    def test_上线属性类型必须合法(self):
        """🔴 今日 bug 的护栏: animate_opacity/animate_offset 上线类型。

        0.86 的 AnimationValue = True | int 毫秒 | Animation —— 传 double 或
        Offset 对象会让客户端解析抛 NoSuchMethodError, 整个 patch 失败
        (2026-10-20 实测: 抽屉/日志面板空白 + 每秒客户端错误)。
        """
        c = ft.Container(content=ft.Text('x'))
        页 = _假页()
        M.进场(c, page=页)
        页.跑完二阶段()
        for 名 in ('animate_opacity', 'animate_offset'):
            值 = getattr(c, 名)
            self.assertIsInstance(值, ft.Animation,
                                 f'{名} 必须是 Animation 对象, 实得 {type(值).__name__}')
        self.assertEqual(c.animate_opacity.duration, M.MOTION_中)

    def test_时长可指定(self):
        c = ft.Container(content=ft.Text('x'))
        页 = _假页()
        M.进场(c, M.MOTION_慢, page=页)
        页.跑完二阶段()
        self.assertEqual(c.animate_opacity.duration, M.MOTION_慢)

    def test_无page时直显不隐形(self):
        """拿不到 page ⇒ 无法二段式 ⇒ 必须直显 (可见性优先于动效)"""
        c = ft.Container(content=ft.Text('x'))
        self.assertFalse(M.进场(c))
        self.assertEqual(c.opacity, 1.0, '无 page 必须保持可见')

    def test_动效关闭时不碰控件(self):
        """关掉动效 ⇒ 完全不设 opacity (保持原样), 硬切行为与改动前一致"""
        c = ft.Container(content=ft.Text('x'))
        with _关动效():
            self.assertFalse(M.进场(c, page=_假页()))
        self.assertEqual(c.opacity, 1.0)            # Container 默认全不透明

    def test_降级_控件完全不支持动画属性则保持可见(self):
        """🔴 硬约定: 动效失败绝不能让控件停在 opacity=0 (界面少一块)"""
        class _只认内容:
            # ⚠️ 必须带 __slots__ —— 否则动态赋值会静默成功, 走不到降级分支
            __slots__ = ('content', 'visible')

            def __init__(self):
                self.content = None
                self.visible = True

        坏 = _只认内容()
        self.assertFalse(M.进场(坏, page=_假页()))   # 设 opacity 即抛 AttributeError
        self.assertFalse(hasattr(坏, 'opacity'), '本测试桩不该有 opacity 属性')
        self.assertTrue(坏.visible, '控件仍应可见')

    def test_降级_一段失败即复位可见(self):
        """起点设置炸了 ⇒ 外层兜底把 opacity 拉回 1.0 (绝不隐形)"""
        class _offset炸:
            visible = True

            @property
            def offset(self):
                return None

            @offset.setter
            def offset(self, v):
                raise AttributeError('不支持 offset')

        控件 = _offset炸()
        self.assertFalse(M.进场(控件, page=_假页()))
        self.assertEqual(控件.opacity, 1.0, '失败路径必须把 opacity 复位成 1')

    def test_降级_二段失败也复位可见(self):
        """协程里挂动画炸了 ⇒ 协程内兜底同样把 opacity 拉回 1.0"""
        class _动画属性炸:
            visible = True

            def __init__(self):
                self.opacity = None
                self.offset = None

            @property
            def animate_opacity(self):
                return None

            @animate_opacity.setter
            def animate_opacity(self, v):
                raise AttributeError('不支持 animate_opacity')

        控件 = _动画属性炸()
        页 = _假页()
        M.进场(控件, page=页)
        页.跑完二阶段()                # 协程内抛错 → 兜底复位
        self.assertEqual(控件.opacity, 1.0, '二段失败也必须复位可见')

    def test_复位幂等(self):
        c = ft.Container(content=ft.Text('x'))
        M.进场(c)
        M.复位(c)
        M.复位(c)
        self.assertEqual(c.opacity, 1.0)

    def test_复位对无opacity控件不抛(self):
        class _裸:
            pass
        M.复位(_裸())          # 不抛即通过


class Test接线护栏(unittest.TestCase):

    def test_gui_app_页面切换走ui_motion(self):
        文本 = (_ROOT / '源码' / 'gui_app.py').read_text(encoding='utf-8')
        self.assertIn('from gui_components import ui_motion', 文本,
                      'gui_app 未导入 ui_motion')
        切页 = 文本.split('def _switch_page')[1][:900]
        self.assertIn('ui_motion.进场(', 切页,
                      '_switch_page 未挂进场动效')
        self.assertIn('ui_motion.复位(', 切页,
                      '_switch_page 隐藏旧页时未复位, 残留 opacity 会致页面不可见')

    def test_gui_app_页面切换未引入page_update(self):
        """项目硬约定: 禁 page.update(); 动效只改属性, 刷不刷由调用方决定"""
        文本 = (_ROOT / '源码' / 'gui_app.py').read_text(encoding='utf-8')
        切页 = 文本.split('def _switch_page')[1][:900]
        self.assertNotIn('page.update()', 切页,
                         '_switch_page 里不得出现 page.update()')

    def test_详情抽屉_视图切换走ui_motion(self):
        """右栏 detail↔preview 切换是第二处落点 (2026-10-14)"""
        文本 = (_ROOT / '源码' / 'gui_components' / 'detail_drawer.py').read_text(encoding='utf-8')
        self.assertIn('from . import ui_motion', 文本,
                      'detail_drawer 未导入 ui_motion')
        切换段 = 文本.split('self._view = view if')[1][:700]
        self.assertIn('ui_motion.进场(', 切换段,
                      '视图切换未挂进场动效')

    def test_详情抽屉_视图切换不做淡出(self):
        """两视图同在 Column 里, 淡出的那个仍占位 ⇒ 只允许淡入"""
        文本 = (_ROOT / '源码' / 'gui_components' / 'detail_drawer.py').read_text(encoding='utf-8')
        切换段 = 文本.split('self._view = view if')[1][:700]
        self.assertNotIn('animate_opacity', 切换段,
                         '视图切换不得手写 animate_opacity (会做成淡出)')

    def test_界面偏好_默认含动效键(self):
        self.assertIn('动效', 界面偏好._默认)
        self.assertTrue(界面偏好._默认['动效'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
