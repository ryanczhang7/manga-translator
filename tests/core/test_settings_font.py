"""MT-027 PO-1, PO-4: `mangatl.store.settings.lettering_font_dir`.

The one key this story reads from `settings.json`. Three outcomes, pinned by the
`## Contract` (amended in RED with the exact `{error}` for each malformed case):

| settings file | returns |
|---|---|
| absent; key absent; value `null`; value `""` | `None` - no override (AC-1, AC-9) |
| value a non-empty string | `Path(value).expanduser()` |
| unreadable; not JSON; not an object; value not a string | a `str` (row 1b): |
| | `"{settings_file} could not be read: {error}"` |

Never raises. A malformed file is a LOUD fallback (PO-4): a setting the user
wrote and the app ignored is the failure this story exists to prevent, so
"could not be read" must never collapse into `None`.

RED: `mangatl.store.settings` does not exist, so this file fails at import.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mangatl.store.settings import SETTING_KEY, lettering_font_dir


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "settings.json"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_setting_is_called_lettering_font_dir() -> None:
    assert SETTING_KEY == "lettering_font_dir"


# --- no override ------------------------------------------------------------------


def test_no_settings_file_means_no_override(tmp_path: Path) -> None:
    assert lettering_font_dir(tmp_path / "settings.json") is None


@pytest.mark.parametrize(
    "text",
    [
        "{}",
        '{"lettering_font_dir": null}',
        '{"lettering_font_dir": ""}',
        '{"api_key_set": true, "theme": "dark"}',
    ],
    ids=["empty-object", "null", "empty-string", "other-keys-only"],
)
def test_a_settings_file_without_a_font_folder_means_no_override(tmp_path: Path, text: str) -> None:
    assert lettering_font_dir(_write(tmp_path, text)) is None


# --- an override ------------------------------------------------------------------


def test_a_folder_named_in_settings_is_returned_as_a_path(tmp_path: Path) -> None:
    folder = tmp_path / "My Fonts" / "Comic"
    settings = _write(tmp_path, json.dumps({"lettering_font_dir": str(folder), "other": 1}))

    result = lettering_font_dir(settings)

    assert isinstance(result, Path)
    assert result == folder


def test_the_folder_is_returned_whether_or_not_it_exists(tmp_path: Path) -> None:
    # Existence is resolve_faces' question (row 1), reported with the path.
    folder = tmp_path / "not there"
    assert lettering_font_dir(
        _write(tmp_path, json.dumps({"lettering_font_dir": str(folder)}))
    ) == (folder)


def test_a_folder_under_the_home_directory_is_expanded(tmp_path: Path) -> None:
    settings = _write(tmp_path, json.dumps({"lettering_font_dir": "~/fonts/comic"}))
    assert lettering_font_dir(settings) == Path("~/fonts/comic").expanduser()


# --- row 1b: a settings file the app cannot use is reported, not ignored ------------


def test_a_settings_file_that_is_not_json_is_reported_with_the_parse_error(
    tmp_path: Path,
) -> None:
    text = '{"lettering_font_dir": "C:/fonts",'  # truncated: the user's typo
    settings = _write(tmp_path, text)
    with pytest.raises(json.JSONDecodeError) as caught:
        json.loads(text)

    assert lettering_font_dir(settings) == f"{settings} could not be read: {caught.value}"


@pytest.mark.parametrize(
    "text", ['["C:/fonts"]', '"C:/fonts"', "3", "null"], ids=["list", "string", "number", "null"]
)
def test_a_settings_file_that_is_not_a_json_object_is_reported(tmp_path: Path, text: str) -> None:
    settings = _write(tmp_path, text)
    assert lettering_font_dir(settings) == f"{settings} could not be read: not a JSON object"


@pytest.mark.parametrize(
    "value", [3, True, ["C:/fonts"], {"path": "C:/fonts"}], ids=["number", "bool", "list", "object"]
)
def test_a_font_folder_that_is_not_a_string_is_reported(tmp_path: Path, value: object) -> None:
    settings = _write(tmp_path, json.dumps({"lettering_font_dir": value}))
    assert lettering_font_dir(settings) == (
        f"{settings} could not be read: lettering_font_dir is not a string"
    )


def test_a_settings_file_that_cannot_be_opened_is_reported_and_does_not_raise(
    tmp_path: Path,
) -> None:
    # A directory where the file should be: opening it raises an OSError on
    # every platform. The OS's own wording is not pinned - only that the
    # detail names the file, says it could not be read, and carries a reason.
    settings = tmp_path / "settings.json"
    settings.mkdir()

    result = lettering_font_dir(settings)

    prefix = f"{settings} could not be read: "
    assert isinstance(result, str)
    assert result.startswith(prefix)
    assert len(result) > len(prefix), "the detail does not say why the file could not be read"
