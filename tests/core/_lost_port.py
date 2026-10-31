"""MT-126: retry a lost-port induction that did not take, on a fresh child, and say so.

The tests of MT-069 (`test_cv2_lost_completion_port.py`) and MT-071
(`test_cv2_lost_completion_port_inpaint.py`) close the default Windows thread
pool's completion port in a fresh *induced* child and then run a vacuity canary
- `SetThreadpoolWait` on a fresh thread - which must raise `0xC000070A`. When the
canary succeeds the port was never lost, and the test fails as `VACUOUS`. That
happened in about one full gate run in ten with no code change, cause not yet
known (MT-126 `## Context`).

The policy here, and only here: spawn a fresh induced child again, at most
`INDUCTION_ATTEMPTS` times, and **only when the canary succeeded**. A report
whose canary raised - with the right code or the wrong one - or whose close
failed, or whose production call failed, is returned after one spawn, so a real
regression is never retried away. The helper reads nothing of a report but its
canary and, for the messages, `closed_handle`, `close_ok` and
`io_completion_handles`; every other check stays in the test files.

Pure Python over report dicts, so `test_lost_port_induction.py` runs it on every
platform with a scripted spawner.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

#: The maximum number of induced children per test (MT-126 C-1, settled).
INDUCTION_ATTEMPTS: int = 3

#: STATUS_THREADPOOL_HANDLE_EXCEPTION (audit MT-068 E1).
THREADPOOL_HANDLE_EXCEPTION: int = 0xC000070A


class InductionRetried(UserWarning):
    """The induction took only on a later attempt; the text names the vacuous ones."""


def _hex(value: int | None) -> str:
    return "none" if value is None else f"{value:#x}"


def _attempt_line(number: int, limit: int, report: dict[str, Any]) -> str:
    if "io_completion_handles" in report:
        handles = "[" + ", ".join(_hex(v) for v in report["io_completion_handles"]) + "]"
    else:
        handles = "unreported"
    return (
        f"attempt {number}/{limit}: closed {_hex(report['closed_handle'])}"
        f" (close_ok {report['close_ok']}), IoCompletion handles {handles}"
    )


def _vacuous(report: dict[str, Any]) -> bool:
    return bool(report["canary"]["ok"] is True)


@dataclass(frozen=True)
class Induction:
    """Every induced report spawned for one test, and the bound it was spawned under."""

    report: dict[str, Any]
    attempts: tuple[dict[str, Any], ...]
    limit: int

    @property
    def took(self) -> bool:
        """True when the last child's canary did not succeed (the port was lost)."""
        return not _vacuous(self.report)

    def _vacuous_lines(self) -> list[str]:
        return [
            _attempt_line(number, self.limit, report)
            for number, report in enumerate(self.attempts, start=1)
            if _vacuous(report)
        ]

    def vacuous_message(self) -> str:
        """The failure text: the story's needle, the count, then one line per vacuous attempt."""
        lines = self._vacuous_lines()
        head = (
            "VACUOUS: the canary SetThreadpoolWait on a fresh thread succeeded in the induced"
            f" child in {len(lines)} of {self.limit} attempts, so the default thread pool's"
            " completion port was never lost"
        )
        return "\n".join([head, *lines])


def run_induced(
    spawn: Callable[[int], dict[str, Any]], attempts: int = INDUCTION_ATTEMPTS
) -> Induction:
    """Call `spawn(n)` for n = 1, 2, ... until a report's canary did not succeed."""
    if attempts < 1:
        raise ValueError(f"attempts must be at least 1, not {attempts}")
    reports: list[dict[str, Any]] = []
    for index in range(attempts):
        report = spawn(index + 1)
        reports.append(report)
        if report["canary"]["ok"] is not True:
            break
    return Induction(report=reports[-1], attempts=tuple(reports), limit=attempts)


def warn_if_retried(induction: Induction) -> None:
    """One `InductionRetried` when a later child took; nothing otherwise.

    An induction that never took is not warned about: the test fails, and its
    `vacuous_message()` carries the same per-attempt lines.
    """
    if len(induction.attempts) < 2:
        return
    if not induction.took:
        return
    lines = induction._vacuous_lines()
    prefix = (
        f"MT-126: the lost-port induction took on attempt"
        f" {len(induction.attempts)}/{induction.limit};"
    )
    warnings.warn("\n".join([prefix, *lines]), InductionRetried, stacklevel=2)
