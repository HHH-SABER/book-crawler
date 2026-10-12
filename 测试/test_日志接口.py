# -*- coding: utf-8 -*-
"""日志接口守卫 (2026-10-12)。

**实测事故**: `爬虫.py` 两处写了 `_log.warning(_折叠)` —— 而项目的 `BoundLogger`
只暴露 `debug/info/warn/error/error_exc`, **没有 `warning`**, 也没有 `__getattr__` 兜底
⇒ 直接 `AttributeError: 'BoundLogger' object has no attribute 'warning'` ⇒
整个抓取任务以"任务异常"崩掉。真机全站测试在"目录解析折叠站"那条分支上抓到
(且被测站点恰好会走到该分支)。

本文件守两件事:
  ① `BoundLogger` 暴露**标准 logging 方法名** (warning/critical 别名), 两种写法都能用;
  ② **通用守卫**: 扫 `源码/` 下所有 `_log.<方法>(` / `日志.<方法>(` 调用, 断言方法名
     确实是 logger 提供的 —— 这样任何拼错的日志方法名都会被门禁拦下, 不必再靠真机撞。

运行方式 (项目根目录):
    python -m unittest discover -s 测试 -v
"""
import re
import sys
import unittest
from pathlib import Path

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

import 日志 as L                 # noqa: E402

# logger 允许被调用的方法名白名单 (改 logger 接口时同步这里)
_L = L.get('守卫')
允许 = sorted(m for m in dir(_L) if not m.startswith('_')) + \
      ['debug', 'info', 'warn', 'warning', 'error', 'critical', 'error_exc']
允许 = sorted(set(允许))


class Test标准logging方法名可用(unittest.TestCase):

    def test_warning与critical别名存在(self):
        """`warning` 是绝大多数人的肌肉记忆 —— 必须有别名, 否则 AttributeError 崩任务。"""
        for 名 in ('warning', 'critical'):
            self.assertTrue(callable(getattr(_L, 名, None)),
                            f'BoundLogger 缺 {名}() (实测曾因此崩掉整个抓取任务)')
            self.assertTrue(callable(getattr(L, 名, None)),
                            f'模块级 日志.{名}() 也应存在')

    def test_warning实际可调用不抛(self):
        """真调一次 (写进沙箱日志目录), 确认不抛。"""
        _L.warning('日志接口守卫自测: warning 别名可用')
        _L.critical('日志接口守卫自测: critical 别名可用')

    def test_项目原有方法仍在(self):
        for 名 in ('debug', 'info', 'warn', 'error', 'error_exc'):
            self.assertTrue(callable(getattr(_L, 名, None)), f'缺 {名}()')


class Test全仓日志调用点方法名合法(unittest.TestCase):
    """⚠️ 通用守卫: 把"日志方法名拼错"这类崩溃挡在门禁里, 而不是等真机撞。

    口径要点 (首版写太宽, 把 `日志.get(...)`/`日志.close()` 这类**模块级 API** 也报了):
    只查**绑定到 `日志.get()` 的实例变量** (项目惯例 `_log = 日志.get('模块名')`),
    对它们做 `实例.<方法>(` 的方法名白名单校验。
    """

    _绑定 = re.compile(r'^\s*(\w+)\s*=\s*日志\.(?:get|BoundLogger)\s*\(')

    def _实例名(self, 源码行s):
        名s = {'_log'}                       # 项目主流惯例, 无条件纳入
        for 行 in 源码行s:
            m = self._绑定.match(行)
            if m:
                名s.add(m.group(1))
        return 名s

    def test_所有_log调用点的方法名都合法(self):
        坏 = []
        检查文件 = 0
        for f in sorted((_根 / '源码').rglob('*.py')):
            if 'rust_core' in str(f):
                continue
            行s = f.read_text(encoding='utf-8', errors='replace').splitlines()
            实例名 = self._实例名(行s)
            模式 = re.compile(r'\b(' + '|'.join(re.escape(x) for x in 实例名)
                            + r')\.([A-Za-z_][A-Za-z0-9_]*)\s*\(')
            检查文件 += 1
            for i, 行 in enumerate(行s, 1):
                去注释 = 行.split('#', 1)[0]
                for m in 模式.finditer(去注释):
                    名 = m.group(2)
                    if 名 not in 允许 and 名 not in ('get', 'close', 'install_global_excepthook',
                                                'enable_console', '注册镜像回调', '取镜像回调',
                                                'is_console_enabled', 'set_level'):
                        坏.append(f'{f.relative_to(_根)}:{i} → {m.group(1)}.{名}()')
        self.assertGreater(检查文件, 20, '扫到的文件太少, 守卫可能没生效')
        self.assertEqual(
            坏, [],
            '日志调用用了 logger 没有的方法 (会 AttributeError 崩任务): ' + '; '.join(坏))


if __name__ == '__main__':
    unittest.main(verbosity=2)
