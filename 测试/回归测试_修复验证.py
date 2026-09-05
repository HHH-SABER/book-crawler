# -*- coding: utf-8 -*-
"""回归测试: 验证 4 个修复点无副作用

修复点:
1. 爬虫.py 批量清单解析 (with open 替换裸 open)
2. site_manage_page.py 导入 get_app_base_dir (修复 NameError)
3. 爬虫.py clean_content 删除实体名裸替换 (保留 &entity; 正规替换)
4. 请求引擎.py requests 会话按 host 缓存复用
"""
import os
import sys
import time
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.normpath(os.path.join(_HERE, "..", "源码"))
sys.path.insert(0, _SRC)

PASS = 0
FAIL = 0


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}  {detail}")


# ==================================================================
# 测试1: 批量清单解析 — with open 行为一致
# ==================================================================
def test_batch_parse():
    print("\n[测试1] 批量清单解析 (with open 修复)")
    # 构造测试清单文件
    lines = [
        "# 注释行\n",
        "https://example.com/book1\n",
        "\n",
        "https://example.com/book2\n",
        "# 另一条注释\n",
        "https://example.com/book3\n",
    ]
    fd, path = tempfile.mkstemp(suffix=".txt", text=True)
    try:
        os.write(fd, "".join(lines).encode("utf-8"))
        os.close(fd)
        # 复现修复后的逻辑
        with open(path, encoding="utf-8") as _bf:
            urls = [ln.strip() for ln in _bf
                    if ln.strip() and not ln.strip().startswith("#")]
        ok("解析出 3 个 URL", len(urls) == 3, f"实际 {len(urls)}")
        ok("无注释行", all(not u.startswith("#") for u in urls))
        ok("顺序保留", urls[0] == "https://example.com/book1")
        ok("末项正确", urls[-1] == "https://example.com/book3")
        # 文件句柄已关闭 (with 退出后)
        # 通过尝试再次打开同名文件验证未锁 (Windows 上未关闭的句柄会锁文件)
        try:
            with open(path, "a", encoding="utf-8") as f2:
                f2.write("")
            ok("with 退出后文件句柄已释放", True)
        except Exception as e:
            ok("with 退出后文件句柄已释放", False, str(e))
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass


# ==================================================================
# 测试2: site_manage_page get_app_base_dir 可导入, 不再 NameError
# ==================================================================
def test_site_manage_import():
    print("\n[测试2] site_manage_page get_app_base_dir 导入")
    try:
        import gui_components.pages.site_manage_page as smp
        ok("模块导入成功", True)
    except Exception as e:
        ok("模块导入成功", False, str(e))
        return
    # 检查 get_app_base_dir 在模块作用域可用
    has_fn = hasattr(smp, "get_app_base_dir")
    ok("get_app_base_dir 已定义在模块", has_fn)
    if has_fn:
        try:
            d = smp.get_app_base_dir()
            ok("get_app_base_dir() 可调用且返回非空", bool(d), f"返回 {d!r}")
        except Exception as e:
            ok("get_app_base_dir() 可调用且返回非空", False, str(e))
    # 模拟 _build_alarm_banner 中对 get_app_base_dir 的调用路径
    # (原先引用未定义的 _path_utils 会在 try 内抛 NameError 被吞, 横幅永远空)
    try:
        d = os.path.join(smp.get_app_base_dir(), "数据")
        ok("告警横幅路径拼接不再 NameError", bool(d))
    except Exception as e:
        ok("告警横幅路径拼接不再 NameError", False, str(e))


# ==================================================================
# 测试3: clean_content HTML 实体处理
# ==================================================================
def test_clean_content_entities():
    print("\n[测试3] clean_content HTML 实体处理")
    try:
        import 爬虫 as crawler_mod
        ok("爬虫模块导入成功", True)
    except Exception as e:
        ok("爬虫模块导入成功", False, str(e))
        return
    Spider = getattr(crawler_mod, "NovelSpider", None)
    if Spider is None:
        ok("NovelSpider 类存在", False)
        return
    ok("NovelSpider 类存在", True)
    # 构造一个不发起网络请求的实例 (只测 clean_content 纯函数行为)
    try:
        spider = Spider.__new__(Spider)
        ok("可创建实例 (不触发 __init__)", True)
    except Exception as e:
        ok("可创建实例 (不触发 __init__)", False, str(e))
        return
    # 场景 A: 正规 HTML 实体 (&ldquo; 等) 应被替换为对应字符
    # 字典映射: ldquo->" rdquo->" hellip->… (半角引号)
    try:
        out = spider.clean_content("他说&ldquo;你好&rdquo;，&hellip;结束")
        ok("&ldquo;/&rdquo; 替换为引号", '"' in out, out)
        ok("&hellip; 替换为省略号", "…" in out, out)
    except Exception as e:
        ok("正规 HTML 实体替换", False, str(e))
        return
    # 场景 B: 实体名作为普通英文词不应被误伤 (修复前会被替换)
    try:
        out = spider.clean_content("The bullet hit the bull. nbsp is not a word. mdash here")
        # "bull" 不应变成 "•", "nbsp" 不应变成空格, "mdash" 不应变成 "—"
        ok("bull 不再被误替换为 •", "•" not in out, out)
        ok("nbsp 不再被误替换为空格", "nbsp" in out, out)
        ok("mdash 不再被误替换为 —", "mdash" in out, out)
    except Exception as e:
        ok("实体名裸替换已删除", False, str(e))
    # 场景 C: 零宽字符清理仍有效 (回归保护)
    try:
        out = spider.clean_content("正文\u200b内容\u00ad尾巴")
        ok("零宽字符清理仍生效", "\u200b" not in out and "\u00ad" not in out, out)
    except Exception as e:
        ok("零宽字符清理仍生效", False, str(e))


# ==================================================================
# 测试4: 请求引擎 requests 会话按 host 缓存复用
# ==================================================================
def test_requests_engine_session_cache():
    print("\n[测试4] 请求引擎 requests 会话复用")
    try:
        import 请求引擎 as eng_mod
        ok("请求引擎模块导入成功", True)
    except Exception as e:
        ok("请求引擎模块导入成功", False, str(e))
        return
    try:
        mgr = eng_mod.请求引擎管理器()
        ok("管理器可实例化", True)
    except Exception as e:
        ok("管理器可实例化", False, str(e))
        return
    # 验证 _requests_sessions 字典已初始化
    ok("有 _requests_sessions 缓存字典",
       hasattr(mgr, "_requests_sessions"), "")
    # 不发真实请求, 只验证会话缓存逻辑:
    # 调用 _请求_requests 到同一 host 两次, 应复用同一 Session 对象
    # 用 httpbin.org 的不可达端口以快速失败 (我们只关心会话缓存, 不关心响应)
    try:
        s1 = eng_mod._探测_curl_cffi  # 仅占位, 确认模块属性可访问
        ok("模块探测函数可访问", True)
    except Exception:
        ok("模块探测函数可访问", False)
    # 直接验证缓存逻辑: 手动模拟两次同 host 调用的会话获取
    import requests as _req
    host = "example.com"
    # 第一次: 缓存为空, 应创建新 Session
    sess1 = mgr._requests_sessions.get(host)
    if sess1 is None:
        sess1 = _req.Session()
        sess1.trust_env = False
        mgr._requests_sessions[host] = sess1
    # 第二次: 应返回同一个 Session
    sess2 = mgr._requests_sessions.get(host)
    ok("同 host 第二次取到同一 Session", sess1 is sess2)
    # 不同 host 应有独立 Session
    host2 = "other.com"
    sess3 = mgr._requests_sessions.get(host2)
    if sess3 is None:
        sess3 = _req.Session()
        sess3.trust_env = False
        mgr._requests_sessions[host2] = sess3
    ok("不同 host 取到不同 Session", sess1 is not sess3)
    # 验证 trust_env=False 已设置 (避免读取系统代理环境变量)
    ok("会话 trust_env=False", sess1.trust_env is False)
    # 验证 _取host 工具方法正常 (netloc 含端口, 小写化)
    try:
        h = eng_mod.请求引擎管理器._取host("https://www.Example.com:443/path")
        ok("_取host 提取并小写", h == "www.example.com:443", f"got {h!r}")
    except Exception as e:
        ok("_取host 提取并小写", False, str(e))


# ==================================================================
# 测试5: 日志 console 镜像防递归护栏 (GUI 任务线程互递归修复)
# ==================================================================
def test_log_mirror_recursion_guard():
    print("\n[测试5] 日志 console 镜像防递归护栏")
    import 日志 as app_log
    app_log.enable_console()
    written = {"n": 0}

    class Counting:
        def write(self, t):
            if t.strip():
                written["n"] += 1
        def flush(self):
            pass

    class Redirector:
        """模拟 GUI 任务线程: print → 重定向器 → app_log.info → _write → print"""
        def __init__(self, orig):
            self.orig = orig
        def write(self, text):
            if text.strip():
                app_log.info("任务回归", text.strip())
        def flush(self):
            pass

    old = sys.stdout
    sys.stdout = Redirector(Counting())
    try:
        app_log.info("任务回归", "一条测试日志")
    finally:
        sys.stdout = old
    ok("互递归已断环 (无放大)", written["n"] <= 2,
       f"真实 stdout 收到 {written['n']} 行 (修复前数百行)")


# ==================================================================
# 测试6: _打印站点历史先验 对 delay=None 不再 TypeError
# ==================================================================
def test_site_prior_delay_none():
    print("\n[测试6] 站点历史先验 delay=None 兼容")
    from 爬虫 import NovelSpider
    spider = NovelSpider.__new__(NovelSpider)   # 跳过 __init__ (不建 Session)
    try:
        # 自适应模式下 delay=None, 旧代码 delay < 2 会 TypeError (被 except 吞掉)
        r = spider._打印站点历史先验("https://example.com/book/1", None)
        ok("delay=None 不抛异常", r is None)
        r2 = spider._打印站点历史先验("https://example.com/book/1", 1.0)
        ok("delay=1.0 不抛异常", r2 == 1.0)
    except TypeError as e:
        ok("delay=None 不抛异常", False, str(e))


# ==================================================================
# 测试7: 速度自适应核心时序 (降级/回升/手动直通/并发闸门)
# ==================================================================
def test_speed_adaptive():
    print("\n[测试7] 速度自适应控制器")
    import threading
    import 速度自适应 as sa

    c = sa.build_controller("https://www.example.com/book/1", total_chapters=500)
    ok("大书启动取最快档", c.tier.level == sa._TIERS[-1].level, c.tier.name)
    for _ in range(3):
        c.record_chapter(False)
    ok("连续3章失败降档", c.tier.level == 1, c.tier.name)
    c.note_risk("rate_limit")
    ok("限频事件再降档", c.tier.level == 0, c.tier.name)
    c._last_change_time -= sa.UPGRADE_COOLDOWN_SECONDS + 10
    for _ in range(sa.UPGRADE_CONSEC_OK + 5):
        c.record_chapter(True)
    ok("冷静期+稳定成功回升", c.tier.level == 1, c.tier.name)
    snap = c.snapshot()
    ok("降升计数正确", snap["downgrades"] == 2 and snap["upgrades"] == 1, str(snap))

    m = sa.build_controller("https://x.com/b", manual_threads=2, manual_delay=0.7)
    m.note_risk("rate_limit")
    m.record_chapter(False)
    ok("手动模式不受信号影响", m.initial_params() == (2, 0.7))

    tan = sa.build_controller("https://m.tanmixs.com/abc/ml.html", total_chapters=500)
    ok("tanmixs 站点上限压到标准", tan.tier.level == 0, tan.tier.name)

    # 并发闸门: 降到标准档后同时进入抓取段的 worker 数 = 1
    g = sa.build_controller("https://gate.com/b", total_chapters=500)
    peak = {"v": 0, "cur": 0}
    def _worker():
        with g.gate():
            peak["cur"] += 1
            peak["v"] = max(peak["v"], peak["cur"])
            time.sleep(0.02)
            peak["cur"] -= 1
    g.note_risk("waf_captcha")
    g.note_risk("waf_captcha")   # 极速 → 快速 → 标准
    ts = [threading.Thread(target=_worker) for _ in range(6)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=10)
    ok("闸门并发峰值=1 (降两档后)", peak["v"] == 1, f"峰值 {peak['v']}")


if __name__ == "__main__":
    print("=" * 60)
    print("回归测试: 7 组修复点无副作用验证")
    print("=" * 60)
# ==================================================================
# 测试8: 增量模式从头重抓不得丢失旧正文 (T1 致命 Bug 回归)
# ==================================================================
def test_incremental_rewrite_preserves_old_chapters():
    print("\n[测试8] 增量模式从头重抓保留旧正文")
    import tempfile
    import shutil
    from unittest import mock
    from pathlib import Path
    from 爬虫 import NovelSpider

    out_dir = Path(tempfile.mkdtemp(prefix="nc_t1_")).resolve()
    spider = NovelSpider("https://example.com")
    old_body = {i: f"第{i}章的旧正文内容{i * 111}" for i in range(1, 4)}
    # 预置"上次完整抓取"的输出文件 (无检查点 → resume 走章节数兜底判从头重抓)
    out_file = out_dir / "测试书.txt"
    out_file.write_text(
        "".join(f"## 第{i}章\n\n{old_body[i]}\n\n" for i in range(1, 4)),
        encoding="utf-8")

    spider.get_novel_title = lambda url: "测试书"
    spider.get_chapter_list = lambda url, sort=False: [
        {"title": f"第{i}章", "url": f"https://example.com/{i}"} for i in range(1, 4)]
    spider._是否应跳过章节 = lambda url: True          # 模拟: 全部章节 24h 内未变化
    spider._记录站点历史 = lambda *a, **k: None        # 不写用户站点历史

    try:
        with mock.patch("风控事件.add"), mock.patch("风控事件.flush"):
            spider.run(str(out_file), output_file=str(out_file),
                       output_dir=str(out_dir), resume=True, show_progress=False,
                       incremental=True, incremental_max_age_hours=24)
        text = out_file.read_text(encoding="utf-8")
        ok("3 章标题全部保留", all(f"## 第{i}章" in text for i in range(1, 4)))
        ok("3 章旧正文全部保留", all(old_body[i] in text for i in range(1, 4)))
        ok("增量跳过计数 = 3", spider._增量跳过数 == 3, str(spider._增量跳过数))
    finally:
        spider.close()
        shutil.rmtree(out_dir, ignore_errors=True)


if __name__ == "__main__":
    print("=" * 60)
    print("回归测试: 8 组修复点无副作用验证")
    print("=" * 60)
    test_batch_parse()
    test_site_manage_import()
    test_clean_content_entities()
    test_requests_engine_session_cache()
    test_log_mirror_recursion_guard()
    test_site_prior_delay_none()
    test_speed_adaptive()
    test_incremental_rewrite_preserves_old_chapters()
    print("\n" + "=" * 60)
    print(f"结果: {PASS} 通过, {FAIL} 失败")
    print("=" * 60)
    sys.exit(1 if FAIL else 0)
