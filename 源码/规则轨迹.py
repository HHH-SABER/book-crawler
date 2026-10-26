# -*- coding: utf-8 -*-
"""规则轨迹：把"站点策略分发"的运行时决策记成可比对的只读快照（S1 第二步，2026-10-26）。

## 为什么需要它

S1（规则内核）的目标是"把 `爬虫.py` 的站点策略分发抽成 IR，再用**重放**证明等价"。
第一步已经能**静态**导出"阶段词汇 + 适配器声明"（`规则内核.py`），但静态表说明不了
"这次抓取，某个阶段到底走了哪条分支、传了什么、返回什么" —— 那才是重放要比对的东西。

本模块提供**记录器**：在 `sites_config.适配器策略()` 这个唯一公共入口上挂一个
**默认关闭、开启后零副作用**的探针，把每次分发记成一条确定性记录：

    {'序号': 1, '阶段': '专属选择器', '主机指纹': 'a1b2c3d4e5f6',
     '命中适配器': True, '返回摘要': 'dict(2)', '上下文键': ['soup']}

## 三条硬约束（都是踩过的坑）

1. **默认关闭、关闭时零开销零行为变化** —— 开关是模块级布尔，关闭时只多一次函数调用；
2. **确定性**：上下文只记**排序后的键名**、返回值只记**类型/长度摘要**、URL 只记主机指纹
   —— 任何随哈希随机化/字典序变化的量都不进快照（否则重放对比天天假红）；
3. **隐私**：真实域名/站点代号一律不落地，只存 `sha256(host)[:12]`；快照写 `.runtime/`
   （gitignored），**永不入库**。

## 用法

    import 规则轨迹
    规则轨迹.清空(); 规则轨迹.启用()
    ... 跑一遍要观察的链路 ...
    规则轨迹.停用()
    快照 = 规则轨迹.快照()      # 可直接 json.dumps 比对

命令行入口见 `脚本/规则轨迹.py`（`--写` / `--对比` / `--自检`）。
"""
import hashlib
from urllib.parse import urlsplit

_启用 = False
_记录 = []
_序号 = 0


def 启用() -> None:
    global _启用
    _启用 = True


def 停用() -> None:
    global _启用
    _启用 = False


def 启用中() -> bool:
    return _启用


def 清空() -> None:
    global _序号
    _记录.clear()
    _序号 = 0


def 主机指纹(url: str) -> str:
    """只保留主机名的不可逆指纹（隐私：真实域名绝不落地）。"""
    try:
        主机 = urlsplit(url or '').hostname or ''
    except ValueError:
        主机 = ''
    if not 主机:
        return ''
    return hashlib.sha256(主机.encode('utf-8')).hexdigest()[:12]


def _摘要(值) -> str:
    """返回值摘要：只记类型与规模，不记内容（保证确定性与隐私）。"""
    if 值 is None:
        return 'None'
    if isinstance(值, bool):
        return 'True' if 值 else 'False'
    if isinstance(值, (int, float)):
        return f'{type(值).__name__}({值})'
    if isinstance(值, str):
        return f'str({len(值)})'
    if isinstance(值, dict):
        return f'dict({len(值)})'
    if isinstance(值, (list, tuple, set, frozenset)):
        return f'{type(值).__name__}({len(值)})'
    return type(值).__name__


def 记录(阶段: str, url: str, 命中: bool, 结果=None, 异常=None, 上下文=None) -> None:
    """记一条分发决策（仅在 `启用中()` 时由调用方调用）。

    Args:
        阶段: 分发阶段名（如 `'专属选择器'`）
        url: 当次 URL（只取主机指纹）
        命中: 是否命中适配器且实现了该阶段
        结果: 钩子返回值（只记摘要）
        异常: 钩子/适配器抛出的异常实例（只记类型名）
        上下文: 传入的上下文 dict（只记排序后的键名）
    """
    global _序号
    _序号 += 1
    _记录.append({
        '序号': _序号,
        '阶段': str(阶段),
        '主机指纹': 主机指纹(url),
        '命中适配器': bool(命中),
        '返回摘要': ('异常:' + type(异常).__name__) if 异常 is not None else _摘要(结果),
        '上下文键': sorted(str(k) for k in (上下文 or {})),
    })


def 取记录() -> list:
    """返回记录列表的浅拷贝（防止外部原地改坏）。"""
    return list(_记录)


def 快照() -> dict:
    """可直接 JSON 序列化、可逐字节比对的快照。"""
    return {'记录数': len(_记录), '记录': 取记录()}


版本 = 1


def 生成元信息(样本数=None, head=None) -> dict:
    """快照元信息（工具版本 / 生成时间 / HEAD / 样本数）。

    元信息**不参与**轨迹比对（生成时间每次都不同），只用于"这条快照是不是过期了"的判断。
    """
    import time
    return {
        '工具版本': 版本,
        '生成时间': time.strftime('%Y-%m-%d %H:%M:%S'),
        'HEAD': str(head or ''),
        '样本数': dict(样本数 or {}),
    }


def 对比快照(旧: dict, 新: dict) -> list:
    """逐条比对两份快照的**轨迹**（忽略元信息），返回人类可读差异（空 = 一致）。

    兼容历史格式：缺 `轨迹` / `记录` 的旧快照不会抛异常，只报"条数变化"。
    """
    差 = []
    旧轨 = ((旧 or {}).get('轨迹') or {}).get('记录') or []
    新轨 = ((新 or {}).get('轨迹') or {}).get('记录') or []
    if len(旧轨) != len(新轨):
        差.append(f'记录条数变化: {len(旧轨)} → {len(新轨)}')
    for i in range(min(len(旧轨), len(新轨))):
        a, b = 旧轨[i], 新轨[i]
        键s = [k for k in ('阶段', '主机指纹', '命中适配器', '返回摘要', '上下文键')
              if a.get(k) != b.get(k)]
        if 键s:
            差.append(f'第 {i + 1} 条差异 {键s}: 旧={ {k: a.get(k) for k in 键s} }'
                     f' 新={ {k: b.get(k) for k in 键s} }')
    return 差[:20]

