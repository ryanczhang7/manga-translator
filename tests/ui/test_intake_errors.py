"""MT-057 AC-2, AC-3, AC-5 and AC-6: a chosen folder that cannot become a
chapter summary shows the drop target's error state, and writes nothing.

"Chosen" is both paths (story `## Acceptance criteria`): the chooser, through
`MainWindow`'s one hand-over, and `mangatl <folder>`, where `build_window`
returns the *intake* window with its target in the error state (C-3, PO-8) -
not MT-054's notice window. The dropped path of AC-6 is in
`test_folder_drop.py`; the summary itself is in `test_chapter_summary.py`.
This file imports nothing this story adds, so every test here runs in RED and
fails on its own assertion.

Oracle partition (story `## Contract`):

- **Settled - spelled out here, never imported:** AC-2's headline, AC-3's
  headline, AC-6's sentence (the Lead Designer's, `components.md` §2 as amended
  2026-09-30). `{folder}` is `str(folder.resolve())`, whole.
- **Oracle-free, control demanded (AC-6):** the same folder with the bad file
  replaced by a valid PNG shows the summary; with two bad files, `p2.png` and
  `p10.png`, the one named is `p2.png` - first in natural order, where lexical
  AND directory-listing order (NTFS: `p1, p10, p2, p3`) would name `p10.png`.
- **Mechanical:** AC-3's OS text passed through - C-7's fixture patches
  `pathlib.Path.iterdir` to raise `PermissionError(13, PROBE, path)` for the
  chosen folder only, `PROBE` a string no constant could contain (probed in
  RED: `read_chapter` reaches `iterdir` on the resolved folder and nothing
  else in `open_folder`, nor `rglob`, calls it); AC-5's tree hash (C-6) and no
  `.mtproj` sibling, for every error.

**Timing:** no real-time waits, only exposure, activation and focus.
"""

from __future__ import annotations

import hashlib
import pathlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QSize, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QWidget

from mangatl import app as app_module
from mangatl.ui import tokens_gen
from mangatl.ui.intake import FolderDropTarget
from mangatl.ui.main_window import WINDOW_TITLE, MainWindow

# --- Settled strings, spelled out (never read back from the module under test) ------
AFFORDANCE_ERROR = "Choose a different folder"


def _no_pages(folder: Path) -> str:
    """AC-2. No backticks: they were formatting in the story, not copy."""
    return f"No page images in {folder}. This tool reads .png and .jpg files."


def _cannot_read(folder: Path, os_error: str) -> str:
    """AC-3: the folder, then the operating system's own text on a new line."""
    return f"Windows would not let this app read {folder}.\n{os_error}"


def _undecodable(filename: str) -> str:
    """AC-6, the designer's sentence."""
    return (
        f"{filename} could not be opened as a page image."
        " Remove or replace it, then choose the folder again."
    )


#: C-7: text no constant in the app could contain.
PROBE = "Access is denied (probe 7f3a)"
#: An `OSError` with no `strerror`: its `str()` is the text (C-2's fallback).
PROBE_NO_ERRNO = "listing refused (probe c19e, no errno)"


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
    return _png(QSize(60, 80))


def _folder(root: Path, name: str, files: dict[str, bytes]) -> Path:
    folder = root / name
    folder.mkdir()
    for filename, data in files.items():
        (folder / filename).write_bytes(data)
    return folder


@pytest.fixture
def empty(tmp_path: Path) -> Path:
    """AC-2: nothing at all."""
    return _folder(tmp_path, "Empty chapter", {})


@pytest.fixture
def no_page_files(tmp_path: Path, page_png: bytes) -> Path:
    """AC-2: files, none a page - and a page one level down, which is not read
    (subfolders are not descended into, MT-004)."""
    folder = _folder(tmp_path, "Vol 1 & 2", {"notes.txt": b"x", "cover.gif": b"GIF89a"})
    _folder(folder, "extras", {"p1.png": page_png})
    return folder


@pytest.fixture
def listable(tmp_path: Path, page_png: bytes) -> Path:
    """AC-3: valid pages - it would show a summary if it could be listed."""
    return _folder(tmp_path, "Locked & shared", {"p1.png": page_png, "p2.png": page_png})


@pytest.fixture
def one_bad(tmp_path: Path, page_png: bytes) -> Path:
    """AC-6: `p2.png` will not decode; the pages around it do."""
    return _folder(
        tmp_path,
        "Vol 3",
        {"p1.png": page_png, "p2.png": b"not a page image", "p3.png": page_png},
    )


@pytest.fixture
def two_bad(tmp_path: Path, page_png: bytes) -> Path:
    """AC-6: `p2.png` and `p10.png` will not decode. Natural order names
    `p2.png`; lexical and NTFS listing order (`p1, p10, p2, p3`) `p10.png`."""
    folder = _folder(
        tmp_path,
        "Vol 4",
        {
            "p1.png": page_png,
            "p2.png": b"not a page image",
            "p3.png": page_png,
            "p10.png": b"not a page image either",
        },
    )
    listed = [p.name for p in folder.iterdir()]
    bad_first_listed = next(n for n in listed if n in ("p2.png", "p10.png"))
    assert bad_first_listed == "p10.png", f"precondition: listing order is {listed}"
    return folder


def _hashes(root: Path) -> dict[str, str | None]:
    """C-6: every path under `root`, with the SHA-256 of every file."""
    return {
        str(p.relative_to(root)): (
            hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
        )
        for p in sorted(root.rglob("*"))
    }


def _assert_wrote_nothing(root: Path, folder: Path, before: dict[str, str | None]) -> None:
    """AC-5: the tree byte-for-byte as it was, and no `.mtproj` sibling."""
    assert before, "precondition: nothing to hash"
    assert _hashes(root) == before, "showing the error created, modified or deleted something"
    project = folder.with_name(folder.name + ".mtproj")
    assert not project.exists(), f"{project.name} was created"


def _deny_listing(
    monkeypatch: pytest.MonkeyPatch, folder: Path, error: OSError | None = None
) -> list[Path]:
    """C-7: `Path.iterdir` raises for `folder` (compared resolved) and
    delegates otherwise. Returns every path it refused, so a test can show the
    patch was reached rather than the outcome arriving some other way."""
    locked = folder.resolve()
    real = pathlib.Path.iterdir
    refused: list[Path] = []

    def iterdir(self: Path) -> Iterator[Path]:
        if self.resolve() == locked:
            refused.append(self)
            raise error if error is not None else PermissionError(13, PROBE, str(self))
        return real(self)

    monkeypatch.setattr(pathlib.Path, "iterdir", iterdir)
    return refused


# --- Windows --------------------------------------------------------------------------


class Chooser:
    """A `FolderChooser` returning the queued answers in order (then `None`)."""

    def __init__(self, *answers: Path | None) -> None:
        self.answers = list(answers)
        self.parents: list[QWidget] = []

    def __call__(self, parent: QWidget) -> Path | None:
        self.parents.append(parent)
        return self.answers.pop(0) if self.answers else None


@pytest.fixture
def windows(qtbot) -> Iterator[list[QMainWindow]]:  # type: ignore[no-untyped-def]
    made: list[QMainWindow] = []
    yield made
    for window in made:
        opened = getattr(window, "opened", None)
        if isinstance(opened, QMainWindow):
            opened.close()
        window.close()


def _choose(qtbot, windows: list[QMainWindow], folder: Path) -> MainWindow:  # type: ignore[no-untyped-def]
    """The intake window with the real `open_folder`, shown; `folder` chosen."""
    window = MainWindow(open_folder=app_module.open_folder, choose_folder=Chooser(folder))
    qtbot.addWidget(window)
    windows.append(window)
    window.resize(900, 600)
    with qtbot.waitExposed(window):
        window.show()
    _settle()
    QTest.mouseClick(_target(window), Qt.MouseButton.LeftButton)
    _settle()
    return window


def _launch(qtbot, folder: Path | str) -> QMainWindow:  # type: ignore[no-untyped-def]
    """`mangatl <folder>`: the window `build_window` returns, not shown."""
    window = app_module.build_window([str(folder)])
    qtbot.addWidget(window)
    return window


def _target(window: QMainWindow) -> FolderDropTarget:
    central = window.centralWidget()
    assert isinstance(central, FolderDropTarget), (
        f"central widget is {type(central).__name__}"
        f" ({getattr(central, 'objectName', lambda: '')()!r}), not the FolderDropTarget"
    )
    return central


def _assert_error(window: QMainWindow, text: str) -> None:
    """The drop target's error state (MT-055 C-3): the reason verbatim as the
    headline, the body empty and hidden, the affordance offering another
    folder, the reason as the description - and no summary, no notice."""
    target = _target(window)
    headline, body, affordance = (
        target.findChild(QLabel, name) for name in ("headline", "body", "affordance")
    )
    assert headline is not None and body is not None and affordance is not None
    assert (target.state, headline.text()) == ("error", text)
    assert body.text() == ""
    assert not body.isVisibleTo(target)
    assert affordance.text() == AFFORDANCE_ERROR
    assert target.accessibleDescription() == text
    assert window.findChild(QWidget, "chapter-summary") is None, "a summary was created"
    assert window.findChild(QObject, "notice") is None, "MT-054's notice was shown"


def _assert_chosen_error(window: MainWindow, text: str) -> None:
    assert window.opened is None, f"the folder opened {type(window.opened).__name__}"
    assert window.isVisible(), "the intake window closed"
    _assert_error(window, text)


def _assert_launched_error(window: QMainWindow, text: str) -> None:
    """C-3: the intake window, target in its error state, not shown."""
    assert type(window) is MainWindow, f"build_window returned a {type(window).__name__}"
    assert window.windowTitle() == WINDOW_TITLE
    assert not window.isVisible(), "build_window showed its window"
    _assert_error(window, text)
    assert window.open_folder is app_module.open_folder, "the intake window has no open_folder"


# =============================================================================
# AC-2: a folder with no .png/.jpg/.jpeg files
# =============================================================================


@pytest.mark.parametrize("which", ["empty", "no_page_files"])
def test_a_chosen_folder_with_no_page_images_says_so_and_writes_nothing(
    qtbot,  # type: ignore[no-untyped-def]
    windows,
    tmp_path: Path,
    request: pytest.FixtureRequest,
    which: str,
) -> None:
    folder: Path = request.getfixturevalue(which)
    before = _hashes(tmp_path)

    window = _choose(qtbot, windows, folder)

    _assert_chosen_error(window, _no_pages(folder.resolve()))
    _assert_wrote_nothing(tmp_path, folder, before)


@pytest.mark.parametrize("which", ["empty", "no_page_files"])
def test_mangatl_on_a_folder_with_no_page_images_shows_the_intake_error_and_writes_nothing(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
    request: pytest.FixtureRequest,
    which: str,
) -> None:
    folder: Path = request.getfixturevalue(which)
    before = _hashes(tmp_path)

    window = _launch(qtbot, folder)

    _assert_launched_error(window, _no_pages(folder.resolve()))
    _assert_wrote_nothing(tmp_path, folder, before)


# =============================================================================
# AC-3: a folder the app cannot list
# =============================================================================


def test_a_chosen_folder_that_cannot_be_listed_names_it_and_passes_the_os_text_through(
    qtbot,  # type: ignore[no-untyped-def]
    windows,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    listable: Path,
) -> None:
    before = _hashes(tmp_path)
    refused = _deny_listing(monkeypatch, listable)

    window = _choose(qtbot, windows, listable)

    _assert_chosen_error(window, _cannot_read(listable.resolve(), PROBE))
    assert refused, "C-7: the error did not come from listing the chosen folder"
    _assert_wrote_nothing(tmp_path, listable, before)


def test_mangatl_on_a_folder_that_cannot_be_listed_shows_the_intake_error_with_the_os_text(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    listable: Path,
) -> None:
    before = _hashes(tmp_path)
    refused = _deny_listing(monkeypatch, listable)

    window = _launch(qtbot, listable)

    _assert_launched_error(window, _cannot_read(listable.resolve(), PROBE))
    assert refused, "C-7: the error did not come from listing the chosen folder"
    _assert_wrote_nothing(tmp_path, listable, before)


def test_an_os_error_without_strerror_is_shown_by_its_own_text(
    qtbot,  # type: ignore[no-untyped-def]
    windows,
    monkeypatch: pytest.MonkeyPatch,
    listable: Path,
) -> None:
    """C-2: `strerror` if not `None`, else `str(error)`."""
    error = OSError(PROBE_NO_ERRNO)
    assert error.strerror is None and str(error) == PROBE_NO_ERRNO
    _deny_listing(monkeypatch, listable, error)

    window = _choose(qtbot, windows, listable)

    _assert_chosen_error(window, _cannot_read(listable.resolve(), PROBE_NO_ERRNO))


# =============================================================================
# AC-6: a page that will not decode
# =============================================================================


def test_a_chosen_folder_with_an_undecodable_page_names_it_and_shows_no_summary(
    qtbot,  # type: ignore[no-untyped-def]
    windows,
    tmp_path: Path,
    one_bad: Path,
) -> None:
    before = _hashes(tmp_path)

    window = _choose(qtbot, windows, one_bad)

    _assert_chosen_error(window, _undecodable("p2.png"))
    _assert_wrote_nothing(tmp_path, one_bad, before)


def test_mangatl_on_a_folder_with_an_undecodable_page_shows_the_intake_error_naming_it(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
    one_bad: Path,
) -> None:
    before = _hashes(tmp_path)

    window = _launch(qtbot, one_bad)

    _assert_launched_error(window, _undecodable("p2.png"))
    _assert_wrote_nothing(tmp_path, one_bad, before)


def test_the_same_folder_with_the_bad_page_replaced_shows_the_summary(
    qtbot,  # type: ignore[no-untyped-def]
    windows,
    one_bad: Path,
    page_png: bytes,
) -> None:
    """AC-6's control: the error is about that file, not about the folder."""
    (one_bad / "p2.png").write_bytes(page_png)

    window = _choose(qtbot, windows, one_bad)

    central = window.centralWidget()
    assert central.objectName() == "chapter-summary", (
        f"central widget is {type(central).__name__} ({central.objectName()!r}), not the summary"
    )
    assert window.opened is None


def test_with_two_undecodable_pages_the_first_in_natural_order_is_named(
    qtbot,  # type: ignore[no-untyped-def]
    windows,
    tmp_path: Path,
    two_bad: Path,
) -> None:
    before = _hashes(tmp_path)

    window = _choose(qtbot, windows, two_bad)

    _assert_chosen_error(window, _undecodable("p2.png"))
    _assert_wrote_nothing(tmp_path, two_bad, before)


def test_mangatl_with_two_undecodable_pages_names_the_first_in_natural_order(
    qtbot,  # type: ignore[no-untyped-def]
    two_bad: Path,
) -> None:
    window = _launch(qtbot, two_bad)

    _assert_launched_error(window, _undecodable("p2.png"))
