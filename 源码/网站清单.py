# -*- coding: utf-8 -*-
"""网站清单：自动维护「网址 + 网站名 + 小说名」清单文件 (仿 小说网站.txt)

为什么需要它: 用户手维护的 小说网站.txt 是纯 URL 清单, 无站名/书名,
每次抓书都要回头补记录。本模块在程序抓取成功后把 (网址, 网站名, 小说名)
自动追加进清单, 按网址去重 (同一书重复抓只更新不新增), 供:
  - 用户直接打开查看 (与 小说网站.txt 同风格, 每行一条, # 注释);
  - 爬取历史页按网址反查站名/书名显示。

文件位置: %LOCALAPPDATA%/小说爬虫/数据/网站清单.txt (get_state_root),
与 爬取历史.json/书架 同根 —— 换 EXE、换目录、重装都不丢;
每次运行 `自动生成若缺失()` 幂等自检, EXE 迁移/首启后自动生成模板。

可靠性 (对齐项目规约):
  - 原子写: tmp + os.replace (写一半崩溃不损坏旧内容);
  - 线程安全: 模块级锁串行化读写 (多任务并发完成时同时追加);
  - 写盘失败只记日志, 绝不阻塞抓取主流程。
"""
import os
import sys
import threading
import time
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    from _path_utils import get_state_root
except Exception:
    def get_state_root():
        return os.path.join(os.path.expanduser("~"), "AppData",
                            "Local", "小说爬虫")

try:
    import 日志 as _app_log
    _log = _app_log.get('网站清单')
except Exception:
    import logging
    _log = logging.getLogger('网站清单')

_文件名 = '网站清单.txt'
_锁 = threading.Lock()

# 常见站点 域名 → 网站名 (未知域名回退为域名本身, 详见 域名网站名())
_网站名映射 = {
    'qiqishu.cc': '奇书网',
    'yueliang.org': '月亮小说网',
    'shuhaige.net': '书海阁',
    'yunshuzhai.com': '云书斋',
    'als1010.space': '爱丽丝书屋',
    'uuwxw.cc': '悠悠书城',
    'zhiruo.org': '知若网',
    'biquwx.cc': '笔趣阁',
    'ahxsw.com': '安徽小说网',
    '11bzw.org': '书宝网',
    'yqyp.net': '一起泡',
    '28zw.org': '云趣阁',
    'spscl.com': '书神领域',
    'tanmixs.com': '探密小说网',
    '630wang.cc': '630小说',
    'ciyewk.com': '笔趣阁',
    'ltbook.net': '龙腾小说',
    '322zw.com': '蛇蝎小说网',
    'banlvzw.com': '半路中文',
    'exotxt.net': '飘天文学',
    '5hbook.net': '六五读书',
    'oldtimeswx.net': '旧时小说网',
    'yipinzongshi.com': '一品宗师',
    'xingguangks.com': '星光小说',
    'shubaoks.net': '书包网',
    'orion34g.com': '猎户座',
    'pjxdd.com': '爬爬小说',
    'qingheks.com': '清河看小说',
    '27xsw.cc': '27小说网',
}


def 文件路径() -> str:
    """清单文件绝对路径 (数据目录)"""
    return os.path.join(get_state_root(), '数据', _文件名)


def 自动生成若缺失() -> str:
    """启动自检: 数据目录无清单文件时生成模板。幂等, 返回文件路径。

    迁移 EXE 位置 / 换机器 / 首启后调用可保证文件存在 (空模板,
    带使用说明注释), 之后抓取成功自动追加记录。
    """
    path = 文件路径()
    try:
        if os.path.exists(path):
            return path
        _目录 = os.path.dirname(path)
        if not os.path.isdir(_目录):
            os.makedirs(_目录, exist_ok=True)
        模板 = ('# 网站清单 — 程序自动维护, 请勿手改格式 (抓取成功后自动追加)\n'
                '# 每行: 网址\\t网站名\\t小说名 (制表符分隔, # 开头为注释)\n'
                f'# 首次生成: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
        with _锁:
            if not os.path.exists(path):
                _原子写(path, 模板)
        _log.info(f"[网站清单] 首次生成: {path}")
    except Exception as e:
        _log.debug(f'裸 except 吞异常: {type(e).__name__}: {e} '
                   f'(清单自检失败不影响主流程)')
    return path


def 读取() -> list:
    """读取全部条目 [{网址, 网站名, 小说名}], 忽略注释/空行/非法行"""
    条目 = []
    try:
        with open(文件路径(), 'r', encoding='utf-8') as f:
            for 行 in f:
                行 = 行.rstrip('\n').rstrip('\r')
                if not 行 or 行.lstrip().startswith('#'):
                    continue
                段 = 行.split('\t')
                if len(段) < 1 or not 段[0].strip():
                    continue
                条目.append({
                    '网址': 段[0].strip(),
                    '网站名': 段[1].strip() if len(段) > 1 else '',
                    '小说名': 段[2].strip() if len(段) > 2 else '',
                })
    except FileNotFoundError:
        return []
    except Exception as e:
        _log.debug(f'裸 except 吞异常: {type(e).__name__}: {e}')
    return 条目


def 记录(网址: str, 网站名: str = '', 小说名: str = '') -> bool:
    """抓取成功后追加一条记录。按网址去重: 已存在则不重复新增,
    只补齐缺失的 网站名/小说名 (小说重抓时刷新)。

    返回值: True=写入成功 (含已存在仅更新), False=写入失败 (不阻塞主流程)。
    """
    网址 = (网址 or '').strip()
    if not 网址:
        return False
    自动生成若缺失()
    with _锁:                    # 串行化: 多任务并发完成同时追加互不覆盖
        try:
            条目 = 读取()
            已有 = next((x for x in 条目 if x['网址'] == 网址), None)
            if 已有 is not None:
                _变 = False
                # 站名/书名非空且与旧值不同 → 覆盖 (旧值可能是域名占位/首抓空名,
                # 后续抓取拿到准确中文站名/书名时允许补齐更新; 同值调用不写盘)
                if 网站名 and 已有['网站名'] != 网站名:
                    已有['网站名'] = 网站名
                    _变 = True
                if 小说名 and 已有['小说名'] != 小说名:
                    已有['小说名'] = 小说名
                    _变 = True
                if _变:       # 字段有更新 → 落盘同步 (纯去重命中不写)
                    _行 = '\n'.join(
                        f"{x['网址']}\t{x['网站名']}\t{x['小说名']}"
                        for x in 条目) + '\n'
                    _原子写(文件路径(), _行)
                return True
            _网站名 = 网站名 or 域名网站名(网址)
            条目.append({'网址': 网址, '网站名': _网站名, '小说名': 小说名})
            行 = [f"{x['网址']}\t{x['网站名']}\t{x['小说名']}"
                  for x in 条目]
            内容 = '\n'.join(行)
            if 内容:
                内容 += '\n'
            _原子写(文件路径(), 内容)
            return True
        except Exception as e:
            _log.debug(f'裸 except 吞异常: {type(e).__name__}: {e} '
                       f'(记录网站清单失败不影响抓取)')
            return False


def 查(网址: str) -> dict:
    """按网址反查条目, 未命中返回 {}"""
    网址 = (网址 or '').strip()
    for x in 读取():
        if x['网址'] == 网址:
            return x
    return {}


def 按小说名搜索(关键词: str) -> list:
    """按书名关键词模糊搜索 (历史页书名过滤用), 无结果返回 []"""
    关键词 = (关键词 or '').strip()
    if not 关键词:
        return []
    try:
        return [x for x in 读取()
                if 关键词 in (x.get('小说名') or '')]
    except Exception:
        return []


def 域名网站名(网址或域名: str) -> str:
    """URL/域名 → 中文网站名。未知域名回退 '域名' (去 www. 前缀)"""
    s = (网址或域名 or '').strip()
    try:
        from urllib.parse import urlparse
        if '://' in s:
            s = urlparse(s).netloc
        s = s.split('@')[-1].split(':')[0].lower()
        if s.startswith('www.'):
            s = s[4:]
        return _网站名映射.get(s, s or '')
    except Exception:
        return s or ''


def _原子写(path: str, 内容: str) -> None:
    """tmp + os.replace 原子落盘 (禁止直接 write_text, 对齐项目规约)"""
    import os as _os
    tmp = path + f'.tmp.{_os.getpid()}'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(内容)
        f.flush()
        _os.fsync(f.fileno())
    _os.replace(tmp, path)


def 维护_兼容小说网站txt(url: str, 小说名: str) -> bool:
    """向用户手维护的 小说网站.txt 追加网址 (若缺少), 保持两清单同步。
    文件不存在则跳过 (用户未手动建时不自动创建, 不与 网站清单.txt 抢位置)。
    """
    if not url:
        return False
    try:
        from _path_utils import get_app_base_dir
        path = os.path.join(get_app_base_dir(), '小说网站.txt')
        if not os.path.exists(path):
            return False
        with _锁:
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    文本 = f.read()
            except FileNotFoundError:
                文本 = ''
            for 行 in 文本.splitlines():
                if 行.strip() == url:
                    return True
            新增 = (文本 + ('\n' if 文本 and not 文本.endswith('\n') else '')
                    + url + '\n')
            原子path = path + f'.tmp.{os.getpid()}'
            with open(原子path, 'w', encoding='utf-8') as f:
                f.write(新增)
            os.replace(原子path, path)
            return True
    except Exception as e:
        _log.debug(f'裸 except 吞异常: {type(e).__name__}: {e}')
        return False