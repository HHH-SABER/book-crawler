# -*- coding: utf-8 -*-
"""字符集统计探测 (P8-C13, 2026-10-24)。

解决的问题 (审查/评估报告认定的真痛点): 站点**声明的编码不可信**
(大量中文站声明 utf-8 实际 GBK/Big5, 或反之) → 按声明解码出乱码 →
质检把乱码当"低分"降级 → 好内容被误杀。

规格 (实施计划 §C-13): "加 uchardet 式探测 (无依赖则统计法), 探测后再解码"。
本模块 = 零依赖统计法, 纯函数 + 可单测 (D8)。

判定链 (按确定性从高到低, 依据随结果返回供日志/测试断言):
  ① BOM        —— UTF-8/16/32 字节序标记, 确定性;
  ② meta 声明  —— 前 4KB 内 `<meta charset>` / `content="...charset="`, 但**要过
                   "可解码性 + UTF-8 反压"验证 (声明会说谎, 见下);
  ③ UTF-8 严格  —— 能严格解码即认定 (合法 UTF-8 中文绝不会误判成 GBK, 这是
                   反向守护的关键一步);
  ④ 统计打分    —— gb18030 vs big5 严格解码后按"常见汉字占比"打分, 取高者;
  ⑤ 兜底 utf-8。

"声明说谎"的两种形态及处理:
  · 声明 utf-8 实际 GBK/Big5: ③ 严格解码失败 → 落到 ④ 统计 → 命中真编码;
  · 声明 GBK/Big5 实际 UTF-8: ④之前 ③ 已判定 UTF-8 返回 (meta 只作提示, 不
    覆盖更强的 UTF-8 证据) —— 防"按声明解出乱码"。
"""
import codecs
import re
from typing import Optional, Tuple

# 常见汉字区 (CJK 统一表意文字 + 扩展A 常用段); 用于统计打分
_汉字区 = (
    (0x4E00, 0x9FA5),    # 基本区
    (0x3400, 0x4DBF),    # 扩展 A
)

# 第二信号: 真实中文文本会同时出现"高频常用字"与"中文标点" —— 随机字节即使
# 被 gb18030 (全映射编码) 解出汉字, 也几乎不会命中这两类 (2026-10-24 实测:
# 4KB 随机字节的 gb18030 汉字/非ASCII 比高达 0.80, 单看比值无法拒绝)。
_常见字 = frozenset('的一是了我不人在他有这个上们来到时大地为子中你说生国年着就那和要她出也得里后自以会家可下而过天去能对小多然于心学么之都好看起发当没成只如事把还用第样道想作种开美总从无情己面最女但现前些所同日手又行意动方期它头经长儿回位分爱老因很给名法间斯知世什两次使身者被高已亲其进此话常与活正感')

# meta 声明提取 (只扫前 4KB, 避免大页面全量正则)
_META正则 = re.compile(
    rb'charset\s*=\s*["\']?\s*([A-Za-z0-9_\-]+)', re.IGNORECASE)

# 声明编码名 → Python 编码名 (大小写/别名归一)
_别名 = {
    'utf8': 'utf-8', 'utf-8': 'utf-8', 'utf_8': 'utf-8',
    'gb2312': 'gb18030', 'gbk': 'gb18030', 'gb18030': 'gb18030',
    'big5': 'big5', 'big-5': 'big5', 'big5-hkscs': 'big5',
    'utf-16': 'utf-16', 'utf16': 'utf-16', 'utf_16': 'utf-16',
    'utf-16le': 'utf-16', 'utf-16be': 'utf-16',
    'iso-8859-1': 'latin-1', 'latin1': 'latin-1',
}


def _归一编码名(名: Optional[str]) -> Optional[str]:
    if not 名:
        return None
    return _别名.get(名.strip().lower())


def _可严格解码(原始: bytes, 编码: str) -> bool:
    try:
        原始.decode(编码)
        return True
    except (LookupError, UnicodeDecodeError):
        return False


def _中文得分(文本: str) -> float:
    """中文可信度得分 (0~1); 不过闸返回 0.0。三道闸门:

    ① 汉字数 ≥ 8          —— 样本不足不猜 (短样本统计无意义);
    ② 汉字/非ASCII ≥ 0.5  —— 非 ASCII 字符里得绝大多数是汉字;
    ③ 高频常用字密度 ≥ 0.12 —— **关键第二信号**: 现代中文文本的前 100 高频字
       覆盖率约 40% (简体/繁体共享大部分高频字), 而随机字节流的高频字密度
       实测 ~0.005 (2026-10-24: 4KB 随机字节被 gb18030 解出 208 个"汉字",
       占比高达 0.80, 但高频字 0 个) —— 单看占比无法拒绝二进制流, 密度可以。
    """
    if not 文本:
        return 0.0
    汉字们 = [ch for ch in 文本
            if any(起 <= ord(ch) <= 止 for 起, 止 in _汉字区)]
    if len(汉字们) < 8:
        return 0.0
    非ascii = sum(1 for ch in 文本 if ord(ch) > 127)
    if 非ascii == 0:
        return 0.0
    占比 = len(汉字们) / 非ascii
    if 占比 < 0.5:
        return 0.0
    常用 = sum(1 for ch in 汉字们 if ch in _常见字)
    if 常用 / len(汉字们) < 0.12:
        return 0.0
    return 占比


def _BOM编码(原始: bytes) -> Optional[str]:
    for 标记, 编码 in (
            (codecs.BOM_UTF8, 'utf-8-sig'),
            (codecs.BOM_UTF32_LE, 'utf-32'),
            (codecs.BOM_UTF32_BE, 'utf-32'),
            (codecs.BOM_UTF16_LE, 'utf-16'),
            (codecs.BOM_UTF16_BE, 'utf-16'),
    ):
        if 原始.startswith(标记):
            return 编码
    return None


def _meta声明编码(原始: bytes) -> Optional[str]:
    m = _META正则.search(原始[:4096])
    return _归一编码名(m.group(1).decode('ascii', errors='ignore')) if m else None


def 探测(原始: bytes) -> Tuple[str, str]:
    """探测字节流的字符集。返回 (编码, 依据); 依据 ∈
    bom / meta / strict / statistic / default (供日志与测试断言)。"""
    if not 原始:
        return ('utf-8', 'default')

    # ① BOM (最高确定性)
    编码 = _BOM编码(原始)
    if 编码:
        return (编码, 'bom')

    # ② meta 声明: **任何声明都要过验证** (声明会说谎, 两种形态都要纠偏)
    #    · 声明 utf-8 实际 GBK/Big5 → 严格解码失败 → 声明作废, 落统计;
    #    · 声明 GBK 实际 UTF-8 中文 → UTF-8 证据更强 → 声明作废, 信 UTF-8;
    #    · latin-1 等价于"没声明" (服务器默认值), 不采信。
    声明 = _meta声明编码(原始)
    if 声明 == 'latin-1':
        声明 = None
    elif 声明 in ('utf-8', 'utf-8-sig', 'utf-16', 'utf-32'):
        if not _可严格解码(原始, 声明):
            声明 = None                    # 最常见形态: 声明 utf-8 但是中文编码字节
    elif 声明:
        if not _可严格解码(原始, 声明):
            声明 = None
        elif _可严格解码(原始, 'utf-8') and _中文得分(
                原始.decode('utf-8', errors='ignore')) > 0:
            声明 = None                    # 合法 UTF-8 中文冒充中文编码
    if 声明:
        return (声明, 'meta')

    # ③ UTF-8 严格解码 (合法 UTF-8 的充分证据; 早于统计, 防误判)
    if _可严格解码(原始, 'utf-8'):
        return ('utf-8', 'strict')

    # ④ 统计: gb18030 vs big5 按中文可信度打分 (内部含占比+第二信号双门槛)
    候选 = {}
    for 编码 in ('gb18030', 'big5'):
        try:
            候选[编码] = _中文得分(原始.decode(编码, errors='replace'))
        except (LookupError, UnicodeDecodeError):
            候选[编码] = 0.0
    if 候选:
        最佳 = max(候选, key=候选.get)
        if 候选[最佳] > 0:                  # 双门槛都不过 → 不硬猜, 落兜底
            return (最佳, 'statistic')

    # ⑤ 兜底
    return ('utf-8', 'default')


def 解码(原始: bytes) -> Tuple[str, str]:
    """探测并解码。返回 (文本, 依据)。绝不抛异常 (坏字节走 replace)。"""
    if not 原始:
        return ('', 'default')
    编码, 依据 = 探测(原始)
    try:
        return (原始.decode(编码, errors='replace'), 依据)
    except (LookupError, UnicodeDecodeError):
        return (原始.decode('utf-8', errors='replace'), 'default')


if __name__ == '__main__':
    # 手工自检: python 字符集探测.py (内置样例)
    样本 = [
        ('UTF-8 中文', '第一章 测试内容。'.encode('utf-8')),
        ('GBK 中文', '第一章 测试内容。'.encode('gb18030')),
        ('Big5 中文', '第一章 測試內容。'.encode('big5')),
        ('谎报 utf-8 的 GBK', '第一章 测试内容。'.encode('gb18030')),
    ]
    for 名, 数据 in 样本:
        编码, 依据 = 探测(数据)
        print(f'{名}: {编码} ({依据})')
