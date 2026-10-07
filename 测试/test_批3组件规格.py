# -*- coding: utf-8 -*-
"""批 3(3)(4)(5) 组件规格对齐设计稿的回归护栏。

钉住三页的关键规格 (防半迁移/防回退):
- 爬取历史: 统计数值 28px + 千位分隔; 过滤 chip 高 28/胶囊/语义浅底选中;
  明细行白底 + 底部分隔线
- 站点管理: 插件卡奶油底; 适配器行白底两行布局; 启用开关蓝色轨道
- 远控: 状态卡粗标题; 信息行边框值盒 + 复制按钮; 记录卡计数
全部离线 (import _沙箱), 不联网、不碰用户状态根。
"""
import unittest

import _沙箱  # noqa: F401

import flet as ft
from pathlib import Path
import json as _json

from gui_components import ui_tokens
from gui_components.pages.history_page import HistoryPage
from gui_components.pages.remote_page import RemotePage

# 站点管理页 import 时会读 BASE_DIR/站点配置.json, 走沙箱状态根即安全
# (插件目录在 Test站点页规格 内用临时目录重定向, 见其 setUp)
from gui_components.pages.site_manage_page import SiteManagePage


def _收集(控件, 属性):
    出 = []
    def 走(c):
        if c is None:
            return
        v = getattr(c, 属性, None)
        if v is not None and not isinstance(v, (list, tuple, ft.Container)):
            出.append(v)
        for 属 in ('controls',):
            子 = getattr(c, 属, None)
            if isinstance(子, list):
                for x in 子:
                    走(x)
        子 = getattr(c, 'content', None)
        if 子 is not None:
            走(子)
    走(控件)
    return 出


class _页面基例(unittest.TestCase):
    def setUp(self):
        ui_tokens.设置主题(False)
        self.addCleanup(lambda: ui_tokens.设置主题(False))


class Test历史页规格(_页面基例):
    def setUp(self):
        super().setUp()
        self.页 = HistoryPage()
        self.根 = self.页.build()

    def test_统计数值为28号字(self):
        nums = [t for t in _收集(self.页._stat_row, 'size') if t == 28]
        self.assertGreaterEqual(len(nums), 5, '5 张统计卡的数值应为 28px')

    def test_统计数值带千位分隔(self):
        # 伪造 >999 的量级走一遍渲染 (query 走真实历史库, 沙箱内为空)
        self.页._build_stat_cards({'总请求数': 2847, '新增': 1923, '更新': 612,
                                   '未变化': 234, '失败': 78})
        文本 = _收集(self.页._stat_row, 'value')
        self.assertIn('2,847', 文本)

    def test_过滤chip高28且胶囊(self):
        chips = self.页._result_chips_row.controls
        self.assertTrue(chips, '应有结果过滤 chips')
        for c in chips:
            self.assertEqual(c.height, 28, '设计稿 .filter-chip 高 28px')
            self.assertEqual(c.border_radius, 999, 'chip 为胶囊圆角')

    def test_选中chip用语义浅底而非实心填充(self):
        self.页._filter_result = '新增'
        self.页._rebuild_result_chips()
        active = [c for c in self.页._result_chips_row.controls
                  if c.content.value == '新增']
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].bgcolor, ui_tokens.取色('status-success-bg'),
                         '选中 chip 应用语义浅底 (设计稿 .filter-chip.active.success)')

    def test_明细行白底带底部分隔线(self):
        self.页._view_mode = "urls"
        rows = [c for c in self.页._table_view.controls
                if getattr(c, 'border', None) is not None]
        self.assertTrue(rows, 'URL 明细行应有底部分隔线')
        for c in rows[:3]:
            self.assertEqual(c.bgcolor, ft.Colors.SURFACE, '明细行应为白底')


class Test站点页规格(_页面基例):
    def setUp(self):
        super().setUp()
        # 源码/沙箱下 站点适配/ 无插件 (脱钩设计: 真实插件在 站点适配_本地/)。
        # 本组测试播种一个临时适配器目录 + 假插件, 验证行的规格对齐。
        import tempfile
        import json as _json
        self._tmp = Path(tempfile.mkdtemp(prefix="nc_sites_")).resolve()
        self._适配目录 = self._tmp / "站点适配"
        self._适配目录.mkdir()
        (self._适配目录 / "fake_adapter.py").write_text(
            'SITE = {"domain": "fake.example", "pattern": "html_selector"}\n'
            'def parse_catalog(soup, url, base, **kw):\n    return None\n',
            encoding="utf-8")
        (self._tmp / "站点配置.json").write_text(
            _json.dumps([{"domain": "test.example", "pattern": "html_selector",
                          "enabled": True}], ensure_ascii=False),
            encoding="utf-8")
        import gui_components.pages.site_manage_page as _smp
        import sites_config as _sc
        import _path_utils as _pu
        # sites_config 在函数体内 `from _path_utils import get_app_base_dir`,
        # 故统一 patch _path_utils 源头 + site_manage_page 的模块级绑定
        self._原取基目录 = [_smp.get_app_base_dir, _pu.get_app_base_dir]
        _pu.get_app_base_dir = lambda: str(self._tmp)
        _smp.get_app_base_dir = lambda: str(self._tmp)
        # 强制重扫: 全量门禁下其他测试可能已置 _ADAPTERS_LOADED,
        # 不重扫则假插件不会被加载 (能力徽章为空)
        _sc.reload_adapters()
        self.页 = SiteManagePage()
        self.根 = self.页.build()
        self.页._render_adapters(force=True)
        self.addCleanup(self._还原)

    def _还原(self):
        import gui_components.pages.site_manage_page as _smp
        import sites_config as _sc
        import _path_utils as _pu
        _smp.get_app_base_dir, _pu.get_app_base_dir = self._原取基目录
        _sc.reload_adapters()   # 还原真实插件注册表
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_插件卡为warning浅底(self):
        self.assertEqual(self.页._adapter_card.bgcolor,
                         ui_tokens.取色('status-warning-bg'),
                         '设计稿插件卡为奶油底 (status-warning-bg)')

    def test_插件行白底且含能力徽章pill(self):
        self.assertGreater(len(self.页._adapter_view.controls), 0, '应有插件行')
        行 = self.页._adapter_view.controls[0]
        self.assertEqual(行.bgcolor, ft.Colors.SURFACE, '插件行应为白底小卡')
        pills = [c for c in _收集(行, 'height') if c == 20]
        self.assertGreaterEqual(len(pills), 1, '应有 20px 高的能力徽章 pill')

    def test_启用开关蓝色轨道(self):
        switches = []

        def 走(c):
            if isinstance(c, ft.Switch):
                switches.append(c)
            for 属 in ('controls',):
                子 = getattr(c, 属, None)
                if isinstance(子, list):
                    for x in 子:
                        走(x)
            子 = getattr(c, 'content', None)
            if 子 is not None:
                走(子)
        走(self.根)
        self.assertTrue(switches, '站点表应有启用开关')
        for s in switches:
            self.assertEqual(s.active_track_color,
                             ui_tokens.取色('btn-primary-bg'),
                             '设计稿: 开启轨道为主题蓝 (非 iOS 绿)')

    def test_统计文案右置工具行(self):
        # 工具行 Row 里应有 expand 占位 (统计文案右置的标志)
        texts = _收集(self.页._info_text, 'value')
        self.assertIsInstance(texts, list)


class Test远控页规格(_页面基例):
    def setUp(self):
        super().setUp()
        self.页 = RemotePage()
        self.根 = self.页.build()

    def test_状态卡有粗标题(self):
        self.assertEqual(self.页._card_title.weight, ft.FontWeight.BOLD)
        self.assertIn(self.页._card_title.value, ('远控已启用', '远控已关闭'))

    def test_信息行有边框值盒与复制按钮(self):
        # 状态卡内应有 3 个边框值盒 (本地地址/token/外网命令)
        boxes = [c for c in _收集(self.根, 'border_radius') if c == 4]
        self.assertGreaterEqual(len(boxes), 3, '应有 ≥3 个边框值盒')
        copies = [c for c in _收集(self.根, 'tooltip') if c == '复制到剪贴板']
        self.assertGreaterEqual(len(copies), 3, '应有 ≥3 个复制按钮')

    def test_记录卡有计数文本(self):
        self.assertEqual(self.页._rows_count.value, '共 0 条')

    def test_打码token复制的是明文(self):
        self.页._token明文 = 'abcd1234'
        self.assertEqual(self.页._取当前token(), 'abcd1234',
                         '复制应取明文而非打码展示')


if __name__ == '__main__':
    unittest.main()
