"""The page strip's thumbnail decode (MT-087, `components.md` §`PageStrip`).

A thumbnail is 72 px wide (`layout.md` §"Review workspace": "72px thumbnail +
`space.3` either side") and as tall as the page's STORED aspect makes it - the
geometry comes from the store, as `RunThumbnail` (MT-062) takes it, never from
the decoded image. The decode asks Qt's reader for exactly that size, so the
whole page is never held at full resolution.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage, QImageReader

__all__ = ["THUMBNAIL_WIDTH", "decode_thumbnail", "thumbnail_size"]

#: `layout.md`: a 72 px thumbnail, `space.3` either side of it in the 96 px strip.
THUMBNAIL_WIDTH: int = 72


def thumbnail_size(width: int, height: int) -> QSize:
    """The thumbnail of a page stored as `width` x `height`: 72 px wide, its
    height the page's aspect, never less than 1 px."""
    return QSize(THUMBNAIL_WIDTH, max(1, round(THUMBNAIL_WIDTH * height / width)))


def decode_thumbnail(path: Path, size: QSize) -> QImage | None:
    """The image at `path` scaled to exactly `size`, or None when its bytes do
    not decode (junk, empty, missing, a directory). Never raises: `QImageReader`
    reports every failure through `canRead()` or a null image, not an exception."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    if not reader.canRead():
        return None
    reader.setScaledSize(size)
    image = reader.read()
    return None if image.isNull() else image
