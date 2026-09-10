# -*- coding: utf-8 -*-
"""系统托盘 (pystray): 最小化到托盘后的恢复/彻底退出入口。

线程模型: pystray 在自己的线程跑消息循环; 回调只做事件转发 (由调用方经
page.run_task 回到 flet 主循环) — 与项目"跨线程只调度不碰控件"的纪律一致。
"""
import threading


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
    except Exception:
        pass
