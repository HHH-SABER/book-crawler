# -*- coding: utf-8 -*-
"""验证码配置原子写回归测试 (批1: captcha_module.Config.save 直写 -> tmp+os.replace)。

## 为什么需要

`Config.save()` 写 `captcha_config.json` (验证码模块的用户配置), 旧实现
`Path(self.path).write_text(...)` **直写最终路径**。写入途中若进程被杀/断电/磁盘满,
会留下半截 JSON; 下次 `Config.load()` 解析失败 -> `_merge` 拿不到内容 -> **静默回退
全默认配置**。后果严重且隐蔽: 用户显式开启的 ddddocr 自动识别等设置会"凭空消失",
而 load() 只 `_log.info` 一句、不报错, 用户无从察觉。

修复采用项目既有范式 (爬取历史.py:_落盘 U17 / 本批 M2 检查点): **tmp + os.replace**。

## 锁定的契约

1. 必须经 os.replace 原子落盘, 不得 write_text 直写最终路径。
2. tmp 名带 pid (GUI 与远控是两个进程, 可能写同一配置; 共用 .tmp 会互相截断, U16)。
3. tmp 与目标同目录 (os.replace 跨盘抛 OSError)。
4. save 后无 tmp 残留; 内容可被 load() 正确读回。

不联网, 不改源码逻辑 (仅落盘方式), 临时目录写入并清理。
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '源码'))

import captcha_module as cm  # noqa: E402


class TestConfig原子写(unittest.TestCase):
    """captcha_module.Config.save 必须走 tmp + os.replace"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix='captcha_cfg_')
        self.cfg_path = os.path.join(self.tmp_dir, 'captcha_config.json')
        self.cfg = cm.Config(path=self.cfg_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_save后内容正确且可load回(self):
        self.cfg.data['strategies'] = {'ddddocr': {'enabled': True, 'retry_limit': 5}}
        self.cfg.save()
        self.assertTrue(os.path.isfile(self.cfg_path))
        # 用全新 Config load 回来, 验证落盘内容完整合法
        back = cm.Config(path=self.cfg_path).load()
        self.assertTrue(back.data['strategies']['ddddocr']['enabled'])
        self.assertEqual(5, back.data['strategies']['ddddocr']['retry_limit'])

    def test_经由os_replace落盘而非直写(self):
        with mock.patch.object(cm.os, 'replace', wraps=os.replace) as m:
            self.cfg.save()
        self.assertTrue(m.called, 'Config.save 必须通过 os.replace 原子落盘')
        src, dst = Path(m.call_args[0][0]), Path(m.call_args[0][1])
        self.assertEqual(Path(self.cfg_path).resolve(), dst.resolve(),
                         'os.replace 目标必须是配置最终路径')
        self.assertIn('.tmp', src.name, '源必须是临时文件')

    def test_临时文件名带pid(self):
        with mock.patch.object(cm.os, 'replace', wraps=os.replace) as m:
            self.cfg.save()
        src = Path(m.call_args[0][0])
        self.assertIn(str(os.getpid()), src.name,
                      f'临时文件名应含 pid 防双进程冲突, 实际: {src.name}')

    def test_临时文件与目标同目录(self):
        with mock.patch.object(cm.os, 'replace', wraps=os.replace) as m:
            self.cfg.save()
        src, dst = Path(m.call_args[0][0]), Path(m.call_args[0][1])
        self.assertEqual(src.parent.resolve(), dst.parent.resolve(),
                         '临时文件必须与目标同目录, 否则 os.replace 不保证原子')

    def test_save后无tmp残留(self):
        self.cfg.save()
        残留 = [p.name for p in Path(self.tmp_dir).iterdir() if '.tmp' in p.name]
        self.assertEqual([], 残留, 'os.replace 后临时文件应已消失')

    def test_连续多次save均完整(self):
        for i in range(5):
            self.cfg.data['retry_limit'] = i
            self.cfg.save()
            data = json.loads(Path(self.cfg_path).read_text(encoding='utf-8'))
            self.assertEqual(i, data['retry_limit'])

    def test_自定义path参数save(self):
        """save(path=...) 形式也应原子写"""
        other = os.path.join(self.tmp_dir, 'other_config.json')
        with mock.patch.object(cm.os, 'replace', wraps=os.replace) as m:
            self.cfg.save(path=other)
        self.assertTrue(m.called)
        self.assertTrue(os.path.isfile(other))

    def test_path为None时save不报错(self):
        """无路径时 save 应安全返回 (不抛异常), 与旧行为一致"""
        cfg = cm.Config(path=None)
        try:
            cfg.save()
        except Exception as e:
            self.fail(f'path=None 时 save 不应抛异常, 实际: {e}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
