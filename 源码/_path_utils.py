# -*- coding: utf-8 -*-
"""
统一路径解析（源码直跑 / PyInstaller onefile / PyInstaller onedir 均支持）

契约（经验 1341648 / 843258 总结）：
- RESOURCE_DIR : 内置只读资源（打包后是 sys._MEIPASS 临时目录），
                 存放 --add-data 嵌入的文件（如抓取结果/占位、图标等）。
- BASE_DIR     : 可写用户目录（EXE 可执行文件所在目录），
                 用户的 TXT 输出、自定义配置、Chrome 用户数据目录
                 等持久化内容必须落在这里。

开发模式（python 源码/*.py）：
  - RESOURCE_DIR = 源码/ 目录
  - BASE_DIR     = 项目根（源码/ 的上级，即 k:\程序文件\小说爬虫）
"""
import os
import sys
import shutil


def is_frozen() -> bool:
    """当前是否处于 PyInstaller 打包产物中运行"""
    return bool(getattr(sys, "frozen", False))


def get_resource_dir() -> str:
    """内置只读资源目录（RESOURCE_DIR）。
    - PyInstaller : sys._MEIPASS
    - 源码模式    : 本文件所在目录（即 源码/）
    """
    if is_frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.dirname(os.path.abspath(__file__))


def get_app_base_dir() -> str:
    """用户可写运行基目录（BASE_DIR）。
    - PyInstaller : sys.executable 所在目录（EXE 旁边）
    - 源码模式    : 项目根（源码/ 的上级）
    """
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def get_default_output_dir() -> str:
    """抓取结果/ 默认输出目录（永远写 BASE_DIR/抓取结果）。"""
    path = os.path.join(get_app_base_dir(), "抓取结果")
    os.makedirs(path, exist_ok=True)
    return path


# ---- 状态数据根（跨更新/重装持久）--------------------------------------
# 历史记录/书架/风控状态/阅读进度/日志 等"使用痕迹"存到用户级稳定目录,
# 换 EXE、换安装目录、重装都不会丢; 抓取结果/站点适配/站点配置 仍留在
# EXE 旁边 (用户要直接看到、要手改)。
_STATE_ROOT = None
# 修复(U9): 锁改为模块级直接创建。旧实现是惰性创建 (if _状态根锁 is None: ...),
# "判断-创建"本身非原子 —— 两个线程可各自 new 出一把锁并同时进入临界区,
# 触发并发 copytree 迁移 (重复复制 / 半成品目录)。
import threading as _threading
_状态根锁 = _threading.Lock()


def get_state_root() -> str:
    """状态数据根目录: %LOCALAPPDATA%/小说爬虫 (无则该变量时回退 BASE_DIR)。

    首次调用执行一次性迁移: 旧位置 BASE_DIR/数据、BASE_DIR/日志 → 新根
    (复制而非移动, 迁移失败也不影响旧数据继续可用)。幂等、线程安全。"""
    global _STATE_ROOT
    if _STATE_ROOT:
        return _STATE_ROOT
    with _状态根锁:
        if _STATE_ROOT:
            return _STATE_ROOT
        base = get_app_base_dir()
        local = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        root = os.path.join(local, "小说爬虫") if local else base
        try:
            os.makedirs(root, exist_ok=True)
            for name in ("数据", "日志"):
                old = os.path.join(base, name)
                new = os.path.join(root, name)
                if os.path.isdir(old) and not os.path.exists(new):
                    shutil.copytree(old, new)
        except OSError:
            pass  # 迁移/建目录失败 → 仍然返回 root, 各模块自身兜底
        _STATE_ROOT = root
        return _STATE_ROOT


def resolve_output_dir(output_dir) -> str:
    """对调用方传入的 output_dir 做规范化。
    相对路径一律相对于 BASE_DIR 解析，创建并返回绝对路径。
    """
    if not output_dir:
        return get_default_output_dir()
    if os.path.isabs(output_dir):
        resolved = output_dir
    else:
        resolved = os.path.normpath(os.path.join(get_app_base_dir(), output_dir))
    os.makedirs(resolved, exist_ok=True)
    return resolved


def resolve_data_file(filename: str, copy_default_from_resource_if_missing: bool = True) -> str:
    """**读写配置用**：返回 BASE_DIR 下的数据文件路径（用户可编辑、持久化）。

    当 BASE_DIR 下该文件不存在时：
      1. 若 RESOURCE_DIR 下有同名文件（作为打包内置默认值），则复制一份到 BASE_DIR；
      2. 否则直接返回 BASE_DIR 下的目标路径（由调用方决定是否生成默认内容）。
    """
    base_path = os.path.join(get_app_base_dir(), filename)
    if os.path.exists(base_path):
        return base_path

    if copy_default_from_resource_if_missing:
        # --add-data 可能把配置文件放到 RESOURCE_DIR 或 RESOURCE_DIR/源码/ 下，两处都查
        # 同时也检查 BASE_DIR/配置/ 目录（项目源码中的配置模板位置）
        candidates = [
            os.path.join(get_resource_dir(), filename),
            os.path.join(get_resource_dir(), "源码", filename),
            os.path.join(get_app_base_dir(), "配置", filename),
        ]
        for src in candidates:
            if os.path.isfile(src):
                try:
                    shutil.copy2(src, base_path)
                    return base_path
                except OSError:
                    # 复制失败（权限/磁盘满）时继续返回 base_path，调用方会尝试写入生成
                    break
    return base_path

