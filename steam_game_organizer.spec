# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Steam Game Organizer.
#
# One exe plus a bundle folder beside it. Everything else - the bundled runtime, the cache, the
# config - lives in the bundle, which is how the app already works from a source checkout:
# steam_game_organizer.py resolves its own folder as the project root and expects core/, services/,
# runtime/, config/, cache/ and logs/ to be siblings of the entry point. Freezing changes nothing
# about that contract; it only stops the reader from having to have Python installed.
#
# `onedir` rather than `--onefile`: a one-file build spends minutes repacking the interpreter into a
# temp folder on every launch, and the bundled runtime already ships a full interpreter for the
# extraction tools to call. The datas are listed by hand so the contents are reviewable, not
# inferred from an import scan that would drag in the stdlib test suite and the whole tcl/tk tree.
block_cipher = None

a = Analysis(
    ['steam_game_organizer.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('core', 'core'),
        ('services', 'services'),
        ('ui', 'ui'),
        ('utils', 'utils'),
        ('app', 'app'),
        ('debug', 'debug'),
        ('tools', 'tools'),
        ('assets', 'assets'),
        ('runtime', 'runtime'),
        ('VERSION.txt', '.'),
        ('AGENTS.md', '.'),
        ('ARCHITECTURE.md', '.'),
        ('README.md', '.'),
        ('ruff.toml', '.'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='steam_game_organizer',
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
    exclude_binaries=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='steam_game_organizer',
)