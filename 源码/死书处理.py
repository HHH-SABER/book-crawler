# -*- coding: utf-8 -*-
"""死书处理 (2026-10-02 新增): 抓取失败的原因判定 + 死书清单 + 删除编排。

解决的问题: 抓取失败时"网站不可达"与"书被删除"被拍扁成同一句
"未提取到章节, 所有可用源均未能完成抓取", 用户无法判断该不该删这本书的
记录。本模块给出可判定的分类, 并提供死书清单 (集中管理) 与删除编排。

判定信号 (来自 爬虫.py, 三者互斥优先级见 判定死书):
  ① 页面为空: inspect_page 重试耗尽 / Selenium 兜底失败 → 返回空 soup
     (爬虫.py:1493 / :1533-1534, 不抛异常) —— 页面根本没拿到
  ② 书名退化: 书名提取失败回退占位值 (爬虫.py:5525-5531 → "novel"/"小说")
  ③ 章节数为 0

处置原则: 只有"书已删除或不可读"才询问用户是否删除记录; "站点不可达"
与"目录无章节"仅提示 (删了可惜 / 疑似选择器失效, 误删代价高)。

模块边界 (不做什么):
  - 不动 爬取历史 / 站点历史 (按需求: 只删任务/书架/网站清单)
  - 不删已抓产物文件 (任务删除恒 delete_file=False)
  - 不做"以后不再询问"式全局偏好开关 (记录死书返回"是否首次"即等价实现)
  - 不给手机端做询问/回执 (远控是单向广播, 架构上不可能)
"""
import hashlib
import json
import os
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import 日志 as _app_log
_log = _app_log.get('死书处理')

# 死书类型 (与 判定死书 的返回值一一对应)
类型_站点不可达 = '站点不可达'
类型_书已删除 = '书已删除或不可读'
类型_无章节 = '目录无章节'

# 只有这些类型才询问用户是否删除 (UI 层的唯一分叉依据)
可询问删除类型 = (类型_书已删除,)

# 书名提取失败时的退化值 (爬虫.py:5525-5531 的回退 + None/空串)
书名退化集合 = (None, '', 'novel', '小说')

# 状态取值 (3 态, 不设"新增"态 —— 落盘即"待确认")
状态_待确认 = '待确认'
状态_已删除 = '已删除'
状态_已忽略 = '已忽略'

_清单文件名 = '死书清单.json'
_清单版本 = 1
_上限 = 500
# RLock (可重入): 记录死书() 持锁期间会调用 保存()/载入(), 二者内部同样取锁;
# 用普通 Lock 会在单线程内自死锁 (2026-10-02 实测踩到)
_锁 = threading.RLock()


class 死书错误(RuntimeError):
    """死书判定异常: 携带 类型/原因/网址, 取代泛用 RuntimeError。

    只在"0 章节且已判定死书"时抛出; 其余失败路径 (网络抖动/反爬/部分章节
    失败) 保持原 RuntimeError 语义不变。多源回退下以判定出的死书为准 —— 若
    后续源只抛出普通网络异常, run_crawl 会保留先前这个 死书错误 (判定信息量
    更大, 不应被更笼统的异常覆盖)。
    """

    def __init__(self, 类型: str, 原因: str, 网址: str = ''):
        super().__init__(f"死书[{类型}]: {原因}")
        self.类型 = 类型
        self.原因 = 原因
        self.网址 = 网址


def 判定死书(*, 页面为空: bool, 书名: str = '', 章节数: int = 0) -> dict:
    """0 章节三信号判定 (纯函数, 无 IO)。返回 {类型, 原因, 可询问删除}。

    优先级 (自上而下短路):
      ① 章节数 > 0         → 不是死书 (返回 None)
      ② 页面为空           → 站点不可达   (可询问删除=False)
      ③ 书名退化 + 0 章节  → 书已删除或不可读 (可询问删除=True)
      ④ 书名正常 + 0 章节  → 目录无章节   (可询问删除=False, 疑似选择器失效)
    """
    if 章节数 and 章节数 > 0:
        return None
    if 页面为空:
        return {
            '类型': 类型_站点不可达,
            '原因': '目录页三次重试均未取到内容 (页面为空), 站点不可达或网络受限',
            '可询问删除': False,
        }
    if (书名 or '') in 书名退化集合 or str(书名 or '').strip() in 书名退化集合:
        return {
            '类型': 类型_书已删除,
            '原因': '目录页可访问但未解析出章节, 且书名提取退化为占位值',
            '可询问删除': True,
        }
    return {
        '类型': 类型_无章节,
        '原因': '目录页可访问且书名正常, 但未解析出章节 (疑似选择器失效或目录为空)',
        '可询问删除': False,
    }


# ---------------------------------------------------------------- 清单存储
def 清单路径() -> str:
    from _path_utils import get_state_root
    return os.path.join(get_state_root(), '数据', _清单文件名)


def _规范化网址(网址: str) -> str:
    """去 fragment / 去尾斜杠 / netloc 小写 —— 仅用于死书清单内部去重。"""
    try:
        sp = urlsplit((网址 or '').strip())
        netloc = (sp.netloc or '').lower()
        path = (sp.path or '').rstrip('/')
        return f"{netloc}{path}"
    except Exception:
        return (网址 or '').strip().lower()


def _键(网址: str) -> str:
    return hashlib.sha1(_规范化网址(网址).encode('utf-8')).hexdigest()[:12]


def 载入() -> list:
    """读死书清单; 文件缺失/损坏 → [] (绝不抛, 记 info 级日志)。"""
    path = 清单路径()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            数据 = json.load(f)
        记录 = 数据.get('记录') if isinstance(数据, dict) else None
        return [r for r in 记录 if isinstance(r, dict)] if isinstance(记录, list) else []
    except FileNotFoundError:
        return []
    except Exception as e:
        _log.info(f"死书清单读取失败 (按空清单处理): {type(e).__name__}: {e}")
        return []


def 保存(记录列表: list) -> bool:
    """原子写死书清单 (锁内快照 → 锁外 IO; tmp 名带 pid+tid 防并发截断)。"""
    path = 清单路径()
    try:
        with _锁:
            快照 = json.dumps({'版本': _清单版本, '记录': 记录列表},
                              ensure_ascii=False, indent=1)
        锚定 = Path(path).resolve()
        锚定.parent.mkdir(parents=True, exist_ok=True)
        tmp = 锚定.with_name(f"{锚定.name}.tmp.{os.getpid()}.{threading.get_ident()}")
        tmp.write_text(快照, encoding='utf-8')
        os.replace(tmp, 锚定)
        return True
    except Exception as e:
        _log.debug(f'裸 except 吞异常: {type(e).__name__}: {e} (死书清单落盘失败)')
        return False


def _裁剪(记录列表: list) -> list:
    """上限裁剪: 先裁 已删除/已忽略, 再裁最旧的。"""
    if len(记录列表) <= _上限:
        return 记录列表
    活跃 = [r for r in 记录列表 if r.get('状态') == 状态_待确认]
    已结 = [r for r in 记录列表 if r.get('状态') != 状态_待确认]
    保留 = len(记录列表) - _上限
    新 = 活跃
    for r in sorted(已结, key=lambda x: x.get('最近时间', '')):
        if 保留 <= 0:
            break
        新.append(r)
        保留 -= 1
    return 新[-_上限:] if len(新) > _上限 else 新


def 记录死书(网址: str, 书名: str, 类型: str, 原因: str,
             任务id: str = '', 备注: str = '') -> tuple:
    """登记/累加一条死书。返回 (记录, 是否首次)。

    首次 = 该网址此前没有"待确认"记录 (用于决定要不要弹窗):
      - 全新           → 首次=True
      - 已有 待确认    → 次数+1, 首次=False (不重复打扰)
      - 已有 已删除    → 重开为 待确认 (用户又提交了), 首次=True
      - 已有 已忽略    → 保持 已忽略, 次数+1, 首次=False (用户已表态)
    """
    网址 = (网址 or '').strip()
    if not 网址:
        raise ValueError('死书记录必须有网址')
    现在 = time.strftime('%Y-%m-%d %H:%M:%S')
    with _锁:
        记录列表 = 载入()
        键 = _键(网址)
        已有 = next((r for r in 记录列表 if r.get('键') == 键), None)
        if 已有 is None:
            记录 = {
                '键': 键, '网址': 网址, '书名': 书名 or '', '域名': _取域名(网址),
                '类型': 类型, '原因': 原因,
                '可询问删除': 类型 in 可询问删除类型,
                '状态': 状态_待确认, '首次时间': 现在, '最近时间': 现在,
                '次数': 1, '任务id': [任务id] if 任务id else [], '备注': 备注,
            }
            记录列表.append(记录)
            首次 = True
        else:
            首次 = 已有.get('状态') == 状态_已删除
            已有['状态'] = 状态_待确认 if 首次 else 已有.get('状态', 状态_待确认)
            已有.update({'网址': 网址, '书名': 书名 or 已有.get('书名', ''),
                         '域名': _取域名(网址), '类型': 类型, '原因': 原因,
                         '可询问删除': 类型 in 可询问删除类型,
                         '最近时间': 现在, '次数': int(已有.get('次数', 1)) + 1,
                         '备注': 备注 or 已有.get('备注', '')})
            if 任务id and 任务id not in 已有.setdefault('任务id', []):
                已有['任务id'].append(任务id)
            记录 = 已有
        保存(_裁剪(记录列表))
    return 记录, 首次


def _取域名(网址: str) -> str:
    try:
        return (urlsplit(网址).netloc or '').lower()
    except Exception:
        return ''


def 列出(状态: str = '', 类型: str = '') -> list:
    """按状态/类型筛选 (空串 = 不过滤), 按最近时间倒序。"""
    记录列表 = 载入()
    if 状态:
        记录列表 = [r for r in 记录列表 if r.get('状态') == 状态]
    if 类型:
        记录列表 = [r for r in 记录列表 if r.get('类型') == 类型]
    return sorted(记录列表, key=lambda r: r.get('最近时间', ''), reverse=True)


def 设状态(键: str, 状态: str) -> bool:
    with _锁:
        记录列表 = 载入()
        目标 = next((r for r in 记录列表 if r.get('键') == 键), None)
        if 目标 is None:
            return False
        目标['状态'] = 状态
        return 保存(记录列表)


def 移除记录(键: str) -> bool:
    """只清死书清单本身, 不动任何其他数据。"""
    with _锁:
        记录列表 = 载入()
        留 = [r for r in 记录列表 if r.get('键') != 键]
        if len(留) == len(记录列表):
            return False
        return 保存(留)


def 标记已恢复(网址: str) -> dict:
    """抓取成功 → 该网址不再是死书, 移除其 待确认/已忽略 记录。

    阶段5 (重新检测) 的落点。**必须由数据层自动调用**, 不能只靠死书清单页
    刷新时顺带处理: 重新检测后用户可能直接切去任务表看进度, 根本不在清单页;
    若清理挂在 UI 上, 记录会一直躺在清单里 → 用户以为"重新检测没用"。

    刻意**不动 已删除**: 那是用户已处置的终态账目 (任务/书架/网站清单三处
    都已删), 抓回一本书不等于该把历史账目改写 —— 留着只占一条, 无害。

    幂等: 记录不存在 / 已是 已删除 → 返回 移除=False, 不报错 (成功路径上
    静默是正确行为, 不能因"没有死书记录"让整轮抓取被当成失败)。

    返回 {'移除': bool, '键': str, '书名': str}。
    """
    网址 = (网址 or '').strip()
    空 = {'移除': False, '键': '', '书名': ''}
    if not 网址:
        return 空
    with _锁:
        记录列表 = 载入()
        键 = _键(网址)
        目标 = next((r for r in 记录列表 if r.get('键') == 键), None)
        if 目标 is None:
            return 空
        if 目标.get('状态') == 状态_已删除:
            return {'移除': False, '键': 键, '书名': 目标.get('书名', '')}
        书名 = 目标.get('书名', '')
        留 = [r for r in 记录列表 if r.get('键') != 键]
        if not 保存(留):
            return {'移除': False, '键': 键, '书名': 书名}
    _log.info(f"死书清单: 已移除死书记录 (书名={书名 or '?'} 网址={网址[:60]})")
    return {'移除': True, '键': 键, '书名': 书名}


# ---------------------------------------------------------------- 删除编排
范围_默认 = ('任务', '书架', '网站清单')


def 删除书记录(网址: str, 任务id: str = '', 范围: tuple = 范围_默认,
                task_manager=None) -> dict:
    """统一删除编排: 任务记录 + 书架.json + 网站清单.txt。

    返回 {项: (成功, 说明), ..., '全部成功': bool}。
    逐项独立 try, **不做回滚**: 任务行一旦从 tasks 摘除无法复原, 伪回滚比
    部分成功更危险 (用户看到"已删除"但数据半在)。部分成功由调用方如实呈现。
    任务项恒传 delete_file=False → 已抓产物文件绝不会被删。
    """
    from urllib.parse import urlsplit as _sp

    def _删任务():
        if not 任务id:
            return False, '无任务id (非本任务删除)'
        mgr = task_manager
        if mgr is None:
            # TaskManager.__init__ 需要 page 参数, 无参构造必 TypeError
            # ("missing 1 required positional argument: 'page'", 阶段3 实测)。
            # 无外部 manager 时只能放弃任务项 —— 诚实报失败, 不能伪成功:
            # 任务行删不掉却告诉用户"已删除", 用户去清单页找不到残留行。
            return False, '未提供任务管理器, 跳过任务行 (请在任务表内直接删除)'
        return bool(mgr.delete_task(任务id, delete_file=False)), '' if mgr else ''

    def _删书架():
        import 书架
        ok = 书架.移除(网址)
        return ok, '' if ok else '书架中无该书记录'

    def _删网站清单():
        import 网站清单
        ok = 网站清单.移除(网址)
        return ok, '' if ok else '网站清单中无该网址'

    分派 = {'任务': _删任务, '书架': _删书架, '网站清单': _删网站清单}
    结果 = {}
    for 项 in 范围:
        try:
            结果[项] = 分派[项]()
        except Exception as e:
            结果[项] = (False, f'{type(e).__name__}: {e}')
            _log.error(f'死书处理: 删除{项}失败 ({网址[:40]}): {type(e).__name__}: {e}')
    结果['全部成功'] = all(v[0] for k, v in 结果.items() if k != '全部成功')
    return 结果
