"""MT-138: an abort in the test suite keeps its log and prints Qt's last words.

Each probe under `tests/ui/__probe_*.py` is run ONCE per module as a child
pytest, in the gates' configuration (pytest-qt's capture on, no `-s`), from the
repository root, so it reads the same `pyproject.toml` and the same
`tests/conftest.py` the gate does. The assertions read the child's real output:

- AC-1: a `qCritical` at import and in a test, then a Qt fatal
  (`QMessageLogger().fatal`), each reach the output as one tee line
  (`tests/conftest.py`), in order.
- AC-2: `os.abort()` prints faulthandler's abort line and a stack naming the
  probe - MT-112 PO-5's signature, on demand.
- AC-3: the tee ignores a warning, reports a critical, and leaves pytest-qt's
  `Captured Qt messages` report as it was. The negative control for AC-1.
- AC-4: the shipped `keep-when` lines for `unit` match the real abort line and
  the real fatal tee line, and no line of the quiet probe's output.
- AC-5: a directory walk of `tests/ui` collects no probe.

**A failure of this module must not itself be kept as an unexplained incident.**
The children's output holds exactly the lines the `keep-when` signatures exist
to catch, and `gates.sh` keeps a failing `unit` or `coverage` log in which ANY
line matches one - so a failing assertion here that echoed the output, or whose
traceback quoted a signature literal, would be hoarded and would evict a real
incident's log (it did, once, while this module was written: MT-138 `## Notes`).
So no test body spells a signature (they are module constants, which a
traceback does not show), every boolean is computed into a local before it is
asserted (so assertion rewriting has nothing to expand), and every message goes
through `_shown`, which defuses the signatures. `test_shown_defuses_every_unit_signature`
pins that last part against the real output.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_PROBES = _REPO / "tests" / "ui"
_MANIFEST = _REPO / ".claude" / "harness" / "project.conf"
_TIMEOUT_S = 120

_FATAL_PROBE = "tests/ui/__probe_qt_fatal.py"
_ABORT_PROBE = "tests/ui/__probe_abort.py"
_QUIET_PROBE = "tests/ui/__probe_qt_quiet.py"

_TEE_PREFIX = "qt-message: "
_FATAL_TEE_PREFIX = _TEE_PREFIX + "FATAL"
_WARNING_TEE_PREFIX = _TEE_PREFIX + "WARNING"
_ABORT_LINE = "Fatal Python error: Aborted"
_KEEP_WHEN_UNIT = re.compile(r"^\s*keep-when\s*\|\s*unit\s*\|\s*(.*?)\s*$")

# The exit status of `abort()`: the UCRT's on Windows, SIGABRT elsewhere.
_ABORT_EXIT = 3 if sys.platform == "win32" else -6

_AC1_EXPECTED = [
    "qt-message: CRITICAL in no test: PROBE-CRITICAL at import",
    "qt-message: CRITICAL in tests/ui/__probe_qt_fatal.py::test_qfatal:"
    " PROBE-CRITICAL before the fatal",
    "qt-message: FATAL in tests/ui/__probe_qt_fatal.py::test_qfatal: PROBE-FATAL",
]
_AC3_CRITICAL = (
    "qt-message: CRITICAL in tests/ui/__probe_qt_quiet.py::test_critical_then_fail:"
    " PROBE-CRITICAL reported"
)


def _run(probe: str) -> subprocess.CompletedProcess[str]:
    """Run one probe as a child pytest, as AC terms define "run as a child"."""
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", probe],
        cwd=_REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_TIMEOUT_S,
        check=False,
    )


def _output(result: subprocess.CompletedProcess[str]) -> str:
    """The child's stdout and stderr together ("the output")."""
    return (result.stdout or "") + "\n" + (result.stderr or "")


@dataclass(frozen=True)
class _Child:
    """A finished probe child. Its repr is short and defused, because pytest
    prints a failing test's arguments - fixture values - in the traceback."""

    returncode: int
    output: str

    def __repr__(self) -> str:
        return f"_Child(returncode={self.returncode}, output=<{len(self.output)} chars>)"


def _child(probe: str) -> _Child:
    result = _run(probe)
    return _Child(result.returncode, _output(result))


def _lines(output: str) -> list[str]:
    return [line.rstrip("\r") for line in output.splitlines()]


def _tee_lines(output: str) -> list[str]:
    """Every tee line of the output, in order."""
    return [line for line in _lines(output) if line.startswith(_TEE_PREFIX)]


def _unit_signatures() -> list[str]:
    """The regexes of the shipped manifest's `keep-when | unit | ...` lines."""
    text = _MANIFEST.read_text(encoding="utf-8").replace("\r", "")
    signatures = []
    for line in text.split("\n"):
        match = _KEEP_WHEN_UNIT.match(line)
        if match:
            signatures.append(match.group(1))
    return signatures


def _matches_a_signature(line: str, signatures: list[str]) -> bool:
    return any(re.search(signature, line) for signature in signatures)


def _shown(value: object) -> str:
    """`value` as text for a failure message, with every keep-when signature defused."""
    text = value if isinstance(value, str) else repr(value)
    return (
        text.replace("qt-message:", "qt-message~")
        .replace("Fatal Python error", "Fatal-Python-error")
        .replace("Windows fatal exception", "Windows-fatal-exception")
        .replace("Unknown C++ exception", "Unknown-C++-exception")
    )


@pytest.fixture(scope="module")
def fatal_run() -> _Child:
    return _child(_FATAL_PROBE)


@pytest.fixture(scope="module")
def abort_run() -> _Child:
    return _child(_ABORT_PROBE)


@pytest.fixture(scope="module")
def quiet_run() -> _Child:
    return _child(_QUIET_PROBE)


# --- AC-1 ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "index", [0, 1, 2], ids=["critical-at-import", "critical-in-test", "fatal-in-test"]
)
def test_ac1_each_qt_critical_and_fatal_reaches_the_output_exactly_once(
    fatal_run: _Child, index: int
) -> None:
    expected = _AC1_EXPECTED[index]
    tees = _tee_lines(fatal_run.output)
    exactly_once = tees.count(expected) == 1
    assert exactly_once, _shown(
        f"expected exactly one {expected!r}; tee lines were {tees!r};"
        f" exit {fatal_run.returncode}; output:\n{fatal_run.output}"
    )


def test_ac1_the_three_tee_lines_are_in_order(
    fatal_run: _Child,
) -> None:
    tees = _tee_lines(fatal_run.output)
    in_order = [line for line in tees if line in _AC1_EXPECTED] == _AC1_EXPECTED
    assert in_order, _shown(f"tee lines out of order or missing: {tees!r}")


def test_ac1_a_qt_fatal_exits_non_zero(fatal_run: _Child) -> None:
    # Not pinned to 127: the status is Qt's, and the story does not own it.
    non_zero = fatal_run.returncode != 0
    assert non_zero, _shown(fatal_run.output)


# --- AC-2 ---------------------------------------------------------------------


def _abort_stack(lines: list[str]) -> list[str] | None:
    """The `Current thread` stack after the abort line, or None if either is missing."""
    stripped = [line.strip() for line in lines]
    if _ABORT_LINE not in stripped:
        return None
    start = stripped.index(_ABORT_LINE)
    thread = next(
        (i for i in range(start + 1, len(lines)) if stripped[i].startswith("Current thread")),
        None,
    )
    if thread is None:
        return None
    stack: list[str] = []
    for line in lines[thread + 1 :]:
        if not line.strip():
            break
        stack.append(line)
    return stack


def test_ac2_an_abort_prints_the_abort_line_and_a_stack_naming_the_probe(
    abort_run: _Child,
) -> None:
    stack = _abort_stack(_lines(abort_run.output))
    has_stack = stack is not None
    assert has_stack, _shown(f"no abort line followed by a stack:\n{abort_run.output}")
    names_probe = any("__probe_abort.py" in line for line in stack or [])
    assert names_probe, _shown(f"the stack does not name __probe_abort.py: {stack!r}")


def test_ac2_an_abort_exits_with_the_platform_abort_status(
    abort_run: _Child,
) -> None:
    status_is_abort = abort_run.returncode == _ABORT_EXIT
    assert status_is_abort, _shown(f"exit {abort_run.returncode}:\n{abort_run.output}")


# --- AC-3 (the negative control for AC-1) -------------------------------------


def test_ac3_a_qt_warning_is_not_teed(quiet_run: _Child) -> None:
    output = quiet_run.output
    tees = _tee_lines(output)
    no_warning_tee = not [line for line in tees if "PROBE-WARNING" in line]
    assert no_warning_tee, _shown(tees)
    no_warning_level = not [ln for ln in _lines(output) if ln.startswith(_WARNING_TEE_PREFIX)]
    assert no_warning_level, _shown(tees)


def test_ac3_a_qt_critical_is_teed_exactly_once(
    quiet_run: _Child,
) -> None:
    tees = _tee_lines(quiet_run.output)
    only_the_critical = tees == [_AC3_CRITICAL]
    assert only_the_critical, _shown(f"tee lines {tees!r}; output:\n{quiet_run.output}")


def test_ac3_pytest_qt_still_reports_the_critical_under_captured_qt_messages(
    quiet_run: _Child,
) -> None:
    lines = _lines(quiet_run.output)
    header = next((i for i, line in enumerate(lines) if "Captured Qt messages" in line), None)
    has_section = header is not None
    assert has_section, _shown(f"no `Captured Qt messages` section:\n{lines!r}")
    reported = [
        line
        for line in lines[(header or 0) + 1 :]
        if "PROBE-CRITICAL reported" in line and not line.startswith(_TEE_PREFIX)
    ]
    assert reported, _shown(f"pytest-qt's report lost the critical:\n{lines!r}")


def test_ac3_the_quiet_probe_reports_one_failed_one_passed_and_exits_1(
    quiet_run: _Child,
) -> None:
    output = quiet_run.output
    summary = re.search(r"^1 failed, 1 passed in ", output, re.MULTILINE) is not None
    assert summary, _shown(output)
    exit_1 = quiet_run.returncode == 1
    assert exit_1, _shown(f"exit {quiet_run.returncode}")


# --- AC-4 ---------------------------------------------------------------------


def test_ac4_the_real_abort_line_matches_a_unit_keep_when_signature(
    abort_run: _Child,
) -> None:
    signatures = _unit_signatures()
    abort_lines = [line for line in _lines(abort_run.output) if line.strip() == _ABORT_LINE]
    assert abort_lines, _shown(f"the abort probe printed no abort line:\n{abort_run.output}")
    matched = _matches_a_signature(abort_lines[0], signatures)
    assert matched, _shown(f"{abort_lines[0]!r} matches none of {signatures!r}")


def test_ac4_the_real_fatal_tee_line_matches_a_unit_keep_when_signature(
    fatal_run: _Child,
) -> None:
    signatures = _unit_signatures()
    fatal_lines = [
        line for line in _tee_lines(fatal_run.output) if line.startswith(_FATAL_TEE_PREFIX)
    ]
    assert fatal_lines, _shown(f"the fatal probe printed no fatal tee line:\n{fatal_run.output}")
    matched = _matches_a_signature(fatal_lines[0], signatures)
    assert matched, _shown(f"{fatal_lines[0]!r} matches none of {signatures!r}")


def test_ac4_no_line_of_an_ordinary_failing_run_matches_a_unit_signature(
    quiet_run: _Child,
) -> None:
    signatures = _unit_signatures()
    assert signatures, "the manifest has no keep-when line for unit"
    kept = [line for line in _lines(quiet_run.output) if _matches_a_signature(line, signatures)]
    nothing_kept = kept == []
    assert nothing_kept, _shown(f"an ordinary failing run would be kept: {kept!r}")


def test_shown_defuses_every_unit_signature(
    fatal_run: _Child,
    abort_run: _Child,
) -> None:
    # A failure message of this module is built by `_shown`; if a line of it
    # matched a signature, the failing gate log would be kept as an incident.
    signatures = _unit_signatures()
    texts = [fatal_run.output, abort_run.output, repr(_AC1_EXPECTED), repr(signatures)]
    leaked = [
        line
        for text in texts
        for line in _shown(text).splitlines()
        if _matches_a_signature(line, signatures)
    ]
    nothing_leaked = leaked == []
    assert nothing_leaked, f"{len(leaked)} line(s) of a failure message would be kept"


# --- AC-5 ---------------------------------------------------------------------


def test_ac5_a_directory_walk_of_tests_ui_collects_no_probe() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            "tests/ui",
        ],
        cwd=_REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_TIMEOUT_S,
        check=False,
    )
    collected_ok = result.returncode == 0
    assert collected_ok, _shown(_output(result))
    collected = [line for line in _lines(result.stdout) if "::" in line]
    assert collected, _shown(f"the collection listed no item at all:\n{_output(result)}")
    # Judged on the file part of the node id only: a parametrize id of another
    # test may quote a probe's path (AC-1's once did) without being a probe.
    probes = [line for line in collected if "__probe_" in line.split("::", 1)[0]]
    no_probe = probes == []
    assert no_probe, _shown(f"a probe was collected by the directory walk: {probes!r}")
    for name in ("__probe_qt_fatal.py", "__probe_abort.py", "__probe_qt_quiet.py"):
        assert (_PROBES / name).is_file(), f"probe {name} is missing, so AC-5 judges nothing"
