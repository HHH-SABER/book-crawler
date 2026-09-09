# -*- coding: utf-8 -*-
"""远控服务 FastAPI 层: 手机/外部设备对 TaskManager 的唯一 HTTP 入口。

端点一览 (/api/v1, 除 healthz 与面板外均需 token):
  GET  /                          面板 (单页 HTML, JS 持 token 调 API)
  GET  /api/v1/healthz            健康检查 (免鉴权, 供看门狗)
  POST /api/v1/tasks              发任务 {url, mode?, resume?, export_epub?}
  GET  /api/v1/tasks              任务列表 (含进度/状态/耗时)
  GET  /api/v1/tasks/{id}/logs?after=N   日志增量 (返回 total/entries/截断)
  GET  /api/v1/tasks/{id}/logs/stream    日志 SSE 流 (EventSource 可用 ?k= 鉴权)
  POST /api/v1/tasks/{id}/stop    停止任务
  GET  /api/v1/books              书架 (扫 抓取结果/*.txt, 合并 书架.json 标题)
  GET  /api/v1/books/{id}/epub    EPUB 下载 (按需生成, txt mtime 失效缓存)

健壮性要点 (自检清单):
- 鉴权用 hmac.compare_digest 常时比较; token 走 ?k= 或 Authorization: Bearer
- 日志增量: 客户端持 after 指针; 若服务端日志被 500 条截断导致 total < after,
  返回 entries 从 0 起并置 截断=True, 客户端据此重置指针 (否则会永久漏日志)
- 书籍 id = 文件绝对路径 md5 前 12 位; 下载按 id 反查路径, 杜绝路径穿越
- 爬虫重依赖 (requests/selenium 链) 惰性导入: 仅 POST /tasks 与 EPUB 生成时触达
- TaskManager 线程只写数据, 本层只读快照 (GIL 下 list/dict 读安全)
"""
import asyncio
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse

from _path_utils import get_default_output_dir
from .配置 import 取配置

app = FastAPI(title="小说爬虫远控", docs_url=None, redoc_url=None, openapi_url=None)

_面板路径 = Path(__file__).with_name("面板.html")

_task_manager = None   # 惰性单例 (TaskManager(page=None), 无 flet 依赖)


def _任务管理器():
    global _task_manager
    if _task_manager is None:
        from gui_components.task_manager import TaskManager
        _task_manager = TaskManager(page=None)
    return _task_manager


# ---------------------------------------------------------------- 鉴权
def _要求鉴权(k: Optional[str] = None, authorization: Optional[str] = None) -> None:
    """token 校验: ?k= 或 Authorization: Bearer <token>, 常时比较防时序侧信道"""
    token = 取配置().get("token", "")
    supplied = k or ""
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if not token or not supplied or not hmac.compare_digest(supplied, token):
        raise HTTPException(status_code=401, detail="未授权")


# ---------------------------------------------------------------- 书架
def _扫结果目录() -> list:
    """扫 抓取结果/*.txt → [{id, 标题, 路径, 大小, 修改时间}]

    id = 绝对路径 md5 前 12 位 (稳定且不泄露文件系统结构)。
    """
    out_dir = get_default_output_dir()
    items = []
    try:
        names = sorted(os.listdir(out_dir))
    except OSError:
        return items
    for name in names:
        if not name.lower().endswith(".txt"):
            continue
        if "质检报告" in name:
            continue   # 质检汇总报告不是书 (生成质检汇总报告 的产物)
        path = os.path.join(out_dir, name)
        if not os.path.isfile(path):
            continue
        try:
            st = os.stat(path)
        except OSError:
            continue
        items.append({
            "id": hashlib.md5(os.path.abspath(path).encode("utf-8")).hexdigest()[:12],
            "标题": name[:-4],
            "文件": name,
            "路径": os.path.abspath(path),
            "大小": st.st_size,
            "修改时间": int(st.st_mtime),
        })
    return items


def _书架标题映射() -> dict:
    """书架.json 的 {输出文件名: 标题} — 丰富文件名之外的真实书名"""
    mapping = {}
    try:
        from 书架 import 列出
        for it in 列出():
            f = (it.get("输出文件") or "").strip()
            if f:
                mapping[os.path.basename(f)] = it.get("标题") or ""
    except Exception:
        pass
    return mapping


def _按id查书(book_id: str) -> Optional[dict]:
    for item in _扫结果目录():
        if item["id"] == book_id:
            标题表 = _书架标题映射()
            真名 = 标题表.get(item["文件"])
            if 真名:
                item["标题"] = 真名
            return item
    return None


def _确保epub(item: dict) -> str:
    """按需把 txt 转成 EPUB (txt 更新后缓存自动失效), 返回 epub 路径"""
    import epub_exporter
    txt = item["路径"]
    epub = os.path.splitext(txt)[0] + ".epub"
    if (not os.path.isfile(epub)
            or os.path.getmtime(epub) < os.path.getmtime(txt)):
        epub_exporter.txt_to_epub(txt, title=item["标题"])
    if not os.path.isfile(epub):
        raise HTTPException(status_code=500, detail="EPUB 生成失败")
    return epub


# ---------------------------------------------------------------- 端点
@app.get("/api/v1/healthz")
def healthz():
    return {"ok": True, "时间": int(time.time())}


@app.get("/")
def 面板():
    if not _面板路径.is_file():
        raise HTTPException(status_code=500, detail="面板文件缺失")
    return FileResponse(_面板路径, media_type="text/html")


@app.post("/api/v1/tasks")
def 创建任务(body: dict, k: Optional[str] = None,
            authorization: Optional[str] = None):
    _要求鉴权(k, authorization)
    url = (body or {}).get("url", "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="缺少 url")
    try:
        # 惰性导入 (requests/selenium 重链); SSRF 校验复用爬虫现有防线
        from 爬虫 import validate_public_url
        validate_public_url(url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"URL 校验失败: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"爬虫模块加载失败: {e}")

    mode = (body or {}).get("mode") or "full"
    if mode not in ("full", "test", "range"):
        mode = "full"
    chapter_range = (body or {}).get("chapter_range")
    if isinstance(chapter_range, (list, tuple)) and len(chapter_range) == 2:
        chapter_range = tuple(chapter_range)   # run_crawl 按元组解包
    else:
        chapter_range = None
    try:
        task_id = _任务管理器().create_task(
            url=url,
            mode=mode,
            chapter_range=chapter_range,
            resume=bool((body or {}).get("resume", True)),
            export_epub=bool((body or {}).get("export_epub", False)),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"任务创建失败: {e}")
    return {"task_id": task_id}


def _任务快照(t) -> dict:
    m = t.metrics
    start = m.start_time if m else 0
    end = m.end_time if m else 0
    耗时 = max(0, int((end or time.time()) - start)) if start else 0
    return {
        "id": t.task_id, "url": t.url, "标题": t.title,
        "状态": t.status, "进度": [t.progress_current, t.progress_total],
        "错误": t.error, "输出文件": t.output_file,
        "耗时秒": 耗时,
        "增量跳过": m.incremental_skipped if m else 0,
    }


@app.get("/api/v1/tasks")
def 任务列表(k: Optional[str] = None, authorization: Optional[str] = None):
    _要求鉴权(k, authorization)
    mgr = _任务管理器()
    with mgr._lock:
        tasks = list(mgr.tasks.values())
    return {"任务": [_任务快照(t) for t in tasks]}


@app.post("/api/v1/tasks/{task_id}/stop")
def 停止任务(task_id: str, k: Optional[str] = None,
            authorization: Optional[str] = None):
    _要求鉴权(k, authorization)
    if not _任务管理器().stop_task(task_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"ok": True}


@app.get("/api/v1/tasks/{task_id}/logs")
def 任务日志(task_id: str, after: int = 0,
            k: Optional[str] = None, authorization: Optional[str] = None):
    """日志增量: 客户端持 after 指针; 日志被 500 条截断致 total < after 时,
    从 0 重发并置 截断=True (客户端据此重置指针, 防永久漏日志)"""
    _要求鉴权(k, authorization)
    task = _任务管理器().get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    logs = task.logs
    total = len(logs)
    if after < 0 or after > total:
        after = 0
        截断 = True
    else:
        截断 = False
    return {"total": total, "截断": 截断, "entries": logs[after:]}


@app.get("/api/v1/tasks/{task_id}/logs/stream")
async def 任务日志流(task_id: str, after: int = 0,
                    k: Optional[str] = None,
                    authorization: Optional[str] = None):
    """日志 SSE 流: 每 0.6s 推增量, 15s 无新日志发注释行保活"""
    _要求鉴权(k, authorization)
    task = _任务管理器().get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    async def _流():
        pos = max(0, after)
        try:
            for _ in range(6000):     # 最长 ~1h, 防僵尸流
                logs = task.logs
                total = len(logs)
                if pos < 0 or pos > total:
                    pos = 0     # 截断 → 客户端按事件里的 total 重置
                if total > pos:
                    payload = json.dumps(
                        {"total": total, "entries": logs[pos:]},
                        ensure_ascii=False)
                    pos = total
                    yield f"data: {payload}\n\n"
                else:
                    yield ": keepalive\n\n"
                await asyncio.sleep(0.6)
        except asyncio.CancelledError:   # 客户端断开
            return

    return StreamingResponse(_流(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.get("/api/v1/books")
def 书架列表(k: Optional[str] = None, authorization: Optional[str] = None):
    _要求鉴权(k, authorization)
    items = _扫结果目录()
    标题表 = _书架标题映射()
    for it in items:
        真名 = 标题表.get(it["文件"])
        if 真名:
            it["标题"] = 真名
        it.pop("路径", None)   # 不向客户端泄露服务器路径
    return {"书籍": items}


@app.get("/api/v1/books/{book_id}/epub")
def 下载epub(book_id: str, k: Optional[str] = None,
             authorization: Optional[str] = None):
    _要求鉴权(k, authorization)
    item = _按id查书(book_id)
    if item is None:
        raise HTTPException(status_code=404, detail="书籍不存在")
    epub = _确保epub(item)
    return FileResponse(epub, filename=item["标题"] + ".epub",
                        media_type="application/epub+zip")
