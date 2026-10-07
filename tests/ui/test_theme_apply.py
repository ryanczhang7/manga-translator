"""MT-028 Contract blocks 3-6: the stylesheet is re-composed from resolved values
under High Contrast and applied; the default theme is unchanged; a live mode
change loses nothing and is announced once.

**Oracle partition: settled.** Every string, role and rule here is read out of
the design, never chosen: the composition rule is `high-contrast.md` section 2
and 2.1 ("re-compose, never drop"), the override rules are the packaged
`theme_hc.qss.tmpl` (from `theme_hc.qss.in`, `components.md` section 10.1),
the focus rule is `accessibility.md` A-15.8, the live-change rule A-15.10, the
announcement texts `high-contrast.md` section 8. Expected values are computed
from `tokens_gen.TOKENS`, MT-026's `resolve` and the packaged resources, so no
colour is typed here except the synthetic palette below.

- AC-2: `compose_stylesheet(..., high_contrast=True)` is the base template
  resolved through `resolve`, then `"\\n"`, then the override with `@{hc.Role}`
  replaced by the palette; no authored literal of a non-exempt colour survives,
  every `@static` literal does; and `apply_theme` APPLIES it (`setStyleSheet`).
- AC-4: with High Contrast off the composed sheet is the packaged `theme.qss`
  byte for byte; `main` still sets exactly that one sheet before any window,
  and touches nothing else on the application.
- AC-5: the override rules come after the base and resolve to the palette.
  RED chose BOTH forms the contract offers: the sheet must END WITH `"\\n"` plus
  the override rendered here, and the effective declarations of each named
  selector are read from the sheet parsed with the generator's own
  `tokens._COMMENT` / `tokens._RULE`.
- AC-6: every base `:focus` ring resolves to `WindowText`, except
  `QPushButton[variant="primary"]:focus`, whose effective `border-color` is
  `HighlightedText` (the rule Contract block 5 adds).
- AC-7: a real Workspace keeps its selection, column scroll, canvas zoom and
  pan, and uncommitted editor text across on -> off. "Uncommitted" is proved
  by no `editor.statusChanged` emission and `_dirty()` still true, not by a
  time bound: a commit is the only thing that starts the save timer, so an
  `elapsed < SAVE_DEBOUNCE_MS` check would discriminate nothing, and with CI
  running `tests/ui` about 4x slower than the RED host (unit 488 s vs 123 s)
  the ~95 ms measured locally would sit near 400 ms of a 500 ms limit - a
  pending failure (bound withdrawn by the orchestrator in RED).
- AC-8: one announcement per change, none at startup, no other widget.
- AC-9: a notification that is not a change does nothing.

**DV-3 (owned by GATES), named here as Contract block 7 asks.** With the
override not appended, the assertions that discriminate are AC-5's
`QPushButton:pressed` pair, the 2 px `QToolTip`/`QMenu` border, the `QWidget`
`selection-color`, both `:disabled` border colours, AC-6's primary focus ring,
and AC-5's "ends with the rendered override" and "last rule is after the
base" checks. `QPushButton:hover`'s VALUE does NOT discriminate - the base rule
already resolves it to `Window` - only its "last rule is after the base" case does.
"""

from __future__ import annotations

import ctypes
import gc
import weakref
from collections.abc import Callable, Iterator, Mapping
from importlib.resources import files
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from PySide6.QtCore import QBuffer, QSize, Qt
from PySide6.QtGui import QAccessible, QColor, QImage
from PySide6.QtWidgets import QApplication, QMainWindow

from mangatl import app as app_module
from mangatl.domain.line import Line
from mangatl.domain.page import Chapter, Page
from mangatl.store.project import create_project
from mangatl.ui import link as link_module
from mangatl.ui import theme as theme_module
from mangatl.ui import tokens, tokens_gen
from mangatl.ui.contrast import FixedContrastSource, SystemContrastSource
from mangatl.ui.link import LiveRegion, OrderedRegion
from mangatl.ui.stylesheet import (
    BASE_TEMPLATE_RESOURCE,
    HC_TEMPLATE_RESOURCE,
    base_template,
    hc_template,
)
from mangatl.ui.theme import (
    MissingPaletteRole,
    ThemeController,
    UnknownToken,
    apply_theme,
    compose_stylesheet,
    resolve,
)
from mangatl.ui.workspace import Workspace

#: MT-072 (`tests/ui/conftest.py`): every window `build_window` returns here is
#: closed at teardown, and every project it opened with it.
pytestmark = pytest.mark.usefixtures(
    "every_opened_project_is_closed", "every_built_window_is_closed"
)

T = tokens_gen.TOKENS
STATIC = "@static"

#: A synthetic contrast palette. Every value appears nowhere in `TOKENS`
#: (asserted below), so "present in the sheet" can only mean "came from here".
PALETTE: dict[str, str] = {
    "Window": "#010203",
    "WindowText": "#FDFEFF",
    "Highlight": "#1A2B3C",
    "HighlightedText": "#C3B2A1",
    "DisabledText": "#4D5E6F",
}

#: `high-contrast.md` section 8, exactly.
ANNOUNCE_ON = "High contrast on."
ANNOUNCE_OFF = "High contrast off."

PRIMARY_FOCUS = 'QPushButton[variant="primary"]:focus'


# =============================================================================
# Independent instruments: the expected sheets, computed here
# =============================================================================


def _packaged_bytes(resource: str) -> bytes:
    return files("mangatl.ui").joinpath(resource).read_bytes()


def _packaged_theme() -> str:
    return _packaged_bytes("theme.qss").decode("utf-8")


def _render_base(high_contrast: bool, palette: Mapping[str, str]) -> str:
    template = _packaged_bytes("theme.qss.tmpl").decode("utf-8")
    return tokens._PLACEHOLDER.sub(
        lambda m: resolve(m.group(1), high_contrast=high_contrast, palette=palette), template
    )


def _render_override(palette: Mapping[str, str]) -> str:
    template = _packaged_bytes("theme_hc.qss.tmpl").decode("utf-8")

    def substitute(match: Any) -> str:
        name = match.group(1)
        if name.startswith("hc."):
            return palette[name.removeprefix("hc.")]
        return resolve(name, high_contrast=True, palette=palette)

    return tokens._PLACEHOLDER.sub(substitute, template)


def _expected_hc_sheet(palette: Mapping[str, str] = PALETTE) -> str:
    """Contract block 3: base resolved under HC, `"\\n"`, override resolved."""
    return _render_base(True, palette) + "\n" + _render_override(palette)


def _compose_hc(palette: Mapping[str, str] = PALETTE) -> str:
    return compose_stylesheet(base_template(), hc_template(), high_contrast=True, palette=palette)


def _rules(sheet: str) -> list[tuple[str, list[tuple[str, str]]]]:
    """(selector list with whitespace collapsed, [(property, value), ...]) per
    rule, in sheet order - parsed with the generator's own regexes."""
    stripped = tokens._COMMENT.sub("", sheet)
    parsed = []
    for match in tokens._RULE.finditer(stripped):
        selector = " ".join(match.group(1).split())
        body = match.group(0)[match.group(0).index("{") + 1 : -1]
        declarations = []
        for part in body.split(";"):
            if ":" in part:
                prop, value = part.split(":", 1)
                declarations.append((prop.strip(), " ".join(value.split())))
        parsed.append((selector, declarations))
    return parsed


def _template_rules(template: str) -> list[tuple[str, list[tuple[str, str]]]]:
    """`_rules` over an UNRENDERED template: each `@{name}` is first rewritten
    as the brace-free `@<name>`, because `_RULE` cannot see past a `{`."""
    return _rules(tokens._PLACEHOLDER.sub(lambda m: f"@<{m.group(1)}>", template))


def _effective(sheet: str, selector: str) -> dict[str, str]:
    """The cascade within one selector: later declarations win."""
    result: dict[str, str] = {}
    for found, declarations in _rules(sheet):
        if found == selector:
            for prop, value in declarations:
                result[prop] = value
    return result


def _effective_border_colour(sheet: str, selector: str) -> str | None:
    """The colour a selector's border ends up with: a `border` shorthand sets
    it (its last word), a later `border-color` overrides it."""
    colour = None
    for found, declarations in _rules(sheet):
        if found != selector:
            continue
        for prop, value in declarations:
            if prop == "border":
                colour = value.split()[-1]
            elif prop == "border-color":
                colour = value
    return colour


# =============================================================================
# Stand-ins and recorders
# =============================================================================


class _RecordingApp:
    """An application with `setStyleSheet` and nothing else. Anything else the
    theme path touches fails the test with the attribute's name."""

    def __init__(self) -> None:
        object.__setattr__(self, "sheets", [])
        object.__setattr__(self, "touched", [])

    def setStyleSheet(self, sheet: str) -> None:
        self.sheets.append(sheet)

    def __getattr__(self, name: str) -> Any:
        self.touched.append(name)
        pytest.fail(f"the theme path touched app.{name}; only setStyleSheet is permitted")


@pytest.fixture
def recorded_alerts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, Any]]:
    """Replace `mangatl.ui.link.QAccessible` (imported BY NAME) with a recorder
    of (event type, event object), as `tests/ui/test_canvas_keys.py` does."""
    posted: list[tuple[Any, Any]] = []
    stand_in = SimpleNamespace(
        Event=QAccessible.Event,
        updateAccessibility=lambda event: posted.append((event.type(), event.object())),
    )
    monkeypatch.setattr(link_module, "QAccessible", stand_in)
    return posted


def _alerts(posted: list[tuple[Any, Any]]) -> list[Any]:
    return [obj for kind, obj in posted if kind == QAccessible.Event.Alert]


@pytest.fixture
def real_sheet_restored(qapp: QApplication) -> Iterator[QApplication]:
    """For tests that apply a sheet to the real application: `""` goes back."""
    try:
        yield qapp
    finally:
        qapp.setStyleSheet("")


# =============================================================================
# Fixture checks (the instruments, not the code under test)
# =============================================================================


def test_the_synthetic_palette_uses_no_value_any_token_has() -> None:
    """Fixture check: presence of a palette value in a sheet is unambiguous."""
    authored = {value.upper() for value in T.values()}
    clashes = {role: value for role, value in PALETTE.items() if value.upper() in authored}
    assert clashes == {}


def _non_exempt_colour_literals() -> set[str]:
    """AC-2: the authored value of every colour token whose HC role is a
    palette role - i.e. not `@static`. From `HC_PALETTE_ROLE`, never typed."""
    return {T[name].upper() for name, role in tokens_gen.HC_PALETTE_ROLE.items() if role != STATIC}


def _static_colour_tokens() -> set[str]:
    return {name for name, role in tokens_gen.HC_PALETTE_ROLE.items() if role == STATIC}


def test_no_exempt_colour_shares_its_literal_with_a_non_exempt_one_the_base_uses() -> None:
    """Fixture check: if an `@static` colour the base template uses had the same
    literal as a non-exempt one, AC-2's two halves would contradict."""
    used = set(tokens._PLACEHOLDER.findall(_packaged_bytes("theme.qss.tmpl").decode("utf-8")))
    exempt_used = {T[name].upper() for name in _static_colour_tokens() & used}
    assert exempt_used & _non_exempt_colour_literals() == set()


# =============================================================================
# Block 3: the templates come from the package
# =============================================================================


def test_the_loader_names_both_packaged_templates() -> None:
    assert BASE_TEMPLATE_RESOURCE == "theme.qss.tmpl"
    assert HC_TEMPLATE_RESOURCE == "theme_hc.qss.tmpl"


@pytest.mark.parametrize(
    "load, resource",
    [(base_template, "theme.qss.tmpl"), (hc_template, "theme_hc.qss.tmpl")],
    ids=["base", "override"],
)
def test_each_template_is_the_packaged_resource_read_as_utf8_byte_for_byte(
    load: Callable[[], str], resource: str
) -> None:
    text = load()
    assert isinstance(text, str)
    assert text.encode("utf-8") == _packaged_bytes(resource)


# =============================================================================
# AC-4: High Contrast off is the default theme, byte for byte
# =============================================================================


@pytest.mark.parametrize("palette", [{}, PALETTE], ids=["empty palette", "a contrast palette"])
def test_with_high_contrast_off_the_composed_sheet_is_the_packaged_theme_byte_for_byte(
    palette: dict[str, str],
) -> None:
    """AC-4: and the palette is not consulted at all when the mode is off."""
    sheet = compose_stylesheet(base_template(), hc_template(), high_contrast=False, palette=palette)

    expected = _packaged_bytes("theme.qss")
    assert sheet.encode("utf-8") == expected, (
        f"High Contrast off composed {len(sheet)} chars that are not the packaged"
        f" mangatl.ui/theme.qss ({len(expected)} bytes)"
    )


def test_with_high_contrast_off_the_override_template_is_not_appended() -> None:
    sheet = compose_stylesheet(
        "QWidget { color: @{color.text.primary}; }",
        "QWidget { color: @{hc.WindowText}; }",
        high_contrast=False,
        palette=PALETTE,
    )
    assert sheet == f"QWidget {{ color: {T['color.text.primary']}; }}"


# =============================================================================
# AC-2: under High Contrast the sheet is re-composed, never dropped or narrowed
# =============================================================================


def test_under_high_contrast_the_sheet_is_the_resolved_base_then_the_resolved_override() -> None:
    """AC-2 and Contract block 3, exactly: not a smaller sheet, not the base
    alone, not the override alone."""
    assert _compose_hc() == _expected_hc_sheet()


def test_under_high_contrast_no_authored_literal_of_a_non_exempt_colour_survives() -> None:
    """AC-2's assertable form. Case-insensitive: QSS does not care about hex case."""
    sheet = _compose_hc().upper()
    literals = _non_exempt_colour_literals()
    assert literals, "fixture: no non-exempt colour literal was derived"

    surviving = sorted(literal for literal in literals if literal in sheet)
    assert surviving == [], f"authored literals still in the High Contrast sheet: {surviving}"


def test_under_high_contrast_every_static_colour_the_base_uses_keeps_its_literal() -> None:
    """AC-2, over the real base template (today it uses no `@static` colour, so
    the next test carries this half of AC-2 against a template that does)."""
    used = set(tokens._PLACEHOLDER.findall(base_template()))
    sheet = _compose_hc().upper()
    missing = sorted(
        name for name in _static_colour_tokens() & used if T[name].upper() not in sheet
    )
    assert missing == []


@pytest.mark.parametrize(
    "token",
    ["color.canvas.surround", "color.canvas.page-edge", "overlay.bubble.idle", "overlay.halo"],
)
def test_under_high_contrast_a_static_colour_in_the_base_keeps_its_authored_literal(
    token: str,
) -> None:
    """AC-2: `@static` is exempt in a composed sheet too."""
    sheet = compose_stylesheet(
        f"QFrame {{ background-color: @{{{token}}}; color: @{{color.text.primary}}; }}",
        "",
        high_contrast=True,
        palette=PALETTE,
    )
    assert T[token] in sheet
    assert PALETTE["WindowText"] in sheet


@pytest.mark.parametrize("role", list(PALETTE))
def test_under_high_contrast_each_palette_colour_reaches_the_sheet(role: str) -> None:
    assert PALETTE[role] in _compose_hc(), f"{role} ({PALETTE[role]}) is not in the sheet"


def test_applying_the_theme_under_high_contrast_sets_the_composed_sheet_on_the_application(
    qapp: QApplication,
) -> None:
    """AC-2: APPLIED, with `setStyleSheet` - not composed and then bypassed
    (DV-1: guarding `setStyleSheet` with `if not high_contrast` fails here)."""
    app = _RecordingApp()

    controller = apply_theme(app, FixedContrastSource(True), palette_provider=lambda: dict(PALETTE))

    assert app.sheets == [_expected_hc_sheet()], (
        f"setStyleSheet was called {len(app.sheets)} times; expected once with the"
        " High Contrast composition"
    )
    assert isinstance(controller, ThemeController)
    assert controller.high_contrast is True
    assert app.touched == []


def test_the_palette_is_read_only_when_high_contrast_is_being_applied(qapp: QApplication) -> None:
    """Contract block 4: with the mode off the provider is never called (PO-4)."""
    app = _RecordingApp()
    reads: list[int] = []

    def provider() -> dict[str, str]:
        reads.append(1)
        return dict(PALETTE)

    source = FixedContrastSource(False)
    controller = apply_theme(app, source, palette_provider=provider)
    assert reads == []
    assert app.sheets == [_packaged_theme()]
    assert controller.high_contrast is False

    source.set_value(True)
    assert len(reads) >= 1
    assert app.sheets[-1] == _expected_hc_sheet()


# --- Block 3: nothing is swallowed ----------------------------------------------------


def test_an_override_role_the_palette_lacks_raises_and_names_it() -> None:
    palette = {role: value for role, value in PALETTE.items() if role != "HighlightedText"}
    with pytest.raises(MissingPaletteRole) as raised:
        compose_stylesheet(
            "", "QWidget { color: @{hc.HighlightedText}; }", high_contrast=True, palette=palette
        )
    assert raised.value.token == "hc.HighlightedText"
    assert raised.value.role == "HighlightedText"


def test_a_base_token_whose_role_the_palette_lacks_raises_under_high_contrast() -> None:
    palette = {role: value for role, value in PALETTE.items() if role != "Highlight"}
    with pytest.raises(MissingPaletteRole) as raised:
        compose_stylesheet(base_template(), hc_template(), high_contrast=True, palette=palette)
    assert raised.value.role == "Highlight"


@pytest.mark.parametrize(
    "high_contrast, where",
    [(False, "base"), (True, "base"), (True, "override")],
    ids=["off, in the base", "on, in the base", "on, in the override"],
)
def test_an_unknown_token_raises_rather_than_rendering(high_contrast: bool, where: str) -> None:
    """Contract block 3: `UnknownToken` from MT-026, never a silent blank. (Off,
    the override is not rendered at all - pinned above.)"""
    bad = "QWidget { color: @{color.no-such-token}; }"
    base, override = (bad, "") if where == "base" else ("", bad)
    with pytest.raises(UnknownToken) as raised:
        compose_stylesheet(base, override, high_contrast=high_contrast, palette=PALETTE)
    assert raised.value.token == "color.no-such-token"


# =============================================================================
# AC-5: the override rules come after the base and resolve to the palette
# =============================================================================


def test_under_high_contrast_the_rendered_override_is_appended_after_the_whole_base() -> None:
    sheet = _compose_hc()
    override = _render_override(PALETTE)
    base = _render_base(True, PALETTE)

    assert sheet.endswith("\n" + override), "the override is not the end of the sheet"
    assert sheet.startswith(base), "the sheet does not begin with the whole resolved base"
    first_base_rule = _rules(base)[0][0]
    first_override_rule = _rules(override)[0][0]
    assert sheet.index(first_base_rule) < len(base) < sheet.rindex(first_override_rule)


EMPHASIS = f"{T['border-width.emphasis']}px"

#: AC-5, from `theme_hc.qss.in` / `components.md` section 10.1: selector ->
#: the declarations its effective (last-wins) rule must carry, as palette roles.
OVERRIDES: dict[str, dict[str, str]] = {
    "QWidget": {
        "selection-background-color": "{Highlight}",
        "selection-color": "{HighlightedText}",
    },
    "QPushButton:hover": {"background-color": "{Window}"},
    "QPushButton:pressed": {"background-color": "{Highlight}", "color": "{HighlightedText}"},
    "QPushButton:disabled": {"border-color": "{DisabledText}"},
    "QLineEdit:disabled, QPlainTextEdit:disabled": {"border-color": "{DisabledText}"},
    "QToolTip": {"border": EMPHASIS + " solid {WindowText}"},
    "QMenu": {"border": EMPHASIS + " solid {WindowText}"},
}


@pytest.mark.parametrize("selector", list(OVERRIDES))
def test_under_high_contrast_each_override_rule_wins_with_its_palette_value(selector: str) -> None:
    """AC-5: hover is never a ground change; pressed and selection are the
    Highlight pair; disabled borders are DisabledText; e2 is a 2 px WindowText
    boundary."""
    effective = _effective(_compose_hc(), selector)
    expected = {prop: value.format(**PALETTE) for prop, value in OVERRIDES[selector].items()}

    wrong = {
        prop: effective.get(prop)
        for prop, value in expected.items()
        if effective.get(prop) != value
    }
    assert wrong == {}, f"{selector}: expected {expected}"


@pytest.mark.parametrize("selector", list(OVERRIDES))
def test_under_high_contrast_the_last_rule_for_each_override_selector_is_the_override(
    selector: str,
) -> None:
    """AC-5: "after the base rules" - the last rule naming the selector is in
    the appended block, so it wins at equal specificity."""
    selectors = [found for found, _ in _rules(_compose_hc())]
    base_rule_count = len(_rules(_render_base(True, PALETTE)))
    assert selector in selectors, f"no {selector} rule in the sheet"
    last = len(selectors) - 1 - selectors[::-1].index(selector)
    assert last >= base_rule_count, (
        f"the last {selector} rule is rule {last}, inside the base's {base_rule_count} rules"
    )


# =============================================================================
# AC-6: focus takes the foreground of the ground it sits on (A-15.8)
# =============================================================================


def _base_focus_ring_selectors() -> list[str]:
    """Every `:focus` rule the base template defines whose ring is `color.focus.ring`."""
    return [
        selector
        for selector, declarations in _template_rules(base_template())
        if ":focus" in selector and any("@<color.focus.ring>" in value for _, value in declarations)
    ]


def test_the_base_defines_the_primary_button_focus_ring_and_others() -> None:
    """Fixture check: AC-6 is about a real set of rules, including the one
    `Highlight`-ground selector."""
    selectors = _base_focus_ring_selectors()
    assert PRIMARY_FOCUS in selectors
    assert len(selectors) >= 2, selectors


def test_the_packaged_override_template_carries_the_primary_button_focus_rule() -> None:
    """AC-6 / Contract block 5: GREEN regenerated `theme_hc.qss.tmpl`."""
    assert PRIMARY_FOCUS in [selector for selector, _ in _template_rules(hc_template())]


def test_under_high_contrast_every_window_ground_focus_ring_is_window_text() -> None:
    """AC-6: every base `:focus` ring except the primary button's resolves to
    `WindowText`."""
    sheet = _compose_hc()
    wrong = {
        selector: _effective_border_colour(sheet, selector)
        for selector in _base_focus_ring_selectors()
        if selector != PRIMARY_FOCUS
        and _effective_border_colour(sheet, selector) != PALETTE["WindowText"]
    }
    assert wrong == {}, f"focus rings not WindowText ({PALETTE['WindowText']}): {wrong}"


def test_under_high_contrast_the_primary_button_focus_ring_is_highlighted_text() -> None:
    """AC-6: the one `Highlight`-ground selector takes `HighlightedText`."""
    colour = _effective_border_colour(_compose_hc(), PRIMARY_FOCUS)
    assert colour == PALETTE["HighlightedText"], (
        f"{PRIMARY_FOCUS} ring is {colour}, not HighlightedText ({PALETTE['HighlightedText']})"
    )


# =============================================================================
# AC-4 / Block 6: startup applies one sheet, the default, before any window
# =============================================================================


def _pages_folder(root: Path, name: str, size: QSize) -> Path:
    folder = root / name
    folder.mkdir()
    image = QImage(size, QImage.Format.Format_RGB32)
    image.fill(QColor(T["color.surface.raised"]))
    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    (folder / "page 1.png").write_bytes(bytes(buffer.data().data()))
    buffer.close()
    return folder


SMALL_PAGE = QSize(60, 80)


def _project_folder(root: Path, size: QSize = SMALL_PAGE) -> Path:
    folder = _pages_folder(root, "with project", size)
    chapter = Chapter(
        source_dir=folder,
        pages=(
            Page(
                ordinal=0,
                filename="page 1.png",
                width=size.width(),
                height=size.height(),
                sha256="0" * 64,
            ),
        ),
    )
    with create_project(chapter, root / "with project.mtproj"):
        pass
    return folder


LAUNCHES: dict[str, Callable[[Path], list[str]]] = {
    "no argument": lambda root: [],
    "a folder with a project": lambda root: [str(_project_folder(root))],
}


def _run_main(
    qtbot: Any, monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> tuple[list[tuple[str, object]], list[str], list[weakref.ref[Any]]]:
    """`main(argv)` with a recording `QApplication` stand-in, on a host with no
    contrast theme (no `ctypes.windll`). Returns (event log, attributes the
    stand-in was asked for besides its own, weak refs to the controllers)."""
    events: list[tuple[str, object]] = []
    touched: list[str] = []
    controllers: list[weakref.ref[Any]] = []
    built: list[QMainWindow] = []
    real_build = app_module.build_window
    real_apply = app_module.apply_theme

    def recording_build(arguments: list[str]) -> QMainWindow:
        events.append(("build_window", list(arguments)))
        window = real_build(arguments)
        qtbot.addWidget(window)
        built.append(window)
        return window

    def recording_apply(app: Any, source: Any, **options: Any) -> Any:
        events.append(("apply_theme", source))
        controller = real_apply(app, source, **options)
        controllers.append(weakref.ref(controller))
        return controller

    class _RecordingQApplication:
        def __init__(self, argv: list[str]) -> None:
            events.append(("QApplication", list(argv)))

        def setStyleSheet(self, sheet: str) -> None:
            events.append(("setStyleSheet", sheet))

        def exec(self) -> int:
            events.append(("exec", None))
            for window in built:
                window.close()
            return 0

        def __getattr__(self, name: str) -> Any:
            touched.append(name)
            pytest.fail(f"main touched app.{name}; only setStyleSheet and exec are permitted")

    monkeypatch.delattr(ctypes, "windll", raising=False)
    monkeypatch.setattr(app_module, "build_window", recording_build)
    monkeypatch.setattr(app_module, "apply_theme", recording_apply)
    monkeypatch.setattr(app_module, "QApplication", _RecordingQApplication)
    assert app_module.main(argv) == 0
    assert len(built) == 1, f"main built {len(built)} windows"
    return events, touched, controllers


@pytest.mark.parametrize("launch", list(LAUNCHES))
def test_startup_sets_exactly_the_packaged_theme_once_before_any_window(
    qtbot: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, launch: str
) -> None:
    """AC-4: MT-061 AC-1 keeps holding once `main` goes through `apply_theme`."""
    events, touched, _ = _run_main(qtbot, monkeypatch, ["mangatl", *LAUNCHES[launch](tmp_path)])

    names = [name for name, _ in events]
    sheets = [value for name, value in events if name == "setStyleSheet"]
    assert len(sheets) == 1, f"launched with {launch}: {names}"
    assert isinstance(sheets[0], str)
    assert sheets[0].encode("utf-8") == _packaged_bytes("theme.qss")
    assert names.index("setStyleSheet") < names.index("build_window"), names
    assert names[-1] == "exec", names
    assert touched == [], f"main touched app.{touched}"


@pytest.mark.parametrize("launch", list(LAUNCHES))
def test_startup_follows_the_system_contrast_source_through_one_apply_theme(
    qtbot: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, launch: str
) -> None:
    """Contract block 6: `apply_theme(app, SystemContrastSource())` before
    `build_window`, and the controller outlives `main`'s locals (else a live
    change at runtime would reach nothing)."""
    events, _, controllers = _run_main(qtbot, monkeypatch, ["mangatl", *LAUNCHES[launch](tmp_path)])

    names = [name for name, _ in events]
    applied = [value for name, value in events if name == "apply_theme"]
    assert len(applied) == 1, names
    assert isinstance(applied[0], SystemContrastSource)
    assert (
        names.index("QApplication")
        < names.index("apply_theme")
        < names.index("setStyleSheet")
        < names.index("build_window")
    ), names
    gc.collect()
    assert controllers[0]() is not None, "the ThemeController did not outlive main()"


# =============================================================================
# AC-7: a live change loses nothing
# =============================================================================

#: Rows enough that the column scrolls (16 rows: measured column maximum 4
#: offscreen at 1100x720 against a candidate, RED handoff); a page large
#: enough that zoom 2.0 leaves both canvas scroll bars a range.
ROWS = 16
BIG_PAGE = QSize(1600, 2400)
WINDOW = QSize(1100, 720)


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


def _line(index: int) -> Line:
    return Line(
        reading_index=index,
        source_ja=f"ja {index}",
        proposed_en=f"Hello {index}.",
        final_en=None,
        status="proposed",
        edited_at=None,
        ocr_empty=False,
    )


def _snapshot(window: Workspace) -> dict[str, object]:
    canvas = window.page_canvas
    editor = window.translation_column.row(1).editor
    return {
        "selected_region_id": window.link.state.selected_region_id,
        "column scroll": window.translation_column.list.verticalScrollBar().value(),
        "canvas zoom": canvas.transform().m11(),
        "canvas horizontal scroll": canvas.horizontalScrollBar().value(),
        "canvas vertical scroll": canvas.verticalScrollBar().value(),
        "editor text": editor.text(),
        "editor uncommitted": editor._dirty(),
        "editor status": editor.status,
    }


def test_switching_high_contrast_on_and_off_loses_no_selection_scroll_zoom_or_typed_text(
    qtbot: Any, real_sheet_restored: QApplication, tmp_path: Path
) -> None:
    """AC-7 (A-15.10, section 8): the uncommitted text is the one that would
    hurt. DV-2: a handler that clears the focused editor fails here.

    No elapsed-time bound against `SAVE_DEBOUNCE_MS`: a commit is the only thing
    that starts the save timer, and `commits == []` over `editor.statusChanged`
    (with `_dirty()` still true) already proves none happened, so a time bound
    would discriminate nothing. It would also fail spuriously: CI runs
    `tests/ui` about 4x slower than the RED host (unit 488 s vs 123 s), putting
    the ~95 ms measured locally near 400 ms against a 500 ms limit."""
    qapp = real_sheet_restored
    source = FixedContrastSource(False)
    controller = apply_theme(qapp, source, palette_provider=lambda: dict(PALETTE))
    assert qapp.styleSheet() == _packaged_theme(), "precondition: the default theme"

    window = app_module.build_window([str(_project_folder(tmp_path, BIG_PAGE))])
    assert isinstance(window, Workspace)
    qtbot.addWidget(window)
    window.resize(WINDOW)
    with qtbot.waitExposed(window):
        window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    regions = [
        OrderedRegion(i, ((40, 40 + 70 * i), (400, 40 + 70 * i), (400, 90 + 70 * i)))
        for i in range(ROWS)
    ]
    window.set_regions(
        regions,
        [f"ja {i}" for i in range(ROWS)],
        [f"Hello {i}." for i in range(ROWS)],
        [_line(i) for i in range(ROWS)],
    )
    _settle()

    window.link.select(1)
    canvas = window.page_canvas
    canvas.set_zoom(2.0)
    horizontal, vertical = canvas.horizontalScrollBar(), canvas.verticalScrollBar()
    horizontal.setValue(horizontal.maximum() // 3)
    vertical.setValue(vertical.maximum() // 3)
    editor = window.translation_column.row(1).editor
    editor.setFocus(Qt.FocusReason.OtherFocusReason)
    qtbot.waitUntil(editor.hasFocus)
    commits: list[str] = []
    editor.statusChanged.connect(commits.append)

    qtbot.keyClicks(editor, " typed")  # and NOT Enter: the edit stays uncommitted
    column = window.translation_column.list.verticalScrollBar()
    column.setValue(column.maximum() // 2)
    _settle()

    before = _snapshot(window)
    # Preconditions: each of the four is in a non-default state, or the test is vacuous.
    assert before["selected_region_id"] == 1, before
    assert before["column scroll"] > 0, f"the column did not scroll: {before}"
    assert before["canvas zoom"] == 2.0, before
    assert before["canvas horizontal scroll"] > 0, before
    assert before["canvas vertical scroll"] > 0, before
    assert before["editor text"] == "Hello 1. typed", before
    assert before["editor uncommitted"] is True, before

    sheets = [qapp.styleSheet()]
    for value, expected_sheet in ((True, _expected_hc_sheet()), (False, _packaged_theme())):
        source.set_value(value)
        _settle()
        sheets.append(qapp.styleSheet())
        assert sheets[-1] != sheets[-2], f"switching to {value} did not change the sheet"
        assert sheets[-1] == expected_sheet, f"switching to {value} applied the wrong sheet"
        after = _snapshot(window)
        lost = {key: (before[key], after[key]) for key in before if after[key] != before[key]}
        assert lost == {}, f"switching High Contrast to {value} lost (before, after): {lost}"
        assert commits == [], f"switching to {value} committed the typed text: {commits}"
    assert controller.high_contrast is False


# =============================================================================
# AC-8: announced once, never at startup, and nothing shown
# =============================================================================


def test_a_live_change_is_announced_once_each_way_and_startup_announces_nothing(
    qapp: QApplication, recorded_alerts: list[tuple[Any, Any]]
) -> None:
    app = _RecordingApp()
    source = FixedContrastSource(False)
    controller = apply_theme(app, source, palette_provider=lambda: dict(PALETTE))
    assert _alerts(recorded_alerts) == [], "the startup apply announced something"

    source.set_value(True)
    assert len(_alerts(recorded_alerts)) == 1
    assert controller.live_region.text() == ANNOUNCE_ON

    source.set_value(False)
    assert len(_alerts(recorded_alerts)) == 2
    assert controller.live_region.text() == ANNOUNCE_OFF
    assert all(obj is controller.live_region for obj in _alerts(recorded_alerts))


def test_each_apply_reports_the_mode_it_applied(qapp: QApplication) -> None:
    """Contract block 4: `themeApplied(bool)` after each apply; `high_contrast`
    is the mode most recently applied."""
    app = _RecordingApp()
    source = FixedContrastSource(False)
    controller = apply_theme(app, source, palette_provider=lambda: dict(PALETTE))
    applied: list[bool] = []
    controller.themeApplied.connect(applied.append)

    source.set_value(True)
    assert controller.high_contrast is True
    source.set_value(False)
    assert controller.high_contrast is False
    assert applied == [True, False]
    assert len(app.sheets) == 3


def test_a_live_change_shows_no_notice_banner_or_toast(qapp: QApplication) -> None:
    """AC-8: the only widget the theme path creates is its parentless,
    off-screen `LiveRegion`."""
    before = list(QApplication.topLevelWidgets())
    app = _RecordingApp()
    source = FixedContrastSource(False)
    controller = apply_theme(app, source, palette_provider=lambda: dict(PALETTE))
    source.set_value(True)
    source.set_value(False)
    _settle()

    assert isinstance(controller.live_region, LiveRegion)
    assert controller.live_region.parent() is None
    new = [
        widget
        for widget in QApplication.topLevelWidgets()
        if not any(widget is old for old in before) and widget is not controller.live_region
    ]
    assert new == [], f"the theme path showed: {[type(w).__name__ for w in new]}"


def test_the_theme_module_takes_nothing_from_the_progress_notices() -> None:
    """Contract block 4: no notice machinery is even reachable from `theme`.
    Pins that no name bound in `mangatl.ui.theme` is the `mangatl.ui.progress`
    module or an object defined there."""
    offenders = [
        name
        for name, value in vars(theme_module).items()
        if (isinstance(value, ModuleType) and value.__name__.startswith("mangatl.ui.progress"))
        or getattr(value, "__module__", None) == "mangatl.ui.progress"
    ]
    assert offenders == []


# =============================================================================
# AC-9: a notification that is not a change does nothing
# =============================================================================


@pytest.mark.parametrize("mode", [False, True])
def test_a_change_signal_carrying_the_current_mode_reapplies_and_announces_nothing(
    qapp: QApplication, recorded_alerts: list[tuple[Any, Any]], mode: bool
) -> None:
    app = _RecordingApp()
    source = FixedContrastSource(False)
    controller = apply_theme(app, source, palette_provider=lambda: dict(PALETTE))
    if mode:
        source.set_value(True)
    sheets, alerts = len(app.sheets), len(_alerts(recorded_alerts))

    source.changed.emit(mode)
    source.set_value(mode)

    assert len(app.sheets) == sheets, "a non-change re-applied the sheet"
    assert len(_alerts(recorded_alerts)) == alerts, "a non-change was announced"
    assert controller.high_contrast is mode
