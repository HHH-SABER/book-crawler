---
name: nc-maintain
description: 小说爬虫项目的日常维护流程 — 跑测试、未定义引用检查、打包 EXE、发版同步 CHANGELOG。当用户要求"跑测试/回归/打包/构建 EXE/发版/检查引用"或修复代码后需要验证时使用。
---

# 小说爬虫维护流程

工作目录: 项目根。所有命令用项目虚拟环境 `.venv`(Windows)。

## 1. 测试

```bash
# unittest 发现式 (离线回归, 用 测试样本/ 真实快照, 不联网)
python -m unittest discover -s 测试 -v
```

- 必须全绿。任何失败先判断是新代码引入还是既有用例过期,不要静默跳过。
- 手写脚本不在 discover 范围,重大改动后单独跑:
  `python 测试/回归测试_修复验证.py`、`python 测试/_test_task_metrics.py`。
- GUI 相关测试 (`_test_gui_v3.py`) 会覆写根目录 站点配置.json (有备份/finally 恢复),
  不要在爬虫任务运行中执行它。

## 2. 静态检查

```bash
python 脚本\check_undefined_refs.py
```

改完 Python 代码必跑;输出未定义引用/疑似拼写问题。历史遗留告警知悉即可,不允许新增。

## 3. 打包 EXE

```bash
python 脚本\build_exe.py            # 或双击 脚本\打包EXE.bat
```

- 自动递增 `脚本/版本.json` 版本号 (--bump=patch/minor/major) 并在 CHANGELOG.md 顶部同步条目。
- 会预下载 flet client 缓存、收集 ddddocr onnx 模型;`源码/rust_core.pyd` 存在则打进
  bundle (Rust 加速), 缺失则静默回退纯 Python (非致命)。
- 产物在 `dist/`。CI (release.yml, tag `v*` 触发) 与本机共用此脚本。

## 4. 发版检查单

1. CHANGELOG.md 顶部条目与 `脚本/版本.json` 版本一致
2. `python -m unittest discover -s 测试` 全绿
3. 打包成功且 dist 下 EXE 可启动 (GUI 能开、CLI `--test` 模式可跑)
4. 打 git tag `v{版本}` 并推送 (历史上有 v2.3.1 漏打 tag 导致发布断档的教训)

## 5. 修复后收尾

按 AGENTS.md 的修复工作流: 补回归用例 → 测试全绿 → check_undefined_refs → CHANGELOG → 提交。
