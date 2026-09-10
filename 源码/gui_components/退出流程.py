# -*- coding: utf-8 -*-
"""应用退出流程 (可单测)。

## 为什么需要这个模块 (2026-09-10 实测结论, flet 0.86.5)

flet 桌面是**双进程**: Python 侧是 Flet 协议服务端, Flutter 客户端 `flet.exe`
是独立子进程。`flet/app.py` 的收尾顺序是:

    fvp, pid_file = await open_flet_view_async(...)
    await fvp.wait()             # 等客户端进程退出
    close_flet_view(pid_file)    # os.kill(pid, SIGKILL) 收尾

配合 `page.window.prevent_close = True`, 只有两条路可走 —— 而**单独用任何一条
都不完整**(三种方式均已用最小复现脚本实测, 见 文档/退出卡死定位与修复-2026-09-10.md):

| 退出方式 | Python 进程 | flet.exe 客户端 |
|---|---|---|
| `os._exit(0)` (旧实现) | 退出 | **残留孤儿窗口**: 界面还在、没有后端、关不掉 |
| `await page.window.destroy()` | **永久挂住** (`ft.run()` 不返回) | 正常回收 |
| destroy + 等待 + `os._exit` (本模块) | 退出 | 正常回收 |

`os._exit()` 不展开调用栈、不跑 finally/atexit, 所以 `close_flet_view()` 永不执行;
而单纯 destroy 之后 flet 的事件循环不返回。故必须两步都做。

## 顺序 (每步失败都不阻断后续 —— 退出必须能完成)

1. 停内嵌远控 (非阻塞)
2. 停托盘图标
3. 置位运行中任务的 stop_flag, 等 ≤等检查点秒 让爬虫写完检查点
4. 收尾钩子 (日志 close / 爬取历史 flush / 站点历史 flush / 风控事件 flush)
   —— 第 7 步不跑 atexit, 所以落盘必须在这里显式做掉
5. `await page.window.destroy()` —— 回收桌面客户端进程
6. 短暂等待, 给 flet 收尾留时间, 并输出结果摘要
7. 兜底强制结束 Python 进程
"""
import asyncio

等检查点秒 = 3.0      # 有运行中任务时, 最多等多久让它们写完检查点
等收尾秒 = 1.5        # destroy 之后给 flet 收尾 / 客户端退出留的时间 (实测足够)


async def 执行退出(page,
                   托盘对象=None,
                   停远控=None,
                   任务管理器=None,
                   收尾钩子=(),
                   等候秒=等收尾秒,
                   退出码=0,
                   休眠=None,
                   强制结束=None,
                   记录=None) -> dict:
    """按上述 7 步退出应用。

    正常情况下**不会返回** —— 第 7 步会结束进程。返回 dict 只服务于单测
    (测试注入 强制结束 拦截掉真正的进程终止)。

    Args:
        page: flet Page (需 page.window.destroy 可用)
        托盘对象: pystray Icon 或 None
        停远控: 无参可调用, 停内嵌远控服务 (须非阻塞)
        任务管理器: TaskManager, 用于取运行中任务并置位 stop_flag
        收尾钩子: 可迭代的无参可调用, 落盘/关闭资源用
        等候秒: destroy 之后的等待秒数
        退出码: 兜底结束时的进程退出码
        休眠: 协程函数, 默认 asyncio.sleep (测试注入以加速)
        强制结束: 单参可调用, 默认 os._exit (测试注入以拦截)
        记录: 单参日志回调, 默认丢弃
    """
    休眠 = 休眠 or asyncio.sleep
    强制结束 = 强制结束 or (lambda code: __import__("os")._exit(code))

    def _记(m):
        """日志回调容错: 收尾阶段日志句柄可能已被关闭"""
        if 记录 is None:
            return
        try:
            记录(m)
        except Exception:
            pass

    结果 = {"停远控": False, "停托盘": False, "运行中任务数": 0,
            "等检查点": False, "收尾钩子数": 0, "收尾钩子失败": 0,
            "销毁窗口": False, "强制结束": False}

    # 1. 停内嵌远控 (非阻塞: 只置 should_exit)
    if 停远控 is not None:
        try:
            停远控()
            结果["停远控"] = True
        except Exception as e:
            _记(f"停远控失败: {type(e).__name__}: {e}")

    # 2. 停托盘
    if 托盘对象 is not None:
        try:
            from gui_components.tray import 停止托盘
            停止托盘(托盘对象)
            结果["停托盘"] = True
        except Exception as e:
            _记(f"停托盘失败: {type(e).__name__}: {e}")

    # 3. 置位全部运行中任务的 stop_flag, 等一小段时间让爬虫写完检查点
    运行中 = []
    if 任务管理器 is not None:
        try:
            运行中 = [t for t in 任务管理器.get_all_tasks()
                      if getattr(t, "status", "") in ("running", "pending")]
            for t in 运行中:
                try:
                    t.stop_flag.set()
                except Exception as e:
                    _记(f"置位 stop_flag 失败: {type(e).__name__}: {e}")
        except Exception as e:
            _记(f"取任务列表失败: {type(e).__name__}: {e}")
    结果["运行中任务数"] = len(运行中)
    if 运行中:
        try:
            await 休眠(等检查点秒)
            结果["等检查点"] = True
        except Exception as e:
            _记(f"等待检查点失败: {type(e).__name__}: {e}")

    # 4. 收尾钩子: 必须显式落盘 —— 第 7 步不跑 atexit
    for 钩子 in 收尾钩子:
        try:
            钩子()
            结果["收尾钩子数"] += 1
        except Exception as e:
            结果["收尾钩子失败"] += 1
            _记(f"收尾钩子失败: {type(e).__name__}: {e}")

    # 5. 关键: 销毁窗口 → 桌面客户端进程正常退出
    #    (只用 os._exit 会让 flet.exe 变孤儿窗口; 只用 destroy 则 Python 挂住)
    try:
        await page.window.destroy()
        结果["销毁窗口"] = True
    except Exception as e:
        _记(f"销毁窗口失败: {type(e).__name__}: {e}")

    # 6. 给 flet 收尾 (fvp.wait → close_flet_view) 留时间
    try:
        await 休眠(等候秒)
    except Exception as e:
        _记(f"等待收尾失败: {type(e).__name__}: {e}")

    # 7. 兜底: ft.run() 在 destroy 后不返回, 必须强制结束 Python 进程
    _记(f"退出流程完成: {结果}")
    结果["强制结束"] = True
    强制结束(退出码)
    return 结果
