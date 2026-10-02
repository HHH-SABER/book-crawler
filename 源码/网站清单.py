# -*- coding: utf-8 -*-
"""网站清单：自动维护「网址 + 网站名 + 小说名」清单文件

为什么需要它: 早期用户手维护的 小说网站.txt 是纯 URL 清单, 无站名/书名,
每次抓书都要回头补记录。本模块把 (网址, 网站名, 小说名) 自动累积成一份
可读清单, 按网址去重 (同一书重复抓只更新不新增), 供:
  - 用户直接打开查看 (每行一条, # 注释);
  - 爬取历史页按网址反查站名/书名显示 + 书名关键词搜索。

文件位置 (2026-10-01 起): **程序基目录**/网站清单.txt (get_app_base_dir)
  - 源码模式: 项目根/网站清单.txt
  - EXE 模式: EXE 同级目录/网站清单.txt
  —— 与 抓取结果/、站点配置.json 同侧: 用户从任何渠道拿到 EXE, 首次运行
  即在旁边自动生成, 文件管理器直接可见, 不必去 %LOCALAPPDATA% 找。
  旧位置(状态根 数据/网站清单.txt)已有记录时, 首次使用自动迁移过来。

⚠️ 隐私: 本文件是用户的个人爬取记录, **不入库** (.gitignore 已忽略),
   请勿上传、随发布包分发或分享; 构建脚本只会在 dist 预置**空模板**。

可靠性 (对齐项目规约):
  - 原子写: tmp + os.replace (写一半崩溃不损坏旧内容);
  - 线程安全: 模块级锁串行化读写 (多任务并发完成时同时追加);
  - 写盘失败只记日志, 绝不阻塞抓取主流程;
  - 只收录 http/https 网址 (本地文件/测试临时路径不入清单)。
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
    from _path_utils import get_app_base_dir, get_state_root
except Exception:
    def get_app_base_dir():
        """回退实现: 源码模式取项目根 (本文件位于 源码/ 下)"""
        return os.path.normpath(os.path.join(_HERE, '..'))

    def get_state_root():
        """回退实现: 状态数据根 (%LOCALAPPDATA%/小说爬虫)"""
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
# 测试/探针/多实例隔离: 该环境变量设为绝对文件路径时覆盖清单落点
# (不设置则用程序基目录; 与「重定向 LOCALAPPDATA」同一思路)
_环境覆盖变量 = 'NC_LEDGER_PATH'

# 域名 → 网站名 (站点专属数据, 站点脱钩: 外置 站点适配_本地/域名映射.json 不入库;
# 公开形态映射为空, 未知域名回退为域名本身, 详见 域名网站名() 与 _加载域名映射())
_网站名映射 = {}
_映射已加载 = False


def _加载域名映射():
    """从 站点适配_本地/域名映射.json 加载 域名→站名 (幂等; 缺失即公开形态)。

    punycode 子域 (xn-- 前缀) 需在 JSON 里单独映射。
    """
    global _映射已加载
    if _映射已加载:
        return
    _映射已加载 = True
    try:
        import json as _json
        from _path_utils import get_app_base_dir
        _p = os.path.join(get_app_base_dir(), '站点适配_本地', '域名映射.json')
        if os.path.isfile(_p):
            with open(_p, 'r', encoding='utf-8') as f:
                _data = _json.load(f)
            if isinstance(_data, dict):
                _网站名映射.update({str(k).strip().lower(): str(v)
                                    for k, v in _data.items() if k})
    except Exception as _e:
        try:
            _log.info(f'[网站清单] 域名映射加载失败 (不影响主流程): '
                      f'{type(_e).__name__}')
        except Exception:
            pass  # 刻意静默: 日志链路兜底


def _环境已覆盖() -> bool:
    """NC_LEDGER_PATH 是否已显式指向隔离落点 (测试/探针/多实例)"""
    return bool((os.environ.get(_环境覆盖变量) or '').strip())


def 文件路径() -> str:
    """清单文件绝对路径。

    优先级: 环境变量 NC_LEDGER_PATH (测试/探针/多实例隔离) > 程序基目录
    (源码模式=项目根, EXE 模式=EXE 同级目录)。
    """
    覆盖 = (os.environ.get(_环境覆盖变量) or '').strip()
    if 覆盖:
        return os.path.abspath(覆盖)
    return os.path.join(get_app_base_dir(), _文件名)


def 旧路径() -> str:
    """2026-10-01 之前的落点 (状态根 数据/网站清单.txt), 仅用于一次性迁移"""
    try:
        return os.path.join(get_state_root(), '数据', _文件名)
    except Exception as e:
        _log.debug(f'裸 except 吞异常: {type(e).__name__}: {e} (旧清单路径解析失败)')
        return ''


def 模板文本() -> str:
    """空清单模板 (首启生成与构建期在 dist 预置共用; 不含任何用户记录)"""
    return ('# 网站清单 — 程序自动维护, 请勿手改格式 (抓取/尝试抓取后自动追加)\n'
            '# 每行: 网址\\t网站名\\t小说名 (制表符分隔, # 开头为注释)\n'
            '# 本文件是个人爬取记录, 请勿上传或分享\n'
            f'# 首次生成: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')


def 自动生成若缺失() -> str:
    """启动自检: 基目录无清单文件时生成模板 (幂等), 返回文件路径。

    用户从任何渠道拿到 EXE, 首次运行即在 EXE 同级生成该文件;
    旧位置(状态根)已有记录时先迁移过来 —— 用户无感, 历史不丢。
    例外: 已用 NC_LEDGER_PATH 指定隔离落点 (测试/探针/多实例) 时不迁移,
    绝不把真实用户记录搬进临时环境。
    """
    path = 文件路径()
    try:
        if os.path.exists(path):
            return path
        _目录 = os.path.dirname(path)
        if _目录:
            os.makedirs(_目录, exist_ok=True)
        旧 = '' if _环境已覆盖() else 旧路径()
        with _锁:
            if not os.path.exists(path):
                内容 = ''
                if (旧 and os.path.abspath(旧) != os.path.abspath(path)
                        and os.path.exists(旧)):
                    try:
                        with open(旧, 'r', encoding='utf-8', errors='ignore') as f:
                            内容 = f.read()
                    except OSError as e:
                        _log.debug(f'旧清单读取失败, 改用空模板: '
                                   f'{type(e).__name__}: {e}')
                if 内容.strip():
                    _原子写(path, 内容)
                    _log.info(f"[网站清单] 已从旧位置迁移: {旧} → {path}")
                else:
                    _原子写(path, 模板文本())
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
    """追加/更新一条记录 (任务开始=尝试抓取, 任务结束=补齐书名)。

    按网址去重: 已存在则不重复新增, 只补齐缺失的 网站名/小说名
    (同一书重抓只刷新字段)。只收录 http/https 网址 —— 本地文件与
    测试临时路径不入清单, 保证这份记录对用户始终有意义。

    返回值: True=写入成功 (含已存在仅更新), False=未写入 (不阻塞主流程)。
    """
    网址 = (网址 or '').strip()
    if not 网址:
        return False
    if not 网址.lower().startswith(('http://', 'https://')):
        _log.debug(f'[网站清单] 跳过非 http(s) 目标: {网址[:80]}')
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
                    _原子写(文件路径(), _重建(条目))
                return True
            _网站名 = 网站名 or 域名网站名(网址)
            条目.append({'网址': 网址, '网站名': _网站名, '小说名': 小说名})
            _原子写(文件路径(), _重建(条目))
            return True
        except Exception as e:
            _log.debug(f'裸 except 吞异常: {type(e).__name__}: {e} '
                       f'(记录网站清单失败不影响抓取)')
            return False


def 移除(网址: str) -> bool:
    """按网址移除一条清单条目 (死书处理用)。命中并落盘返回 True。

    匹配两轮: 先精确串匹配, 未命中再按规范化网址匹配 —— 清单是用户可手改的
    文本文件, 手改常带尾斜杠/大小写差异。不调用 自动生成若缺失(): 对不存在的
    文件执行移除是 no-op False, 绝不凭空生成模板文件。
    """
    网址 = (网址 or '').strip()
    if not 网址:
        return False
    with _锁:                    # 串行化: 与 记录() 共用同一把锁, 不互相覆盖
        try:
            条目 = 读取()
            留 = [x for x in 条目 if x['网址'] != 网址]
            if len(留) == len(条目):          # 精确未命中 → 规范化兜底
                _规范 = _规范化网址(网址)
                留 = [x for x in 条目 if _规范化网址(x['网址']) != _规范]
            if len(留) == len(条目):
                return False
            _原子写(文件路径(), _重建(留))    # _重建 自带 _注释头, 表头不被抹掉
            return True
        except Exception as e:
            _log.debug(f'裸 except 吞异常: {type(e).__name__}: {e} '
                       f'(移除网站清单条目失败)')
            return False


def _规范化网址(网址: str) -> str:
    """去 fragment / 去尾斜杠 / netloc 小写 (仅本模块内匹配用)"""
    try:
        from urllib.parse import urlsplit
        sp = urlsplit((网址 or '').strip())
        return f"{(sp.netloc or '').lower()}{(sp.path or '').rstrip('/')}"
    except Exception:
        return (网址 or '').strip().lower()


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
    _加载域名映射()
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


def _注释头() -> str:
    """保留清单文件开头连续的 # 注释块 (含空行)。

    回写时若不带上, 记录一次就把表头(格式说明/隐私提示)抹掉 ——
    2026-10-01 实测: 别处会话跑了一批抓取后, 清单只剩纯数据行。
    """
    try:
        with open(文件路径(), 'r', encoding='utf-8') as f:
            头 = []
            for 行 in f:
                s = 行.rstrip('\r\n')
                if s.lstrip().startswith('#'):
                    头.append(s)
                elif not s.strip() and 头:
                    头.append(s)          # 注释块内的空行保留
                else:
                    break
            while 头 and not 头[-1].strip():
                头.pop()                  # 尾部空行去掉, 避免越写越长
            return ('\n'.join(头) + '\n') if 头 else 模板文本()
    except FileNotFoundError:
        return 模板文本()
    except Exception as e:
        _log.debug(f'裸 except 吞异常: {type(e).__name__}: {e} (清单注释头读取失败)')
        return ''


def _重建(条目) -> str:
    """注释头 + 数据行 —— 所有回写都走这里, 保证表头不被抹掉"""
    行 = [f"{x['网址']}\t{x['网站名']}\t{x['小说名']}" for x in 条目]
    正文 = '\n'.join(行)
    if 正文:
        正文 += '\n'
    return _注释头() + 正文


def _原子写(path: str, 内容: str) -> None:
    """原子落盘 (范式同 爬取历史.py:_落盘): pathlib 锚定 + tmp 带 pid + os.replace"""
    import os as _os
    from pathlib import Path as _P
    fobj = _P(path).resolve()
    tmp = fobj.with_name(fobj.name + f'.tmp.{_os.getpid()}')
    tmp.write_text(内容, encoding='utf-8')
    _os.replace(tmp, fobj)