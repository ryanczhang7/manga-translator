"""MT-024 C-4: what `packaging/mangatl.spec` hands PyInstaller.

The spec is EXECUTED with stub `Analysis`/`PYZ`/`EXE`/`COLLECT`, exactly as
`test_typeset_packaging.py` does, and the `datas` and `binaries` it passes to
`Analysis` are read back. This needs no weights on the machine (PO-6: the spec
reads `packaging/models.json` and never stats a weight), and that is part of
what is pinned: on CI, where `packaging/models/` does not exist at `unit` time,
the spec still executes.

The built tree itself is judged by `tests/frozen` after `build`; this file
judges the instruction, that one the outcome.

**`datas`, in C-4's order, exactly ten entries:** the fonts entry first and
unchanged (MT-020), then one `(packaging/models/<path>, models/<dirname>)` per
manifest entry in manifest order, then `(packaging/models.json, models)`, then
the three theme artefacts to `mangatl/ui`. Sources are compared resolved;
destinations with `\\` and `/` unified and a trailing separator dropped, so
`models` and `models/` (what `os.path.join("models", "")` makes of a file at
the top of the directory) are the same destination.

**`binaries`:** every `*.dll` under the venv's `nvidia/cu13/bin/x86_64/` and
`nvidia/cudnn/bin/` is a source. The *destination* is deliberately not pinned:
C-4 calls the placement checkable, not sacred, and GREEN may move it after
reading `provider:` off `mangatl.exe --check`.

RED: the spec has one `datas` entry and an empty `binaries`; the manifest
does not exist. The assertions fail on that.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path, PurePosixPath
from typing import Any

import _settled_models as settled

SPEC = settled.REPO_ROOT / "packaging" / "mangatl.spec"
SRC = settled.REPO_ROOT / "src"


class _Stub:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        type(self).calls.append((args, kwargs))
        self.pure: list[Any] = []
        self.scripts: list[Any] = []
        self.binaries: list[Any] = list(kwargs.get("binaries", []))
        self.datas: list[Any] = list(kwargs.get("datas", []))


def _analysis_kwargs() -> dict[str, Any]:
    analysis = type("Analysis", (_Stub,), {"calls": []})
    namespace: dict[str, Any] = {
        "__name__": "__main__",
        "__file__": str(SPEC),
        "SPECPATH": str(SPEC.parent),
        "Analysis": analysis,
        "PYZ": type("PYZ", (_Stub,), {"calls": []}),
        "EXE": type("EXE", (_Stub,), {"calls": []}),
        "COLLECT": type("COLLECT", (_Stub,), {"calls": []}),
    }
    exec(compile(SPEC.read_text(encoding="utf-8"), str(SPEC), "exec"), namespace)
    assert len(analysis.calls) == 1
    _, kwargs = analysis.calls[0]
    return kwargs


def _norm(dest: str) -> str:
    return str(PurePosixPath(dest.replace("\\", "/")))


def _pairs(key: str) -> list[tuple[Path, str]]:
    return [(Path(src).resolve(), _norm(str(dest))) for src, dest in _analysis_kwargs()[key]]


def _expected_datas() -> list[tuple[Path, str]]:
    root = settled.REPO_ROOT
    models = [
        (
            (root / "packaging" / "models" / str(entry["path"])).resolve(),
            _norm(str(PurePosixPath("models") / PurePosixPath(str(entry["path"])).parent)),
        )
        for entry in settled.SETTLED_ENTRIES
    ]
    ui = SRC / "mangatl" / "ui"
    return [
        ((SRC / "mangatl" / "typeset" / "fonts").resolve(), "mangatl/typeset/fonts"),
        *models,
        ((root / "packaging" / "models.json").resolve(), "models"),
        ((ui / "theme.qss").resolve(), "mangatl/ui"),
        ((ui / "theme.qss.tmpl").resolve(), "mangatl/ui"),
        ((ui / "theme_hc.qss.tmpl").resolve(), "mangatl/ui"),
    ]


def test_the_expected_model_destinations_are_the_two_directories_of_the_layout() -> None:
    """Fixture check on `_expected_datas`: a top-level weight goes to `models`,
    an OCR file to `models/manga-ocr`."""
    destinations = [dest for _, dest in _expected_datas()[1:6]]
    assert destinations == [
        "models",
        "models/manga-ocr",
        "models/manga-ocr",
        "models/manga-ocr",
        "models",
    ]


def test_the_spec_ships_fonts_weights_manifest_and_theme_in_that_order() -> None:
    datas = _pairs("datas")
    expected = _expected_datas()

    assert datas == expected, (
        "packaging/mangatl.spec datas differ from C-4:\n"
        + "\n".join(f"  got      {src} -> {dest}" for src, dest in datas)
        + "\n"
        + "\n".join(f"  expected {src} -> {dest}" for src, dest in expected)
    )


def test_the_model_entries_follow_the_manifest_the_spec_reads() -> None:
    """The weights come from `packaging/models.json`, not from a list in the
    spec: every manifest `path` has a source under `packaging/models/`."""
    assert settled.MANIFEST.is_file(), f"{settled.MANIFEST} does not exist (MT-024 C-1)"
    manifest = json.loads(settled.MANIFEST.read_text("utf-8"))
    models_dir = (settled.REPO_ROOT / "packaging" / "models").resolve()
    sources = [src for src, _ in _pairs("datas") if src.is_relative_to(models_dir)]

    assert sources == [(models_dir / entry["path"]).resolve() for entry in manifest["models"]]


def _nvidia_dlls() -> list[Path]:
    spec = importlib.util.find_spec("nvidia")
    assert spec is not None and spec.submodule_search_locations, "no nvidia package in the venv"
    found: list[Path] = []
    for location in spec.submodule_search_locations:
        base = Path(location)
        found += sorted((base / "cu13" / "bin" / "x86_64").glob("*.dll"))
        found += sorted((base / "cudnn" / "bin").glob("*.dll"))
    return [path.resolve() for path in found]


def test_the_venv_holds_the_twenty_cuda_runtime_dlls_the_story_measured() -> None:
    """The premise of the next test, measured at PLANNED: 10 under
    `nvidia/cu13/bin/x86_64`, 10 under `nvidia/cudnn/bin`. If the locked
    runtime changes, this goes red first, saying so."""
    assert len(_nvidia_dlls()) == 20, [path.name for path in _nvidia_dlls()]


def test_the_spec_bundles_every_cuda_runtime_dll_from_the_venv() -> None:
    """C-4 / PO-1: without these the frozen app falls through to CPU silently
    (MT-002 E2). Destination unpinned - see the module docstring."""
    bundled = {src for src, _ in _pairs("binaries")}
    missing = [path.name for path in _nvidia_dlls() if path not in bundled]

    assert missing == [], f"the spec does not bundle {len(missing)} CUDA DLLs: {missing}"
