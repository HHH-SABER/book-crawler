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
import traceback
from typing import Optional

# 统一日志模块 (位于上级目录 源码/)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import 日志 as app_log
except Exception:
    app_log = None


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
    threads: int = 1
    delay: float = 1.0
    resume: bool = True
    output_dir: str = None


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


class _ThreadAwareStdout:
    """线程感知的 stdout 调度器（多任务日志隔离）

    背景: 全局 sys.stdout 被多线程并发替换会产生竞态——
    后启动的线程会覆盖前一个线程设置的 stdout, 导致多个任务的
    print 输出全部灌入最后一个任务, 标题/进度/日志互相串。
    方案: 用单一调度器替代 sys.stdout, 按"当前线程ID"分发到
    各线程注册的 writer, 实现真正的日志隔离。
    """

    def __init__(self):
        self._default = sys.__stdout__
        self._lock = threading.Lock()
        self._writers = {}  # thread_id -> writer

    def register(self, writer):
        """当前线程注册日志 writer (爬虫线程启动时调用)"""
        with self._lock:
            self._writers[threading.get_ident()] = writer

    def unregister(self):
        """当前线程注销 writer (爬虫线程结束时调用)"""
        with self._lock:
            self._writers.pop(threading.get_ident(), None)

    def _get_writer(self):
        with self._lock:
            return self._writers.get(threading.get_ident())

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

    def create_task(self, url: str, mode: str = "full",
                    chapter_range: tuple = None, threads: int = 1,
                    delay: float = 1.0, resume: bool = True,
                    output_dir: str = None) -> str:
        """创建并启动一个新爬虫任务，返回 task_id"""
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
        )
        with self._lock:
            self.tasks[task_id] = task

        # 启动子线程执行抓取
        t = threading.Thread(
            target=self._run_task,
            args=(task, url, mode, chapter_range, threads, delay, resume, output_dir),
            daemon=True
        )
        task.thread = t
        t.start()
        return task_id

    def create_batch_task(self, urls: list, threads: int = 2,
                          delay: float = 1.0, resume: bool = True,
                          output_dir: str = None) -> str:
        """创建并启动一个批量任务 (一次抓取多本书), 返回 task_id

        内部调用 run_batch: 书级并行 + 同域限流保护 + 汇总报告。
        """
        with self._lock:
            self._counter += 1
            task_id = f"task_{self._counter}"

        task = TaskInfo(
            task_id=task_id,
            url=f"[批量] {len(urls)} 本书",
            title=f"批量{len(urls)}本",
            mode="batch",
            status="running"
        )
        with self._lock:
            self.tasks[task_id] = task

        # 启动子线程执行批量抓取
        t = threading.Thread(
            target=self._run_batch_task,
            args=(task, urls, threads, delay, resume, output_dir),
            daemon=True
        )
        task.thread = t
        t.start()
        return task_id

    def _run_batch_task(self, task: TaskInfo, urls: list, threads: int,
                        delay: float, resume: bool, output_dir: str):
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
                threads=max(1, threads),
                sort_chapters=True,
                resume=resume,
                show_progress=True,
                output_dir=output_dir,
                delay=delay,
                stop_event=task.stop_flag
            )
            # 如果状态还是running且没有标记completed，标记为completed
            if task.status == "running":
                task.status = "completed"
        except Exception as e:
            task.status = "failed"
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
                  resume: bool, output_dir: str):
        """在子线程中执行 run_crawl，重定向 print 到任务日志"""
        # 注册到线程感知 stdout 调度器 (不再直接替换全局 sys.stdout, 避免多任务互踩)
        _THREAD_STDOUT.register(TaskLogRedirector(task, sys.__stdout__))
        try:
            # 动态导入爬虫模块（避免在GUI启动时加载selenium等重依赖）
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from 爬虫 import run_crawl

            if app_log is not None:
                app_log.info(f"任务{task.task_id}",
                             f"任务启动: {url} 模式={mode} 线程={threads} 延迟={delay} 续传={resume}")
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
                stop_event=task.stop_flag
            )
            # 如果状态还是running且没有标记completed，标记为completed
            if task.status == "running":
                task.status = "completed"
        except Exception as e:
            task.status = "failed"
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
                task.status = "stopped"
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
                task.status = "stopped"
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

    def get_all_tasks(self) -> list:
        """获取所有任务列表（按创建时间排序）"""
        with self._lock:
            return sorted(self.tasks.values(), key=lambda t: t.task_id)
