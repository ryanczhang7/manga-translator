"""MT-028 Contract blocks 1-2: High Contrast reaches the app as one boolean
behind an interface, off by default, and a real `QPalette` is snapshotted into
the plain five-role mapping `resolve` reads.

**Oracle partition.** AC-1 is *settled* - `accessibility.md` A-15.4 and
`high-contrast.md` section 3 fix the interface, the platform call and the
fail-closed default; nothing here designs a detection model. AC-3 is
*mechanical* and pinned exactly: five keys in a fixed order, uppercase
`#RRGGBB`, alpha dropped, `DisabledText` from the Disabled group's `WindowText`
and the other four from the Active group.

- AC-1: `ContrastSource` is the interface (abstract `is_high_contrast`, a
  `changed(bool)` signal); `FixedContrastSource` is the double every other test
  drives; `read_system_high_contrast()` is total and answers `False` on every
  failure; `SystemContrastSource` constructs without raising and reports
  `False` where the call is absent or fails.
- AC-3: `palette_snapshot(QPalette)`.

**Why this file imports `ctypes`** (Contract block 1, amended in RED): the
"default off" cases replace `ctypes.windll` - deleting it, or substituting a
`user32.SystemParametersInfoW` that fails or that writes `dwFlags` through the
struct pointer it is handed - so the struct is shown to be *read*, not assumed.
That is the only use; nothing here calls the real Windows API.
"""

from __future__ import annotations

import ctypes
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from PySide6.QtCore import QObject
from PySide6.QtGui import QColor, QPalette

from mangatl.ui.contrast import (
    ContrastSource,
    FixedContrastSource,
    SystemContrastSource,
    palette_snapshot,
    read_system_high_contrast,
)

#: `SPI_GETHIGHCONTRAST` and `HCF_HIGHCONTRASTON` (Contract block 1; Win32).
SPI_GETHIGHCONTRAST = 0x0042
HCF_HIGHCONTRASTON = 0x1
#: `HCF_AVAILABLE`: a flag that is set on every Windows host and means nothing
#: about whether a contrast theme is ON. The mask must ignore it.
HCF_AVAILABLE = 0x2

#: AC-3: the five roles, in the order the snapshot returns them.
ROLES = ("Window", "WindowText", "Highlight", "HighlightedText", "DisabledText")


# =============================================================================
# AC-1: the interface and the test double
# =============================================================================


def test_the_contrast_interface_has_no_answer_of_its_own() -> None:
    """AC-1: `ContrastSource.is_high_contrast` is abstract."""
    with pytest.raises(NotImplementedError):
        ContrastSource().is_high_contrast()


def test_an_injected_source_with_nothing_said_reports_high_contrast_off() -> None:
    """AC-1: the double's default is the fail-closed default, off."""
    assert FixedContrastSource().is_high_contrast() is False


@pytest.mark.parametrize("value", [True, False])
def test_an_injected_source_reports_exactly_the_value_it_was_given(value: bool) -> None:
    assert FixedContrastSource(value).is_high_contrast() is value


def test_an_injected_source_can_be_parented_like_any_qobject() -> None:
    parent = QObject()
    source = FixedContrastSource(True, parent)
    assert source.parent() is parent
    assert source.is_high_contrast() is True


@pytest.mark.parametrize(
    "make", [FixedContrastSource, SystemContrastSource], ids=lambda c: c.__name__
)
def test_both_sources_are_the_one_interface_and_carry_its_changed_signal(
    qapp: Any, monkeypatch: pytest.MonkeyPatch, make: Callable[[], ContrastSource]
) -> None:
    """AC-1: the rest of the app sees one boolean behind one interface."""
    monkeypatch.delattr(ctypes, "windll", raising=False)
    source = make()
    assert isinstance(source, ContrastSource)
    assert isinstance(source, QObject)
    received: list[bool] = []
    source.changed.connect(received.append)  # a Signal: connectable
    assert received == []


@pytest.mark.parametrize("start, new", [(False, True), (True, False)])
def test_changing_an_injected_source_emits_the_new_value_exactly_once(
    start: bool, new: bool
) -> None:
    source = FixedContrastSource(start)
    received: list[bool] = []
    source.changed.connect(received.append)

    source.set_value(new)

    assert received == [new], f"set_value({new}) from {start} emitted {received}"
    assert source.is_high_contrast() is new


@pytest.mark.parametrize("value", [True, False])
def test_setting_an_injected_source_to_the_value_it_already_has_emits_nothing(
    value: bool,
) -> None:
    """AC-1/AC-9: `changed` means changed, not "was told again"."""
    source = FixedContrastSource(value)
    received: list[bool] = []
    source.changed.connect(received.append)

    source.set_value(value)

    assert received == [], f"set_value({value}) on a source already {value} emitted {received}"
    assert source.is_high_contrast() is value


# =============================================================================
# AC-1: the platform call, fail-closed
# =============================================================================


def _struct_of(pointer: Any) -> Any:
    """The struct a `SystemParametersInfoW` caller handed in, whether it passed
    `ctypes.byref(s)`, `ctypes.pointer(s)` or the struct itself."""
    if hasattr(pointer, "_obj"):  # byref
        return pointer._obj
    if hasattr(pointer, "contents"):  # pointer
        return pointer.contents
    return pointer


def _windll(system_parameters_info: Callable[..., int]) -> SimpleNamespace:
    return SimpleNamespace(user32=SimpleNamespace(SystemParametersInfoW=system_parameters_info))


def _filling(flags: int, returns: int, calls: list[dict[str, Any]]) -> Callable[..., int]:
    """A `SystemParametersInfoW` that writes `flags` into the HIGHCONTRASTW
    struct it is handed - as Windows does - and returns `returns`."""

    def system_parameters_info(action: int, ui_param: int, pv_param: Any, win_ini: int) -> int:
        struct = _struct_of(pv_param)
        calls.append(
            {
                "action": action,
                "cbSize": struct.cbSize,
                "sizeof": ctypes.sizeof(struct),
            }
        )
        struct.dwFlags = flags
        return returns

    return system_parameters_info


def _raising(error: BaseException) -> Callable[..., int]:
    def system_parameters_info(*args: Any) -> int:
        raise error

    return system_parameters_info


def test_with_no_windows_api_at_all_high_contrast_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-1: the platform is not Windows (no `ctypes.windll`) - off, no raise."""
    monkeypatch.delattr(ctypes, "windll", raising=False)
    assert read_system_high_contrast() is False


def test_when_the_platform_call_reports_failure_high_contrast_is_off_even_if_flags_were_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-1: a zero return is a failed call, whatever the struct now holds."""
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        ctypes, "windll", _windll(_filling(HCF_HIGHCONTRASTON, 0, calls)), raising=False
    )
    assert read_system_high_contrast() is False
    assert len(calls) == 1, f"the platform call was made {len(calls)} times"


@pytest.mark.parametrize(
    "error",
    [OSError("access denied"), AttributeError("user32"), ValueError("bad"), RuntimeError("x")],
    ids=lambda e: type(e).__name__,
)
def test_when_the_platform_call_raises_high_contrast_is_off_and_nothing_escapes(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    """AC-1: the function is total - any exception is "off"."""
    monkeypatch.setattr(ctypes, "windll", _windll(_raising(error)), raising=False)
    assert read_system_high_contrast() is False


@pytest.mark.parametrize(
    "flags, expected",
    [
        (HCF_HIGHCONTRASTON, True),
        (HCF_HIGHCONTRASTON | HCF_AVAILABLE, True),
        (HCF_AVAILABLE, False),
        (0, False),
    ],
    ids=["on", "on-and-available", "available-only", "none"],
)
def test_a_successful_platform_call_is_read_from_the_struct_flags(
    monkeypatch: pytest.MonkeyPatch, flags: int, expected: bool
) -> None:
    """AC-1: the answer is `dwFlags & HCF_HIGHCONTRASTON` from the struct the
    call filled - read, not assumed - and the call is SPI_GETHIGHCONTRAST with
    `cbSize` set to the struct's size, as Windows requires."""
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(ctypes, "windll", _windll(_filling(flags, 1, calls)), raising=False)

    assert read_system_high_contrast() is expected, f"dwFlags={flags:#x}"
    assert len(calls) == 1, f"the platform call was made {len(calls)} times"
    assert calls[0]["action"] == SPI_GETHIGHCONTRAST, calls[0]
    assert calls[0]["cbSize"] == calls[0]["sizeof"], (
        f"HIGHCONTRASTW.cbSize was {calls[0]['cbSize']}, not the struct's size"
        f" {calls[0]['sizeof']}: Windows refuses the call"
    )


@pytest.mark.parametrize(
    "windll",
    [
        None,
        _windll(_filling(HCF_HIGHCONTRASTON, 0, [])),
        _windll(_raising(OSError("no"))),
    ],
    ids=["no windll", "call returns 0", "call raises"],
)
def test_the_system_source_constructs_without_raising_and_reports_off_when_the_call_fails(
    qapp: Any, monkeypatch: pytest.MonkeyPatch, windll: SimpleNamespace | None
) -> None:
    """AC-1: the real source is fail-closed too, and constructing it is safe."""
    if windll is None:
        monkeypatch.delattr(ctypes, "windll", raising=False)
    else:
        monkeypatch.setattr(ctypes, "windll", windll, raising=False)

    source = SystemContrastSource()

    assert source.is_high_contrast() is False


# =============================================================================
# AC-3: the palette adapter (mechanical, pinned exactly)
# =============================================================================

Active = QPalette.ColorGroup.Active
Inactive = QPalette.ColorGroup.Inactive
Disabled = QPalette.ColorGroup.Disabled
Role = QPalette.ColorRole


def _decoyed_palette() -> QPalette:
    """Distinct colours in the five slots the adapter must read, and different
    ones in every neighbouring slot it must not."""
    palette = QPalette()
    # Decoys first, so a slot the adapter reads is never left holding one.
    for group in (Active, Inactive, Disabled):
        for role in (
            Role.Window,
            Role.WindowText,
            Role.Highlight,
            Role.HighlightedText,
            Role.Button,
            Role.ButtonText,
            Role.Text,
            Role.Base,
            Role.Link,
        ):
            palette.setColor(group, role, QColor("#777777"))
    palette.setColor(Inactive, Role.Window, QColor("#111111"))
    palette.setColor(Inactive, Role.WindowText, QColor("#222222"))
    palette.setColor(Disabled, Role.Window, QColor("#333333"))
    palette.setColor(Disabled, Role.Highlight, QColor("#444444"))
    palette.setColor(Active, Role.Text, QColor("#555555"))
    palette.setColor(Active, Role.Button, QColor("#666666"))
    palette.setColor(Active, Role.Link, QColor("#888888"))
    # The five slots. Lower-case hex letters in, so upper-casing is observable;
    # an alpha channel on Window, so dropping it is observable.
    palette.setColor(Active, Role.Window, QColor(0xAB, 0xCD, 0xEF, 0x40))
    palette.setColor(Active, Role.WindowText, QColor("#fedcba"))
    palette.setColor(Active, Role.Highlight, QColor("#0a1b2c"))
    palette.setColor(Active, Role.HighlightedText, QColor("#f0e0d0"))
    palette.setColor(Disabled, Role.WindowText, QColor("#9c8b7a"))
    return palette


EXPECTED_SNAPSHOT = {
    "Window": "#ABCDEF",
    "WindowText": "#FEDCBA",
    "Highlight": "#0A1B2C",
    "HighlightedText": "#F0E0D0",
    "DisabledText": "#9C8B7A",
}


def test_the_snapshot_is_exactly_the_five_roles_from_their_groups_as_uppercase_rgb() -> None:
    """AC-3: Active group for four roles, Disabled `WindowText` for
    `DisabledText`, `#RRGGBB` upper-case with alpha dropped, nothing else."""
    snapshot = palette_snapshot(_decoyed_palette())

    assert type(snapshot) is dict
    assert snapshot == EXPECTED_SNAPSHOT


def test_the_snapshot_keys_come_in_the_contract_order() -> None:
    assert list(palette_snapshot(_decoyed_palette())) == list(ROLES)


@pytest.mark.parametrize(
    "group, role, key",
    [
        (Active, Role.Window, "Window"),
        (Active, Role.WindowText, "WindowText"),
        (Active, Role.Highlight, "Highlight"),
        (Active, Role.HighlightedText, "HighlightedText"),
        (Disabled, Role.WindowText, "DisabledText"),
    ],
    ids=ROLES,
)
def test_each_snapshot_role_follows_its_one_palette_slot(
    group: QPalette.ColorGroup, role: QPalette.ColorRole, key: str
) -> None:
    """AC-3, one case per role: change the one slot, and only that key moves."""
    palette = _decoyed_palette()
    palette.setColor(group, role, QColor("#13579b"))

    snapshot = palette_snapshot(palette)

    expected = dict(EXPECTED_SNAPSHOT)
    expected[key] = "#13579B"
    assert snapshot == expected


def test_the_snapshot_is_total_over_a_default_palette() -> None:
    snapshot = palette_snapshot(QPalette())

    assert list(snapshot) == list(ROLES)
    for key, value in snapshot.items():
        assert isinstance(value, str)
        assert len(value) == 7 and value.startswith("#"), f"{key}: {value!r}"
        assert value == value.upper(), f"{key}: {value!r} is not upper-case"
        int(value[1:], 16)
