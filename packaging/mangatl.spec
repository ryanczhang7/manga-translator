# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-folder build.

One folder, not one file: the shipped app carries ~1 GB of .onnx weights
(stack.md §3), and a one-file build unpacks all of it to a temp directory on
every launch. Run from the repository root, after the weights are fetched:

    uv run python packaging/fetch_models.py
    uv run pyinstaller --noconfirm packaging/mangatl.spec

`dist/` and `build/` are gitignored.
"""

import glob
import importlib.util
import json
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))
SRC = os.path.join(ROOT, "src")
PACKAGING = os.path.join(ROOT, "packaging")
UI = os.path.join(SRC, "mangatl", "ui")

# MT-024 C-1, C-4: the weights `packaging/fetch_models.py` fetched, one entry per
# manifest line, each to `models/<dirname of its path>` - the layout
# `mangatl.compose` reads, under `mangatl.app_paths.bundled_models_dir()`. The
# manifest is READ here and no weight is ever statted (PO-6): the spec is
# executed by unit tests on machines with no weights, and PyInstaller's own
# "Unable to find" is the refusal if the fetch was skipped.
with open(os.path.join(PACKAGING, "models.json"), encoding="utf-8") as handle:
    MODELS = json.load(handle)["models"]
MODEL_DATAS = [
    (
        os.path.join(PACKAGING, "models", *entry["path"].split("/")),
        "/".join(["models", *entry["path"].split("/")[:-1]]),
    )
    for entry in MODELS
]

# MT-024 C-4, PO-1: the CUDA and cuDNN runtime DLLs from the venv's `nvidia`
# namespace package, to the same relative places in `_internal/`. In 1.30.0
# `onnxruntime.preload_dlls()` looks for them under
# `<dirname(onnxruntime.__file__)>/../nvidia/...`, which in the frozen tree is
# `_internal/nvidia/...`. Without them the app runs on the CPU silently.
_NVIDIA = importlib.util.find_spec("nvidia")
CUDA_BINARIES = [
    (dll, dest)
    for base in (_NVIDIA.submodule_search_locations if _NVIDIA else [])
    for subdir, dest in (
        (os.path.join("cu13", "bin", "x86_64"), "nvidia/cu13/bin/x86_64"),
        (os.path.join("cudnn", "bin"), "nvidia/cudnn/bin"),
    )
    for dll in sorted(glob.glob(os.path.join(base, subdir, "*.dll")))
]

a = Analysis(
    [os.path.join(SRC, "mangatl", "app.py")],
    pathex=[SRC],
    binaries=CUDA_BINARIES,
    datas=[
        # MT-020 (C-7): the four lettering faces and OFL.txt, to the place
        # `mangatl.typeset.font.FONT_DIR` resolves to inside the frozen package.
        # The OFL requires the licence to travel with the fonts; never subset.
        (os.path.join(SRC, "mangatl", "typeset", "fonts"), "mangatl/typeset/fonts"),
        *MODEL_DATAS,
        # The manifest travels with the weights: the startup check verifies
        # against `_internal/models/models.json` (MT-024 C-3, AC-5).
        (os.path.join(PACKAGING, "models.json"), "models"),
        # MT-025 PO-8, MT-061 PO-1: the theme and both templates are read as
        # package resources at startup, and PyInstaller bundles only modules.
        (os.path.join(UI, "theme.qss"), "mangatl/ui"),
        (os.path.join(UI, "theme.qss.tmpl"), "mangatl/ui"),
        (os.path.join(UI, "theme_hc.qss.tmpl"), "mangatl/ui"),
    ],
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
