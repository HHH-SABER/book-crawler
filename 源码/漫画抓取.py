# -*- coding: utf-8 -*-
"""漫画抓取 (2026-11-09, P8 §H 横向 H1/H2 的第一个落地品类)。

与网文主链路**完全独立**: 独立模块、独立命令行、独立输出目录
（`抓取结果/漫画/<书名>/`），出问题可整体弃用，不影响小说抓取。

站点适配现状（2026-11-09 实测画质/完整性）:
  · manwang  漫网  47 章(全) / 22 页 / 900×1279 / 免登录 —— **首选**
    图列表由 `pic-v2.js` 客户端生成 ⇒ 每章需渲染取 `img[data-src]`
  · tuku     图库  63 章(含分段) / 19 页 / 640×910 / 免登录 —— 备选
    直连 HTTP，图片 URL 带签名参数(cid/key)，从章节 HTML 正则可取
  · 其余站(neosek/manhuatuan/hanabimanga) 见 文档/实施计划.md §H 评估结论

合规: 仅供个人阅读备份，限速 0.35s/张、串行、不重试轰炸；不二次分发。
"""
import json
import re
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urljoin

import requests

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
图后缀 = re.compile(r'\.(?:jpg|jpeg|png|webp)(?:$|\?)', re.I)


# ------------------------------------------------------------------ 数据结构
@dataclass
class 章节:
    序号: int
    标题: str
    url: str


@dataclass
class 站点:
    名: str
    详情正则: str            # 从详情页 HTML 抓章节链接
    图片正则: str            # 从章节 HTML 抓图片 URL（渲染站用选择器，可为空）
    需渲染: bool = False
    图选择器: str = 'img[data-src]'   # 渲染站的取图选择器
    referer: str = ''


# 站点表由 站点适配_本地/漫画站点.json 提供（不入库: 含真实域名与站点正则）。
# 公开模块只保留通用框架 —— 与网文适配器"站点信息只进私有目录"的规矩一致。
_站点表: dict = {}


def 站点配置路径() -> Path:
    return Path(__file__).resolve().parent.parent / '站点适配_本地' / '漫画站点.json'


def 加载站点表() -> dict:
    """读私有站点配置（首次调用缓存）。缺配置返回空表，调用方给明确提示。"""
    global _站点表
    if _站点表:
        return _站点表
    路径 = 站点配置路径()
    if not 路径.is_file():
        return {}
    try:
        原始 = json.loads(路径.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}    # 刻意静默: 配置坏了等同于未配置, 由调用方报"未识别站点"
    for 名, 项 in 原始.items():
        if not isinstance(项, dict):
            continue
        _站点表[名] = 站点(
            名=名,
            详情正则=str(项.get('详情正则') or ''),
            图片正则=str(项.get('图片正则') or ''),
            需渲染=bool(项.get('需渲染')),
            图选择器=str(项.get('图选择器') or 'img[data-src]'),
            referer=str(项.get('域名') or ''),
        )
    return _站点表


def 识别站点(url: str) -> Optional[str]:
    for 名, 站 in 加载站点表().items():
        if 站.referer and 站.referer in url:
            return 名
    return None


# ------------------------------------------------------------------ 章节列表
def 解析章节列表(html: str, 详情url: str, 站名: str) -> List[章节]:
    """从详情页 HTML 提取章节（按出现顺序，按 URL 去重）。"""
    站 = 加载站点表()[站名]
    结果, 已见 = [], set()
    for m in re.finditer(r'href="([^"]+)"[^>]*>(.*?)</a>', html, re.S | re.I):
        href, 文本 = m.group(1), re.sub(r'<[^>]+>', '', m.group(2)).strip()
        if not re.search(站.详情正则, href):
            continue
        完整 = urljoin(详情url, href)
        if 完整 in 已见:
            continue
        已见.add(完整)
        序号 = len(结果) + 1
        # 详情页的"开始阅读/继续阅读"是导航词, 不是章名 → 回落为 第N话
        if not 文本 or re.search(r'^(开始阅读|继续阅读|从头看|立即阅读|点击阅读)$', 文本):
            文本 = f'第{序号}话'
        结果.append(章节(序号, 文本[:40], 完整))
    return 结果


def 解析图片列表(html: str, 章url: str, 站名: str) -> List[str]:
    """从章节 HTML 提取图片 URL（纯 HTTP 站用；渲染站见 渲染取图）。"""
    站 = 加载站点表()[站名]
    if not 站.图片正则:
        return []
    urls = []
    for m in re.finditer(站.图片正则, html, re.I):
        候选 = urljoin(章url, m.group(1))
        if re.search(r'(logo|icon|avatar|banner|placeholder|loading|qrcode)', 候选, re.I):
            continue
        if 候选 not in urls:
            urls.append(候选)
    return urls


# ------------------------------------------------------------------ 渲染取图
def 渲染取图(章url: str, 站名: str, 驱动=None) -> Tuple[List[str], object]:
    """用浏览器渲染取图（懒加载站）。返回 (图片URL列表, 驱动对象)。

    驱动由调用方传入以复用（47 章只启一次浏览器）；为 None 时自建并返回。
    """
    自建 = 驱动 is None
    if 自建:
        from browser_driver import PlaywrightDriver
        驱动 = PlaywrightDriver(visible=False, timeout=45000)
    站 = 加载站点表()[站名]
    驱动.get(章url)
    _pg = 驱动._page
    _pg.wait_for_timeout(1800)
    for _ in range(4):                       # 触发懒加载
        _pg.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        _pg.wait_for_timeout(700)
    urls = _pg.evaluate(
        """(sel) => [...document.querySelectorAll(sel)]
              .map(e => e.getAttribute('data-src') || e.getAttribute('data-original')
                        || e.currentSrc || e.src)
              .filter(u => u && /^https?:/.test(u))""", 站.图选择器)
    去重 = [u for i, u in enumerate(urls) if u not in urls[:i]]
    return 去重, 驱动


# ------------------------------------------------------------------ 下载
def 图片文件名(序号: int, url: str, 总页: int = 0) -> str:
    """`001.jpg` 形态的补零文件名（保持页序）。"""
    宽 = max(3, len(str(总页 or 序号)))
    后缀 = '.jpg'
    m = re.search(r'\.(jpg|jpeg|png|webp)', url, re.I)
    if m:
        后缀 = '.' + ('jpg' if m.group(1).lower() in ('jpg', 'jpeg') else m.group(1).lower())
    return f'{序号:0{宽}d}{后缀}'


def 下载章节图片(urls: List[str], 目标目录: Path, 会话: requests.Session,
                 章url: str, 间隔: float = 0.35, 日志=None) -> Tuple[int, int]:
    """下载一章的图片。断点续传: 已存在且非空的跳过。返回 (成功数, 跳过数)。"""
    目标目录.mkdir(parents=True, exist_ok=True)
    成功 = 跳过 = 0
    for i, u in enumerate(urls, 1):
        目标 = 目标目录 / 图片文件名(i, u, len(urls))
        if 目标.is_file() and 目标.stat().st_size > 1024:
            跳过 += 1
            continue
        try:
            r = 会话.get(u, headers={'User-Agent': UA, 'Referer': 章url},
                        timeout=30)
            if r.status_code != 200 or len(r.content) < 1024:
                if 日志:
                    日志(f'  ! 第{i}页异常 HTTP {r.status_code} / {len(r.content)}B')
                continue
            目标.write_bytes(r.content)
            成功 += 1
        except (requests.RequestException, OSError) as e:
            if 日志:
                日志(f'  ! 第{i}页失败 {type(e).__name__}: {str(e)[:60]}')
        time.sleep(间隔)
    return 成功, 跳过


# ------------------------------------------------------------------ 整本
def 抓整本(详情url: str, 输出根: Path, 章范围: Optional[Tuple[int, int]] = None,
          间隔: float = 0.35, 日志=print) -> dict:
    """抓整本漫画。返回统计 dict。"""
    站名 = 识别站点(详情url)
    if not 站名:
         raise ValueError(
             f'未识别的站点: {详情url}\n'
             f'请在 {站点配置路径()} 里补该站配置（域名/详情正则/图片正则/需渲染）。')
    站 = 加载站点表()[站名]
    会话 = requests.Session()
    会话.headers.update({'User-Agent': UA})
    日志(f'[站点] {站名}；详情页 {详情url}')

    详情HTML = 会话.get(详情url, timeout=30).text
    章节s = 解析章节列表(详情HTML, 详情url, 站名)
    if not 章节s:
        raise RuntimeError('未解析到任何章节链接（站点结构可能变了）')
    日志(f'[章节] 共 {len(章节s)} 话')

    if 章范围:
        起, 止 = 章范围
        章节s = [c for c in 章节s if 起 <= c.序号 <= 止]
        日志(f'[范围] 只抓第 {起}-{止} 话 → {len(章节s)} 话')

    # 书名取自 <title> 首段
    m = re.search(r'<title[^>]*>(.*?)</title>', 详情HTML, re.S)
    书名 = re.split(r'[_\-—|]', (m.group(1) if m else '漫画').strip())[0].strip() or '漫画'
    书名 = re.sub(r'[\\/:*?"<>|]', '_', 书名)
    输出目录 = 输出根 / 书名
    输出目录.mkdir(parents=True, exist_ok=True)

    驱动 = None
    总成功 = 总跳过 = 总页 = 0
    try:
        for 章 in 章节s:
            if 站.需渲染:
                urls, 驱动 = 渲染取图(章.url, 站名, 驱动)
            else:
                html = 会话.get(章.url, timeout=30).text
                urls = 解析图片列表(html, 章.url, 站名)
            if not urls:
                日志(f'[警告] 第{章.序号}话未取到图片: {章.url}')
                continue
            目录 = 输出目录 / f'{章.序号:03d}_{章.标题[:20]}'
            成功, 跳过 = 下载章节图片(urls, 目录, 会话, 章.url, 间隔, 日志)
            总成功 += 成功
            总跳过 += 跳过
            总页 += len(urls)
            日志(f'[第{章.序号}/{len(章节s)}话] {len(urls)} 页 → 新下 {成功}, 跳过 {跳过}')
    finally:
        if 驱动 is not None:
            try:
                驱动.quit()
            except Exception:
                pass    # 刻意静默: 浏览器收尾失败不影响已下载结果

    return {'书名': 书名, '目录': str(输出目录), '章节数': len(章节s),
            '总页数': 总页, '新下载': 总成功, '跳过': 总跳过}


def 导出CBZ(输出目录: Path) -> List[Path]:
    """把每章目录打成 .cbz（图片原样打包，供阅读器使用）。"""
    结果 = []
    for 章目录 in sorted(p for p in 输出目录.iterdir() if p.is_dir()):
        图 = sorted(章目录.glob('*'))
        图 = [p for p in 图 if 图后缀.search(p.suffix) and p.stat().st_size > 1024]
        if not 图:
            continue
        cbz = 章目录.with_suffix('.cbz')
        with zipfile.ZipFile(cbz, 'w', zipfile.ZIP_STORED) as z:
            for p in 图:
                z.write(p, p.name)
        结果.append(cbz)
    return 结果


if __name__ == '__main__':
    import argparse

    ap = argparse.ArgumentParser(description='漫画抓取（个人阅读备份，限速串行）')
    ap.add_argument('详情页', help='漫画详情页 URL')
    ap.add_argument('--out', default=None, help='输出根目录（默认 抓取结果/漫画）')
    ap.add_argument('--章范围', default='', help='如 1-47；留空=全部')
    ap.add_argument('--间隔', type=float, default=0.35, help='每张图间隔秒（默认 0.35）')
    ap.add_argument('--cbz', action='store_true', help='完成后每章打包 .cbz')
    a = ap.parse_args()

    根 = Path(a.out) if a.out else (Path(__file__).resolve().parent.parent / '抓取结果' / '漫画')
    范围 = None
    if a.章范围:
        起, 止 = a.章范围.split('-')
        范围 = (int(起), int(止))
    统计 = 抓整本(a.详情页, 根, 章范围=范围, 间隔=a.间隔,
                 日志=lambda m: print(m, flush=True))
    print('\n完成:', 统计)
    if a.cbz:
        cbzs = 导出CBZ(Path(统计['目录']))
        print(f'CBZ: {len(cbzs)} 个')
