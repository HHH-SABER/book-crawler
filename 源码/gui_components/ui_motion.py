# -*- coding: utf-8 -*-
"""ui_motion — 动效令牌与统一出口 (2026-10-14 新增)

======================================================================
一、为什么独立于 ui_tokens.py
======================================================================
ui_tokens 是**纯数据 + 取色** (其 docstring 明写"设计稿的唯一真值来源"),
不该引入 flet 运行时依赖; 而动效必须造 `ft.Animation`, 天然要 flet。
职责分开 ⇒ ui_tokens 保持零依赖可单测, 动效集中在一处便于统一节奏。

======================================================================
二、⚠️ Flet 0.86.5 动画 API 实测结论 (与旧文档/记忆不符, 改前必读)
======================================================================
  ✅ animate_opacity / animate_scale / animate_offset
     + animate=Animation(duration, curve)            ← 隐式动画, 可用
  ✅ AnimatedSwitcher(content, duration, transition=...)
  ✅ on_animation_end
  ⚠️ 曲线名是 **FAST_OUT_SLOWIN** —— Flutter 的 `FAST_OUT_SLOW_IN`
     在 0.86 **不存在**, 写错会静默不生效
  ❌ 以下均已不存在 (别再照着老教程写):
       Curves            → 改名 AnimationCurve
       ScaleTransition   → 改名 AnimatedSwitcherTransition
       AnimatedOpacity / AnimatedScale / AnimatedContainer / AnimatedPositioned
                         → 一律删掉, 改用基类上的 animate_* 属性

======================================================================
三、三条硬规矩 (写动效前先读)
======================================================================
1. **时长只用三档** (快/中/慢), 别随手写数字 —— 全应用节奏一致,
   才不会显得"有的地方快得跳、有的地方慢得拖"。
2. **动效开关必须一键降级**: `动画()` 在关掉偏好时返回 None, 调用方走
   无动效分支, 且**界面必须完全可用** —— 不允许"靠动画才显示出来"。
   例: 进场失败时把 opacity 复位成 1, 绝不能让控件停在不可见状态。
3. **先改数据、再挂动画**: 控件若随后被 `visible=False`, 淡出会残留在
   Stack 里挡住点击 —— 本项目页面切换只做"目标页淡入", 不做淡出。
"""
import flet as ft

# ---- 时长三档 (毫秒) ----
MOTION_快 = 120      # 按压 / hover 等即时反馈
MOTION_中 = 200      # 状态切换、页面进场
MOTION_慢 = 320      # 大块内容进场 (抽屉、空态、首次引导)

# ---- 幅度 (Flet 的 Offset 用**相对控件尺寸的比例**, 不是像素) ----
MOTION_进场上移 = 0.015    # 进场: 从下方 1.5% 处升上来 (克制, 不做大幅滑入)
MOTION_按压缩放 = 0.97     # 按压时缩到 97%

_曲线 = ft.AnimationCurve.FAST_OUT_SLOWIN
_起位 = ft.Offset(0, MOTION_进场上移)
_终位 = ft.Offset(0, 0)


def 动效开启() -> bool:
    """用户是否要动效 (界面偏好 `动效` 键, 默认开)。

    任何异常都回 True —— 读偏好失败不该让界面"没动效", 只该无声。
    """
    try:
        import 界面偏好
        return bool(界面偏好.取('动效', True))
    except Exception as e:
        _debug(f'动效偏好读取失败, 按开启处理: {type(e).__name__}')
        return True


def 动画(时长: int = MOTION_中):
    """统一出口: 造一个 ft.Animation。**关掉动效时返回 None**。

    调用方必须能处理 None (约定见模块 docstring 第三节第 2 条)。
    """
    if not 动效开启():
        return None
    return ft.Animation(duration=时长, curve=_曲线)


def 进场(控件, 时长: int = MOTION_中) -> bool:
    """给控件挂「淡入 + 轻微上移」进场动效 (原地改属性, **不触发 update**)。

    符合项目硬约定: 禁 page.update(), 由调用方决定刷不刷。

    返回 True=已挂上动效; False=未挂 (动效关闭 / 控件不支持)。
    False 时控件保证是**完全可见**的, 不会停在 opacity=0。
    """
    动 = 动画(时长)
    if 动 is None:
        return False
    try:
        控件.opacity = 0.0
        控件.offset = _起位
        控件.animate_opacity = 1.0
        控件.animate_offset = _终位
        控件.animate = 动
        return True
    except Exception as e:
        _debug(f'进场动效挂载失败, 已降级为直接可见: {type(e).__name__}')
        try:
            控件.opacity = 1.0        # 复位: 绝不让控件停在不可见状态
        except Exception as e2:
            # 复位也失败 ⇒ 控件可能停在 opacity=0, 必须留痕 (这是真事故)
            _debug(f'⚠️ 复位失败, 控件可能不可见: {type(e2).__name__}: {e2}')
        return False


def 复位(控件) -> None:
    """清掉残留的进场状态 (控件被复用/重新显示前调用)。

    只改 opacity —— offset 交给下一次 `进场` 覆盖, 避免这里手写
    Flet 内部默认值而踩版本差异。
    """
    try:
        控件.opacity = 1.0
    except Exception as e:
        _debug(f'动效复位失败 (可忽略): {type(e).__name__}')


def _debug(msg: str) -> None:
    """动效是纯装饰, 任何失败都只留日志, 绝不冒泡影响界面。"""
    try:
        import 日志 as _app_log
        _app_log.get('ui_motion').debug(msg)
    except Exception:
        pass    # 日志链路本身不可用时彻底静默 —— 装饰性功能不该留痕噪声
