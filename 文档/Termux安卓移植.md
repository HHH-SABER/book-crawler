# Termux (安卓) 移植路线

> 对应行动清单 P2「安卓/Termux 移植路线」。匹配"计划移植安卓"画像；
> fanqienovel-downloader 已打通 Termux，本方案为同路径低成本验证。

## 一、能做什么 / 不能做什么

| 能力 | Termux 版 | 说明 |
|---|---|---|
| 多站目录/正文抓取 | ✅ | 核心 CLI 全功能 (多模式/断点续传/增量/一键更新) |
| 内容清洗排版/质检 | ✅ | 纯 Python, 完整可用 |
| EPUB 导出 | ✅ | ebooklib (lxml) |
| 反爬多引擎降级 | ⚠️ 部分 | requests + cloudscraper 可用; curl_cffi(TLS) 需编译 |
| 浏览器渲染 (selenium/playwright) | ❌ | 安卓无 Chrome 桌面版, 已降级 |
| 验证码 OCR (ddddocr/opencv) | ❌ | 重依赖难装, 已降级 |
| 桌面 GUI (flet) | ❌ | flet 桌面版不支持安卓; CLI 为入口 |

> 核心抓取不受影响：项目顶层依赖仅 requests/bs4/lxml/fake-useragent，
> selenium/playwright/opencv/ddddocr/curl_cffi 均为延迟导入，
> 缺失时自动降级（请求引擎回退 requests）。

## 二、安装

1. 安装 [Termux](https://f-droid.org/packages/com.termux/) (F-Droid 版)
2. 手机克隆/拷贝本项目到 Termux 可读目录（如 `~/storage/downloads/小说爬虫`）
3. 进入项目根目录执行：

```bash
bash 脚本/termux_setup.sh
```

或手动安装：

```bash
pkg update -y
pkg install -y python clang libxml2 libxslt binutils
python -m pip install --upgrade pip
pip install -r requirements-termux.txt
```

> 可选 TLS 指纹 (curl_cffi)：`pkg install rust` 后取消
> `requirements-termux.txt` 中 `curl_cffi` 注释再 `pip install -r requirements-termux.txt`。

## 三、使用

```bash
cd 项目目录
python 源码/启动器.py <小说目录页URL>          # 完整抓取
python 源码/启动器.py <URL> --list            # 仅章节列表
python 源码/启动器.py <URL> --test            # 测试模式
python 源码/启动器.py <URL> --epub            # 抓完导出 EPUB
python 源码/启动器.py --update                # 一键更新书架 (增量)
python 源码/启动器.py --batch books.txt       # 批量抓取
```

输出默认到 `抓取结果/`（在 Termux 中即为项目目录下，可经文件管理器/网盘同步）。

## 四、限制与后续

- **强反爬站点**（Selenium challenge / TLS 指纹 / 图片验证码）在 Termux 上成功率下降；
  轻反爬站（js_cookie / 频率限制）不受影响
- **真正安卓原生版**（GUI）需后续评估 flet 安卓 APK 或 Kivy；
  当前 Termux CLI 为"计划移植安卓"的最低成本验证，核心抓取逻辑与桌面版完全一致
