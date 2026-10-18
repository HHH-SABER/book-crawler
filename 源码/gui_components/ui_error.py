# -*- coding: utf-8 -*-
"""客户端界面错误诊断 (2026-10-18 灰页排查)。

**背景**: 内容区偶发整块 `#C4C4C4` —— 该色不是任何 Flet/Material 令牌,
按 Flutter 的 ErrorWidget(灰盒, 0xC0C0C0 约 94% 叠白 ≈ #C4C4C4)判定,
是**客户端建树抛错**(Flet 的 Flutter 侧 ErrorWidget), 而 Python 侧此前
**完全无感**: 日志里既无异常、窗口也 Responding=True。

Flet 0.86 的 `Page.on_error` 是客户端错误的**唯一可观测通道**。
本模块只做**纯逻辑**(不依赖 flet), 便于离线单测:

  界面错误文本(事件) → 规整成一行可落盘的诊断文本
  自愈提示(文本)     → 给用户看的一句话(含已记录 + 建议动作)

真实落盘/刷新动作留在 gui_app 的钩子里 (那里才有日志与 page)。
"""


def 界面错误文本(事件) -> str:
    """从 Flet 的 error 事件里取出可读诊断文本。

    优先级: 字符串事件 → `.data` → `.message` → 对象 `str()` 兜底。
    **只取到第一层有用信息就停**, 不把对象 repr 混进诊断文本
    (否则日志里会出现 `<... object at 0x...>`, 反而盖住真正的错误)。
    取不到任何有用信息时返回空串 (调用方自行决定兜底文案)。
    """
    if 事件 is None:
        return ''
    if isinstance(事件, str):
        return 事件.strip()[:2000]
    首选 = []
    for 名 in ('data', 'message'):
        try:
            值 = getattr(事件, 名, None)
        except Exception:       # noqa: BLE001 — 诊断代码自身绝不能抛
            continue
        if 值 is None:
            continue
        文本 = str(值).strip()
        if 文本 and 文本 not in 首选:
            首选.append(文本)
    if 首选:
        return ' | '.join(首选)[:2000]
    # 兜底只对**异常对象**取 str(); 普通事件对象没有 data/message 时
    # 返回空串 —— 往日志里写 `<... object at 0x...>` 是噪音, 反而盖住真错误。
    if not isinstance(事件, BaseException):
        return ''
    try:
        return str(事件).strip()[:2000]
    except Exception:           # noqa: BLE001 — 诊断代码自身绝不能抛
        return ''


def 自愈提示(文本: str = '') -> str:
    """给用户的界面错误提示 (显示在 SnackBar / 提示条里)。

    只说「已记录 + 下一步怎么做」, 不把原始异常栈丢给用户。
    """
    有文本 = bool((文本 or '').strip())
    尾巴 = '（详情已写入 日志/）' if 有文本 else ''
    return (f'界面渲染出错，已记录日志{尾巴}；'
            '若画面空白，先切一次左侧页面，仍不行请重启程序')
