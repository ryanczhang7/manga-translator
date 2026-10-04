"""Which faces letter the chapter: the shipped ones, or a folder the user named.

MT-027. A configured folder is used only when ``validate_faces`` passes it -
four faces told apart by their ``OS/2`` style bits, each covering
``REQUIRED_CODEPOINTS``. Anything wrong with it falls back to the **shipped**
faces (never a system font), and says why: ``fallback`` and ``detail`` carry
``validate_faces``' reason and sentence unchanged. Nothing wrong with the
override raises; a broken *bundled* directory still does, as ``load_faces``
always has.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from mangatl.typeset.font import (
    FONT_DIR,
    FONT_FAMILY,
    Faces,
    FallbackReason,
    load_faces,
    read_face_folder,
)

__all__ = ["FaceResolution", "FallbackReason", "resolve_faces"]


@dataclass(frozen=True)
class FaceResolution:
    faces: Faces
    source: Literal["default", "override"]
    family: str
    fallback: FallbackReason
    detail: str  # "" exactly when fallback == "none"


def resolve_faces(override_dir: Path | None, bundled_dir: Path = FONT_DIR) -> FaceResolution:
    """The faces to letter in: ``override_dir``'s when it passes, else ``bundled_dir``'s."""
    if override_dir is None:
        return FaceResolution(load_faces(bundled_dir), "default", FONT_FAMILY, "none", "")
    faces, reason, detail, family = read_face_folder(override_dir)
    if faces is None:
        return FaceResolution(load_faces(bundled_dir), "default", FONT_FAMILY, reason, detail)
    return FaceResolution(faces, "override", family, "none", "")
