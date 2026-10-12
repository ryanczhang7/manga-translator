"""MT-077 C-1: the Gemini API key in ``settings.json`` - read, write, mask.

`mangatl.store.settings` is extended, never duplicated: it already reads
``lettering_font_dir`` (MT-027). This file pins the four additions C-1 names -
``API_KEY_SETTING``, ``gemini_api_key``, ``write_setting``, ``SettingsUnreadable``
and ``mask_key`` - and the two properties AC-2 is about:

- **every other key the file already had is preserved by value** (``==`` after
  ``json.loads``, never bytes), the MT-027 ``lettering_font_dir`` above all;
- **the write is atomic**: a temp file in the same directory, then
  ``os.replace`` through this module's ``os``. Making that ``os.replace`` raise
  must leave the original file byte-identical and no temp file behind.

**Oracle: mechanical, pinned exactly** (story `## Contract`). Every expected
value is spelled out here, never read back from the module under test - the
one exception is the serialisation, which C-1 states as a formula
(``json.dumps(obj, indent=2, ensure_ascii=False) + "\\n"``) and this file
evaluates on its own expected object.

RED: the names do not exist yet. The module itself does, so this file collects
and every test fails on its own ``AttributeError``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

import mangatl.store.settings as settings_module

KEY = "AIzaSyD-not-a-real-key-0123456789wxyz"
FONT_DIR = "D:/fonts/フォント"
BOM = b"\xef\xbb\xbf"


def _settings_file(tmp_path: Path) -> Path:
    """Where the file lives, one folder down - as ``%APPDATA%\\mangatl\\``."""
    return tmp_path / "mangatl" / "settings.json"


def _write_json(path: Path, obj: Any, *, bom: bool = False) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (BOM if bom else b"") + json.dumps(obj, indent=2).encode("utf-8")
    path.write_bytes(data)
    return data


def _write_raw(path: Path, data: bytes) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def _serialised(obj: dict[str, Any]) -> bytes:
    """C-1's serialisation, stated as a formula and evaluated here."""
    return (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


# =============================================================================
# The names C-1 adds
# =============================================================================


def test_the_setting_is_called_gemini_api_key() -> None:
    assert settings_module.API_KEY_SETTING == "gemini_api_key"


@pytest.mark.parametrize(
    "name",
    ["API_KEY_SETTING", "SettingsUnreadable", "gemini_api_key", "mask_key", "write_setting"],
)
def test_the_new_names_are_exported_beside_the_font_setting(name: str) -> None:
    exported = settings_module.__all__
    assert name in exported, f"{name} is not in mangatl.store.settings.__all__ ({exported})"
    assert "lettering_font_dir" in exported and "SETTING_KEY" in exported, (
        "the MT-027 exports were removed; C-1 extends the module, never replaces it"
    )


def test_settings_unreadable_is_an_exception() -> None:
    assert issubclass(settings_module.SettingsUnreadable, Exception)


# =============================================================================
# mask_key - the only form a key may take in a log line or a message (AC-5)
# =============================================================================


@pytest.mark.parametrize(
    ("key", "masked"),
    [
        ("abcdefgh", "****efgh"),
        ("abcde", "****bcde"),
        ("abcd", "****"),
        ("abc", "****"),
        ("", "****"),
        (KEY, "****wxyz"),
    ],
    ids=["eight", "five", "four", "three", "empty", "realistic"],
)
def test_a_masked_key_shows_at_most_its_last_four_characters(key: str, masked: str) -> None:
    assert settings_module.mask_key(key) == masked


# =============================================================================
# gemini_api_key - the stored key, or None; never raises
# =============================================================================


def test_the_stored_key_is_returned_as_stored(tmp_path: Path) -> None:
    file = _settings_file(tmp_path)
    _write_json(file, {"gemini_api_key": KEY, "lettering_font_dir": FONT_DIR})

    assert settings_module.gemini_api_key(file) == KEY


def test_the_stored_key_is_not_stripped(tmp_path: Path) -> None:
    file = _settings_file(tmp_path)
    _write_json(file, {"gemini_api_key": f"  {KEY} "})

    assert settings_module.gemini_api_key(file) == f"  {KEY} "


def test_a_leading_bom_is_skipped_when_reading_the_key(tmp_path: Path) -> None:
    file = _settings_file(tmp_path)
    _write_json(file, {"gemini_api_key": KEY}, bom=True)

    assert settings_module.gemini_api_key(file) == KEY


def test_no_settings_file_is_no_key(tmp_path: Path) -> None:
    file = _settings_file(tmp_path)
    assert not file.exists()

    assert settings_module.gemini_api_key(file) is None


@pytest.mark.parametrize(
    "contents",
    [
        {},
        {"lettering_font_dir": FONT_DIR},
        {"gemini_api_key": None},
        {"gemini_api_key": ""},
        {"gemini_api_key": 1234},
        {"gemini_api_key": [KEY]},
        {"gemini_api_key": {"key": KEY}},
        [{"gemini_api_key": KEY}],
        "gemini_api_key",
    ],
    ids=[
        "empty object",
        "key absent",
        "null",
        "empty string",
        "a number",
        "a list",
        "an object",
        "not an object",
        "a bare string",
    ],
)
def test_a_file_without_a_usable_key_is_no_key(tmp_path: Path, contents: Any) -> None:
    file = _settings_file(tmp_path)
    _write_json(file, contents)

    assert settings_module.gemini_api_key(file) is None


@pytest.mark.parametrize(
    "data",
    [b'{"gemini_api_key": "abc', b"", b"\xff\xfe not utf-8 \x80"],
    ids=["truncated json", "empty file", "not utf-8"],
)
def test_an_unparsable_file_is_no_key_and_does_not_raise(tmp_path: Path, data: bytes) -> None:
    file = _settings_file(tmp_path)
    _write_raw(file, data)

    assert settings_module.gemini_api_key(file) is None


def test_a_settings_path_that_is_a_folder_is_no_key(tmp_path: Path) -> None:
    file = _settings_file(tmp_path)
    file.mkdir(parents=True)

    assert settings_module.gemini_api_key(file) is None


# =============================================================================
# write_setting - AC-2
# =============================================================================


def test_the_first_write_creates_the_folder_and_the_file(tmp_path: Path) -> None:
    file = _settings_file(tmp_path)
    assert not file.parent.exists(), "precondition: %APPDATA%\\mangatl does not exist yet"

    settings_module.write_setting(file, "gemini_api_key", KEY)

    assert json.loads(file.read_text(encoding="utf-8")) == {"gemini_api_key": KEY}


def test_every_other_key_the_file_had_is_preserved_by_value(tmp_path: Path) -> None:
    """AC-2: the MT-027 font folder survives, and so does anything else the
    user (or a later story) put in the file."""
    file = _settings_file(tmp_path)
    before = {
        "lettering_font_dir": FONT_DIR,
        "zoom": 1.5,
        "recent": ["D:/manga/ch 01", "D:/manga/ch 02"],
        "nested": {"a": [1, 2, {"b": None}], "c": True},
        "nothing": None,
    }
    _write_json(file, before)

    settings_module.write_setting(file, "gemini_api_key", KEY)

    after = json.loads(file.read_text(encoding="utf-8"))
    assert after.get("lettering_font_dir") == FONT_DIR, (
        f"lettering_font_dir is {after.get('lettering_font_dir')!r} after writing the key;"
        f" AC-2 preserves it as {FONT_DIR!r}"
    )
    assert after == {**before, "gemini_api_key": KEY}


def test_writing_the_key_again_replaces_only_the_key(tmp_path: Path) -> None:
    file = _settings_file(tmp_path)
    _write_json(file, {"gemini_api_key": "old-key-0000", "lettering_font_dir": FONT_DIR})

    settings_module.write_setting(file, "gemini_api_key", KEY)

    assert json.loads(file.read_text(encoding="utf-8")) == {
        "gemini_api_key": KEY,
        "lettering_font_dir": FONT_DIR,
    }


def test_the_file_is_written_as_indented_utf8_json_without_a_bom(tmp_path: Path) -> None:
    file = _settings_file(tmp_path)
    _write_json(file, {"lettering_font_dir": FONT_DIR})

    settings_module.write_setting(file, "gemini_api_key", KEY)

    data = file.read_bytes()
    assert not data.startswith(BOM), "C-1: UTF-8, no BOM"
    assert data == _serialised({"lettering_font_dir": FONT_DIR, "gemini_api_key": KEY})


def test_a_file_saved_with_a_bom_is_read_and_rewritten_without_one(tmp_path: Path) -> None:
    file = _settings_file(tmp_path)
    _write_json(file, {"lettering_font_dir": FONT_DIR}, bom=True)

    settings_module.write_setting(file, "gemini_api_key", KEY)

    data = file.read_bytes()
    assert not data.startswith(BOM)
    assert json.loads(data.decode("utf-8")) == {
        "lettering_font_dir": FONT_DIR,
        "gemini_api_key": KEY,
    }


def test_the_written_key_reads_back(tmp_path: Path) -> None:
    file = _settings_file(tmp_path)

    settings_module.write_setting(file, settings_module.API_KEY_SETTING, KEY)

    assert settings_module.gemini_api_key(file) == KEY


@pytest.mark.parametrize(
    "data",
    [
        b'{"lettering_font_dir": "D:/fonts",',
        b"[1, 2, 3]\n",
        b'"just a string"\n',
        b"\xff\xfe not utf-8 \x80",
    ],
    ids=["truncated json", "a list", "a string", "not utf-8"],
)
def test_a_file_the_app_cannot_parse_is_refused_and_left_untouched(
    tmp_path: Path, data: bytes
) -> None:
    """A hand-edited file the app cannot parse is the user's, not the app's to
    replace (C-1)."""
    file = _settings_file(tmp_path)
    _write_raw(file, data)

    with pytest.raises(settings_module.SettingsUnreadable) as caught:
        settings_module.write_setting(file, "gemini_api_key", KEY)

    assert file.read_bytes() == data, "the unreadable file was overwritten"
    assert sorted(p.name for p in file.parent.iterdir()) == ["settings.json"], (
        "the refused write left a file behind"
    )
    message = str(caught.value)
    assert message.startswith(f"{file} could not be read: "), (
        f"SettingsUnreadable says {message!r}; C-1 is _unreadable's"
        " '{file} could not be read: {why}'"
    )
    assert KEY not in message and KEY[-8:] not in message, (
        "the refusal's message carries the value being written (AC-5)"
    )


# =============================================================================
# write_setting - atomic (AC-2): temp file in the same folder, then os.replace
# =============================================================================


def test_the_write_lands_through_os_replace_from_the_same_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control for the test below: the write really goes through this
    module's `os.replace`, from a temp file beside the settings file, so making
    that call raise is a crash *between* writing the temp and the rename."""
    file = _settings_file(tmp_path)
    _write_json(file, {"lettering_font_dir": FONT_DIR})
    real_replace = os.replace
    calls: list[tuple[Path, Path]] = []

    def recording(src: Any, dst: Any) -> None:
        calls.append((Path(src), Path(dst)))
        real_replace(src, dst)

    monkeypatch.setattr(settings_module.os, "replace", recording)

    settings_module.write_setting(file, "gemini_api_key", KEY)

    assert len(calls) == 1, f"os.replace was called {len(calls)} times; C-1 is once"
    ((src, dst),) = calls
    assert dst == file
    assert src.parent == file.parent, (
        f"the temp file was {src}; C-1 writes it in the settings file's own folder,"
        " so the rename cannot cross a volume"
    )
    assert src != file
    assert sorted(p.name for p in file.parent.iterdir()) == ["settings.json"]


@pytest.mark.parametrize("existing", [True, False], ids=["file exists", "first write"])
def test_a_crash_at_the_rename_leaves_the_original_file_and_no_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing: bool
) -> None:
    """AC-2: a crash mid-write cannot leave a half file."""
    file = _settings_file(tmp_path)
    before = (
        _write_json(file, {"lettering_font_dir": FONT_DIR, "gemini_api_key": "old-key-0000"})
        if existing
        else None
    )

    def crash(src: Any, dst: Any) -> None:
        raise OSError("the disk went away mid-write")

    monkeypatch.setattr(settings_module.os, "replace", crash)

    with pytest.raises(OSError, match="the disk went away mid-write"):
        settings_module.write_setting(file, "gemini_api_key", KEY)

    if before is not None:
        assert file.read_bytes() == before, "the original settings file changed"
        expected = ["settings.json"]
    else:
        assert not file.exists(), "a settings file appeared although the rename failed"
        expected = []
    left = sorted(p.name for p in file.parent.iterdir()) if file.parent.exists() else []
    assert left == expected, f"the failed write left {left} in {file.parent}; C-1 removes the temp"
