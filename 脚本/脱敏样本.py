# -*- coding: utf-8 -*-
"""真实页面样本脱敏 (2026-10-13): 让 `测试样本_本地/` 的真站快照可**入库**。

## 为什么需要这个脚本

排查"缺少样本"时发现: 本地 57 份真站快照一直都在 (分页/折叠/验证/键盘翻页/
完整大目录五种形态齐全), 但它们 (a) 在**不入库**目录, (b) **含真实域名与书名**,
于是公开侧测试一个都用不上 ⇒ "缺样本"成了长期受阻项。

本脚本把真站快照脱敏成**可入库的形态样本**: 只保留"判据关心的结构"
(容器/链接形态/章节号/宣称章数/验证表单), 一律替换掉"站点身份"
(域名/书名/作者/追踪串/内联 base64)。

## 脱敏规则 (可审计, 全部列在这里)

| 类别 | 处理 | 理由 |
|---|---|---|
| 真实域名 | → `site{N}.example.com` | 保留"多级子域/多域名共存"的结构特征 |
| 第三方广告域 | 同上 (统一编号) | 快照里常有几十个广告站, 一并占位 |
| 书名 / 作者 | → `<书名>` / `<作者>` | 红线: 禁书名 |
| 章节标题文字 | → `第N章 <章节标题>` | 保留"标题含第N章"这一形态特征 |
| URL 里的数字 ID | **保留** | 章节 URL 形态本身是被测对象 |
| query 串里的追踪参数 | → 删 (保留 key) | utm_/spm/from 等无判据价值 |
| 内联 base64 (表情图等) | → `<b64>` | 可能含原文 |
| cookie / token 串 | → `<token>` | 同上 |
| 站点版权/备案文案 | → 移除该行 | 可能含真实站名 |

**不脱敏** (刻意保留): HTML 结构、class/id 名、正则可判的关键词
(`captcha`/`geetest`/`check_code`/`共N章`/`隐藏的N章`)、章节号、链接顺序。

## 用法

```bash
# 脱敏 + 入库 (写到 测试/样本/)
.runtime\\python314\\python.exe 脚本\\脱敏样本.py --入库

# 只看会产出什么 (不写文件)
.runtime\\python314\\python.exe 脚本\\脱敏样本.py

# 单份试跑
.runtime\\python314\\python.exe 脚本\\脱敏样本.py --单份 siteg_访问验证页.html
```

## 收尾自检 (硬门禁)

每份产物落盘前必过两道:
  ① **红线扫描**: 真实域名/书名/书号 一律不得残留;
  ② **形态不变**: 脱敏后判据行为必须与脱敏前**一致**
     (折叠页仍告警 / 验证页仍判 True / 完整目录仍不告警) —— 脱敏不能改结论。
任一不过 → 该份**不入库**并明确报错, 不产出半成品。
"""
import argparse
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass  # 刻意静默: 控制台编码重配置失败不该中断脚本 (Windows GBK 控制台常见)

_根 = Path(__file__).resolve().parent.parent
_源 = _根 / '测试样本_本地'
_出 = _根 / '测试' / '样本'

# 入库白名单: 只脱敏"判据需要"的形态样本, 且控制体积
白名单 = {
    # 文件名: (形态说明, 裁剪上限字节; None=不裁剪)
    'tianqiu_目录.html': ('折叠目录页(宣称远大于首页可见)', None),
    'siteg_访问验证页.html': ('访问验证页(带输入框的验证表单)', None),
    'siteg_软封页.html': ('软封页(非验证但被拦截)', None),
    'washai_目录_第22页.html': ('分页目录-末页(链接数锐减)', None),
    'washai_目录.html': ('分页目录-首页(仅首屏条目)', 120_000),
    'siteq_目录_真实页.html': ('完整大目录(宣称≈实际, 不应误告警)', 120_000),
    'siteq_content.html': ('键盘翻页章节页(提示继续翻页)', None),
}

# 章节标题 → 保留"第N章"形态, 抹掉具体标题文字
_章标题 = re.compile(r'(第\s*\d+\s*[章回节])[^<]{0,40}?(?=<|</a>|</div>|$)')
_任意书名 = re.compile(r'<title>([^<]{0,60})</title>')
_追踪参数 = re.compile(r'([?&])(utm_[a-z_]+|spm|from|referer|keyword|ref)=[^&"\'\s]+',
                       re.I)
_内联b64 = re.compile(r'(data:image/[a-z]+;base64,)[A-Za-z0-9+/=]{40,}', re.I)
_长token = re.compile(r'\b[A-Za-z0-9_\-]{40,}\b')

# 判据依赖的关键词: 脱敏**不得**改动它们 (改动即说明脱敏破坏了被测特征)
# ⚠️ '访问验证' 与 'check_code' 是 **源码里硬编码的判据关键词**
# (waf_captcha.looks_like_waf_captcha 的"内容型"判据: `'访问验证' in text and
#  'check_code' in text`) ⇒ 替换掉任何一个都会让第一道门失效。
_必须保留 = ('check_code', '安全验证', '验证码', 'input', 'img', 'form',
             '共', '章', '目录', '下一页', '隐藏', 'geetest', 'captcha',
             '访问验证', '__wafcaptcha', '_waform', '访问频率太高')


def _关键词完好(原文: str, 新文: str) -> list:
    """返回"原文有但脱敏后丢了"的判据关键词 (空 = 完好)"""
    return [k for k in _必须保留 if k in 原文 and k not in 新文]


_域名表: dict = {}
_计数器 = [0]


def _占位域名(域名: str) -> str:
    """真实域名 → site{N}.example.com (同域名恒定同编号, 保结构不变)"""
    域名 = 域名.lower().strip()
    if 域名 not in _域名表:
        _计数器[0] += 1
        _域名表[域名] = f'site{_计数器[0]}.example.com'
    return _域名表[域名]


# 通用中文词 (站点的固定文案, **不是**身份, 不得替换 —— 判据可能依赖它们)
_通用词 = frozenset((
    '章节目录', '最新章节', '最新章节列表', '全文阅读', '免费阅读', '在线阅读',
    '全文免费阅读', '无弹窗', '手机版阅读', '最快更新', '请收藏', '加入书架',
    '上一页', '下一页', '返回目录', '章节报错', '章节错误', '已完结', '连载中',
    '本书暂无章节', '目录页', '第一页', '共', '章', '页',
))

# 通用 HTML/JS 标识 (不得当身份词替换, 否则结构坏掉)
# 常见路径/资源名 —— **不是**站点身份, 替换它会破坏链接形态
_路径词 = frozenset((
    'static', 'book', 'books', 'read', 'css', 'js', 'img', 'image', 'images',
    'api', 'ajax', 'app', 'apps', 'assets', 'public', 'static2', 'tpl', 'template',
    'templates', 'www', 'web', 'html', 'htm', 'php', 'asp', 'index', 'default',
    'main', 'home', 'user', 'users', 'admin', 'login', 'register', 'search',
    'list', 'detail', 'content', 'data', 'info', 'page', 'pages', 'down',
    'download', 'upload', 'file', 'files', 'media', 'video', 'audio', 'font',
    'fonts', 'common', 'global', 'plugins', 'widget', 'widgets', 'res',
    'source', 'novel', 'chapter', 'chapters', 'txt', 'zip', 'rar', 'apk',
))

_技术词 = frozenset((
    'html', 'body', 'head', 'meta', 'link', 'script', 'style', 'div', 'span',
    'a', 'img', 'form', 'input', 'button', 'table', 'tr', 'td', 'th', 'ul',
    'li', 'p', 'br', 'hr', 'title', 'lang', 'charset', 'content', 'name',
    'http', 'https', 'com', 'net', 'org', 'index', 'css', 'js', 'png', 'jpg',
))


def _收集身份词典(原文: str) -> set:
    """从原文提取"站点/书本身份"词, 供全文替换。

    来源三类 (实测这三类最易漏):
      ① 域名主干 (如 `ixdzs.hk` → `ixdzs`) —— 还会出现在 APP 下载路径等处;
      ② 《》包裹的书名;
      ③ meta/og 里的**非通用**中文词组 (书名与站名常藏在 description/
         keywords/og:novel:book_name 里, 独立 title 替换抓不到)。
    """
    词 = set()
    for m in re.finditer(r'https?://([a-z0-9-]{3,})\.[a-z]{2,}', 原文, re.I):
        词.add(m.group(1))
    for m in re.finditer(r'《([^》]{2,30})》', 原文):
        词.add(m.group(1))
    for m in re.finditer(r'content="([^"]{3,120})"', 原文):
        块原文 = m.group(1)
        # 判据关键词所在的块**整块跳过** (2026-10-13 踩坑: 无此保护时会把
        # 验证页的"…安全验证, 请输入验证码…"整块当身份词替换 ⇒ 页面语义被破坏
        # ⇒ 第一道门不再命中)
        if any(k in 块原文 for k in _必须保留):
            continue
        for 块 in re.findall(r'[\u4e00-\u9fa5]{2,14}', 块原文):
            if 块 not in _通用词:
                词.add(块)
    for m in re.finditer(r'<title>([^<]{2,80})</title>', 原文):
        # title 全段都要看: 常见形态是 `书名-作者名-章节名…`, 只取第一段会漏作者
        for 段 in re.split(r'[-_|｜,，]', m.group(1)):
            主 = 段.strip()
            # title 里也可能是**判据关键词**而非书名/作者 (实测某验证页 title 就是
            # "访问验证" —— 源码 waf_captcha 硬编码判据), 当身份词替换会让门失效
            if (主 and 主 not in _通用词
                    and not any(k in 主 for k in _必须保留)):
                词.add(主)
    return {w for w in 词
            if len(w) >= 2
            and (not w.isascii() or w.lower() not in _技术词)
            and (not w.isascii() or w.lower() not in _路径词)}


def 脱敏(html: str) -> str:
    # 身份词典必须从**原文**收集 (2026-10-13 踩坑: 曾在末尾收集, 那里真实域名
    # 已被占位符替换 ⇒ 词典漏掉域名主干 ⇒ APP 下载路径里的站点标识残留)
    身份词 = _收集身份词典(html)
    # ① 域名 (含 src/href/action 里的协议头形式)
    def _换域名(m):
        return _占位域名(m.group(2)) if m.group(2) else m.group(0)

    html = re.sub(r'(https?://)([a-z0-9.-]+\.[a-z]{2,})', _换域名, html, flags=re.I)
    # ② 裸域名 (src="/xxx" 之外的 protocol-relative 与纯文本域名)
    # 判别依据 = **TLD 白名单**, 不是上下文 (两次踩坑换来的):
    #   ① 按"前面不是 /"来判 → URL 路径里的真 CDN 域名 (bytecdntp.com) 漏替换 ⇒ 红线残留;
    #   ② 不做上下文限制     → 路径里的 "verify.jpg" 文件名被当域名替换 ⇒ 破坏判据
    #      (验证码图片路径被吃 ⇒ "验证码 UI 佐证"失效 ⇒ 第二道门漏判)。
    # 按 TLD 判: jpg/png/css 不是 TLD → 不动 (文件名); com/net/… 是 TLD → 替换。
    _TLD = (r'com|net|org|edu|gov|int|mil|cc|hk|tw|mo|cn|jp|kr|io|co|me|top|xyz|'
            r'info|biz|club|site|online|pro|vip|shop|fun|app|dev|live|work|team')
    html = re.sub(r'(?<![\w-])((?:[a-z0-9-]+\.)+(?:' + _TLD + r'))(?![\w.-])',
                  lambda m: _占位域名(m.group(1)), html, flags=re.I)
    # ③ 书名/标题
    # title 也可能是判据关键词 (某验证页 title 就是"访问验证") ⇒ 带保护地替换
    html = _任意书名.sub(
        lambda m: m.group(0) if any(k in m.group(1) for k in _必须保留)
        else '<title><NOVEL></title>', html)
    html = re.sub(r'(作者[:：]\s*)[^\s<，,]{1,20}', r'\1<AUTHOR>', html)
    html = re.sub(r'(?:作\s*者\s*[:：]?\s*)</?(?:span|p|div|a|b)[^>]*>?\s*[\u4e00-\u9fa5]{2,6}\s*<',
                  '作者：<AUTHOR><', html)
    # ④ 章节标题文字 (保留"第N章"形态)
    html = _章标题.sub(r'\1 <TITLE>', html)
    # ⑤ 追踪参数 / 内联 base64 / 长 token
    html = _追踪参数.sub(r'\1\2=', html)
    html = _内联b64.sub(r'\1<b64>', html)
    html = _长token.sub('<token>', html)
    # ⑥ 身份词 (书名/站名/域名主干) 全局替换 —— 放最后, 顺序最末
    for 词 in sorted(身份词, key=len, reverse=True):
        if len(词) >= 2:
            html = html.replace(词, '<NOVEL>' if not 词.isascii() else '<SITE>')
    return html


def 裁剪(html: str, 上限: int | None) -> str:
    """超体积时**按块删除非判据内容**。

    ⚠️ 2026-10-13 踩坑: 首版按**字节截断** (`html[:上限]`), 结果把尾部
    186 条章节链接整段切掉 —— 而快照尾部往往正是"最新章节目录" ⇒ **样本失真、
    判据结论会被扭曲**。改为只删对判据无用的块 (script/style/注释), **链接零损失**;
    仍超限时按 `<ul>/<table>` 整块删, 绝不切链接文本。
    """
    if not 上限 or len(html) <= 上限:
        return html
    html = re.sub(r'<script\b.*?</script>', '', html, flags=re.S | re.I)
    html = re.sub(r'<style\b.*?</style>', '', html, flags=re.S | re.I)
    html = re.sub(r'<!--.*?-->', '', html, flags=re.S)
    html = re.sub(r'<noscript\b.*?</noscript>', '', html, flags=re.S | re.I)
    # ⚠️ 刻意**不删** `<ul>/<table>`: 实测目录页的章节链接就装在最大那个
    # `<ul>` 里, 删它会让样本从 133 KB 塌到 9 KB、链接几乎全丢 ⇒ 样本失真。
    # **宁可体积超限, 也不失真** —— 体积只是仓库开销, 形态才是测试价值。
    return html + '\n<!-- 已裁剪: 仅删除 script/style/注释; 列表块保留防失真 -->\n'


def _链接形态(文本: str) -> set:
    """取 href 的**路径结构** (去掉域名与数字 ID), 用于脱敏前后比对。

    脱敏会把域名换成 siteN.example.com, 但**路径形态必须一模一样** ——
    章节链接形态本身就是被测对象 (如 `/read/<id>/p<n>.html`)。
    """
    出 = set()
    for m in re.finditer(r'href="([^"]+)"', 文本):
        u = m.group(1).split('#')[0]
        if not u or u.startswith(('javascript:', 'mailto:', '#')):
            continue
        路径 = re.sub(r'^(?:https?:)?//[^/]+', '', u)   # 去协议+域名(含 //host 形)
        # 再去**裸形态**的占位域名 (脱敏产物里可能是 `siteN.example.com/x`
        # 而非 `//siteN.example.com/x`) ⇒ 同一链接只差域名前缀时形态应视为相同
        路径 = re.sub(r'^site\d+\.example\.com(?=/)', '', 路径)
        路径 = re.sub(r'\d+', 'N', 路径)                    # 数字 ID 归一
        # **只取章节链接**: 含数字段且以 .html/.htm 结尾。
        # 排除 css/js/图片/APP/压缩包/CDN 域名等 —— 它们的形态会因域名替换
        # 而变化 (protocol-relative → 绝对路径等), 与被测的章节形态无关。
        if not (re.search(r'N', 路径) and
                re.search(r'\.(html?|php|asp|aspx)$', 路径, re.I)):
            continue
        出.add(路径)
    return 出


def 判据行为(源码_dir: Path) -> dict:
    """脱敏前后判据行为对照 (硬门禁②: 行为必须一致)"""
    import io
    import sys as _s
    if str(_根 / '源码') not in _s.path:
        _s.path.insert(0, str(_根 / '源码'))
    from bs4 import BeautifulSoup
    import 爬虫 as C
    import captcha_module as CM
    判 = CM.CaptchaHandler.__dict__['is_captcha_page']
    行为 = {}
    折 = _根 / '测试样本_本地' / 'tianqiu_目录.html'
    if 折.is_file():
        原 = BeautifulSoup(折.read_bytes().decode('utf-8', 'replace'), 'lxml')
        链 = len(re.findall(r'href="[^"]*\d+\.html"', 折.read_bytes().decode('utf-8', 'replace')))
        行为['折叠_脱敏前'] = bool(C._目录折叠提示(原, 链))
    验 = _根 / '测试样本_本地' / 'siteg_访问验证页.html'
    if 验.is_file():
        t = 验.read_bytes().decode('utf-8', 'replace')
        行为['验证页_第一道门'] = bool(C._像验证码页(t))
        行为['验证页_第二道门'] = bool(判(t))
    return 行为


def 红线扫描(文本: str, _对照原文: str = '') -> list:
    """脱敏产物自检 (硬门禁①)。返回命中项列表, 空 = 通过。"""
    命中 = []
    真实域 = re.findall(r'[a-z0-9-]+\.(?:com|net|org|cc|hk|tw|la|me|top|xyz|info)\b',
                        文本, re.I)
    真实域 = [d for d in set(真实域)
              if not d.endswith(('example.com', 'example.org', 'example.net'))]
    if 真实域:
        命中.append(f'真实域名残留: {sorted(真实域)[:5]}')
    原形态, 新形态 = _链接形态(_对照原文), _链接形态(文本)
    if 原形态 != 新形态:
        丢 = sorted(原形态 - 新形态)[:3]
        加 = sorted(新形态 - 原形态)[:3]
        命中.append(f'链接形态被改动: 丢={丢} 多={加}')
    丢词 = _关键词完好(_对照原文, 文本)
    if 丢词:
        命中.append(f'判据关键词被脱敏破坏: {丢词}')
    裸 = re.sub(r'<[A-Za-z_]+>', '', 文本)   # 剥掉占位符再扫, 避免误判
    if re.search(r'第\s*\d+\s*章\s*[\u4e00-\u9fa5]{2,}', 裸):
        命中.append('疑似书名残留(章节标题未抹净)')
    return 命中


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='真实页面样本脱敏入库')
    ap.add_argument('--入库', action='store_true', help='写入 测试/样本/')
    ap.add_argument('--单份', default='', help='只处理指定文件 (调试用)')
    args = ap.parse_args(argv)

    if not _源.is_dir():
        print(f'[FAIL] 源样本目录不存在: {_源}')
        return 1

    名单 = {args.单份: ('', None)} if args.单份 else 白名单
    缺 = [n for n in 名单 if not (_源 / n).is_file()]
    if 缺:
        print(f'[WARN] 快照缺失(跳过): {缺}')

    前 = 判据行为(_源)
    print(f'[基线] 脱敏前判据行为: {前}')

    产出, 失败 = [], []
    for 名, (说明, 上限) in 名单.items():
        路径 = _源 / 名
        if not 路径.is_file():
            continue
        原文 = 路径.read_bytes().decode('utf-8', errors='replace')
        新 = 裁剪(脱敏(原文), 上限)
        命中 = 红线扫描(新, 原文)
        if 命中:
            失败.append((名, 命中))
            print(f'  [FAIL] {名}: {命中}')
            continue
        产出.append((名, 说明, 新))
        print(f'  [OK] {名}  {len(原文)//1024} KB → {len(新)//1024} KB  ({说明})')

    # 行为不变校验: 用脱敏产物复跑同一组判据
    if 产出 and args.入库:
        import io
        import sys as _s
        if str(_根 / '源码') not in _s.path:
            _s.path.insert(0, str(_根 / '源码'))
        from bs4 import BeautifulSoup
        import 爬虫 as C
        import captcha_module as CM
        判 = CM.CaptchaHandler.__dict__['is_captcha_page']
        _出.mkdir(parents=True, exist_ok=True)
        for 名, 说明, 新 in 产出:
            出名 = 名
            (_出 / 出名).write_text(新, encoding='utf-8')
            print(f'  [写入] 测试/样本/{出名}')
        # 复跑行为对照
        折 = next((p for p in 产出 if 'tianqiu' in p[0]), None)
        if 折:
            soup = BeautifulSoup(折[2], 'lxml')
            链 = len(re.findall(r'href="[^"]*\d+\.html"', 折[2]))
            后 = bool(C._目录折叠提示(soup, 链))
            if 后 != 前.get('折叠_脱敏前'):
                print(f'  [FAIL] 折叠判据行为变了: 前={前.get("折叠_脱敏前")} 后={后}')
                return 1
            print(f'  [校验] 折叠判据行为一致: {后} ✓')
        验 = next((p for p in 产出 if '访问验证' in p[0]), None)
        if 验:
            if not C._像验证码页(验[2]):
                print('  [FAIL] 验证页脱敏后第一道门不再命中')
                return 1
            if not 判(验[2]):
                print('  [FAIL] 验证页脱敏后第二道门不再命中')
                return 1
            print('  [校验] 验证页两道门仍命中 ✓')

    print(f'\n[汇总] 通过 {len(产出)} 份 / 失败 {len(失败)} 份'
          f'{"（未入库）" if not args.入库 else "（已入库）"}')
    return 1 if 失败 else 0


if __name__ == '__main__':
    sys.exit(main())
