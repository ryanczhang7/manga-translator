"""Fetch the model weights `packaging/models.json` names, verified, before a build.

MT-024 C-1, PO-2. Run from the repository root - the `build` gate does, before
PyInstaller:

    uv run python packaging/fetch_models.py

Each entry is downloaded from
`https://huggingface.co/{repo}/resolve/{revision}/{file}` - a pinned commit,
never a branch - streamed into `packaging/models/{path}.part` and hashed on the
way, and renamed to `{path}` only when its SHA-256 is the manifest's. On a
mismatch the `.part` is removed and the script exits 1 naming the file and both
hashes, so `fetch && pyinstaller` builds nothing. A file already present with
the right hash is not downloaded again: a developer fetches 728 MB once.

`urllib.request` and nothing else: no new dependency. The parser, the hashing
and the exception are `mangatl.models.manifest`'s, the same ones the app's
startup check uses; nothing here imports the inference runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mangatl.models.manifest import ModelHashMismatch, load_manifest, sha256_of

HERE = Path(__file__).resolve().parent
URL = "https://huggingface.co/{repo}/resolve/{revision}/{file}"
_CHUNK = 1 << 20
_TIMEOUT_S = 60


def fetch_all(
    manifest: Path,
    target: Path,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> list[Path]:
    """Download every entry of `manifest` into `target` that is not already
    there with its hash. Returns the paths downloaded, in manifest order.

    Raises `ModelHashMismatch` for a download whose bytes are not the
    manifest's, after removing its `.part`; the file's name is never given to
    bytes that did not verify.
    """
    fetched: list[Path] = []
    for entry in load_manifest(manifest):
        final = target / entry.path
        if final.is_file() and sha256_of(final) == entry.sha256:
            continue
        final.parent.mkdir(parents=True, exist_ok=True)
        part = final.with_name(f"{final.name}.part")
        url = URL.format(repo=entry.repo, revision=entry.revision, file=entry.file)
        digest = hashlib.sha256()
        try:
            with opener(url, timeout=_TIMEOUT_S) as response, part.open("wb") as out:
                while chunk := response.read(_CHUNK):
                    digest.update(chunk)
                    out.write(chunk)
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        actual = digest.hexdigest()
        if actual != entry.sha256:
            part.unlink()
            raise ModelHashMismatch(f"{entry.path}: sha256 {actual} != {entry.sha256}")
        os.replace(part, final)
        fetched.append(final)
    return fetched


def main(
    argv: list[str] | None = None,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> int:
    """Fetch into `--target` (default `packaging/models/`) what `--manifest`
    (default `packaging/models.json`) names. 0 when every file verifies, 1 with
    the mismatch on stderr when one does not."""
    parser = argparse.ArgumentParser(description="Fetch and verify the bundled model weights.")
    parser.add_argument("--manifest", type=Path, default=HERE / "models.json")
    parser.add_argument("--target", type=Path, default=HERE / "models")
    arguments = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        fetched = fetch_all(arguments.manifest, arguments.target, opener=opener)
    except ModelHashMismatch as error:
        print(f"fetch_models: refused: {error}", file=sys.stderr)
        return 1
    print(f"fetch_models: {len(fetched)} downloaded, every weight verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
