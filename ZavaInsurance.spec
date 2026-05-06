# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Zava Insurance Store package.
Bundles Flask app + templates + static + sample data into single folder.
"""

import os
import sys

block_cipher = None
BASE = os.path.dirname(os.path.abspath(SPEC))

a = Analysis(
    ['launcher.py'],
    pathex=[BASE],
    binaries=[],
    datas=[
        ('app.py', '.'),
        ('templates', 'templates'),
        ('static', 'static'),
        ('sample_data', 'sample_data'),
        ('reports', 'reports'),
    ],
    hiddenimports=[
        'flask',
        'openai',
        'requests',
        'PIL',
        'PIL._tkinter_finder',
        'webview',
        'webview.platforms.edgechromium',
        'clr_loader',
        'pythonnet',
        'foundry_local',
        'werkzeug',
        'werkzeug.utils',
        'jinja2',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas', 'scipy'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ZavaInsurance',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # No console window — use windowed mode
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='arm64',
    icon='packaging/Assets/app.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='ZavaInsurance',
)
