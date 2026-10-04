"""MT-027 test isolation: no test sees the developer's real `%APPDATA%`.

A guard for `tests/conftest.py`, which every bake test now depends on. It
imports nothing from `mangatl`, so it runs (and passes) in RED; it was earned
there by a probe - the fixture's `setenv` removed, this file run, both tests red,
restored - recorded in the story's `## Handoff`.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def test_appdata_points_at_an_empty_directory_under_pytests_temp_root(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    appdata = Path(os.environ["APPDATA"])
    base = tmp_path_factory.getbasetemp().resolve()

    assert appdata.resolve().is_relative_to(base), (
        f"APPDATA is {appdata}, outside pytest's temp root {base}: the real settings leak in"
    )
    assert list(appdata.iterdir()) == []


def test_each_test_gets_its_own_appdata_not_the_one_the_previous_test_wrote_into(
    appdata: Path,
) -> None:
    # The `appdata` fixture and the environment agree, and a file written here
    # cannot be read by the next test (each call to the fixture is a new dir).
    assert Path(os.environ["APPDATA"]) == appdata
    (appdata / "marker").write_text("x", encoding="utf-8")
    assert appdata.name.startswith("appdata")
