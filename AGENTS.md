# 项目指令 — 小说爬虫 (Book Crawler)

多站点小说爬虫,Python 3.10+ / Flet 0.86 GUI / PyInstaller 打包。约 2 万行。
所有工作遵循项目合规边界:仅供学习研究,验证码自动识别**默认必须关闭**。

## 常用命令

```bash
# 虚拟环境 (所有命令在 .venv 下执行)
.venv\Scripts\activate

# 离线回归测试 (unittest 发现式, 必须全绿才算完成)
python -m unittest discover -s 测试 -v

# 未定义引用静态检查 (改完代码必跑)
python 脚本\check_undefined_refs.py

# 打包 EXE (自动递增版本号 + 同步 CHANGELOG; CI 用同一脚本)
python 脚本\build_exe.py
```

注意:`测试/回归测试_修复验证.py`、`_test_gui_v3.py`、`_test_task_metrics.py` 是手写
`__main__` 脚本,不被 unittest discover 收集,需单独 `python 测试\xxx.py` 运行。

## 文件上传规约 (2026-09-13 定稿, 所有会话必须遵守)

**入库白名单** — 只有以下内容允许 `git add`(新文件先对照本表,不在表内 = 不入库):

| 目录/模式 | 性质 |
|---|---|
| `源码/`、`测试/`、`站点适配/`、`脚本/` | 源码与工具脚本 |
| `测试样本/` | 离线测试 fixture (删除会破坏测试) |
| `文档/`、`界面设计预览/` | 项目文档与设计资源 |
| `配置/`(模板)、`.github/` | 分发配置模板与 CI |
| 根级 `README/CHANGELOG/AGENTS/LICENSE/requirements.txt/.gitignore`、`启动*.bat`、`脚本/图标.ico` | 项目元文件 |

**禁止入库** (即使 `git status` 显示 untracked 也不得 add;已在 .gitignore 则勿改):
1. **运行时用户数据**: `数据/*`(仅 .gitkeep 入库)、`抓取结果*`、根级 `站点配置.json`/`captcha_config.json`(用户本机配置)、`日志/`、`HANDOFF.md`、`/提示词.txt`
2. **会话私有目录**: `.workbuddy/`、`.zcode/`、`.idea/`、`.mimosa/`、`.trae/`、`.vscode/` —— AI 会话的记忆/审查缓存/IDE 配置,一律不入库;**会话结束前应清理自己产生的此类临时文件**
3. **编译/打包产物**: `dist/`、`build/`、`rust_core_poc/**/target/`、`*.spec`、`build_log.txt`、根级 `*.zip`、`小说爬虫.exe`
4. **大体积工具链**: 任何 toolchain/SDK 缓存不得入库或提交 (`rust_core_poc/.toolchain/` 经用户裁决本地保留)

**提交纪律**:
- `git add` 一律**指定文件路径**,禁止 `git add -A` / `git add .`(历史两次误提交 HANDOFF 的根因)
- 提交前 `git status -s` 逐行确认: 出现自己没创建的文件 = 其他会话在途内容,**不得一并提交**
- 新增依赖/模型/大二进制(>1MB)入库前先说明用途征得同意

## 模块地图 (源码/)

| 模块 | 职责 |
|---|---|
| 爬虫.py | NovelSpider 核心上帝类 (7000 行,抓取编排/解析/清洗/断点) — 改动需谨慎 |
| 请求引擎.py | requests → cloudscraper → curl_cffi 多引擎降级链 |
| 反爬检测器.py | 无状态反爬特征识别 (状态码/响应头/正文) |
| 速度自适应.py | 档位控制器 + Condition 并发闸门 (note_risk 降档/record_chapter 回升) |
| 代理池.py / 风控事件.py / 站点漂移检测.py | 按域代理绑定 / JSONL 风控事件 / EMA 基线告警 |
| dns_doh.py | DNS 污染回退 (进程内 patch getaddrinfo + DoH) |
| sites_config.py | 站点适配三层体系: JSON 规则(热重载) / 站点适配/*.py 插件 / 内置 SITE_PATTERNS |
| 内容质检器.py / content_decoder.py / decrypt_utils.py | 五维质检 / 码点流·Base64 解码 / 六种正文解密 (质检与解码有 rust_core 加速路径) |
| 爬取历史.py / 站点历史.py / 书架.py | URL 维度历史(增量) / 站点先验 / 已抓书目 |
| captcha_module.py / waf_captcha.py / browser_driver.py | 验证码框架 (自动识别默认关) / WAF 流程 / Playwright 反检测驱动 |
| gui_app.py + gui_components/ | Flet 0.86 界面; TaskManager 单一数据源, 爬虫线程只写数据不碰控件 |
| rust_core_poc/ | PyO3 扩展源码 (质检/解码加速); 编译产物 源码/rust_core.pyd 不入库 |

## 编码规约 (本项目既有约定, 新代码必须遵守)

- **标识符/注释/日志用中文**,公开 API 与第三方接口用英文。
- **原子写**:凡写 JSON 状态文件必须 tmp + `os.replace`,配防抖 + flush/atexit 兜底
  (参照 爬取历史.py;禁止直接 `write_text`)。
- **裸 except 必须留痕**:`except Exception: pass` 禁止;至少 `_log.debug(f'裸 except 吞异常: {type(e).__name__}')`。
- **SSRF 防护**:一切用户可控 URL 发请求前过 `validate_public_url` (爬虫.py)。
- **站点逻辑**:新站点优先 JSON 规则或 站点适配/*.py 插件;禁止再往 爬虫.py 加域名 if 特判。
- **线程安全**:爬虫工作线程只写数据结构,绝不碰 Flet 控件;共享可变状态加锁或放 thread-local。
- **资源释放**:driver/session 提供 close()/幂等清理,支持 with 上下文。
- 路径处理用 `_path_utils.py` 的 RESOURCE_DIR/BASE_DIR 契约,禁止硬编码盘符。

## 修复工作流

1. 改代码 → 2. 为该修复补回归用例 (离线, 用 测试样本/ 快照) → 3. `unittest discover` 全绿
→ 4. `check_undefined_refs.py` 无新告警 → 5. 更新 CHANGELOG.md (对齐其条目格式)
→ 6. 提交信息格式 `fix(域): 一句话` 或 `feat(域): ...` (中文, 参照 git log)。

## 已知问题台账

系统审查报告在 文档/ (项目审查报告-*.md, 优化检查报告.md)。
已确认未修的高优先级问题以最近一次审查会话结论为准,修复前先 grep 复核现状,
防止重复修或基于过期信息改动。
