# -*- coding: utf-8 -*-
"""整页重刷器 (2026-11-10 v2.7.2: Flet 客户端残影自愈)。

背景
----
v2.7.1 把 1s 刷新循环改成「脏标记驱动、空闲零 patch」后, 卡顿修好了,
但暴露了一个**此前被每秒整页刷新顺带掩盖**的客户端问题: Flet 桌面客户端
在主题切换 / 窗口尺寸变化 / 弹层开关时可能只重绘局部, 旧帧像素留在未覆盖
区域 → 同一个窗口里出现两份界面、白色残块、遮罩只盖住一块矩形。
实机验证: 把窗口边框轻拖一下(强制 Flutter 重新布局)残影立刻消失,
说明是**重绘问题**, 不是数据错误, 也不是多开进程。

关键约束: 裸 page.update() 是空操作
----------------------------------
Flet 0.86 的 `Page.update()` → `Session.patch_control(page)` →
`ObjectPatch.from_diff(prev_control or control, control)`。没传 prev 时
src 与 dst 是**同一个对象**, 靠控件内部的 `__prev_*` 脏快照算差量;
若自上次 update 后一个属性都没改, patch 为 `[[0]]`, `Session` 只在
`len(patch) > 1` 时发消息 —— 也就是说「什么都没变时的 page.update()」
什么都不会发给客户端, 根本不会触发重绘。本项目实测确认过这一点。

因此每次整页重刷都先**制造一条视觉等价的真实属性变更**: 把
`page.opacity` 在 `1.0` 与 `0.999999` 之间来回切 (肉眼完全无差别)。
`opacity` 是 Page 自身的 Prop 字段, 赋值会登记 `_dirty`, 随后的
`page.update()` 实测会真的发出
`PATCH_CONTROL([[0], [Replace, 0, 'opacity', 0.999999]])` ——
整页根节点重绘, 残影被压平。
⚠️ 不要换成 `page.padding`: 它是普通 dataclass 字段 (非 Prop),
赋值不登记 `_dirty`, `page.update()` 仍然什么都不发。

对策
----
不恢复「每秒全树 diff」(那是卡顿主因), 只在两类时机发一次整页 patch:
  ① 结构性事件登记的请求 —— 由刷新循环在下一拍执行, 延迟 ≤1s;
  ② 低频心跳 (默认 20s) —— 兜底任何未知触发源。
相比旧实现 1 次/秒, 空闲期开销降低约 95%, 且保留自愈能力。

用法: gui_app.main() 建一个实例, 把 .请求 传给主题切换/窗口尺寸/切页/
关闭行为等路径, .服务() 由 _tick_loop 每拍调用一次。
"""
import time


class 整页重刷器:
    """把「需要整页重绘」排队, 由主刷新循环统一消费。"""

    def __init__(self, page, 心跳秒=20.0, 时钟=time.monotonic):
        self._page = page
        self.心跳秒 = float(心跳秒)
        self._时钟 = 时钟
        self.剩余 = 0
        self.上次 = 时钟()
        self._翻转 = False
        self._原opacity = getattr(page, 'opacity', 1.0)
        # 只有数值型 opacity 才能安全地切到「几乎相同」的值; 其它类型
        # 保持不动, 退化为普通 page.update() (不制造未知视觉变化)。
        self._可翻转 = (isinstance(self._原opacity, (int, float))
                       and not isinstance(self._原opacity, bool))

    def 请求(self, 次数=1):
        """登记一次或多次整页重绘 (取最大值, 防同一拍的多个事件无限叠加)。"""
        self.剩余 = max(self.剩余, int(次数))

    def _制造真实变更(self):
        """让随后的 page.update() 真的有 patch 可发 (见模块说明)。"""
        if not self._可翻转:
            return
        try:
            self._翻转 = not self._翻转
            self._page.opacity = (max(0.0, self._原opacity - 1e-6)
                                  if self._翻转 else self._原opacity)
        except Exception:
            self._可翻转 = False   # 类型/版本不兼容就退化, 不反复抛

    def 服务(self) -> bool:
        """刷新循环每拍调用一次; 返回本拍是否真的发了整页 patch。

        刻意吞掉 page.update() 的异常: 构建期/窗口销毁期调用会抛, 不能让
        1s 刷新循环因此中断; 同时无论如何都推进「上次」, 否则心跳会退化成
        每秒重试一次 (正好是我们要避免的)。
        """
        现在 = self._时钟()
        if self.剩余 <= 0 and (现在 - self.上次) < self.心跳秒:
            return False
        self.剩余 = max(0, self.剩余 - 1)
        self.上次 = 现在
        self._制造真实变更()
        try:
            self._page.update()
        except Exception:
            return False
        return True
