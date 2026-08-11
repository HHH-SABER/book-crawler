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
from typing import Optional


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


class TaskLogRedirector:
    """将 print 输出重定向到指定任务的日志列表

    每个任务线程独立持有此对象，替换 sys.stdout，实现日志隔离。
    同时保留原始 stdout 输出，方便调试。
    """

    def __init__(self, task_info: TaskInfo, original_stdout):
        self.task = task_info
        self.original = original_stdout

    def write(self, text):
        if text.strip():
            timestamp = time.strftime('%H:%M:%S')
            for line in text.strip().split('\n'):
                if line.strip():
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
            status="running"
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

    def _run_task(self, task: TaskInfo, url: str, mode: str,
                  chapter_range: tuple, threads: int, delay: float,
                  resume: bool, output_dir: str):
        """在子线程中执行 run_crawl，重定向 print 到任务日志"""
        original_stdout = sys.stdout
        sys.stdout = TaskLogRedirector(task, original_stdout)
        try:
            # 动态导入爬虫模块（避免在GUI启动时加载selenium等重依赖）
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from 爬虫 import run_crawl

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
        finally:
            sys.stdout = original_stdout

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

    def get_task(self, task_id: str) -> Optional[TaskInfo]:
        """获取任务信息"""
        with self._lock:
            return self.tasks.get(task_id)

    def get_all_tasks(self) -> list:
        """获取所有任务列表（按创建时间排序）"""
        with self._lock:
            return sorted(self.tasks.values(), key=lambda t: t.task_id)
