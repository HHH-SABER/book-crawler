# -*- coding: utf-8 -*-
"""多任务管理器：管理并行爬虫任务，每个任务在独立线程运行

通过重定向 print 到任务日志实现进度跟踪，通过正则解析进度信息。
"""
import threading
import dataclasses
import sys
import time
import re
import os
import contextvars
from typing import Optional

# 统一日志模块 (位于上级目录 源码/)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import 日志 as app_log
except Exception:
    app_log = None


@dataclasses.dataclass
class TaskMetrics:
    """任务运行时指标 (由爬虫结构化日志解析回填, 见 TaskLogRedirector)"""
    engine: str = "requests"      # 当前引擎: 默认 requests; 反爬降级后为 cloudscraper/curl_cffi
    anti_spider_type: str = ""    # 最近命中的反爬类型: js_challenge/rate_limit/...
    quality_score: float = -1.0   # 最近一次内容质检得分 0-100 (-1=尚未质检)
    quality_passed: bool = False  # 最近一次质检是否通过
    incremental_skipped: int = 0  # 增量模式累计跳过章节数
    engine_fallback_chain: list = dataclasses.field(default_factory=list)  # 引擎降级尝试记录
    start_time: float = 0.0       # 任务启动时间戳 (计算耗时用)
    end_time: float = 0.0         # 任务结束时间戳 (完成后冻结耗时; 0=仍在运行)


@dataclasses.dataclass
class TaskInfo:
    """单个爬虫任务的状态信息"""
    task_id: str
    url: str
    title: str = "未知"
    mode: str = "full"
    progress_current: int = 0
    progress_total: int = 0
    status: str = "pending"  # pending/running/completed/failed
    logs: list = dataclasses.field(default_factory=list)
    output_file: str = ""
    error: str = ""
    thread: Optional[threading.Thread] = None
    stop_flag: threading.Event = dataclasses.field(default_factory=threading.Event)
    # 创建参数 (供"重新下载"复用)
    chapter_range: tuple = None
    threads: int = None    # None = 速度自适应 (程序自动选档)
    delay: float = None
    resume: bool = True
    output_dir: str = None
    export_epub: bool = False   # 抓取完成后是否同时导出 EPUB
    incremental: bool = False   # 增量抓取 (跳过已抓取且未变化的章节, 一键更新用)
    # 运行时指标 (GUI 表格列数据源)
    metrics: TaskMetrics = dataclasses.field(default_factory=TaskMetrics)
    selected: bool = False  # 当前是否被选中 (供抽屉/表格高亮)


class TaskLogRedirector:
    """将 print 输出重定向到指定任务的日志列表

    每个任务线程独立持有此对象，替换 sys.stdout，实现日志隔离。
    同时保留原始 stdout 输出，方便调试。
    """

    def __init__(self, task_info: TaskInfo, original_stdout):
        self.task = task_info
        self.original = original_stdout

    def _log_to_file(self, line: str):
        """将日志行同步落盘 (统一日志系统), 失败不影响主流程"""
        if app_log is None:
            return
        try:
            app_log.info(f"任务{self.task.task_id}", line)
        except Exception:
            pass

    def write(self, text):
        if text.strip():
            timestamp = time.strftime('%H:%M:%S')
            for line in text.strip().split('\n'):
                if line.strip():
                    self._log_to_file(line.strip())
                    self.task.logs.append({
                        'time': timestamp,
                        'msg': line.strip()
                    })
                    # 从日志中解析进度: "正在抓取第 X/Y 章" 或 "X/Y (Z%)"
                    self._parse_progress(line.strip())
                    # 解析小说名称: "提取到小说名称: XXX"
                    m = re.search(r'提取到小说名称:\s*(.+)', line.strip())
                    if m:
                        self.task.title = m.group(1).strip()
                    # 解析完成: "抓取完成，共X章"
                    m = re.search(r'抓取完成.*共(\d+)章', line.strip())
                    if m:
                        self.task.progress_current = self.task.progress_total
                        self.task.status = "completed"
                        if self.task.metrics:
                            self.task.metrics.end_time = time.time()
                        # 质检列兜底回填 (修复质检列空白): 逐行解析可能漏检,
                        # 完成时从 站点历史.json 取该书最近质检摘要回填
                        self._backfill_quality(self.task)
            # 保留最近500条日志
            if len(self.task.logs) > 500:
                self.task.logs = self.task.logs[-500:]
        # 同时输出到控制台（调试用）
        try:
            self.original.write(text)
        except Exception:
            pass

    def flush(self):
        try:
            self.original.flush()
        except Exception:
            pass

    def _parse_progress(self, line: str):
        """从日志行中解析进度信息"""
        # 匹配 "正在抓取第 X/Y 章"
        m = re.search(r'正在抓取第\s+(\d+)/(\d+)\s+章', line)
        if m:
            self.task.progress_current = int(m.group(1))
            self.task.progress_total = int(m.group(2))
            return
        # 匹配进度条 "X/Y (Z%)"
        m = re.search(r'(\d+)/(\d+)\s*\((\d+(?:\.\d+)?)%\)', line)
        if m:
            self.task.progress_current = int(m.group(1))
            self.task.progress_total = int(m.group(2))
            return
        # 匹配 "共找到 X 个章节"
        m = re.search(r'共(?:找到|提取)\s*(\d+)\s*(?:个)?章节', line)
        if m:
            self.task.progress_total = int(m.group(1))
            return
        # 匹配输出文件路径
        m = re.search(r'已保存至(.+\.txt)', line)
        if m:
            self.task.output_file = m.group(1).strip()
        # ---- 运行时指标解析 (引擎/反爬/质检/增量) ----
        self._parse_metrics(line)

    def _parse_metrics(self, line: str):
        """从爬虫结构化日志行解析运行时指标 (与 _parse_progress 同级, 只改数据不动 UI)

        已知日志格式 (爬虫.py / 请求引擎.py / 内容质检器.py 输出):
          [反爬] ✅ {引擎} 引擎请求成功 ...      → 当前引擎
          [反爬] ⚠️ {引擎} 引擎请求失败 ...      → 降级链追加
          [引擎] {引擎} 请求异常: ...            → 降级链追加
          [反爬] 命中 {机制}, ...                → 反爬类型
          [反爬] 频率限制, 退避 ...              → 反爬类型 rate_limit
          [反爬检测] 命中 WAF 图片验证码页 / WAF JS 挑战页 → 反爬类型
          [反爬检测] 检测到JS cookie校验页面     → 反爬类型 js_cookie
          [质检] {章节} 得分{分} 通过/失败(...)  → 质检得分
          [增量] 跳过第 X/Y 章 (未变化)          → 增量跳过计数
        """
        mt = self.task.metrics

        # 引擎: 成功
        m = re.search(r'\[反爬\]\s*✅\s*(\S+)\s*引擎请求成功', line)
        if m:
            mt.engine = m.group(1)
            return
        # 引擎: 失败/异常 → 降级链
        m = re.search(r'\[反爬\]\s*⚠️\s*(\S+)\s*引擎请求失败', line)
        if m and m.group(1) not in mt.engine_fallback_chain:
            mt.engine_fallback_chain.append(m.group(1))
            return
        m = re.search(r'\[引擎\]\s*(\S+)\s*请求异常', line)
        if m and m.group(1) not in mt.engine_fallback_chain:
            mt.engine_fallback_chain.append(m.group(1))
            return

        # 反爬类型
        if '[反爬] 频率限制' in line:
            mt.anti_spider_type = 'rate_limit'
            return
        m = re.search(r'\[反爬\]\s*命中\s*(\S+?),', line)
        if m:
            mt.anti_spider_type = m.group(1)
            return
        if '[反爬检测] 命中 WAF 图片验证码页' in line:
            mt.anti_spider_type = 'waf_captcha'
            return
        if '[反爬检测] 命中 WAF JS 挑战页' in line:
            mt.anti_spider_type = 'waf_js_challenge'
            return
        if '检测到JS cookie校验页面' in line or '命中JS cookie校验' in line:
            mt.anti_spider_type = 'js_cookie'
            return

        # 质检得分: "[质检] {章节} 得分{分} 通过" / "得分{分} 失败(...)"
        # (容错: "得分 92" 允许冒号后带空格)
        m = re.search(r'\[质检\].*?得分\s*(\d+(?:\.\d+)?)\s*(通过|失败)', line)
        if m:
            mt.quality_score = float(m.group(1))
            mt.quality_passed = (m.group(2) == '通过')
            return

        # 增量跳过
        if '[增量] 跳过第' in line:
            mt.incremental_skipped += 1
            return

    def _backfill_quality(self, task):
        """任务完成时, 从 站点历史.json 回填质检得分 (逐行解析的可靠兜底)。

        数据源: 数据/站点历史.json → {域名: {书籍: [{质检摘要: {平均分,通过,未通过}}]}}
        逐行已解析到得分时不覆盖。
        """
        try:
            mt = task.metrics
            if mt is None or mt.quality_score >= 0:
                return
            import re as _re
            from pathlib import Path as _Path
            # 数据源候选 (按优先级): 程序统一解析 → 项目根/数据/ → 项目根/
            _hist = None
            _cands = []
            try:
                import _path_utils
                _cands.append(_Path(_path_utils.resolve_data_file('站点历史.json')))
            except Exception:
                pass
            _root = _Path(__file__).resolve().parents[2]
            _cands.append(_root / '数据' / '站点历史.json')
            _cands.append(_root / '站点历史.json')
            for _c in _cands:
                if _c.is_file():
                    _hist = _c
                    break
            if _hist is None:
                return
            m = _re.match(r'https?://([^/:]+)', task.url or '')
            if not m:
                return
            domain = m.group(1).lower()
            if domain.startswith('www.'):
                domain = domain[4:]
            import json as _json
            d = _json.loads(_hist.read_text(encoding='utf-8'))
            rec = d.get(domain)
            if not rec or not rec.get('书籍'):
                return
            摘要 = rec['书籍'][-1].get('质检摘要') or {}
            平均分 = 摘要.get('平均分')
            if 平均分 is None:
                return
            mt.quality_score = float(平均分)
            mt.quality_passed = (摘要.get('通过', 0) >= 摘要.get('未通过', 0))
        except Exception:
            pass


# 任务 writer 的 contextvar: register() 时写入, worker 线程经 copy_context 继承
_WRITER_CTX = contextvars.ContextVar('_task_stdout_writer', default=None)


class _ThreadAwareStdout:
    """线程感知的 stdout 调度器（多任务日志隔离）

    背景: 全局 sys.stdout 被多线程并发替换会产生竞态——
    后启动的线程会覆盖前一个线程设置的 stdout, 导致多个任务的
    print 输出全部灌入最后一个任务, 标题/进度/日志互相串。
    方案: 用单一调度器替代 sys.stdout, 按"当前线程ID"分发到
    各线程注册的 writer, 实现真正的日志隔离。

    并行抓取的 worker 线程 (ThreadPoolExecutor) 不会单独注册,
    通过 contextvars 把任务 writer 随 copy_context() 传播给 worker
    (爬虫.py 提交任务时用 copy_context().run 包裹), 使质检/引擎等
    worker 内日志也能被 _parse_metrics 解析回填。
    """

    def __init__(self):
        self._default = sys.__stdout__
        self._lock = threading.Lock()
        self._writers = {}  # thread_id -> writer

    def register(self, writer):
        """当前线程注册日志 writer (爬虫线程启动时调用)"""
        with self._lock:
            self._writers[threading.get_ident()] = writer
        # 同步写入 contextvars, 供 ThreadPoolExecutor worker 经 copy_context 继承
        try:
            _WRITER_CTX.set(writer)
        except Exception:
            pass

    def unregister(self):
        """当前线程注销 writer (爬虫线程结束时调用)"""
        with self._lock:
            self._writers.pop(threading.get_ident(), None)
        try:
            _WRITER_CTX.set(None)
        except Exception:
            pass

    def _get_writer(self):
        with self._lock:
            w = self._writers.get(threading.get_ident())
        if w is not None:
            return w
        # 兜底: worker 线程无独立注册, 取上下文中的任务 writer
        try:
            w = _WRITER_CTX.get()
        except Exception:
            w = None
        return w

    def write(self, text):
        w = self._get_writer()
        if w is not None:
            try:
                w.write(text)
            except Exception:
                pass
        else:
            try:
                self._default.write(text)
            except Exception:
                pass

    def flush(self):
        w = self._get_writer()
        if w is not None:
            try:
                w.flush()
            except Exception:
                pass
        else:
            try:
                self._default.flush()
            except Exception:
                pass

    # 兼容: 部分库会访问这些属性
    def isatty(self):
        return False

    @property
    def encoding(self):
        return getattr(self._default, 'encoding', 'utf-8')


# 模块级单例: 首次导入即替换全局 stdout (幂等, 重复导入不重复替换)
_THREAD_STDOUT = _ThreadAwareStdout()
if not isinstance(sys.stdout, _ThreadAwareStdout):
    sys.stdout = _THREAD_STDOUT


class TaskManager:
    """多任务管理器：创建、停止、查询爬虫任务"""

    def __init__(self, page):
        self.page = page  # Flet Page 实例，用于触发UI更新
        self.tasks: dict[str, TaskInfo] = {}
        self._lock = threading.Lock()
        self._counter = 0
        self._selected_task_id: str = ""       # 当前选中任务 (表格高亮/抽屉联动)
        self._selected_callbacks: list = []    # 选中变化订阅者 (主线程调用)

    # ------------------------------------------------------------ 选中联动
    def on_selected_change(self, callback):
        """订阅选中任务变化 (回调签名: callback(task_id: str), 空串=取消选中)"""
        self._selected_callbacks.append(callback)

    def select_task(self, task_id: str):
        """选中/取消选中任务 (切换到新任务时触发回调, 线程安全)"""
        with self._lock:
            old = self._selected_task_id
            if task_id == old:
                return
            for t in self.tasks.values():
                t.selected = (t.task_id == task_id)
            self._selected_task_id = task_id
        for cb in self._selected_callbacks:
            try:
                cb(task_id)
            except Exception:
                pass

    @property
    def selected_task_id(self) -> str:
        """当前选中任务 ID (空串=无选中)"""
        return self._selected_task_id

    # ------------------------------------------------------------ 指标更新
    def update_metrics(self, task_id: str, **fields):
        """外部直接更新任务指标字段 (仅改数据不动 UI, 线程安全)

        可用字段: engine / anti_spider_type / quality_score / quality_passed /
                  incremental_skipped / engine_fallback_chain
        """
        with self._lock:
            task = self.tasks.get(task_id)
            if task is None:
                return
            for k, v in fields.items():
                if hasattr(task.metrics, k):
                    setattr(task.metrics, k, v)

    def create_task(self, url: str, mode: str = "full",
                    chapter_range: tuple = None, threads: int = None,
                    delay: float = None, resume: bool = True,
                    output_dir: str = None, export_epub: bool = False,
                    incremental: bool = False, unique_title: bool = True) -> str:
        """创建并启动一个新爬虫任务，返回 task_id

        threads/delay 为 None (默认) 时由速度自适应模块自动选档。
        incremental=True 时启用增量抓取 (一键更新书架用, 建议 unique_title=False
        以续写原文件而非另存带序号的新文件)。
        """
        with self._lock:
            self._counter += 1
            task_id = f"task_{self._counter}"

        task = TaskInfo(
            task_id=task_id,
            url=url,
            mode=mode,
            status="running",
            chapter_range=chapter_range,
            threads=threads,
            delay=delay,
            resume=resume,
            output_dir=output_dir,
            export_epub=export_epub,
            incremental=incremental,
        )
        task.metrics.start_time = time.time()
        with self._lock:
            self.tasks[task_id] = task

        # 启动子线程执行抓取
        t = threading.Thread(
            target=self._run_task,
            args=(task, url, mode, chapter_range, threads, delay, resume, output_dir,
                  unique_title, incremental),
            daemon=True
        )
        task.thread = t
        t.start()
        return task_id

    def create_batch_task(self, urls: list, threads: int = None,
                          delay: float = None, resume: bool = True,
                          output_dir: str = None, export_epub: bool = False) -> str:
        """创建并启动一个批量任务 (一次抓取多本书), 返回 task_id

        内部调用 run_batch: 书级并行 (None=自适应) + 同域限流保护 + 汇总报告。
        """
        with self._lock:
            self._counter += 1
            task_id = f"task_{self._counter}"

        task = TaskInfo(
            task_id=task_id,
            url=f"[批量] {len(urls)} 本书",
            title=f"批量{len(urls)}本",
            mode="batch",
            status="running",
            export_epub=export_epub,
        )
        task.metrics.start_time = time.time()
        with self._lock:
            self.tasks[task_id] = task

        # 启动子线程执行批量抓取
        t = threading.Thread(
            target=self._run_batch_task,
            args=(task, urls, threads, delay, resume, output_dir, export_epub),
            daemon=True
        )
        task.thread = t
        t.start()
        return task_id

    @staticmethod
    def _set_terminal(task: TaskInfo, status: str):
        """置为终态 (completed/failed/stopped) 并冻结耗时 end_time"""
        task.status = status
        if task.metrics:
            task.metrics.end_time = time.time()

    def _run_batch_task(self, task: TaskInfo, urls: list, threads: int,
                        delay: float, resume: bool, output_dir: str,
                        export_epub: bool = False):
        """在子线程中执行 run_batch，重定向 print 到任务日志"""
        # 注册到线程感知 stdout 调度器 (不再直接替换全局 sys.stdout, 避免多任务互踩)
        _THREAD_STDOUT.register(TaskLogRedirector(task, sys.__stdout__))
        try:
            # 动态导入爬虫模块（避免在GUI启动时加载selenium等重依赖）
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from 爬虫 import run_batch

            if app_log is not None:
                app_log.info(f"任务{task.task_id}", f"批量任务启动: {len(urls)} 个网址")
            run_batch(
                url_list=urls,
                threads=threads,
                sort_chapters=True,
                resume=resume,
                show_progress=True,
                output_dir=output_dir,
                delay=delay,
                stop_event=task.stop_flag,
                unique_title=True,
                export_epub=export_epub,
            )
            # 如果状态还是running且没有标记completed，标记为completed
            if task.status == "running":
                self._set_terminal(task, "completed")
        except Exception as e:
            self._set_terminal(task, "failed")
            task.error = str(e)
            task.logs.append({
                'time': time.strftime('%H:%M:%S'),
                'msg': f"[错误] {e}"
            })
            if app_log is not None:
                app_log.error_exc(f"任务{task.task_id}", f"批量任务异常: {e}", e)
        finally:
            _THREAD_STDOUT.unregister()

    def _run_task(self, task: TaskInfo, url: str, mode: str,
                  chapter_range: tuple, threads: int, delay: float,
                  resume: bool, output_dir: str, unique_title: bool = False,
                  incremental: bool = False):
        """在子线程中执行 run_crawl，重定向 print 到任务日志"""
        # 注册到线程感知 stdout 调度器 (不再直接替换全局 sys.stdout, 避免多任务互踩)
        _THREAD_STDOUT.register(TaskLogRedirector(task, sys.__stdout__))
        try:
            # 动态导入爬虫模块（避免在GUI启动时加载selenium等重依赖）
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from 爬虫 import run_crawl

            if app_log is not None:
                app_log.info(f"任务{task.task_id}",
                             f"任务启动: {url} 模式={mode} 线程={threads} 延迟={delay} 续传={resume}"
                             + (" 增量=开" if incremental else ""))
            run_crawl(
                catalog_url=url,
                mode=mode,
                sort_chapters=True,
                output_dir=output_dir,
                resume=resume,
                show_progress=True,
                chapter_range=chapter_range,
                threads=threads,
                delay=delay,
                stop_event=task.stop_flag,
                unique_title=unique_title,
                export_epub=task.export_epub,
                incremental=incremental or task.incremental,
            )
            # 如果状态还是running且没有标记completed，标记为completed
            if task.status == "running":
                self._set_terminal(task, "completed")
        except Exception as e:
            self._set_terminal(task, "failed")
            task.error = str(e)
            task.logs.append({
                'time': time.strftime('%H:%M:%S'),
                'msg': f"[错误] {e}"
            })
            if app_log is not None:
                app_log.error_exc(f"任务{task.task_id}", f"任务异常: {e}", e)
        finally:
            _THREAD_STDOUT.unregister()

    def stop_task(self, task_id: str):
        """停止指定任务（通过设置停止标志，爬虫循环检查后退出）"""
        with self._lock:
            task = self.tasks.get(task_id)
            if task:
                task.stop_flag.set()
                self._set_terminal(task, "stopped")
                task.logs.append({
                    'time': time.strftime('%H:%M:%S'),
                    'msg': "[用户停止] 任务已被用户手动停止"
                })
        if app_log is not None:
            app_log.info(f"任务{task_id}", f"任务已停止: {task_id}")

    def delete_task(self, task_id: str, delete_file: bool = False) -> bool:
        """删除任务 (从任务列表移除)。

        Args:
            task_id: 任务 ID
            delete_file: True 时同时删除该任务已下载的输出文件

        Returns:
            bool: 是否删除成功
        """
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return False
            # 停止仍在运行的任务
            task.stop_flag.set()
            if task.status == "running":
                self._set_terminal(task, "stopped")
            self.tasks.pop(task_id, None)
        if delete_file and task.output_file:
            try:
                # 安全校验: 只允许删除输出目录下的 .txt 文件, 防误删任意路径
                from _path_utils import resolve_output_dir
                out_dir = resolve_output_dir(task.output_dir)
                fp = os.path.abspath(task.output_file)
                if os.path.isfile(fp) and os.path.abspath(out_dir) == \
                        os.path.dirname(fp) and fp.lower().endswith('.txt'):
                    os.remove(fp)
                    if app_log is not None:
                        app_log.info(f"任务{task_id}", f"已删除源文件: {fp}")
                else:
                    if app_log is not None:
                        app_log.warn(f"任务{task_id}", f"源文件不在输出目录或非txt, 跳过删除: {fp}")
            except Exception as e:
                if app_log is not None:
                    app_log.error(f"任务{task_id}", f"删除源文件失败: {e}")
        if app_log is not None:
            app_log.info(f"任务{task_id}", f"任务已删除: {task_id} (删文件={delete_file})")
        return True

    def get_task_params(self, task_id: str) -> dict:
        """获取任务创建参数 (供"重新下载"复用)"""
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return {}
            return {
                'url': task.url,
                'mode': task.mode,
                'chapter_range': task.chapter_range,
                'threads': task.threads,
                'delay': task.delay,
                'resume': task.resume,
                'output_dir': task.output_dir,
                'export_epub': task.export_epub,
            }

    def restart_task(self, task_id: str) -> bool:
        """在原任务内重新开始抓取 (不新建任务)。

        重置进度/日志/停止标记后, 用原参数在同一个 task_id 上重新启动
        抓取线程; resume=False 从头重新抓取, 输出覆盖同名文件。

        Returns:
            bool: 是否成功重启
        """
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return False
            if task.status == "running":
                return False
        # 重置任务状态 (保留原创建参数 url/mode/threads 等)
        task.progress_current = 0
        task.progress_total = 0
        task.status = "running"
        task.logs = []
        task.error = ""
        task.output_file = ""
        task.metrics = TaskMetrics(start_time=time.time())  # 重置运行时指标
        task.stop_flag = threading.Event()  # 新建停止标记 (旧标记可能已被置位)
        task.logs.append({
            'time': time.strftime('%H:%M:%S'),
            'msg': "[重新下载] 任务在原任务内重新开始 (从头抓取)"
        })
        # 重新启动抓取线程 (同一 task_id, 任务列表不新增条目)
        t = threading.Thread(
            target=self._run_task,
            args=(task, task.url, task.mode, task.chapter_range,
                  task.threads, task.delay, False, task.output_dir),
            daemon=True
        )
        task.thread = t
        t.start()
        if app_log is not None:
            app_log.info(f"任务{task_id}", f"任务重新下载 (原任务重启): {task.url}")
        return True

    def get_task(self, task_id: str) -> Optional[TaskInfo]:
        """获取任务信息"""
        with self._lock:
            return self.tasks.get(task_id)

    def find_task_by_url(self, url: str, mode: str = None) -> Optional[TaskInfo]:
        """查找与给定 URL 相同的任务 (可选限定模式); 无则返回 None"""
        with self._lock:
            for t in self.tasks.values():
                if t.url == url and (mode is None or t.mode == mode):
                    return t
        return None

    def get_all_tasks(self) -> list:
        """获取所有任务列表（按创建序号排序）

        M5 修复: task_id 为 "task_N" 字符串, 字典序会使 task_10 排在 task_2
        之前 (批量导入必现); 改按数字序号排序。
        """
        with self._lock:
            return sorted(self.tasks.values(),
                          key=lambda t: int(t.task_id.split('_')[-1]))
