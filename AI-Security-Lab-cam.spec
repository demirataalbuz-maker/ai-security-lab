# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

# Sadece ortak icerik gomulur; kisisel dosyalar (reports/progress/notes) exe'ye GIRMEZ.
_content = ['attacks.json', 'tools.json', 'questions.json', 'scenarios.json',
            'path.json', 'practice.json']
datas = [('data/' + f, 'data') for f in _content] + [('theme', 'theme'), ('icon.ico', '.')]
binaries = []
hiddenimports = []
for _m in ('customtkinter', 'mediapipe'):
    _r = collect_all(_m)
    datas += _r[0]; binaries += _r[1]; hiddenimports += _r[2]
tmp_ret = ([], [], [])
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'pandas'],
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
    name='AI-Security-Lab',
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
    icon=['icon.ico'],
)
