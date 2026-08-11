# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['K:/程序文件/小说爬虫/src/gui_app.py'],
    pathex=[],
    binaries=[],
    datas=[('K:/程序文件/小说爬虫/_flet_client', 'flet_client'), ('K:/程序文件/小说爬虫/config/captcha_config.json', '.')],
    hiddenimports=[],
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
)
