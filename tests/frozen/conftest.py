"""MT-024 C-8: the `frozen` gate reads the tree the `build` gate produced.

`dist/mangatl` is resolved from the repository root, never from the working
directory. When it is absent every test here **fails** - never skips - with
the one instruction that fixes it: a skipped tree test is a required gate
reporting nothing about the thing this story exists for, and `frozen`'s
evidence line (`[1-9][0-9]* passed`) would not tell the difference from a
gate that did nothing.

The tree this judges may be stale: in RED it is the last `build` gate's output,
from before this story's spec changes. That is what makes AC-2, AC-3b and AC-7
red here and AC-3 and AC-4 green (see the story's handoff).

Nothing here imports `mangatl`: the built tree is judged against the files in
the repository - `packaging/models.json`, `src/mangatl/...` - read as bytes
and JSON, so a defect shared by the source and the frozen copy of it cannot
make the comparison agree with itself.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _frozen_tree import DIST, MANIFEST, require_tree


@pytest.fixture(scope="session")
def built_tree() -> Path:
    """`dist/mangatl`, which must exist."""
    return require_tree(DIST)


@pytest.fixture(scope="session")
def internal(built_tree: Path) -> Path:
    return built_tree / "_internal"


@pytest.fixture(scope="session")
def manifest_entries() -> list[dict[str, object]]:
    """`packaging/models.json`'s entries, read as JSON."""
    if not MANIFEST.is_file():
        pytest.fail(f"{MANIFEST} does not exist (MT-024 C-1)", pytrace=False)
    entries: list[dict[str, object]] = json.loads(MANIFEST.read_text(encoding="utf-8"))["models"]
    return entries
