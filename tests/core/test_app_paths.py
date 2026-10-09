"""MT-027 PO-1: `mangatl.app_paths.settings_path`, MT-024's planned signature.

`%APPDATA%\\mangatl\\settings.json`, spelled out here rather than derived, and
the fallback under the user's home when `APPDATA` is unset. Nothing is created:
asking where the file lives must not make the folder.

RED: `mangatl.app_paths` does not exist, so this file fails at import.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import mangatl.app_paths as app_paths
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


# =============================================================================
# MT-024 C-3: where the bundled models live, frozen and not
# =============================================================================
#
# `bundled_dir()` is `sys._MEIPASS` in a frozen build and the repository root
# otherwise; the models directory and the manifest hang off it differently in
# the two (C-3). The frozen branch is driven by monkeypatching `sys.frozen` and
# `sys._MEIPASS` - both absent from a normal interpreter, hence `raising=False`.
#
# RED: the three functions do not exist. They are reached through the module
# object inside each test, so the MT-027 tests above keep running.

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def frozen_at(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A frozen interpreter whose bundle is unpacked at a path that does not exist."""
    meipass = tmp_path / "bundle" / "_internal"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    return meipass


@pytest.fixture
def not_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", "/nowhere/that/is/used", raising=False)


def test_unfrozen_the_bundle_is_the_repository_root(not_frozen: None) -> None:
    assert app_paths.bundled_dir() == REPO_ROOT


def test_unfrozen_the_models_are_fetched_into_packaging_models(not_frozen: None) -> None:
    assert app_paths.bundled_models_dir() == REPO_ROOT / "packaging" / "models"


def test_unfrozen_the_manifest_is_the_committed_packaging_models_json(not_frozen: None) -> None:
    # Not `packaging/models/models.json`: in a checkout the manifest is the
    # committed file beside the gitignored download directory (C-3).
    assert app_paths.bundled_manifest() == REPO_ROOT / "packaging" / "models.json"


def test_frozen_false_is_not_frozen(monkeypatch: pytest.MonkeyPatch, frozen_at: Path) -> None:
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert app_paths.bundled_dir() == REPO_ROOT
    assert app_paths.bundled_models_dir() == REPO_ROOT / "packaging" / "models"


def test_frozen_the_bundle_is_meipass(frozen_at: Path) -> None:
    assert app_paths.bundled_dir() == frozen_at


def test_frozen_the_models_are_under_the_bundle(frozen_at: Path) -> None:
    assert app_paths.bundled_models_dir() == frozen_at / "models"


def test_frozen_the_manifest_is_the_copy_shipped_with_the_models(frozen_at: Path) -> None:
    assert app_paths.bundled_manifest() == frozen_at / "models" / "models.json"


def test_the_three_answers_are_paths(frozen_at: Path) -> None:
    answers = [
        app_paths.bundled_dir(),
        app_paths.bundled_models_dir(),
        app_paths.bundled_manifest(),
    ]
    assert all(isinstance(answer, Path) for answer in answers), answers


def test_frozen_asking_where_the_models_live_stats_nothing(
    frozen_at: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-3: none of the three stats anything. Every way `pathlib` and `os`
    ask the filesystem a question is recorded for the duration of the three
    calls - and only that: the patch is undone before anything is asserted, so
    a failure here can still be reported."""
    asked: list[str] = []
    answers: list[object] = []

    def recorder(name: str) -> object:
        def record(*args: object, **kwargs: object) -> bool:
            asked.append(f"{name}{args!r}")
            return False

        return record

    with monkeypatch.context() as patch:
        for name in ("stat", "lstat", "exists", "is_dir", "is_file", "mkdir", "touch"):
            patch.setattr(Path, name, recorder(f"Path.{name}"))
        patch.setattr("os.stat", recorder("os.stat"))
        patch.setattr("os.path.exists", recorder("os.path.exists"))
        patch.setattr("os.path.isdir", recorder("os.path.isdir"))
        try:
            answers = [
                app_paths.bundled_dir(),
                app_paths.bundled_models_dir(),
                app_paths.bundled_manifest(),
            ]
        except Exception as error:  # reported after the patch is gone
            answers = [error]

    assert not any(isinstance(answer, Exception) for answer in answers), answers
    assert asked == [], f"asking where the models live asked the filesystem: {asked}"


def test_asking_where_the_models_live_creates_nothing(frozen_at: Path) -> None:
    app_paths.bundled_dir()
    app_paths.bundled_models_dir()
    app_paths.bundled_manifest()

    assert not frozen_at.parent.exists()
