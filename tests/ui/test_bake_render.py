"""MT-066 C-3/C-4: Render in the workspace, both steps off the GUI thread.

`mangatl.ui.bake.BakeController` (new, C-3) runs `preview_bake` and then, on
confirm, `bake_chapter`, each on a `threading.Thread` with its own `Project`,
following MT-059's `RunController`. `Workspace` (C-4) gains `render_button`,
`render_status`, `render()` and `bake_dialog`.

**The seam** (C-3): `open_project`, `preview_bake` and `bake_chapter` are called
as attributes of `mangatl.ui.bake`, so the tests patch them there. Every fake
here is a `Step`: it records the thread that called it and what it was given,
then (when told to) blocks on a `threading.Event` for at most `GATE_S` - never
longer - and returns its value or raises its error.

Oracle partition (story C-6):

- **AC-1 wiring, AC-2, AC-3:** mechanical. The dialog the workspace opens is
  built from the preview the worker produced; with unreviewed lines confirm is
  shown, enabled and default and starts the bake; focus returns to
  `render_button` however the dialog closes, and Tab stays in the dialog.
- **AC-4: an invented metric with a negative control.** While the fake step is
  blocked: (a) its recorded thread is not the main thread; (b) a
  `QTimer.singleShot(0, ...)` the test posts fires within 1000 ms; (c) the button
  is `loading`. The negative control - the worker run synchronously on the GUI
  thread - must fail (a) and (b), and must FAIL rather than hang: the fake gives
  up after `GATE_S`. That control needs the real controller to break, so it is
  DV-2, owned by GATES (story `## Handoff` records the expected outcome).
- **The pending edit (C-4 step 1)** runs the REAL `preview_bake` on a real
  project: an edit typed and not yet saved must be counted as reviewed. DV-4
  removes the first `flush()` and expects that test to fail. The save debounce
  is patched to 60 s there so that only `render()`'s flush can write the edit -
  without it the test would race a 500 ms timer.

**Budgets are liveness bounds, not cost estimates.** A fake step returns in
microseconds once released; `WAIT_MS` is two orders of magnitude over that for
the coverage-instrumented run on CI. The pending-edit test's real preview reads
one uncleaned 60x80 page and typesets nothing. No timing here comes from CI yet:
GREEN's first CI run is the first CI number.

RED: `mangatl.ui.bake` and `mangatl.ui.bake_dialog` do not exist, so this file
fails at import and no assertion in it has run.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from PySide6.QtCore import QObject, Qt, QTimer, Slot
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QWidget
from shiboken6 import isValid

import mangatl.ui.bake as bake_ui
import mangatl.ui.line_editor as line_editor_module
from mangatl.domain.line import OcrResult
from mangatl.domain.region import RawRegion
from mangatl.pipeline.bake import BakePreview, BakeReport, LineRef
from mangatl.pipeline.bake import preview_bake as real_preview_bake
from mangatl.store.intake import read_chapter
from mangatl.store.project import Project, create_project, open_project, project_dir_for
from mangatl.ui.bake import BakeController
from mangatl.ui.bake_dialog import BakeConfirmDialog
from mangatl.ui.buttons import ActivatedByEnter
from mangatl.ui.workspace import Workspace

# --- Settled copy (C-4, voice.md), spelled out -----------------------------------
REST_TEXT = "Render pages"
LOADING_NAME = "Render pages, working"
LOADING_TEXT = "\N{MIDDLE DOT}" * 3

# --- Liveness bounds (module docstring) ------------------------------------------
#: C-6: the fake blocks at most this long, so a synchronous worker fails, not hangs.
GATE_S = 5.0
#: C-6 (b): a timer the test posts must fire within this while a step is blocked.
RESPONSIVE_MS = 1_000
#: How long the GUI waits for a released step's result to arrive.
WAIT_MS = 10_000
#: How long a focus change may take to land offscreen.
FOCUS_MS = 2_000
#: closeEvent: how long the blocked bake keeps going after its release, so a
#: close that does not wait for it emits `closed` visibly before it returns.
LINGER_S = 0.2

PAGE_SIZE = (60, 80)


# =============================================================================
# Fake steps
# =============================================================================


@dataclass
class Step:
    """A fake `preview_bake` / `bake_chapter`: records, maybe blocks, then
    returns `result` or raises it."""

    result: Any
    block: bool = False
    linger_s: float = 0.0
    threads: list[threading.Thread] = field(default_factory=list)
    args: list[tuple[Any, ...]] = field(default_factory=list)
    source_dirs: list[Path] = field(default_factory=list)
    entered: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)
    returned: threading.Event = field(default_factory=threading.Event)
    opened: bool | None = None
    _in_flight: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __call__(self, *args: Any) -> Any:
        with self._lock:
            self._in_flight += 1
            self.threads.append(threading.current_thread())
            self.args.append(args)
            project = args[0]
            if isinstance(project, Project):
                self.source_dirs.append(project.chapter.source_dir)
        try:
            self.entered.set()
            if self.block:
                self.opened = self.release.wait(GATE_S)
                if self.linger_s:
                    time.sleep(self.linger_s)
            if isinstance(self.result, BaseException):
                raise self.result
            return self.result
        finally:
            with self._lock:
                self._in_flight -= 1
            self.returned.set()

    @property
    def calls(self) -> int:
        return len(self.args)

    def idle(self) -> bool:
        with self._lock:
            return self._in_flight == 0


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


# =============================================================================
# Chapters
# =============================================================================


def _png(size: tuple[int, int], bits: bool = False) -> bytes:
    buffer = BytesIO()
    if bits:
        Image.new("1", size, 1).save(buffer, format="PNG")
    else:
        Image.new("RGB", size, (240, 240, 240)).save(buffer, format="PNG")
    return buffer.getvalue()


def _source(tmp_path: Path, pages: int) -> Path:
    source_dir = tmp_path / "ch 01"
    source_dir.mkdir()
    for i in range(pages):
        (source_dir / f"{i + 1:02d}.png").write_bytes(_png(PAGE_SIZE))
    return source_dir


def _ring(x0: int, y0: int, x1: int, y1: int) -> tuple[tuple[int, int], ...]:
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))


def _en(source_dir: Path) -> Path:
    """`<source>_en`, spelled out (architecture.md §5), never derived."""
    return source_dir.parent / (source_dir.name + "_en")


@dataclass
class Rig:
    source_dir: Path
    project: Project
    window: Workspace
    preview: Step
    bake: Step
    steps: list[Step]

    @property
    def output_dir(self) -> Path:
        return _en(self.source_dir)


def _show(qtbot, window: QWidget) -> None:  # type: ignore[no-untyped-def]
    qtbot.addWidget(window)
    window.resize(1100, 720)
    with qtbot.waitExposed(window):
        window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    _settle()


def _default_preview(source_dir: Path) -> BakePreview:
    return BakePreview(
        output_dir=_en(source_dir),
        page_count=2,
        total_lines=3,
        unreviewed=(LineRef(page_ordinal=1, reading_index=0),),
        failed=(),
        overflowing=(),
    )


def _report(pages: int) -> BakeReport:
    return BakeReport(pages_written=pages, regions_empty=0, unreviewed_lines=1, pages_uncleaned=0)


def _teardown(qtbot, steps: list[Step], window: Workspace) -> None:  # type: ignore[no-untyped-def]
    """Release every fake, wait (bounded) for each to return, then close."""
    for step in steps:
        step.release.set()
    for step in steps:
        qtbot.waitUntil(step.idle, timeout=int(GATE_S * 1000) + WAIT_MS)
    _settle()
    if not isValid(window):  # a failing test may have lost it already
        return
    dialog = getattr(window, "bake_dialog", None)
    if isinstance(dialog, QWidget) and isValid(dialog) and dialog.isVisible():
        dialog.close()
    window.close()
    _settle()


@pytest.fixture
def rig(qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Rig]:  # type: ignore[no-untyped-def]
    """A two-page chapter (no regions) open in a shown Workspace, with
    `preview_bake` and `bake_chapter` replaced at the seam by `Step`s."""
    source_dir = _source(tmp_path, 2)
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)):
        pass
    preview = Step(_default_preview(source_dir))
    bake = Step(_report(2))
    monkeypatch.setattr(bake_ui, "preview_bake", preview)
    monkeypatch.setattr(bake_ui, "bake_chapter", bake)
    project = open_project(project_dir_for(source_dir))
    window = Workspace()
    _show(qtbot, window)
    window.load_chapter(project)
    _settle()
    made = Rig(source_dir, project, window, preview, bake, [preview, bake])
    try:
        yield made
    finally:
        _teardown(qtbot, made.steps, window)
        project.__exit__(None, None, None)


def _dialog(qtbot, window: Workspace) -> BakeConfirmDialog:  # type: ignore[no-untyped-def]
    qtbot.waitUntil(
        lambda: (
            isinstance(getattr(window, "bake_dialog", None), BakeConfirmDialog)
            and window.bake_dialog.isVisible()
        ),
        timeout=WAIT_MS,
    )
    dialog = window.bake_dialog
    assert isinstance(dialog, BakeConfirmDialog)
    _settle()
    return dialog


def _focus_render(qtbot, window: Workspace) -> None:  # type: ignore[no-untyped-def]
    window.render_button.setFocus(Qt.FocusReason.OtherFocusReason)
    qtbot.waitUntil(window.render_button.hasFocus, timeout=FOCUS_MS)


def _confirm_dialog(qtbot, window: Workspace) -> BakeConfirmDialog:  # type: ignore[no-untyped-def]
    dialog = _dialog(qtbot, window)
    QTest.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)
    _settle()
    return dialog


def _at_rest(window: Workspace) -> bool:
    button = window.render_button
    return (
        button.property("loading") is False
        and button.accessibleName() == REST_TEXT
        and button.text() == REST_TEXT
    )


def _assert_loading(window: Workspace, rest_width: int) -> None:
    button = window.render_button
    assert button.property("loading") is True, "the button is not in its loading state"
    assert button.accessibleName() == LOADING_NAME
    assert button.text() == LOADING_TEXT
    assert button.width() == rest_width, (
        f"the loading button is {button.width()} px wide, {rest_width} px at rest"
    )


def _responsive(qtbot, step: Step) -> None:  # type: ignore[no-untyped-def]
    """C-6 (b): a timer posted now fires within RESPONSIVE_MS, and `step` is
    still blocked when it does."""
    fired: list[bool] = []
    QTimer.singleShot(0, lambda: fired.append(True))
    qtbot.waitUntil(lambda: bool(fired), timeout=RESPONSIVE_MS)
    assert not step.returned.is_set(), "the step returned before the GUI timer fired"


# =============================================================================
# C-3: BakeController
# =============================================================================


class Recorder(QObject):
    """A GUI-thread receiver for the controller's three signals."""

    def __init__(self) -> None:
        super().__init__()
        self.log: list[tuple[str, object, bool]] = []

    def _add(self, kind: str, value: object) -> None:
        self.log.append((kind, value, threading.current_thread() is threading.main_thread()))

    @Slot(object)
    def on_previewed(self, value: object) -> None:
        self._add("previewed", value)

    @Slot(object)
    def on_baked(self, value: object) -> None:
        self._add("baked", value)

    @Slot(str)
    def on_failed(self, value: str) -> None:
        self._add("failed", value)


@pytest.fixture
def chapter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Path, Step, Step]]:
    source_dir = _source(tmp_path, 2)
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)):
        pass
    preview = Step(_default_preview(source_dir))
    bake = Step(_report(2))
    monkeypatch.setattr(bake_ui, "preview_bake", preview)
    monkeypatch.setattr(bake_ui, "bake_chapter", bake)
    yield source_dir, preview, bake
    for step in (preview, bake):
        step.release.set()


def _controller(qtbot, source_dir: Path) -> tuple[BakeController, Recorder]:  # type: ignore[no-untyped-def]
    controller = BakeController(project_dir_for(source_dir))
    recorder = Recorder()
    controller.previewed.connect(recorder.on_previewed)
    controller.baked.connect(recorder.on_baked)
    controller.failed.connect(recorder.on_failed)
    return controller, recorder


def test_preview_returns_at_once_and_the_preview_arrives_on_the_gui_thread(
    qtbot,  # type: ignore[no-untyped-def]
    chapter: tuple[Path, Step, Step],
) -> None:
    source_dir, preview, _ = chapter
    preview.block = True
    controller, recorder = _controller(qtbot, source_dir)

    controller.preview()
    returned_while_blocked = not preview.returned.is_set()
    qtbot.waitUntil(preview.entered.is_set, timeout=WAIT_MS)
    running = controller.is_running()
    preview.release.set()
    qtbot.waitUntil(lambda: bool(recorder.log), timeout=WAIT_MS)
    controller.wait()

    assert returned_while_blocked, "preview() waited for the step instead of returning at once"
    assert running, "is_running() is False while the preview step is blocked"
    assert not controller.is_running()
    assert preview.threads[0] is not threading.main_thread()
    assert recorder.log == [("previewed", _default_preview(source_dir), True)]


def test_bake_runs_on_a_worker_and_writes_to_the_sibling_en_folder(
    qtbot,  # type: ignore[no-untyped-def]
    chapter: tuple[Path, Step, Step],
) -> None:
    source_dir, _, bake = chapter
    controller, recorder = _controller(qtbot, source_dir)

    controller.bake()
    qtbot.waitUntil(lambda: bool(recorder.log), timeout=WAIT_MS)
    controller.wait()

    assert recorder.log == [("baked", _report(2), True)]
    assert bake.threads[0] is not threading.main_thread()
    assert len(bake.args) == 1
    _project, output_dir = bake.args[0]
    assert output_dir == _en(source_dir)
    assert bake.source_dirs == [source_dir]


def test_each_step_opens_its_own_project_on_its_worker(
    qtbot,  # type: ignore[no-untyped-def]
    chapter: tuple[Path, Step, Step],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_dir, preview, bake = chapter
    opened: list[tuple[Path, bool]] = []

    def recording_open(project_dir: Path) -> Project:
        opened.append((project_dir, threading.current_thread() is threading.main_thread()))
        return open_project(project_dir)

    monkeypatch.setattr(bake_ui, "open_project", recording_open)
    controller, recorder = _controller(qtbot, source_dir)

    controller.preview()
    qtbot.waitUntil(lambda: len(recorder.log) == 1, timeout=WAIT_MS)
    controller.wait()
    controller.bake()
    qtbot.waitUntil(lambda: len(recorder.log) == 2, timeout=WAIT_MS)
    controller.wait()

    assert opened == [(project_dir_for(source_dir), False), (project_dir_for(source_dir), False)]
    assert preview.source_dirs == [source_dir]
    assert bake.source_dirs == [source_dir]


@pytest.mark.parametrize("which", ["preview", "bake"])
def test_an_exception_from_either_step_arrives_as_failed_with_its_message(
    qtbot,  # type: ignore[no-untyped-def]
    chapter: tuple[Path, Step, Step],
    which: str,
) -> None:
    source_dir, preview, bake = chapter
    step = preview if which == "preview" else bake
    step.result = OSError("the disk is full")
    controller, recorder = _controller(qtbot, source_dir)

    getattr(controller, which)()
    qtbot.waitUntil(lambda: bool(recorder.log), timeout=WAIT_MS)
    controller.wait()

    assert recorder.log == [("failed", "the disk is full", True)]


def test_wait_without_a_step_is_a_no_op_and_nothing_is_running(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    controller = BakeController(tmp_path / "never.mtproj")

    controller.wait()

    assert not controller.is_running()


# =============================================================================
# C-4: the Render command at rest
# =============================================================================


def test_render_pages_is_a_primary_enter_activated_button_at_the_right_end_of_the_footer(
    rig: Rig,
) -> None:
    window = rig.window
    button = window.render_button

    assert isinstance(button, ActivatedByEnter)
    assert button.objectName() == "renderButton"
    assert button.property("variant") == "primary"
    assert window.footer.isAncestorOf(button)
    assert _at_rest(window)
    others = [
        w
        for w in window.footer.findChildren(
            QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly
        )
        if w is not button and w.isVisible()
    ]
    right = button.geometry().right()
    assert all(w.geometry().right() < right for w in others), (
        f"something in the footer sits right of Render pages: {others!r}"
    )


def test_the_render_status_is_an_empty_selectable_plain_text_label_in_the_footer(
    rig: Rig,
) -> None:
    status = rig.window.render_status

    assert isinstance(status, QLabel)
    assert rig.window.footer.isAncestorOf(status)
    assert status.text() == ""
    assert status.textFormat() == Qt.TextFormat.PlainText
    assert status.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse


def test_render_before_a_chapter_is_loaded_does_nothing(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    preview = Step(_default_preview(tmp_path / "x"))
    monkeypatch.setattr(bake_ui, "preview_bake", preview)
    window = Workspace()
    _show(qtbot, window)

    window.render()
    window.render_button.click()
    _settle()

    assert preview.calls == 0
    assert getattr(window, "bake_dialog", None) is None
    assert _at_rest(window)


# =============================================================================
# AC-1: Render opens the dialog built from the worker's preview
# =============================================================================


def test_render_opens_the_dialog_built_from_the_preview_of_this_chapter(
    qtbot,  # type: ignore[no-untyped-def]
    rig: Rig,
) -> None:
    rig.window.render_button.click()
    dialog = _dialog(qtbot, rig.window)

    assert dialog.parent() is rig.window
    assert dialog.isModal()
    assert rig.preview.source_dirs == [rig.source_dir]
    out = dialog.findChild(QLabel, "bakeOutputFolder")
    unreviewed = dialog.findChild(QLabel, "bakeUnreviewed")
    assert out is not None and out.text() == str(rig.output_dir)
    assert unreviewed is not None
    assert unreviewed.text() == "1 of 3 lines was never reviewed (page 2). Render anyway?"
    assert dialog.confirm_button.text() == "Render 2 pages"
    assert _at_rest(rig.window), "the button stays loading after the dialog opened"


# =============================================================================
# AC-4: both steps run off the GUI thread, and the window stays responsive
# =============================================================================


def test_while_the_counts_are_computed_the_gui_runs_and_render_pages_is_loading(
    qtbot,  # type: ignore[no-untyped-def]
    rig: Rig,
) -> None:
    window = rig.window
    rig.preview.block = True
    _focus_render(qtbot, window)
    rest_width = window.render_button.width()

    window.render_button.click()
    qtbot.waitUntil(rig.preview.entered.is_set, timeout=WAIT_MS)

    assert rig.preview.threads[0] is not threading.main_thread(), (
        "(a) preview ran on the GUI thread"
    )
    _responsive(qtbot, rig.preview)  # (b)
    _assert_loading(window, rest_width)  # (c)
    assert QApplication.focusWidget() is window.render_button, "the loading button lost focus"

    window.render_button.click()
    QTest.keyClick(window.render_button, Qt.Key.Key_Return)
    _settle()
    assert rig.preview.calls == 1, "a click while loading started a second preview"
    assert getattr(window, "bake_dialog", None) is None

    rig.preview.release.set()
    _dialog(qtbot, window)
    assert rig.preview.opened is True, "the preview step gave up instead of being released"
    assert _at_rest(window)


def test_while_the_chapter_renders_the_gui_runs_and_render_pages_is_loading(
    qtbot,  # type: ignore[no-untyped-def]
    rig: Rig,
) -> None:
    window = rig.window
    rig.bake.block = True
    rest_width = window.render_button.width()
    window.render_button.click()
    dialog = _confirm_dialog(qtbot, window)
    qtbot.waitUntil(rig.bake.entered.is_set, timeout=WAIT_MS)

    assert rig.bake.threads[0] is not threading.main_thread(), "(a) the bake ran on the GUI thread"
    _responsive(qtbot, rig.bake)  # (b)
    _assert_loading(window, rest_width)  # (c)

    window.render_button.click()
    _settle()
    assert rig.preview.calls == 1, "a click while rendering started another preview"
    assert rig.bake.calls == 1, "a click while rendering started another bake"
    assert window.bake_dialog is dialog and not dialog.isVisible()

    rig.bake.release.set()
    qtbot.waitUntil(lambda: _at_rest(window), timeout=WAIT_MS)
    assert rig.bake.opened is True, "the bake step gave up instead of being released"


@pytest.mark.parametrize(
    ("pages", "sentence"),
    [(2, "Rendered 2 pages to {out}."), (1, "Rendered 1 page to {out}.")],
    ids=["plural", "singular"],
)
def test_a_finished_render_states_and_announces_the_page_count_and_the_folder(
    qtbot,  # type: ignore[no-untyped-def]
    rig: Rig,
    pages: int,
    sentence: str,
) -> None:
    rig.bake.result = _report(pages)
    expected = sentence.format(out=rig.output_dir)

    rig.window.render_button.click()
    _confirm_dialog(qtbot, rig.window)
    qtbot.waitUntil(lambda: rig.window.render_status.text() != "", timeout=WAIT_MS)

    assert rig.window.render_status.text() == expected
    assert rig.window.live_region.text() == expected
    assert rig.window.live_region.accessibleName() == expected
    assert _at_rest(rig.window)
    assert rig.bake.args[0][1] == rig.output_dir


@pytest.mark.parametrize("which", ["preview", "bake"])
def test_a_failed_render_says_why_and_render_pages_can_be_used_again(
    qtbot,  # type: ignore[no-untyped-def]
    rig: Rig,
    which: str,
) -> None:
    step = rig.preview if which == "preview" else rig.bake
    step.result = OSError("the disk is full")
    expected = "Render failed: the disk is full"

    rig.window.render_button.click()
    if which == "bake":
        _confirm_dialog(qtbot, rig.window)
    qtbot.waitUntil(lambda: rig.window.render_status.text() != "", timeout=WAIT_MS)

    assert rig.window.render_status.text() == expected
    assert rig.window.live_region.text() == expected
    assert _at_rest(rig.window)

    step.result = _report(2) if which == "bake" else _default_preview(rig.source_dir)
    previews = rig.preview.calls
    rig.window.render_button.click()
    _dialog(qtbot, rig.window)
    assert rig.preview.calls == previews + 1, "Render did nothing after a failure"


# =============================================================================
# AC-2 in the workspace, and Cancel / Esc
# =============================================================================


def test_with_unreviewed_lines_confirming_starts_the_render(qtbot, rig: Rig) -> None:  # type: ignore[no-untyped-def]
    rig.window.render_button.click()
    dialog = _dialog(qtbot, rig.window)

    assert dialog.confirm_button.isVisible()
    assert dialog.confirm_button.isEnabled()
    assert dialog.confirm_button.isDefault()
    QTest.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: rig.bake.calls == 1, timeout=WAIT_MS)


@pytest.mark.parametrize("how", ["cancel", "escape"])
def test_dismissing_the_dialog_renders_nothing_and_returns_render_pages_to_rest(
    qtbot,  # type: ignore[no-untyped-def]
    rig: Rig,
    how: str,
) -> None:
    rig.window.render_button.click()
    dialog = _dialog(qtbot, rig.window)
    _dismiss(qtbot, dialog, how)
    _settle()

    assert rig.bake.calls == 0
    assert _at_rest(rig.window)
    assert rig.window.render_status.text() == ""
    assert not rig.output_dir.exists()


def _dismiss(qtbot, dialog: BakeConfirmDialog, how: str) -> None:  # type: ignore[no-untyped-def]
    with qtbot.waitSignal(dialog.finished, timeout=FOCUS_MS):
        if how == "confirm":
            QTest.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)
        elif how == "cancel":
            QTest.mouseClick(dialog.cancel_button, Qt.MouseButton.LeftButton)
        else:
            qtbot.waitUntil(
                lambda: QApplication.focusWidget() is dialog.confirm_button, timeout=FOCUS_MS
            )
            QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Escape)


# =============================================================================
# AC-3 in the workspace: focus stays in the dialog, then returns to Render pages
# =============================================================================


def test_tabbing_in_the_open_dialog_never_reaches_the_workspace_behind_it(
    qtbot,  # type: ignore[no-untyped-def]
    rig: Rig,
) -> None:
    rig.preview.result = BakePreview(
        output_dir=rig.output_dir,
        page_count=2,
        total_lines=3,
        unreviewed=(LineRef(page_ordinal=0, reading_index=0),),
        failed=(LineRef(page_ordinal=0, reading_index=1),),
        overflowing=(LineRef(page_ordinal=1, reading_index=0),),
    )
    _focus_render(qtbot, rig.window)
    rig.window.render_button.click()
    dialog = _dialog(qtbot, rig.window)
    qtbot.waitUntil(lambda: QApplication.focusWidget() is dialog.confirm_button, timeout=FOCUS_MS)
    focusable = [
        w
        for w in dialog.findChildren(QWidget)
        if w.focusPolicy() & Qt.FocusPolicy.TabFocus and w.isVisibleTo(dialog)
    ]

    presses = len(focusable) + 3
    outside = []
    for key in [Qt.Key.Key_Tab] * presses + [Qt.Key.Key_Backtab] * presses:
        QTest.keyClick(QApplication.focusWidget(), key)
        _settle()
        focused = QApplication.focusWidget()
        if focused is None or not dialog.isAncestorOf(focused):
            outside.append(focused)

    assert outside == [], f"focus left the open dialog for {outside!r}"


@pytest.mark.parametrize("how", ["confirm", "cancel", "escape"])
def test_however_the_dialog_closes_focus_returns_to_render_pages(
    qtbot,  # type: ignore[no-untyped-def]
    rig: Rig,
    how: str,
) -> None:
    rig.bake.block = True  # so "after confirm" is observed while the render runs
    _focus_render(qtbot, rig.window)
    rig.window.render_button.click()
    dialog = _dialog(qtbot, rig.window)
    qtbot.waitUntil(lambda: QApplication.focusWidget() is dialog.confirm_button, timeout=FOCUS_MS)

    _dismiss(qtbot, dialog, how)

    qtbot.waitUntil(
        lambda: QApplication.focusWidget() is rig.window.render_button, timeout=FOCUS_MS
    )
    rig.bake.release.set()
    qtbot.waitUntil(lambda: _at_rest(rig.window), timeout=WAIT_MS)
    assert QApplication.focusWidget() is rig.window.render_button


# =============================================================================
# C-4: closing the window waits for a render in flight
# =============================================================================


def test_closing_the_window_waits_for_a_render_in_flight_before_closed(
    qtbot,  # type: ignore[no-untyped-def]
    rig: Rig,
) -> None:
    rig.bake.block = True
    rig.bake.linger_s = LINGER_S
    rig.window.render_button.click()
    _confirm_dialog(qtbot, rig.window)
    qtbot.waitUntil(rig.bake.entered.is_set, timeout=WAIT_MS)
    seen_at_closed: list[bool] = []
    rig.window.closed.connect(lambda: seen_at_closed.append(rig.bake.returned.is_set()))
    releaser = threading.Timer(0.05, rig.bake.release.set)

    releaser.start()
    rig.window.close()
    releaser.join()

    assert seen_at_closed == [True], (
        "closed was emitted while the render was still running"
        if seen_at_closed
        else "closed was never emitted"
    )
    assert rig.bake.opened is True


# =============================================================================
# C-4 step 1: an edit typed and not yet saved is counted (real preview_bake)
# =============================================================================


@pytest.fixture
def lines_chapter(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[Workspace, list[BakePreview], Step]]:
    """One uncleaned page with two proposed lines, open in a shown Workspace;
    `preview_bake` is the real one, wrapped to record what it returned."""
    # Only render()'s flush may write the edit: the save timer never fires here.
    monkeypatch.setattr(line_editor_module, "SAVE_DEBOUNCE_MS", 60_000)
    source_dir = _source(tmp_path, 1)
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        project.write_regions(
            0,
            [
                RawRegion(
                    polygon=_ring(4, 4 + 36 * i, 56, 36 + 36 * i),
                    mask=_png(PAGE_SIZE, bits=True),
                    confidence=0.9,
                    kind="bubble",
                )
                for i in range(2)
            ],
        )
        project.write_lines(0, [OcrResult("テキスト"), OcrResult("ことば")])
        project.write_proposed(0, {0: "Hello.", 1: "There."})
    results: list[BakePreview] = []

    def recording_preview(project: Project) -> BakePreview:
        result = real_preview_bake(project)
        results.append(result)
        return result

    monkeypatch.setattr(bake_ui, "preview_bake", recording_preview)
    bake = Step(_report(1))
    monkeypatch.setattr(bake_ui, "bake_chapter", bake)
    opened = open_project(project_dir_for(source_dir))
    window = Workspace()
    _show(qtbot, window)
    window.load_chapter(opened)
    window.page_strip.setCurrentRow(0)
    _settle()
    try:
        yield window, results, bake
    finally:
        _teardown(qtbot, [bake], window)
        opened.__exit__(None, None, None)


def test_an_edit_typed_and_not_yet_saved_is_counted_as_reviewed(
    qtbot,  # type: ignore[no-untyped-def]
    lines_chapter: tuple[Workspace, list[BakePreview], Step],
) -> None:
    window, results, _ = lines_chapter
    editor = window.translation_column.row(0).editor
    editor.setFocus(Qt.FocusReason.OtherFocusReason)
    qtbot.waitUntil(editor.hasFocus, timeout=FOCUS_MS)
    editor.selectAll()
    QTest.keyClicks(editor, "Mine")
    _settle()

    window.render()
    dialog = _dialog(qtbot, window)

    assert [r.unreviewed for r in results] == [(LineRef(page_ordinal=0, reading_index=1),)], (
        "the typed edit was not saved before the counts were taken"
    )
    unreviewed = dialog.findChild(QLabel, "bakeUnreviewed")
    assert unreviewed is not None
    assert unreviewed.text() == "1 of 2 lines was never reviewed (page 1). Render anyway?"
