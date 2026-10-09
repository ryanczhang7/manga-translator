"""MT-024 AC-7: the installed app loads its theme, fonts and weights - `--check`.

`dist\\mangatl\\mangatl.exe --check <report>` is run as a subprocess and the
report FILE is read (a `console=False` binary has no stdout). It must exit 0
and hold exactly C-6's six lines, in order, each matched whole by an anchored
pattern. This is the only place a frozen `importlib.resources` lookup is
exercised (MT-025 PO-8, MT-061 PO-1), and where GREEN reads
`provider: CUDAExecutionProvider` on this machine to verify C-4's DLL
placement.

**The negative control** alters one bundled weight in the built tree -
`manga-ocr/vocab.txt`, the smallest, so nothing else about the run changes -
by appending one byte, runs `--check` again, and requires exit 1 with the
`models:` line naming that file and both hashes. The byte is removed in a
`finally` by truncating the file back to the manifest's byte count, and the
restore is verified by re-hashing. The tree is never copied: it is ~2.5 GB.

**Budget.** No pytest timeout plugin is installed, so the subprocess timeout
is the only budget in this file and there are no hooks to size. It is an
expression over what drives the cost - a fixed launch-and-load base plus the
manifest's bytes at a hashing floor - not a constant:
`LAUNCH_S + total_bytes / HASH_FLOOR`. Neither number is measured yet: in
RED the binary has no `--check` (the stale one opens a notice window and
waits, and the timeout is what ends it). GATES records the measured wall
time of `--check` under `## Notes` (the story's settled decision) and should
re-derive both from it, locally and from a CI log.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest
from _frozen_tree import MANIFEST, sha256_of

#: Seconds to start the frozen interpreter, import PySide6 and onnxruntime and
#: load the detector onto a provider. NOT MEASURED - a placeholder for GATES.
LAUNCH_S = 60.0
#: A floor on `hashlib.sha256` throughput through the frozen app, bytes/s,
#: conservative for a CI runner's disk. NOT MEASURED.
HASH_FLOOR = 25_000_000

#: C-6's six lines, whole-line patterns, in order.
REPORT = (
    r"theme: ok \(\d+ bytes\)",
    r"theme-template: ok \(\d+ bytes\)",
    r"theme-hc-template: ok \(\d+ bytes\)",
    r"fonts: ok \(4 faces, OFL\.txt\)",
    r"models: ok \(5 verified\)",
    r"provider: (CUDA|CPU)ExecutionProvider",
)

#: The weight the control alters, and its settled facts (C-1).
ALTERED = "manga-ocr/vocab.txt"


def _entries() -> list[dict[str, object]]:
    entries: list[dict[str, object]] = json.loads(MANIFEST.read_text(encoding="utf-8"))["models"]
    return entries


def _budget(entries: list[dict[str, object]]) -> float:
    total = sum(int(str(entry["bytes"])) for entry in entries)
    return LAUNCH_S + total / HASH_FLOOR


def _check(built_tree: Path, report: Path, entries: list[dict[str, object]]) -> int:
    try:
        completed = subprocess.run(
            [str(built_tree / "mangatl.exe"), "--check", str(report)],
            cwd=str(built_tree.parent),
            timeout=_budget(entries),
            check=False,
            capture_output=True,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(
            f"mangatl.exe --check did not exit within {_budget(entries):.0f} s: a binary"
            " without --check opens a window and waits (C-6: --check returns before any"
            " QApplication)",
            pytrace=False,
        )
    return completed.returncode


def _lines(report: Path) -> list[str]:
    assert report.is_file(), f"--check wrote no report at {report}"
    return report.read_text(encoding="utf-8").splitlines()


def test_check_exits_zero_with_exactly_the_six_lines_in_order(
    built_tree: Path, manifest_entries: list[dict[str, object]], tmp_path: Path
) -> None:
    report = tmp_path / "report.txt"

    code = _check(built_tree, report, manifest_entries)

    lines = _lines(report)
    assert len(lines) == len(REPORT), f"the report has {len(lines)} lines: {lines}"
    for line, pattern in zip(lines, REPORT, strict=True):
        assert re.fullmatch(pattern, line), f"report line {line!r} is not /^{pattern}$/"
    assert code == 0, f"mangatl.exe --check exited {code}; report: {lines}"


def test_the_theme_lines_count_the_bytes_the_package_ships(
    built_tree: Path, manifest_entries: list[dict[str, object]], tmp_path: Path
) -> None:
    report = tmp_path / "report.txt"
    _check(built_tree, report, manifest_entries)
    ui = built_tree / "_internal" / "mangatl" / "ui"

    assert _lines(report)[:3] == [
        f"theme: ok ({(ui / 'theme.qss').stat().st_size} bytes)",
        f"theme-template: ok ({(ui / 'theme.qss.tmpl').stat().st_size} bytes)",
        f"theme-hc-template: ok ({(ui / 'theme_hc.qss.tmpl').stat().st_size} bytes)",
    ]


def test_check_refuses_an_altered_weight_naming_it_and_restores_it(
    built_tree: Path, manifest_entries: list[dict[str, object]], tmp_path: Path
) -> None:
    """The negative control: one byte appended to a bundled weight."""
    (entry,) = [e for e in manifest_entries if e["path"] == ALTERED]
    expected_sha = str(entry["sha256"])
    size = int(str(entry["bytes"]))
    weight = built_tree / "_internal" / "models" / ALTERED
    assert weight.is_file(), f"{weight} is not in the built tree (AC-2)"
    assert sha256_of(weight) == expected_sha, f"{weight} did not verify BEFORE the control ran"
    report = tmp_path / "report.txt"

    try:
        with weight.open("ab") as handle:
            handle.write(b"\n")
        altered_sha = hashlib.sha256(weight.read_bytes()).hexdigest()
        code = _check(built_tree, report, manifest_entries)
    finally:
        with weight.open("r+b") as handle:
            handle.truncate(size)

    assert sha256_of(weight) == expected_sha, f"{weight} was NOT restored: rebuild the tree"
    lines = _lines(report)
    assert code == 1, f"--check exited {code} with an altered weight; report: {lines}"
    models = [line for line in lines if line.startswith("models: ")]
    assert models == [f"models: {ALTERED}: sha256 {altered_sha} != {expected_sha}"], lines
