"""Writing the sibling output folder: one file per page, atomically.

AC-6 and AC-7. The folder is `<source>_en/`, a sibling of the user's scans and
never a child of them (`architecture.md` §5): the source folder is opened for
reading and nothing else, for the whole life of a project.

Two things here are decisions rather than detail:

- **Every file goes to a temporary name inside the output folder and is renamed
  onto its final name only once its bytes are all written.** `os.replace` is
  atomic on the same filesystem on Windows and POSIX alike; a write straight to
  the final name leaves a half-written page under the name the user trusts. The
  temp is removed in a `finally`, so a failure between the write and the rename
  leaves no stray file behind either - a folder the tool cannot account for is
  the same defect as a partial page, one directory entry over.
- **`os.replace` is called as an attribute of `os`.** `from os import replace`
  would bind the name at import time and make AC-7's injected failure - a
  `monkeypatch.setattr(os, "replace", ...)` - silently do nothing.

**Contents are replaced, not merged.** A page from a previous chapter left in
the folder would break the "exactly the same filenames as the input" promise
with a file the user cannot account for, so the folder is emptied first rather
than written over.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from mangatl.store.project import Project

__all__ = ["write_output_folder"]

#: Suffix for the half-written file. It lives in the output folder so that
#: `os.replace` stays a same-filesystem rename, and so that nothing is ever
#: staged beside the user's scans.
_TEMP_SUFFIX = ".part"


def write_output_folder(project: Project, output_dir: Path) -> None:
    """Write every page of `project`'s chapter into `output_dir`.

    The folder is created if absent and emptied if not. Each page's bytes are
    its current rendered output, which for this story is the input scan
    unchanged - no stage has rewritten a pixel yet.

    An `OSError` from the filesystem propagates: the caller decides what a
    failed export means, and a writer that swallowed it would report a complete
    folder that is not one. Whatever was written before the failure stays, whole
    and correctly named; nothing partial and no temporary file survives.
    """
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    source_dir = project.chapter.source_dir
    for page in project.pages():
        _write_atomically(output_dir / page.filename, (source_dir / page.filename).read_bytes())


def _write_atomically(destination: Path, payload: bytes) -> None:
    """Write `payload` to a temp file beside `destination`, then rename onto it."""
    temporary = destination.with_name(destination.name + _TEMP_SUFFIX)
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, destination)
    finally:
        # A no-op after a successful rename, and the cleanup after a failed one.
        temporary.unlink(missing_ok=True)
