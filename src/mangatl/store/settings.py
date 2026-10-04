"""The lettering-font setting from ``settings.json`` (MT-027 PO-1, PO-4).

Only the one key MT-027 reads; MT-024 owns the rest of the file. The user
edits the JSON by hand, so a file that cannot be used is reported - a ``str``
naming the file and why - rather than read as "no override": a setting the
user wrote and the app silently ignored is what MT-027 exists to prevent.
Never raises.
"""

from __future__ import annotations

import json
from pathlib import Path

__all__ = ["SETTING_KEY", "lettering_font_dir"]

SETTING_KEY = "lettering_font_dir"


def lettering_font_dir(settings_file: Path) -> Path | str | None:
    """The configured font folder; ``None`` for none; a ``str`` detail when unreadable.

    | the file | returns |
    |---|---|
    | absent; key absent; ``null``; ``""`` | ``None`` |
    | a non-empty string | ``Path(value).expanduser()`` |
    | unreadable, not JSON, not an object, not a string | ``"{file} could not be read: {why}"`` |
    """
    try:
        text = settings_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as error:
        return _unreadable(settings_file, str(error))
    try:
        settings = json.loads(text)
    except json.JSONDecodeError as error:
        return _unreadable(settings_file, str(error))
    if not isinstance(settings, dict):
        return _unreadable(settings_file, "not a JSON object")
    value = settings.get(SETTING_KEY)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        return _unreadable(settings_file, f"{SETTING_KEY} is not a string")
    return Path(value).expanduser()


def _unreadable(settings_file: Path, why: str) -> str:
    return f"{settings_file} could not be read: {why}"
