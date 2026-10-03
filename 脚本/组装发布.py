# -*- coding: utf-8 -*-
"""组装"正式发布版"目录 (2026-10-03 八项需求#4)。

目的: 从 dist/ 打包产物提炼一个干净、可独立拷贝运行的发布文件夹,
仅含程序本体 + 运行所需文件, 不含任何本机用户数据 (隐私隔离):

  发布/小说爬虫_v<版本>/
    ├─ 小说爬虫.exe          程序本体 (onefile 自包含)
    ├─ 站点适配/             公开站点适配器 (EXE 旁必需目录)
    ├─ 站点适配_本地/        本机私有适配 (存在才带; ⚠含真实站点, 严禁外传)
    ├─ 网站清单.txt          空模板 (永远不含本机爬取记录)
    └─ 使用说明.txt          生成的快速上手说明

刻意排除 (程序首启自动重建, 带上反而泄露隐私):
  抓取结果/  站点配置.json  captcha_config.json  *.checkpoint.json

用法 (项目根执行):
  .runtime\\python314\\python.exe 脚本\\组装发布.py              # 组装目录
  .runtime\\python314\\python.exe 脚本\\组装发布.py --zip        # 组装并打 zip
  .runtime\\python314\\python.exe 脚本\\组装发布.py --版本=2.5.0  # 覆盖版本号

版本号默认读 脚本/版本.json (build_exe.py 维护), 保证发布目录与打包版本一致。
后续版本更新后重跑本脚本即与发布目录同步 (同版本号会整体重建该目录)。
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass  # 刻意静默: stdout 重定向时 reconfigure 必失败, 只丢 UTF-8 优化

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
发布根 = ROOT / "发布"
EXE_NAME = "小说爬虫.exe"

# dist 里的用户运行时数据: 一律不进发布目录 (首启自动重建)
_用户数据 = ("抓取结果", "站点配置.json", "captcha_config.json")


def _读版本() -> str:
    try:
        with open(ROOT / "脚本" / "版本.json", encoding="utf-8") as f:
            return str(json.load(f).get("版本", "")).strip()
    except Exception:
        return ""


def _网站清单模板() -> str:
    """空模板 (与 build_exe.py 写网站清单模板 同源兜底文案, 防格式漂移)"""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "网站清单", str(ROOT / "源码" / "网站清单.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        t = getattr(mod, "模板文本", "")
        if callable(t):
            t = t()   # 源码里是函数 (网站清单.py:120)
        if t:
            return str(t)
    except Exception:
        pass  # 源码缺失/导入失败 → 用内置兜底表头
    return ("# 网站清单 — 程序自动维护, 请勿手改格式 (抓取/尝试抓取后自动追加)\n"
            "# 网址\t网站名\t小说名\n")


def _使用说明文本(ver: str) -> str:
    return f"""小说爬虫 v{ver} — 正式发布版
====================================

【快速上手】
1. 保持本文件夹结构完整 (小说爬虫.exe 与 站点适配/ 必须在同一目录)。
2. 双击 小说爬虫.exe 启动。首次启动会询问是否创建桌面快捷方式。
3. 在"抓取工作台"粘贴小说目录页网址 → 选模式 → 开始。

【数据存放】
- 抓取结果、书架、日志等用户数据存于:
  %LOCALAPPDATA%\\小说爬虫\\
  换电脑/换目录运行不影响已有数据; 本文件夹内不含你的任何隐私数据。

【远控 (手机访问)】
- 程序启动后内嵌远控服务; 手机与电脑连同一 Wi-Fi,
  用"远控"页显示的 本机地址 + token 在手机浏览器打开即可。
- 外网访问为可选进阶 (Tailscale), 见程序内"使用教程"。

【目录说明】
- 小说爬虫.exe     程序本体
- 站点适配/        站点适配器 (必需, 勿删改)
- 站点适配_本地/   本机私有站点 (若存在; ⚠ 含真实站点信息, 严禁外传!)
- 网站清单.txt     程序自动维护的爬取记录 (首次抓取后生成内容)
- 使用说明.txt     本文件

【版本更新】
- 新版本发布后, 用新版发布文件夹整体替换旧文件夹即可;
  用户数据在 %LOCALAPPDATA%, 替换程序不影响已抓内容与续传。
"""


def _copytree_clean(src: Path, dst: Path) -> int:
    """复制目录并剔除 __pycache__/.pyc, 返回复制文件数"""
    n = 0
    for cur, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        rel = Path(cur).relative_to(src)
        (dst / rel).mkdir(parents=True, exist_ok=True)
        for f in files:
            if f.endswith((".pyc", ".pyo")):
                continue
            shutil.copy2(Path(cur) / f, dst / rel / f)
            n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description="组装正式发布版目录")
    ap.add_argument("--zip", action="store_true", help="组装后额外生成 zip 包")
    ap.add_argument("--版本", dest="版本", default="", help="覆盖版本号 (默认读 脚本/版本.json)")
    args = ap.parse_args()

    ver = args.版本.strip() or _读版本()
    if not ver:
        print("[FAIL] 无法确定版本号 (脚本/版本.json 缺失且未传 --版本)")
        return 2

    exe = DIST / EXE_NAME
    if not exe.is_file():
        print(f"[FAIL] {exe} 不存在 — 先跑 脚本/build_exe.py 完成打包再组装")
        return 2

    target = 发布根 / f"小说爬虫_v{ver}"
    发布根.mkdir(parents=True, exist_ok=True)

    # 同版本重建: 若已存在且确实是我们生成的布局 (含 EXE) 才清掉重来;
    # 不含 EXE 说明用户放了自己的东西, 中止保护
    if target.exists():
        if (target / EXE_NAME).is_file():
            shutil.rmtree(target)
            print(f"[CLEAN] 重建已存在的发布目录: {target}")
        else:
            print(f"[FAIL] {target} 已存在且不含 {EXE_NAME} — "
                  f"疑似非本脚本生成, 不动; 请手工处理后再跑")
            return 2

    target.mkdir(parents=True)
    print(f"[OK] 组装 → {target}")

    # 1) 程序本体
    shutil.copy2(exe, target / EXE_NAME)
    print(f"[OK] 复制 {EXE_NAME} ({exe.stat().st_size / 1048576:.1f} MB)")

    # 2) 站点适配/ (公开)
    adapters = DIST / "站点适配"
    if adapters.is_dir():
        n = _copytree_clean(adapters, target / "站点适配")
        print(f"[OK] 复制 站点适配/ ({n} 文件)")
    else:
        print("[WARN] dist 无 站点适配/ — 确认打包产物是否完整")

    # 3) 站点适配_本地/ (本机私有, 存在才带)
    local = DIST / "站点适配_本地"
    if local.is_dir():
        n = _copytree_clean(local, target / "站点适配_本地")
        print(f"[OK] 复制 站点适配_本地/ ({n} 文件) — ⚠ 含真实站点, 此文件夹严禁外传")

    # 4) 网站清单空模板 (绝不复制 dist 里用户的真实记录)
    (target / "网站清单.txt").write_text(_网站清单模板(), encoding="utf-8")
    print("[OK] 预置空 网站清单.txt (用户隐私不进发布包)")

    # 5) 使用说明
    (target / "使用说明.txt").write_text(_使用说明文本(ver), encoding="utf-8")
    print("[OK] 生成 使用说明.txt")

    # 汇总
    total = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
    print(f"[DONE] 发布目录: {target}  (共 {total / 1048576:.1f} MB)")
    print("[提示] 抓取结果/站点配置.json 等用户数据已刻意排除, 程序首启自动重建")

    if args.zip:
        base = str(发布根 / f"小说爬虫_v{ver}")
        arc = shutil.make_archive(base, "zip", root_dir=str(发布根),
                                  base_dir=f"小说爬虫_v{ver}")
        print(f"[DONE] zip 包: {arc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
