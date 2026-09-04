# -*- coding: utf-8 -*-
"""书架清单: 记录已抓取小说 (标题/目录URL/输出文件), 供"一键更新"复用

设计 (对齐 ying-ck record.json / fanqienovel-downloader 一键更新):
  - 每次抓取成功 (run_crawl full/range) 自动登记一本书到 数据/书架.json
  - "一键更新"遍历书架, 对每本以 增量+断点续传 方式重新抓取,
    已抓取且内容未变化的章节自动跳过 (爬取历史模块判定), 减少重复请求
"""
import json
import os
import time
import threading

try:
    from _path_utils import get_app_base_dir
except Exception:
    get_app_base_dir = None

_io_lock = threading.Lock()


def 书架路径() -> str:
    """数据/书架.json (BASE_DIR 下的运行时数据目录)"""
    if get_app_base_dir is not None:
        base = get_app_base_dir()
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = os.path.join(base, "数据", "书架.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


def 加载() -> list:
    """读取书架清单; 损坏/不存在时返回空列表"""
    try:
        with open(书架路径(), 'r', encoding='utf-8') as f:
            items = json.load(f)
        return items if isinstance(items, list) else []
    except Exception:
        return []


def 保存(items) -> bool:
    """整体写回书架清单"""
    try:
        with open(书架路径(), 'w', encoding='utf-8') as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def 记录(标题: str, 目录URL: str, 输出文件: str = '') -> None:
    """按目录URL upsert 一条书架记录 (同一本书不重复)"""
    if not 目录URL:
        return
    with _io_lock:
        items = 加载()
        now = time.strftime('%Y-%m-%d %H:%M:%S')
        for it in items:
            if it.get('目录URL') == 目录URL:
                if 标题:
                    it['标题'] = 标题
                if 输出文件:
                    it['输出文件'] = 输出文件
                it['最后更新'] = now
                break
        else:
            items.append({'标题': 标题, '目录URL': 目录URL,
                          '输出文件': 输出文件 or '',
                          '最后更新': now})
        保存(items)


def 移除(目录URL: str) -> None:
    """从书架移除一条记录 (按目录URL)"""
    with _io_lock:
        items = [it for it in 加载() if it.get('目录URL') != 目录URL]
        保存(items)


def 列出() -> list:
    """返回书架清单副本 (按最后更新倒序)"""
    items = 加载()
    items.sort(key=lambda it: it.get('最后更新', ''), reverse=True)
    return items
