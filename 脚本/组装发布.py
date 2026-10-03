# -*- coding: utf-8 -*-
"""组装发布目录 (2026-10-03 八项需求#4; 2026-10-04 隐私整改)。

**两种产物, 默认只产"公开安全包"** —— 旧实现把"本机私有"与"可公开分发"混在同一目录,
目录名却叫"正式发布版", 极易误传 (2026-10-04 审查发现, 见 文档/审查报告汇总.md):

  发布/小说爬虫_v<版本>/        公开包 —— 可分发 / 可上传 Release, **不含任何真实站点**
  发布/小说爬虫_v<版本>_本机/   本机包 —— 含 站点适配_本地/ (真实适配器+域名映射+cookies),
                                 **严禁外传**, 需显式 `--含本地适配器` 才生成

公开包内容:
  ├─ 小说爬虫.exe        程序本体 (onefile 自包含)
  ├─ 站点适配/           公开适配器目录 (公开仓库形态: 仅 _模板.py 占位)
  ├─ 网站清单.txt        空模板 (绝不含本机爬取记录)
  └─ 使用说明.txt

本机包额外带:
  └─ 站点适配_本地/      真实适配器 + 站点表/映射/cookies  ← 严禁外传

一律排除 (程序首启自动重建; 带上即泄露隐私):
  抓取结果/  站点配置.json  captcha_config.json  *.checkpoint.json
  数据/ (含 远控配置.json token)   日志/

**组装后隐私自检**: 扫描产物, 命中任何一项即 [FAIL] 并返回非 0
(私有适配目录 / 映射与 cookies 文件 / checkpoint / 非空网站清单 / 用户数据目录)。
自检只按**文件名与目录名**判定, 不硬编码任何真实域名 —— 本脚本要入库,
不能把站点信息带进公开仓库。

用法 (项目根执行):
  .runtime\\python314\\python.exe 脚本\\组装发布.py                  # 公开包
  .runtime\\python314\\python.exe 脚本\\组装发布.py --zip            # 公开包 + zip (可上传)
  .runtime\\python314\\python.exe 脚本\\组装发布.py --含本地适配器    # 本机包 (严禁外传)
  .runtime\\python314\\python.exe 脚本\\组装发布.py --版本=2.5.0      # 覆盖版本号

版本号默认读 脚本/版本.json (build_exe.py 维护), 保证发布目录与打包版本一致。
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

# 产物中**禁止出现**的目录名/文件名 (首启自动重建; 带上即泄露隐私)
# 2026-10-04: 旧实现里这组数据是个**零引用的死变量**(看着像黑名单, 实际只有白名单复制生效),
# 现改为真正参与 _隐私自检 —— 白名单之外再加一道"产物扫描"兜底。
_禁入名 = (
    "抓取结果", "站点配置.json", "captcha_config.json", "远控配置.json",
    "域名映射.json", "域名cookies.json", "站点映射.json", "站点表.json",
    "日志", "数据",
)
_禁入后缀 = (".checkpoint.json",)
# 仅"公开包"额外禁止: 本机私有适配目录
_公开包禁入 = ("站点适配_本地",)


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


def _使用说明文本(ver: str, 含本地: bool) -> str:
    形态 = "本机全功能包" if 含本地 else "公开发布版"
    本地行 = ("- 站点适配_本地/   本机私有站点 (⚠ 含真实站点信息与 cookies, 严禁外传!)\n"
              if 含本地 else "")
    return f"""小说爬虫 v{ver} — {形态}
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
- 首次启动若弹出 Windows 防火墙询问, 需选"允许"手机才能连上 (否则仅本机可访问)。
- 外网访问为可选进阶 (Tailscale), 见程序内"使用教程"。

【目录说明】
- 小说爬虫.exe     程序本体
- 站点适配/        站点适配器 (必需, 勿删改)
{本地行}- 网站清单.txt     程序自动维护的爬取记录 (首次抓取后生成内容)
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


def _隐私自检(target: Path, 含本地: bool) -> list:
    """扫描已组装产物, 返回问题清单 (空 = 通过)。只按文件名/目录名判定。"""
    问题 = []
    清单 = target / "网站清单.txt"
    for f in target.rglob("*"):
        rel = f.relative_to(target)
        名字 = set(rel.parts)
        # 本机私有适配目录: 本机包里其中一切都是**预期内容**(映射/cookies/站点表),
        # 一律豁免; 公开包里该目录根本不该存在。
        if any(禁 in 名字 for 禁 in _公开包禁入):
            if not 含本地:
                问题.append(f"公开包不得含私有适配目录: {rel}")
            continue
        for 禁 in _禁入名:
            if 禁 in 名字:
                问题.append(f"命中禁止项 '{禁}': {rel}")
        if f.is_file() and f.name.endswith(_禁入后缀):
            问题.append(f"命中检查点文件: {rel}")
    if 清单.is_file():
        try:
            if 清单.read_text(encoding="utf-8") != _网站清单模板():
                问题.append("网站清单.txt 与空模板不一致 (可能带上了本机爬取记录)")
        except Exception as e:
            问题.append(f"网站清单.txt 读取失败: {type(e).__name__}")
    else:
        问题.append("缺少 网站清单.txt")
    if not (target / EXE_NAME).is_file():
        问题.append(f"缺少 {EXE_NAME}")
    return 问题


def _磁盘空间够(target: Path, 需要: int) -> bool:
    try:
        自由 = shutil.disk_usage(str(target.anchor or target)).free
    except Exception as e:
        print(f"[WARN] 磁盘空间检查跳过: {type(e).__name__}")
        return True
    if 自由 < 需要:
        print(f"[FAIL] 目标盘剩余 {自由 / 1048576:.0f} MB < 预计需要 {需要 / 1048576:.0f} MB")
        return False
    return True


def _EXE新旧提示(exe: Path) -> None:
    """EXE 早于 版本.json 的更新时间 → 提示可能把旧产物装进新版号目录"""
    try:
        版本文件 = ROOT / "脚本" / "版本.json"
        if 版本文件.is_file() and exe.stat().st_mtime + 1 < 版本文件.stat().st_mtime:
            print("[WARN] dist 里的 EXE 早于 脚本/版本.json 的更新时间 —— "
                  "疑似旧产物, 建议先重跑 脚本/build_exe.py 再组装")
    except Exception:
        pass  # 刻意静默: 仅提示性检查, 失败不该阻断组装


def main() -> int:
    ap = argparse.ArgumentParser(description="组装发布目录 (默认公开安全包)")
    ap.add_argument("--zip", action="store_true", help="组装后额外生成 zip 包")
    ap.add_argument("--版本", dest="版本", default="", help="覆盖版本号 (默认读 脚本/版本.json)")
    ap.add_argument("--含本地适配器", dest="含本地", action="store_true",
                    help="同时打入 站点适配_本地/ (真实站点+cookies, 严禁外传)")
    ap.add_argument("--我确认含私有站点", dest="我确认", action="store_true",
                    help="对本机包打 zip 时的二次确认 (防误打包外传)")
    args = ap.parse_args()

    ver = args.版本.strip() or _读版本()
    if not ver:
        print("[FAIL] 无法确定版本号 (脚本/版本.json 缺失且未传 --版本)")
        return 2

    含本地 = bool(args.含本地)
    exe = DIST / EXE_NAME
    if not exe.is_file():
        print(f"[FAIL] {exe} 不存在 — 先跑 脚本/build_exe.py 完成打包再组装")
        return 2

    名称 = f"小说爬虫_v{ver}" + ("_本机" if 含本地 else "")
    target = 发布根 / 名称
    发布根.mkdir(parents=True, exist_ok=True)

    if 含本地:
        print("[!] 本机包: 将包含 站点适配_本地/ (真实站点 + 域名映射 + cookies) —— 严禁外传")
    else:
        print("[i] 公开包: 不含任何真实站点 (私有适配目录默认排除; 需要时加 --含本地适配器)")

    # 同版本重建: 若已存在且确实是我们生成的布局 (含 EXE) 才清掉重来;
    # 不含 EXE 说明用户放了自己的东西, 中止保护
    try:
        if target.exists():
            if (target / EXE_NAME).is_file():
                shutil.rmtree(target)
                print(f"[CLEAN] 重建已存在的发布目录: {target}")
            else:
                print(f"[FAIL] {target} 已存在且不含 {EXE_NAME} — "
                      f"疑似非本脚本生成, 不动; 请手工处理后再跑")
                return 2
        if not _磁盘空间够(发布根, int(exe.stat().st_size * 1.2) + 32 * 1048576):
            return 2
        target.mkdir(parents=True)
        print(f"[OK] 组装 → {target}")

        # 1) 程序本体
        shutil.copy2(exe, target / EXE_NAME)
        print(f"[OK] 复制 {EXE_NAME} ({exe.stat().st_size / 1048576:.1f} MB)")
        _EXE新旧提示(exe)

        # 2) 站点适配/ (公开形态)
        adapters = DIST / "站点适配"
        if adapters.is_dir():
            n = _copytree_clean(adapters, target / "站点适配")
            print(f"[OK] 复制 站点适配/ ({n} 文件)")
        else:
            print("[WARN] dist 无 站点适配/ — 确认打包产物是否完整")

        # 3) 站点适配_本地/ — **仅本机包**, 需显式开关
        local = DIST / "站点适配_本地"
        if 含本地:
            if local.is_dir():
                n = _copytree_clean(local, target / "站点适配_本地")
                print(f"[OK] 复制 站点适配_本地/ ({n} 文件) — ⚠ 严禁外传")
            else:
                print("[WARN] 已要求 --含本地适配器, 但 dist 无 站点适配_本地/")
        else:
            print("[OK] 已排除 站点适配_本地/ (公开包)")

        # 4) 网站清单空模板 (绝不复制 dist 里用户的真实记录)
        (target / "网站清单.txt").write_text(_网站清单模板(), encoding="utf-8")
        print("[OK] 预置空 网站清单.txt (用户隐私不进发布包)")

        # 5) 使用说明
        (target / "使用说明.txt").write_text(_使用说明文本(ver, 含本地), encoding="utf-8")
        print("[OK] 生成 使用说明.txt")

        # 6) 隐私自检 (兜底: 白名单复制之外再扫一遍产物)
        问题 = _隐私自检(target, 含本地)
        if 问题:
            print("[FAIL] 隐私自检未通过 —— 产物可能泄露本机数据:")
            for p in 问题:
                print(f"       · {p}")
            return 3
        print(f"[OK] 隐私自检通过 ({'本机包' if 含本地 else '公开包'}): "
              f"无用户数据 / 无 checkpoint / 清单为空模板")
    except OSError as e:
        print(f"[FAIL] 组装失败 (文件系统): {type(e).__name__}: {e}")
        return 4

    total = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
    print(f"[DONE] 发布目录: {target}  (共 {total / 1048576:.1f} MB)")
    print("[提示] 抓取结果/站点配置.json 等用户数据已刻意排除, 程序首启自动重建")

    if args.zip:
        if 含本地 and not args.我确认:
            print("[FAIL] 拒绝为本机包打 zip: 它含真实站点信息与 cookies。"
                  "如确需打包(例如本机备份), 请显式加 --我确认含私有站点")
            return 5
        try:
            base = str(发布根 / 名称)
            arc = shutil.make_archive(base, "zip", root_dir=str(发布根), base_dir=名称)
            print(f"[DONE] zip 包: {arc}")
            if 含本地:
                print("[!] 该 zip 含私有站点信息 —— 严禁上传/分享")
        except OSError as e:
            print(f"[FAIL] 打 zip 失败: {type(e).__name__}: {e}")
            return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
