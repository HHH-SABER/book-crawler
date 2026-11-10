# -*- coding: utf-8 -*-
"""漫画任务执行器（统一内容库改造 D/6，2026-11-10）。

把纯 CLI 的 `漫画抓取` / `漫画导出` 接进 TaskManager 的**最小闭环**：
任务行、进度（话）、标题、停止、日志进统一管道、终态通知。

刻意不做（本轮范围外）：死书判定、EPUB、书架/历史对齐、预览。
死书清单与网站清单是小说语义，漫画成功/失败都不写它们（见
task_manager._收尾成功 / _记死书 的品类早退）。

日志走 print：_run_task 已把本线程 stdout 注册到 TaskLogRedirector，
故 print 会同时进任务日志面板与应用日志，与小说链路完全一致。
"""
from pathlib import Path


def 执行(管理器, task, 参数: dict) -> None:
    """执行一次漫画任务。由 品类执行器.执行 惰性调用。"""
    import 漫画抓取
    import 漫画导出
    import _path_utils
    from gui_components import task_manager as _tm

    url = task.url
    日志 = lambda 消息: print(消息, flush=True)   # noqa: E731  (统一日志管道)

    # 输出根走路径契约：用户填的相对目录按 BASE_DIR 解析；缺省 抓取结果/漫画
    用户目录 = (参数.get('输出目录') or '').strip()
    if 用户目录:
        输出根 = Path(_path_utils.resolve_output_dir(用户目录))
    else:
        输出根 = Path(_path_utils.get_default_output_dir()) / '漫画'

    # 同域闸门：与小说一致，同站最多 1 个任务在抓，排队可被停止打断
    闸门 = _tm._取域闸门(url)
    已获闸 = _tm._获取域闸门(闸门, task.stop_flag,
                            占用提示=lambda: _tm._排队提示(task))
    if not 已获闸:
        return    # 排队中被停止，stop_task 已置终态

    task.status = 'running'
    try:
        日志(f'[漫画] 开始: {url} → {输出根}')

        def 标题回调(书名):
            task.title = 书名

        统计 = 漫画抓取.抓整本(
            url, 输出根,
            章范围=task.chapter_range,
            间隔=0.35,
            日志=日志,
            停止事件=task.stop_flag,
            标题回调=标题回调,
        )
        task.output_file = 统计['目录']
        task.progress_total = 统计['章节数']

        if 统计.get('已停止'):
            日志(f"[漫画] 已停止，保留已下载内容: {统计['目录']}")
            管理器._set_terminal(task, 'stopped')
            return

        task.progress_current = 统计['章节数']

        # 导出：与 CLI 共用同一实现（pages / cbz / pdf × 卷 / 话）
        品类参数 = getattr(task, '品类参数', None) or {}
        格式 = 品类参数.get('导出格式') or 'pages'
        源 = Path(统计['目录'])
        if 格式 in ('cbz', 'pdf'):
            卷界文本 = str(品类参数.get('卷界') or '').strip()
            if 卷界文本:
                话数 = len(漫画导出.找话目录(源))
                卷界 = 漫画导出.解析卷界(卷界文本, 话数)
                结果 = 漫画导出.导出(源, 格式=格式, 单位='卷', 卷界=卷界)
            else:
                结果 = 漫画导出.导出(源, 源, 格式=格式, 单位='话',
                                    写索引=False)
            日志(f"[导出] {格式.upper()} {len(结果['册s'])} 个 → "
                 f"{结果['输出目录']}")
            task.output_file = 结果['输出目录']

        日志(f"抓取完成，共{统计['章节数']}话 / {统计['总页数']}页 "
             f"(新下 {统计['新下载']}, 跳过 {统计['跳过']})")
        管理器._set_terminal(task, 'completed')
    finally:
        if 闸门 is not None:
            闸门.release()
