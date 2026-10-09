"""Where the built tree is, and the refusal when it is not (MT-024 C-8).

A helper module rather than code in `conftest.py`, so `test_built_tree.py` can
call `require_tree` on a path of its own and watch it refuse - the negative
control for "fails, never skips".
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
DIST: Final = REPO_ROOT / "dist" / "mangatl"
MANIFEST: Final = REPO_ROOT / "packaging" / "models.json"
EXE: Final = DIST / "mangatl.exe"

MISSING_TREE: Final = "run `bash scripts/gates.sh --gate build` first"


def require_tree(dist: Path) -> Path:
    """`dist` if it holds a built `mangatl.exe` and its `_internal`, else a
    test failure carrying the instruction."""
    if not (dist / "mangatl.exe").is_file() or not (dist / "_internal").is_dir():
        pytest.fail(f"no built tree at {dist}: {MISSING_TREE}", pytrace=False)
    return dist


def sha256_of(path: Path) -> str:
    """Streamed, so 343 MB of encoder is never one `bytes` object. Written here
    rather than imported from `mangatl.models.manifest`: the oracle must not
    share the implementation it judges."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
