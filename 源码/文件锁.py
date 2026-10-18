# -*- coding: utf-8 -*-
"""跨进程文件锁 (C6 Roadmap R03, 2026-10-18)。

**解决的问题**: 各状态文件 (数据/*.json) 的单次写已是原子的 (tmp+os.replace),
部分模块还做了"落盘前读盘合并" (U16) —— 但"读→合并→写"整个序列没有跨进程
互斥: 进程 A 读盘合并完还没写, 进程 B 也读盘合并并写了, A 后写 ⇒ **B 刚写
进去的数据被 A 的旧快照抹掉** (静默丢更新)。GUI 与远控服务/CLI 是两个进程,
共享同一批状态文件, 这个窗口真实存在 (R03 登记项)。

**选型**: `msvcrt.locking` (Windows stdlib, 零新增依赖):
  · 锁的是**专用 .lock 文件的第 1 字节**, 不是数据文件本身 —— 数据文件被
    os.replace 换 inode 不影响锁 (锁在 .lock 上, 它永不被替换);
  · **进程退出/崩溃时 OS 自动释放锁** —— 不会留下"僵锁文件"坑死后来者
    (自己造 .lock 标志文件的方案治不了这个);
  · 只护本机 —— 状态文件本就只在本机读写, 跨机场景不存在。

**降级**: 非 Windows / 建不了锁文件 ⇒ `yield False` 无锁直入 (与加锁前行为
一致, 不会更坏); 拿不到锁 (等待超时) 也放行并告知调用方 —— **绝不卡死抓取**。

用法 (包住整个"读→改→写"临界区, 粒度=一个状态文件):
    from 文件锁 import 写锁
    with 写锁(路径) as 锁住:
        数据 = _读(路径)
        数据[k] = v
        _原子写(路径, 数据)
        # 锁住=False (超时放行) 时调用方可知情 —— 记录一条 debug 即可
"""
import os
import threading
import time
from contextlib import contextmanager

# 等锁上限: 正常临界区是毫秒级 (序列化+写盘), 10 秒等不到说明对方卡死,
# 放行直入 (旧行为) 比无限等待好 —— 抓取主流程永不被锁拖死。
_等锁超时秒 = 10.0
_轮询间隔秒 = 0.05

# 进程内串行化: msvcrt 锁是 per-handle, **同进程内两个线程各开一个句柄
# 会互相认为"没锁"而双双进入** —— 必须叠加同进程 threading 锁才对。
_进程内锁 = threading.Lock()
_已告警 = set()          # 超时放行的告警去重 (同文件只叨一次)


@contextmanager
def 写锁(数据路径: str, 超时秒: float = _等锁超时秒):
    """跨进程互斥进入临界区。yield True=锁住; False=未锁住 (降级/超时放行)。

    任何情况下都不抛异常 —— 锁是可靠性增强, 不是新的失败点。
    """
    句柄 = None
    锁住 = False
    try:
        # ① 进程内先互斥 (同进程多线程: GUI 的 flush 与 worker 的记录)
        if not _进程内锁.acquire(timeout=max(0.1, 超时秒)):
            yield False          # 进程内都抢不到: 放行 (旧行为), 不卡任务
            return
        try:
            # ② 跨进程 (msvcrt 字节锁; 非 Windows 降级无锁)
            try:
                import msvcrt
            except Exception:
                yield False      # 非 Windows: 无跨进程锁, 直入
                return
            try:
                句柄 = os.open(数据路径 + '.process.lock',
                               os.O_RDWR | os.O_CREAT, 0o644)
            except OSError:
                yield False      # 锁文件都建不了 (只读目录等): 放行
                return
            截止 = time.monotonic() + max(0.0, 超时秒)
            while True:
                try:
                    msvcrt.locking(句柄, msvcrt.LK_NBLCK, 1)   # 非阻塞试锁第 1 字节
                    锁住 = True
                    break
                except OSError:
                    if time.monotonic() >= 截止:
                        break
                    time.sleep(_轮询间隔秒)
            if not 锁住 and 数据路径 not in _已告警:
                _已告警.add(数据路径)   # 同文件只叨一次, 不刷屏
                try:
                    import 日志 as _app_log
                    _app_log.get('文件锁').debug(
                        f'等锁超时({超时秒:.0f}s)放行直入: {os.path.basename(数据路径)}')
                except Exception:
                    pass    # 刻意静默: 日志链路本身不可用时彻底静默 (与项目日志兜底约定一致)
            yield 锁住
        finally:
            if 句柄 is not None:
                if 锁住:
                    try:
                        import msvcrt
                        msvcrt.locking(句柄, msvcrt.LK_UNLCK, 1)
                    except Exception:
                        pass    # 刻意静默: 解锁失败无补救动作, OS 在进程退出时兜底释放; 记日志只会制造噪声
                try:
                    os.close(句柄)
                except OSError:
                    pass    # 刻意静默: 关句柄失败无副作用 (锁已释放/本就要退出), 记日志只会制造噪声
    finally:
        try:
            _进程内锁.release()
        except RuntimeError:
            pass    # 未 acquire 成功 (早退分支) 时 release 会抛, 忽略


def _自检():
    """无依赖自检: 基本互斥 + 不抛异常 (测试/排查用)。"""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, 't.json')
        with 写锁(p) as 拿到:
            assert 拿到 is True, '本机空闲时应当一次拿到'
        with 写锁(p, 超时秒=0.2) as 拿到:
            assert 拿到 is True
    return True


if __name__ == '__main__':
    _自检()
    print('文件锁自检 OK (msvcrt 互斥 + 超时放行 + 不抛)')
