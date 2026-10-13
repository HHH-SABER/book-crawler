# -*- coding: utf-8 -*-
"""红线扫描器 (2026-10-13): 公开仓库与发布产物的站点/书名泄露检查。

## 为什么要有这个脚本

本项目最高约束是**真实站点信息不得进公开仓库** (域名/站名/站点表/cookies/书名)。
此前只有人工 grep 把关 —— 今天一天里就抓到过 4 处残留 (验证页文案被引用、
APP 下载路径里的站点标识、meta 里的书名)。**手工检查必有一天手滑**, 而这类
泄露不可逆, 故固化为门禁。

## 扫描范围与能力边界 (诚实声明)

| 目标 | 方式 | 有效性 |
|---|---|---|
| 公开源码/测试/文档/脚本 | 文本逐行扫 | ✅ 完全可靠 |
| **zip 发布包** | **解包后逐文件扫** | ✅ 完全可靠 (zip 内是明文) |
| exe 发布包 | **不扫二进制** | ⚠️ PyInstaller 把源码编译成 pyc 并**压缩**进 PYZ, 字节级无明文 ⇒ 扫它是**假安全感** |
| exe 的安全保证 | 扫**构建输入** (公开适配器/清单/说明) + 组装脚本排除清单 | ✅ 真正可靠的那层 |

**结论**: exe 不扫字节, 改扫"它旁边的明文文件 + 构建输入" —— 这才是实际会泄露的路径。

## 红线悖论与两层词库

具体站点词/书名清单**本身含真实站名**, 入库就等于把名单写进公开仓库 ⇒ 分层:
  · **本地词库** `站点适配_本地/红线词库.txt` (gitignored, 一行一个词):
    本地开发与发版前全量扫, 最严;
  · **入库的通用规则** (本文件内): 文件级红线 + 域名形态模式, CI 上也能跑。

## 用法

```bash
# 本地全量扫 (含本地词库, 最严) —— 发版前必跑
.runtime\\python314\\python.exe 脚本\\红线扫描.py --全量

# 扫指定路径
.runtime\\python314\\python.exe 脚本\\红线扫描.py 发布/小说爬虫_v2.5.20.zip

# CI 模式 (无本地词库, 只跑入库的通用规则)
.runtime\\python314\\python.exe 脚本\\红线扫描.py --ci
```
"""
import argparse
import io
import os
import re
import sys
import zipfile
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass  # 刻意静默: 控制台编码重配置失败不该中断脚本 (Windows GBK 控制台常见)

_根 = Path(__file__).resolve().parent.parent

# ============ 入库的通用规则 (CI 可跑) ============

# ① 文件级红线: 这些文件/目录出现在公开侧 = 直接事故
_禁文件 = (
    '站点适配_本地', '域名映射.json', '域名cookies.json', '站点表.json',
    'captcha_config.json', '远控配置.json', '爬取历史.json', '任务历史.json',
    '测试样本_本地',
)
_禁目录片段 = ('站点适配_本地', '测试样本_本地')

# ② 文本内容红线 (通用模式, 不依赖具体站点名单)
# 占位/示例域名白名单 (测试与文档允许使用, 不算真实站点)
# 公共基础设施域名 (构建/下载镜像, **不是**小说站点 ⇒ 允许出现)
_基建白名单 = ('99988866.xyz',   # flet 客户端缓存镜像 (构建用, 非站点)
             'ghproxy.com', 'githubusercontent.com', 'github.com',
             'pypi.org', 'python.org', 'pytorch.org', 'npmjs.com',
             'github.io', 'rust-lang.org', 'crates.io', 'docs.rs',
             'tsinghua.edu.cn', 'aliyun.com', 'tencent.com',
             'storage.googleapis.com',   # chromedriver 官方下载 CDN (驱动用)
             'registry.npmmirror.com',    # npmmirror 公共镜像 (驱动下载兜底)
             'googlechromelabs.github.io',  # Chrome for Testing 官方 API (GitHub Pages)
             'alidns.com', 'dnspod.com', 'cloudflare.com', 'cloudflareinsights.com',
             'dns.google', '114dns.com')

# 工具链/依赖缓存目录: **不是项目内容**, 扫它们只会产出噪音
# (rust_core_poc/.toolchain 下 1.8 万个 rust-lang 文档文件曾让门禁完全失效)
_排除目录 = ('.toolchain', 'node_modules', '__pycache__', '.git', 'build',
            '.venv', 'venv', 'target', '_MEI')

_占位域 = frozenset((
    'example.com', 'example.org', 'example.net', 'a.com', 'b.com', 'c.com',
    'test.com', 'foo.com', 'bar.com', 'baz.com', 'qux.com', 'xxx.com',
    'xx.com', 'yy.com', 'zz.com',
    'your-domain.com', 'mysite.com', 'domain.com', 'site.com', 'localhost',
))

_文本红线 = (
    # 真实域名: **只抓三级以上** (子域.主域.TLD) —— 2026-10-13 实测教训:
    # 抓两级时测试占位 (a.com/b.com) 造成 2.8 万处误报, 门禁直接失效。
    # 真实站点几乎都带子域 (book./m./www./img.); 两级裸域 (如 <主域>.cc 这类)
    # 交给**本地词库**把关 —— 那才是可靠的防线, 通用模式只做兜底。
    (re.compile(r'(?<![\w-])([a-z0-9-]+\.[a-z0-9-]+\.(?:com|net|org|cc|hk|tw|cn'
                r'|la|me|top|xyz|info|io|co|biz|site|club|online|pro|vip))'
                r'(?=[/"\'<\s]|$)', re.I),
     '真实域名(三级+)'),
    # 《书名》形态 (站点 meta 常用): 只认**中文**书名, 占位词排除
    (re.compile(r'《[\u4e00-\u9fa5]{2,40}》'), '书名括号'),
)

_二进制跳过 = ('.exe', '.pyd', '.pyc', '.zip', '.7z', '.rar', '.png', '.jpg',
               '.jpeg', '.gif', '.ico', '.woff', '.woff2', '.ttf', '.mp3', '.wav')

_本地词库路径 = _根 / '站点适配_本地' / '红线词库.txt'


def _读本地词库() -> list:
    if not _本地词库路径.is_file():
        return []
    出 = []
    for ln in io.open(_本地词库路径, encoding='utf-8', errors='replace'):
        w = ln.strip()
        if w and not w.startswith('#'):
            出.append(w)
    return 出


def _扫文本(文本: str, 本地词: list, 来源: str) -> list:
    命中 = []
    for rx, 名 in _文本红线:
        for m in rx.findall(文本):
            值 = m if isinstance(m, str) else m[0]
            # 占位域名/示例域排除 (脱敏样本与文档示例是允许的)
            if any(值.lower().endswith(d) for d in _基建白名单):
                continue
            if (值.lower() in _占位域
                    or 值.lower().endswith(tuple('.' + d for d in _占位域))
                    or value_is_placeholder(值)):
                continue
            命中.append((来源, 名, 值[:40]))
    for w in 本地词:
        if w and w in 文本:
            命中.append((来源, f'本地词库[{w[:12]}]', w[:40]))
    return 命中


def value_is_placeholder(值: str) -> bool:
    """占位域名识别 (2026-10-13: 按 RFC 2606 保留域 + 常见占位词, 不枚举 TLD)。

    踩坑记录: 首版只认 `siteN.example.com|org|net`, 结果脱敏样本用的
    `sitec.example.cc` 与测试的 `www.unknown-zzz.com` 造成 1.9 万处误报
    ⇒ 门禁又失效。改为**特征匹配**: RFC 保留域 (example./invalid./test.)
    + 常见占位词 (unknown/sample/placeholder/mock/dummy/your-)。
    """
    v = 值.lower()
    if re.search(r'\b(example|invalid|test|sample|placeholder|mock|dummy)\b'
                 r'\.', v):
        return True
    if re.search(r'\b(unknown|your-|my-|foo|bar|baz|书名|作者|示例|evil)', v):
        return True
    return bool(re.match(r'^site\d*\.example\.', v))


def _相对(路径: Path, 根: Path) -> str:
    """安全 relative_to: 路径在根外时退回原样 (测试会传临时目录)。"""
    try:
        return str(路径.relative_to(根))
    except ValueError:
        return str(路径)


def _扫文件(路径: Path, 本地词: list, 根: Path) -> list:
    命 = []
    名 = 路径.name
    # ① 文件级红线 (含"文件名形态": 质检报告只在**文件名**层面查,
    #    内容里出现该字符串是脚本自身文档/模式的正常情况, 不算泄露)
    for 禁 in _禁文件:
        if 禁 in 名:
            命.append((_相对(路径, 根), '禁文件', 禁))
    if 名.endswith('.txt.质检报告.txt'):
        命.append((_相对(路径, 根), '质检报告文件', 名[:40]))
    if 命:
        return 命
    # ② zip: 解包扫 (zip 内是明文, 完全可靠)
    if 路径.suffix.lower() == '.zip':
        try:
            z = zipfile.ZipFile(路径)
            for n in z.namelist():
                if n.endswith('/'):
                    continue
                for 禁 in _禁目录片段:
                    if 禁 in n:
                        命.append((f'{路径.name}!/{n}', '禁文件(包内)', 禁))
                if n.lower().endswith(_二进制跳过):
                    continue
                try:
                    t = z.read(n).decode('utf-8', errors='replace')
                except Exception:
                    continue
                命 += _扫文本(t, 本地词, f'{路径.name}!/{n}')
        except Exception as e:
            命.append((str(路径), 'zip 无法解包', str(e)[:40]))
        return 命
    # ③ exe: 不扫二进制 (压缩后无明文, 扫它是假安全感) —— 只记录
    if 路径.suffix.lower() == '.exe':
        return []
    # ④ 文本文件
    if 路径.suffix.lower() in _二进制跳过:
        return 命
    try:
        文本 = 路径.read_bytes().decode('utf-8', errors='replace')
    except Exception:
        return 命
    return 命 + _扫文本(文本, 本地词, _相对(路径, 根))


def 扫描(目标: list, 本地词: list) -> tuple:
    """返回 (命中列表, 扫描文件数)"""
    命, 数 = [], 0
    for t in 目标:
        p = Path(t)
        if not p.is_absolute():
            p = _根 / p
        if p.is_file():
            命 += _扫文件(p, 本地词, _根)
            数 += 1
        elif p.is_dir():
            for f in sorted(p.rglob('*')):
                if not f.is_file():
                    continue
                if any(x in f.parts for x in _排除目录):
                    continue
                命 += _扫文件(f, 本地词, _根)
                数 += 1
    return 命, 数


# CI/默认扫描范围: 公开侧全部
_公开范围 = ['源码', '测试', '脚本', '文档', 'CHANGELOG.md', 'README.md',
             '.github', 'rust_core_poc', 'requirements.txt', 'requirements-lock.txt']


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='红线扫描: 站点/书名泄露检查')
    ap.add_argument('目标', nargs='*', help='要扫的文件/目录 (缺省扫公开侧)')
    ap.add_argument('--全量', action='store_true',
                    help='本地模式: 公开侧 + 发布产物, 且加载本地词库 (最严)')
    ap.add_argument('--ci', action='store_true',
                    help='CI 模式: 只跑入库的通用规则, 无本地词库')
    args = ap.parse_args(argv)

    本地词 = [] if args.ci else _读本地词库()
    目标 = args.目标 or list(_公开范围)
    if args.全量:
        # 只扫 **发布/** (公开包 + zip, zip 会解包扫明文文件)。
        # **刻意不扫 dist/** —— 那是本机私有产物 (含真实站点适配器与用户
        # 数据), 靠 .gitignore 保证不进仓库; 扫它只会把 866 处用户数据当
        # "命中", 而那不是门禁能管的事 (门禁管的是"会不会进公开仓库")。
        目标 += ['发布']

    命, 数 = 扫描(目标, 本地词)
    词库状态 = (f'本地词库 {len(本地词)} 词' if 本地词 else '无本地词库(仅通用规则)')
    print(f'[红线扫描] 范围 {len(目标)} 项 / 文件 {数} 个 / {词库状态}')
    if 命:
        print(f'\n[FAIL] 命中 {len(命)} 处:')
        for 来源, 名, 值 in 命[:40]:
            print(f'  ⚠ {来源[:52]:54} {名:14} {值}')
        if len(命) > 40:
            print(f'  … 另有 {len(命) - 40} 处')
        print('\n处置: ①真实站点信息 → 改代号/占位; ②确属误报 → 把词加入 '
              '脚本的排除表并注明理由')
        return 1
    print('[PASS] 未发现站点/书名/用户数据残留')
    return 0


if __name__ == '__main__':
    sys.exit(main())
