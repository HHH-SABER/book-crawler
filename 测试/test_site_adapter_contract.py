# -*- coding: utf-8 -*-
"""站点适配机制契约测试 (公开侧, 占位域, 无任何真实站点信息)。

锁定「站点脱钩机制」的公开侧行为契约 (AGENTS §目录与文件管理规范 四):
  1. 站点适配/_模板.py 展示完整 SITE 契约 (占位域 example.com), 且
     因文件名以 _ 开头不会被 load_adapters 加载执行;
  2. load_adapters 幂等, 双目录扫描 (公开侧 + 站点适配_本地);
  3. 提取器别名归一与"未注册走通用路径"的降级行为;
  4. 函数型分页机制名引用 (站点表.json 外置形态) 的解析。

注: 公开仓库不含任何测试样本文件 (真实快照在 测试样本_本地/ 不入库,
    合成占位样本已移除 —— 契约测试全部使用内联 HTML, 零文件依赖)。
公开仓库形态 (无 站点适配_本地/) 与本地形态下本测试都必须全绿。
运行: python -m unittest discover -s 测试 -v
"""
import importlib.util
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / '源码'))

from bs4 import BeautifulSoup  # noqa: E402

_TEMPLATE = _ROOT / '站点适配' / '_模板.py'


def _载入模板模块():
    spec = importlib.util.spec_from_file_location('site_adapter_template', str(_TEMPLATE))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Test模板契约(unittest.TestCase):
    """_模板.py 必须是完整、可执行的 SITE 契约参考实现"""

    @classmethod
    def setUpClass(cls):
        if not _TEMPLATE.is_file():
            raise unittest.SkipTest('站点适配/_模板.py 不存在')

    def test_占位域配置契约(self):
        mod = _载入模板模块()
        self.assertTrue(hasattr(mod, 'SITE'), '模板必须定义 SITE dict')
        site = mod.SITE
        self.assertIsInstance(site, dict)
        self.assertEqual(site.get('domain'), 'example.com')
        self.assertIn(site.get('pattern'),
                      ('html_selector', 'qsbs_bb', 'ajax_two_step', 'selenium'),
                      'pattern 必须是四种模式常量之一')
        self.assertIsInstance(site.get('content_selectors'), list)
        self.assertIsInstance(site.get('content_pagination'), dict)

    def test_契约函数齐全可调用(self):
        mod = _载入模板模块()
        for attr in ('parse_catalog', 'extract_content', 'paginate'):
            fn = getattr(mod, attr, None)
            self.assertTrue(callable(fn), f'模板契约函数 {attr} 缺失或不可调用')

    def test_模板行为自洽(self):
        """模板的三个契约函数对最小 HTML 的行为符合契约 (示例即文档)"""
        mod = _载入模板模块()
        soup = BeautifulSoup(
            '<html><body><div id="list">'
            '<a href="/book/1/1.html">第1章</a><a href="/book/1/2.html">第2章</a>'
            '</div><div id="content">' + '<p>示例正文段落内容。</p>' * 30 +
            '</div></body></html>', 'lxml')
        ch = mod.parse_catalog(soup, 'https://example.com/book/1/', 'https://example.com')
        self.assertIsInstance(ch, list)
        self.assertEqual(len(ch), 2)
        self.assertIn('title', ch[0])
        self.assertIn('url', ch[0])
        text = mod.extract_content(soup, 'https://example.com/book/1/1.html',
                                   'https://example.com')
        self.assertIsNotNone(text)
        self.assertIn('示例正文段落内容', text)
        nxt = mod.paginate('https://example.com/book/1/1.html', 1)
        self.assertEqual(nxt, 'https://example.com/book/1/1_1.html')


class Test加载器契约(unittest.TestCase):
    """load_adapters / 提取器注册表 / 函数分页 的机制行为"""

    def test_load_adapters幂等且不加载下划线模板(self):
        import sites_config as sc
        sc.load_adapters()
        first = dict(sc.ADAPTERS)
        sc.load_adapters()
        self.assertEqual(sc.ADAPTERS, first, 'load_adapters 二次调用必须幂等')
        # _模板.py 以 _ 开头, 任何形态下都不应作为适配器注册
        self.assertNotIn('example.com', sc.ADAPTERS,
                         '占位模板不得被注册为真实适配器')

    def test_未注册提取器走通用路径(self):
        """公开形态 (或未知机制名) 时 extract_content_html_selector 走通用 get_text"""
        import sites_config as sc
        html = ('<html><body><div id="content">'
                + '<p>通用提取路径的正文段落。</p>' * 30
                + '</div></body></html>')
        text = sc.extract_content_html_selector(
            html, ['#content'], extractor='未注册的机制名')
        self.assertIn('通用提取路径的正文段落', text)

    def test_提取器别名归一直通未知名(self):
        import sites_config as sc
        # 未知名原样返回 (不抛错)
        self.assertEqual(sc.解析提取器名('unknown_mech'), 'unknown_mech')
        # 已注册机制名直通
        self.assertEqual(sc.解析提取器名('p_nav_filter'), 'p_nav_filter')

    def test_函数分页机制名未知时干净返回None(self):
        import sites_config as sc
        pag = {'type': 'function', 'function': '不存在的机制名', 'max_pages': 30}
        self.assertIsNone(sc.build_paged_url('https://example.com/a/1/2.html', 1, pag))


if __name__ == '__main__':
    unittest.main(verbosity=2)
