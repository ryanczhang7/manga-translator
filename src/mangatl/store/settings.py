"""``settings.json``: the lettering-font setting (MT-027) and the Gemini API key (MT-077).

The user edits the JSON by hand, so a font folder that cannot be used is
reported - a ``str`` naming the file and why - rather than read as "no
override": a setting the user wrote and the app silently ignored is what MT-027
exists to prevent.

The API key is read as ``None`` whenever it is not a usable string: the key is
itself a ``str``, so a detail would be indistinguishable from a key. A file the
app cannot parse surfaces at the write instead (``SettingsUnreadable``), where
the user is acting, and is never overwritten - a hand-edited file the app
cannot parse is the user's, not the app's to replace.

``write_setting`` is atomic: the new contents go to a temp file in the same
folder and land with one ``os.replace``, so a crash mid-write leaves the old
file or the new one, never half of either. A key appears in a message or a log
line only as ``mask_key`` renders it (MT-077 AC-5). Pure: no Qt, no SDK.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

__all__ = [
    "API_KEY_SETTING",
    "SETTING_KEY",
    "SettingsUnreadable",
    "gemini_api_key",
    "lettering_font_dir",
    "mask_key",
    "write_setting",
]

SETTING_KEY = "lettering_font_dir"
API_KEY_SETTING = "gemini_api_key"


class SettingsUnreadable(Exception):
    """The existing settings file cannot be parsed as a JSON object. The
    message names the file and why - never the value being written."""


def lettering_font_dir(settings_file: Path) -> Path | str | None:
    """The configured font folder; ``None`` for none; a ``str`` detail when unreadable.

    | the file | returns |
    |---|---|
    | absent; key absent; ``null``; ``""`` | ``None`` |
    | a non-empty string | ``Path(value).expanduser()`` |
    | unreadable, not JSON, not an object, not a string | ``"{file} could not be read: {why}"`` |

    A leading UTF-8 BOM (``EF BB BF``, as older Notepad saves) is skipped, as if
    it were not there (PO-8); it is not "unreadable".
    """
    try:
        settings = _read_object(settings_file)
    except SettingsUnreadable as error:
        return str(error)
    value = settings.get(SETTING_KEY)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        return _unreadable(settings_file, f"{SETTING_KEY} is not a string")
    return Path(value).expanduser()


def gemini_api_key(settings_file: Path) -> str | None:
    """The stored Gemini API key exactly as stored, or ``None``.

    ``None`` for: no file; the key absent, ``null`` or ``""``; a value that is
    not a string; a file that is unreadable, not JSON or not an object. A
    leading UTF-8 BOM is skipped. Never raises.
    """
    try:
        settings = _read_object(settings_file)
    except SettingsUnreadable:
        return None
    value = settings.get(API_KEY_SETTING)
    if not isinstance(value, str) or value == "":
        return None
    return value


def write_setting(settings_file: Path, key: str, value: str) -> None:
    """Set ``key`` to ``value`` in ``settings_file``, keeping every other key.

    An absent file is ``{}``; its folder is created. A file that exists but
    cannot be parsed as a JSON object raises ``SettingsUnreadable`` and is left
    as it is. Written as indented UTF-8 JSON without a BOM, through a temp file
    in the same folder and one ``os.replace``; if anything fails after the temp
    file exists, the temp file is removed and the error propagates.
    """
    settings = _read_object(settings_file)
    settings[key] = value
    data = (json.dumps(settings, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(
        dir=settings_file.parent, prefix=f".{settings_file.name}.", suffix=".tmp"
    )
    temp = Path(name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        os.replace(temp, settings_file)
    except BaseException:
        # `Path.unlink`, never `os.replace`: a test may have replaced that.
        temp.unlink(missing_ok=True)
        raise


def mask_key(key: str) -> str:
    """``"****"`` and the key's last four characters - the only form a key may
    take in a log line or a message (AC-5). A key of four characters or fewer
    shows none of them."""
    return "****" + key[-4:] if len(key) > 4 else "****"


def _read_object(settings_file: Path) -> dict[str, Any]:
    """The file's JSON object; ``{}`` when the file is absent.

    Raises ``SettingsUnreadable`` when it cannot be read, is not JSON, or is
    not an object.
    """
    try:
        text = settings_file.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError) as error:
        raise SettingsUnreadable(_unreadable(settings_file, str(error))) from None
    try:
        settings = json.loads(text)
    except json.JSONDecodeError as error:
        raise SettingsUnreadable(_unreadable(settings_file, str(error))) from None
    if not isinstance(settings, dict):
        raise SettingsUnreadable(_unreadable(settings_file, "not a JSON object"))
    return settings


def _unreadable(settings_file: Path, why: str) -> str:
    return f"{settings_file} could not be read: {why}"
