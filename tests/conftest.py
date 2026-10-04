"""Suite-wide isolation from the machine the tests run on.

MT-027 (`## Contract`, "Test isolation"): `bake_chapter` and `preview_bake` now
read `%APPDATA%\\mangatl\\settings.json` (`mangatl.app_paths.settings_path`), so a
developer whose real settings file names a lettering font would bake every
existing bake test in that font - and `tests/core/test_bake.py`'s pixel and
`BakeReport` equality assertions would fail on that machine alone, or worse,
pass on it for the wrong reason.

So every test, in every folder, runs with `APPDATA` pointed at a fresh empty
directory of its own. It is `tmp_path_factory.mktemp`, not `tmp_path`: a test's
own `tmp_path` stays exactly as empty as it was before this fixture existed,
which several suites assert on (`world.contents(...)`, `snapshot(...)`).

`appdata` hands the same directory to a test that wants to write a settings
file into it (`tests/core/_font_fixtures.write_settings`).
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def appdata(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`APPDATA` for this test: a new, empty directory under pytest's basetemp."""
    directory = tmp_path_factory.mktemp("appdata")
    monkeypatch.setenv("APPDATA", str(directory))
    return directory
