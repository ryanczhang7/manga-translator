# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-folder build.

One folder, not one file: the shipped app carries ~1 GB of .onnx weights
(stack.md §3), and a one-file build unpacks all of it to a temp directory on
every launch. Run from the repository root:

    uv run pyinstaller --noconfirm packaging/mangatl.spec

`dist/` and `build/` are gitignored.
"""

import os

ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))
SRC = os.path.join(ROOT, "src")

a = Analysis(
    [os.path.join(SRC, "mangatl", "app.py")],
    pathex=[SRC],
    binaries=[],
    # Model weights are added here by MT-024, once MT-002 has decided what the
    # inference runtime is. Nothing to carry yet.
    datas=[],
    hiddenimports=["mangatl.ui.main_window"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Qt is large. Drop the subsystems this app does not use rather than
    # shipping them: the installer size is the user's download.
    excludes=[
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtQuick",
        "PySide6.QtQml",
        "PySide6.Qt3DCore",
        "PySide6.QtMultimedia",
        "tkinter",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="mangatl",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="mangatl",
)
