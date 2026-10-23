# -*- coding: utf-8 -*-
"""关闭窗口行为: 最小化到托盘 / 直接退出 / 询问 (2026-10-24 S1 Wave1 从
gui_app.main() 整块搬出 —— 原内联 250 行, main() 只留一行调用)。

装什么: page.window.prevent_close + on_event → 按用户偏好 ("记住我的选择")
分发到 托盘/退出/询问弹窗。退出走 gui_components/退出流程.执行退出
(destroy → 等 flet 收尾 → 兜底强退), 顺序不可改。

冒烟脚本 测试/冒烟_关闭关键路径.py 以日志行为断言本模块, 改动需保持埋点。
"""
import os

import flet as ft

import 日志 as app_log
from _path_utils import get_state_root
from .ui_fluent import 提示条
from .ui_tokens import 取色

# 托盘对象由本模块托管 (gui_app._排空通知 经 取托盘对象() 读, 不跨模块摸字典)
_托盘 = {"对象": None}


def 取托盘对象():
    """当前托盘对象 (未建/已退出为 None) —— 给终态通知气泡用。"""
    return _托盘["对象"]


def 安装(page, task_manager) -> None:
    """把关闭行为装到 page。task_manager: 用于退出前检查运行中任务数。"""

    # ---- 关闭行为: 最小化到托盘 / 直接退出 (关闭按钮不再直接退出) ----
    _关闭配置 = os.path.join(get_state_root(), "数据", "客户端配置.json")

    def _读关闭行为():
        import json as _j
        try:
            with open(_关闭配置, "r", encoding="utf-8") as f:
                return _j.load(f).get("关闭行为", "询问")
        except Exception:
            return "询问"

    def _写关闭行为(v):
        import json as _j
        from pathlib import Path as _P
        try:
            fobj = _P(_关闭配置).resolve()
            fobj.parent.mkdir(parents=True, exist_ok=True)
            tmp = fobj.with_name(fobj.name + ".tmp")
            tmp.write_text(_j.dumps({"关闭行为": v}, ensure_ascii=False),
                           encoding="utf-8")
            os.replace(tmp, fobj)
        except OSError as _e:
            app_log.debug("GUI", f'裸 except 吞异常: {type(_e).__name__}: {_e}')

    async def _显示主窗():
        page.window.visible = True
        page.window.minimized = False
        try:
            page.update()
        except Exception as _e:
            app_log.debug("GUI", f'裸 except 吞异常: {type(_e).__name__}: {_e}')

    def _停远控服务():
        """停内嵌远控 (非阻塞: 只置 should_exit, 由 daemon 线程自行收尾)"""
        try:
            import 远控.服务 as _远控退
            _远控退.停止后台()
        except Exception as _e:
            app_log.info("退出", f"停远控失败: {type(_e).__name__}: {_e}")

    def _收尾落盘():
        """显式落盘 + 关日志。

        退出流程最后是 os._exit(), 不会触发 atexit —— 而这些模块平时靠 atexit
        兜底, 不在这里显式 flush 就会丢数据 (爬取历史/站点历史的防抖窗口内记录、
        风控事件的内存缓冲、日志尾部)。
        """
        try:
            import 爬取历史 as _ch
            _ch.取爬取历史().flush()
        except Exception as _e:
            app_log.info("退出", f"爬取历史 flush 失败: {type(_e).__name__}: {_e}")
        try:
            import 站点历史 as _sh
            _sh.取站点历史().flush()
        except Exception as _e:
            app_log.info("退出", f"站点历史 flush 失败: {type(_e).__name__}: {_e}")
        try:
            import 风控事件 as _fk
            _fk.flush()
        except Exception as _e:
            app_log.info("退出", f"风控事件 flush 失败: {type(_e).__name__}: {_e}")
        try:
            # 修复(U15b): 请求引擎单例的会话池此前无人 close。
            # os._exit 不跑 atexit, 所以必须在这里显式释放。
            from 请求引擎 import 获取引擎管理器
            获取引擎管理器().close()
        except Exception as _e:
            app_log.info("退出", f"引擎会话释放失败: {type(_e).__name__}: {_e}")
        try:
            app_log.close()
        except Exception:
            pass  # 刻意静默: try 块本身在写日志, 再加日志会递归 (日志链路兜底)

    async def _彻底退出():
        """**唯一**的退出出口 —— 步骤顺序不可改, 详见 gui_components/退出流程.py

        实测 (flet 0.86.5, 桌面是"Python + flet.exe"双进程):
          · 只用 os._exit(0): 跳过 flet 的 close_flet_view(), flet.exe 变孤儿窗口
            (界面还在、没有后端、点关闭没反应) = 用户报的"关不掉 / 界面卡死"
          · 只用 page.window.destroy(): 客户端正常回收, 但 ft.run() 不返回, Python 挂住
        故必须 destroy → 等 flet 收尾 → 兜底强退。
        """
        from gui_components.退出流程 import 执行退出
        # 埋点: 退出路径此前直到最后一步都零日志 —— 中途挂死时无迹可查
        # (冒烟脚本 S3 靠它区分 "关闭事件未送达" 与 "退出流程中途挂死")
        app_log.info("退出", "开始退出流程 (停远控→停托盘→任务检查点→落盘→销毁窗口)")
        await 执行退出(
            page,
            托盘对象=_托盘["对象"],
            停远控=_停远控服务,
            任务管理器=task_manager,
            收尾钩子=(_收尾落盘,),
            记录=lambda m: app_log.info("退出", m))

    def _隐藏到托盘():
        # 关键顺序: 先建托盘, 成功后才隐藏窗口 —— 托盘创建失败时窗口保持
        # 可见 (旧实现先隐藏再建托盘, 托盘失败即"窗口消失且无入口"=关不掉)
        if _托盘["对象"] is None:
            try:
                from gui_components.tray import 启动托盘
                图标路径 = os.path.normpath(os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), "..",
                    "脚本", "图标.ico"))
                _托盘["对象"] = 启动托盘(
                    图标路径,
                    显示=lambda: page.run_task(_显示主窗),
                    退出=lambda: page.run_task(_彻底退出))
                app_log.info("托盘", "已最小化到托盘 (远控保持运行; 双击图标恢复)")
                # 首次最小化给一条系统气泡: Windows 11 默认把新托盘图标收进
                # "^" 折叠区, 用户容易以为"托盘没出现/最小化失效"
                try:
                    _托盘["对象"].notify("已最小化到托盘，双击托盘图标恢复主窗口")
                except Exception as _e:
                    app_log.debug("GUI", f'裸 except 吞异常: {type(_e).__name__}: {_e}')
            except Exception as _e_tray:
                app_log.info("托盘", f"托盘不可用, 取消隐藏以保持可操作: {_e_tray}")
                try:
                    page.show_dialog(提示条("系统托盘不可用, 已取消关闭; 建议再点关闭并选直接退出"))
                except Exception as _e:
                    app_log.debug("GUI", f'裸 except 吞异常: {type(_e).__name__}: {_e}')
                return
        page.window.visible = False
        # 显式 update: window 属性变更须 update 才下发到客户端 (与 _显示主窗 对称)。
        # 旧实现缺这一句, "最小化到托盘"点击后窗口不隐藏 —— 托盘其实建好了,
        # 但用户视角就是"没反应/失效"
        try:
            page.update()
        except Exception as _e:
            app_log.debug("GUI", f'裸 except 吞异常: {type(_e).__name__}: {_e}')

    def _关闭询问():
        """关闭确认弹窗 (Fluent 风格)。

        交互设计:
          - 默认焦点在"最小化到托盘" (安全动作, Enter 直接触发; 直接退出必须显式点击);
          - "直接退出"用错误色 TextButton 弱化, 且离主按钮最远防误点;
          - 弹窗为 modal, 配显式"取消" —— 遮罩点击不再静默吞掉关闭意图;
          - 有运行中任务时展示警示条 (退出可断点续传), 帮用户做对选择;
          - "记住我的选择"整行可点 (Checkbox 无 label 参数, 文字用 GestureDetector 接管)。
        弹窗内全部文字显式设色: 打包环境下 dialog 文字样式缺 color 会渲染成不可见。
        """
        from gui_components.ui_fluent import (
            txt, SIZE_SMALL, SIZE_SUBTITLE, WEIGHT_SUBTITLE,
        )
        # 令牌色由 main() 作用域的 取色/登记重刷 提供 (Phase 3)

        记住 = ft.Checkbox(value=False)
        # 埋点: 冒烟脚本(测试/冒烟_关闭关键路径.py)以日志行为断言依据,
        # 同时给生产日志留运行痕迹 (v2.4.19 教训: 关键路径需要可观测性)
        app_log.info("关闭", "弹出关闭确认弹窗")

        def _弹层关闭():
            try:
                page.pop_dialog()
            except Exception as _e:
                app_log.debug("GUI", f'裸 except 吞异常: {type(_e).__name__}: {_e}')

        def _切换记住(e):
            记住.value = not 记住.value
            try:
                记住.update()
            except Exception as _e:
                app_log.debug("GUI", f'裸 except 吞异常: {type(_e).__name__}: {_e}')

        def _选托盘(e):
            _弹层关闭()
            if 记住.value:
                _写关闭行为("托盘")
            _隐藏到托盘()

        def _选退出(e):
            _弹层关闭()
            if 记住.value:
                _写关闭行为("退出")
            page.run_task(_彻底退出)

        def _取消(e):
            app_log.info("关闭", "用户取消关闭, 窗口保持")
            _弹层关闭()

        rows = [txt("要最小化到系统托盘（远控保持运行），还是直接退出？",
                    color=ft.Colors.ON_SURFACE)]
        # 运行中任务警示: 直接退出会中断抓取 (进度已存盘, 可断点续传)
        try:
            运行数 = sum(1 for _t in task_manager.tasks.values()
                        if _t.status == "running")
        except Exception:
            运行数 = 0
        if 运行数:
            rows.append(ft.Container(
                content=txt(f"⚠ 有 {运行数} 个任务正在运行，直接退出将中断抓取"
                            f"（已抓进度已保存，可断点续传）",
                            size=SIZE_SMALL, color=ft.Colors.ON_TERTIARY_CONTAINER),
                bgcolor=ft.Colors.TERTIARY_CONTAINER,
                border_radius=4,
                padding=ft.Padding(10, 8, 10, 8),
            ))
        rows.append(ft.Row(
            [记住,
             ft.GestureDetector(
                 content=txt("记住我的选择，以后不再询问", color=ft.Colors.ON_SURFACE),
                 on_tap=_切换记住)],
            spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER))

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                [ft.Icon(ft.Icons.LOGOUT, size=20, color=取色('text-secondary')),
                 txt("关闭窗口", size=SIZE_SUBTITLE, weight=WEIGHT_SUBTITLE,
                     color=ft.Colors.ON_SURFACE)],
                spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            content=ft.Container(
                content=ft.Column(rows, tight=True, spacing=12), width=430),
            actions=[
                ft.TextButton("直接退出", on_click=_选退出,
                              style=ft.ButtonStyle(color=取色('status-error'))),
                ft.TextButton("取消", on_click=_取消),
                ft.FilledButton("最小化到托盘", on_click=_选托盘, autofocus=True),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.show_dialog(dlg)

    def _处理关闭(e):
        try:
            if getattr(e, "type", None) == ft.WindowEventType.CLOSE:
                行为 = _读关闭行为()
                if 行为 == "托盘":
                    _隐藏到托盘()
                elif 行为 == "退出":
                    page.run_task(_彻底退出)
                else:
                    _关闭询问()
        except Exception as _e_cl:
            # 兜底降级 (v2.4.19 教训): 弹窗/配置处理自身异常时**不再直接退出** ——
            # 此前一个 import 错误就让"关闭"变成无确认强退。改为退到托盘:
            # 关闭意图仍被执行 (窗口消失), 应用可从托盘菜单退出, 完全可恢复。
            # 若托盘也建不成, _隐藏到托盘 会保持窗口可见, 不会"关不掉"。
            app_log.info("关闭", f"关闭处理异常, 降级为最小化到托盘: {_e_cl}")
            try:
                _隐藏到托盘()
            except Exception as _e_cl2:
                app_log.info("关闭", f"托盘降级也失败, 直接退出以免卡死: {_e_cl2}")
                page.run_task(_彻底退出)

    page.window.prevent_close = True
    page.window.on_event = _处理关闭
