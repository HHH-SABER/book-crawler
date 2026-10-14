# -*- coding: utf-8 -*-
"""目录链接判定工具 (2026-10-14 阶段二从 爬虫.py 拆出, 纯函数零行为变化)。

拆分原则: **原样搬迁 + 显式 import 桥接** —— 爬虫.py 删除本组定义,
`from 目录链接工具 import (...)` 引入, 全部既有调用点与测试导入路径不变。

为什么先拆这组: 它们是"链接收集"的判定核心 (非章节页/章节链接/站点正则),
纯函数、无实例状态依赖, 是爬虫.py 里边界最清晰、风险最低的第一刀。
拆分验证: 脚本/解析基线.py --对比 必须与入库基线一致。
"""
import re

try:
    from 日志 import get as _取日志
    _log = _取日志('目录链接工具')
except Exception:
    import logging
    _log = logging.getLogger('目录链接工具')


def _非章节页名() -> tuple:
    """目录页里"看着像章节、其实是导航/功能区"的链接特征 (2026-10-08 实网取证)。

    实网: <站点> 的「[寻找更多新章] -> /<书号>/liked.html」通过了 `novel_path in href`
    过滤被当成章节抓 → **正文为空、质检 0 分, 还占掉一个章节号**, 于是
    "抓取失败章节号 (1): [1]" 这种误导性报告就出来了 (实抓日志逐字可见)。

    只收**确定不是章节**的页名, 不用"必须纯数字"这类激进规则 —— 后者会误伤
    `chapter-123.html` / 拼音 slug 等正当写法。
    """
    return ('/ch1.html', '/dx1.html', '/index.html', '/indexlist.html',
            '/liked.html', '/bookcase.html', '/comment.html', '/about.html')


def _是非章节链接(href: str, 含index前缀: bool = False) -> bool:
    """统一收口: 该链接是否为"非章节页"(目录/书架/评论/关于/首页列表等)。

    2026-10-10 (E1): 原先 3 处各写一遍 `any(k in href for k in _非章节页名())`,
    其中一处还额外拼了 `['/index_']` —— 改词表时容易漏改一处, 口径会漂移
    (实测就漏过一次: `liked.html` 曾从某个选择器分支被当章节抓)。
    """
    if any(k in href for k in _非章节页名()):
        return True
    return bool(含index前缀 and '/index_' in href)


def _章节链接合正则(href: str, 站点正则: str) -> bool:
    """站点表声明了 `chapter_url_regex` 时, 章节链接**必须**匹配它 (2026-10-13)。

    **为什么要它**: `chapter_url_regex` 在 `sites_config.py` 有文档、在站点管理页可编辑,
    但**爬虫从不读取**(实测全源码 0 处使用) ⇒ 这个字段一直是**死配置**: 站点明明声明了
    自己章节 URL 的形状, 通用筛选却只靠弱启发式(路径前缀 + 词表) ⇒ 目录页里的
    **导航位/外站链接**只要路径前缀凑得上, 就会被当章节收下。

    口径 (安全方向):
      - **未配置** → 一律放行 ⇒ 与改造前行为**完全一致** (18 个已配置站受益, 其余无变化);
      - 配了 → `re.search` 命中才放行;
      - 正则**写坏了** → 放行并留痕 (不能因为一个坏正则让整站抓不动)。
    """
    if not 站点正则:
        return True
    try:
        return bool(re.search(站点正则, href))
    except re.error as e:
        _log.warn(f"[目录解析] 站点表 chapter_url_regex 非法 ({e}), 本次放行: {站点正则[:40]}")
        return True
