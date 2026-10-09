"""`models.json`: the one statement of which weights ship, and their hashes.

**MT-024 C-1, C-2.** The manifest is the source of truth for the weights, for
the build's fetch and the app's startup check alike: one parser, one hashing
function and one exception for both. A silently substituted weight is a
correctness failure with no symptom until the output is wrong, so every entry
pins a SHA-256 and `verify_bundled_models` refuses the first that does not hold.

Each entry's `path` is where the file lives **under the models directory**,
with forward slashes as written in the JSON - MT-036 C-6's layout, which
`tests/core/test_fetch_models.py` ties to `mangatl.compose`'s constants.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "MANIFEST_FILENAME",
    "ModelEntry",
    "ModelHashMismatch",
    "load_manifest",
    "sha256_of",
    "verify_bundled_models",
]

#: The manifest's name: committed as `packaging/models.json`, shipped beside the
#: weights as `_internal/models/models.json` (C-3).
MANIFEST_FILENAME: str = "models.json"

#: Bytes read per `update` while hashing: a 343 MB encoder is never one object.
_CHUNK = 1 << 20


@dataclass(frozen=True)
class ModelEntry:
    """One weight file: where it comes from, where it goes, and what it hashes to."""

    name: str
    role: str
    repo: str
    revision: str
    file: str
    path: str
    sha256: str
    bytes: int
    licence: str


class ModelHashMismatch(Exception):
    """A weight is missing, or its bytes are not the manifest's.

    The message is the whole report, and the build and the app both show it as
    it is: `"<path>: missing"` or `"<path>: sha256 <actual> != <expected>"`.
    """


def load_manifest(manifest: Path) -> tuple[ModelEntry, ...]:
    """The entries of `manifest` (`{"models": [...]}`), in file order."""
    document = json.loads(manifest.read_text(encoding="utf-8"))
    return tuple(ModelEntry(**entry) for entry in document["models"])


def sha256_of(path: Path) -> str:
    """The lowercase hex SHA-256 of `path`, read in 1 MiB chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_bundled_models(root: Path, manifest: Path | None = None) -> None:
    """Return when every entry of `manifest` is under `root` with its hash.

    `manifest` defaults to `root / MANIFEST_FILENAME`, which is where the frozen
    tree keeps it; a checkout keeps it beside the download directory instead,
    so callers there pass it (C-6, amended in RED). Raises `ModelHashMismatch`
    for the first entry, in manifest order, that is missing or mis-hashed.
    Reads only.
    """
    for entry in load_manifest(manifest if manifest is not None else root / MANIFEST_FILENAME):
        path = root / entry.path
        if not path.is_file():
            raise ModelHashMismatch(f"{entry.path}: missing")
        actual = sha256_of(path)
        if actual != entry.sha256:
            raise ModelHashMismatch(f"{entry.path}: sha256 {actual} != {entry.sha256}")
