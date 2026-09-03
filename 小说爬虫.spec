# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['K:/程序文件/小说爬虫/源码/gui_app.py'],
    pathex=[],
    binaries=[],
    datas=[('K:/程序文件/小说爬虫/_flet_client', 'flet_client'), ('K:/程序文件/小说爬虫/源码/站点配置.json', '.'), ('K:/程序文件/小说爬虫/配置/captcha_config.json', '.'), ('K:/程序文件/小说爬虫/.venv/Lib/site-packages/ddddocr', 'ddddocr')],
    hiddenimports=['selenium.webdriver.chrome.webdriver', 'selenium.webdriver.chrome.service', 'selenium.webdriver.chrome.options', 'selenium.webdriver.common.by', 'selenium.webdriver.common.action_chains', 'selenium.webdriver.common.keys', 'selenium.webdriver.support.ui', 'selenium.webdriver.support.expected_conditions'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='小说爬虫',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='K:/程序文件/小说爬虫/_version_info.txt',
    icon=['K:/程序文件/小说爬虫/脚本/图标.ico'],
)
