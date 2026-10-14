# -*- coding: utf-8 -*-
"""通用验证码接管路径的回归用例 (2026-10-12)。

**背景**: 进入验证码管理器的入口 `_solve_waf_captcha` 原先**只挂在
`站点匹配(url, 'siteT')` 分支**上, 且入口判定只认三个站点专属标记 ⇒
非 siteT 站点即使返回验证码页也**永远进不了管理器** ⇒ 用户打开的
"自动识别 / 失败转人工"对它们**形同虚设**(实测: 目标站映射为 siteI)。

本次把"是不是验证码页"抽成通用口径 `_像验证码页()`, 并在通用请求路径加了
`_尝试通用验证码接管()` 口子, 由 `_应主动接管验证码()` 闸门控制。

⚠️ 两条**刻意的设计边界**由本文件守着:
  ① **JS 挑战页(`ge_js_validator`/`window.location.reload`)不得**走验证码管理器 ——
     那类页面没有验证码图片可识别, 让管理器去试只会白烧 `auto_max_fail` 次数、
     最终误弹人工; 它们该走既有的 JS 令牌流程。
  ② **默认配置(自动识别全关)不得主动接管** —— 否则用户抓书会被莫名弹窗打断
     (合规默认 = 不主动开浏览器)。

运行方式 (项目根目录):
    python -m unittest discover -s 测试 -v
"""
import ast
import inspect
import sys
import unittest
from pathlib import Path

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

import 爬虫 as C                # noqa: E402
import captcha_module as CM     # noqa: E402

# 2026-10-14 批 4: inspect_page 实现移至 页面抓取.检查页面
_源码 = ((_根 / '源码' / '爬虫.py').read_text(encoding='utf-8')
         + '\n' + (_根 / '源码' / '页面抓取.py').read_text(encoding='utf-8'))


class Test像验证码页(unittest.TestCase):

    def test_传统标记命中(self):
        for 文本 in ('<html>访问频率太高</html>',
                    '<html>__wafcaptcha 请输入验证码</html>',
                    '<html><form id="_waform">…</form></html>'):
            with self.subTest(文本=文本[:30]):
                self.assertTrue(C._像验证码页(文本))

    def test_通用特征命中(self):
        self.assertTrue(C._像验证码页('<html>访问验证 请输入 check_code</html>'))

    def test_普通页面不命中(self):
        for 文本 in ('', None, '<html><body><a href="/1.html">第1章</a></body></html>',
                     '<html><title>小说目录</title></html>'):
            with self.subTest(文本=str(文本)[:30]):
                self.assertFalse(C._像验证码页(文本))

    def test_JS挑战页不得被判成验证码页(self):
        """⚠️ 设计边界①: JS 挑战(Kay 令牌)页没有验证码图片, 交给验证码管理器只会
        白烧 auto_max_fail 次数并误弹人工 ⇒ 必须**不**命中。"""
        for 文本 in ('<html><script>ge_js_validator</script></html>',
                     '<html>window.location.reload()</html>'):
            with self.subTest(文本=文本[:30]):
                self.assertFalse(C._像验证码页(文本),
                                 'JS 挑战页不该进验证码管理器 (应走 JS 令牌流程)')


class Test接管闸门(unittest.TestCase):

    def test_无管理器不接管(self):
        self.assertFalse(C._应主动接管验证码(None))

    def test_默认配置不接管(self):
        """⚠️ 设计边界②: 出厂默认自动识别全关 → 不得主动起浏览器接管。"""
        管理器, _ = _造管理器({})
        self.assertFalse(C._应主动接管验证码(管理器),
                         '默认配置下主动接管会莫名弹窗打断用户')

    def test_启用任一自动策略后接管(self):
        for 策略 in ('ddddocr', 'slider', 'third_party', 'point_click'):
            with self.subTest(策略=策略):
                管理器, _ = _造管理器({策略: True})
                self.assertTrue(C._应主动接管验证码(管理器))

    def test_异常配置不炸(self):
        class _坏:
            class config:                       # noqa: N801
                @staticmethod
                def strategy_enabled(n):
                    raise RuntimeError('坏配置')
        self.assertFalse(C._应主动接管验证码(_坏()))


def _造管理器(开关: dict):
    cfg = CM.Config()
    for n in ('ddddocr', 'slider', 'third_party', 'point_click'):
        cfg.data['strategies'][n]['enabled'] = bool(开关.get(n, False))
    return CM.CaptchaManager(config=cfg, monitor=CM.CaptchaMonitor()), cfg


class Test接线到位(unittest.TestCase):
    """防"改了但没接上": 结构守卫比行为断言更能防回归。"""

    def test_既有入口复用通用判定(self):
        段 = _方法源码('_solve_waf_captcha')
        self.assertIn('_像验证码页(', 段,
                      '_solve_waf_captcha 应改用 _像验证码页() 统一口径')
        self.assertNotIn("'__wafcaptcha' not in page_source", 段,
                         '旧的三个标记内联判定应已被替换')

    def test_通用请求路径接了接管口子(self):
        段 = _方法源码('检查页面')
        self.assertIn('_尝试通用验证码接管(', 段,
                      '通用请求路径应调用 _尝试通用验证码接管()')
        self.assertIn('_应主动接管验证码(', 段, '接管前必须过闸门')

    def test_接管方法存在且失败时返回None(self):
        self.assertTrue(callable(getattr(C.NovelSpider, '_尝试通用验证码接管', None)))
        源 = inspect.getsource(C.NovelSpider._尝试通用验证码接管)
        self.assertIn('return None', 源, '接管失败必须回退(None), 不得改变原结果')


def _方法源码(名: str) -> str:
    树 = ast.parse(_源码)
    for n in ast.walk(树):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == 名:
            return ast.get_source_segment(_源码, n) or ''
    raise AssertionError(f'找不到方法 {名}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
