"""MT-024 AC-2, AC-3, AC-3b and AC-4: what the built tree holds, and what it must not.

Every assertion walks or reads the REAL `dist/mangatl` the `build` gate wrote
(`conftest.py` fails when there is none), and compares it with the repository's
own files as bytes: `packaging/models.json` and the hashes it pins (AC-2), the
vendored fonts (AC-3), the three theme artefacts (AC-3b). Nothing is compared
with the spec - the spec is `tests/core/test_spec_datas.py`'s - because a spec
that says the right thing and a tree that holds it are different claims, and
only the second is what a user installs.

**AC-4's forbidden set is an explicit list**, here and nowhere else, and the
walk is over every path under `dist/mangatl/`. DV-2 (GATES) adds
`(os.path.join(ROOT, "docs"), "docs")` to the spec's `datas`, rebuilds, and
this must go red: that is the probe that makes the exclusion real, and the
`frozen` gate's own "seen to fail" probe.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _frozen_tree import MANIFEST, MISSING_TREE, REPO_ROOT, require_tree, sha256_of

SRC = REPO_ROOT / "src" / "mangatl"

#: AC-4, spelled out: the names that never ship.
FORBIDDEN = frozenset(
    {".claude", "docs", "scripts", ".github", "tests", "fixtures", "spikes", "packaging"}
)

FACES = (
    "Shantell_Sans-Normal-Regular.otf",
    "Shantell_Sans-Normal-Regular_Italic.otf",
    "Shantell_Sans-Normal-Bold.otf",
    "Shantell_Sans-Normal-Bold_Italic.otf",
)
THEME = ("theme.qss", "theme.qss.tmpl", "theme_hc.qss.tmpl")


# -- C-8: no tree is a failure, not a skip ----------------------------------------


def test_a_missing_tree_fails_with_the_instruction_that_builds_it(tmp_path: Path) -> None:
    """Negative control for `conftest.built_tree`: a directory with no
    `mangatl.exe` is a FAILURE carrying `run ... --gate build first`, never a
    skip. `pytest.fail` raises `Failed`; `pytest.skip` would raise `Skipped`,
    which this would not catch."""
    with pytest.raises(pytest.fail.Exception) as raised:
        require_tree(tmp_path / "dist" / "mangatl")

    assert str(raised.value) == f"no built tree at {tmp_path / 'dist' / 'mangatl'}: {MISSING_TREE}"


def test_a_tree_without_its_internal_directory_is_not_a_built_tree(tmp_path: Path) -> None:
    dist = tmp_path / "mangatl"
    dist.mkdir()
    (dist / "mangatl.exe").write_bytes(b"MZ")

    with pytest.raises(pytest.fail.Exception):
        require_tree(dist)


# -- AC-2: the weights, at their manifest paths, with their manifest hashes ----------


def test_every_manifest_entry_is_bundled_with_its_manifest_hash(
    internal: Path, manifest_entries: list[dict[str, object]]
) -> None:
    problems = []
    for entry in manifest_entries:
        path = internal / "models" / str(entry["path"])
        if not path.is_file():
            problems.append(f"{entry['path']}: missing from {internal / 'models'}")
            continue
        actual = sha256_of(path)
        if actual != entry["sha256"]:
            problems.append(f"{entry['path']}: sha256 {actual} != {entry['sha256']}")

    assert len(manifest_entries) == 5, f"the manifest names {len(manifest_entries)} models"
    assert problems == [], "\n".join(problems)


def test_the_bundled_manifest_is_byte_identical_to_the_committed_one(internal: Path) -> None:
    bundled = internal / "models" / "models.json"

    assert bundled.is_file(), f"{bundled} is missing"
    assert bundled.read_bytes() == MANIFEST.read_bytes()


def test_the_models_directory_holds_the_manifest_and_its_entries_and_nothing_else(
    internal: Path, manifest_entries: list[dict[str, object]]
) -> None:
    models = internal / "models"
    shipped = sorted(p.relative_to(models).as_posix() for p in models.rglob("*") if p.is_file())

    assert shipped == sorted([*(str(entry["path"]) for entry in manifest_entries), "models.json"])


# -- AC-3: the four faces and the licence ----------------------------------------------


@pytest.mark.parametrize("name", [*FACES, "OFL.txt"])
def test_the_lettering_font_ships_byte_identical_to_the_vendored_file(
    internal: Path, name: str
) -> None:
    shipped = internal / "mangatl" / "typeset" / "fonts" / name

    assert shipped.is_file(), f"{shipped} is missing"
    assert shipped.read_bytes() == (SRC / "typeset" / "fonts" / name).read_bytes()


# -- AC-3b: the theme artefacts ------------------------------------------------------


@pytest.mark.parametrize("name", THEME)
def test_the_theme_artefact_ships_byte_identical_to_the_package_resource(
    internal: Path, name: str
) -> None:
    shipped = internal / "mangatl" / "ui" / name

    assert shipped.is_file(), f"{shipped} is missing: the frozen app cannot load its theme"
    assert shipped.read_bytes() == (SRC / "ui" / name).read_bytes()


# -- AC-4: the agentic scaffolding never ships -------------------------------------------


def _every_path(root: Path) -> list[Path]:
    return [path.relative_to(root) for path in root.rglob("*")]


def test_nothing_under_internal_starts_with_a_forbidden_name(internal: Path) -> None:
    offenders = sorted(
        {path.parts[0] for path in _every_path(internal) if path.parts[0] in FORBIDDEN}
    )

    assert offenders == [], f"_internal/ ships {offenders}"


def test_nothing_under_the_frozen_package_has_a_forbidden_component(internal: Path) -> None:
    package = internal / "mangatl"
    assert package.is_dir(), f"{package} is missing"
    offenders = sorted(
        path.as_posix()
        for path in _every_path(package)
        if any(part in FORBIDDEN for part in path.parts)
    )

    assert offenders == [], f"_internal/mangatl/ ships {offenders}"


def test_nothing_beside_the_executable_has_a_forbidden_name(built_tree: Path) -> None:
    offenders = sorted(path.name for path in built_tree.iterdir() if path.name in FORBIDDEN)

    assert offenders == [], f"dist/mangatl/ ships {offenders}"


def test_the_walk_sees_a_forbidden_directory_when_one_is_there(tmp_path: Path) -> None:
    """Negative control for the two walks above, on a synthetic tree: one
    forbidden top-level name and one nested inside the package are both found,
    and a permitted name that merely contains a forbidden one is not."""
    internal = tmp_path / "_internal"
    (internal / "docs" / "wiki").mkdir(parents=True)
    (internal / "mangatl" / "ui" / "tests").mkdir(parents=True)
    (internal / "mangatl" / "scriptsy").mkdir(parents=True)
    (internal / "dist-docs").mkdir(parents=True)

    top = sorted({p.parts[0] for p in _every_path(internal) if p.parts[0] in FORBIDDEN})
    nested = sorted(
        p.as_posix()
        for p in _every_path(internal / "mangatl")
        if any(part in FORBIDDEN for part in p.parts)
    )

    assert top == ["docs"]
    assert nested == ["ui/tests"]
