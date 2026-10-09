"""Where the application keeps its own files (MT-024's planned signatures).

MT-027 PO-1 needed ``settings_path`` before MT-024 was built, so it lives here
under the name MT-024 planned for it; MT-024 extends this module rather than
duplicating it. Asking where a file lives creates nothing.

**The bundle (MT-024 C-3).** In a frozen build the shipped files are under
PyInstaller's ``sys._MEIPASS`` (``_internal/``), the weights in ``models/`` with
their manifest beside them. In a checkout the weights are fetched into the
gitignored ``packaging/models/`` and the manifest is the committed
``packaging/models.json`` - beside that directory, not inside it. ``sys.frozen``
and ``sys._MEIPASS`` are read at call time, and nothing here touches the disk.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from mangatl.models.manifest import MANIFEST_FILENAME

__all__ = ["bundled_dir", "bundled_manifest", "bundled_models_dir", "settings_path"]


def settings_path() -> Path:
    """``%APPDATA%\\mangatl\\settings.json``, read from the environment at call time.

    With ``APPDATA`` unset, the same place under the home folder's
    ``AppData\\Roaming``.
    """
    appdata = os.environ.get("APPDATA")
    root = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return root / "mangatl" / "settings.json"


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundled_dir() -> Path:
    """``sys._MEIPASS`` in a frozen build, else the repository root."""
    if _frozen():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]  # set by PyInstaller
    return Path(__file__).resolve().parents[2]


def bundled_models_dir() -> Path:
    """Frozen: ``<bundle>/models``. A checkout: ``packaging/models``."""
    if _frozen():
        return bundled_dir() / "models"
    return bundled_dir() / "packaging" / "models"


def bundled_manifest() -> Path:
    """Frozen: the copy shipped beside the weights. A checkout: the committed
    ``packaging/models.json``."""
    if _frozen():
        return bundled_models_dir() / MANIFEST_FILENAME
    return bundled_dir() / "packaging" / MANIFEST_FILENAME
