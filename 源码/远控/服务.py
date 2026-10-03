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
import urllib.request
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse

from _path_utils import get_default_output_dir, get_state_root
from .配置 import 取配置
try:
    import 日志 as _app_log          # 批2D: 统一留痕通道 (容错导入, 同 input_bar 桥模式)
except Exception:
    _app_log = None


def _dbg(source: str, message: str):
    """裸 except 吞异常留痕 (DEBUG 级: 只落盘不 console 镜像, 避免刷屏)"""
    if _app_log is not None:
        try:
            _app_log.debug(source, message)
        except Exception:
            pass  # 刻意静默: try 块本身在写日志, 再加日志会递归 (日志链路兜底)


app = FastAPI(title="小说爬虫远控", docs_url=None, redoc_url=None, openapi_url=None)

_面板路径 = Path(__file__).with_name("面板.html")

# 远控使用教程 md (2026-09-29 教程入 UI): EXE 经 --add-data 与面板同目录;
# 源码运行直接读项目 文档/
_教程候选 = (
    Path(__file__).with_name("远控使用教程.md"),
    Path(__file__).parents[2] / "文档" / "远控使用教程.md",
)


def _教程md路径() -> Path:
    for p in _教程候选:
        if p.is_file():
            return p
    return _教程候选[0]


def _行内md(s: str) -> str:
    """行内标记: **粗体** 与 `代码` (输入已经过 html.escape, 安全)"""
    import re as _re
    s = _re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', s)
    s = _re.sub(r'`([^`]+)`', r'<code>\1</code>', s)
    return s


def _md转html(md: str) -> str:
    """极简 Markdown→HTML (纯标准库, 教程页专用)。

    支持: #/##/### 标题、```代码块、表格(| |)、有序/无序列表、**粗体**、`行内代码`。
    流程: 逐行先 html.escape 再施加标记 (防注入); 空行分段。
    """
    import html as _html
    import re as _re
    out = []
    in_code = in_table = False
    for ln in md.replace('\r\n', '\n').split('\n'):
        e = _html.escape(ln)
        if e.startswith('```'):
            out.append('</code></pre>' if in_code else '<pre><code>')
            in_code = not in_code
            continue
        if in_code:
            out.append(e)
            continue
        if e.startswith('|') and e.rstrip().endswith('|'):
            cells = [c.strip() for c in e.strip().strip('|').split('|')]
            if all(_re.fullmatch(r':?-{2,}:?', c) for c in cells):
                continue                      # 表头分隔行
            tag = 'th' if not in_table else 'td'
            if not in_table:
                out.append('<table>')
                in_table = True
            out.append('<tr>' + ''.join(f'<{tag}>{c}</{tag}>' for c in cells) + '</tr>')
            continue
        if in_table:
            out.append('</table>')
            in_table = False
        if e.startswith('### '):
            out.append(f'<h3>{e[4:]}</h3>')
        elif e.startswith('## '):
            out.append(f'<h2>{e[3:]}</h2>')
        elif e.startswith('# '):
            out.append(f'<h1>{e[2:]}</h1>')
        elif e.startswith('- '):
            out.append(f'<li>{_行内md(e[2:])}</li>')
        elif _re.match(r'^\d+\. ', e):
            out.append(f'<li>{_行内md(_re.sub(r"^\d+\. ", "", e))}</li>')
        elif not e.strip():
            out.append('')
        else:
            out.append(f'<p>{_行内md(e)}</p>')
    if in_table:
        out.append('</table>')
    if in_code:
        out.append('</code></pre>')
    body = '\n'.join(out)
    # 连续 <li> 包裹 <ul>
    body = _re.sub(r'((?:<li>.*?</li>\n?)+)', r'<ul>\1</ul>', body)
    return body


_教程页模板 = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>远控使用教程</title>
<style>
body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
     margin:0;padding:16px;background:#f5f5f7;color:#1d1d1f;line-height:1.65;}
.wrap{max-width:720px;margin:0 auto;background:#fff;border-radius:12px;
      padding:20px 18px;box-shadow:0 1px 4px rgba(0,0,0,.08);}
h1{font-size:1.4em;} h2{font-size:1.15em;border-bottom:1px solid #e5e5ea;
   padding-bottom:4px;margin-top:1.6em;} h3{font-size:1.02em;}
pre{background:#1d1d1f;color:#f5f5f7;padding:10px;border-radius:8px;
    overflow-x:auto;font-size:.85em;}
code{background:#eef0f3;padding:1px 5px;border-radius:4px;font-size:.9em;}
pre code{background:none;padding:0;}
table{border-collapse:collapse;width:100%;font-size:.9em;margin:.6em 0;}
th,td{border:1px solid #e5e5ea;padding:6px 8px;text-align:left;}
th{background:#f5f5f7;}
li{margin:.3em 0;}
.back{display:inline-block;margin-bottom:10px;color:#007aff;text-decoration:none;}
</style></head><body><div class="wrap">
<a class="back" href="/">&#8592; 返回控制面板</a>
{body}
</div></body></html>"""

_任务管理器锁 = threading.Lock()
_task_manager = None   # 惰性单例 (TaskManager(page=None), 无 flet 依赖)


def _任务管理器():
    global _task_manager
    if _task_manager is None:
        with _任务管理器锁:
            if _task_manager is None:
                from gui_components.task_manager import TaskManager
                _task_manager = TaskManager(page=None)
    return _task_manager


# ---------------------------------------------------------------- 内嵌模式
def 注入任务管理器(mgr) -> None:
    """桌面客户端内嵌模式: 用 GUI 的 TaskManager 实例共享任务列表。

    共享后: 手机发起的任务实时出现在桌面任务表 (GUI 每秒轮询同一对象),
    桌面发起的任务手机同样可见 —— 跨端同步由"单实例"天然保证。"""
    global _task_manager
    _task_manager = mgr


_server = None          # 内嵌 uvicorn.Server 实例 (供开关优雅停机)
_server_thread = None


def 后台启动(host: str = None, port: int = None):
    """守护线程内启动 uvicorn (GUI 内嵌远控); 禁用/已在运行返回 None。

    - 持有 Server 实例: 停止后台() 经 should_exit 优雅停机 (端口释放)
    - loop/http 显式纯 Python 实现, 防冻结环境缺 C 扩展
    - 端口被占等失败: 线程内捕获并记日志, 不影响桌面客户端
    """
    global _server, _server_thread
    import threading as _t
    import uvicorn
    cfg = 取配置()
    if not cfg.get("启用", True):
        return None
    if 运行中():
        return None
    _host = host or cfg.get("绑定", "0.0.0.0")
    _port = int(port or cfg.get("端口", 8760))
    try:
        config = uvicorn.Config(app, host=_host, port=_port,
                                log_level="warning", loop="asyncio", http="h11",
                                timeout_graceful_shutdown=3)
        _server = uvicorn.Server(config)
    except Exception as e:
        _日志留痕(f"内嵌远控配置失败: {type(e).__name__}: {e}")
        _server = None
        return None
    _server_thread = _t.Thread(target=_server.run, name="远控服务", daemon=True)
    _server_thread.start()
    # 启动留痕: 主入口 + 多网卡时的全部局域网入口 (2026-10-03 八项需求#7)
    _ips = 局域网地址们()
    _其它 = ", ".join(f"http://{ip}:{_port}/" for ip in _ips[1:])
    _日志留痕(f"远控服务已启动: {展示地址()}"
              + (f"; 局域网其他入口: {_其它}" if _其它 else ""))
    return _server_thread


def 停止后台() -> None:
    """优雅停止内嵌远控 (should_exit 触发 uvicorn 收尾, 线程自然退出)"""
    global _server, _server_thread
    srv = _server
    _server = None
    if srv is not None:
        try:
            srv.should_exit = True
        except Exception as _e:
            _dbg("远控服务", f'裸 except 吞异常: {type(_e).__name__}: {_e}')
    worker = _server_thread
    if worker is not None and worker is not threading.current_thread():
        worker.join(timeout=5)
        if worker.is_alive():
            _server = srv
            raise RuntimeError("远控服务仍在收尾，请稍后重试")
    _server_thread = None


def 运行中() -> bool:
    """内嵌远控是否在运行 (顶栏开关据此展示真实状态)"""
    return _server is not None and _server_thread is not None \
        and _server_thread.is_alive()


# ---------------------------------------------------------------- 地址展示
def 局域网地址们() -> list:
    """枚举本机局域网 IPv4 地址 (零依赖, 纯标准库)。

    两级探测:
    1) UDP connect 技巧 (不实际发包): 连 8.8.8.8 取本机出口 IP — 最可靠的
       "主网卡"地址, 在线时必命中;
    2) 主机名 getaddrinfo 枚举: 离线兜底 + 补齐其余网卡 (多网卡场景)。
    均排除 127.* 回环。失败静默返回已收集部分 (可能为空)。
    """
    import socket as _s
    out: list = []
    try:
        with _s.socket(_s.AF_INET, _s.SOCK_DGRAM) as sk:
            sk.connect(("8.8.8.8", 80))
            ip = sk.getsockname()[0]
        if ip and not ip.startswith("127.") and ip not in out:
            out.append(ip)
    except OSError:
        pass  # 离线/无默认路由: 走主机名枚举兜底
    try:
        for info in _s.getaddrinfo(_s.gethostname(), None, _s.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ip not in out:
                out.append(ip)
    except OSError:
        pass  # 极端环境 (gethostname 失败): 返回已收集结果即可
    return out


def 展示地址() -> str:
    """面板对外展示地址: 绑定 0.0.0.0/:: 时取首个局域网 IP 拼可用 URL,
    其余绑定值 (用户手改 127.0.0.1 等) 原样展示。"""
    cfg = 取配置()
    bind = str(cfg.get("绑定", "127.0.0.1"))
    port = int(cfg.get("端口", 8760))
    if bind in ("0.0.0.0", "::"):
        ips = 局域网地址们()
        ip = ips[0] if ips else "127.0.0.1"
        return f"http://{ip}:{port}/"
    return f"http://{bind}:{port}/"


def 地址提示() -> str:
    """地址可用性提示 (空串 = 无需提示)。

    2026-10-04 修八项需求 #7: 旧实现里「绑定 0.0.0.0 但一个局域网地址都没探测到」时,
    `展示地址()` 会回落成 `http://127.0.0.1:端口/` 并**当作局域网地址**展示 ——
    手机必然连不上, 界面却毫无线索。这里把两种"看着能用其实不能用"说清楚。
    """
    try:
        cfg = 取配置()
    except Exception:
        return ""
    bind = str(cfg.get("绑定", "") or "")
    if bind and bind not in ("0.0.0.0", "::"):
        if bind in ("127.0.0.1", "localhost", "::1"):
            return ("仅本机可访问 (绑定为回环地址); 如需手机访问, "
                    "请把绑定改为 0.0.0.0")
        return ""
    if not 局域网地址们():
        return "未探测到局域网地址: 请确认电脑已联网并连上 Wi-Fi; 此时手机可能连不上"
    return ""


def _日志留痕(msg: str) -> None:
    try:
        import 日志 as _alog
        _alog.get("远控").info(msg)
    except Exception:
        pass  # 刻意静默: 日志链路兜底: _日志留痕 的 try 体写任务日志, 再加日志会递归


# ---------------------------------------------------------------- 鉴权
def _要求鉴权(k: Optional[str] = None, authorization: Optional[str] = Header(default=None)) -> None:
    """token 校验: ?k= 或 Authorization: Bearer <token>, 常时比较防时序侧信道"""
    token = 取配置().get("token", "")
    supplied = k or ""
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if not token or not supplied or not hmac.compare_digest(supplied.encode("utf-8"), str(token).encode("utf-8")):
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
    except Exception as _e:
        _dbg("远控服务", f'裸 except 吞异常: {type(_e).__name__}: {_e}')
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
        if not epub_exporter.txt_to_epub(txt, title=item["标题"]):
            raise HTTPException(status_code=500, detail="EPUB 生成失败，旧文件已保留")
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


@app.get("/tutorial")
def 教程():
    """远控使用教程页 (免鉴权, 与面板同级; 2026-09-29 教程入 UI)"""
    p = _教程md路径()
    if not p.is_file():
        raise HTTPException(status_code=404, detail="教程文件缺失")
    md = p.read_text(encoding='utf-8', errors='replace')
    return HTMLResponse(_教程页模板.replace('{body}', _md转html(md)))


@app.post("/api/v1/tasks")
def 创建任务(body: dict, k: Optional[str] = None,
            authorization: Optional[str] = Header(default=None)):
    _要求鉴权(k, authorization)
    raw_url = (body or {}).get("url", "")
    if not isinstance(raw_url, str):
        raise HTTPException(status_code=400, detail="url 必须是字符串")
    url = raw_url.strip()
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

    mode = (body or {}).get("mode", "full")
    if mode not in ("full", "test", "range"):
        raise HTTPException(status_code=400, detail="mode 仅支持 full/test/range")
    chapter_range = (body or {}).get("chapter_range")
    if chapter_range is not None or mode == "range":
        if (not isinstance(chapter_range, (list, tuple)) or len(chapter_range) != 2
                or any(type(n) is not int for n in chapter_range)
                or chapter_range[0] < 1 or chapter_range[1] < chapter_range[0]):
            raise HTTPException(status_code=400, detail="区间需两个正整数，结束章不得小于开始章")
        chapter_range = tuple(chapter_range)
    for flag in ("resume", "export_epub", "unique_title", "incremental"):
        if flag in body and type(body[flag]) is not bool:
            raise HTTPException(status_code=400, detail=f"{flag} 必须是布尔值")
    # 增量透传 (EXE/桌面批量用): incremental=True 默认 unique_title=False ——
    # 增量语义是续写原文件, True 会另存 "书名(1).txt" 使旧正文无法参与增量搬运;
    # 显式传入 unique_title 时以显式为准 (与 GUI"一键更新书架"同参数组合)
    增量 = bool((body or {}).get("incremental", False))
    if "unique_title" in body:
        唯一标题 = bool(body["unique_title"])
    else:
        唯一标题 = not 增量
    try:
        task_id = _任务管理器().create_task(
            url=url,
            mode=mode,
            chapter_range=chapter_range,
            resume=bool((body or {}).get("resume", True)),
            export_epub=bool((body or {}).get("export_epub", False)),
            # 续传中断任务时必须 False — True 会另存 "书名(1).txt" 而非续写
            unique_title=唯一标题,
            incremental=增量,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"任务创建失败: {e}")
    try:   # 标记来源: 远控页在桌面端按此过滤展示"手机端记录"
        t = _任务管理器().get_task(task_id)
        if t is not None:
            t.来源 = "手机"
    except Exception as _e:
        _dbg("远控服务", f'裸 except 吞异常: {type(_e).__name__}: {_e}')
    return {"task_id": task_id}


def _任务快照(t) -> dict:
    m = t.metrics
    start = m.start_time if m else 0
    end = m.end_time if m else 0
    耗时 = max(0, int((end or time.time()) - start)) if start else 0
    if t.status == "interrupted" and not end:
        耗时 = 0  # 历史中断时刻未知，不累计为本轮运行时间
    return {
        "id": t.task_id, "url": t.url, "标题": t.title,
        "状态": t.status, "进度": [t.progress_current, t.progress_total],
        "错误": t.error, "输出文件": t.output_file,
        "耗时秒": 耗时,
        "增量跳过": m.incremental_skipped if m else 0,
    }


@app.get("/api/v1/tasks")
def 任务列表(k: Optional[str] = None, authorization: Optional[str] = Header(default=None)):
    _要求鉴权(k, authorization)
    _恢复中断任务()   # 只读恢复: 首次查询时重建上次中断的任务展示
    mgr = _任务管理器()
    with mgr._lock:
        tasks = list(mgr.tasks.values())
    return {"任务": [_任务快照(t) for t in tasks]}


@app.post("/api/v1/tasks/{task_id}/stop")
def 停止任务(task_id: str, k: Optional[str] = None,
            authorization: Optional[str] = Header(default=None)):
    _要求鉴权(k, authorization)
    mgr = _任务管理器()
    task = mgr.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    # 修复(U5): 只停 running/pending; 已终态的任务拒绝改写状态 (旧实现会把
    # "已完成"改写成"已停止", 手机端随即收到一次错误的完成推送)
    if not mgr.stop_task(task_id):
        raise HTTPException(
            status_code=409,
            detail=f"任务已处于终态({task.status}), 不能停止")
    return {"ok": True}


@app.delete("/api/v1/tasks/{task_id}")
def 删除展示任务(task_id: str, k: Optional[str] = None,
                authorization: Optional[str] = Header(default=None)):
    """移除任务展示项 (仅非运行态; 不删除输出文件与检查点)"""
    _要求鉴权(k, authorization)
    if not _删除展示任务(task_id):
        raise HTTPException(status_code=404, detail="任务不存在或仍在运行")
    return {"ok": True}


@app.get("/api/v1/tasks/{task_id}/logs")
def 任务日志(task_id: str, after: int = 0, epoch: Optional[str] = None,
            k: Optional[str] = None, authorization: Optional[str] = Header(default=None)):
    """日志增量: 客户端持 after 指针; 日志被 500 条截断致 total < after 时,
    从 0 重发并置 截断=True (客户端据此重置指针, 防永久漏日志)"""
    _要求鉴权(k, authorization)
    task = _任务管理器().get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    from gui_components.task_manager import snapshot_task_logs
    snapshot = snapshot_task_logs(task, after)
    if epoch is not None and epoch != snapshot["epoch"]:
        snapshot = snapshot_task_logs(task, 0)
        snapshot["截断"] = True
    return snapshot


@app.get("/api/v1/tasks/{task_id}/logs/stream")
async def 任务日志流(task_id: str, after: int = 0, epoch: Optional[str] = None,
                    k: Optional[str] = None,
                    authorization: Optional[str] = Header(default=None)):
    """日志 SSE 流: 每 0.6s 推增量, 15s 无新日志发注释行保活"""
    _要求鉴权(k, authorization)
    task = _任务管理器().get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    async def _流():
        pos = max(0, after)
        current_epoch = epoch
        try:
            for _ in range(6000):     # 最长 ~1h, 防僵尸流
                from gui_components.task_manager import snapshot_task_logs
                snapshot = snapshot_task_logs(task, pos)
                if current_epoch is not None and current_epoch != snapshot["epoch"]:
                    snapshot = snapshot_task_logs(task, 0)
                    snapshot["截断"] = True
                current_epoch = snapshot["epoch"]
                total = snapshot["total"]
                if snapshot["entries"] or snapshot["截断"]:
                    payload = json.dumps(snapshot, ensure_ascii=False)
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


_已扫中断 = False
_章节缓存: dict = {}      # txt路径 -> (mtime, [ {标题, 内容} ])
_进度锁 = threading.Lock()
_章节缓存锁 = threading.Lock()   # 同步端点跑在 Starlette 线程池, 读/写/淘汰须互斥
_已推终态: set = set()    # (task_id, status, end_time) — 防重复推送


def _推送地址可用(u: str) -> bool:
    """推送服务器地址仅允许 http/https (阻断 file:// 等自定义协议)"""
    return str(u).strip().lower().startswith(("http://", "https://"))


def _发送推送(标题: str, 内容: str) -> None:
    """完成推送 (④): Bark / ntfy, 按配置二选一或都发; 失败仅记日志不抛"""
    cfg = 取配置().get("推送") or {}
    渠道结果 = []
    bark = cfg.get("bark") or {}
    if bark.get("启用") and bark.get("地址"):
        if not _推送地址可用(bark["地址"]):
            渠道结果.append("bark✗Scheme")
        else:
            try:
                from urllib.parse import quote
                from sites_config import validate_public_url
                base = bark["地址"].rstrip("/")
                # SSRF 边界: 推送地址可经配置 API 写入, 对最终请求 URL 校验
                # (协议/主机/字面 IP 边界), 拼接标题与正文后紧贴 urlopen 复验
                url = f"{base}/{quote(标题, safe='')}/{quote(内容, safe='')}"
                validate_public_url(base)
                validate_public_url(url)
                import requests as _rq
                resp = _rq.get(url, timeout=10)
                resp.raise_for_status()
                渠道结果.append("bark✓")
            except Exception as e:
                渠道结果.append(f"bark✗{type(e).__name__}")
    ntfy = cfg.get("ntfy") or {}
    if ntfy.get("启用") and ntfy.get("主题"):
        服务器 = ntfy.get("服务器", "https://ntfy.sh")
        if not _推送地址可用(服务器):
            渠道结果.append("ntfy✗Scheme")
        else:
            try:
                from email.header import Header
                from sites_config import validate_public_url
                validate_public_url(服务器)
                data = 内容.encode("utf-8")
                final_url = 服务器.rstrip("/") + "/" + str(ntfy["主题"])
                validate_public_url(final_url)
                import requests as _rq
                resp = _rq.post(final_url, data=data,
                                headers={"Title": Header(标题, "utf-8").encode(),
                                         "Tags": "books"},
                                timeout=10)
                resp.raise_for_status()
                渠道结果.append("ntfy✓")
            except Exception as e:
                渠道结果.append(f"ntfy✗{type(e).__name__}")
    if 渠道结果:
        try:
            from 日志 import get as _日志取
            _日志取("远控").info(f"[推送] {标题} → {' '.join(渠道结果)}")
        except Exception as _e:
            _dbg("远控服务", f'裸 except 吞异常: {type(_e).__name__}: {_e}')


def _扫描终态() -> list:
    """终态监视器单遍: 检测 running → 终态 的翻转, 逐条发送推送。

    仅在"本进程内观察到 running"的任务上触发; 启动时恢复的 interrupted
    不会误推。返回本遍触发的事件列表 (供单测断言)。"""
    已触发 = []
    mgr = _任务管理器()
    with mgr._lock:
        快照 = list(mgr.tasks.values())
    for t in 快照:
        if getattr(t, "_恢复项", False) or t.status not in ("completed", "failed", "stopped",
                                                             "dead_pending"):
            continue
        end = t.metrics.end_time if t.metrics else 0
        键 = (t.task_id, t.status, end)
        if 键 in _已推终态:
            continue
        # 只推"本进程见过其运行"的任务: 恢复的 interrupted 直接是终态而非翻转,
        # 但其 end_time 为 0 且从未 running; 用 end_time>0 判定为真实终态
        if not end:
            continue
        _已推终态.add(键)
        章节 = f"{t.progress_current}/{t.progress_total}章" \
            if t.progress_total else ""
        链接 = ""
        前 = (取配置().get("外链前缀") or "").rstrip("/")
        if 前:
            # G-H2 (GUI 专项审查): 推送正文禁止携带 token —— Bark/ntfy 是
            # 第三方通道, 全权限 token 内嵌 ?k= 会随推送离开本机。
            # 改为指到面板根 (token 已存面板本地), 用户从面板进阅读页, 不损失可达性。
            链接 = f"\n面板: {前}/"
        状态词 = {"completed": "抓取完成", "failed": "抓取失败",
                  "stopped": "已停止", "dead_pending": "书已删除(待确认)"}.get(t.status, t.status)
        _发送推送(f"{t.title or t.url} · {状态词}",
                  f"{章节}{链接}")
        已触发.append((t.task_id, t.status))
    # 只清理已不在表中的运行轮次，避免任意删活跃终态键导致重复通知。
    活跃键 = {(t.task_id, t.status, t.metrics.end_time if t.metrics else 0) for t in 快照}
    _已推终态.intersection_update(活跃键)
    return 已触发


async def _终态监视():
    """每 3 秒跑一遍终态检测 (HTTP 发送放线程池, 不阻塞事件循环)"""
    while True:
        try:
            await asyncio.to_thread(_扫描终态)
        except Exception as _e:
            _dbg("远控服务", f'裸 except 吞异常: {type(_e).__name__}: {_e}')
        await asyncio.sleep(3)


@app.on_event("startup")
async def _启动监视器():
    app.state.终态监视 = asyncio.create_task(_终态监视())


@app.on_event("shutdown")
async def _停止监视器():
    task = getattr(app.state, "终态监视", None)
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass  # 预期取消：服务关闭时回收监视器
        app.state.终态监视 = None



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
        # 去重 (2026-09-29 任务历史持久化): 同 URL 的 interrupted 项可能已由
        # 任务历史恢复进表, checkpoint 扫描不再注入第二条
        with mgr._lock:
            已有同URL = any(
                existing.url == ck["catalog_url"]
                and existing.status in ("running", "interrupted", "pending")
                for existing in mgr.tasks.values())
        if 已有同URL:
            continue
        try:
            completed = int(ck.get("completed", 0) or 0)
            total = int(ck.get("total", 0) or 0)
            if completed < 0 or total < completed or not isinstance(ck["catalog_url"], str):
                continue
        except (ValueError, TypeError, OverflowError):
            _dbg("远控服务", f"检查点字段异常，跳过: {name}")
            continue
        t = TaskInfo(task_id=tid, url=ck["catalog_url"],
                     title=os.path.splitext(name[:-len(".checkpoint.json")])[0],
                     status="interrupted",
                     progress_current=completed,
                     progress_total=total)
        with mgr._lock:
            mgr.tasks[tid] = t


def _删除展示任务(task_id: str) -> bool:
    """移除任务展示项 (仅非运行态; 不动输出文件与检查点)"""
    mgr = _任务管理器()
    with mgr._lock:
        t = mgr.tasks.get(task_id)
        if t is None or t.status in ("running", "pending") or (t.thread is not None and t.thread.is_alive()):
            return False
    return mgr.delete_task(task_id, delete_file=False)


# ---------------------------------------------------------------- 阅读
def _解析章节(item: dict) -> list:
    """按 '## 标题' 切分 txt 为章节列表 (mtime 缓存)。

    首个 '## ' 之前的导语非空时作为 '(开篇)' 章节保留 (epub 导出会丢弃它,
    阅读页选择保留, 由读者自己跳过)。"""
    path = item["路径"]
    try:
        st = os.stat(path)
        mtime = (st.st_mtime_ns, st.st_size)
    except OSError as e:
        raise HTTPException(status_code=404, detail="文件已不存在") from e
    with _章节缓存锁:
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
            elif "\n".join(缓冲).strip():
                章节.append({"标题": "(开篇)", "内容": "\n".join(缓冲).strip()})
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
    with _章节缓存锁:
        _章节缓存[path] = (mtime, 章节)
        # 防长会话内存缓涨 (一本 900KB txt ≈ 2MB 缓存)
        # 淘汰须持锁: 并发请求下 len() 与 pop(next(iter())) 之间可能被另一
        # 线程清空 → StopIteration / dict changed size → 未捕获异常 → 500
        while len(_章节缓存) > 8:
            _章节缓存.pop(next(iter(_章节缓存)))
    return 章节


def _读进度(book_id: str) -> int:
    try:
        with open(os.path.join(get_state_root(), "数据", "阅读进度.json"),
                  "r", encoding="utf-8") as f:
            data = json.load(f)
            return max(0, int(data.get(book_id, 0))) if isinstance(data, dict) else 0
    except (OSError, ValueError, TypeError):
        return 0


def _写进度(book_id: str, chapter: int) -> None:
    from pathlib import Path as _Path
    进度文件 = _Path(get_state_root()) / "数据" / "阅读进度.json"
    with _进度锁:
        data = {}
        try:
            with open(进度文件, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    data = {}
        except (OSError, ValueError) as _e:
            _dbg("远控服务", f'裸 except 吞异常: {type(_e).__name__}: {_e}')
        data[book_id] = max(0, int(chapter))
        # 原子写 (范式同 爬取历史.py): tmp + os.replace, pathlib 字面段拼接
        tmp = 进度文件.with_name(进度文件.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, 进度文件)


@app.get("/api/v1/books/{book_id}/chapters")
def 章节列表(book_id: str, k: Optional[str] = None,
            authorization: Optional[str] = Header(default=None)):
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
            authorization: Optional[str] = Header(default=None)):
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
           authorization: Optional[str] = Header(default=None)):
    _要求鉴权(k, authorization)
    return {"章节": _读进度(book_id)}


@app.post("/api/v1/books/{book_id}/progress")
def 存进度(book_id: str, body: dict, k: Optional[str] = None,
           authorization: Optional[str] = Header(default=None)):
    _要求鉴权(k, authorization)
    序 = (body or {}).get("章节")
    if type(序) is not int or 序 < 0:
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
def 书架列表(k: Optional[str] = None, authorization: Optional[str] = Header(default=None)):
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
             authorization: Optional[str] = Header(default=None)):
    _要求鉴权(k, authorization)
    item = _按id查书(book_id)
    if item is None:
        raise HTTPException(status_code=404, detail="书籍不存在")
    epub = _确保epub(item)
    return FileResponse(epub, filename=item["标题"] + ".epub",
                        media_type="application/epub+zip")
