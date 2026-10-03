"""MT-020 AC-8(b): the PyInstaller spec carries the font directory into the build.

"The built application tree" is checked without a PyInstaller run (C-7, PO-6):
`packaging/mangatl.spec` is EXECUTED here with stub `Analysis`/`PYZ`/`EXE`/
`COLLECT` callables and `SPECPATH` set, and the `datas` it hands `Analysis` is
read back. The `build` gate is what proves the spec actually freezes.

This file imports nothing from `mangatl`: the expected source directory is
spelled from the repository root (`_typeset_oracle.FONT_DIR`), and
`test_typeset_font.py` pins that `mangatl.typeset.font.FONT_DIR` is the same
place. So in RED this file runs, and fails on its assertion.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import _typeset_oracle as oracle

SPEC = oracle.REPO_ROOT / "packaging" / "mangatl.spec"

#: Where FONT_DIR sits inside the frozen package (C-7).
FROZEN_FONT_DIR = "mangatl/typeset/fonts"


class _Stub:
    """Records its arguments; offers the attributes the spec reads off it."""

    calls: list[tuple[tuple[Any, ...], dict[str, Any]]]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        type(self).calls.append((args, kwargs))
        self.pure: list[Any] = []
        self.scripts: list[Any] = []
        self.binaries: list[Any] = []
        self.datas: list[Any] = list(kwargs.get("datas", []))


def _run_spec() -> list[tuple[str, str]]:
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
    return [(str(src), str(dest)) for src, dest in kwargs["datas"]]


def test_the_spec_ships_the_font_directory_to_its_place_in_the_frozen_package() -> None:
    datas = _run_spec()
    shipped = [dest for src, dest in datas if Path(src).resolve() == oracle.FONT_DIR.resolve()]
    assert shipped == [FROZEN_FONT_DIR], f"datas={datas!r}"
