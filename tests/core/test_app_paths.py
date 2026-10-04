"""MT-027 PO-1: `mangatl.app_paths.settings_path`, MT-024's planned signature.

`%APPDATA%\\mangatl\\settings.json`, spelled out here rather than derived, and
the fallback under the user's home when `APPDATA` is unset. Nothing is created:
asking where the file lives must not make the folder.

RED: `mangatl.app_paths` does not exist, so this file fails at import.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mangatl.app_paths import settings_path


def test_the_settings_file_is_mangatl_settings_json_under_appdata(appdata: Path) -> None:
    assert settings_path() == appdata / "mangatl" / "settings.json"


def test_the_settings_file_follows_appdata_when_it_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Read at call time, not captured at import: the conftest points APPDATA
    # somewhere new for every test.
    monkeypatch.setenv("APPDATA", str(tmp_path / "elsewhere"))
    assert settings_path() == tmp_path / "elsewhere" / "mangatl" / "settings.json"


def test_without_appdata_the_settings_file_is_under_the_home_roaming_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))

    assert (
        settings_path() == tmp_path / "home" / "AppData" / "Roaming" / "mangatl" / "settings.json"
    )


def test_asking_where_the_settings_file_lives_creates_nothing(appdata: Path) -> None:
    settings_path()
    assert list(appdata.iterdir()) == []
