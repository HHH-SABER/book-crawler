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
    # 任务来源: 本机(桌面客户端创建) / 手机(远控面板创建) — 远控页按此过滤展示
    来源: str = "本机"
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
        # U19 第二阶段决策依据: 统计"事件通道"与"正则兜底"各自真正改动了多少次状态。
        # 跑一轮真实抓取后看 覆盖率摘要(): 若正则兜底始终为 0, 说明事件已覆盖全部路径,
        # 那时才能安全删除正则; 若某个字段频繁靠正则兜底, 说明该字段还缺事件发出点。
        self.事件应用数 = 0
        self.正则兜底数 = 0
        self.正则兜底字段 = set()

    # U19 第二阶段开关: 正则兜底**默认停用**(False)。
    # 依据 2026-09-11 的两组实验:
    #   ① 离线端到端: 停用正则后事件通道仍正确填充 title/进度/输出文件/增量跳过;
    #   ② 真实运行差分(322zw.com 51 章): 停用正则后最终状态与开启时完全一致
    #      (status=completed / 进度 51/51 / 质检 100.0 通过 / 输出文件正确),
    #      事件生效 54 次, 正则改写从 54 次降到 2 次(仅剩内联两段, 已由"完成"事件覆盖)。
    # 置 True 可一行回退到"日志正则解析"的旧行为(代码与契约测试都保留着)。
    启用正则兜底 = False

    # 状态指纹用的字段名 (与 _状态指纹 顺序一一对应)
    _指纹字段 = ('title', 'progress_current', 'progress_total', 'output_file',
                 'status', 'engine', 'engine_fallback_chain', 'anti_spider_type',
                 'quality_score', 'quality_passed', 'incremental_skipped')

    def _状态指纹(self):
        m = self.task.metrics
        return (self.task.title, self.task.progress_current, self.task.progress_total,
                self.task.output_file, self.task.status, m.engine,
                len(m.engine_fallback_chain), m.anti_spider_type,
                m.quality_score, m.quality_passed, m.incremental_skipped)

    def _应用完成终态(self):
        """完成终态的统一落点 (正则路径与 '完成' 事件共用同一实现, 避免两处漂移)"""
        self.task.progress_current = self.task.progress_total
        self.task.status = 'completed'
        if self.task.metrics:
            self.task.metrics.end_time = time.time()
        # 质检列兜底回填 (逐章解析可能漏检): 完成时从 站点历史.json 取该书最近质检摘要
        self._backfill_quality(self.task)

    def 覆盖率摘要(self) -> str:
        """诊断一行: 事件通道覆盖是否完整 (供判断能否删除正则)。

        **指标口径要说清**（避免误读）: `正则兜底数` 统计的是"正则路径实际改动了状态"的次数,
        它是个**上界** —— 事件与正则会同时命中同一条语义 (事件在前或在后),
        因此 >0 **不一定**代表"该字段缺事件发出点", 只代表"正则仍在改写状态"。

        可靠的推论只有单向的:
          · 正则兜底 == 0  → 正则从未改动状态 → **可以安全删除**;
          · 正则兜底 > 0   → 需结合 `测试/test_event_channel.py` 的等价表与该轮日志,
                             逐个字段确认是"事件缺失"还是"两者重叠"。

        **注意**: `启用正则兜底=False` 时该计数恒为 0 (纯属构造), 此时不构成"可删"的证据 ——
        本方法会显式区分这两种情况, 避免自证式误读 (2026-09-11 自查发现)。
        """
        if not getattr(self, '启用正则兜底', True):
            return (f'正则兜底已停用(U19 第二阶段); 事件生效 {self.事件应用数} 次, '
                    f'状态全由事件驱动 —— 此计数为 0 是配置所致, 不能作为"可删"的证据')
        if not self.正则兜底数:
            return (f'事件通道覆盖完整 (事件生效 {self.事件应用数} 次, '
                    f'正则兜底 0 次) —— 具备删除正则的条件')
        return (f'正则仍在改写状态 {self.正则兜底数} 次, 涉及字段 '
                f'{sorted(self.正则兜底字段)} (事件生效 {self.事件应用数} 次) '
                f'—— 这是上界, 需逐字段确认是"事件缺失"还是"两者重叠"')

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
                s = line.strip()
                if s:
                    self._log_to_file(s)
                    self.task.logs.append({
                        'time': timestamp,
                        'msg': s
                    })
                    # U19: 统计正则兜底是否仍在起作用 (正则停用时这里恒不计数)
                    _前 = self._状态指纹()
                    if self.启用正则兜底:
                        # 从日志中解析进度: "正在抓取第 X/Y 章" 或 "X/Y (Z%)"
                        self._parse_progress(s)
                        # 解析小说名称: "提取到小说名称: XXX"
                        # 性能: 每条日志行都会经过这里, 先用子串做廉价预判再跑正则
                        # (子串是正则能够匹配的必要条件, 语义完全等价)
                        if '提取到小说名称' in s:
                            m = re.search(r'提取到小说名称:\s*(.+)', s)
                            if m:
                                self.task.title = m.group(1).strip()
                        # 解析完成: "抓取完成，共X章"
                        if '抓取完成' in s:
                            m = re.search(r'抓取完成.*共(\d+)章', s)
                            if m:
                                self._应用完成终态()
                    # U19: 正则路径若确实改动了状态, 记一笔 (含改了哪些字段)
                    _后 = self._状态指纹()
                    if _后 != _前:
                        self.正则兜底数 += 1
                        self.正则兜底字段.update(
                            n for n, a, b in zip(self._指纹字段, _前, _后) if a != b)
            # 保留最近500条日志
            # (原地截断: 旧实现用 logs[-500:] 整体切片, 一旦超过 500 条,
            #  每来一行日志都要重建一个 500 元素的新列表)
            if len(self.task.logs) > 500:
                del self.task.logs[:-500]
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
        """从日志行中解析进度信息

        性能: 每条日志行都会走这里, 故对每条正则先用子串做廉价预判。
        子串是正则匹配的必要条件 → 语义完全等价, 只是省掉必然失败的匹配。
        """
        # 匹配 "正在抓取第 X/Y 章"
        if '正在抓取第' in line:
            m = re.search(r'正在抓取第\s+(\d+)/(\d+)\s+章', line)
            if m:
                self.task.progress_current = int(m.group(1))
                self.task.progress_total = int(m.group(2))
                return
        # 匹配进度条 "X/Y (Z%)"
        if '%' in line:
            m = re.search(r'(\d+)/(\d+)\s*\((\d+(?:\.\d+)?)%\)', line)
            if m:
                self.task.progress_current = int(m.group(1))
                self.task.progress_total = int(m.group(2))
                return
        # 匹配 "共找到 X 个章节"
        if '章节' in line:
            m = re.search(r'共(?:找到|提取)\s*(\d+)\s*(?:个)?章节', line)
            if m:
                self.task.progress_total = int(m.group(1))
                return
        # 匹配输出文件路径
        if '已保存至' in line:
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

        # 性能: 本函数每条日志行都会被调用, 而绝大多数行不含任何指标标记。
        # 先做一次整体短路, 避免每行白跑 10+ 条必然失败的正则。
        # 下列子串覆盖本函数全部分支的前置必要条件 ('[反爬' 同时覆盖
        # '[反爬]' 与 '[反爬检测]'), 故不影响任何解析结果。
        if not ('[反爬' in line or '[引擎]' in line or '[质检]' in line
                or '[增量]' in line or 'JS cookie校验' in line):
            return

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

    # ------------------------------------------------------------------
    # U19 · 结构化任务事件通道（**主通道**；正则路径默认停用，仅作回退）
    # ------------------------------------------------------------------
    def 处理任务事件(self, 类型: str, 数据: dict):
        """消费爬虫发布的结构化事件, 直接更新任务状态。

        字段语义与 `_parse_progress` / `_parse_metrics` 的正则路径**逐字段等价**
        —— `测试/test_event_channel.py` 用"同一语义的日志行 vs 事件"双向断言,
        保证两条通道不会漂移。
        """
        self.事件应用数 += 1
        if 类型 == '完成':
            # 与正则路径共用 _应用完成终态(), 保证两条通道语义严格一致
            self._应用完成终态()
            return
        if 类型 == '标题':
            标题 = (数据.get('标题') or '').strip()
            if 标题:
                self.task.title = 标题
            return
        if 类型 == '进度':
            self.task.progress_current = int(数据.get('当前') or 0)
            总数 = int(数据.get('总数') or 0)
            if 总数:
                self.task.progress_total = 总数
            return
        if 类型 == '章节总数':
            总数 = int(数据.get('总数') or 0)
            if 总数:
                self.task.progress_total = 总数
            return
        if 类型 == '输出文件':
            路径 = (数据.get('路径') or '').strip()
            if 路径:
                self.task.output_file = 路径
            return
        if 类型 == '增量跳过':
            self.task.metrics.incremental_skipped += 1
            return
        if 类型 == '引擎成功':
            引擎 = 数据.get('引擎') or ''
            if 引擎:
                self.task.metrics.engine = 引擎
            return
        if 类型 == '引擎失败':
            引擎 = 数据.get('引擎') or ''
            链路 = self.task.metrics.engine_fallback_chain
            if 引擎 and 引擎 not in 链路:
                链路.append(引擎)
            return
        if 类型 == '反爬':
            机制 = 数据.get('机制') or ''
            if 机制:
                self.task.metrics.anti_spider_type = 机制
            return
        if 类型 == '质检':
            try:
                self.task.metrics.quality_score = float(数据.get('得分'))
            except (TypeError, ValueError):
                pass        # 得分缺失/非数字 → 保持原值 (与正则不匹配时同语义)
            self.task.metrics.quality_passed = bool(数据.get('通过'))
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


# ---------------------------------------------------------------- 同域闸门
# 同域任务串行 (对齐 run_batch 的"同站最多 1 本并行"): GUI 批量 / 手机远控
# 创建的任务同进程共享同一闸门表。排队中的任务保持 running 并在日志显示
# "[排队]"; stop 置位可打断等待 (未获得=不 release, 绝不误放他人闸门)。
_域闸门_表: dict = {}
_域闸门_锁 = threading.Lock()


def _取域闸门(url: str):
    """按域名取(建)信号量; 解析不出域名返回 None (直接放行)"""
    from urllib.parse import urlparse
    try:
        host = (urlparse(url or '').hostname or '').lower()
    except Exception:
        host = ''
    if not host:
        return None
    with _域闸门_锁:
        if host not in _域闸门_表:
            _域闸门_表[host] = threading.Semaphore(1)
        return _域闸门_表[host]


def _获取域闸门(闸门, stop_flag=None, 占用提示=None) -> bool:
    """stop-aware 获取同域闸门。

    返回 True=已获得 (调用方必须 release); False=排队中 stop 置位而放弃
    (未获得, 不得 release)。闸门为 None 视为放行。
    """
    if 闸门 is None:
        return True
    if 闸门.acquire(blocking=False):
        return True
    if 占用提示 is not None:
        try:
            占用提示()
        except Exception:
            pass
    while not 闸门.acquire(timeout=1.0):
        if stop_flag is not None and stop_flag.is_set():
            return False
    return True


def _排队提示(task) -> None:
    """同域排队时的可见提示 (任务日志 + 应用日志)"""
    task.logs.append({'time': time.strftime('%H:%M:%S'),
                      'msg': '[排队] 同站已有任务在运行, 等待轮转 (同域串行防封)'})
    if app_log is not None:
        try:
            app_log.info(f"任务{task.task_id}", "[排队] 同站已有任务在运行, 等待轮转")
        except Exception:
            pass


class TaskManager:
    """多任务管理器：创建、停止、查询爬虫任务"""

    def __init__(self, page):
        self.page = page  # Flet Page 实例，用于触发UI更新
        self.tasks: dict[str, TaskInfo] = {}
        self._lock = threading.Lock()
        self._counter = 0
        self._selected_task_id: str = ""       # 当前选中任务 (表格高亮/抽屉联动)

    # ------------------------------------------------------------ 选中联动
    def select_task(self, task_id: str):
        """选中/取消选中任务 (线程安全; 联动由 GUI 刷新循环轮询读取)"""
        with self._lock:
            if task_id == self._selected_task_id:
                return
            for t in self.tasks.values():
                t.selected = (t.task_id == task_id)
            self._selected_task_id = task_id

    @property
    def selected_task_id(self) -> str:
        """当前选中任务 ID (空串=无选中)"""
        return self._selected_task_id

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

    @staticmethod
    def _set_terminal(task: TaskInfo, status: str):
        """置为终态 (completed/failed/stopped) 并冻结耗时 end_time"""
        task.status = status
        if task.metrics:
            task.metrics.end_time = time.time()

    def _is_task_thread_owner(self, task: TaskInfo) -> bool:
        """当前线程是否仍是该任务登记的运行线程。

        restart_task 允许在旧线程收尾期间 (stop_event 已置位但 run_crawl 尚未
        返回) 于同一 task_id 上重启: 新线程接管 task.thread。旧线程退出时若
        仍按 task.status 判断, 会把新运行误标 completed/failed 并冻结其
        end_time — 终态变更必须只由登记线程执行。"""
        with self._lock:
            return task.thread is threading.current_thread()

    def _run_task(self, task: TaskInfo, url: str, mode: str,
                  chapter_range: tuple, threads: int, delay: float,
                  resume: bool, output_dir: str, unique_title: bool = False,
                  incremental: bool = False):
        """在子线程中执行 run_crawl，重定向 print 到任务日志"""
        # 注册到线程感知 stdout 调度器 (不再直接替换全局 sys.stdout, 避免多任务互踩)
        重定向器 = TaskLogRedirector(task, sys.__stdout__)
        _THREAD_STDOUT.register(重定向器)
        # U19: 同时订阅结构化任务事件 —— 与日志正则并行的显式数据通道。
        # 事件优先 (有则直接赋值), 正则兜底 (覆盖尚未发出事件的路径);
        # 两者都按线程隔离, 故多任务并发不会串台。
        try:
            import 任务事件
            任务事件.订阅(重定向器)
        except Exception as _e_ev:
            if app_log is not None:
                app_log.info(f"任务{task.task_id}",
                             f"任务事件通道订阅失败 (仅影响事件通道, 正则兜底仍在): "
                             f"{type(_e_ev).__name__}: {_e_ev}")
        try:
            # 动态导入爬虫模块（避免在GUI启动时加载selenium等重依赖）
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from 爬虫 import run_crawl

            if app_log is not None:
                app_log.info(f"任务{task.task_id}",
                             f"任务启动: {url} 模式={mode} 线程={threads} 延迟={delay} 续传={resume}"
                             + (" 增量=开" if incremental else ""))
            # 同域闸门: 同一站点最多 1 个任务在抓 (对齐 run_batch 限流)。
            # als1010 事故 (2026-09-12): GUI 批量 11 URL 同站并发 → WAF 拦截;
            # 排队期间任务保持 running, 日志可见, 可被停止打断。
            同域闸门 = _取域闸门(url)
            已获闸 = _获取域闸门(同域闸门, task.stop_flag,
                                占用提示=lambda: _排队提示(task))
            if not 已获闸:
                return  # 排队等待中被停止 (stop_task 已置终态)
            try:
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
            finally:
                if 同域闸门 is not None:
                    同域闸门.release()
            # 如果状态还是running且没有标记completed，标记为completed
            if self._is_task_thread_owner(task) and task.status == "running":
                self._set_terminal(task, "completed")
        except Exception as e:
            if self._is_task_thread_owner(task):
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
            try:
                import 任务事件
                任务事件.退订(重定向器)      # U19: 退订, 防线程复用/重复注册
            except Exception:
                pass
            try:
                # U19 诊断: 一轮任务的"事件 vs 正则兜底"统计, 供判断能否删除正则
                if app_log is not None:
                    app_log.info(f"任务{task.task_id}", 重定向器.覆盖率摘要())
            except Exception:
                pass

    def stop_task(self, task_id: str) -> bool:
        """停止指定任务（通过设置停止标志，爬虫循环检查后退出）。

        修复(U5): 只允许停止 running/pending 状态的任务。旧实现不校验状态,
        对已 completed/failed/stopped 的任务同样执行 —— 把"已完成"改写成
        "已停止"; 远控共用此入口, 手机端会看到错误终态并触发一次错误的
        完成推送。

        Returns:
            True = 已受理停止; False = 任务不存在或已处于终态(无需停止)
        """
        受理 = False
        with self._lock:
            task = self.tasks.get(task_id)
            if task and task.status in ("running", "pending"):
                task.stop_flag.set()
                self._set_terminal(task, "stopped")
                task.logs.append({
                    'time': time.strftime('%H:%M:%S'),
                    'msg': "[用户停止] 任务已被用户手动停止"
                })
                受理 = True
        if app_log is not None:
            if 受理:
                app_log.info(f"任务{task_id}", f"任务已停止: {task_id}")
            else:
                app_log.info(f"任务{task_id}",
                             f"停止请求被忽略: 任务不存在或已处于终态")
        return 受理

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
        抓取线程; resume 取 task.resume (调用方 — 输入条复用分支 — 在重启前
        已把用户当前 续传/EPUB/输出目录 选项同步进 task 字段, M2), 输出覆盖
        同名文件。

        Returns:
            bool: 是否成功重启
        """
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return False
            if task.status == "running":
                return False
            # L1 修复: 重置/登记线程的整段移入锁内 (旧实现检查与重置分离,
            # 并发的 delete_task/stop_task 可插入造成僵尸线程)
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
                'msg': f"[重新下载] 任务在原任务内重新开始 (续传={task.resume})"
            })
            # 重新启动抓取线程 (同一 task_id, 任务列表不新增条目)
            # M2: resume 用 task.resume — 旧实现硬编码 False, 用户在输入条上
            # 勾选的 断点续传/导出EPUB/输出目录 被静默丢弃
            t = threading.Thread(
                target=self._run_task,
                args=(task, task.url, task.mode, task.chapter_range,
                      task.threads, task.delay, task.resume, task.output_dir),
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

    @staticmethod
    def _任务排序键(t):
        """任务排序键: 兼容 "task_N" 与远控写入的 "resume_<md5>" 等非数字后缀。

        修复: 旧实现 int(task_id.split('_')[-1]) 遇到远控恢复中断任务时写入的
        "resume_<md5>" 会抛 ValueError, 该异常从 get_all_tasks 冒出后被 GUI 的
        刷新循环外层 try 吞掉 → 任务表/状态栏/远控页整体静默停摆 (重启才恢复)。
        数字后缀仍按数值排序 (保住 M5 修复: task_2 排在 task_10 之前)。
        """
        tid = str(getattr(t, 'task_id', '') or '')
        前缀, _, 后缀 = tid.rpartition('_')
        if 后缀.isdigit():
            return (前缀, 0, int(后缀), '')
        return (前缀, 1, 0, 后缀)

    def get_all_tasks(self) -> list:
        """获取所有任务列表（按创建序号排序）

        M5 修复: task_id 为 "task_N" 字符串, 字典序会使 task_10 排在 task_2
        之前 (批量导入必现); 改按数字序号排序。
        """
        with self._lock:
            return sorted(self.tasks.values(), key=self._任务排序键)
