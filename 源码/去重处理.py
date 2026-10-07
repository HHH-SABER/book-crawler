# -*- coding: utf-8 -*-
"""重复文件检测与清理 (2026-10-07 新增): 句子级指纹判定 + 去重清单 + 清理编排。

解决的问题: 同一本书被不同站点抓取, 页面标题带站点装饰后缀
("TXT下载" / "免费全文" / "全集最新列表"), 且**章节切法不同**
(A 站 40 章 / B 站 56 章, 内容一致)。标题法分不出、章节法更分不出
(章数多 ≠ 内容多, 站点可能只是切得更碎), 结果同一本书在 抓取结果/ 里堆成多份。

判定信号 (分层, 逐层加强):
  ① 标题归一化  —— **仅作粗筛**: 去括号内容 + 站点装饰后缀 + 空白。
     实测会漏 (如 `示例书甲1.txt` 与 `(示例站点)示例书甲.txt`
     是同一本, 归一化后不同名), 也会误判 (如 `示例书丙.txt` 与
     `示例书丙（校对版 ）.txt` 归一化后同名, 实为两部作品, 句子重叠仅 8.5%)。
  ② 句子级指纹  —— **主力判定**, 对分章/分段免疫: 中文句子以 。！？… 结尾,
     站点怎么切章都改不了句子本身。指标 = Jaccard / 包含度 / 归一化正文字数。

阈值 (2026-10-06 在本机 31 个真实文件上实测标定, 该数据上零误报):
  - Jaccard >= 0.85                → 同一本
  - 包含度 >= 0.95 且 J < 0.85     → 真子集 (保留大的)
  - J >= 0.30 或 包含度 >= 0.60    → 灰区 → 待确认 (绝不自动删)
  - 标题同前缀 且 包含度 >= 0.30   → 灰区 (抓"同书不同站源文本")
  - 其余                           → 不同书

处置原则:
  - **保留项用「归一化正文字数」判定, 不用文件字节数/章节数**
    (字节数受换行/广告/编码干扰; 章数多不代表内容多)。
  - **绝不自动删**: 只产出 待确认 清单; 删除必须由用户确认 (不可逆)。
  - 默认**移入隔离目录** `_已去重/` 而非直接删, 用户可反悔。

模块边界 (不做什么):
  - 不动 爬虫.py 的 _resolve_unique_title (源头"同名就建 (1)"另立一项治理)
  - 不读站点配置/不发网络请求 (纯本地文件分析)
  - 不缓存指纹 (算法便宜且随文件变化, 缓存反而会过期误导)
"""
import hashlib
import json
import os
import re
import shutil
import threading
import time
import zlib
from pathlib import Path

import 日志 as _app_log
_log = _app_log.get('去重处理')

# ---------------------------------------------------------------- 判定常量
句长下限 = 12                 # 短于此长度的句子不进指纹 (对话引语/噪声太多)
阈值_Jaccard_同一本 = 0.85    # >= 此值判同一本
阈值_包含度_子集 = 0.95       # >= 此值且 Jaccard 未达同一本 → 真子集
阈值_Jaccard_灰区 = 0.30      # 灰区下界 (需人工确认)
阈值_包含度_灰区 = 0.60
最小字数比 = 0.02             # 字数比过小则跳过内容比对 (省 O(n^2) 成本)

判定_同一本 = '同一本'
判定_子集 = '真子集'
判定_灰区 = '疑似(待人工确认)'
判定_不同 = '不同'

# 站点装饰后缀 (出现在页面 <title> 里, 与书名粘连)
站点装饰后缀 = (
    'TXT下载', 'txt下载', '免费全文', '全集最新列表', '最新章节',
    '全文阅读', '无弹窗', '全文', '完结', '精校版', '精校',
)

# 广告/水印行特征 (刻意最小化: 只滤掉会污染指纹的整行站点水印)
_广告模式 = re.compile(
    r'(本章未完|请收藏|最快更新|手机版阅读|无弹窗|全文免费阅读|'
    r'www\.|https?://|一秒记住|笔趣|天才一秒|记住本站|请记住本书)'
)
_句界 = re.compile(r'[。！？…；!?;]+')
_非正文 = re.compile(r'[^\u4e00-\u9fffA-Za-z0-9]+')
_括号 = re.compile(r'[（(][^）)]*[）)]')
_空白 = re.compile(r'[\s_\-]+')

# ---------------------------------------------------------------- 清单常量
清单文件名 = '去重清单.json'
_清单版本 = 1
_清单上限 = 200
_锁 = threading.RLock()

状态_待确认 = '待确认'
状态_已清理 = '已清理'
状态_已忽略 = '已忽略'
状态集合 = (状态_待确认, 状态_已清理, 状态_已忽略)

隔离目录名 = '_已去重'


# ================================================================ 指纹与判定
def 归一化标题(文件名: str) -> str:
    """去扩展名 + 去括号内容 + 去站点装饰后缀 + 去空白。仅作粗筛。"""
    名 = 文件名[:-4] if 文件名.lower().endswith('.txt') else 文件名
    名 = _括号.sub('', 名)
    for 后缀 in 站点装饰后缀:
        名 = 名.replace(后缀, '')
    return _空白.sub('', 名)


def 读指纹(路径: str) -> tuple:
    """读一个正文文件 → (句子指纹集合, 归一化正文字数)。

    句子是分章/分段的**不变量**: 站点把同一段文字切成 40 章还是 56 章,
    句子的文本都不变, 因此本指纹对"章节切法不同"完全免疫。
    """
    集 = set()
    字数 = 0
    try:
        with open(路径, 'r', encoding='utf-8', errors='replace') as f:
            原文 = f.read()
    except OSError as e:
        _log.info(f"读取失败, 按空指纹处理: {os.path.basename(路径)} "
                  f"{type(e).__name__}: {e}")
        return 集, 字数

    有效行 = [ln for ln in 原文.splitlines() if ln.strip() and not _广告模式.search(ln)]
    for 句 in _句界.split('\n'.join(有效行)):
        净 = _非正文.sub('', 句)
        if len(净) < 句长下限:
            continue
        字数 += len(净)
        集.add(zlib.crc32(净.encode('utf-8')))
    return 集, 字数


def 相似度(甲: dict, 乙: dict) -> dict:
    """三个指标的原始计算 (甲/乙 为 扫描() 的条目)。"""
    集甲, 集乙 = 甲['句集'], 乙['句集']
    if not 集甲 or not 集乙:
        return {'Jaccard': 0.0, '含甲于乙': 0.0, '含乙于甲': 0.0, '交集': 0}
    交 = len(集甲 & 集乙)
    if 交 == 0:
        return {'Jaccard': 0.0, '含甲于乙': 0.0, '含乙于甲': 0.0, '交集': 0}
    并 = len(集甲) + len(集乙) - 交
    return {
        'Jaccard': 交 / 并,
        '含甲于乙': 交 / len(集甲),   # 甲有多少比例出现在乙里
        '含乙于甲': 交 / len(集乙),
        '交集': 交,
    }


def 判定对(甲: dict, 乙: dict) -> dict:
    """判定一对文件的关系, 并给出保留建议。

    返回 {'判定', '指标', '保留', '删除', '理由'} —— 判定为 不同 时
    保留/删除 均为 None (不该动)。
    """
    指 = 相似度(甲, 乙)
    标题甲, 标题乙 = 归一化标题(甲['名']), 归一化标题(乙['名'])
    同前缀 = bool(标题甲 and 标题乙 and
                  (标题甲 in 标题乙 or 标题乙 in 标题甲) and
                  min(len(标题甲), len(标题乙)) >= 2)

    # 保留更全的那份 (以归一化正文字数为准, 不看字节数/章数)
    更全, 更少 = (甲, 乙) if 甲['字数'] >= 乙['字数'] else (乙, 甲)

    if 指['Jaccard'] >= 阈值_Jaccard_同一本:
        return {'判定': 判定_同一本, '指标': 指, '保留': 更全, '删除': 更少,
                '理由': f"句子集合 Jaccard={指['Jaccard']:.3f} ≥ {阈值_Jaccard_同一本}，"
                        f"两份正文基本一致"}

    最大包含 = max(指['含甲于乙'], 指['含乙于甲'])
    if 指['Jaccard'] >= 阈值_Jaccard_灰区 or 最大包含 >= 阈值_包含度_灰区:
        子集侧 = None
        if 最大包含 >= 阈值_包含度_子集:
            子集侧 = 乙 if 指['含甲于乙'] >= 指['含乙于甲'] else 甲
        提示 = (f"疑似同一本但含差异（Jaccard={指['Jaccard']:.3f}，"
                f"最大包含度={最大包含:.3f}）")
        if 子集侧 is not None:
            提示 = (f"一份是另一份的真子集（包含度={最大包含:.3f} ≥ {阈值_包含度_子集}）")
        return {'判定': 判定_灰区 if 子集侧 is None else 判定_子集,
                '指标': 指, '保留': 更全, '删除': 更少, '理由': 提示}

    if 同前缀 and 最大包含 >= 阈值_Jaccard_灰区:
        return {'判定': 判定_灰区, '指标': 指, '保留': 更全, '删除': 更少,
                '理由': f"标题同前缀且包含度={最大包含:.3f}，疑似同书不同站源的文本，"
                        f"差异较大需人工确认"}

    return {'判定': 判定_不同, '指标': 指, '保留': None, '删除': None, '理由': ''}


def 扫描(目录: str) -> list:
    """扫描目录下的正文文件 → [{'路径','名','字数','句集','字节'}]。

    排除: 非 .txt、质检报告 (`.质检报告.txt`)、子目录。
    """
    条目 = []
    if not os.path.isdir(目录):
        return 条目
    for 名 in sorted(os.listdir(目录)):
        if not 名.lower().endswith('.txt') or 名.endswith('.质检报告.txt'):
            continue
        路径 = os.path.join(目录, 名)
        if not os.path.isfile(路径):
            continue
        集, 字数 = 读指纹(路径)
        条目.append({'路径': 路径, '名': 名, '字数': 字数, '句集': 集,
                     '字节': os.path.getsize(路径)})
    return 条目


def _并查集_合并(父: dict, 甲: str, 乙: str) -> None:
    def 根(x):
        while 父[x] != x:
            父[x] = 父[父[x]]
            x = 父[x]
        return x
    a, b = 根(甲), 根(乙)
    if a != b:
        父[b] = a


def 分组(条目列表: list) -> list:
    """把条目聚成重复组, 每组给出保留建议。

    用并查集连通判定非「不同」的对, 再**用代表项复核**: 与代表项够不上
    灰区的成员会被剔出独立成组 —— 防连通性的链式传染把无关的书串进来。
    """
    if len(条目列表) < 2:
        return []
    父 = {e['路径']: e['路径'] for e in 条目列表}
    对结果 = {}
    for i in range(len(条目列表)):
        for j in range(i + 1, len(条目列表)):
            甲, 乙 = 条目列表[i], 条目列表[j]
            比 = 甲['字数'] / 乙['字数'] if min(甲['字数'], 乙['字数']) else 0
            if 比 and 比 < 最小字数比:
                # 字数悬殊: 跳过昂贵的内容比对, 但仍看标题同前缀 (便宜)
                标题甲, 标题乙 = 归一化标题(甲['名']), 归一化标题(乙['名'])
                if not (标题甲 and 标题乙 and
                        (标题甲 in 标题乙 or 标题乙 in 标题甲)):
                    continue
            r = 判定对(甲, 乙)
            if r['判定'] != 判定_不同:
                对结果[(甲['路径'], 乙['路径'])] = r
                _并查集_合并(父, 甲['路径'], 乙['路径'])

    桶 = {}
    for e in 条目列表:
        桶.setdefault(父[e['路径']], []).append(e)

    组 = []
    for _, 成员 in 桶.items():
        if len(成员) < 2:
            continue
        成员.sort(key=lambda x: x['字数'], reverse=True)
        代表 = 成员[0]
        组.append(_成组(代表, 成员, 对结果))
    return 组


def _成组(代表: dict, 成员: list, 对结果: dict) -> dict:
    """给一个桶定组信息: 与代表项够不上灰区的成员剔出, 另立单元素 (不成组)。"""
    保留集 = [代表]
    剔除 = []
    for 其他 in 成员[1:]:
        键 = (代表['路径'], 其他['路径']) if (代表['路径'], 其他['路径']) in 对结果 \
            else (其他['路径'], 代表['路径'])
        r = 对结果.get(键)
        if r is None:
            # 同桶但没直接比过 (链式) → 现算一次复核
            r = 判定对(代表, 其他)
        if r['判定'] == 判定_不同:
            剔除.append(其他)
        else:
            保留集.append(其他)

    可自动, 待确认 = [], []
    for 其他 in 保留集[1:]:
        键 = (代表['路径'], 其他['路径']) if (代表['路径'], 其他['路径']) in 对结果 \
            else (其他['路径'], 代表['路径'])
        r = 对结果.get(键) or 判定对(代表, 其他)
        项 = {'路径': 其他['路径'], '名': 其他['名'], '字数': 其他['字数'],
              '字节': 其他['字节'], '判定': r['判定'], '理由': r['理由'],
              '指标': r['指标']}
        (可自动 if r['判定'] in (判定_同一本, 判定_子集) else 待确认).append(项)

    全部 = [{'路径': 代表['路径'], '名': 代表['名'], '字数': 代表['字数'],
             '字节': 代表['字节']}]
    return {
        '键': 组键(代表['路径']),
        '代表': 全部[0],
        '可自动清理': 可自动,
        '待确认': 待确认,
        '剔除': [{'名': x['名'], '路径': x['路径']} for x in 剔除],
        '组成员数': len(保留集),
    }


def 组键(路径: str) -> str:
    return hashlib.sha1(os.path.abspath(路径).encode('utf-8')).hexdigest()[:12]


def 扫描重复(目录: str = None) -> list:
    """扫描并返回重复组 (按可清理文件数降序)。目录为 None → 默认输出目录。"""
    if 目录 is None:
        from _path_utils import get_default_output_dir
        目录 = get_default_output_dir()
    条目 = 扫描(目录)
    if len(条目) < 2:
        _log.info(f"[去重] {目录} 正文不足 2 个, 无需比对")
        return []
    开始 = time.time()
    组 = 分组(条目)
    _log.info(f"[去重] 扫描 {len(条目)} 个正文, 得 {len(组)} 个重复组, "
              f"耗时 {time.time() - 开始:.1f}s")
    return 组


# ================================================================ 清单存储
def 清单路径() -> str:
    from _path_utils import get_state_root
    return os.path.join(get_state_root(), '数据', 清单文件名)


def 载入() -> list:
    """读去重清单; 缺失/损坏 → [] (绝不抛)。"""
    try:
        with open(清单路径(), 'r', encoding='utf-8') as f:
            数据 = json.load(f)
        记录 = 数据.get('记录') if isinstance(数据, dict) else None
        return [r for r in 记录 if isinstance(r, dict)] if isinstance(记录, list) else []
    except FileNotFoundError:
        return []
    except Exception as e:
        _log.info(f"去重清单读取失败 (按空清单处理): {type(e).__name__}: {e}")
        return []


def 保存(记录列表: list) -> bool:
    """原子写去重清单 (锁内快照 → 锁外 IO; tmp 名带 pid+tid 防并发截断)。"""
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
        _log.debug(f'裸 except 吞异常: {type(e).__name__}: {e} (去重清单落盘失败)')
        return False


def _裁剪(记录列表: list) -> list:
    """上限裁剪: 待确认 (待用户处置) 优先全留, 其余留**最近的**, 总量不超上限。

    ⚠️ 注意与 死书处理._裁剪 的区别: 旧实现算的是 `额度 = len(记录) - 上限`
    (超出量), 结果超限时只留下"超出量"条 —— 例如 220 条全为已结时只返回 20 条,
    **近乎清空清单**。这里改为 `额度 = 上限 - len(活跃)` (还能再装多少条已结),
    语义正确且总长为 min(len(记录), 上限)。
    """
    if len(记录列表) <= _清单上限:
        return 记录列表
    活跃 = [r for r in 记录列表 if r.get('状态') == 状态_待确认]
    已结 = [r for r in 记录列表 if r.get('状态') != 状态_待确认]
    if len(活跃) >= _清单上限:
        # 待确认项本身就超限: 只留最近的, 否则会把清单撑爆
        return sorted(活跃, key=lambda x: x.get('最近时间', ''))[-_清单上限:]
    额度 = _清单上限 - len(活跃)
    保留已结 = sorted(已结, key=lambda x: x.get('最近时间', ''))[-额度:] if 额度 > 0 else []
    return 活跃 + 保留已结


def 写出清单(组列表: list) -> int:
    """把扫描结果并入清单 (同键更新, 已处理过的不倒退)。返回清单条数。"""
    现有 = {r.get('键'): r for r in 载入()}
    现在 = time.strftime('%Y-%m-%d %H:%M')
    for 组 in 组列表:
        旧 = 现有.get(组['键'])
        项 = {
            '键': 组['键'],
            '代表': 组['代表'],
            '可自动清理': 组['可自动清理'],
            '待确认': 组['待确认'],
            '状态': 状态_待确认,
            '最近时间': 现在,
            '次数': (旧.get('次数', 0) + 1) if 旧 else 1,
            '首次时间': 旧.get('首次时间', 现在) if 旧 else 现在,
        }
        # 用户已处置过的组如何继承状态 (2026-10-07 修):
        #   已忽略 → 一直保持 (用户明确说"别再管这组"), 新重复也不打扰
        #   已清理 → **仅当它现在已经没有待办项**才保持; 若又出现新的可清理/待确认项,
        #            退回 待确认 —— 否则新冒出来的重复会被静默忽略 (旧实现有这个洞)
        还有待办 = bool(项['可自动清理'] or 项['待确认'])
        if 旧 and 旧.get('状态') == 状态_已忽略:
            项['状态'] = 状态_已忽略
        elif 旧 and 旧.get('状态') == 状态_已清理 and not 还有待办:
            项['状态'] = 状态_已清理
        现有[组['键']] = 项
    记录 = _裁剪(list(现有.values()))
    保存(记录)
    return len(记录)


def 列出(状态: str = '') -> list:
    """列出清单条目 (可按状态过滤)。"""
    记录 = 载入()
    if 状态:
        记录 = [r for r in 记录 if r.get('状态') == 状态]
    return 记录


def 设状态(键: str, 状态: str) -> bool:
    if 状态 not in 状态集合:
        _log.info(f"[去重] 非法状态被拒: {状态!r}")
        return False
    记录 = 载入()
    命中 = False
    for r in 记录:
        if r.get('键') == 键:
            r['状态'] = 状态
            r['最近时间'] = time.strftime('%Y-%m-%d %H:%M')
            命中 = True
    return 保存(记录) if 命中 else False


def 移除记录(键: str) -> bool:
    记录 = 载入()
    新 = [r for r in 记录 if r.get('键') != 键]
    if len(新) == len(记录):
        return False
    return 保存(新)


# ================================================================ 清理编排
def _隔离路径(隔离目录: str, 名: str) -> str:
    """隔离目录内的不重名目标 (同名时加序号, 绝不覆盖)。"""
    目标 = os.path.join(隔离目录, 名)
    if not os.path.exists(目标):
        return 目标
    主, 扩 = os.path.splitext(名)
    for i in range(1, 10000):
        候选 = os.path.join(隔离目录, f"{主}({i}){扩}")
        if not os.path.exists(候选):
            return 候选
    return os.path.join(隔离目录, f"{主}.{int(time.time())}{扩}")


def 执行清理(键: str, 模式: str = '隔离', 隔离目录: str = None,
             额外确认项: list = None) -> dict:
    """执行一个重复组的清理。**必须由用户确认后调用**。

    参数:
      模式          '隔离' (默认, 可反悔) → 移入 `<结果目录>/_已去重/`
                    '删除' (不可逆)       → 直接删
      额外确认项    用户**显式点名批准**的「待确认」(灰区) 项文件名列表。
                    None/空 = 只清理 `可自动清理` 项 —— 默认最安全。
                    灰区项相似度不够高, 代码不替用户判断, 必须逐个点名批准
                    (2026-10-07 补: 此前灰区项即便人工批准也无任何代码路径可处理)。

    返回 {'清理': [名...], '失败': [(名, 原因)...], '模式', '隔离目录'}
    """
    记录 = None
    for r in 载入():
        if r.get('键') == 键:
            记录 = r
            break
    if 记录 is None:
        return {'清理': [], '失败': [('', '清单中无此键')], '模式': 模式, '隔离目录': ''}

    待删 = list(记录.get('可自动清理') or [])
    if 额外确认项:
        允许 = {str(x) for x in 额外确认项}
        待删 += [x for x in (记录.get('待确认') or [])
                 if (x.get('名') or '') in 允许]
    if not 待删:
        return {'清理': [], '失败': [('', '该组无可自动清理项 (灰区项需用 额外确认项 点名批准)')],
                '模式': 模式, '隔离目录': ''}

    代表路径 = (记录.get('代表') or {}).get('路径') or ''
    基线 = os.path.dirname(os.path.abspath(代表路径)) if 代表路径 else None
    if 隔离目录 is None:
        隔离目录 = os.path.join(基线, 隔离目录名) if 基线 else ''
    if 模式 == '隔离':
        if not 隔离目录:
            return {'清理': [], '失败': [('', '无法确定隔离目录')],
                    '模式': 模式, '隔离目录': ''}
        try:
            os.makedirs(隔离目录, exist_ok=True)
        except OSError as e:
            return {'清理': [], '失败': [('', f'建隔离目录失败: {type(e).__name__}')],
                    '模式': 模式, '隔离目录': 隔离目录}

    已清理, 失败 = [], []
    for 项 in 待删:
        源 = 项.get('路径') or ''
        名 = 项.get('名') or os.path.basename(源)
        if not 源 or not os.path.isfile(源):
            失败.append((名, '源文件不存在'))
            continue
        # 安全: 绝不跨目录/不碰代表项
        if 基线 and os.path.dirname(os.path.abspath(源)) != 基线:
            _log.info(f"[去重] 拒绝越界删除: {源}")
            失败.append((名, '不在结果目录内, 拒绝操作'))
            continue
        if 代表路径 and os.path.abspath(源) == os.path.abspath(代表路径):
            _log.info(f"[去重] 拒绝删除代表项: {源}")
            失败.append((名, '是保留项, 拒绝操作'))
            continue
        try:
            if 模式 == '隔离':
                shutil.move(源, _隔离路径(隔离目录, 名))
            else:
                os.remove(源)
            已清理.append(名)
        except OSError as e:
            _log.info(f"[去重] 清理失败 {名}: {type(e).__name__}: {e}")
            失败.append((名, f'{type(e).__name__}: {e}'))

    if 已清理:
        设状态(键, 状态_已清理)
    return {'清理': 已清理, '失败': 失败, '模式': 模式, '隔离目录': 隔离目录}
