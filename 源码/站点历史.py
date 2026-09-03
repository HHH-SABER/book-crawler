# -*- coding: utf-8 -*-
import 日志 as _app_log
_log = _app_log.get('站点历史')

"""站点抓取历史记录
==================

跨会话持久化每个站点的抓取记录: 抓过的书籍、任务数、反爬机制命中
统计、质检通过率等, 为后续抓取提供先验知识 (如已知站点存在频率限制
时建议加大章节间隔)。

存储位置: BASE_DIR/数据/站点历史.json (原子写入, 线程安全)

数据结构:
{
    "example.com": {
        "域名": "example.com",
        "首次抓取": "2026-09-02 12:00:00",
        "最近抓取": "2026-09-02 15:30:00",
        "任务数": 3,
        "反爬统计": {"rate_limit": 2, "waf_captcha": 1},
        "书籍": [
            {
                "书名": "某某小说",
                "时间": "2026-09-02 15:30:00",
                "总章数": 1200,
                "失败章数": 0,
                "输出文件": "某某小说.txt",
                "质检摘要": {"质检章数": 1200, "通过": 1198, "未通过": 2, "平均分": 93.5},
                "反爬统计": {"rate_limit": 2}
            }
        ]
    }
}

设计原则: 纯标准库实现, 读写失败静默降级 (不影响主流程抓取)。
"""

import json
import os
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

_MAX_BOOKS_PER_SITE = 50   # 每站点最多保留的书籍记录条数


class 站点历史:
    """站点抓取历史 (单例, 线程安全)"""

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
        return os.path.join(data_dir, '站点历史.json')

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
        try:
            fobj = Path(self._file).resolve()   # pathlib 锚定, 防路径穿越
            tmp = fobj.with_name(fobj.name + '.tmp')
            tmp.write_text(json.dumps(self._数据, ensure_ascii=False, indent=2),
                           encoding='utf-8')
            os.replace(tmp, fobj)   # 原子替换, 避免写一半损坏
        except OSError as e:
            _log.info(f"[站点历史] 保存失败: {e}")

    # ------------------------------------------------------------------
    # 对外 API
    # ------------------------------------------------------------------
    @staticmethod
    def 取域名(url: str) -> str:
        """从 URL 提取规范域名 (小写, 去端口和 www. 前缀)"""
        try:
            host = urlparse(url).hostname   # 已小写且不含端口
            if not host:
                return ''
            return host[4:] if host.startswith('www.') else host
        except Exception:
            return ''

    def 记录任务(self, catalog_url, book_title, total, failed,
                 反爬统计=None, 质检摘要=None, output_file=''):
        """整书任务完成后记录一条历史。

        Args:
            catalog_url: 目录页 URL (用于提取域名)
            book_title: 小说标题
            total: 本次任务总章数
            failed: 失败章节号列表
            反爬统计: {机制: 次数} (爬虫._反爬统计)
            质检摘要: {'质检章数','通过','未通过','平均分'}
            output_file: 输出文件路径 (仅记录文件名)
        """
        域名 = self.取域名(catalog_url)
        if not 域名 or not book_title:
            return
        with self._io_lock:
            站点 = self._数据.get(域名)
            if not isinstance(站点, dict):
                站点 = {'域名': 域名, '首次抓取': '', '最近抓取': '',
                        '任务数': 0, '反爬统计': {}, '书籍': []}
                self._数据[域名] = 站点
            now = time.strftime('%Y-%m-%d %H:%M:%S')
            if not 站点.get('首次抓取'):
                站点['首次抓取'] = now
            站点['最近抓取'] = now
            站点['任务数'] = int(站点.get('任务数', 0)) + 1

            记录 = {
                '书名': book_title,
                '时间': now,
                '总章数': total,
                '失败章数': len(failed) if failed else 0,
                '输出文件': os.path.basename(output_file) if output_file else '',
            }
            if 反爬统计:
                记录['反爬统计'] = dict(反爬统计)
                汇总 = 站点.setdefault('反爬统计', {})
                for k, v in 反爬统计.items():
                    汇总[k] = int(汇总.get(k, 0)) + v
            if 质检摘要:
                记录['质检摘要'] = dict(质检摘要)

            # 同书重抓只保留最近一条记录
            站点['书籍'] = [b for b in 站点.get('书籍', [])
                           if isinstance(b, dict) and b.get('书名') != book_title]
            站点['书籍'].append(记录)
            if len(站点['书籍']) > _MAX_BOOKS_PER_SITE:
                站点['书籍'] = 站点['书籍'][-_MAX_BOOKS_PER_SITE:]
            self._保存()

    def 查站点(self, url) -> dict:
        """查询某站点的历史信息 (返回副本, 无记录返回 {})"""
        域名 = self.取域名(url)
        if not 域名:
            return {}
        with self._io_lock:
            记录 = self._数据.get(域名)
            return dict(记录) if isinstance(记录, dict) else {}

    def 列出全部(self) -> list:
        """列出所有站点的历史信息 (按最近抓取时间倒序)"""
        with self._io_lock:
            结果 = [dict(v) for v in self._数据.values() if isinstance(v, dict)]
        结果.sort(key=lambda s: s.get('最近抓取', ''), reverse=True)
        return 结果

    def 取反爬先验(self, url) -> dict:
        """返回站点历史反爬统计 (供主流程调整初始策略)"""
        return self.查站点(url).get('反爬统计') or {}


_默认实例 = None


def 取站点历史() -> 站点历史:
    """获取全局单例 (延迟初始化, 导入失败安全)"""
    global _默认实例
    if _默认实例 is None:
        _默认实例 = 站点历史()
    return _默认实例
