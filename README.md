# 小说爬虫 (Book Crawler)

多站点小说爬虫，支持 Flet 桌面 GUI 和 Windows EXE 打包。

## 项目结构

```
小说爬虫/
├── 源码/                        # 源代码目录
│   ├── 爬虫.py                  # 主爬虫模块（NovelSpider 核心，~4400行）
│   ├── _path_utils.py          # 路径解析工具（源码/打包双模式兼容）
│   ├── browser_driver.py       # Selenium 浏览器驱动封装
│   ├── captcha_module.py       # 验证码识别模块（可插拔）
│   ├── content_decoder.py      # 内容解码器（Base64/码点流/高频字压缩）
│   ├── decrypt_utils.py        # 解密工具集
│   ├── sites_config.py         # 站点适配配置（URL模式 + 解析规则）
│   ├── gui_app.py              # Flet GUI 主程序入口
│   └── gui_components/         # GUI 组件包
│       ├── __init__.py
│       ├── config_tab.py       # 站点配置页签
│       ├── crawl_tab.py        # 抓取页签
│       ├── preview_tab.py      # 结果预览页签
│       └── task_manager.py     # 异步任务管理器
├── 配置/                      # 配置文件目录
│   └── captcha_config.json     # 验证码模块配置（策略开关、API密钥等）
├── 文档/                        # 项目文档目录
│   ├── SITE_ADAPTER.md         # 站点适配器开发指南
│   ├── 优化检查报告.md          # 代码优化与测试报告
│   ├── 验证码模块使用说明.md    # 验证码功能使用说明
│   └── 验证码模块合规评估.md    # 验证码模块法律合规评估
├── 脚本/                     # 构建与工具脚本目录
│   ├── build_exe.py            # EXE 打包脚本（flet pack）
│   ├── ensure_flet_cache.py    # Flet 客户端缓存预下载
│   ├── 打包EXE.bat             # 打包启动脚本（BAT）
│   └── 打包EXE.ps1             # 打包启动脚本（PowerShell）
├── 测试/                       # 测试文件目录
│   └── __init__.py
├── 抓取结果/                     # 抓取结果输出目录（运行时生成）
├── .gitignore                   # Git 忽略规则
├── LICENSE                      # 开源许可证
├── README.md                    # 项目说明文档
├── requirements.txt             # Python 依赖清单
├── 小说爬虫.spec                # PyInstaller 打包配置
├── 启动爬虫.bat                  # CLI 命令行启动脚本
└── 启动GUI.bat                  # GUI 图形界面启动脚本
```

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
```

### 打包 EXE

```
双击 脚本\打包EXE.bat
```

或使用 PowerShell：
```powershell
powershell -ExecutionPolicy Bypass -File 脚本\打包EXE.ps1
```

## 支持的站点

内置多站点适配器，包括：
- 笔趣阁系列（HTML 选择器解析）
- 第一版主网（Base64 加密内容）
- tanmixs（.xs 码点流加密）
- 11bzw.org（AJAX 两步加载）
- 言情一品书、我去读小说等

添加新站点请参考 [文档/SITE_ADAPTER.md](文档/SITE_ADAPTER.md)。

## 技术栈

- **爬虫引擎**：requests + BeautifulSoup4 + Selenium
- **GUI 框架**：Flet 0.86+（Flutter 桌面应用）
- **打包工具**：PyInstaller / flet pack
- **验证码识别**：ddddocr + OpenCV（可选）

## 许可证

见 [LICENSE](LICENSE) 文件。
