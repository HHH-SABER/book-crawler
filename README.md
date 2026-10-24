# 小说爬虫 (Book Crawler)

[![CI](https://github.com/HHH-SABER/book-crawler/actions/workflows/test.yml/badge.svg)](https://github.com/HHH-SABER/book-crawler/actions/workflows/test.yml)
[![Release](https://img.shields.io/github/v/release/HHH-SABER/book-crawler?label=Release)](https://github.com/HHH-SABER/book-crawler/releases/latest)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/)

多站点小说爬虫，支持 Flet 桌面 GUI 和 Windows EXE 打包。
自动识别反爬机制（验证码 / 频率限制 / UA 校验 / JS 质询等），
多引擎自动降级（requests → cloudscraper → curl_cffi），
内容语义质检过滤无意义数据，按 URL 维度记录爬取历史并支持增量爬取。

> **快速上手**：直接下载 [Releases](https://github.com/HHH-SABER/book-crawler/releases/latest)
> 里的 `novel-crawler-*.exe`（免安装，含运行时）；源码运行见下方
> [快速开始](#快速开始)。手机远控见 [手机远控](#手机远控)。
> chromedriver **无需手动下载** —— 程序自动检测 Chrome 版本并匹配（见 `源码/驱动管理.py`）。

> ## ⚠️ 合规声明
>
> 本项目**仅供个人学习与技术研究使用，请勿用于任何商业用途**。
> 抓取的小说内容版权归原作者 / 原网站所有，请在下载后 **24 小时内删除**。
> 使用前请遵守相关法律法规及目标网站的 robots.txt 与服务条款，合理控制抓取频率，
> 避免对目标网站服务器造成压力；因使用本项目产生的任何法律风险由使用者自行承担。

## 项目结构

```
小说爬虫/
├── 源码/                        # 源代码目录 (Python 模块根, 导入路径依赖)
│   ├── 爬虫.py                  # 主爬虫模块 (NovelSpider 核心)
│   ├── 反爬检测器.py            # 反爬机制自动识别
│   ├── 内容质检器.py            # 内容语义质检 (五维评分)
│   ├── 请求引擎.py              # 多引擎请求 (requests/cloudscraper/curl_cffi)
│   ├── 爬取历史.py              # 爬取历史记录 (URL 维度 + 增量爬取)
│   ├── 站点历史.py              # 站点抓取历史 (跨会话先验知识)
│   ├── site_probe.py            # 站点探测 (站点管理页"测试连接")
│   ├── sites_config.py          # 站点适配配置 (运行时合并 站点配置.json)
│   ├── epub_exporter.py         # EPUB 导出器 (txt→EPUB, ebooklib)
│   ├── _path_utils.py           # 路径解析工具 (源码/打包双模式兼容)
│   ├── browser_driver.py        # Selenium 浏览器驱动封装
│   ├── captcha_module.py        # 验证码识别模块 (可插拔)
│   ├── content_decoder.py       # 内容解码器 (Base64/码点流/高频字压缩)
│   ├── decrypt_utils.py         # 解密工具集
│   ├── waf_captcha.py           # WAF 验证码自动解决
│   ├── 日志.py                  # 统一日志模块
│   ├── 启动器.py                # ASCII 启动入口 (bat 调用, 规避中文编码问题)
│   ├── gui_app.py               # Flet GUI 主程序入口 (v3 紧凑布局)
│   └── gui_components/          # GUI 组件包 (导入路径依赖)
│       ├── task_manager.py      # 多任务管理器 (指标日志解析)
│       ├── icon_rail.py         # 图标导航栏
│       ├── input_bar.py         # 单行紧凑输入条 (含导出EPUB开关)
│       ├── task_table.py        # 全宽任务表格 (引擎/反爬/质检指标列)
│       ├── row_detail.py        # 任务行内展开详情
│       ├── log_strip.py         # 可折叠日志条
│       ├── detail_drawer.py     # 右侧上下文抽屉 (任务详情/文件预览)
│       ├── ui_morandi.py        # 莫兰迪主题 + 渲染图风格浅色配色
│       ├── ui_theme.py          # UI 主题系统 (卡片/按钮/状态标签)
│       ├── pages/               # 独立页面子包
│       │   ├── history_page.py        # 爬取历史页 (统计卡+过滤器+明细)
│       │   ├── site_manage_page.py    # 站点管理页 (健康度/启停/测试连接)
│       │   └── history_data.py        # 历史数据源封装
│       └── crawl_tab.py 等      # 旧版页签 (GUI v2 遗留, 已废弃保留)
├── 站点适配/                    # 外部站点适配器插件目录 (免重新打包扩展新站; 公开侧仅 _模板.py)
├── 站点适配_本地/               # 真实站点适配器与站点表 (不入库; 公开仓库不含)
├── 测试样本_本地/               # 站点适配测试样本 (真实快照, 不入库; 公开仓库不含)
├── 脚本/                        # 构建与工具脚本目录
│   ├── build_exe.py             # EXE 打包脚本 (自动版本号 + CHANGELOG 同步)
│   ├── 打包EXE.bat              # 打包启动脚本 (双击运行)
│   ├── 图标.ico                 # 应用图标
│   ├── 版本.json                # 版本状态持久化
│   ├── ensure_flet_cache.py     # Flet 客户端缓存预下载
│   ├── check_undefined_refs.py  # 未定义引用检查
│   └── _test_*.py               # 单元测试脚本
├── 配置/                        # 配置文件目录
│   └── captcha_config.json      # 验证码模块配置 (策略开关、API密钥等)
├── 文档/                        # 项目文档目录
│   ├── SITE_ADAPTER.md          # 站点适配器开发指南
│   ├── 远控使用教程.md          # 手机远控: 安装/操作/FAQ/故障排除
│   ├── 日志使用说明.txt         # 日志位置/格式/级别说明
│   ├── 优化检查报告.md          # 代码优化与测试报告
│   ├── 验证码模块使用说明.md    # 验证码功能使用说明
│   ├── 审查报告汇总.md          # 历次审查报告单一归档
│   ├── 实施计划.md              # 方案设计与调研归档
│   └── 修改记录.md              # 落地修改登记台账
├── 数据/                        # 运行时数据目录 (站点历史/爬取历史 JSON)
├── 抓取结果/                    # 抓取结果输出目录 (运行时生成, 不入库)
├── 日志/                        # 运行时日志目录 (按日期, 保留30天, 不入库)
├── .gitignore                   # Git 忽略规则
├── LICENSE                      # 开源许可证
├── README.md                    # 项目说明文档
├── requirements.txt             # Python 依赖清单
├── 小说爬虫.spec                # PyInstaller 打包配置
├── 启动爬虫.bat                  # CLI 命令行启动脚本
└── 启动GUI.bat                  # GUI 图形界面启动脚本
```

> 说明：`源码/`、`gui_components/`、`pages/` 为 Python 模块/包名，
> 被导入路径与打包配置引用，故保留原名。`dist/` 为打包产物目录（被 git 忽略）。

## 快速开始

### 环境要求

- Python 3.10+
- Chrome 浏览器（Selenium 反爬需要）
- Windows 操作系统（GUI 和打包功能）
- **发行版 EXE 仅支持 Windows x64（64 位）**——产物为 PE32+ x86-64，打包脚本已内建架构自检（2026-10-25 起）

### 安装依赖

```bash
# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境
.venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

### 运行

**GUI 模式**（推荐）：
```
双击 启动GUI.bat
```

**命令行模式**：
```bash
# 交互式
启动爬虫.bat

# 直接抓取
启动爬虫.bat <小说目录页URL>

# 仅获取章节列表
启动爬虫.bat <URL> --list

# 测试模式（只抓前3章）
启动爬虫.bat <URL> --test

# 抓取完成后同时导出 EPUB 电子书
启动爬虫.bat <URL> --epub
```

### 打包 EXE

```
双击 脚本\打包EXE.bat
```

每次打包自动递增版本号（`--bump=patch/minor/major`）并同步 CHANGELOG.md，
产物输出到 `dist\小说爬虫.exe`。

## 站点适配（脱钩说明）

站点适配采用**可插拔适配器**机制。为保护站点隐私，**公开仓库只保留机制、契约与模板，
不含任何真实站点**（域名、站名、快照一概没有）：

- 适配器契约与模板：[`站点适配/_模板.py`](站点适配/_模板.py)（`example.com` 占位，`_` 前缀不加载）
- 开发指南：[文档/SITE_ADAPTER.md](文档/SITE_ADAPTER.md)
- 真实适配器、站点表与测试样本**不入库**，分别放在本机的 `站点适配_本地/`、
  `站点适配_本地/站点表.json` 与 `测试样本_本地/`
  （机制说明见 `AGENTS.md` §目录与文件管理规范 四「站点脱钩（隐私）机制」）

按站点加密形态，适配器层抽象出四类抓取形态：**HTML 选择器解析 / Base64 正文 /
码点流（`.xs` 类）加密 / AJAX 两步加载**；未注册站点走通用提取路径。

添加新站点请参考开发指南：优先用 **JSON 规则**或 `站点适配/*.py` **插件**，
**不要往 `源码/爬虫.py` 里加域名特判**。
站点适配的抓取样本请放在**不入库**的 `测试样本_本地/`。

## 手机远控

电脑挂机抓书，手机远程指挥：**发任务 / 看实时进度与日志 / 中断续传 / 在线阅读 / 下载 EPUB / 完成推送通知**。

- 📖 完整教程：**[文档/远控使用教程.md](文档/远控使用教程.md)**（功能概述 · 核心特性 · 环境要求 · 安装步骤 · 操作指南 · FAQ · 故障排除）
- ⚡ 30 秒上手：桌面客户端顶栏打开"远控"开关（或双击 `启动远控.bat`）→ 常驻机执行 `tailscale serve --bg 8760` → 手机浏览器打开 `https://<机器名>.<tailnet>.ts.net/` → 输入 token（在 `数据/远控配置.json`）

## 技术栈

- **爬虫引擎**：requests + BeautifulSoup4 + Selenium + curl_cffi + cloudscraper
- **反爬识别**：自研反爬检测器（状态码/响应头/正文特征多通道识别）
- **GUI 框架**：Flet 0.86+（Flutter 桌面应用）
- **打包工具**：PyInstaller（onefile + 版本资源文件）
- **验证码识别**：ddddocr + OpenCV（可选）

## Rust 加速（可选）

从 **v2.4.0** 起，内容质检与正文码点流解码可选用 **Rust（PyO3 abi3 扩展）** 加速，
其余功能与架构保持纯 Python，降级安全：

- **接入模块**：`内容质检器.质检` 与 `content_decoder.parse_codepoint_stream`
  在检测到 `源码/rust_core.pyd` 时自动走 Rust；`.pyd` 缺失/异常时**静默回退纯
  Python**，不影响任何功能与现有 EXE 分发。
- **并发收益**：Rust 计算通过 `py.allow_threads` **释放 GIL**，让多 worker 并发
  抓取时这两个 CPU 热点从"进程内 1 核轮流算"变为"多核并行"。真实样本实测
  （8 线程）：解码 ~13x、质检 ~11x 单核；叠加 GIL 释放后并发吞吐再提升 3~5x。
- **兼容**：abi3 产物支持 Python 3.12~3.14；打包由 `脚本/build_exe.py` 自动将
  `.pyd` 打进 EXE（见 CHANGELOG 2.4.0「打包」）。

重建/测试见 [`rust_core_poc/`](rust_core_poc/)（源码 + 基准脚本；本地无链接器/网络
受限时该目录日志含手动构建说明）。并发瓶颈分析见
[`文档/并发瓶颈分析与落地建议.md`](文档/并发瓶颈分析与落地建议.md)。

## 许可证

见 [LICENSE](LICENSE) 文件。

## 项目结构与工程规范（2026-10-13 补齐）

```
小说爬虫/
├─ 源码/                    # 全部运行时代码 (31 个模块, 约 2 万行)
│  ├─ gui_app.py            # Flet GUI 入口 (main(): 窗口装配 + 各视图编排)
│  ├─ gui_components/       # GUI 组件层 (16 模块: 页面/主题/表格/弹窗/任务管理)
│  │  ├─ 首次引导.py         # 首次启动 flag + 桌面快捷方式 (可单测)
│  │  ├─ 补址弹窗.py         # 死书补址两步流程 + 场景分流 (选场景 纯函数)
│  │  └─ ui_fluent.py       # 主题 (含全局 scrollbar_theme 滚动条兜底)
│  │  ├─ ui_motion.py        # 动效令牌与统一出口 (三档时长 + 一键降级)
│  ├─ 爬虫.py                # 抓取引擎 (多引擎降级/分页/去重/质检)
│  ├─ 页面抓取.py            # 引擎降级实现 (缓存/重试/解码/Selenium 兜底)
│  ├─ 目录链接工具.py        # 目录链接判定 + 目录质量 + 正文清洗 (纯函数)
│  ├─ 驱动管理.py            # chromedriver 自动检测/匹配/下载 (需求 #7)
│  ├─ 死书处理.py            # 死书判定 (结构化字段, 无 IO 纯函数)
│  ├─ 界面偏好.py            # 界面开关持久化 (提示音/动效)
│  ├─ 远控/                  # 内嵌远控服务 (自研, 已进 EXE)
│  └─ _path_utils.py        # 路径/状态根 (跨环境: 源码/EXE)
├─ 测试/                    # 公开侧单测 (1200+ 例, CI 跑这套)
│  └─ 样本/                  # 真实页面形态样本 (脱敏, 7 份: 折叠/验证/分页…)
├─ 测试_本地/                # 本地测试 (依赖本机站点适配器, 不入库)
├─ 脚本/                    # 工程脚本
│  ├─ build_exe.py          # 打包 (版本自动 +1, 冒烟强验证)
│  ├─ 组装发布.py            # 组装发布包 (公开包/本机包 + 隐私自检)
│  ├─ 红线扫描.py            # 站点/书名泄露扫描 (--ci / --全量)
│  └─ 脱敏样本.py            # 真实快照 → 可入库样本 (三道硬门禁)
├─ 站点适配/                 # 公开适配器目录 (仅 _模板.py 占位)
├─ 站点适配_本地/            # ★ 真实适配器 + 站点表 + cookies (gitignored, 严禁外传)
├─ 发布/                    # 发布产物 (公开包 + zip, 可独立运行)
├─ dist/                    # 本机构建产物 (含真实适配器, gitignored)
├─ 文档/                    # CHANGELOG 在仓库根; 此处为设计/审查/踩坑记录
└─ .runtime/                 # 便携 Python 3.14 + flet 客户端缓存 (gitignored)
```

### 常用命令

```bash
# 开发期门禁 (提交前必跑, CI 同款)
.runtime\python314\python.exe -m unittest discover -s 测试          # 1156 例
.runtime\python314\python.exe 脚本\check_undefined_refs.py          # 静态引用检查
.runtime\python314\python.exe 脚本\红线扫描.py --ci                  # 红线 (CI 模式)

# 发版前全量 (最严: 加本地站点词库 + 扫发布产物)
.runtime\python314\python.exe 脚本\红线扫描.py --全量

# 打包 + 冒烟 (版本号自动 +1)
.runtime\python314\python.exe 脚本\build_exe.py

# 组装发布包 (公开包; zip 一并产出)
.runtime\python314\python.exe 脚本\组装发布.py --zip

# 发布: 打 tag 推送即触发 CI (构建 EXE → GitHub Release)
git tag -a vX.Y.Z -m "…" && git push origin vX.Y.Z
```

### 红线纪律（本项目最高约束）

**真实站点信息（域名/站名/站点表/cookies）与书目信息绝不进公开仓库。**
已由 `脚本/红线扫描.py` 固化为门禁（CI 每次推送自动跑），但纪律仍要自觉：

| 场景 | 要求 |
|---|---|
| 源码/测试/文档引用站点 | 一律用代号（`siteX`）或脱敏占位（`siteN.example.com`） |
| 本机数据（适配器/映射/cookies/词库） | 只放 `站点适配_本地/`、`数据/`、`测试样本_本地/`（均 gitignored） |
| 新增公开文件 | `git add` 前跑 `红线扫描.py --全量` |
| 疑似误报 | 在扫描器里加排除项**并注明理由**，不许直接关掉检查 |

### 发版流程（一次通过的顺序）

1. 门禁三件套全绿（单测 / 静态 / 红线 --ci）；
2. `红线扫描.py --全量`（含本地词库 + 发布产物）；
3. `build_exe.py`（自动 +1 版本 + 冒烟强验证）；
4. EXE 功能实测（真机抓一本，确认无回归）；
5. `组装发布.py --zip` + **独立**红线扫描产物；
6. 打 tag 推送 → CI 构建 → 验证 Release 附件与 latest 标记。
