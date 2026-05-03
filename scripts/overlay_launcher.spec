# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

ROOT_DIR = Path.cwd()
SRC_DIR = ROOT_DIR / "src"
WEB_DIR = ROOT_DIR / "web"
ICON_DATAS = [(str(path), "web/icons") for path in sorted((WEB_DIR / "icons").glob("*.png"))]

a = Analysis(
    [str(SRC_DIR / "overlay_launcher.py")],
    pathex=[],
    binaries=[],
    datas=[
        (str(WEB_DIR / "control.html"), "web"),
        (str(WEB_DIR / "overlay.html"), "web"),
        *ICON_DATAS,
    ],
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
    name="terraria_overlay",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
