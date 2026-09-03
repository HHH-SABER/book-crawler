# -*- coding: utf-8 -*-
"""速度自适应模块：程序自动评估设备能力与运行环境, 动态选择最快可用速度档位。

设计目标 (无用户手动干预):
  1. 默认以最快速度启动: 启动时依据 设备硬件画像 + 任务规模 + 站点约束
     自动选出当前环境允许的最高档位;
  2. 运行时降级: 抓取过程中检测到限频/验证码/连续失败/系统资源紧张时,
     立即安全回退到更稳妥的档位 (并发数下调 + 章节间隔放大);
  3. 条件恢复后回升: 长时间稳定运行 (连续成功 + 无风险事件 + 冷静期)
     后逐档回升, 回升上限不超过启动档位 (不激进抢跑)。

选档依据的具体指标与评估方式:
  A. 硬件性能画像 (一次性基准, 结果缓存 7 天到 数据/速度画像.json):
     - CPU 逻辑核数            os.cpu_count()
     - 可用内存                Windows: GlobalMemoryStatusEx; 其他: /proc/meminfo
     - CPU 当前忙碌率          Windows: GetSystemTimes 采样; Linux: /proc/stat 采样
                               (系统本身已高负载时压制启动档位)
     - 单核算力基准            固定时长 sha256 吞吐 (MB/s), 纯标准库、无外部依赖
     - 多线程扩展比            4 线程 sha256 吞吐 / 单线程吞吐 (hashlib 释放 GIL,
                               能真实反映并发收益; 扩展比低说明并发无意义)
  B. 任务复杂度: 章节总数。小书 (<30章) 并发收益有限, 上限压到"快速"档;
     大书允许到设备允许的最高档。
  C. 站点约束 (反爬敏感站点): tanmixs.com WAF 按 IP 限流, 强制上限"标准"档
     (实测多浏览器并发反而触发验证码, 见 run() 内历史注释)。
  D. 运行时信号 (评估方式):
     - 章节连续失败 >= 3       → 降一档 (站点可能被高并发惹恼)
     - 反爬事件 (限频/WAF/JS挑战) → 立即降档 (每次事件至少降一档, 连续事件连续降)
     - 系统内存可用 < 300MB    → 降档 (资源受限保护)
     - 回升冷静期 180 秒 + 最近连续成功 >= 30 章 + 期间无风险事件 → 回升一档

线程安全: 控制器会被多个抓取 worker 线程同时调用, 全部状态经同一把锁保护。
并发闸门: 线程池大小按启动档位固定, 运行中通过 gate() 动态调节"同时抓取数",
          降档时多余 worker 在闸门上等待而非退出, 回升时立即恢复满速。
"""
import os
import sys
import time
import json
import threading
import hashlib
from contextlib import contextmanager
from pathlib import Path

try:
    import 日志 as _app_log
    _log = _app_log.get('速度自适应')
except Exception:
    _log = None


def _info(msg):
    if _log is not None:
        _log.info(msg)


def _debug(msg):
    if _log is not None:
        _log.debug(msg)


# ====================================================================== 档位
class SpeedTier:
    """速度档位: 并发线程数 + 章节间请求间隔 (秒)"""

    def __init__(self, level, name, threads, delay):
        self.level = level      # 0=标准 1=快速 2=极速 (越大越快)
        self.name = name
        self.threads = threads
        self.delay = delay

    def __str__(self):
        return f"{self.name} ({self.threads}线程, 间隔{self.delay}s)"


TIER_STANDARD = SpeedTier(0, "标准", 1, 1.0)
TIER_FAST = SpeedTier(1, "快速", 3, 0.5)
TIER_TURBO = SpeedTier(2, "极速", 6, 0.2)
_TIERS = [TIER_STANDARD, TIER_FAST, TIER_TURBO]


def _tier_by_level(level):
    level = max(0, min(int(level), len(_TIERS) - 1))
    return _TIERS[level]


# 反爬敏感站点: 并发上限强制压档 (WAF 按 IP 限流, 并发反而更慢)
SITE_TIER_CAPS = {
    'tanmixs.com': 0,   # 标准 (1线程)
}

# 小书并发收益有限, 上限压到"快速"档
SMALL_BOOK_CHAPTERS = 30

# 回升条件
UPGRADE_COOLDOWN_SECONDS = 180    # 距上次档位变动的冷静期
UPGRADE_CONSEC_OK = 30            # 最近连续成功章节数


# ====================================================================== 设备画像
# 画像缓存路径: 用 BASE_DIR (EXE 旁 / 项目根) 而非 __file__ 推导,
# 否则 onefile EXE 会把缓存写进 _MEIPASS 临时解包目录, 每次运行都重跑基准
try:
    from _path_utils import get_app_base_dir as _get_app_base_dir
    _PROFILE_CACHE = Path(_get_app_base_dir()) / '数据' / '速度画像.json'
except Exception:
    _PROFILE_CACHE = Path(__file__).resolve().parent.parent / '数据' / '速度画像.json'
_PROFILE_TTL = 7 * 24 * 3600      # 画像缓存 7 天 (设备硬件不会频繁变化)
_PROFILE_LOCK = threading.Lock()  # 并发任务同时首次选档时, 基准只跑一份、写入不竞争


def _cpu_core_count():
    try:
        return max(1, os.cpu_count() or 1)
    except Exception:
        return 1


def _available_memory_mb():
    """可用内存 MB (Windows: GlobalMemoryStatusEx; 其他: /proc/meminfo 兜底)"""
    try:
        if sys.platform == 'win32':
            import ctypes

            class _MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ('dwLength', ctypes.c_ulong),
                    ('dwMemoryLoad', ctypes.c_ulong),
                    ('ullTotalPhys', ctypes.c_ulonglong),
                    ('ullAvailPhys', ctypes.c_ulonglong),
                    ('ullTotalPageFile', ctypes.c_ulonglong),
                    ('ullAvailPageFile', ctypes.c_ulonglong),
                    ('ullTotalVirtual', ctypes.c_ulonglong),
                    ('ullAvailVirtual', ctypes.c_ulonglong),
                    ('ullAvailExtendedVirtual', ctypes.c_ulonglong),
                ]

            stat = _MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return stat.ullAvailPhys / (1024 * 1024)
        elif os.path.exists('/proc/meminfo'):
            for line in Path('/proc/meminfo').read_text(encoding='utf-8').splitlines():
                if line.startswith('MemAvailable:'):
                    return float(line.split()[1]) / 1024
    except Exception as e:
        _debug(f'可用内存探测失败: {e}')
    return 4096.0  # 探测失败按 4GB 处理, 不因此压档


def _cpu_busy_ratio(sample_seconds=0.3):
    """采样 CPU 忙碌率 0~1 (Windows: GetSystemTimes; Linux: /proc/stat; 失败返回 None)"""
    try:
        if sys.platform == 'win32':
            import ctypes

            class _FT(ctypes.Structure):
                _fields_ = [('dwLowDateTime', ctypes.c_ulong),
                            ('dwHighDateTime', ctypes.c_ulong)]

            def _to_int(ft):
                return (ft.dwHighDateTime << 32) | ft.dwLowDateTime

            idle1, kernel1, user1 = _FT(), _FT(), _FT()
            if not ctypes.windll.kernel32.GetSystemTimes(
                    ctypes.byref(idle1), ctypes.byref(kernel1), ctypes.byref(user1)):
                return None
            time.sleep(sample_seconds)
            idle2, kernel2, user2 = _FT(), _FT(), _FT()
            if not ctypes.windll.kernel32.GetSystemTimes(
                    ctypes.byref(idle2), ctypes.byref(kernel2), ctypes.byref(user2)):
                return None
            idle = _to_int(idle2) - _to_int(idle1)
            total = (_to_int(kernel2) + _to_int(user2)) - (_to_int(kernel1) + _to_int(user1))
            if total <= 0:
                return None
            return max(0.0, min(1.0, 1.0 - idle / total))
        elif os.path.exists('/proc/stat'):
            def _read():
                for line in Path('/proc/stat').read_text(encoding='utf-8').splitlines():
                    if line.startswith('cpu '):
                        parts = [int(p) for p in line.split()[1:9]]
                        idle = parts[3] + parts[4]
                        return idle, sum(parts)
                return None
            r1 = _read()
            time.sleep(sample_seconds)
            r2 = _read()
            if not r1 or not r2:
                return None
            d_idle = r2[0] - r1[0]
            d_total = r2[1] - r1[1]
            if d_total <= 0:
                return None
            return max(0.0, min(1.0, 1.0 - d_idle / d_total))
    except Exception as e:
        _debug(f'CPU 忙碌率采样失败: {e}')
    return None


def _sha256_bench(workers=1, duration=0.35):
    """固定时长 sha256 吞吐基准 (MB/s)。hashlib 对大 buffer 释放 GIL,
    多线程结果能真实反映多核并发收益。"""
    block = b'\x00' * (256 * 1024)  # 256KB
    total_hashed = 0

    def _worker():
        nonlocal total_hashed
        local = 0
        end = time.perf_counter() + duration
        h = hashlib.sha256()
        while time.perf_counter() < end:
            h.update(block)
            local += len(block)
        with threading.Lock():
            total_hashed += local

    threads = [threading.Thread(target=_worker) for _ in range(max(1, workers))]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - t0
    if elapsed <= 0:
        return 0.0
    return (total_hashed / elapsed) / (1024 * 1024)


def _benchmark():
    """运行一次完整基准, 返回画像 dict (失败时返回保守默认画像)"""
    cores = _cpu_core_count()
    mem_mb = _available_memory_mb()
    busy = _cpu_busy_ratio()
    try:
        single = _sha256_bench(workers=1)
        quad = _sha256_bench(workers=min(4, max(2, cores)))
        scale = (quad / single) if single > 0 else 1.0
    except Exception as e:
        _debug(f'基准运行失败: {e}')
        single, scale = 0.0, 1.0
    return {
        'cpu_cores': cores,
        'mem_available_mb': round(mem_mb),
        'cpu_busy_ratio': round(busy, 3) if busy is not None else None,
        'single_core_score_mbps': round(single, 1),
        'parallel_scale_4t': round(scale, 2),
        'bench_time': time.time(),
    }


def _load_cached_profile():
    """读取缓存的设备画像 (TTL 内有效, 损坏/过期返回 None)"""
    try:
        if not _PROFILE_CACHE.exists():
            return None
        data = json.loads(_PROFILE_CACHE.read_text(encoding='utf-8'))
        if time.time() - float(data.get('bench_time', 0)) > _PROFILE_TTL:
            return None
        return data
    except Exception as e:
        _debug(f'画像缓存读取失败: {e}')
        return None


def _save_profile(profile):
    """缓存设备画像到 数据/速度画像.json (失败不影响主流程)"""
    try:
        _PROFILE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _PROFILE_CACHE.write_text(
            json.dumps(profile, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception as e:
        _debug(f'画像缓存写入失败: {e}')


def 设备画像(force_refresh=False):
    """获取设备硬件画像 (优先 7 天缓存, 缓存过期/强制时重新基准)

    并发安全: 模块级锁 + 双重检查, 多任务同时首次选档时基准只跑一份。
    """
    if not force_refresh:
        cached = _load_cached_profile()
        if cached:
            return cached
    with _PROFILE_LOCK:
        # 双重检查: 等锁期间其他线程可能已完成基准并写好缓存
        if not force_refresh:
            cached = _load_cached_profile()
            if cached:
                return cached
        profile = _benchmark()
        _save_profile(profile)
    _info(f"[速度自适应] 设备画像: {profile['cpu_cores']}核 / "
          f"可用内存 {profile['mem_available_mb']}MB / "
          f"CPU忙碌率 {profile['cpu_busy_ratio'] if profile['cpu_busy_ratio'] is not None else '未知'} / "
          f"单核基准 {profile['single_core_score_mbps']}MB/s / "
          f"多线程扩展比 {profile['parallel_scale_4t']}")
    return profile


def _profile_max_level(profile):
    """由设备画像推导允许的最高档位 level (0=标准 1=快速 2=极速)"""
    try:
        cores = int(profile.get('cpu_cores', 1))
        mem_mb = float(profile.get('mem_available_mb', 2048))
        busy = profile.get('cpu_busy_ratio')
        score = float(profile.get('single_core_score_mbps', 0))
        scale = float(profile.get('parallel_scale_4t', 1.0))

        # 运行环境受限: 系统已高负载 / 可用内存紧张 → 直接压到标准档
        if busy is not None and busy >= 0.85:
            return 0
        if mem_mb < 512:
            return 0
        # 并发有效性与算力同时达标才允许极速:
        #   >=4 核, 4线程扩展比 >=1.8 (并发真有收益), 单核吞吐 >= 40MB/s
        if cores >= 4 and scale >= 1.8 and score >= 40:
            return 2
        if cores >= 2:
            return 1
        return 0
    except Exception:
        return 0


# ====================================================================== 控制器
class SpeedController:
    """自适应速度控制器 (线程安全)

    - 启动档位 = min(设备允许档, 站点上限, 任务规模上限), 满足"默认最快";
    - 运行中通过 record_chapter()/note_risk() 反馈信号, 触发降级/回升;
    - gate() 提供动态并发闸门: 降档时同时抓取数立即收缩, 回升时立即恢复;
    - current_delay() 返回当前档位的章节间隔, 抓取循环每章实时读取;
    - manual=(threads, delay) 时进入手动模式: 档位固定不自动调节 (CLI --threads 用),
      仅做统计。
    """

    def __init__(self, domain, start_level, max_level, manual=None):
        self.domain = domain or ''
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._manual = manual  # None=自适应; (threads, delay)=手动直通
        self._max_tier = _tier_by_level(max_level)
        self._tier = _tier_by_level(start_level)
        self._active = 0            # 当前正在闸门内抓取的 worker 数
        self._consec_fail = 0
        self._consec_ok = 0
        self._risk_since_change = 0
        self._last_change_time = time.time()
        self._downgrades = 0
        self._upgrades = 0
        # 手动模式: 按指定线程数开闸, 档位即手动值
        if manual is not None:
            self._manual_threads, self._manual_delay = manual
            self._tier = SpeedTier(-1, f"手动({self._manual_threads}线程)",
                                   self._manual_threads, self._manual_delay)
            self._max_tier = self._tier

    # ------------------------------------------------------------ 启动参数
    def initial_params(self):
        """返回 (threads, delay) 供抓取循环初始化线程池与间隔"""
        with self._lock:
            return self._tier.threads, self._tier.delay

    @property
    def tier(self):
        with self._lock:
            return self._tier

    # ------------------------------------------------------------ 并发闸门
    @contextmanager
    def gate(self):
        """动态并发闸门: 进入抓取段前持有, 降档时多余 worker 在此等待。"""
        with self._cond:
            while self._active >= self._tier.threads:
                self._cond.wait(timeout=1.0)
            self._active += 1
        try:
            yield
        finally:
            with self._cond:
                self._active -= 1
                self._cond.notify_all()

    def current_delay(self):
        """当前章节间隔 (秒), 抓取循环每章实时读取 (降档立即放大间隔)"""
        with self._lock:
            return self._tier.delay

    # ------------------------------------------------------------ 运行时信号
    def note_risk(self, mechanism):
        """反爬风险事件 (限频/WAF/JS挑战/UA封锁) → 立即降一档"""
        if self._manual is not None:
            return
        msg = None
        with self._lock:
            self._risk_since_change += 1
            self._consec_ok = 0
            if self._tier.level > 0:
                msg = self._change_tier_locked(self._tier.level - 1,
                                               f"反爬事件 {mechanism}")
            else:
                msg = (f"[速度自适应] {self.domain} 已是最低档, "
                       f"反爬事件 {mechanism} 由退避/冷却机制接管")
        # 日志 I/O 在锁外执行: 持锁落盘会阻塞 gate 等待者与并发 worker
        if msg:
            _info(msg)

    def record_chapter(self, ok, latency=None):
        """记录单章结果: 连续失败触发降级; 稳定期满足时尝试回升"""
        if self._manual is not None:
            return
        msg = None
        with self._lock:
            if ok:
                self._consec_fail = 0
                self._consec_ok += 1
            else:
                self._consec_fail += 1
                self._consec_ok = 0
                if self._consec_fail >= 3 and self._tier.level > 0:
                    msg = self._change_tier_locked(self._tier.level - 1,
                                                   f"连续 {self._consec_fail} 章失败")
                    self._consec_fail = 0
                    self._consec_ok = 0
            if msg is None:
                msg = self._maybe_upgrade_locked()
        # 日志 I/O 在锁外执行
        if msg:
            _info(msg)

    def _system_pressure(self):
        """系统资源压力检查: 内存紧张返回 True (降档保护)"""
        return _available_memory_mb() < 300

    def _maybe_upgrade_locked(self):
        """回升判定 (须持锁; 只改状态不落盘): 冷静期 + 连续成功 + 无风险事件"""
        if self._tier.level >= self._max_tier.level:
            return None
        if self._consec_ok < UPGRADE_CONSEC_OK:
            return None
        if time.time() - self._last_change_time < UPGRADE_COOLDOWN_SECONDS:
            return None
        if self._risk_since_change > 0:
            return None
        if self._system_pressure():
            return f"[速度自适应] {self.domain} 条件满足但系统内存紧张, 暂不回升"
        return self._change_tier_locked(self._tier.level + 1, "运行稳定, 条件恢复回升")

    # ------------------------------------------------------------ 档位变更
    def _change_tier_locked(self, new_level, reason):
        """切换档位并调整闸门上限 (须持锁; 只改状态不落盘, 返回日志消息)"""
        old_tier = self._tier
        new_tier = _tier_by_level(new_level)
        if new_tier.level == old_tier.level:
            return None
        upgraded = new_tier.level > old_tier.level
        self._tier = new_tier
        self._last_change_time = time.time()
        self._risk_since_change = 0
        self._consec_ok = 0
        if upgraded:
            self._upgrades += 1
        else:
            self._downgrades += 1
        self._cond.notify_all()  # 闸门上限变化, 唤醒等待中的 worker
        arrow = '⬆️ 回升' if upgraded else '⬇️ 降级'
        return (f"[速度自适应] {self.domain} {arrow}: {old_tier.name} → {new_tier} "
                f"(原因: {reason})")

    # ------------------------------------------------------------ 快照
    def snapshot(self):
        """当前状态快照 (供日志/指标面板)"""
        with self._lock:
            return {
                'domain': self.domain,
                'tier': str(self._tier),
                'level': self._tier.level,
                'threads': self._tier.threads,
                'delay': self._tier.delay,
                'max_level': self._max_tier.level,
                'manual': self._manual is not None,
                'consec_fail': self._consec_fail,
                'consec_ok': self._consec_ok,
                'downgrades': self._downgrades,
                'upgrades': self._upgrades,
            }


# ====================================================================== 工厂
def build_controller(catalog_url, total_chapters=None, manual_threads=None,
                     manual_delay=None):
    """为一次抓取任务构建 SpeedController。

    Args:
        catalog_url: 小说目录页 URL (用于解析域名匹配站点约束)
        total_chapters: 章节总数 (任务规模参与选档, 未知传 None)
        manual_threads/manual_delay: CLI 显式指定的线程/间隔 → 手动直通模式

    Returns:
        SpeedController 实例
    """
    # 手动模式 (CLI --threads/--delay 显式指定): 不自动调节, 保持向后兼容
    if manual_threads is not None and manual_threads > 0:
        delay = float(manual_delay) if manual_delay is not None else 1.0
        _info(f"[速度自适应] 手动指定速度: {manual_threads} 线程 / 间隔 {delay}s (不自动调节)")
        return SpeedController('', 0, 0, manual=(manual_threads, delay))

    from urllib.parse import urlparse
    try:
        domain = urlparse(catalog_url).netloc.lower()
    except Exception:
        domain = ''

    # 站点上限 (反爬敏感站点)
    site_cap = 2
    for site, cap in SITE_TIER_CAPS.items():
        if site in domain:
            site_cap = cap
            break

    # 任务规模上限 (小书并发收益有限)
    task_cap = 2
    if total_chapters is not None and total_chapters < SMALL_BOOK_CHAPTERS:
        task_cap = 1

    # 设备画像上限
    profile = 设备画像()
    device_cap = _profile_max_level(profile)

    max_level = max(0, min(site_cap, task_cap, device_cap))
    # 默认以最快速度启动: 启动档位 = 允许的最高档
    controller = SpeedController(domain, max_level, max_level)
    _info(f"[速度自适应] {domain or '未知站点'} 启动档位: {controller.tier} "
          f"(设备上限={_tier_by_level(device_cap).name}, "
          f"站点上限={_tier_by_level(site_cap).name}, "
          f"任务规模上限={_tier_by_level(task_cap).name}, "
          f"共 {total_chapters if total_chapters is not None else '?'} 章)")
    return controller
