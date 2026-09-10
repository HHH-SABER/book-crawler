# -*- coding: utf-8 -*-
"""单页等待时长契约测试。

回归背景 (2026-09-10 实测): 每页原本无条件 `time.sleep(random 0.5~1.5)`, 而章节
循环里还有一次"速度自适应档位间隔"的 sleep —— 两者**叠加**, 实际间隔等于两者之和。
后果有两个:
  1. 控制器以为自己在按 1.0s 节流, 实际 1.5~2.5s, 它的"健康就提速"模型建立在
     错误前提上;
  2. 实测 1000 章白等 500~1500 秒, 而整章 CPU (HTML 解析/质检/清洗) 合计仅约
     60 秒 —— 这是墙钟里唯一值钱的杠杆。
现改为取较大值 (去双重计时, 但保留 ≤1.5s 的抖动地板), 本文件固化该语义。

运行方式 (项目根目录):
    python -m unittest discover -s 测试 -v
"""
import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '源码'))

from 爬虫 import _单页等待秒, 页面等待_抖动与档位取较大值  # noqa: E402


class Test单页等待(unittest.TestCase):

    def test_档位间隔更大时取档位(self):
        self.assertEqual(_单页等待秒(档位间隔=2.0, 抖动=0.5), 2.0)

    def test_抖动更大时取抖动(self):
        self.assertEqual(_单页等待秒(档位间隔=0.2, 抖动=1.4), 1.4)

    def test_不叠加(self):
        """核心回归: 返回的是最大值, 不是两者之和"""
        抖动, 档位 = 1.2, 0.8
        值 = _单页等待秒(档位间隔=档位, 抖动=抖动)
        self.assertEqual(值, max(抖动, 档位))
        self.assertNotAlmostEqual(值, 抖动 + 档位)

    def test_有抖动地板(self):
        """任何档位下都不会比"纯抖动下限"更快 —— 反爬节律下限不被破坏"""
        for 间隔 in (0.0, 0.1, 0.2, 0.5):
            self.assertGreaterEqual(_单页等待秒(档位间隔=间隔, 抖动=0.5), 0.5)

    def test_无控制器仍给抖动(self):
        值 = _单页等待秒()
        self.assertGreaterEqual(值, 0.5)
        self.assertLessEqual(值, 1.5)

    def test_可回滚到旧行为(self):
        """取较大值=False 时必须恢复"相加"语义 (一行回滚路径可用)"""
        self.assertAlmostEqual(
            _单页等待秒(档位间隔=1.0, 抖动=0.6, 取较大值=False), 1.6)

    def test_默认常量开启取较大值(self):
        self.assertTrue(页面等待_抖动与档位取较大值,
                        '默认应为取较大值; 若刻意回滚请同步本用例与文档')

    def test_负数与None视为0(self):
        self.assertEqual(_单页等待秒(档位间隔=None, 抖动=0.7), 0.7)
        self.assertEqual(_单页等待秒(档位间隔=-1, 抖动=0.7), 0.7)


if __name__ == '__main__':
    unittest.main(verbosity=2)
