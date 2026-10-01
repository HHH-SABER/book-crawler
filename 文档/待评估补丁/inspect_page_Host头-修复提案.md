# 待评估补丁 · K27：`inspect_page` 硬编码 `Host` 头

> 提出时间：2026-10-01 04:25（WorkBuddy 小元）
> 状态：**未实施，等评估**。本目录不含生产代码，不影响门禁。
> 背景：`站点适配/bookben5.py` 开发中实测发现，详见 `文档/踩坑总表.md` **K27**。

## 1. 问题

`源码/爬虫.py` 的 `inspect_page()` 在构造请求头时**写死了 Host**：

```python
# 源码/爬虫.py 约 1402–1420 行
headers = {
    'User-Agent': self._fixed_ua,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Cache-Control': 'max-age=0',
    'DNT': '1',
    'Sec-GPC': '1',
    'Referer': url,
    'Host': url.split('/')[2],        # ← 问题所在
    ...
}
```

## 2. 后果（实测证据）

站点做**主机级跳转**时（`bookben5.org` → `www.bookben5.org`），带固定 `Host: bookben5.org`
的请求被服务端反复判定为旧主机 → **无限 301**：

```
[爬虫] 请求失败(1/3): Exceeded 30 redirects.
[爬虫] 请求失败(2/3): Exceeded 30 redirects.
[爬虫] 请求失败(3/3): Exceeded 30 redirects.
[爬虫] 请求重试耗尽, 返回空页面(交由调用方Selenium兜底)
```

→ `inspect_page` 返回 `BeautifulSoup('', 'lxml')`（**空页面**）→ 适配器与通用目录解析
都拿不到任何链接 → **目录 0 章**。

**对照实验**（同一 URL、同一 UA，仅去掉 Host 头）：

| 请求 | 结果 |
|---|---|
| 不带 `Host` 头 | **200**，287,806 字符，**1,517 个章节链接** |
| 带 `Host: bookben5.org`（requests 自行处理跳转） | 200，正常 |
| 主程序 `inspect_page`（含硬编码 Host） | **Exceeded 30 redirects** → 空页面 |

> 说明：requests 会把显式传入的 `Host` 一直带过重定向（不重新按新主机生成），
> 这正是循环的成因。`requests` 本身会按 URL 自动生成正确的 `Host`，
> **手写这行没有任何收益**。

## 3. 影响面评估

- **凡是做 www / 主机级跳转的站点**都可能中招（不是 bookben5 独有）。
- 对不做跳转的站点**无影响** —— 这也是它长期潜伏、直到遇见 bookben5 才暴露的原因。
- 现有适配器（washai / als1010 / yunshuzhai 等）的域名不跳转，故未受影响。

## 4. 建议改法（一行）

```diff
--- a/源码/爬虫.py
+++ b/源码/爬虫.py
@@ -1411,7 +1411,6 @@
         'Sec-GPC': '1',
         'Referer': url,
-        'Host': url.split('/')[2],
         # 不要在此硬编码 Cookie 头：requests 传入 headers 中的 Cookie 会覆盖 session.cookies，
         # 导致反爬提取的 cookie(如 zhiruo.org 的 ge_js_validator_20)无法随请求发出，校验永远过不去。
         # 让 session.cookies 自动管理即可。
```

风险点（逐条评估用）：

| # | 疑虑 | 评估 |
|---|---|---|
| 1 | 某些站点是否**依赖**这个 Host 头才给正常响应？ | 未见依据；requests 默认行为就是发正确 Host，去掉后与浏览器一致。**建议在改动后跑一次真实站点抓取回归**（任选 2–3 个现有适配器站点，走 `mode='list'`，比对章数与之前一致）。 |
| 2 | 是否与"验证码 cookie 绑定 UA"等反爬逻辑耦合？ | 无关。UA 仍由 `self._fixed_ua` 控制，Host 是独立维度。 |
| 3 | 是否会改变 `_get_with_js_challenge` 的跳转处理？ | 该函数用同一 headers；去掉 Host 后跳转链正常（这正是修复目的）。 |
| 4 | 有没有别处也固定了 Host？ | 见下方回归测试第 3 条（兜底扫描 `session.headers`）。 |

## 5. 随附的回归测试

`文档/待评估补丁/test_inspect_page_no_hardcoded_host.py`（3 条）——用 AST 定位
`inspect_page` 内的 `headers = {...}`，断言其中**不含 `Host`**。

- 与项目既有"机器执法"风格一致（`test_no_silent_except.py`、`check_undefined_refs.py` 都是扫描源码）。
- **含防"空转通过"的自校验**：若将来 headers 被重构（改名/抽函数），测试会**响亮失败**而不是静默通过。
- 落地方式：修复补丁应用后，把该文件移入 `测试/` 并纳入常规门禁。

## 6. 落地步骤（评估通过后由我执行）

1. 应用上面的一行删除；
2. 把 `test_inspect_page_no_hardcoded_host.py` 移入 `测试/`；
3. 跑门禁（unittest + `check_undefined_refs.py` + 手写回归）；
4. **真实站点回归**：对 2–3 个现有适配器站点跑 `mode='list'`，比对章数与修复前一致；
5. 另对 bookben5 验证：**在适配器自愈关闭**（`allow_self_fetch=False`）的情况下也能解析出 1,504 章
   —— 这一步是"核心修复真正生效"的端到端证明；
6. 更新 `CHANGELOG.md` 与 `文档/修改记录.md`；
7. 提交（点名 add）+ 推送。

## 7. 与现有规避的关系

适配器层的 `站点适配/bookben5.py::_自助抓取` 是**规避**（能跑，但每个跳转站点都要各自打补丁）；
本补丁是**根治**（一处修复覆盖所有跳转站点）。两者可并存：
根治落地后，适配器的自愈路径自然不再被触发，可以保留作为兜底。
