"""Where the application keeps its own files (MT-024's planned signatures).

MT-027 PO-1 needed ``settings_path`` before MT-024 was built, so it lives here
under the name MT-024 planned for it; MT-024 extends this module rather than
duplicating it. Asking where a file lives creates nothing.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["settings_path"]


def settings_path() -> Path:
    """``%APPDATA%\\mangatl\\settings.json``, read from the environment at call time.

    With ``APPDATA`` unset, the same place under the home folder's
    ``AppData\\Roaming``.
    """
    appdata = os.environ.get("APPDATA")
    root = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return root / "mangatl" / "settings.json"
