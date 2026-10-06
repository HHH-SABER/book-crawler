# -*- coding: utf-8 -*-
"""日志"每行两遍"回归（2026-10-06 批 3 修复）。

## 事故
运行日志页每行**重复两遍**（设计稿是干净单行）。根因链：
```
日志._write → 落盘一次
           → console 镜像再 print 到 stdout
           → 任务线程的 stdout 是 TaskLogRedirector
           → 它把这一行 _log_to_file 再落盘一次   ⇒ 文件里每条两遍
```
证据：重复两行同毫秒时间戳、来源分别是 `[爬虫]`（原始 `_log.info`）与 `[任务task_N]`
（重定向器落盘）；该消息在 `爬虫.py` 里**只有 `_log.info`**（没有 `print`），
且 `run_crawl` 会调 `_app_log.enable_console()` —— 故只能是镜像导致。

## 修复
`日志` 增线程本地**镜像回调**：任务线程注册后，日志记录直接交给它（进任务日志），
**不再写 stdout** → 重定向器不会再二次落盘；裸 print 仍落盘（否则那些行会从文件里消失）。

## 判据为什么用替身而不是去数文件行
数文件行**跨用例不稳**：日志器是单例，文件句柄在首次写入时就绑定了当时的路径，
而有的用例会改写 `LOCALAPPDATA`（状态根）→ 全量门禁里"写入目录 ≠ 计数目录"，数出 0
（2026-10-06 实测踩到）。改成给 `_log_to_file` 装实例级替身，直接数"镜像是否被二次落盘"，
**确定性且不碰文件系统**。
"""
import io
import sys
import unittest

import _沙箱  # noqa: F401

import 日志 as L
from gui_components.task_manager import TaskLogRedirector, TaskInfo


class Test日志去重(unittest.TestCase):

    def setUp(self):
        self._原控制台 = L.is_console_enabled()
        self._原stdout = sys.stdout
        self.addCleanup(self._还原)
        L.enable_console()          # 镜像开启 = run_crawl 的真实状态

    def _还原(self):
        sys.stdout = self._原stdout
        L.注册镜像回调(None)
        L._console_enabled = self._原控制台     # 该模块没有 disable API, 直接复原标志

    def _造重定向器(self, tid: str):
        任务 = TaskInfo(task_id=tid, url=f'https://example.com/{tid}', title='测试书')
        重定向器 = TaskLogRedirector(任务, sys.__stdout__)
        落盘 = []
        重定向器._log_to_file = lambda s, _出=落盘: _出.append(s)   # 实例级替身
        return 任务, 重定向器, 落盘

    # ---------------------------------------------------------------- 机制
    def test_注册回调后不再写stdout(self):
        收到 = []
        L.注册镜像回调(lambda lvl, src, msg: 收到.append((lvl, src, msg)))
        缓冲 = io.StringIO()
        sys.stdout = 缓冲
        try:
            L.get('测试源').info('镜像回调-标记-A')
        finally:
            sys.stdout = self._原stdout
        self.assertEqual([m for _, _, m in 收到], ['镜像回调-标记-A'],
                         '注册回调后记录应交给回调')
        self.assertNotIn('镜像回调-标记-A', 缓冲.getvalue(),
                         '注册回调后不得再写 stdout (否则任务线程会二次落盘)')

    def test_任务线程镜像记录不再二次落盘(self):
        任务, 重定向器, 落盘 = self._造重定向器('t_去重')
        sys.stdout = 重定向器
        重定向器._注册镜像()
        try:
            L.get('爬虫').info('去重-标记-B')
        finally:
            重定向器._注销镜像()
            sys.stdout = self._原stdout
        self.assertEqual(落盘, [],
                         '镜像记录已被 日志._write 落过盘, 不得再落一次 —— 再落就是"每行两遍"')
        self.assertTrue(any('去重-标记-B' in x.get('msg', '') for x in 任务.logs),
                        '任务日志(界面用)仍应收到这一行 —— 修复不能以丢日志为代价')

    def test_裸print仍落盘(self):
        """裸 print 不经统一日志系统, 不落盘就会从文件里消失 —— 必须仍落盘。"""
        任务, 重定向器, 落盘 = self._造重定向器('t_裸print')
        sys.stdout = 重定向器
        try:
            重定向器.write('这是一条裸 print 的输出\n')
        finally:
            sys.stdout = self._原stdout
        self.assertEqual(落盘, ['这是一条裸 print 的输出'],
                         '裸 print 必须落盘 (否则日志文件会缺这些行)')

    # ---------------------------------------------------------------- 对照组
    def test_对照组_不注册回调时会二次落盘(self):
        """不注册回调 → 镜像走 stdout → 重定向器二次落盘。

        这条是**机制证据**: 它复现"每行两遍"的成因, 也说明本修复拦的正是它。
        """
        任务, 重定向器, 落盘 = self._造重定向器('t_对照')
        sys.stdout = 重定向器
        try:
            L.get('爬虫').info('对照-标记-C')       # 刻意**不**注册镜像回调
        finally:
            sys.stdout = self._原stdout
        self.assertEqual(落盘, ['对照-标记-C'],
                         '对照条件应发生"镜像→重定向器→二次落盘"; 若为空说明镜像未生效, 用例失去意义')


if __name__ == '__main__':
    unittest.main(verbosity=2)
