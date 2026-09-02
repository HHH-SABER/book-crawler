# -*- coding: utf-8 -*-
"""GUI v3 新模块单测: sites_config 运行时合并 / site_probe URL 规范化

注意: 测试会在 BASE_DIR 临时创建 站点配置.json, 结束后删除。
"""
import sys
import os
import json

BASE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.join(BASE, '源码'))

import sites_config  # noqa: E402
import site_probe  # noqa: E402

CFG = os.path.join(BASE, '站点配置.json')
_HAD_ORIG = os.path.exists(CFG)
_ORIG = open(CFG, encoding='utf-8').read() if _HAD_ORIG else None


def _cleanup():
    """恢复/删除测试用配置文件"""
    if _HAD_ORIG:
        with open(CFG, 'w', encoding='utf-8') as f:
            f.write(_ORIG)
    elif os.path.exists(CFG):
        os.remove(CFG)


def test_runtime_config_merge_and_enabled():
    """运行时配置: 新域名追加 + 内置域名覆盖 + enabled=False 跳过"""
    # 取一个真实内置域名做覆盖测试
    builtin = sites_config.SITE_PATTERNS[0]['domain']
    test_domain = 'test-merge-xyz.example.com'
    data = [
        {'domain': test_domain, 'pattern': 'html_selector',
         'content_selectors': ['#content']},
        {'domain': builtin, 'pattern': 'html_selector'},
        {'domain': 'test-disabled.example.com', 'pattern': 'html_selector',
         'enabled': False},
    ]
    with open(CFG, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)

    # 重置已应用标记, 强制重新合并
    sites_config._RUNTIME_APPLIED = False
    # 新域名: 能匹配到 (未禁用)
    pat = sites_config.get_site_pattern(f'https://{test_domain}/book/1.html')
    assert pat is not None and pat['domain'] == test_domain, '新域名应可匹配'
    # 禁用域名: 不匹配
    pat2 = sites_config.get_site_pattern('https://test-disabled.example.com/a.html')
    assert pat2 is None, 'enabled=False 的站点应被跳过'
    # 内置域名: 仍在列表且 pattern 被覆盖
    pat3 = sites_config.get_site_pattern(f'https://m.{builtin}/x.html')
    assert pat3 is not None and pat3['pattern'] == 'html_selector', \
        '内置域名应被运行时配置覆盖'


def test_runtime_config_missing_file():
    """配置文件不存在时: 静默使用内置配置"""
    if os.path.exists(CFG):
        os.remove(CFG)
    sites_config._RUNTIME_APPLIED = False
    builtin = sites_config.SITE_PATTERNS[0]['domain']
    pat = sites_config.get_site_pattern(f'https://{builtin}/a.html')
    assert pat is not None, '无运行时配置时应回退内置'


def test_runtime_config_bad_json():
    """配置文件损坏时: 静默降级不抛异常"""
    with open(CFG, 'w', encoding='utf-8') as f:
        f.write('{invalid json!!')
    sites_config._RUNTIME_APPLIED = False
    try:
        sites_config.get_site_pattern('https://anything.example.com/a.html')
    except Exception as e:
        raise AssertionError(f'坏 JSON 不应抛异常: {e}')


def test_normalize_site_url():
    assert site_probe.normalize_site_url('tanmixs.com') == 'https://tanmixs.com/'
    assert site_probe.normalize_site_url('https://a.com/path/x') == 'https://a.com/'
    assert site_probe.normalize_site_url('http://b.com') == 'http://b.com/'
    assert site_probe.normalize_site_url('') == ''
    assert site_probe.normalize_site_url('  c.com  ') == 'https://c.com/'


if __name__ == '__main__':
    fails = 0
    try:
        for name, fn in sorted(globals().items()):
            if name.startswith('test_') and callable(fn):
                try:
                    fn()
                    print(f'  PASS {name}')
                except AssertionError as e:
                    fails += 1
                    print(f'  FAIL {name}: {e}')
    finally:
        _cleanup()
    print('全部通过' if fails == 0 else f'{fails} 项失败')
    sys.exit(0 if fails == 0 else 1)
