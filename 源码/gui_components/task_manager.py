# -*- coding: utf-8 -*-
"""多任务管理器：管理并行爬虫任务，每个任务在独立线程运行

通过重定向 print 到任务日志实现进度跟踪，通过正则解析进度信息。
"""
import threading
import dataclasses
import json
import sys
import time
import re
import os
import contextvars
from pathlib import Path
from typing import Optional

# 统一日志模块 (位于上级目录 源码/)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import 日志 as app_log
except Exception:
    app_log = None


class TaskLogBuffer(list):
    """保留最近 500 行，累计游标不随截断回退；快照与追加共用锁。"""
    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self.total = 0
        self.epoch = str(time.time_ns())

    def append(self, entry):
        with self._lock:
            super().append(entry)
            self.total += 1
            if len(self) > 500:
                del self[:-500]

    def extend(self, entries):
        for entry in entries:
            self.append(entry)

    def snapshot(self, after=0):
        with self._lock:
            total = self.total
            first = total - len(self)
            reset = after < first or after > total or after < 0
            pos = first if reset else after
            return {"total": total, "截断": reset,
                    "entries": list(self[max(0, pos-first):]), "epoch": self.epoch}


def snapshot_task_logs(task, after=0):
    logs = task.logs
    if isinstance(logs, TaskLogBuffer):
        return logs.snapshot(after)
    # 兼容旧调用方/测试直接赋 list；生产 TaskInfo 均用累计缓冲。
    copied = list(logs)
    reset = after < 0 or after > len(copied)
    return {"total": len(copied), "截断": reset,
            "entries": copied[0 if reset else after:], "epoch": str(id(logs))}


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
    # 最近一章的清洗统计 ('清洗' 事件, 2026-09-29 可观测性):
    # {关键词行, 推广行, 过短行, 符号行, 广告行, 水印} — 全为 int
    clean_summary: dict = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class TaskInfo:
    """单个爬虫任务的状态信息"""
    task_id: str
    url: str
    title: str = "未知"
    mode: str = "full"
    progress_current: int = 0
    progress_total: int = 0
    status: str = "pending"  # pending/running/completed/failed/stopped/interrupted/dead_pending(死书待确认,终态)
    logs: list = dataclasses.field(default_factory=TaskLogBuffer)
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
    # 死书信息 {类型,原因,可询问删除,网址,首次时间,...}; 非死书恒为 None
    # (2026-10-02 新增; 用 Optional[dict] 而非 dataclass 子结构, 使序列化
    #  白名单/恢复过滤/GUI 展示零改动即正确工作)
    dead: Optional[dict] = None
    _恢复项: bool = False  # 启动恢复项不触发本轮完成推送 (不持久化)


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
    #   ② 真实运行差分(实测样本 51 章): 停用正则后最终状态与开启时完全一致
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
        if self.task.stop_flag.is_set() or self.task.status == 'stopped':
            return
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
            pass  # 刻意静默: try 块本身在写日志, 再加日志会递归 (日志链路兜底)

    def 接收日志行(self, s: str, 落盘: bool):
        """把一行日志收进任务日志 (并可选落盘)。

        落盘=True: 来自**裸 print** 的行 —— 这些行不经统一日志系统, 不落盘就会
        从日志文件里消失, 所以必须落。
        落盘=False: 来自**日志镜像回调**的行 —— 文件里**已经有**这条记录了
        (由 日志._write 落过), 再落就变成"每行两遍"。这也是本次修复的核心。
        """
        if not s:
            return
        if 落盘:
            self._log_to_file(s)
        self.task.logs.append({
            'time': time.strftime('%H:%M:%S'),
            'msg': s,
        })
        # U19: 统计正则兜底是否仍在起作用 (正则停用时这里恒不计数)
        _前 = self._状态指纹() if self.启用正则兜底 else None
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
        _后 = self._状态指纹() if self.启用正则兜底 else None
        if _后 != _前:
            self.正则兜底数 += 1
            self.正则兜底字段.update(
                n for n, a, b in zip(self._指纹字段, _前, _后) if a != b)
        # 保留最近500条日志 (原地截断, 避免每行都重建列表)
        if len(self.task.logs) > 500:
            del self.task.logs[:-500]

    def 镜像回调(self, level, source, message):
        """日志镜像回调入口 (该线程已注册): 只进任务日志, **不再落盘**。"""
        self.接收日志行(str(message).strip(), 落盘=False)

    def _注册镜像(self):
        try:
            app_log.注册镜像回调(self.镜像回调)
        except Exception as _e:
            if app_log is not None:
                app_log.debug('任务管理', f'注册日志镜像回调失败(退化为 stdout 镜像): '
                                         f'{type(_e).__name__}: {_e}')

    def _注销镜像(self):
        try:
            app_log.注册镜像回调(None)
        except Exception as _e:
            if app_log is not None:
                app_log.debug('任务管理', f'注销日志镜像回调失败: {type(_e).__name__}: {_e}')

    def write(self, text):
        """裸 print 入口 (sys.stdout 被替换): 逐行收进任务日志**并落盘**。"""
        if text.strip():
            for line in text.strip().split('\n'):
                self.接收日志行(line.strip(), 落盘=True)
        # 同时输出到控制台（调试用）
        try:
            self.original.write(text)
        except Exception:
            pass  # 刻意静默: 高频路径(write(), 逐行/每秒级), 补日志会刷屏

    def flush(self):
        try:
            self.original.flush()
        except Exception:
            pass  # 刻意静默: 高频路径(flush(), 逐行/每秒级), 补日志会刷屏

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
        if 类型 == '清洗':
            # 2026-09-29 可观测性: 最近一章的清洗删除计数 (clean_content 发布)
            try:
                self.task.metrics.clean_summary = {
                    k: int(v) for k, v in 数据.items() if isinstance(v, (int, float))}
            except (TypeError, ValueError):
                pass        # 字段异常 → 保持上次统计 (与质检得分缺失同语义)
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
                _cands.append(_Path(os.path.join(_path_utils.get_state_root(), '数据', '站点历史.json')))
            except Exception as _e:
                if app_log:
                    app_log.debug("任务管理", f'裸 except 吞异常: {type(_e).__name__}: {_e}')
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
        except Exception as _e:
            if app_log:
                app_log.debug("任务管理", f'裸 except 吞异常: {type(_e).__name__}: {_e}')


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
        except Exception as _e:
            if app_log:
                app_log.debug("任务管理", f'裸 except 吞异常: {type(_e).__name__}: {_e}')

    def unregister(self):
        """当前线程注销 writer (爬虫线程结束时调用)"""
        with self._lock:
            self._writers.pop(threading.get_ident(), None)
        try:
            _WRITER_CTX.set(None)
        except Exception as _e:
            if app_log:
                app_log.debug("任务管理", f'裸 except 吞异常: {type(_e).__name__}: {_e}')

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
                pass  # 刻意静默: 高频路径(write(), 逐行/每秒级), 补日志会刷屏
        else:
            try:
                self._default.write(text)
            except Exception:
                pass  # 刻意静默: 高频路径(write(), 逐行/每秒级), 补日志会刷屏

    def flush(self):
        w = self._get_writer()
        if w is not None:
            try:
                w.flush()
            except Exception:
                pass  # 刻意静默: 高频路径(flush(), 逐行/每秒级), 补日志会刷屏
        else:
            try:
                self._default.flush()
            except Exception:
                pass  # 刻意静默: 高频路径(flush(), 逐行/每秒级), 补日志会刷屏

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
    if stop_flag is not None and stop_flag.is_set():
        return False
    if 闸门 is None:
        return True
    if 闸门.acquire(blocking=False):
        return True
    if 占用提示 is not None:
        try:
            占用提示()
        except Exception as _e:
            if app_log:
                app_log.debug("任务管理", f'裸 except 吞异常: {type(_e).__name__}: {_e}')
    while not 闸门.acquire(timeout=1.0):
        if stop_flag is not None and stop_flag.is_set():
            return False
    if stop_flag is not None and stop_flag.is_set():
        闸门.release()
        return False
    return True


def _排队提示(task) -> None:
    """同域排队时的可见提示 (任务日志 + 应用日志)。

    2026-10-04 (Phase 3): 同时把状态置为 **pending「等待中」**。
    旧实现在闸门排队期间任务一直是 `running` → 界面把"在排队"谎报成"抓取中",
    而 `pending` 这个状态在整条链路上从未被赋值过 (死状态), 状态徽章也就永远
    显示不出"等待中"这一档。
    """
    task.status = 'pending'
    task.logs.append({'time': time.strftime('%H:%M:%S'),
                      'msg': '[排队] 同站已有任务在运行, 等待轮转 (同域串行防封)'})
    if app_log is not None:
        try:
            app_log.info(f"任务{task.task_id}", "[排队] 同站已有任务在运行, 等待轮转")
        except Exception:
            pass  # 刻意静默: try 块本身在写日志, 再加日志会递归 (日志链路兜底)


class TaskManager:
    """多任务管理器：创建、停止、查询爬虫任务"""

    # 任务历史持久化 (2026-09-29 用户反馈"更新程序后历史记录就没了"):
    # 任务表曾是全工程唯一不落盘的对象, 重启即清零。
    # 落盘 STATE_ROOT/数据/任务历史.json, 保留最近 _历史最大条数 条;
    # logs 不存 (已全量落 日志/*.log), 上限防 JSON 膨胀。
    _历史最大条数 = 200
    _历史文件名 = '任务历史.json'

    def __init__(self, page):
        self.page = page  # Flet Page 实例，用于触发UI更新
        self.tasks: dict[str, TaskInfo] = {}
        self._lock = threading.Lock()
        self._历史写锁 = threading.Lock()
        self._counter = 0
        self._selected_task_id: str = ""       # 当前选中任务 (表格高亮/抽屉联动)
        # 死书待弹队列 (2026-10-02): 工作线程只塞 task_id, 主线程 _refresh_loop
        # 每 tick 排空至多一条 → page.run_task 弹窗 (跨线程只调度不碰控件)。
        # 纯内存: 重启后为空 → 不重弹 (与死书清单页状态一致)。
        self._死书待弹: list = []
        self._通知待弹: list = []   # 任务终态通知队列 (gui_app 每 tick 排空弹 SnackBar)
        self._加载任务历史()                    # 重启后恢复任务表 (含 running→interrupted)

    # ------------------------------------------------------ 任务历史持久化
    @staticmethod
    def _历史路径() -> Optional[str]:
        try:
            import _path_utils
            return os.path.join(_path_utils.get_state_root(), '数据',
                                TaskManager._历史文件名)
        except Exception as _e:
            if app_log is not None:
                try:
                    app_log.debug('任务管理',
                                  f'历史路径解析失败: {type(_e).__name__}: {_e}')
                except Exception:
                    pass  # 刻意静默: try 块本身在写日志, 再加日志会递归 (日志链路兜底)
            return None

    @staticmethod
    def _序列化任务(t: TaskInfo) -> dict:
        """白名单序列化: 显式逐字段构造。

        不用 dataclasses.asdict — 它对字段值 deepcopy, 而 stop_flag 是
        threading.Event (内含不可 deepcopy 的 _thread.lock), 会 TypeError。
        logs 不存 (已全量落 日志/*.log); thread/stop_flag/selected 是运行期对象。
        """
        m = t.metrics
        return {
            'task_id': t.task_id, 'url': t.url, 'title': t.title,
            'mode': t.mode,
            'progress_current': t.progress_current,
            'progress_total': t.progress_total,
            'status': t.status, 'output_file': t.output_file, 'error': t.error,
            'dead': t.dead,
            'chapter_range': (list(t.chapter_range)
                              if t.chapter_range else None),
            'threads': t.threads, 'delay': t.delay, 'resume': t.resume,
            'output_dir': t.output_dir, 'export_epub': t.export_epub,
            'incremental': t.incremental, '来源': t.来源,
            'metrics': {
                'engine': m.engine,
                'anti_spider_type': m.anti_spider_type,
                'quality_score': m.quality_score,
                'quality_passed': m.quality_passed,
                'incremental_skipped': m.incremental_skipped,
                'engine_fallback_chain': list(m.engine_fallback_chain),
                'start_time': m.start_time, 'end_time': m.end_time,
                'clean_summary': dict(m.clean_summary or {}),
            },
        }

    def _保存任务历史(self):
        """即时写 (终态流转/删除/重启后调用, 低频无需防抖)。

        锁内取快照、锁外落盘 (范式同 爬取历史._落盘 U17: 不在临界区做文件 IO);
        tmp 名带 pid+线程 id — 同进程不同线程 (stop_task 来自 UI/远控线程,
        _run_task finally 来自任务线程) 并发写时共用 tmp 会互相截断。
        resume_/checkpoint 扫描注入的展示项 (task_id 非 'task_' 前缀) 不入库:
        其数据源是 checkpoint 文件本身, 入库会造成重启后双份恢复。
        """
        path = self._历史路径()
        if not path:
            return
        try:
            with self._历史写锁:
                with self._lock:
                    条目 = [self._序列化任务(t) for t in self.tasks.values()
                            if t.task_id.startswith('task_')]
                条目 = 条目[-self._历史最大条数:]
                锚定 = Path(path).resolve()   # pathlib 锚定 (防穿越告警/路径规范)
                os.makedirs(str(锚定.parent), exist_ok=True)
                tmp = 锚定.with_name(锚定.name + f'.tmp.{os.getpid()}.{threading.get_ident()}')
                tmp.write_text(json.dumps(条目, ensure_ascii=False), encoding='utf-8')
                os.replace(tmp, 锚定)
        except Exception as _e:
            if app_log is not None:
                try:
                    app_log.debug('任务管理',
                                  f'任务历史落盘失败: {type(_e).__name__}: {_e}')
                except Exception:
                    pass  # 刻意静默: try 块本身在写日志, 再加日志会递归 (日志链路兜底)

    def _加载任务历史(self):
        """启动恢复: 重建 TaskInfo (thread/stop_flag 由 dataclass 默认值重建)。

        running → interrupted — 进程已死线程不可能还活着; end_time 归 0 且
        服务._扫描终态 只推"本进程观察过 running"的翻转 → 恢复的终态不会误推送。
        容错: 文件缺失/损坏/单条字段异常 → 跳过, 不影响其余与程序启动。
        """
        path = self._历史路径()
        if not path or not os.path.isfile(path):
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                条目 = json.load(f)
        except (OSError, ValueError) as _e:
            if app_log is not None:
                try:
                    app_log.info('任务管理',
                                 f'任务历史读取失败 (忽略): {type(_e).__name__}: {_e}')
                except Exception:
                    pass  # 刻意静默: try 块本身在写日志, 再加日志会递归 (日志链路兜底)
            return
        if not isinstance(条目, list):
            return
        _任务字段 = {f.name for f in dataclasses.fields(TaskInfo)} - {
            'thread', 'stop_flag', 'selected', 'logs', 'metrics', '_恢复项'}
        _指标字段 = {f.name for f in dataclasses.fields(TaskMetrics)}
        恢复数 = 0
        for d in 条目:
            try:
                if not isinstance(d, dict):
                    continue
                m = d.pop('metrics', None) or {}
                kwargs = {k: v for k, v in d.items() if k in _任务字段}
                if not kwargs.get('task_id') or not kwargs.get('url'):
                    continue
                if kwargs.get('chapter_range') is not None:
                    kwargs['chapter_range'] = tuple(kwargs['chapter_range'])
                t = TaskInfo(**kwargs)
                t._恢复项 = True
                t.metrics = TaskMetrics(**{k: v for k, v in m.items()
                                           if k in _指标字段})
                if t.status in ('running', 'pending'):
                    # 2026-10-04 (Phase 3): `pending`(同域排队中) 也必须转 interrupted ——
                    # 重启后线程必然已死; 若把 pending 原样留着, 它会被 `_同URL判重`
                    # 当成"活跃", 同一 URL 再次提交就被静默复用成僵尸任务。
                    t.status = 'interrupted'
                    t.error = t.error or '程序退出时中断 (可重新下载续传)'
                    t.metrics.end_time = 0.0
                self.tasks[t.task_id] = t
                恢复数 += 1
            except Exception as _e:
                if app_log is not None:
                    try:
                        app_log.debug('任务管理', '任务历史单条恢复失败 (跳过): '
                                      f'{type(_e).__name__}')
                    except Exception:
                        pass  # 刻意静默: try 块本身在写日志, 再加日志会递归 (日志链路兜底)
                continue
        if 恢复数:
            # _counter 续接存量最大 task_N, 防新任务 id 与恢复项冲突
            _最大N = 0
            for tid in self.tasks:
                _m = re.fullmatch(r'task_(\d+)', tid)
                if _m:
                    _最大N = max(_最大N, int(_m.group(1)))
            self._counter = max(self._counter, _最大N)
            if app_log is not None:
                try:
                    app_log.info('任务管理',
                                 f'任务历史已恢复 {恢复数} 条 (计数续接至 {_最大N})')
                except Exception:
                    pass  # 刻意静默: try 块本身在写日志, 再加日志会递归 (日志链路兜底)

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

    def _同URL判重(self, url: str):
        """锁内快照同 URL 现存任务, 返回 (可复用id或None, 待清理残影id列表).

        活跃判定: status∈{pending,running} 或线程仍存活。
        (2026-10-04 Phase 3: 去掉幽灵状态 `queued` —— 全工程从未给 task.status
         赋过该值, 它只是让人以为"还有第三种活跃态"。)

        本方法只读快照; 实际清理 (delete_task 自带锁) 必须由调用方在锁外执行,
        防止非重入锁自死锁。
        """
        with self._lock:
            同URL = [t for t in self.tasks.values() if t.url == url]
            for t in 同URL:
                活着 = (t.status in ("pending", "running")
                        or bool(t.thread is not None and t.thread.is_alive()))
                if 活着 and not t.stop_flag.is_set():
                    return t.task_id, []
            return None, [t.task_id for t in 同URL]

    def create_task(self, url: str, mode: str = "full",
                    chapter_range: tuple = None, threads: int = None,
                    delay: float = None, resume: bool = True,
                    output_dir: str = None, export_epub: bool = False,
                    incremental: bool = False, unique_title: bool = True) -> str:
        """创建并启动一个新爬虫任务，返回 task_id

        threads/delay 为 None (默认) 时由速度自适应模块自动选档。
        incremental=True 时启用增量抓取 (一键更新书架用, 建议 unique_title=False
        以续写原文件而非另存带序号的新文件)。

        同 URL 判重 (2026-10-02 残影事故): 批量脚本对同一本书反复提交
        (蓝屏恢复自动重提 + 失败补交 + 手动重提) 曾每次都新建一行, 任务表
        一度堆到 111 行 (真实书目仅 40)。现在:
          ① 同 URL 已有在跑/排队任务 → 幂等复用返回该 id, 不新建第二行;
          ② 同 URL 只有终态旧记录 (线程已死) → 清除残影展示项 (不删输出
             文件) 后新建本轮任务, 界面恒为该 URL 恰好一行。
        """
        活跃复用, 终态残影 = self._同URL判重(url)
        if 活跃复用 is not None:
            return 活跃复用
        for _旧id in 终态残影:
            self.delete_task(_旧id, delete_file=False)   # 锁外调用, 防自死锁
        with self._lock:
            self._counter += 1
            task_id = f"task_{self._counter}"

        task = TaskInfo(
            task_id=task_id,
            url=url,
            mode=mode,
            # 2026-10-04 (Phase 3): 新建即 `pending「等待中」` —— 线程启动后
            # 可能在同域闸门排队 (`_排队提示` 保持 pending), 真正开抓时才转 running。
            # 旧实现建好就写 running, 于是 pending 永远是死状态, 徽章也显示不出等待中。
            status="pending",
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
        self._保存任务历史()   # 先保存 running，异常退出也能恢复
        t.start()
        return task_id

    # 队列上限 (2026-10-04 修八项需求 #2): 主循环每秒只弹一条、每条 SnackBar 6 秒,
    # 无界队列会让"一批任务集中结束"后的通知滞后很久且用户取消不掉。满则丢最旧 ——
    # 保住最近发生的 (用户最关心的正是刚出结果的那本)。
    _通知上限 = 5
    _死书待弹上限 = 20

    def _入队通知(self, item: dict) -> None:
        """线程安全入队 + 相邻去重 + 有界 (2026-10-04 #2 修复)。

        - **相邻去重**: 同一本书连续两次同状态 (例如失败→重试→又失败) 合并为一条,
          保留最新原因, 避免同一本书刷满队列;
        - **有界**: 超出上限丢最旧的, 防止通知无休止滞后。
        与 `_死书待弹` 使用同一把 `_lock`, 纪律统一 (旧实现 append 不持锁、pop 持锁)。
        """
        with self._lock:
            队列 = self._通知待弹
            if (队列 and 队列[-1].get('书名') == item.get('书名')
                    and 队列[-1].get('状态') == item.get('状态')):
                队列[-1] = item
                return
            队列.append(item)
            超出 = len(队列) - self._通知上限
            if 超出 > 0:
                del 队列[:超出]

    def _set_terminal(self, task: TaskInfo, status: str):
        """置为终态 (completed/failed/stopped/dead_pending) 并冻结耗时 end_time。

        八项需求 #2: completed/failed/dead_pending 入**终态通知队列** (工作线程
        侧只碰数据, gui_app 每 tick 排空弹 SnackBar) 并播放提示音效 —— 用户
        后台挂机时靠声音感知任务成败。stopped 是用户主动操作, 不通知不响铃
        (自己停的自己知道)。音效 winsound 为 Windows 内置模块, 零依赖;
        非 Windows / 声音设备缺失时静默跳过 (通知文案仍入队)。

        2026-10-04 (#2 审查修复): ①状态改为**显式白名单** —— 旧实现 `else` 把任何
        非 completed/stopped 的状态都当"失败"通知, 将来新增状态会静默变假失败;
        ②**幂等** —— 同一任务重复以同一终态调用不再重复入队/重复响铃。
        """
        _原先状态 = getattr(task, 'status', '')
        task.status = status
        if task.metrics:
            task.metrics.end_time = time.time()
        if status not in ('completed', 'failed', 'dead_pending'):
            return                      # stopped 及未来状态: 不通知不响铃
        if _原先状态 == status:
            return                      # 幂等: 重复置同终态不重复打扰
        书名 = (task.title or '').strip() or '未知书名'
        if status == "completed":
            self._入队通知({'书名': 书名, '状态': 'success', '原因': ''})
        else:
            # failed / dead_pending: 失败原因优先 task.error, 死书用判定原因
            原因 = ''
            if isinstance(task.dead, dict):
                原因 = f"{task.dead.get('类型', '')}: {task.dead.get('原因', '')}"
            elif task.error:
                原因 = task.error
            self._入队通知({'书名': 书名, '状态': 'fail', '原因': 原因[:200]})
        self._播放终态音效(status)

    @staticmethod
    def _播放终态音效(status: str) -> None:
        """终态提示音 (八项需求 #2): 成功叮咚 / 失败低鸣。线程安全, 失败留痕。

        2026-10-04 (#2 修复): 先查用户偏好 `提示音` —— 关掉后**完全静默**
        (通知 SnackBar 仍照常弹, 只是不响), 解决"夜间挂机被强制响铃"的抱怨。
        """
        try:
            import 界面偏好
            if not 界面偏好.取('提示音', True):
                return
        except Exception as _e偏好:
            if app_log:
                app_log.debug('任务管理',
                              f'提示音偏好读取失败, 按默认(响)处理: {type(_e偏好).__name__}')
        try:
            import winsound
            if status == "completed":
                winsound.MessageBeep(winsound.MB_ICONASTERISK)   # 成功: 叮
            else:
                winsound.MessageBeep(winsound.MB_ICONHAND)       # 失败: 低鸣
        except Exception as _e:
            if app_log:
                app_log.debug('任务管理',
                              f'提示音未播放(非 Windows/无声音设备): {type(_e).__name__}: {_e}')

    def 取一条待弹通知(self) -> dict:
        """主线程消费终态通知队列 (加锁 pop, 空则返回 None)。每 tick 至多取一条。"""
        with self._lock:
            return self._通知待弹.pop(0) if self._通知待弹 else None

    def _该收尾成功(self, task: TaskInfo) -> bool:
        """是否该做"成功收尾" —— **按最终状态判定**, 不看"谁先置的状态"。

        2026-10-06 修复的真实 bug: 旧实现把收尾写在
        `if ... and task.status == "running":` 分支内部, 但抓取过程中
        `_应用完成终态()`(完成事件通路 :367 / 正则通路 :226) **早已**把 status
        置成 'completed' → 进不了那个分支 → 收尾(清死书记录/记网站清单)永不执行。
        实测: 历史日志里从未出现 `已移除死书记录`; 三条 10-03 的死书记录在
        对应任务早已 completed 时仍留在清单里。
        提成独立方法是为了让这个判断可被测试直接钉住 (见 test_死书自动清理.py)。
        """
        return self._is_task_thread_owner(task) and task.status == "completed"

    def _收尾成功(self, task: TaskInfo, url: str) -> None:
        """成功收尾 (数据层, 工作线程): 清死书记录 + 记网站清单。

        两件都是纯 bookkeeping, 失败**不得**影响抓取结果 —— 故各自 try 包住,
        只留痕不抛。调用点见 _run_task 末尾 (先过 _该收尾成功)。
        """
        # 阶段5 (重新检测): 抓成功 ⇒ 该网址不再是死书, 移除死书清单记录。
        # 清理**必须挂在数据层**, 不能靠死书清单页刷新时顺带处理 ——
        # 重检后用户多半直接切到任务表看进度, 不在本页;
        # 若清理挂 UI, 记录会一直躺在清单里, 用户以为"重新检测没用"。
        try:
            from 死书处理 import 标记已恢复
            恢复 = 标记已恢复(url)
            if 恢复.get('移除'):
                task.dead = None      # 抓成功 ⇒ 同步清任务上的死书标记
                if app_log is not None:
                    app_log.info(f"任务{task.task_id}",
                                 f"抓取成功, 已移除死书记录: {url}")
        except Exception as _e_恢复:
            if app_log is not None:
                app_log.debug(f"任务{task.task_id}",
                              f"死书记录清理失败 (不影响抓取结果): "
                              f"{type(_e_恢复).__name__}")
        # v2.4.28: 抓取成功 → 自动记录 网站清单 (网址+站名+书名, 去重)。
        # 任务可能因站点异常只抓到部分章节 (failed>0 也算已尽力跑完),
        # 书名由 '标题' 事件回填; 未拿到书名时仍记录网址+网站名占位
        try:
            from 网站清单 import 记录 as _记清单, 域名网站名
            _记清单(url, 域名网站名(url), (task.title or '').strip())
        except Exception as _e_清单:
            if app_log is not None:
                app_log.debug(f"任务{task.task_id}",
                              f"网站清单记录失败 (不影响抓取结果): "
                              f"{type(_e_清单).__name__}")

    def _记死书(self, task: TaskInfo, exc: Exception) -> None:
        """死书失败落点 (工作线程, 只碰数据不碰控件)。

        非 死书错误 → 一行 no-op 直接返回。命中时: 登记死书清单 + 置状态
        dead_pending + 首次才入待弹队列 (避免同一本书反复弹窗打扰)。
        """
        try:
            from 死书处理 import 死书错误, 记录死书
        except Exception as _e:
            if app_log:
                app_log.debug('任务管理', f'裸 except 吞异常: {type(_e).__name__}: {_e}')
            return
        if not isinstance(exc, 死书错误):
            return
        try:
            # 八项需求 #3 (2026-10-04 修复): "书籍与网站同时失效"信号改为**结构化携带**。
            # 死书错误.网站失效 由 判定死书 在判定侧算出 (DNS 层失效特征), 随异常到此处。
            # 旧实现对 str(exc) 做 是网站失效异常() 嗅探 —— 而 str(exc) 恒为判定死书的
            # 4 条固定文案(不含任何特征串), 该条件**恒 False**, 记录['网站失效'] 永不置位,
            # gui_app._弹双失效 成了死代码 (2026-10-04 审查发现, 见 文档/审查报告汇总.md)。
            # 这里不再嗅探, 只读标志, 并交给 记录死书 落盘 (清单页/重启后仍可见)。
            网站失效 = bool(getattr(exc, '网站失效', False))
            记录, 首次 = 记录死书(task.url, task.title, exc.类型, exc.原因, task.task_id,
                                  网站失效=网站失效)
            task.dead = 记录
            task.status = 'dead_pending'      # end_time 由随后的 _set_terminal 冻结
            if 首次:
                with self._lock:
                    队列 = self._死书待弹
                    if task.task_id not in 队列:
                        队列.append(task.task_id)
                    超出 = len(队列) - self._死书待弹上限
                    if 超出 > 0:
                        del 队列[:超出]
        except Exception as _e2:
            if app_log:
                app_log.debug('任务管理', f'裸 except 吞异常: {type(_e2).__name__}: {_e2}')

    def 取一条待弹死书(self) -> str:
        """主线程消费待弹队列 (加锁 pop, 空则返回空串)。每 tick 至多取一条。"""
        with self._lock:
            return self._死书待弹.pop(0) if self._死书待弹 else ''

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
        # 再注册**日志镜像回调** (2026-10-06 日志去重): 本线程的统一日志记录直接进
        # 任务日志, 不再绕 stdout 镜像 —— 否则镜像会被上面的重定向器再落盘一次,
        # 日志文件里每条出现两遍 (日志页看起来"每行重复")。
        重定向器._注册镜像()
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
            # 同站并发事故 (2026-09-12): GUI 批量 11 URL 同站并发 → WAF 拦截;
            # 排队期间任务状态为 pending「等待中」(2026-10-04 Phase 3 修正:
            # 旧实现排队期间谎报 running), 日志可见, 可被停止打断。
            同域闸门 = _取域闸门(url)
            已获闸 = _获取域闸门(同域闸门, task.stop_flag,
                                占用提示=lambda: _排队提示(task))
            if not 已获闸:
                return  # 排队等待中被停止 (stop_task 已置终态)
            # 拿到闸门 = 真正开抓, 由「等待中」转「抓取中」
            task.status = 'running'
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
            # ⚠️ 2026-10-06 修复(真 bug / 同类于"代码存在但不可达"):
            # 下面这段"成功收尾"原先挂在上面那个 `status == "running"` 分支**内部**,
            # 但抓取过程中的"完成"事件通路(_应用完成终态, 见本文件 :367)与正则通路(:226)
            # **早就把 status 置成 'completed' 了** → 收尾永远不执行。
            # 实测证据: ①历史日志里从未出现过 `已移除死书记录`;
            #          ②三条 10-03 的死书清单记录, 在对应任务早已 completed 的情况下仍在清单里
            #            (用户 2026-10-06 报告"这本书在死书清单上, 为什么还能爬/还在清单里")。
            # 现按**最终状态**判定(_该收尾成功), 与"谁先置的状态"无关。
            if self._该收尾成功(task):
                self._收尾成功(task, url)
        except Exception as e:
            if self._is_task_thread_owner(task) and not task.stop_flag.is_set():
                # 八项需求 #2 顺序修正: 先填 error / 判死书, 再置终态 ——
                # _set_terminal 里的终态通知要展示真实失败原因 (旧序 task.error
                # 尚为空, 通知原因恒为 ''), 死书路径还能带上 dead 判定原因
                task.error = str(e)
                self._记死书(task, e)      # 死书失败落点 (非死书异常为一行 no-op)
                self._set_terminal(
                    task,
                    task.status if task.status == 'dead_pending' else "failed")
                task.logs.append({
                    'time': time.strftime('%H:%M:%S'),
                    'msg': f"[错误] {e}"
                })
            if app_log is not None:
                app_log.error_exc(f"任务{task.task_id}", f"任务异常: {e}", e)
        finally:
            _THREAD_STDOUT.unregister()
            重定向器._注销镜像()      # 线程复用必须注销, 否则回调悬空 (同 _THREAD_STDOUT)
            try:
                import 任务事件
                任务事件.退订(重定向器)      # U19: 退订, 防线程复用/重复注册
            except Exception as _e:
                if app_log:
                    app_log.debug("任务管理", f'裸 except 吞异常: {type(_e).__name__}: {_e}')
            try:
                # U19 诊断: 一轮任务的"事件 vs 正则兜底"统计, 供判断能否删除正则
                if app_log is not None:
                    app_log.info(f"任务{task.task_id}", 重定向器.覆盖率摘要())
            except Exception:
                pass  # 刻意静默: try 块本身在写日志, 再加日志会递归 (日志链路兜底)
            # 任务历史持久化: 每轮任务结束 (completed/failed/中断退出) 落一次盘
            self._保存任务历史()

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
        if 受理:
            self._保存任务历史()   # stopped 终态即时落盘 (锁外)
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
            # 文件仍被 worker 使用时，停止并拒绝立即删文件；下一次可安全重试。
            if delete_file and task.thread is not None and task.thread.is_alive():
                task.stop_flag.set()
                self._set_terminal(task, "stopped")
                return False
            # 停止仍在运行的任务
            task.stop_flag.set()
            if task.status == "running":
                self._set_terminal(task, "stopped")
            self.tasks.pop(task_id, None)
            if self._selected_task_id == task_id:
                self._selected_task_id = ""
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
        self._保存任务历史()   # 删除后同步历史 (防止已删条目重启后"复活")
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
            if task.status == "running" or (task.thread is not None and task.thread.is_alive()):
                return False
            task._恢复项 = False
            # L1 修复: 重置/登记线程的整段移入锁内 (旧实现检查与重置分离,
            # 并发的 delete_task/stop_task 可插入造成僵尸线程)
            task.progress_current = 0
            task.progress_total = 0
            task.status = "running"
            task.logs = TaskLogBuffer()
            task.error = ""
            task.dead = None      # 重下成功后清死书标记 (2026-10-02, 与 error 同处)
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
        self._保存任务历史()   # 重启后 running 状态落盘 (下次启动恢复为 interrupted)
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
