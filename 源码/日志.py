# -*- coding: utf-8 -*-
"""统一日志模块: 所有运行日志落盘到 BASE_DIR/日志/, 便于事后排查问题

设计要点:
- 单例 AppLogger, 线程安全 (锁保护写入)
- 按天轮转: 日志/YYYY-MM-DD.log, 单文件超过 5MB 加序号 (如 2026-08-11_2.log)
- 保留最近 30 天日志, 启动时自动清理过期文件
- 级别: DEBUG / INFO / WARN / ERROR
- 格式: [HH:MM:SS.mmm] [级别] [来源] 消息
- 定位路径复用 _path_utils.get_app_base_dir() (EXE 旁或项目根)
"""
import os
import sys
import time
import traceback
import threading

# 日志级别
DEBUG, INFO, WARN, ERROR = "DEBUG", "INFO", "WARN", "ERROR"
_LEVEL_ORDER = {DEBUG: 10, INFO: 20, WARN: 30, ERROR: 40}

_MAX_FILE_SIZE = 5 * 1024 * 1024   # 单文件 5MB 轮转
_RETENTION_DAYS = 30               # 日志保留天数
_DEFAULT_LEVEL = DEBUG             # 默认记录全部级别 (含调试详情)


def get_log_dir() -> str:
    """日志目录: BASE_DIR/日志 (自动创建)"""
    try:
        import _path_utils
        base = _path_utils.get_app_base_dir()
    except Exception:
        base = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(base, "日志")
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError:
        pass
    return log_dir


class AppLogger:
    """线程安全的文件日志器 (单例)"""

    _instance = None
    _init_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if getattr(self, "_ready", False):
            return
        self._ready = True
        self._lock = threading.Lock()
        self._file = None
        self._file_path = None
        self._cur_date = None
        self._level = _DEFAULT_LEVEL
        self._cleanup_old_logs()

    # ---------------------------------------------------------------- 路径
    def _daily_path(self, date_str: str, seq: int = 0) -> str:
        name = f"{date_str}.log" if seq == 0 else f"{date_str}_{seq}.log"
        return os.path.join(get_log_dir(), name)

    def _switch_file_if_needed(self):
        """按天/按大小轮转日志文件"""
        today = time.strftime('%Y-%m-%d')
        seq = 0
        path = self._daily_path(today)
        while seq < 100:
            if not os.path.exists(path):
                break
            if os.path.getsize(path) < _MAX_FILE_SIZE:
                break
            seq += 1
            path = self._daily_path(today, seq)
        if self._file is None or path != self._file_path:
            if self._file is not None:
                try:
                    self._file.close()
                except Exception:
                    pass
            self._file_path = path
            self._file = open(path, 'a', encoding='utf-8', buffering=1)  # 行缓冲
            self._cur_date = today

    # ---------------------------------------------------------------- 写日志
    def _write(self, level: str, source: str, message: str):
        if _LEVEL_ORDER.get(level, 20) < _LEVEL_ORDER.get(self._level, 20):
            return
        ts = time.strftime('%H:%M:%S') + f".{int(time.time() * 1000) % 1000:03d}"
        line = f"[{ts}] [{level}] [{source}] {message}"
        with self._lock:
            try:
                self._switch_file_if_needed()
                self._file.write(line + '\n')
            except Exception:
                pass  # 日志失败绝不影响主流程

    def debug(self, source: str, message: str):
        self._write(DEBUG, source, message)

    def info(self, source: str, message: str):
        self._write(INFO, source, message)

    def warn(self, source: str, message: str):
        self._write(WARN, source, message)

    def error(self, source: str, message: str):
        self._write(ERROR, source, message)

    def error_exc(self, source: str, message: str, exc: Exception = None):
        """错误 + 完整堆栈 (优先使用传入的异常, 否则取当前调用栈)"""
        self._write(ERROR, source, message)
        if exc is not None:
            stack = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        else:
            stack = traceback.format_exc()
        for line in stack.rstrip().split('\n'):
            self._write(ERROR, source, line)

    def set_level(self, level: str):
        """运行时调整日志级别 (如切换为 ERROR 仅记录错误)"""
        self._level = level

    # ---------------------------------------------------------------- 维护
    def _cleanup_old_logs(self):
        """删除超过保留天数的旧日志文件"""
        try:
            log_dir = get_log_dir()
            cutoff = time.time() - _RETENTION_DAYS * 86400
            for name in os.listdir(log_dir):
                if not name.endswith('.log'):
                    continue
                fp = os.path.join(log_dir, name)
                try:
                    if os.path.getmtime(fp) < cutoff:
                        os.remove(fp)
                except OSError:
                    pass
        except Exception:
            pass

    def close(self):
        with self._lock:
            if self._file is not None:
                try:
                    self._file.close()
                except Exception:
                    pass
                self._file = None


# 模块级便捷函数 (与 logging 模块风格一致)
def debug(source: str, message: str): AppLogger().debug(source, message)
def info(source: str, message: str): AppLogger().info(source, message)
def warn(source: str, message: str): AppLogger().warn(source, message)
def error(source: str, message: str): AppLogger().error(source, message)
def error_exc(source: str, message: str, exc: Exception = None):
    AppLogger().error_exc(source, message, exc)


def install_global_excepthook():
    """安装全局异常钩子: 未捕获异常写入日志 (GUI 崩溃也留痕)"""
    def _hook(exc_type, exc_value, exc_tb):
        try:
            stack = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
            with _excepthook_lock:
                AppLogger().error("系统", f"未捕获异常: {exc_value}")
                for line in stack.rstrip().split('\n'):
                    AppLogger().error("系统", line)
        except Exception:
            pass
        # 保留原始行为
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    if not getattr(sys.excepthook, "_app_log_installed", False):
        _excepthook_lock = threading.Lock()
        _hook._app_log_installed = True
        sys.excepthook = _hook
