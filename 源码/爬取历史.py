# -*- coding: utf-8 -*-
import 日志 as _app_log
_log = _app_log.get('爬取历史')

"""爬取历史记录
================

按 URL 维度持久化每次请求的元信息: 状态码、响应耗时、内容哈希、字节大小、
抓取结果(新增/更新/未变化/失败)和错误原因。支持:

1. **增量爬取**: 通过 `是否已抓取且未变化(url, max_age_hours)` 判断某 URL
   是否在指定时间窗口内成功抓取过, 主流程据此跳过未变更页面, 减少重复请求。
2. **内容变化检测**: 每次抓取计算 SHA-256 哈希, 与上次记录比较,
   自动标记结果类型 (新增/更新/未变化/失败)。
3. **查询与统计**: `查询()` 支持按域名/时间范围/结果过滤; `统计()` 输出
   各结果类型的计数, 便于排查失败站点。

存储位置: BASE_DIR/数据/爬取历史.json (原子写入 os.replace, 线程安全)

数据结构:
{
    "example.com": {
        "域名": "example.com",
        "首次抓取": "2026-09-02 12:00:00",
        "最近抓取": "2026-09-02 15:30:00",
        "总请求数": 100,
        "统计": {"新增": 80, "更新": 5, "未变化": 13, "失败": 2},
        "URLs": {
            "https://example.com/book/1/ch1.html": {
                "首次抓取": "2026-09-02 12:00:00",
                "最后抓取": "2026-09-02 15:30:00",
                "状态码": 200,
                "耗时秒": 1.23,
                "字节大小": 12345,
                "内容哈希": "sha256:abcdef...",
                "结果": "未变化",
                "错误原因": "",
                "变更次数": 0
            }
        }
    }
}

设计原则:
- 纯标准库实现, 读写失败静默降级 (绝不影响主爬取流程)
- 单例 + threading.Lock 保证并发写入一致性
- 原子替换 (临时文件 + os.replace) 避免写一半损坏
- 每个 URL 只保留最新一条记录 (历史变更次数累计), 控制文件体积
"""

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

# 每站点最多保留的 URL 条数 (LRU 截断, 避免长期运行后文件无限增长)
_MAX_URLS_PER_SITE = 5000
# 结果类型常量 (对外字符串契约, 不要改动)
RESULT_NEW = '新增'
RESULT_UPDATE = '更新'
RESULT_UNCHANGED = '未变化'
RESULT_FAIL = '失败'


class 爬取历史:
    """爬取历史记录管理器 (单例, 线程安全)"""

    _instance = None
    _init_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if getattr(self, '_ready', False):
            return
        self._ready = True
        self._file = self._取存储路径()
        self._io_lock = threading.Lock()
        self._数据 = self._加载()

    # ------------------------------------------------------------------
    # 存储层
    # ------------------------------------------------------------------
    @staticmethod
    def _取存储路径() -> str:
        try:
            import _path_utils
            base = _path_utils.get_app_base_dir()
        except Exception:
            base = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(base, '数据')
        try:
            os.makedirs(data_dir, exist_ok=True)
        except OSError:
            pass
        return os.path.join(data_dir, '爬取历史.json')

    def _加载(self) -> dict:
        try:
            with open(self._file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
        return {}

    def _保存(self):
        """原子写入 (临时文件 + os.replace); 失败只打印日志, 不抛异常"""
        try:
            fobj = Path(self._file).resolve()   # pathlib 锚定, 防路径穿越
            tmp = fobj.with_name(fobj.name + '.tmp')
            tmp.write_text(json.dumps(self._数据, ensure_ascii=False, indent=2),
                           encoding='utf-8')
            os.replace(tmp, fobj)
        except OSError as e:
            _log.info(f"[爬取历史] 保存失败: {e}")

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    @staticmethod
    def 取域名(url: str) -> str:
        """从 URL 提取规范域名 (小写, 去端口和 www. 前缀)"""
        try:
            host = urlparse(url).hostname
            if not host:
                return ''
            return host[4:] if host.startswith('www.') else host
        except Exception:
            return ''

    @staticmethod
    def _计算哈希(content: bytes) -> str:
        """计算 bytes 的 SHA-256 哈希 (带前缀, 便于人读)"""
        if not content:
            return ''
        return 'sha256:' + hashlib.sha256(content).hexdigest()

    @staticmethod
    def _规范时间戳(时间字符串: str) -> float:
        """把 'YYYY-MM-DD HH:MM:SS' 转 time.mktime; 失败返回 0"""
        try:
            return time.mktime(time.strptime(时间字符串, '%Y-%m-%d %H:%M:%S'))
        except (ValueError, TypeError):
            return 0.0

    def _取站点记录(self, 域名: str, 创建: bool = False) -> dict:
        """获取/创建站点节点 (调用方需持有 _io_lock)"""
        站点 = self._数据.get(域名)
        if not isinstance(站点, dict):
            if not 创建:
                return {}
            站点 = {
                '域名': 域名, '首次抓取': '', '最近抓取': '',
                '总请求数': 0,
                '统计': {RESULT_NEW: 0, RESULT_UPDATE: 0,
                         RESULT_UNCHANGED: 0, RESULT_FAIL: 0},
                'URLs': {},
            }
            self._数据[域名] = 站点
        站点.setdefault('统计', {RESULT_NEW: 0, RESULT_UPDATE: 0,
                                 RESULT_UNCHANGED: 0, RESULT_FAIL: 0})
        站点.setdefault('URLs', {})
        return 站点

    # ------------------------------------------------------------------
    # 对外 API
    # ------------------------------------------------------------------
    def 记录请求(self, url: str, 状态码: int, 耗时秒: float,
                 content: bytes = b'', 错误原因: str = '') -> str:
        """记录一次请求结果, 返回本次结果类型 (新增/更新/未变化/失败)。

        Args:
            url: 请求的 URL (完整)
            状态码: HTTP 状态码 (0 表示未拿到响应)
            耗时秒: 请求耗时
            content: 响应体字节 (用于计算哈希和字节大小; 失败时传 b'')
            错误原因: 失败原因描述 (成功时为空)

        Returns:
            '新增' / '更新' / '未变化' / '失败'
        """
        域名 = self.取域名(url)
        if not 域名:
            return RESULT_FAIL

        失败 = bool(错误原因) or not (200 <= int(状态码 or 0) < 400)
        新哈希 = self._计算哈希(content) if not 失败 else ''
        字节大小 = len(content) if content else 0
        now = time.strftime('%Y-%m-%d %H:%M:%S')

        try:
            with self._io_lock:
                站点 = self._取站点记录(域名, 创建=True)
                if not 站点.get('首次抓取'):
                    站点['首次抓取'] = now
                站点['最近抓取'] = now
                站点['总请求数'] = int(站点.get('总请求数', 0)) + 1

                urls = 站点['URLs']
                旧记录 = urls.get(url)
                旧哈希 = 旧记录.get('内容哈希', '') if isinstance(旧记录, dict) else ''

                if 失败:
                    结果 = RESULT_FAIL
                elif not 旧记录:
                    结果 = RESULT_NEW
                elif 新哈希 and 新哈希 == 旧哈希:
                    结果 = RESULT_UNCHANGED
                else:
                    结果 = RESULT_UPDATE

                # 统计计数 (站点级)
                统计 = 站点['统计']
                统计[结果] = int(统计.get(结果, 0)) + 1

                # URL 级记录 (只保留最新一条)
                新记录 = {
                    '首次抓取': (旧记录.get('首次抓取', now)
                                if isinstance(旧记录, dict) else now),
                    '最后抓取': now,
                    '状态码': int(状态码 or 0),
                    '耗时秒': round(float(耗时秒 or 0), 3),
                    '字节大小': 字节大小,
                    '内容哈希': 新哈希,
                    '结果': 结果,
                    '错误原因': 错误原因 or '',
                    '变更次数': int(旧记录.get('变更次数', 0)
                                    if isinstance(旧记录, dict) else 0)
                                + (1 if 结果 == RESULT_UPDATE else 0),
                }
                urls[url] = 新记录

                # LRU 截断: 超过上限时按最后抓取时间淘汰最旧的
                if len(urls) > _MAX_URLS_PER_SITE:
                    旧项 = sorted(urls.items(),
                                  key=lambda kv: kv[1].get('最后抓取', ''))[
                        :len(urls) - _MAX_URLS_PER_SITE]
                    for k, _ in 旧项:
                        urls.pop(k, None)

                self._保存()
        except Exception as e:
            # 任何异常都不能影响主流程
            _log.info(f"[爬取历史] 记录异常: {e}")
            return RESULT_FAIL
        return 结果

    def 查URL(self, url: str) -> dict:
        """查询单个 URL 的历史记录 (返回副本, 无记录返回 {})"""
        域名 = self.取域名(url)
        if not 域名:
            return {}
        with self._io_lock:
            站点 = self._数据.get(域名)
            if not isinstance(站点, dict):
                return {}
            记录 = 站点.get('URLs', {}).get(url)
            return dict(记录) if isinstance(记录, dict) else {}

    def 查站点(self, url: str) -> dict:
        """查询某站点完整历史 (返回副本, 无记录返回 {})"""
        域名 = self.取域名(url)
        if not 域名:
            return {}
        with self._io_lock:
            站点 = self._数据.get(域名)
            return dict(站点) if isinstance(站点, dict) else {}

    def 是否已抓取且未变化(self, url: str, max_age_hours: float = 24) -> bool:
        """判断 URL 是否在指定时间窗口内成功抓取且内容未变化 (供增量爬取跳过用)。

        Args:
            url: 待检查的 URL
            max_age_hours: 时间窗口 (小时), 默认 24。
                <=0 表示禁用增量跳过 (一律返回 False, 总是重新抓取, 更安全)。

        Returns:
            True=可跳过 (最近一次为新增/未变化/更新且在窗口内, 且非失败)
        """
        if not max_age_hours or max_age_hours <= 0:
            return False   # 禁用增量, 总是重新抓取
        记录 = self.查URL(url)
        if not 记录:
            return False
        if 记录.get('结果') == RESULT_FAIL:
            return False
        最后抓取 = self._规范时间戳(记录.get('最后抓取', ''))
        if 最后抓取 <= 0:
            return False
        已过小时 = (time.time() - 最后抓取) / 3600.0
        if 已过小时 > max_age_hours:
            return False
        return True

    def 查询(self, 域名: str = None, 起始时间: str = None,
             结束时间: str = None, 结果: str = None) -> list:
        """按条件查询 URL 历史, 返回记录列表 (按时间倒序)。

        Args:
            域名: 仅查询该域名 (None=全部)
            起始时间: 'YYYY-MM-DD HH:MM:SS' (含, None=不限)
            结束时间: 'YYYY-MM-DD HH:MM:SS' (含, None=不限)
            结果: 仅筛选该结果类型 (新增/更新/未变化/失败, None=全部)

        Returns:
            [{域名, url, ...记录字段}, ...]
        """
        起始ts = self._规范时间戳(起始时间) if 起始时间 else 0
        结束ts = self._规范时间戳(结束时间) if 结束时间 else float('inf')
        结果列表 = []
        with self._io_lock:
            域名列表 = [域名] if 域名 else list(self._数据.keys())
            for d in 域名列表:
                站点 = self._数据.get(d)
                if not isinstance(站点, dict):
                    continue
                for url, 记录 in 站点.get('URLs', {}).items():
                    if not isinstance(记录, dict):
                        continue
                    if 结果 and 记录.get('结果') != 结果:
                        continue
                    ts = self._规范时间戳(记录.get('最后抓取', ''))
                    if ts < 起始ts or ts > 结束ts:
                        continue
                    项 = {'域名': d, 'url': url}
                    项.update(记录)
                    结果列表.append(项)
        结果列表.sort(key=lambda x: x.get('最后抓取', ''), reverse=True)
        return 结果列表

    def 统计(self, 域名: str = None, 起始时间: str = None,
             结束时间: str = None) -> dict:
        """按条件统计各结果类型计数。

        Args:
            域名: 仅统计该域名 (None=全部)
            起始时间/结束时间: 时间范围 (同 查询)

        Returns:
            {'新增': N, '更新': N, '未变化': N, '失败': N, '总请求数': N}
        """
        汇总 = {RESULT_NEW: 0, RESULT_UPDATE: 0,
                RESULT_UNCHANGED: 0, RESULT_FAIL: 0, '总请求数': 0}
        # 直接遍历 URL 级记录, 避免站点级累计受 LRU 截断影响
        for 项 in self.查询(域名=域名, 起始时间=起始时间, 结束时间=结束时间):
            r = 项.get('结果')
            if r in 汇总:
                汇总[r] += 1
            汇总['总请求数'] += 1
        return 汇总

    def 列出全部站点(self) -> list:
        """列出所有站点的简要信息 (按最近抓取时间倒序)"""
        with self._io_lock:
            结果 = []
            for v in self._数据.values():
                if not isinstance(v, dict):
                    continue
                项 = {'域名': v.get('域名', ''),
                      '首次抓取': v.get('首次抓取', ''),
                      '最近抓取': v.get('最近抓取', ''),
                      '总请求数': v.get('总请求数', 0),
                      '统计': dict(v.get('统计', {})),
                      'URL数': len(v.get('URLs', {}))}
                结果.append(项)
        结果.sort(key=lambda s: s.get('最近抓取', ''), reverse=True)
        return 结果


_默认实例 = None


def 取爬取历史() -> 爬取历史:
    """获取全局单例 (延迟初始化, 导入失败安全)"""
    global _默认实例
    if _默认实例 is None:
        _默认实例 = 爬取历史()
    return _默认实例
