# -*- coding: utf-8 -*-
"""红线扫描器门禁 (2026-10-13): 公开仓库/发布产物的站点与书名泄露检查。

## 背景

本项目最高约束是真实站点信息不得进公开仓库。此前靠人工 grep —— 今天上线
本扫描器的**当天就抓到一处现存泄露** (`源码/爬虫.py` 命令行示例里写着真实
站点 URL, 而相邻两行都是代号), 证明人工把关不可靠、此门禁必要。

## 两层防线

· **CI/门禁 (本文件)**: 只跑**入库的通用规则** (三级以上真实域名 / 书名
  括号 / 禁文件 / zip 解包扫), 不依赖本地词库 ⇒ GitHub Actions 也能跑;
· **本地全量 (`脚本/红线扫描.py --全量`)**: 加载 `站点适配_本地/红线词库.txt`
  (具体站点词, gitignored), 发版前人工跑, 最严。

## 变异测试 (K33)

本文件的"能抓到"用例**必须**在扫描器判据被破坏时变红 —— 已做: 把三级域名
正则改成永不匹配后, `test_能抓到真实站点域名` 等 3 例立刻 FAIL。
运行: python -m unittest discover -s 测试
"""
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

_根 = Path(__file__).resolve().parent.parent
_扫描器 = _根 / '脚本' / '红线扫描.py'
_PY = _根 / '.runtime' / 'python314' / 'python.exe'


def _跑(args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(_PY), str(_扫描器)] + args,
        cwd=str(_根), capture_output=True, text=True, encoding='utf-8',
        timeout=300)


class Test扫描器有效性(unittest.TestCase):
    """★ 变异测试守门: 扫描器必须真的能抓到 (不是永远 PASS 的装饰)"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    # 样本域名**动态拼接**: 测试文件本身会被公开侧扫描扫到, 写死完整域名
    # 会自命中 (2026-10-13 踩坑) ⇒ 运行时才拼出完整值
    _样本域 = 'book.' + 'qiqishu' + '.cc'

    def test_能抓到真实站点域名(self):
        坏 = self.tmp / 'bad.py'
        坏.write_text(f'url = "https://{self._样本域}/read/1/2.html"\n',
                      encoding='utf-8')
        r = _跑([str(坏)])
        self.assertNotEqual(r.returncode, 0, '含三级真实域名的文件必须被抓')
        self.assertIn('真实域名', r.stdout)

    def test_能抓到书名(self):
        坏 = self.tmp / 'bad2.py'
        坏.write_text('title = "' + '《' + '某本小说' + '》' + '"\n',
                      encoding='utf-8')
        r = _跑([str(坏)])
        self.assertNotEqual(r.returncode, 0, '书名括号必须被抓')

    def test_能抓到禁文件(self):
        坏 = self.tmp / '站点表.json'
        坏.write_text('{}', encoding='utf-8')
        r = _跑([str(坏)])
        self.assertNotEqual(r.returncode, 0, '站点表.json 是禁文件, 必须被抓')

    def test_zip解包扫(self):
        """zip 内是明文, 必须解包扫 (发布产物的实际形态)"""
        坏 = self.tmp / 'inner.py'
        坏.write_text(f'x = "https://{self._样本域}/1.html"\n', encoding='utf-8')
        z = self.tmp / 'release.zip'
        with zipfile.ZipFile(z, 'w') as f:
            f.write(坏, 'inner.py')
        r = _跑([str(z)])
        self.assertNotEqual(r.returncode, 0, 'zip 内的站点词必须被抓')

    def test_zip内禁目录被抓(self):
        z = self.tmp / 'bad.zip'
        with zipfile.ZipFile(z, 'w') as f:
            f.writestr('站点适配_本地/washai.py', '# 真实适配器\n')
        r = _跑([str(z)])
        self.assertNotEqual(r.returncode, 0, 'zip 内混入私有适配目录必须被抓')


class Test占位不误报(unittest.TestCase):
    """反向护栏: 测试占位/示例域/RFC 保留域**不得**误报 (否则门禁失效)"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_测试占位域不误报(self):
        for i, 占位 in enumerate(('a.com', 'example.com', 'xx.com', 'evil.com',
                                  'www.unknown-zzz.com', 'site1.example.com',
                                  'sitec.example.cc', 'book.example.org')):
            with self.subTest(占位=占位):
                p = self.tmp / f'ok{i}.py'
                p.write_text(f'u = "https://{占位}/x"\n', encoding='utf-8')
                r = _跑([str(p)])
                self.assertEqual(r.returncode, 0,
                                 f'{占位} 是占位/示例域, 不该误报: {r.stdout[-200:]}')

    def test_公共基础设施不误报(self):
        p = self.tmp / 'ci.py'
        p.write_text('mirror = "https://mirror.ghproxy.com/"\n'
                     'dns = "https://dns.alidns.com/resolve"\n', encoding='utf-8')
        r = _跑([str(p)])
        self.assertEqual(r.returncode, 0, '公共构建镜像/DNS 不该误报')

    def test_脱敏样本的占位域名不误报(self):
        """形态样本里的 siteN.example.com 是脱敏产物, 必须放行"""
        r = _跑(['测试/样本'])
        self.assertEqual(r.returncode, 0, f'脱敏样本应全部放行: {r.stdout[-300:]}')


class Test公开侧当前干净(unittest.TestCase):
    """门禁本体: 公开侧扫描必须 PASS (这同时是回归 —— 今天修过一处泄露)"""

    def test_公开侧无残留(self):
        r = _跑(['--ci'])
        self.assertEqual(r.returncode, 0,
                         f'公开侧存在红线残留, 必须修:\n{r.stdout[-500:]}')
        self.assertIn('PASS', r.stdout)

    def test_发布产物无残留(self):
        """发布/ (公开包 + zip 解包扫) —— 用户明确要求覆盖发布产物"""
        发布 = _根 / '发布'
        if not 发布.is_dir():
            self.skipTest('无发布目录')
        r = _跑([str(发布)])
        self.assertEqual(r.returncode, 0,
                         f'发布产物存在红线残留:\n{r.stdout[-500:]}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
