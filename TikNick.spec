# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Tik-Nick — single-file, windowed, Windows 10/11

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('web', 'web'),          # HTML/CSS/JS bundled inside the exe
        ('icon.ico', '.'),       # window icon
        ('i18n_en.json', '.'),   # תרגום הדוחות והגיליון להדפסה (i18n.py קורא אותו)
    ],
    hiddenimports=[
        # pywebview loads its Windows backend dynamically — pin them so
        # PyInstaller doesn't miss them
        'webview.platforms.edgechromium',
        'webview.platforms.winforms',
        'clr_loader',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='TikNick',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # no black console window for end users
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
    version='version_info.txt',
)
