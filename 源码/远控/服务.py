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
import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse

from _path_utils import get_default_output_dir, get_app_base_dir
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
            # 续传中断任务时必须 False — True 会另存 "书名(1).txt" 而非续写
            unique_title=bool((body or {}).get("unique_title", True)),
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
    _恢复中断任务()   # 只读恢复: 首次查询时重建上次中断的任务展示
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


@app.delete("/api/v1/tasks/{task_id}")
def 删除展示任务(task_id: str, k: Optional[str] = None,
                authorization: Optional[str] = None):
    """移除任务展示项 (仅非运行态; 不删除输出文件与检查点)"""
    _要求鉴权(k, authorization)
    if not _删除展示任务(task_id):
        raise HTTPException(status_code=404, detail="任务不存在或仍在运行")
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


_app = app  # 别名 (语义可读)

_已扫中断 = False
_章节缓存: dict = {}      # txt路径 -> (mtime, [ {标题, 内容} ])
_进度锁 = threading.Lock()


def _恢复中断任务():
    """只读恢复 (关键变更 6): 服务启动后首次查询时, 扫 抓取结果/*.checkpoint.json,
    把上次被中断的任务重建为 interrupted 展示项。续传 = 对其 url 以
    resume=True + unique_title=False 重新发任务 (断点续传语义自动接管)。"""
    global _已扫中断
    if _已扫中断:
        return
    _已扫中断 = True
    mgr = _任务管理器()
    out_dir = get_default_output_dir()
    try:
        names = os.listdir(out_dir)
    except OSError:
        return
    from gui_components.task_manager import TaskInfo
    for name in names:
        if not name.endswith(".checkpoint.json"):
            continue
        path = os.path.join(out_dir, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                ck = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(ck, dict) or not ck.get("catalog_url"):
            continue
        tid = "resume_" + hashlib.md5(path.encode("utf-8")).hexdigest()[:8]
        if tid in mgr.tasks:
            continue
        t = TaskInfo(task_id=tid, url=ck["catalog_url"],
                     title=name[:-len(".checkpoint.json")],
                     status="interrupted",
                     progress_current=int(ck.get("completed", 0) or 0),
                     progress_total=int(ck.get("total", 0) or 0))
        with mgr._lock:
            mgr.tasks[tid] = t


def _删除展示任务(task_id: str) -> bool:
    """移除任务展示项 (仅非运行态; 不动输出文件与检查点)"""
    mgr = _任务管理器()
    with mgr._lock:
        t = mgr.tasks.get(task_id)
        if t is None or t.status == "running":
            return False
        del mgr.tasks[task_id]
        if mgr._selected_task_id == task_id:
            mgr._selected_task_id = ""
        return True


# ---------------------------------------------------------------- 阅读
def _解析章节(item: dict) -> list:
    """按 '## 标题' 切分 txt 为章节列表 (mtime 缓存)。

    首个 '## ' 之前的导语非空时作为 '(开篇)' 章节保留 (epub 导出会丢弃它,
    阅读页选择保留, 由读者自己跳过)。"""
    path = item["路径"]
    try:
        mtime = os.path.getmtime(path)
    except OSError as e:
        raise HTTPException(status_code=404, detail="文件已不存在") from e
    cached = _章节缓存.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"读取失败: {e}") from e
    章节 = []
    当前标题, 缓冲 = None, []
    for line in text.splitlines():
        if line.startswith("## "):
            if 当前标题 is not None:
                章节.append({"标题": 当前标题, "内容": "\n".join(缓冲).strip()})
            当前标题, 缓冲 = line[3:].strip(), []
        elif 当前标题 is not None:
            缓冲.append(line)
        else:
            缓冲.append(line)   # 首章之前的导语
    if 当前标题 is not None:
        章节.append({"标题": 当前标题, "内容": "\n".join(缓冲).strip()})
    else:
        导语 = "\n".join(缓冲).strip()
        if 导语:
            章节.append({"标题": "(开篇)", "内容": 导语})
    _章节缓存[path] = (mtime, 章节)
    if len(_章节缓存) > 8:   # 防长会话内存缓涨 (一本 900KB txt ≈ 2MB 缓存)
        _章节缓存.pop(next(iter(_章节缓存)))
    return 章节


def _读进度(book_id: str) -> int:
    try:
        with open(os.path.join(get_app_base_dir(), "数据", "阅读进度.json"),
                  "r", encoding="utf-8") as f:
            return int(json.load(f).get(book_id, 0))
    except (OSError, ValueError, TypeError):
        return 0


def _写进度(book_id: str, chapter: int) -> None:
    path = os.path.join(get_app_base_dir(), "数据", "阅读进度.json")
    with _进度锁:
        data = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            pass
        data[book_id] = max(0, int(chapter))
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)


@app.get("/api/v1/books/{book_id}/chapters")
def 章节列表(book_id: str, k: Optional[str] = None,
            authorization: Optional[str] = None):
    _要求鉴权(k, authorization)
    item = _按id查书(book_id)
    if item is None:
        raise HTTPException(status_code=404, detail="书籍不存在")
    章节 = _解析章节(item)
    return {"总章数": len(章节),
            "章节": [{"序": i, "标题": c["标题"]} for i, c in enumerate(章节)],
            "进度": _读进度(book_id)}


@app.get("/api/v1/books/{book_id}/content/{index}")
def 章节内容(book_id: str, index: int, k: Optional[str] = None,
            authorization: Optional[str] = None):
    """路径参数用 ASCII 名 {index} — 中文组名在 Starlette 路径正则下不匹配 (实测 404)"""
    _要求鉴权(k, authorization)
    item = _按id查书(book_id)
    if item is None:
        raise HTTPException(status_code=404, detail="书籍不存在")
    章节 = _解析章节(item)
    if not 0 <= index < len(章节):
        raise HTTPException(status_code=404, detail="章节超出范围")
    return {"序": index, "标题": 章节[index]["标题"],
            "内容": 章节[index]["内容"], "总章数": len(章节)}


@app.get("/api/v1/books/{book_id}/progress")
def 读进度(book_id: str, k: Optional[str] = None,
           authorization: Optional[str] = None):
    _要求鉴权(k, authorization)
    return {"章节": _读进度(book_id)}


@app.post("/api/v1/books/{book_id}/progress")
def 存进度(book_id: str, body: dict, k: Optional[str] = None,
           authorization: Optional[str] = None):
    _要求鉴权(k, authorization)
    序 = (body or {}).get("章节")
    if not isinstance(序, int) or 序 < 0:
        raise HTTPException(status_code=400, detail="章节序号无效")
    _写进度(book_id, 序)
    return {"ok": True}


@app.get("/reader/{book_id}")
def 阅读页(book_id: str, k: Optional[str] = None):
    """阅读器页面 (token 经 ?k= 传入, JS 转存 sessionStorage)"""
    _要求鉴权(k)
    页 = Path(__file__).with_name("阅读.html")
    if not 页.is_file():
        raise HTTPException(status_code=500, detail="阅读页文件缺失")
    return FileResponse(页, media_type="text/html")


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
