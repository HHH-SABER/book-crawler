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
