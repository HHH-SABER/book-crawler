> **v2.4.34 本地交付（2026-09-30）**：保留原项目和原依赖版本。直接运行 `dist/小说爬虫.exe`；源码入口 `启动GUI.bat` / `启动爬虫.bat` / `启动远控.bat` 优先使用随包 `.runtime/python314` 和原 `.venv/Lib/site-packages`，无需依赖原作者的 `F:/Python` 或本轮工作目录。GUI 源码优先使用同包 Flet 客户端，避免首启下载。
> 开发/测试：`.runtime\python314\python.exe -m unittest discover -s 测试 -v`；构建：`.runtime\python314\python.exe 脚本\build_exe.py --version=2.4.34`（设置 `FLET_CACHE_DIR` 指向 `.runtime/flet_client`）。若自行重建环境，Python 3.14 + `requirements.txt` 与 `requirements-lock.txt`；Rust 可选并保留 Python 回退。
> 便携运行时为官方 CPython 3.14.0 Windows x64 嵌入版；第三方库复用附件原件，无新增 Python 包。Chrome/Playwright 浏览器程序仍按原项目要求由目标机提供。

# 小说爬虫 (Book Crawler)

多站点小说爬虫，支持 Flet 桌面 GUI 和 Windows EXE 打包。
自动识别反爬机制（验证码 / 频率限制 / UA 校验 / JS 质询等），
多引擎自动降级（requests → cloudscraper → curl_cffi），
内容语义质检过滤无意义数据，按 URL 维度记录爬取历史并支持增量爬取。

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
