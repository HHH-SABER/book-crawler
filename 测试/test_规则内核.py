# -*- coding: utf-8 -*-
"""规则内核只读 IR 导出的用例（S1 第一步）。

覆盖：阶段词汇扫描（AST/字面量/去重）、适配器声明阶段提取（== / in 两种写法）、
IR 在"无适配器"形态下的安全性，以及**只读性**（不 import 爬虫.py、重复调用结果一致）。
"""
import pathlib
import sys
import unittest

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '源码'))
sys.path.insert(0, str(_PROJECT_ROOT / '测试'))

import _沙箱  # noqa: E402,F401  状态根沙箱
import 规则内核  # noqa: E402


class 阶段扫描用例(unittest.TestCase):
    def test_扫真实源码能拿到阶段词汇(self):
        清单 = 规则内核.扫描阶段清单()
        self.assertGreaterEqual(len(清单), 8, f'阶段数偏少，疑似扫描失效: {清单.keys()}')
        # 这几个是 爬虫.py 里稳定存在的阶段（改代码才会变）
        for 必含 in ('目录规范化', '章节链接接受'):
            self.assertIn(必含, 清单, f'缺阶段词汇: {必含}')

    def test_次数与位置可追溯(self):
        清单 = 规则内核.扫描阶段清单()
        桶 = 清单['章节链接接受']
        self.assertGreaterEqual(桶['次数'], 1)
        self.assertTrue(all(':' in x for x in 桶['位置']), '位置应为 文件名:行号')

    def test_只认字符串字面量_变量透传不计入(self):
        # 直接构造一个含"变量阶段"的临时源码
        临时 = pathlib.Path(__import__('tempfile').gettempdir()) / '_nc_ir_probe.py'
        临时.write_text(
            'def f():\n'
            "    _站点策略(url, '固定阶段')\n"
            '    _站点策略(url, 变量阶段)\n'
            '    _站点策略(url)\n',
            encoding='utf-8')
        try:
            清单 = 规则内核.扫描阶段清单([临时])
        finally:
            临时.unlink(missing_ok=True)
        self.assertEqual(list(清单), ['固定阶段'])


class 声明阶段用例(unittest.TestCase):
    def test_等号分支(self):
        源码 = (
            'def 站点策略(url, 阶段, **kw):\n'
            "    if 阶段 == '目录规范化':\n"
            '        return None\n'
            "    if 阶段 == '专属选择器':\n"
            '        return {}\n'
        )
        self.assertEqual(规则内核.声明阶段(源码), ['目录规范化', '专属选择器'])

    def test_in分支与去重(self):
        源码 = (
            'def 站点策略(url, 阶段, **kw):\n'
            "    if 阶段 in ('目录兜底解析', '文本提链'):\n"
            '        return None\n'
            "    if 阶段 == '文本提链':\n"
            '        return False\n'
        )
        self.assertEqual(规则内核.声明阶段(源码), ['目录兜底解析', '文本提链'])

    def test_非阶段变量不误判(self):
        源码 = 'def f(阶段):\n    if 其它 == "x":\n        pass\n'
        self.assertEqual(规则内核.声明阶段(源码), [])

    def test_语法错误返回空而不抛(self):
        self.assertEqual(规则内核.声明阶段('def f(:\n'), [])


class 适配器IR用例(unittest.TestCase):
    def test_空表返回空(self):
        self.assertEqual(规则内核.导出适配器IR({}), {})

    def test_声明阶段可提取(self):
        def 站点策略(url, 阶段, **kw):
            if 阶段 == '目录规范化':
                return None
            return None
        IR = 规则内核.导出适配器IR({'siteA': {'域名': 'a.example.com', '站点策略': 站点策略}})
        self.assertEqual(IR['siteA']['域名'], 'a.example.com')
        self.assertTrue(IR['siteA']['有站点策略'])
        self.assertIn('目录规范化', IR['siteA']['声明阶段'])

    def test_无钩子适配器_声明阶段为空(self):
        IR = 规则内核.导出适配器IR({'siteB': {'域名': 'b.example.com'}})
        self.assertFalse(IR['siteB']['有站点策略'])
        self.assertEqual(IR['siteB']['声明阶段'], [])

    def test_非dict条目被跳过(self):
        IR = 规则内核.导出适配器IR({'bad': '不是字典'})
        self.assertEqual(IR, {})


class 只读与幂等用例(unittest.TestCase):
    def test_重复调用结果一致(self):
        a = 规则内核.扫描阶段清单()
        b = 规则内核.扫描阶段清单()
        self.assertEqual(a, b)

    def test_不导入爬虫模块(self):
        """IR 导出不该把 爬虫.py 拉进内存（6000 行上帝类，会连锁初始化）。

        必须在**子进程**里验：同一进程里别的用例早已 import 过爬虫，
        直接 `'爬虫' in sys.modules` 会随执行顺序假红（审计警告过的坏味道）。
        """
        import subprocess
        代码 = (
            'import sys; sys.path.insert(0, r"%s"); import 规则内核; '
            "print('爬虫' in sys.modules)"
        ) % (_PROJECT_ROOT / '源码')
        结果 = subprocess.run([sys.executable, '-c', 代码], capture_output=True, timeout=60)
        self.assertEqual(结果.returncode, 0, 结果.stderr.decode('utf-8', 'replace')[:300])
        self.assertEqual(结果.stdout.decode().strip(), 'False',
                         '规则内核 不应触发 爬虫.py 的导入')


if __name__ == '__main__':
    unittest.main()
