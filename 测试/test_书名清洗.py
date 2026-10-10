# -*- coding: utf-8 -*-
"""书名清洗 C4 (离线)。

修复背景 (2026-10-10): 目录页/章节页/页标题里混进来的**非书名成分会直接变成文件名**,
用户拿到无法辨认的名字。实测三种来源:
  ① 章节页被当成目录页 → 书名成了 `第 1 部分：…`;
  ② 目录页/分页残留     → 书名尾部多个序号, 形如 `…示例书名甲1`;
  ③ 页标题带站点装饰   → `… 最新章节` / `…免费全文` / `…TXT下载`。

⚠️ 本文件一律用**合成书名** (示例书名甲…), 不用真实书名 —— 公开仓库红线。

运行方式 (项目根目录):
    python -m unittest discover -s 测试 -v
"""
import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '源码'))

import 爬虫 as C                                    # noqa: E402
from 爬虫 import 清洗书名, _书名已退化              # noqa: E402


class Test清洗书名(unittest.TestCase):

    def test_去第N部分前缀(self):
        """实测①: 章节页被当目录页, 章节标题成了书名。"""
        表 = {
            '第 1 部分：示例书名甲': '示例书名甲',
            '第1部分:示例书名甲': '示例书名甲',
            '第 12 部分 示例书名甲': '示例书名甲',
            '第 二 部分、示例书名甲': '示例书名甲',
            '第 1 部分：第 2 部分：示例书名甲': '示例书名甲',   # 叠加也要清干净
            '示例书名甲 第 1 部分': '示例书名甲 第 1 部分',       # 前缀才清, 中间不动
        }
        for 脏, 期望 in 表.items():
            with self.subTest(脏=脏):
                self.assertEqual(清洗书名(脏), 期望)

    def test_去尾部站点装饰(self):
        """实测③: 页标题带的站点装饰。"""
        表 = {
            '示例书名甲最新章节': '示例书名甲',
            '示例书名甲免费全文': '示例书名甲',
            '示例书名甲TXT下载': '示例书名甲',
            '示例书名甲最新章节免费全文': '示例书名甲',      # 叠加
            '示例书名甲_全文阅读': '示例书名甲',             # 边缘标点一并剥掉
        }
        for 脏, 期望 in 表.items():
            with self.subTest(脏=脏):
                self.assertEqual(清洗书名(脏), 期望)

    def test_装饰在中间不动(self):
        """约束③: 词表叫"后缀" —— 出现在中间的不该被削 (否则真书名会被削坏)。"""
        for 好 in ('全文阅读指南', '完结之后的世界', '精校版校对说明'):
            with self.subTest(好=好):
                self.assertEqual(清洗书名(好), 好)

    def test_尾部序号只在长书名上清(self):
        """实测② + 约束③的姊妹条款: 短书名里的数字常是书名本体。"""
        # 长书名 (≥8 字) 尾部的孤立序号 = 分页/目录残留 → 清掉
        self.assertEqual(清洗书名('示例书名甲示例书名乙1'), '示例书名甲示例书名乙')
        self.assertEqual(清洗书名('示例书名甲示例书名乙12'), '示例书名甲示例书名乙')
        # 短书名: 数字是书名本体, 一律不动
        for 短 in ('示例书甲2', '示例书名乙2', '示例书123', '示例书7'):
            with self.subTest(短=短):
                self.assertEqual(清洗书名(短), 短)

    def test_干净书名原样返回(self):
        for 好 in ('示例书名甲', '示例书名甲（修订版）', 'English Title'):
            with self.subTest(好=好):
                self.assertEqual(清洗书名(好), 好)

    # ---------------------------------------------------------- 硬约束
    def test_约束1_绝不返回空(self):
        """空串在 书名退化集合 里, 会被 死书处理 判成"书已删除" —— 清洗不得制造它。

        口径: 非空输入 → 返回值**不得是空串**(哪怕洗成空白也必须保留原值);
              空输入 → 原样返回(语义就是"原本没名字")。
        """
        for 非空 in ('   ', '最新章节', '第 1 部分：', '小说全文'):
            with self.subTest(非空=repr(非空)):
                self.assertNotEqual(清洗书名(非空), '',
                                    f'{非空!r} 被洗成了空串')
        for 空 in ('', None):
            with self.subTest(空=repr(空)):
                self.assertEqual(清洗书名(空), '')

    def test_约束1强化_不得把非退化名洗成退化名(self):
        """`小说全文` 洗掉装饰后是 `小说` —— 而 `小说` 在退化集合里。

        若不拦这一步, 一本**正常书**会因为清洗而凭空触发"书已删除"判定。
        """
        self.assertFalse(_书名已退化('小说全文'))
        self.assertTrue(_书名已退化('小说'))
        self.assertEqual(清洗书名('小说全文'), '小说全文', '应保持原值, 不得洗成退化名')
        self.assertEqual(清洗书名('novel最新章节'), 'novel最新章节')

    def test_约束2_幂等(self):
        样本 = ['第 1 部分：示例书名甲', '示例书名甲最新章节', '示例书名甲示例书名乙1',
               '示例书甲2', '小说全文', '最新章节', '', None, '   ', '示例书名甲（修订版）']
        for x in 样本:
            with self.subTest(x=repr(x)):
                一次 = 清洗书名(x)
                self.assertEqual(清洗书名(一次), 一次)

    def test_退化不变式_清洗不改变退化判定(self):
        """⚠️ 核心不变式: 死书处理靠"书名退化 ⇒ 书已删除"判定。

        清洗可以改书名, 但**绝不能改这个判定结果** —— 否则文件名与死书判定会漂移
        (项目已有一条同类教训: 两处退化集合必须同口径)。
        """
        样本 = ['novel', '小说', '', None, 'novel(1)', '小说(2)', '   ',
               '第 1 部分：示例书名甲', '示例书名甲最新章节', '示例书名甲示例书名乙1',
               '小说全文', 'novel最新章节', '示例书甲2', '示例书名甲']
        for x in 样本:
            with self.subTest(x=repr(x)):
                self.assertEqual(
                    _书名已退化(清洗书名(x)), _书名已退化(x),
                    f'{x!r} 的退化判定被清洗改变了')


class Test提取口已接清洗(unittest.TestCase):
    """清洗必须挂在**唯一提取点** `get_novel_title` 上。

    为什么不是挂在命名那一行: GUI 路径会先在 `run_crawl` 里按书名分配唯一序号 ——
    若那时拿到的还是脏名, 清洗后可能与既有文件撞名。
    """

    def _假蜘蛛(self, 返回名):
        蜘蛛 = object.__new__(C.NovelSpider)      # 不跑 __init__ (不碰网络/状态根)
        蜘蛛._提取书名原始 = lambda _url: 返回名
        return 蜘蛛

    def test_提取口自动清洗(self):
        蜘蛛 = self._假蜘蛛('第 1 部分：示例书名甲最新章节')
        self.assertEqual(蜘蛛.get_novel_title('https://example.com/b/1/'), '示例书名甲')

    def test_原始提取方法仍在(self):
        """防"空转通过": 包装若被重构掉, 本测试要响亮失败。"""
        self.assertTrue(hasattr(C.NovelSpider, '_提取书名原始'),
                        '原始提取方法不见 —— 结构已变, 请同步本测试')
        self.assertTrue(hasattr(C.NovelSpider, 'get_novel_title'))

    def test_退化值经提取口仍是退化(self):
        蜘蛛 = self._假蜘蛛('novel')
        self.assertTrue(_书名已退化(蜘蛛.get_novel_title('https://example.com/b/1/')))


if __name__ == '__main__':
    unittest.main(verbosity=2)
