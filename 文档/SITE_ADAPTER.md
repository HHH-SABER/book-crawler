# 站点适配模式库使用说明

## 文件位置

`源码/sites_config.py` — 集中管理所有小说网站的适配配置。

## 已支持的模式

### 1. qsbs.bb Base64 加密模式
**适用站点**: zhiruo.org, biquwx.cc, ahxsw.com, 28zw.org, spscl.com (云趣阁)

**特征**:
- 章节页 HTML 中，正文不是普通文本，而是 `<script>document.writeln(qsbs.bb('BASE64编码'))</script>` 脚本块
- 每个 `<p>` 段落对应一个 Base64 块
- 分页格式: `{章节ID}.html` → `{章节ID}_1.html` (第2页开始)
- 反爬机制: `ge_js_validator` JS cookie 校验（首次访问返回小校验页，设置 cookie 后重试）

**云趣阁 (28zw.org/spscl.com) 特别说明**:
- 目录页: `/book/{aid}/ml{N}.html` (ml1, ml2, ... 分页; 详情页含"最新章节"倒序+"章节列表"正序, 需去重排序)
- 章节页: `/book/{aid}/{cid}.html` (spscl.com 用 `/yue/{aid}/{cid}.html`)
- 正文容器: `div.content` / `div.word_read` (但 requests 拿到的是 Base64 加密版, 容器内只有广告占位)
- 解码后每个 `<p>` 混有广告行, 用 `content_extractor: 'yunquge_p_filter'` 标记调用专用提取器过滤:
  - "一秒记住新域名 https://..." (含 URL 的广告)
  - "请勿开启浏览器阅读模式..."
  - "相邻推荐:..." / 纯推荐书名列表 (多书名以连续空格分隔)
  - "XXX最新章节txt——..." / "创作者：" / "创作完成日：" 元信息
  - "myJs.bookJs2();" 等 JS 残留
- **分页重复特性**: 每页会包含前页部分内容 (类似"回顾"), 合并后用 `deduplicate_paragraphs()` 按段落指纹去重

**检测方法**:
```python
from sites_config import detect_qsbs_bb_pattern
if detect_qsbs_bb_pattern(html):
    print("此站使用 qsbs.bb 加密")
```

---

### 2. 两步 AJAX 动态加载模式
**适用站点**: 11bzw.org (及任何使用 `/api/read_sign.php` 两步加载的站点)

**特征**:
- 章节页原始 HTML 不含正文，只有导航结构
- 正文通过两步 AJAX 请求动态注入:
  - 第1步: `GET /api/read_sign.php?aid=X&cid=Y` 获取签名 `{sign, bk}`
  - 第2步: `GET /read/X/Y.html?ajax=1&aid=X&cid=Y&bk=Z&sign=S` 获取正文 HTML
- 分页格式: `{章节ID}.html` → `{章节ID}_2.html` (第2页，注意从 2 开始)
- 反爬机制: PHPSESSID / SSRID session cookie

**检测方法**:
```python
from sites_config import detect_ajax_pattern
if detect_ajax_pattern(html):
    print("此站使用两步 AJAX 加载")
```

**通用提取 (不依赖域名)**:
主爬虫 `get_chapter_content` 中的通用自动检测分发层会通过 `_detect_content_pattern()`
识别页面 HTML 中的 `/api/read_sign.php` 特征, 自动调用 `_extract_ajax_two_step_generic()`:
- 从 URL 通用正则 `/{prefix}/{aid}/{cid}(_{N})?.html` 提取 aid/cid 和 page_path
- 若 URL 提取失败, 回退到从页面 HTML 中的 `read_sign.php?aid=X&cid=Y` 引用提取
- 执行两步 AJAX 获取正文, 用 `_is_ad_line()` 逐行过滤广告/导航行
- 适用于任何采用相同 AJAX 协议的站点, 无需为每个域名单独写分支

---

### 3. 通用 BeautifulSoup 选择器模式
**适用站点**: 大多数传统小说站

**特征**:
- 章节页 HTML 直接包含正文
- 通过 CSS 选择器按优先级提取: `#content`, `.content`, `#nr1`, `#bookcontent` 等
- 分页格式多样，需根据站点具体情况配置

---

### 4. Selenium 浏览器渲染模式
**适用站点**: pjxdd.com, qingheks.com, 27xsw.cc

**特征**:
- 普通 requests 完全无法获取任何正文内容
- 必须使用 Selenium/Playwright 无头浏览器渲染页面
- 反爬机制: 返回 challenge 验证页，需要浏览器执行 JS

---

## 为新站点添加适配

### 步骤 1: 探测站点特征

运行 `_site_probe.py` (需自行创建) 或手动检查:

1. **是否有 qsbs.bb 加密?** 查看章节页源码，搜索 `qsbs.bb` 字符串
2. **是否有 AJAX 加载?** 查看是否有 `/api/read_sign.php` 引用，或检查 `<div id="content">` 是否为空
3. **正文是否直接在 HTML?** 查看是否能通过 `#content` 等选择器提取到 500+ 字符文本
4. **分页格式?** 查看下一页链接的 URL 格式 (如 `_1.html`, `_2.html`, `/2/` 等)
5. **反爬机制?** 首次请求是否返回小页面 (200-500 字节)，是否有 `ge_js_validator`

### 步骤 2: 在 SITE_PATTERNS 中添加配置

编辑 `源码/sites_config.py`，在 `SITE_PATTERNS` 列表中添加条目:

```python
{
    'domain': '新站点域名.com',
    'pattern': PATTERN_QSBS_BB,  # 或 PATTERN_AJAX_TWO_STEP / PATTERN_HTML_SELECTOR
    'catalog_parser': 'generic',  # 'generic' / 'biquwx' / '11bzw' / 'zhiruo' / 'yunquge'
    'chapter_url_regex': r'/(\d+)/(\d+)\.html',  # 从目录页 href 提取 (小说ID, 章节ID)
    'content_pagination': {
        'suffix': '_{N}.html',  # 分页后缀模板, {N} 会被替换为页码
        'start': 1,            # 第2页的编号 (1=第2页_1, 2=第2页_2)
        'max_pages': 30,       # 最多抓取页数
    },
    'content_selectors': ['#content', '.content'],  # HTML_SELECTOR 模式使用
    'content_extractor': None,  # 可选: 'yunquge_p_filter' 用于云趣阁广告行过滤
    'anti_spider': {'type': 'js_cookie', 'cookie_name': 'ge_js_validator_20'},
},
```

### 步骤 3: 测试

```bash
cd k:\程序文件\小说爬虫\src
python 爬虫.py "https://www.新站点.com/小说/12345/" --test
```

如果成功，直接运行完整抓取:
```bash
python 爬虫.py "https://www.新站点.com/小说/12345/"
```

### 步骤 4: 如果自动匹配失败

运行自动探测:
```python
from sites_config import auto_detect_pattern
pattern = auto_detect_pattern(session, url, headers, base_url)
# 返回值: 'qsbs_bb' / 'ajax_two_step' / 'html_selector' / None
```

如果返回 `None`，说明该站点使用了新模式，需要:
1. 分析其特征
2. 在 `sites_config.py` 中添加新的模式常量和提取函数
3. 在 `extract_content` 函数中添加对应的分发逻辑

## 正文清洗与排版

`爬虫.py` 提供三层清洗机制, 确保输出正文干净、排版整齐:

### 1. `clean_content(content)` — 通用正文清洗 (适用于所有网站)
- **移除零宽/不可见字符** (U+200B 零宽空格 / U+200C ZWNJ / U+200D ZWJ / U+FEFF BOM /
  U+2060 Word Joiner / U+00AD 软连字符), 部分网站用于反爬/水印, 通用清理
- 修复 HTML 实体 (ldquo/rdquo/hellip/mdash 等)
- 修复常见编码错误字符 (口禽→噙, 昏蛋→混蛋 等)
- 移除页码标记 (如 "（第1页）")
- **按行过滤广告/导航/无意义字符**: 通过 `_is_ad_line()` 基于内容特征识别,
  不依赖具体书名/站点名 — 结构特征 (相邻推荐列表/纯数字行/域名行/纯符号行) +
  标签特征 (XX小说网/XX阅读网/最新章节/txt下载等通用后缀) + 站点宣传语通用片段,
  适用于所有小说网站
- 跳过含 URL/邮箱的行
- 跳过过短行 (<5字) 和符号为主的行
- **段落排版整理**: 合并碎片化短行 (非对话引语且<25字) 到上一段, 使段落完整连贯

### 2. `deduplicate_paragraphs(content)` — 整章段落去重
- 在 `get_chapter_content` 返回前统一调用
- 按段落指纹 (前60字) 去重, 保留首次出现的段落
- 短段落 (<60字) 不参与去重, 保留对话引语、短句等
- 解决云趣阁等站点分页时每页包含前页内容导致的重复

### 3. `get_novel_title(catalog_url)` — 小说标题清理
- 云趣阁 (28zw.org/spscl.com) 详情页 `<title>` 格式为
  "书名最新章节列表_书名刚刚更新(作者)_云趣阁"
- 优先从 `<h1>` 或书名容器提取纯书名
- 失败则从 `<title>` 正则提取 "书名最新章节" 前的书名
- 移除残留的 "txt"/"全文阅读" 等垃圾词

## 已适配站点清单

| 站点 | 模式 | 目录解析 | 分页起始 | 反爬 |
|------|------|----------|----------|------|
| zhiruo.org | qsbs_bb | zhiruo (onclick) | 1 | ge_js_validator JS cookie |
| biquwx.cc | qsbs_bb | biquwx (/txt.shtml) | 1 | ge_js_validator JS cookie |
| ahxsw.com | qsbs_bb | generic | 1 | ge_js_validator JS cookie |
| 28zw.org | qsbs_bb | yunquge (/book/{aid}/ml{N}.html) | 1 | ge_js_validator JS cookie |
| spscl.com | qsbs_bb | yunquge (/yue/{aid}/ml{N}.html) | 1 | ge_js_validator JS cookie |
| 11bzw.org | ajax_two_step | 11bzw (/read/) | 2 | session cookie |
| yqyp.net | html_selector | yqyp (强制PC UA) | 2 | js_cookie (ge_js_validator_20) |
| pjxdd.com | selenium | generic | 1 | challenge 验证页 |
| qingheks.com | selenium | generic | 1 | challenge 验证页 |
| 27xsw.cc | selenium | generic | 1 | challenge 验证页 |

---

## 附录：历史修订与设计记录

### A. 早期设计目标（2026/2/7 制定，现已全部实现）

> 原文档：`修改小说爬虫脚本.md` / `修复爬虫脚本内容提取问题.md`（已归档，不再单独保留）

**核心目标**：
1. **文档名称改为小说名称** — 从目录页 `<title>` 或 H1 提取小说标题作为输出文件名，避免与站点绑定
2. **支持不同小说站点** — 移除硬编码的小说 ID（如 `391625`）和 URL 前缀，统一走"目录页结构分析 + 通用内容检测"分发
3. **删除冗余代码** — 保留关键能力（Base64 解码、分页处理、断点续传、反爬重试），删除孤立调试分支
4. **支持用户输入** — 新增交互式菜单 + 命令行参数 + 启动爬虫.bat 一键入口

**早期遇到的内容提取问题（同样已修复）**：
1. 网站结构变化 → 通过 `sites_config.py` 集中管理 + `_detect_content_pattern` 特征识别兜底
2. 内容编码方式 → 通用层支持 qsbs_bb Base64 / AJAX 两步 / HTML 选择器 / Selenium 四种模式
3. 反爬机制 → `_get_with_js_challenge` 处理 JS cookie 校验、PC UA 重试、AJAX 签名模拟
4. 选择器不正确 → `_extract_html_selector_generic` 遍历 14 种常见容器取最长结果，并支持 PC UA 重试

### B. 2026/8 通用化重构摘要

- 新增 `_detect_content_pattern()` 自动识别分发层，优先于域名分支
- 新增三种通用提取：`_extract_qsbs_bb_generic` / `_extract_ajax_two_step_generic` / `_extract_html_selector_generic`
- 零宽字符通用清理、通用广告行识别（`_is_ad_line()`）、PC UA 重试、段落指纹去重
- 输出目录统一为绝对路径（项目根/抓取结果/），并通过 `--output-dir` 支持覆盖；bat 入口强制指定

> 当通用层稳定后可删除 爬虫.py 中三处标记为「向后兼容备用分支」的旧域名硬编码逻辑。
