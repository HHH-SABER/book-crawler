# -*- coding: utf-8 -*-
"""真实页面形态样本回归 (2026-10-13 新增, 公开侧)。

## 这批样本解决什么问题

此前"真机缺样本"是长期受阻项 (验证码页/折叠目录/分页目录都没有可用样本)。
真相是: **样本一直都在** (`测试样本_本地/` 的 57 份真实快照), 只是
(a) 在不入库目录, (b) 含真实域名与书名无法公开使用。

`脚本/脱敏样本.py` 把其中 7 份关键形态脱敏后放进 `测试/样本/`(入库), 于是
公开侧测试也能用**真实页面结构**做回归 —— 不再依赖合成样本。

## 脱敏的两道硬门禁 (由脚本在入库时强制, 测试侧再验一次)

① **红线**: 真实域名/站点代号/书名作者一律不残留 (域名→`siteN.example.com`,
   书名作者→`<NOVEL>`/`<AUTHOR>`);
② **判据行为不变**: 脱敏**不得**改动判据依赖的关键词
   (`访问验证`/`check_code` 是源码 `waf_captcha` 硬编码判据, 替换掉会让门失效),
   脱敏后判据结论必须与脱敏前一致。

## 形态覆盖

| 样本 | 形态 | 判据价值 |
|---|---|---|
| `tianqiu_目录` | 折叠目录(宣称远大于首页可见) | 折叠告警必须触发 |
| `siteg_访问验证页` | 验证页(带输入框的表单) | 两道门都必须命中 |
| `siteg_软封页` | 被拦截但非验证页 | 不得误判成验证码 |
| `washai_目录` / `_第22页` | 分页目录 首页/末页 | 通用路径只拿得到首页 ⇒ 应告警 |
| `siteq_目录_真实页` | 完整大目录(宣称≈实际) | 不得误告警 |
| `siteq_content` | 键盘翻页章节页 | 章节正文形态 |

运行: python -m unittest discover -s 测试
"""
import re
import sys
import unittest
from pathlib import Path

_根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_根 / '源码'))

_样本 = _根 / '测试' / '样本'
_必在 = ('tianqiu_目录.html', 'siteg_访问验证页.html', 'siteg_软封页.html',
         'washai_目录.html', 'washai_目录_第22页.html',
         'siteq_目录_真实页.html', 'siteq_content.html')


def _读(名):
    p = _样本 / 名
    if not p.is_file():
        raise unittest.SkipTest(f'形态样本缺失: 测试/样本/{名}')
    return p.read_bytes().decode('utf-8', errors='replace')


class Test形态样本完整性(unittest.TestCase):
    """样本本身必须干净 (红线自检, 防有人手改样本带入身份信息)"""

    def test_七份形态样本都在(self):
        缺 = [n for n in _必在 if not (_样本 / n).is_file()]
        self.assertEqual(缺, [], f'缺样本: {缺}')

    def test_无真实域名(self):
        rx = re.compile(r'(?<![\w-])([a-z0-9-]+\.(?:com|net|org|cc|hk|tw|cn|la|me'
                        r'|top|xyz|info|io|co|biz|site|online|pro|vip))(?![\w.-])', re.I)
        for n in _必在:
            命中 = [x for x in (m if isinstance(m, str) else m[0] for m in rx.findall(_读(n)))
                    if 'example.com' not in x]
            self.assertEqual(命中, [], f'{n} 残留真实域名: {命中[:3]}')

    def test_占位符已就位(self):
        """至少要有占位符, 证明脱敏真的跑了 (不是原文照抄)"""
        t = _读('tianqiu_目录.html')
        self.assertIn('<NOVEL>', t)
        self.assertIn('site1.example.com', t)


class Test折叠形态(unittest.TestCase):
    """真实折叠目录页: 告警必须触发 (2026-10-13 修掉了"章节一多就闭嘴"的早退)"""

    def _链数(self, html):
        return len(re.findall(r'href="[^"]*\d+\.html"', html))

    def test_折叠页告警(self):
        from bs4 import BeautifulSoup
        import 爬虫 as C
        h = _读('tianqiu_目录.html')
        r = C._目录折叠提示(BeautifulSoup(h, 'lxml'), self._链数(h))
        self.assertTrue(r, '真实折叠目录页必须告警')
        self.assertIn('折叠', r)

    def test_完整大目录不告警(self):
        from bs4 import BeautifulSoup
        import 爬虫 as C
        h = _读('siteq_目录_真实页.html')
        # 章节链接形态是 `/read/<书号>/p<章号>.html` (中间带 p 前缀), 别用窄正则
        n = len([m for m in re.finditer(r'href="([^"]+\.html)"', h)
                 if re.search(r'/\d', m.group(1))])
        self.assertGreater(n, 100, '完整目录样本应有大量章节链接')
        self.assertFalse(C._目录折叠提示(BeautifulSoup(h, 'lxml'), n),
                         '宣称≈实际的完整目录不该误告警')

    def test_分页目录首页告警(self):
        """通用路径只拿得到首页 ⇒ 相对"宣称"严重缺失 ⇒ 应告警"""
        from bs4 import BeautifulSoup
        import 爬虫 as C
        h = _读('washai_目录.html')
        self.assertTrue(C._目录折叠提示(BeautifulSoup(h, 'lxml'), self._链数(h)),
                        '分页目录首页(通用路径只拿得到这些)应告警')


class Test验证页形态(unittest.TestCase):
    """真实访问验证页: 两道门都必须命中 (第二道门曾把它否决 ⇒ 漏判)"""

    def test_第一道门命中(self):
        import 爬虫 as C
        self.assertTrue(C._像验证码页(_读('siteg_访问验证页.html')))

    def test_第二道门命中(self):
        import captcha_module as CM
        判 = CM.CaptchaHandler.__dict__['is_captcha_page']
        self.assertTrue(判(_读('siteg_访问验证页.html')),
                        '真实验证页不得被第二道门否决(那会造成漏判)')

    def test_软封页不误判成验证页(self):
        """反向护栏: 被拦截但没有验证表单的页面不该被判验证码页"""
        import captcha_module as CM
        判 = CM.CaptchaHandler.__dict__['is_captcha_page']
        self.assertFalse(判(_读('siteg_软封页.html')),
                         '软封页无验证表单, 不该命中第二道门')

    def test_普通页面两道门都不命中(self):
        import captcha_module as CM
        import 爬虫 as C
        判 = CM.CaptchaHandler.__dict__['is_captcha_page']
        h = _读('siteq_content.html')      # 键盘翻页的正常章节页
        self.assertFalse(判(h))
        self.assertFalse(C._像验证码页(h))


if __name__ == '__main__':
    unittest.main(verbosity=2)
