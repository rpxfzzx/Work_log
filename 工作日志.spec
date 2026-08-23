# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:/Users/zhang/Desktop/Deepseek/Project/Work Log/worklog.py'],
    pathex=[],
    binaries=[],
    datas=[('logo.ico', '.'), ('logo_64.png', '.')],
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
    name='工作日志',
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
    icon=['C:/Users/zhang/Desktop/Deepseek/Project/Work Log/logo.ico'],
)
