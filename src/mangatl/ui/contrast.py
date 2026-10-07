"""High Contrast detection and the palette snapshot (MT-028).

`docs/wiki/design/high-contrast.md` section 3 and `accessibility.md` A-15.4:
whether a Windows contrast theme is active reaches the app as **one injectable
boolean behind an interface**, and the default whenever the platform call is not
wired, fails, or the platform is not Windows is **off** - the measured dark
theme, never an HC mapping against a palette that may be unpopulated.

- `ContrastSource` is the interface: `is_high_contrast()` and a `changed(bool)`
  signal carrying the new value, emitted only when it differs.
- `FixedContrastSource` is the double every test drives.
- `SystemContrastSource` reads `SPI_GETHIGHCONTRAST` once at construction and
  again on `WM_SETTINGCHANGE`.
- `read_system_high_contrast()` is the one `ctypes` call, and it never raises.

`palette_snapshot` is the adapter section 4.1/4.3 describes: a real `QPalette`
in, the plain five-role mapping `theme.resolve` reads out, and nothing else.

`system_palette` is where that mapping comes from by default (PO-7): the same
five roles read from Windows' `GetSysColor`, with `palette_snapshot` of Qt's
palette as its fallback where the Windows call is unavailable.
"""

from __future__ import annotations

import ctypes

from PySide6.QtCore import QAbstractNativeEventFilter, QByteArray, QCoreApplication, QObject, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPalette

__all__ = [
    "HCF_HIGHCONTRASTON",
    "SPI_GETHIGHCONTRAST",
    "WM_SETTINGCHANGE",
    "ContrastSource",
    "FixedContrastSource",
    "SystemContrastSource",
    "palette_snapshot",
    "read_system_high_contrast",
    "system_palette",
]

#: Win32 `SystemParametersInfoW` action that fills a `HIGHCONTRASTW`.
SPI_GETHIGHCONTRAST = 0x0042
#: `HIGHCONTRASTW.dwFlags` bit meaning a contrast theme is ON. `HCF_AVAILABLE`
#: (0x2) is set on every host and means nothing here, hence the mask.
HCF_HIGHCONTRASTON = 0x1
#: The message Windows broadcasts when a system setting, contrast included, changes.
WM_SETTINGCHANGE = 0x001A


class _HighContrastW(ctypes.Structure):
    _fields_ = (
        ("cbSize", ctypes.c_uint),
        ("dwFlags", ctypes.c_uint),
        ("lpszDefaultScheme", ctypes.c_wchar_p),
    )


def read_system_high_contrast() -> bool:
    """Whether Windows reports a contrast theme ON. `False` on any failure.

    `ctypes.windll` is looked up here, at call time, so a platform without it -
    or one where it was removed - is simply "off" (A-15.4)."""
    try:
        struct = _HighContrastW()
        struct.cbSize = ctypes.sizeof(struct)
        user32 = ctypes.windll.user32  # type: ignore[attr-defined, unused-ignore]
        ok = user32.SystemParametersInfoW(SPI_GETHIGHCONTRAST, 0, ctypes.byref(struct), 0)
        if not ok:
            return False
        return bool(struct.dwFlags & HCF_HIGHCONTRASTON)
    except Exception:
        return False


class ContrastSource(QObject):
    """The one boolean, behind an interface. `changed` carries the NEW value and
    is emitted only when the value differs from the last one reported."""

    changed = Signal(bool)

    def is_high_contrast(self) -> bool:
        raise NotImplementedError


class FixedContrastSource(ContrastSource):
    """A source whose value is set by hand: the test double."""

    def __init__(self, value: bool = False, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._value = value

    def is_high_contrast(self) -> bool:
        return self._value

    def set_value(self, value: bool) -> None:
        """Take `value`; emit `changed(value)` only if it differs."""
        if value == self._value:
            return
        self._value = value
        self.changed.emit(value)


class _SettingChangeFilter(QAbstractNativeEventFilter):
    """Calls back on a Windows `WM_SETTINGCHANGE`; never consumes a message."""

    def __init__(self, source: SystemContrastSource) -> None:
        super().__init__()
        self._source = source

    def nativeEventFilter(
        self, eventType: QByteArray | bytes | bytearray | memoryview, message: int
    ) -> object:
        try:
            if eventType == b"windows_generic_MSG":
                from ctypes import wintypes

                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_SETTINGCHANGE:
                    self._source.refresh()
        except Exception:  # a filter that raises would break the event loop
            pass
        return False, 0


class SystemContrastSource(ContrastSource):
    """The Windows setting: read at construction, re-read on `WM_SETTINGCHANGE`."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._value = read_system_high_contrast()
        self._filter: _SettingChangeFilter | None = None
        application = QCoreApplication.instance()
        if application is not None:
            # Qt does not own the filter; this reference keeps it alive.
            self._filter = _SettingChangeFilter(self)
            application.installNativeEventFilter(self._filter)

    def is_high_contrast(self) -> bool:
        """The value most recently read."""
        return self._value

    def refresh(self) -> None:
        """Re-read the setting; emit `changed` only if it flipped."""
        value = read_system_high_contrast()
        if value != self._value:
            self._value = value
            self.changed.emit(value)


_ACTIVE = QPalette.ColorGroup.Active
_DISABLED = QPalette.ColorGroup.Disabled
_ROLE = QPalette.ColorRole


def _hex(colour: QColor) -> str:
    return colour.name(QColor.NameFormat.HexRgb).upper()


def palette_snapshot(palette: QPalette) -> dict[str, str]:
    """The five roles `resolve` reads, as uppercase `#RRGGBB` (section 4.3).

    `DisabledText` is the Disabled group's `WindowText`; the other four come from
    the Active group. No other slot is read."""
    return {
        "Window": _hex(palette.color(_ACTIVE, _ROLE.Window)),
        "WindowText": _hex(palette.color(_ACTIVE, _ROLE.WindowText)),
        "Highlight": _hex(palette.color(_ACTIVE, _ROLE.Highlight)),
        "HighlightedText": _hex(palette.color(_ACTIVE, _ROLE.HighlightedText)),
        "DisabledText": _hex(palette.color(_DISABLED, _ROLE.WindowText)),
    }


#: `GetSysColor` index for each role, Win32, in `palette_snapshot`'s key order.
#: `DisabledText` is `COLOR_GRAYTEXT`, the colour Windows draws disabled text in.
_SYS_COLOR_INDEX = (
    ("Window", 5),  # COLOR_WINDOW
    ("WindowText", 8),  # COLOR_WINDOWTEXT
    ("Highlight", 13),  # COLOR_HIGHLIGHT
    ("HighlightedText", 14),  # COLOR_HIGHLIGHTTEXT
    ("DisabledText", 17),  # COLOR_GRAYTEXT
)


def _colorref_hex(colorref: int) -> str:
    """A Win32 `COLORREF` (`0x00BBGGRR`, red in the LOW byte) as `#RRGGBB`."""
    red, green, blue = colorref & 0xFF, (colorref >> 8) & 0xFF, (colorref >> 16) & 0xFF
    return f"#{red:02X}{green:02X}{blue:02X}"


def system_palette() -> dict[str, str]:
    """The five roles `resolve` reads, from Windows' own `GetSysColor` (PO-7).

    Windows, not Qt, is the source because DV-4 measured Qt's `QPalette` wrong
    under Night sky for one role: Qt's `HighlightedText` gave 1.78:1 against
    `Highlight` where Windows' own pair gives 7.96:1 (the values are in
    MT-028's DV-4 result). This is the bounded
    fallback `high-contrast.md` section 2.2 names: the source of the five-key
    mapping changes, nothing else does.

    `ctypes.windll` is looked up here, at call time. Where it is absent, or any
    one call raises, the whole mapping is `palette_snapshot` of Qt's palette -
    never a partial mix of the two, and never a raise."""
    try:
        get_sys_color = ctypes.windll.user32.GetSysColor  # type: ignore[attr-defined, unused-ignore]
        return {role: _colorref_hex(int(get_sys_color(index))) for role, index in _SYS_COLOR_INDEX}
    except Exception:
        return palette_snapshot(QGuiApplication.palette())
