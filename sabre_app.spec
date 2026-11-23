# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['sabre_app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets\\sabre_icon.ico', 'assets'),
        ('assets\\sabre_icon.png', 'assets'),
    ],
    hiddenimports=['sabre_core', 'sabre_terminal', 'sabre_ui', 'sabre_manage', 'sabre_updater'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebEngineQuick',
        'PySide6.QtPdf',
        'PySide6.QtPdfWidgets',
        'PySide6.QtQml',
        'PySide6.QtQuick',
        'PySide6.QtQuickWidgets',
        'PySide6.Qt3DCore',
        'PySide6.Qt3DRender',
        'PySide6.QtMultimedia',
        'PySide6.QtMultimediaWidgets',
        'PySide6.QtSql',
        'PySide6.QtCharts',
        'PySide6.QtDataVisualization',
        'PySide6.QtGraphs',
        'PySide6.QtDesigner',
        'PySide6.QtHelp',
        'PySide6.QtTest',
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'PIL',
        'pillow_heif',
        'lxml',
    ],
    noarchive=False,
    optimize=0,
)
_DROP_PREFIXES = ('api-ms-win-core-', 'api-ms-win-crt-')
_DROP_NAMES = {'ucrtbase.dll', 'icuuc.dll', 'icuin.dll'}
a.binaries = [
    b for b in a.binaries
    if 'codex-runtimes' not in b[1].lower()
    and not b[0].lower().startswith(_DROP_PREFIXES)
    and b[0].lower() not in _DROP_NAMES
    and not (b[0].lower().startswith('icudt') and b[0].lower().endswith('.dll'))
]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='항공운임 조회 (SABRE VER.)',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets\\sabre_icon.ico',
)
