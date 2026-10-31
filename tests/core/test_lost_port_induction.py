"""MT-126: the lost-port induction is retried on a fresh child, and says so loudly.

The three Windows tests of MT-069 and MT-071 close the default thread pool's
completion port in a fresh induced child and fail as `VACUOUS` when that child's
canary `SetThreadpoolWait` succeeds - the induction did not take. That fired in
about one full gate run in ten with no code change. `_lost_port.run_induced`
retries the induction on a *fresh* child, at most `INDUCTION_ATTEMPTS` times,
and only when the canary succeeded; a run whose every attempt is vacuous fails
with every attempt's evidence, and a run that took late emits one
`InductionRetried` warning.

The policy is a pure function over child reports, so these tests drive it with a
scripted fake spawner and no subprocess, on every platform. The spawner raises
`AssertionError("spawned more than scripted")` when its script runs out, so a
helper whose bound is gone fails here rather than hanging (AC-2's control).

Report dicts carry only the keys the helper reads - `canary`, `closed_handle`,
`close_ok`, `io_completion_handles` - plus `calls` where AC-3 needs a failed
production call. Expected strings are spelled out in full, from the story's
contract C-1, not rebuilt from the helper's own formatting.
"""

from __future__ import annotations

import copy
import warnings
from collections.abc import Sequence
from typing import Any

import pytest
from _lost_port import (
    INDUCTION_ATTEMPTS,
    THREADPOOL_HANDLE_EXCEPTION,
    Induction,
    InductionRetried,
    run_induced,
    warn_if_retried,
)

# Settled (C-4): the needle the story record greps for, kept verbatim.
_NEEDLE = "VACUOUS: the canary SetThreadpoolWait on a fresh thread succeeded in the induced child"


class _Spawner:
    """A scripted `spawn`: records each attempt number, refuses to run past the script."""

    def __init__(self, reports: Sequence[dict[str, Any]]) -> None:
        self._reports = list(reports)
        self.calls: list[int] = []

    def __call__(self, attempt: int) -> dict[str, Any]:
        self.calls.append(attempt)
        if len(self.calls) > len(self._reports):
            raise AssertionError("spawned more than scripted")
        return self._reports[len(self.calls) - 1]


def _vacuous(
    closed: int | None, handles: list[int] | None, close_ok: bool | None = True
) -> dict[str, Any]:
    """An induced report whose canary succeeded: the port was never lost."""
    report: dict[str, Any] = {
        "canary": {"ok": True, "winerror": None, "error": None},
        "closed_handle": closed,
        "close_ok": close_ok,
        "calls": {"erase_mask": {"ok": True, "error": None}},
    }
    if handles is not None:
        report["io_completion_handles"] = handles
    return report


def _took(closed: int = 0x20, handles: list[int] | None = None) -> dict[str, Any]:
    """An induced report whose canary raised 0xC000070A: the induction took."""
    return {
        "canary": {
            "ok": False,
            "winerror": 0xC000070A,
            "error": "OSError: [WinError -1073739030] Windows Error 0xc000070a",
        },
        "closed_handle": closed,
        "close_ok": True,
        "io_completion_handles": handles if handles is not None else [closed, 0x44, 0x5C],
        "calls": {"erase_mask": {"ok": True, "error": None}},
    }


# Three distinct vacuous attempts, so a per-attempt line cannot be satisfied by
# another attempt's facts, and close_ok varies so its value is read, not assumed.
_V1 = _vacuous(0x20, [0x20, 0x44, 0x5C], close_ok=True)
_V2 = _vacuous(0x24, [0x24, 0x48], close_ok=False)
_V3 = _vacuous(0x28, [0x28, 0x2C, 0x30, 0x1F0], close_ok=True)

_LINE_V1_OF_3 = "attempt 1/3: closed 0x20 (close_ok True), IoCompletion handles [0x20, 0x44, 0x5c]"
_LINE_V2_OF_3 = "attempt 2/3: closed 0x24 (close_ok False), IoCompletion handles [0x24, 0x48]"
_LINE_V3_OF_3 = (
    "attempt 3/3: closed 0x28 (close_ok True), IoCompletion handles [0x28, 0x2c, 0x30, 0x1f0]"
)
_FIRST_LINE_3_OF_3 = (
    "VACUOUS: the canary SetThreadpoolWait on a fresh thread succeeded in the induced child"
    " in 3 of 3 attempts, so the default thread pool's completion port was never lost"
)


# --- settled values -----------------------------------------------------------------


def test_the_settled_attempt_bound_and_status_code_are_the_storys() -> None:
    assert INDUCTION_ATTEMPTS == 3
    assert THREADPOOL_HANDLE_EXCEPTION == 0xC000070A


def test_induction_retried_is_a_user_warning_so_pytest_prints_it_in_the_summary() -> None:
    assert issubclass(InductionRetried, UserWarning)


# --- AC-1: retried until it takes, and no further -----------------------------------


@pytest.mark.parametrize("k", [0, 1, 2])
def test_a_vacuous_induction_is_retried_on_a_fresh_child_until_one_takes(k: int) -> None:
    script = [*[_V1, _V2, _V3][:k], _took(0x2C)]
    spawn = _Spawner(script)

    induction = run_induced(spawn, 3)

    assert spawn.calls == list(range(1, k + 2)), (
        f"after {k} vacuous attempt(s) the spawner should be called for attempts"
        f" 1..{k + 1} and then stop; it was called with {spawn.calls}"
    )
    assert induction.report is script[k], "the result is not the report that took"
    assert len(induction.attempts) == k + 1
    assert all(got is want for got, want in zip(induction.attempts, script, strict=True)), (
        "the attempts are not every spawned report, in order"
    )
    assert induction.attempts[-1] is induction.report
    assert induction.took is True


def test_an_induction_that_takes_first_time_spawns_exactly_once() -> None:
    spawn = _Spawner([_took(), _took(0x24)])

    induction = run_induced(spawn)

    assert spawn.calls == [1], f"a taking first attempt cost extra spawns: {spawn.calls}"
    assert len(induction.attempts) == 1


# --- AC-2: three vacuous attempts fail, loudly, and never a fourth --------------------


def _all_vacuous() -> tuple[_Spawner, Induction]:
    spawn = _Spawner([_V1, _V2, _V3])
    return spawn, run_induced(spawn)


def test_an_induction_that_never_takes_spawns_exactly_the_default_three_children() -> None:
    spawn, induction = _all_vacuous()
    assert spawn.calls == [1, 2, 3]
    assert induction.took is False
    assert induction.report is _V3
    assert len(induction.attempts) == 3


def test_an_unbounded_retry_hits_the_spawners_control_instead_of_hanging() -> None:
    # The control itself: a fourth spawn raises, so a helper without a bound fails.
    spawn = _Spawner([_V1, _V2, _V3])
    for attempt in (1, 2, 3):
        spawn(attempt)
    with pytest.raises(AssertionError, match=r"^spawned more than scripted$"):
        spawn(4)


def test_the_vacuous_message_starts_with_the_storys_needle() -> None:
    _, induction = _all_vacuous()
    message = induction.vacuous_message()
    assert message.startswith("VACUOUS:"), message
    assert message.startswith(_NEEDLE), message


def test_the_vacuous_message_says_how_many_attempts_were_vacuous() -> None:
    _, induction = _all_vacuous()
    first = induction.vacuous_message().splitlines()[0]
    assert "3 attempts" in first, first
    assert first == _FIRST_LINE_3_OF_3, first


def test_the_vacuous_message_names_every_attempts_closed_handle_close_ok_and_handles() -> None:
    _, induction = _all_vacuous()
    lines = induction.vacuous_message().splitlines()
    assert lines[1:] == [_LINE_V1_OF_3, _LINE_V2_OF_3, _LINE_V3_OF_3], "\n".join(lines)


def test_the_vacuous_message_counts_against_the_bound_it_was_given() -> None:
    spawn = _Spawner([_V1, _V2])
    induction = run_induced(spawn, 2)
    assert spawn.calls == [1, 2]
    assert induction.vacuous_message().splitlines() == [
        "VACUOUS: the canary SetThreadpoolWait on a fresh thread succeeded in the induced child"
        " in 2 of 2 attempts, so the default thread pool's completion port was never lost",
        "attempt 1/2: closed 0x20 (close_ok True), IoCompletion handles [0x20, 0x44, 0x5c]",
        "attempt 2/2: closed 0x24 (close_ok False), IoCompletion handles [0x24, 0x48]",
    ]


def test_an_attempt_that_closed_nothing_prints_none_for_its_handle() -> None:
    induction = run_induced(_Spawner([_vacuous(None, [0x20, 0x44], close_ok=None)]), 1)
    assert induction.vacuous_message().splitlines()[1:] == [
        "attempt 1/1: closed none (close_ok None), IoCompletion handles [0x20, 0x44]"
    ]


def test_an_old_shaped_report_without_the_handle_list_prints_unreported() -> None:
    induction = run_induced(_Spawner([_vacuous(0x20, None)]), 1)
    assert induction.vacuous_message().splitlines()[1:] == [
        "attempt 1/1: closed 0x20 (close_ok True), IoCompletion handles unreported"
    ]


def test_a_child_that_found_no_completion_handle_prints_an_empty_list() -> None:
    induction = run_induced(_Spawner([_vacuous(None, [], close_ok=None)]), 1)
    assert induction.vacuous_message().splitlines()[1:] == [
        "attempt 1/1: closed none (close_ok None), IoCompletion handles []"
    ]


@pytest.mark.parametrize("attempts", [0, -1])
def test_fewer_than_one_attempt_is_refused_before_anything_is_spawned(attempts: int) -> None:
    spawn = _Spawner([_took()])
    with pytest.raises(ValueError):
        run_induced(spawn, attempts)
    assert spawn.calls == []


# --- AC-3: only a succeeding canary is ever retried ------------------------------------


def _failed_production_call() -> dict[str, Any]:
    report = _took()
    report["calls"] = {
        "erase_mask": {"ok": False, "error": "cv2.error: Unknown C++ exception from OpenCV code"}
    }
    return report


def _wrong_winerror() -> dict[str, Any]:
    report = _took()
    report["canary"] = {"ok": False, "winerror": 0x5, "error": "OSError: [WinError 5]"}
    return report


def _close_failed() -> dict[str, Any]:
    report = _took()
    report["close_ok"] = False
    return report


def _canary_setup_failed() -> dict[str, Any]:
    report = _took()
    report["canary"] = {"ok": False, "winerror": None, "error": "setup failed: 8"}
    return report


@pytest.mark.parametrize(
    "make",
    [_failed_production_call, _wrong_winerror, _close_failed, _canary_setup_failed],
    ids=["production-call-failed", "wrong-winerror", "close-failed", "canary-setup-failed"],
)
def test_a_report_whose_canary_did_not_succeed_is_never_retried_away(make: Any) -> None:
    report = make()
    before = copy.deepcopy(report)
    # A second scripted report exists, so a wrongful retry is visible as a call
    # rather than as the spawner's own control.
    spawn = _Spawner([report, _took(0x24)])

    induction = run_induced(spawn)

    assert spawn.calls == [1], f"a non-vacuous report was retried: spawned {spawn.calls}"
    # Identity, not only equality: the test files' own checks must read the very
    # dict the child printed, and the helper may not copy, normalise or edit it.
    assert induction.report is report
    assert induction.report == before, "the helper changed the report it returned"
    assert induction.attempts == (report,)


# --- AC-5: one warning when it took late, none when it took first --------------------


def test_a_late_take_emits_exactly_one_warning_naming_the_vacuous_attempt() -> None:
    induction = run_induced(_Spawner([_V1, _took(0x24)]))

    with pytest.warns(InductionRetried) as record:
        warn_if_retried(induction)

    assert len(record) == 1, [str(w.message) for w in record]
    assert str(record[0].message).splitlines() == [
        "MT-126: the lost-port induction took on attempt 2/3;",
        _LINE_V1_OF_3,
    ]
    # stacklevel=2: the warning points at the test file that called it.
    assert record[0].filename == __file__


def test_a_take_on_the_last_attempt_names_both_vacuous_attempts() -> None:
    induction = run_induced(_Spawner([_V1, _V2, _took(0x28)]))

    with pytest.warns(InductionRetried) as record:
        warn_if_retried(induction)

    assert len(record) == 1, [str(w.message) for w in record]
    assert str(record[0].message).splitlines() == [
        "MT-126: the lost-port induction took on attempt 3/3;",
        _LINE_V1_OF_3,
        _LINE_V2_OF_3,
    ]


def test_a_first_time_take_emits_no_warning() -> None:
    induction = run_induced(_Spawner([_took()]))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        warn_if_retried(induction)


def test_an_induction_that_never_took_emits_no_warning_claiming_it_took() -> None:
    # The failure message carries these lines; a warning saying "took on attempt
    # 3/3" beside a VACUOUS failure would be false.
    _, induction = _all_vacuous()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        warn_if_retried(induction)


def test_running_the_induction_itself_emits_no_warning_so_the_test_emits_exactly_one() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        run_induced(_Spawner([_V1, _V2, _took(0x28)]))
        run_induced(_Spawner([_V1, _V2, _V3]))
