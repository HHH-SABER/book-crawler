# -*- coding: utf-8 -*-
"""系统托盘 (pystray): 最小化到托盘后的恢复/彻底退出入口。

线程模型: pystray 在自己的线程跑消息循环; 回调只做事件转发 (由调用方经
page.run_task 回到 flet 主循环) — 与项目"跨线程只调度不碰控件"的纪律一致。
"""
import threading
try:
    import 日志 as _app_log          # 批2B: 统一留痕通道 (容错导入, 同 input_bar 桥模式)
except Exception:
    _app_log = None


def _dbg(source: str, message: str):
    """裸 except 吞异常留痕 (DEBUG 级: 只落盘不 console 镜像, 避免刷屏)"""
    if _app_log is not None:
        try:
            _app_log.debug(source, message)
        except Exception:
            pass  # 刻意静默: try 块本身在写日志, 再加日志会递归 (日志链路兜底)



def 启动托盘(图标路径: str, 显示, 退出):
    """创建并启动托盘图标; 返回 pystray.Icon 实例。

    参数:
        图标路径: .ico 文件; 加载失败用纯色占位
        显示 / 退出: 无参回调 (调用方负责调度回 UI 线程)
    """
    import pystray
    from PIL import Image
    try:
        img = Image.open(图标路径)
    except Exception:
        img = Image.new("RGBA", (64, 64), (76, 194, 255, 255))
    menu = pystray.Menu(
        pystray.MenuItem("显示主窗口", lambda *_: 显示(), default=True),
        pystray.MenuItem("退出", lambda *_: 退出()),
    )
    icon = pystray.Icon("小说爬虫", img, "小说爬虫 (远控常驻中)", menu)
    threading.Thread(target=icon.run, name="托盘", daemon=True).start()
    return icon


def 停止托盘(icon) -> None:
    """幂等移除托盘图标"""
    try:
        if icon is not None:
            icon.stop()
    except Exception as _e:
        _dbg("托盘", f'裸 except 吞异常: {type(_e).__name__}: {_e}')


# ---- 任务终态系统气泡 (2026-10-09) ----
# 窗口最小化/隐藏到托盘时应用内 SnackBar 不可见, 终态通知改走 pystray
# 系统气泡 (icon.notify)。纯文案聚合在此模块, 便于离线单测 (不依赖 flet/pystray)。


def 终态气泡文本(items: list) -> str:
    """把终态通知列表聚合为一条气泡文案。

    - 单条: 与应用内 SnackBar 同文案 (成功"抓取完成: 《书名》" / 失败附原因)
    - 多条: 成功/失败各一行计数 + 书名 (超 3 本折叠为"等", 气泡空间有限)
    """
    ok = [i for i in items if i.get('状态') == 'success']
    fail = [i for i in items if i.get('状态') != 'success']
    if not ok and not fail:
        return ""
    if len(items) == 1:
        n = items[0]
        if ok:
            return f"抓取完成: 《{n.get('书名', '')}》"
        行 = f"抓取失败: 《{n.get('书名', '')}》"
        原因 = (n.get('原因') or '').strip()
        if 原因:
            行 += f"\n{原因}"
        return 行

    def _名单(seq):
        s = "、".join(f"《{i.get('书名', '')}》" for i in seq[:3])
        return s + ("等" if len(seq) > 3 else "")

    行s = []
    if ok:
        行s.append(f"抓取完成 {len(ok)} 本: {_名单(ok)}")
    if fail:
        行s.append(f"抓取失败 {len(fail)} 本: {_名单(fail)}")
    return "\n".join(行s)


def 发终态气泡(icon, items: list) -> bool:
    """经 pystray 图标发系统气泡; 成功返回 True。

    icon 为 None / 列表为空 / notify 不支持或异常 → False
    (调用方回退 SnackBar, 保证恢复窗口后信息仍可见)。
    线程模型: notify 由 GUI 主线程调用, 与 _隐藏到托盘 既有 notify 用法一致。
    """
    if icon is None or not items:
        return False
    文本 = 终态气泡文本(items)
    if not 文本:
        return False
    try:
        icon.notify(文本, "小说爬虫")
        return True
    except Exception as _e:
        _dbg("托盘", f"终态气泡发送失败: {type(_e).__name__}: {_e}")
        return False
