"""MT-057: a chosen folder of pages shows its chapter summary.

`ChapterSummary` (new, `mangatl.ui.summary`, C-5) replaces the drop target as
`MainWindow`'s central widget when `mangatl.app.open_folder` returns a
`Chapter` (C-2): from the chooser, from `mangatl <folder>` (C-3, the intake
window rather than MT-054's notice window) and - since MT-056 shares the
hand-over - from a drop (`test_folder_drop.py`). The intake *errors* (AC-2, AC-3,
AC-6) are in `test_intake_errors.py`, which imports nothing this story adds.

Oracle partition (story `## Contract`):

- **Settled - spelled out here, never imported:** every summary string
  (`components.md` §2 as amended 2026-09-30, repeated in the story's
  `## Design notes`), the notice's three lines, `Choose a different folder`,
  `Chapter summary`, and AC-2's headline for the summary-to-error path.
- **Oracle-free, control demanded (AC-4):** the notice exists iff
  `sorted(names) != order_filenames(names)`. Controls: `p1 … p9` has no notice
  child at all; `001 … 012` has none; `p1 … p12` has one, with both full lists
  spelled out below (not computed with `sorted`). Expected values are recorded
  in the story's `## Handoff`.
- **Mechanical:** AC-1's fields on a folder whose natural order differs from
  both lexical and directory-listing order (C-8: `page 9, page 10, page 11`
  lists and sorts as `page 10, page 11, page 9` on NTFS), so a summary built
  from `iterdir()` or `sorted()` shows the wrong first AND last page; the
  object names and absences of C-5 (absent = `findChild(...) is None`); focus
  and `choose_other` per C-4; AC-5's tree hash (C-6).

The current view is always `window.centralWidget()` (C-4), never `findChild`:
a replaced widget may linger until deferred deletion.

Widget-level tests build a `Chapter` directly: `ChapterSummary(chapter)` reads
nothing from disk, so a filename holding `<b>` - which Windows cannot create -
can still be shown, and a drive root can be the source folder.

**RED:** this file fails at import (`mangatl.ui.summary` does not exist), so no
assertion here has run; see the story's handoff for each control's expected
value. **Timing:** no real-time waits, only exposure, activation and focus.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QSize, Qt
from PySide6.QtGui import QAccessible, QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QFrame,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QWidget,
)

from mangatl import app as app_module
from mangatl.domain.page import Chapter, Page
from mangatl.store.project import create_project
from mangatl.ui import tokens_gen
from mangatl.ui.intake import FolderDropTarget
from mangatl.ui.main_window import MainWindow
from mangatl.ui.summary import ChapterSummary
from mangatl.ui.workspace import Workspace

# --- Settled strings, spelled out (never read back from the module under test) ------
SCROLL_NAME = "Chapter summary"
CHOOSE = "Choose a different folder"
LEAD = "These filenames sort differently as numbers and as text. The run uses natural order."
AFFORDANCE_ERROR = "Choose a different folder"


def _no_pages(folder: Path) -> str:
    """AC-2's headline; `folder` is the resolved path, whole."""
    return f"No page images in {folder}. This tool reads .png and .jpg files."


#: 41 distinct characters; its first 39 / 40 / 41 are the heading boundaries.
LONG = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNO"
#: LONG cut per the design: its first 20, U+2026, its last 19 (40 characters).
LONG_CUT = "abcdefghijklmnopqrst\u2026wxyzABCDEFGHIJKLMNO"
assert (len(LONG), len(LONG_CUT)) == (41, 40)
assert LONG[:20] + "\u2026" + LONG[-19:] == LONG_CUT

# --- AC-1's folder (C-8) ---------------------------------------------------------------
AC1_NAME = "Vol 1 & 2"
#: Written in this order; NTFS lists them lexically: page 10, page 11, page 9.
AC1_PAGES = ("page 10.png", "page 11.png", "page 9.png")
AC1_FIRST = "page 9.png"  # natural order; lexical/listing first is "page 10.png"
AC1_LAST = "page 11.png"  # natural order; lexical/listing last is "page 9.png"
AC1_NATURAL = "Natural order (used): page 9.png, page 10.png, page 11.png"
AC1_LEXICAL = "Text order (not used): page 10.png, page 11.png, page 9.png"

# --- AC-4's controls, spelled out ------------------------------------------------------
P1_TO_P9 = tuple(f"p{i}.png" for i in range(1, 10))
P1_TO_P12 = tuple(f"p{i}.png" for i in range(1, 13))
PADDED = tuple(f"{i:03d}.png" for i in range(1, 13))
P12_NATURAL = (
    "Natural order (used): p1.png, p2.png, p3.png, p4.png, p5.png, p6.png, p7.png,"
    " p8.png, p9.png, p10.png, p11.png, p12.png"
)
P12_LEXICAL = (
    "Text order (not used): p1.png, p10.png, p11.png, p12.png, p2.png, p3.png, p4.png,"
    " p5.png, p6.png, p7.png, p8.png, p9.png"
)


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


def _png(size: QSize) -> bytes:
    image = QImage(size, QImage.Format.Format_RGB32)
    image.fill(QColor(tokens_gen.TOKENS["color.surface.raised"]))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    buffer.close()
    return bytes(data.data())


@pytest.fixture(scope="module")
def page_png() -> bytes:
    """Real PNG bytes (C-8); small, since only the header and a decode matter."""
    return _png(QSize(60, 80))


def _pages_folder(root: Path, name: str, pages: tuple[str, ...], png: bytes) -> Path:
    folder = root / name
    folder.mkdir()
    for page in pages:
        (folder / page).write_bytes(png)
    return folder


@pytest.fixture
def ac1_folder(tmp_path: Path, page_png: bytes) -> Path:
    """Three pages whose natural order differs from lexical and listing order,
    plus a file that is not a page."""
    folder = _pages_folder(tmp_path, AC1_NAME, AC1_PAGES, page_png)
    (folder / "notes.txt").write_text("not a page", encoding="utf-8")
    listed = [p.name for p in folder.iterdir() if p.suffix == ".png"]
    assert listed[0] != AC1_FIRST and listed[-1] != AC1_LAST, (
        f"precondition (C-8): listing order {listed} agrees with natural order"
    )
    return folder


@pytest.fixture
def no_pages(tmp_path: Path) -> Path:
    """AC-2: files, none of them a page."""
    folder = tmp_path / "Empty & more"
    folder.mkdir()
    (folder / "readme.txt").write_text("x", encoding="utf-8")
    return folder


@pytest.fixture
def source(tmp_path: Path, page_png: bytes) -> Path:
    """A chapter folder whose sibling `.mtproj` project exists, CLOSED."""
    names = ("b-first.png", "a-second.png")
    folder = _pages_folder(tmp_path, "my chapter", names, page_png)
    chapter = Chapter(
        source_dir=folder,
        pages=tuple(
            Page(ordinal=i, filename=name, width=60, height=80, sha256=f"{i}" * 64)
            for i, name in enumerate(names)
        ),
    )
    with create_project(chapter, tmp_path / "my chapter.mtproj"):
        pass
    return folder


def _chapter(names: tuple[str, ...], folder: Path = Path("C:/manga/Chapter 12")) -> Chapter:
    """A `Chapter` as `read_chapter` would return it: `names` IN ORDER."""
    return Chapter(
        source_dir=folder,
        pages=tuple(
            Page(ordinal=i, filename=name, width=60, height=80, sha256=f"{i % 10}" * 64)
            for i, name in enumerate(names)
        ),
    )


def _hashes(root: Path) -> dict[str, str | None]:
    """C-6: every path under `root`, with the SHA-256 of every file."""
    return {
        str(p.relative_to(root)): (
            hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
        )
        for p in sorted(root.rglob("*"))
    }


def _assert_wrote_nothing(root: Path, folder: Path, before: dict[str, str | None]) -> None:
    assert any(v is not None for v in before.values()), "precondition: nothing to hash"
    assert _hashes(root) == before, "showing the folder created, modified or deleted something"
    project = folder.with_name(folder.name + ".mtproj")
    assert not project.exists(), f"{project.name} was created"


# --- Recorders ------------------------------------------------------------------------


class Chooser:
    """A `FolderChooser` returning the queued answers in order (then `None`),
    recording the parent of every call."""

    def __init__(self, *answers: Path | None) -> None:
        self.answers = list(answers)
        self.parents: list[QWidget] = []

    def __call__(self, parent: QWidget) -> Path | None:
        self.parents.append(parent)
        return self.answers.pop(0) if self.answers else None


class FocusTakingChooser(Chooser):
    """A chooser that takes focus while it is open, as a modal dialog does, and
    leaves nothing focused behind it. Without this, a click on the button has
    already focused it, and "focus back on the button" holds for free
    (measured in RED against a scratch candidate that never refocuses)."""

    def __call__(self, parent: QWidget) -> Path | None:
        focused = QApplication.focusWidget()
        if focused is not None:
            focused.clearFocus()
        return super().__call__(parent)


class Opener:
    """A `FolderOpener` that records every path and delegates to the real
    `mangatl.app.open_folder`."""

    def __init__(self) -> None:
        self.calls: list[Path] = []

    def __call__(self, folder: Path) -> QMainWindow | Chapter | str:
        self.calls.append(folder)
        return app_module.open_folder(folder)


@pytest.fixture
def windows(qtbot) -> Iterator[list[QMainWindow]]:  # type: ignore[no-untyped-def]
    """Every window made here, and every window it handed over to, closed at
    teardown - an open `Workspace` holds its project file on Windows."""
    made: list[QMainWindow] = []
    yield made
    for window in made:
        opened = getattr(window, "opened", None)
        if isinstance(opened, QMainWindow):
            opened.close()
        window.close()


def _show(qtbot, windows: list[QMainWindow], window: QMainWindow) -> None:  # type: ignore[no-untyped-def]
    qtbot.addWidget(window)
    windows.append(window)
    window.resize(900, 600)
    with qtbot.waitExposed(window):
        window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    _settle()


def _intake(
    qtbot,  # type: ignore[no-untyped-def]
    windows: list[QMainWindow],
    chooser: Chooser,
    opener: Callable[[Path], QMainWindow | Chapter | str] | None = None,
) -> MainWindow:
    window = MainWindow(open_folder=opener or Opener(), choose_folder=chooser)
    _show(qtbot, windows, window)
    return window


def _choose_from_target(window: QMainWindow) -> None:
    central = window.centralWidget()
    assert isinstance(central, FolderDropTarget), f"central widget is {type(central).__name__}"
    QTest.mouseClick(central, Qt.MouseButton.LeftButton)
    _settle()


def _summary(window: QMainWindow) -> ChapterSummary:
    central = window.centralWidget()
    assert isinstance(central, ChapterSummary), (
        f"central widget is {type(central).__name__}, not the ChapterSummary"
    )
    assert central.objectName() == "chapter-summary"
    return central


def _target(window: QMainWindow) -> FolderDropTarget:
    central = window.centralWidget()
    assert isinstance(central, FolderDropTarget), (
        f"central widget is {type(central).__name__}, not the FolderDropTarget"
    )
    return central


def _label(summary: QWidget, name: str) -> QLabel:
    label = summary.findChild(QLabel, name)
    assert label is not None, f"the summary has no QLabel named {name!r}"
    return label


def _scroll(summary: QWidget) -> QScrollArea:
    scroll = summary.findChild(QScrollArea, "summary-scroll")
    assert scroll is not None, "the summary has no QScrollArea named 'summary-scroll'"
    return scroll


def _choose_button(summary: QWidget) -> QPushButton:
    button = summary.findChild(QPushButton, "summary-choose")
    assert button is not None, "the summary has no QPushButton named 'summary-choose'"
    return button


def _absent(summary: QWidget, name: str) -> None:
    assert summary.findChild(QWidget, name) is None, f"{name!r} exists (absent means not created)"


def _fields(summary: QWidget) -> tuple[str, str, str, str]:
    return (
        _label(summary, "summary-name").text(),
        _label(summary, "summary-count").text(),
        _label(summary, "summary-first").text(),
        _label(summary, "summary-last").text(),
    )


AC1_FIELDS = (AC1_NAME, "3 pages", f"First page: {AC1_FIRST}", f"Last page: {AC1_LAST}")


def _bare(qtbot, chapter: Chapter) -> ChapterSummary:  # type: ignore[no-untyped-def]
    summary = ChapterSummary(chapter)
    qtbot.addWidget(summary)
    return summary


# =============================================================================
# AC-1: a chosen folder of pages shows its name, count, first and last page
# =============================================================================


def test_a_chosen_folder_of_pages_shows_its_name_count_and_first_and_last_page_in_natural_order(
    qtbot,  # type: ignore[no-untyped-def]
    windows,
    ac1_folder: Path,
) -> None:
    opener = Opener()
    window = _intake(qtbot, windows, Chooser(ac1_folder), opener)

    _choose_from_target(window)

    assert opener.calls == [ac1_folder]
    assert window.opened is None, f"a folder of pages opened {type(window.opened).__name__}"
    assert window.isVisible(), "the intake window closed on a folder of pages"
    assert _fields(_summary(window)) == AC1_FIELDS


def test_mangatl_folder_builds_the_intake_window_showing_the_summary_not_a_notice(
    qtbot,  # type: ignore[no-untyped-def]
    ac1_folder: Path,
) -> None:
    """C-3: `MainWindow(open_folder=open_folder)` with `show_summary` called;
    returned NOT shown."""
    window = app_module.build_window([str(ac1_folder)])
    qtbot.addWidget(window)

    assert type(window) is MainWindow, f"build_window returned a {type(window).__name__}"
    assert not window.isVisible(), "build_window showed its window"
    assert window.findChild(QObject, "notice") is None, "MT-054's notice window was built"
    assert window.open_folder is app_module.open_folder
    assert _fields(_summary(window)) == AC1_FIELDS


def test_a_relative_folder_argument_shows_the_summary_of_the_resolved_folder(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    ac1_folder: Path,
) -> None:
    monkeypatch.chdir(tmp_path)

    window = app_module.build_window([AC1_NAME])
    qtbot.addWidget(window)

    assert _fields(_summary(window)) == AC1_FIELDS


def test_open_folder_returns_the_chapter_in_natural_order_for_a_folder_of_pages(
    ac1_folder: Path,
) -> None:
    """C-2 step 3: `read_chapter`'s `Chapter`, not a notice string."""
    outcome = app_module.open_folder(ac1_folder)

    assert isinstance(outcome, Chapter), f"open_folder returned {outcome!r}"
    assert [p.filename for p in outcome.pages] == ["page 9.png", "page 10.png", "page 11.png"]
    assert outcome.source_dir == ac1_folder.resolve()


def test_the_summary_from_the_command_line_has_focus_on_its_scroll_area_once_shown(
    qtbot,  # type: ignore[no-untyped-def]
    windows,
    ac1_folder: Path,
) -> None:
    window = app_module.build_window([str(ac1_folder)])
    _show(qtbot, windows, window)

    scroll = _scroll(_summary(window))
    assert scroll.hasFocus(), f"focus is on {QApplication.focusWidget()!r}, not summary-scroll"


def test_showing_a_summary_writes_nothing_either_way_it_was_chosen(
    qtbot,  # type: ignore[no-untyped-def]
    windows,
    tmp_path: Path,
    ac1_folder: Path,
) -> None:
    """AC-5 / C-6 for the summary: chooser path, then command-line path."""
    before = _hashes(tmp_path)
    window = _intake(qtbot, windows, Chooser(ac1_folder))
    _choose_from_target(window)
    _summary(window)
    _assert_wrote_nothing(tmp_path, ac1_folder, before)

    cli = app_module.build_window([str(ac1_folder)])
    qtbot.addWidget(cli)
    _summary(cli)
    _assert_wrote_nothing(tmp_path, ac1_folder, before)


# =============================================================================
# AC-4: the order notice, iff the two orders differ (controls p1..p9, p1..p12)
# =============================================================================


def test_p1_to_p9_sort_the_same_both_ways_so_no_order_notice_is_created(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Negative control: expected NO `summary-order-notice` child at all."""
    summary = _bare(qtbot, _chapter(P1_TO_P9))

    for name in ("summary-order-notice", "order-lead", "order-natural", "order-lexical"):
        _absent(summary, name)
    assert _label(summary, "summary-count").text() == "9 pages"


def test_zero_padded_names_sort_the_same_both_ways_so_no_order_notice_is_created(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Negative control: `001 … 012` - digits, but padded, so the orders agree."""
    summary = _bare(qtbot, _chapter(PADDED))

    _absent(summary, "summary-order-notice")


def test_p1_to_p12_show_the_order_notice_listing_both_full_orders(qtbot) -> None:  # type: ignore[no-untyped-def]
    summary = _bare(qtbot, _chapter(P1_TO_P12))

    notice = summary.findChild(QFrame, "summary-order-notice")
    assert notice is not None, "no order notice for p1 … p12, whose two orders differ"
    lines = tuple(
        _label(notice, name).text() for name in ("order-lead", "order-natural", "order-lexical")
    )
    assert lines == (LEAD, P12_NATURAL, P12_LEXICAL)


def test_the_order_notice_is_named_by_its_three_lines(qtbot) -> None:  # type: ignore[no-untyped-def]
    summary = _bare(qtbot, _chapter(P1_TO_P12))

    notice = summary.findChild(QFrame, "summary-order-notice")
    assert notice is not None
    assert notice.accessibleName() == f"{LEAD}\n{P12_NATURAL}\n{P12_LEXICAL}"


def test_the_order_notice_lists_every_filename_of_a_long_chapter_never_elided(qtbot) -> None:  # type: ignore[no-untyped-def]
    names = tuple(f"p{i}.png" for i in range(1, 201))
    summary = _bare(qtbot, _chapter(names))

    notice = summary.findChild(QFrame, "summary-order-notice")
    assert notice is not None
    natural = _label(notice, "order-natural").text()
    lexical = _label(notice, "order-lexical").text()
    assert natural == "Natural order (used): " + ", ".join(names)
    prefix = "Text order (not used): "
    assert lexical.startswith(prefix)
    listed = lexical[len(prefix) :].split(", ")
    assert len(listed) == 200 and set(listed) == set(names), "the text order is not complete"
    assert listed[:4] == ["p1.png", "p10.png", "p100.png", "p101.png"]


def test_a_chosen_folder_of_p1_to_p12_shows_the_notice_and_offers_no_order_control(
    qtbot,  # type: ignore[no-untyped-def]
    windows,
    tmp_path: Path,
    page_png: bytes,
) -> None:
    """AC-4 end to end: the order comes from `read_chapter`, and there is no
    control to change it (PO-5) - the only button is the way out."""
    folder = _pages_folder(tmp_path, "twelve", P1_TO_P12, page_png)
    window = _intake(qtbot, windows, Chooser(folder))

    _choose_from_target(window)

    summary = _summary(window)
    notice = summary.findChild(QFrame, "summary-order-notice")
    assert notice is not None, "no order notice for a folder of p1 … p12"
    assert _label(notice, "order-natural").text() == P12_NATURAL
    assert _label(notice, "order-lexical").text() == P12_LEXICAL
    assert notice.findChildren(QAbstractButton) == [], "the notice has a control"
    # MT-059 C-2/D-1: the summary's buttons are Start and the way out, compared
    # as a set - construction order is not a design fact.
    assert {b.objectName() for b in summary.findChildren(QAbstractButton)} == {
        "summary-start",
        "summary-choose",
    }


# =============================================================================
# C-5: the parts, their names, their absences
# =============================================================================


def test_one_page_says_1_page_and_only_page_with_no_first_or_last_line(qtbot) -> None:  # type: ignore[no-untyped-def]
    summary = _bare(qtbot, _chapter(("cover.png",)))

    assert _label(summary, "summary-count").text() == "1 page"
    assert _label(summary, "summary-only").text() == "Only page: cover.png"
    _absent(summary, "summary-first")
    _absent(summary, "summary-last")
    _absent(summary, "summary-order-notice")


def test_two_pages_say_2_pages_with_a_first_and_last_line_and_no_only_line(qtbot) -> None:  # type: ignore[no-untyped-def]
    summary = _bare(qtbot, _chapter(("p1.png", "p2.png")))

    assert _label(summary, "summary-count").text() == "2 pages"
    assert _label(summary, "summary-first").text() == "First page: p1.png"
    assert _label(summary, "summary-last").text() == "Last page: p2.png"
    _absent(summary, "summary-only")


@pytest.mark.parametrize(
    ("length", "shown"),
    [(39, LONG[:39]), (40, LONG[:40]), (41, LONG_CUT)],
    ids=["39-whole", "40-whole", "41-cut"],
)
def test_the_heading_is_cut_in_the_middle_only_above_forty_characters_and_named_uncut(
    qtbot,  # type: ignore[no-untyped-def]
    length: int,
    shown: str,
) -> None:
    summary = _bare(qtbot, _chapter(("p1.png",), Path("C:/manga") / LONG[:length]))

    heading = _label(summary, "summary-name")
    assert heading.text() == shown
    assert heading.accessibleName() == LONG[:length]


def test_a_drive_root_is_headed_by_its_path(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    root = Path(tmp_path.anchor)
    assert root.name == "", f"precondition: {root!r} has a base name"

    summary = _bare(qtbot, _chapter(("p1.png",), root))

    assert _label(summary, "summary-name").text() == str(root)


def test_every_summary_label_is_plain_word_wrapped_mouse_selectable_and_never_a_focus_stop(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    """A folder or file named with markup shows literally (Design notes). The
    names are in natural order and differ from text order, so every part -
    the notice's three lines included - exists to be checked."""
    names = ("<b>p1</b>.png", "p2 &amp;.png", "p10.png")
    summary = _bare(qtbot, _chapter(names, Path("C:/manga/a<b>c")))

    labels = summary.findChildren(QLabel)
    expected = {
        "summary-name",
        "summary-count",
        "summary-first",
        "summary-last",
        "order-lead",
        "order-natural",
        "order-lexical",
    }
    missing = expected - {label.objectName() for label in labels}
    assert not missing, f"labels missing from the summary: {sorted(missing)}"
    for label in labels:
        name = label.objectName() or repr(label.text())
        assert label.textFormat() == Qt.TextFormat.PlainText, f"{name} is not plain text"
        assert label.wordWrap(), f"{name} does not word-wrap"
        assert label.textInteractionFlags() == Qt.TextInteractionFlag.TextSelectableByMouse, (
            f"{name} has interaction flags {label.textInteractionFlags()!r}"
        )
        assert label.focusPolicy() == Qt.FocusPolicy.NoFocus, f"{name} takes focus"
    assert _label(summary, "summary-name").text() == "a<b>c"
    assert _label(summary, "summary-first").text() == "First page: <b>p1</b>.png"
    assert _label(summary, "summary-last").text() == "Last page: p10.png"
    assert _label(summary, "order-natural").text() == (
        "Natural order (used): <b>p1</b>.png, p2 &amp;.png, p10.png"
    )


def test_the_scroll_area_is_named_chapter_summary_and_described_by_its_visible_lines(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    """Heading line uncut; MT-058's cost estimate after the page facts and
    before the notice; the notice as its three lines; not the button."""
    names = ("page 9.png", "page 10.png", "page 11.png")
    summary = _bare(qtbot, _chapter(names, Path("C:/manga") / LONG))

    interface = QAccessible.queryAccessibleInterface(_scroll(summary))
    assert interface is not None
    assert interface.text(QAccessible.Text.Name) == SCROLL_NAME
    assert interface.text(QAccessible.Text.Description) == "\n".join(
        (
            LONG,
            "3 pages",
            "First page: page 9.png",
            "Last page: page 11.png",
            "Estimated for 3 pages: $0.18.",
            "Budget $2.00.",
            LEAD,
            AC1_NATURAL,
            AC1_LEXICAL,
        )
    )


def test_a_one_page_summary_is_described_without_first_last_or_notice(qtbot) -> None:  # type: ignore[no-untyped-def]
    summary = _bare(qtbot, _chapter(("cover.png",), Path("C:/manga/One shot")))

    assert _scroll(summary).accessibleDescription() == (
        "One shot\n1 page\nOnly page: cover.png\nEstimated for 1 page: $0.06.\nBudget $2.00."
    )


def test_the_scroll_area_scrolls_vertically_only_and_holds_every_part_but_the_button(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    summary = _bare(qtbot, _chapter(P1_TO_P12))
    scroll = _scroll(summary)

    assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert scroll.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    tab = Qt.FocusPolicy.TabFocus.value
    assert scroll.focusPolicy().value & tab == tab, "the scroll area is not a focus stop"
    for name in ("summary-name", "summary-count", "summary-first", "summary-last"):
        assert scroll.isAncestorOf(_label(summary, name)), f"{name} is outside the scroll area"
    notice = summary.findChild(QFrame, "summary-order-notice")
    assert notice is not None and scroll.isAncestorOf(notice)
    button = _choose_button(summary)
    assert not scroll.isAncestorOf(button), "the button scrolls away with the content"
    assert summary.isAncestorOf(button)


def test_the_summary_has_two_buttons_start_run_and_choose_a_different_folder(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    """MT-059 C-2/D-1 rewrote this MT-057 test, which pinned "the only button,
    no start button": the summary now has exactly two, compared as a set."""
    summary = _bare(qtbot, _chapter(P1_TO_P12))

    button = _choose_button(summary)
    assert button.text() == CHOOSE
    start = summary.findChild(QPushButton, "summary-start")
    assert start is not None, "the summary has no QPushButton named 'summary-start'"
    assert start.text() == "Start run"
    buttons = summary.findChildren(QAbstractButton)
    assert len(buttons) == 2 and set(buttons) == {start, button}, (
        f"buttons: {[b.text() for b in buttons]}"
    )
    assert not isinstance(summary, QAbstractButton)


def test_the_summary_does_not_accept_drops(qtbot, windows, ac1_folder: Path) -> None:  # type: ignore[no-untyped-def]
    """PO-9: drops onto the summary are out of scope - not accepted."""
    assert not _bare(qtbot, _chapter(("p1.png",))).acceptDrops()

    window = _intake(qtbot, windows, Chooser(ac1_folder))
    _choose_from_target(window)

    assert not window.centralWidget().acceptDrops(), "the window's summary accepts drops"


@pytest.mark.parametrize(
    "how", ["click", "Return", "Enter", "Space"], ids=["click", "Return", "Enter", "Space"]
)
def test_the_summary_emits_choose_other_once_per_activation_of_its_button(
    qtbot,  # type: ignore[no-untyped-def]
    how: str,
) -> None:
    """A `QPushButton` outside a dialog ignores Return and Enter (measured,
    PySide6 offscreen): those two are not satisfied for free."""
    summary = _bare(qtbot, _chapter(("p1.png", "p2.png")))
    summary.resize(600, 400)
    with qtbot.waitExposed(summary):
        summary.show()
    summary.activateWindow()
    qtbot.waitUntil(summary.isActiveWindow)
    seen: list[int] = []
    summary.choose_other.connect(lambda: seen.append(1))
    button = _choose_button(summary)

    _activate_button(qtbot, button, how)

    assert seen == [1], f"{how} emitted choose_other {len(seen)} times"


def _activate_button(qtbot, button: QPushButton, how: str) -> None:  # type: ignore[no-untyped-def]
    if how == "click":
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    else:
        button.setFocus(Qt.FocusReason.OtherFocusReason)
        qtbot.waitUntil(button.hasFocus)
        key = {"Return": Qt.Key.Key_Return, "Enter": Qt.Key.Key_Enter, "Space": Qt.Key.Key_Space}
        QTest.keyClick(button, key[how])
    _settle()


# =============================================================================
# C-4: MainWindow shows the summary, and the way out of it
# =============================================================================


def test_show_summary_and_show_error_replace_the_central_widget(qtbot, windows) -> None:  # type: ignore[no-untyped-def]
    window = _intake(qtbot, windows, Chooser())

    window.show_summary(_chapter(("p1.png", "p2.png"), Path("C:/manga/Direct")))
    assert _label(_summary(window), "summary-name").text() == "Direct"

    window.show_error("A reason & <b>not markup</b>")
    target = _target(window)
    assert target.state == "error"
    headline = target.findChild(QLabel, "headline")
    assert headline is not None and headline.text() == "A reason & <b>not markup</b>"


def test_the_shown_summary_has_focus_on_its_scroll_area(qtbot, windows, ac1_folder: Path) -> None:  # type: ignore[no-untyped-def]
    window = _intake(qtbot, windows, Chooser(ac1_folder))

    _choose_from_target(window)

    scroll = _scroll(_summary(window))
    assert scroll.hasFocus(), f"focus is on {QApplication.focusWidget()!r}, not summary-scroll"


@pytest.mark.parametrize(
    "how", ["click", "Return", "Enter", "Space"], ids=["click", "Return", "Enter", "Space"]
)
def test_choose_a_different_folder_asks_the_chooser_once_with_the_window_as_parent(
    qtbot,  # type: ignore[no-untyped-def]
    windows,
    ac1_folder: Path,
    how: str,
) -> None:
    chooser = Chooser(ac1_folder, None)
    window = _intake(qtbot, windows, chooser)
    _choose_from_target(window)
    assert len(chooser.parents) == 1

    _activate_button(qtbot, _choose_button(_summary(window)), how)

    assert len(chooser.parents) == 2, f"{how} on the button asked {len(chooser.parents) - 1} times"
    assert chooser.parents[1] is window, "the chooser's parent is not the window"


@pytest.mark.parametrize("how", ["click", "Space"])
def test_dismissing_the_chooser_from_the_summary_keeps_it_and_returns_focus_to_the_button(
    qtbot,  # type: ignore[no-untyped-def]
    windows,
    tmp_path: Path,
    ac1_folder: Path,
    how: str,
) -> None:
    opener = Opener()
    window = _intake(qtbot, windows, FocusTakingChooser(ac1_folder, None), opener)
    _choose_from_target(window)
    summary = _summary(window)
    before = _hashes(tmp_path)

    _activate_button(qtbot, _choose_button(summary), how)

    assert window.centralWidget() is summary, "a dismissed chooser replaced the summary"
    assert opener.calls == [ac1_folder], "the dismissal reached open_folder"
    assert _fields(summary) == AC1_FIELDS
    assert _choose_button(summary).hasFocus(), (
        f"focus is on {QApplication.focusWidget()!r}, not the button"
    )
    assert _hashes(tmp_path) == before


def test_a_folder_with_no_pages_chosen_from_the_summary_replaces_it_with_the_error_state(
    qtbot,  # type: ignore[no-untyped-def]
    windows,
    ac1_folder: Path,
    no_pages: Path,
) -> None:
    window = _intake(qtbot, windows, Chooser(ac1_folder, no_pages))
    _choose_from_target(window)
    _activate_button(qtbot, _choose_button(_summary(window)), "click")

    target = _target(window)
    assert target.state == "error"
    parts = [target.findChild(QLabel, n) for n in ("headline", "affordance")]
    assert [p.text() if p else None for p in parts] == [
        _no_pages(no_pages.resolve()),
        AFFORDANCE_ERROR,
    ]
    assert window.opened is None


def test_the_drop_target_restored_from_the_summary_still_asks_the_chooser(
    qtbot,  # type: ignore[no-untyped-def]
    windows,
    ac1_folder: Path,
    no_pages: Path,
) -> None:
    """C-4: `show_error` wires a new target exactly as the constructor does."""
    chooser = Chooser(ac1_folder, no_pages, None)
    window = _intake(qtbot, windows, chooser)
    _choose_from_target(window)
    _activate_button(qtbot, _choose_button(_summary(window)), "click")
    assert len(chooser.parents) == 2

    QTest.mouseClick(_target(window), Qt.MouseButton.LeftButton)
    _settle()

    assert len(chooser.parents) == 3, "the restored drop target does not ask the chooser"


def test_the_drop_target_restored_from_the_summary_still_hands_a_dropped_folder_over(
    qtbot,  # type: ignore[no-untyped-def]
    windows,
    ac1_folder: Path,
    no_pages: Path,
) -> None:
    opener = Opener()
    window = _intake(qtbot, windows, Chooser(ac1_folder, no_pages), opener)
    _choose_from_target(window)
    _activate_button(qtbot, _choose_button(_summary(window)), "click")

    _target(window).dropped.emit(ac1_folder)
    _settle()

    assert opener.calls == [ac1_folder, no_pages, ac1_folder]
    assert _fields(_summary(window)) == AC1_FIELDS


def test_a_second_folder_of_pages_chosen_from_the_summary_shows_its_own_summary(
    qtbot,  # type: ignore[no-untyped-def]
    windows,
    tmp_path: Path,
    ac1_folder: Path,
    page_png: bytes,
) -> None:
    other = _pages_folder(tmp_path, "Chapter 13", ("01.png", "02.png"), page_png)
    window = _intake(qtbot, windows, Chooser(ac1_folder, other))
    _choose_from_target(window)
    first = _summary(window)

    _activate_button(qtbot, _choose_button(first), "click")

    second = _summary(window)
    assert second is not first
    assert _fields(second) == ("Chapter 13", "2 pages", "First page: 01.png", "Last page: 02.png")
    assert _scroll(second).hasFocus(), "focus is not on the new summary's scroll area"


def test_a_folder_with_a_project_chosen_from_the_summary_opens_the_workspace(
    qtbot,  # type: ignore[no-untyped-def]
    windows,
    ac1_folder: Path,
    source: Path,
) -> None:
    window = _intake(qtbot, windows, Chooser(ac1_folder, source))
    _choose_from_target(window)

    _activate_button(qtbot, _choose_button(_summary(window)), "click")

    assert isinstance(window.opened, Workspace), f"opened is {type(window.opened).__name__}"
    qtbot.addWidget(window.opened)
    assert window.opened.isVisible(), "the Workspace was not shown"
    assert not window.isVisible(), "the intake window is still open"
