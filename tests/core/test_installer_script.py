"""MT-024 AC-8 (the script) and C-7: `packaging/installer.iss`.

Mechanical: the `[Setup]` keys and the `[Files]` and `[Icons]` lines are
parsed out of the script and each value C-7 pins is compared exactly. The
compile itself is the `installer` gate - nothing here runs ISCC - and the
clean-machine clause of AC-8 is a manual verification recorded in `## Notes`,
which no test pretends to be.

Inno Setup has no inline comments in `[Setup]`: a `;` starts a comment only at
the beginning of a line. The `; ...` annotations in C-7's block are the
contract's notes, not part of the file, and a value carrying one would be read
by ISCC as part of the value - so the parser here does exactly what ISCC does,
and a value with a trailing comment fails its equality.

`AppVersion` is compared with `pyproject.toml`'s `[project].version`, read
with `tomllib`, so the two spellings of the version cannot drift.

RED: `packaging/installer.iss` does not exist; every test fails on that.

What these tests do NOT constrain: any `[Setup]` key C-7 does not name (an
`AppPublisher`, a `LicenseFile` - MT-076's), the `[Icons]` section beyond its
one line, and anything in sections C-7 does not mention.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "packaging" / "installer.iss"
PYPROJECT = REPO_ROOT / "pyproject.toml"


def _sections() -> dict[str, list[str]]:
    """Section name (lower-cased, as ISCC treats it) -> its non-comment lines."""
    assert SCRIPT.is_file(), f"{SCRIPT} does not exist (MT-024 C-7)"
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw in SCRIPT.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip().lower()
            sections.setdefault(current, [])
            continue
        assert current is not None, f"{line!r} comes before any section"
        sections[current].append(line)
    return sections


def _setup() -> dict[str, str]:
    lines = _sections().get("setup")
    assert lines, "installer.iss has no [Setup] section"
    keys: dict[str, str] = {}
    for line in lines:
        key, sep, value = line.partition("=")
        assert sep, f"[Setup] line {line!r} is not key=value"
        name = key.strip()
        assert name.lower() not in {k.lower() for k in keys}, f"[Setup] repeats {name}"
        keys[name] = value.strip()
    return keys


#: C-7's `[Setup]` block, every key it names, value for value.
SETUP = {
    "AppName": "mangatl",
    "AppVersion": "0.1.0",
    "DefaultDirName": r"{localappdata}\Programs\mangatl",
    "PrivilegesRequired": "lowest",
    "ArchitecturesAllowed": "x64compatible",
    "ArchitecturesInstallIn64BitMode": "x64compatible",
    "OutputDir": r"..\dist\installer",
    "OutputBaseFilename": "mangatl-setup",
    "Compression": "lzma2/fast",
    "SolidCompression": "no",
    "DisableProgramGroupPage": "yes",
}


@pytest.mark.parametrize("key", list(SETUP))
def test_the_setup_section_sets_each_key_the_contract_pins(key: str) -> None:
    setup = _setup()
    assert key in setup, f"[Setup] has no {key}; it has {sorted(setup)}"
    assert setup[key] == SETUP[key], f"[Setup] {key}={setup[key]!r}; C-7 pins {SETUP[key]!r}"


def test_the_installer_version_is_the_project_version() -> None:
    with PYPROJECT.open("rb") as handle:
        version = tomllib.load(handle)["project"]["version"]

    assert _setup().get("AppVersion") == version, (
        f"installer.iss AppVersion={_setup().get('AppVersion')!r},"
        f" pyproject.toml [project].version={version!r}"
    )


def test_the_installer_never_offers_to_elevate() -> None:
    """Per-user, no UAC, one double-click (AC-8). `PrivilegesRequiredOverridesAllowed`
    would let the user - or a command-line switch - turn `lowest` into an
    administrative install, which is the dialog AC-8 promises never appears."""
    keys = {name.lower() for name in _setup()}
    assert "privilegesrequiredoverridesallowed" not in keys


def test_the_installer_installs_into_a_per_user_directory() -> None:
    # `{localappdata}`, never `{autopf}`/`{pf}`: a Program Files target needs
    # elevation, which `PrivilegesRequired=lowest` would then fail at run time.
    assert _setup()["DefaultDirName"].startswith("{localappdata}\\")


def test_the_files_section_is_the_built_tree_recursively_and_nothing_else() -> None:
    files = _sections().get("files")
    assert files == [
        r'Source: "..\dist\mangatl\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion'
    ], f"[Files] is {files}"


def test_the_start_menu_entry_launches_the_installed_executable() -> None:
    icons = _sections().get("icons")
    assert icons == [r'Name: "{autoprograms}\mangatl"; Filename: "{app}\mangatl.exe"'], (
        f"[Icons] is {icons}"
    )


def test_the_parser_reads_a_trailing_comment_as_part_of_the_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative control for `_setup`: the parse is ISCC's, so C-7's annotation
    copied into the file makes the value wrong, rather than being stripped by
    a kinder parser than the compiler."""
    probe = tmp_path / "installer.iss"
    probe.write_text(
        "; header\n[Setup]\nAppName=mangatl\nPrivilegesRequired=lowest ; per-user\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(f"{__name__}.SCRIPT", probe)

    assert _setup() == {"AppName": "mangatl", "PrivilegesRequired": "lowest ; per-user"}
