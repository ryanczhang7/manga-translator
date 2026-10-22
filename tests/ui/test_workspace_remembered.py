"""MT-088: the workspace remembers its size, position and the dragged column width.

Three sections, cheapest first:

1. **Block 1, no Qt.** `mangatl.ui.workspace_state`'s pure functions - the
   dataclass, the first-run size, the clamp, the reader and the writer. None of
   these tests requests `qtbot`, so none needs a `QApplication`; one test checks
   in a fresh interpreter that importing the module loads no PySide6 at all.
2. **Block 3, a bare `Workspace`.** Armed with
   `remember_layout(tmp_path / "workspace.json", work_area=...)` - every work
   area is INJECTED (Contract block 6, PO-2), never read from the offscreen
   800 x 800 screen - then shown and settled.
3. **Block 4, through `mangatl.app.build_window`.** The one place the DEFAULT
   work area is used: the offscreen screen's `availableGeometry()`, measured on
   this host as `QRect(0, 0, 800, 800)`.

**Oracle partition (story, `## Contract`).** *Settled*, read out of
`layout.md` §Window and written as literals ONCE, in the constants test:
1600 x 1000, 1100 x 720, 280-560, 300 / 380, `version: 1`,
`<APPDATA>/mangatl/workspace.json`. *Mechanical*, pinned exactly: everything
else. *Oracle-free*: none. No assertion here has a tolerance.

**Contract amendments made in RED** (story, `## Contract`):

- **A-1** - `first_run_size` and `clamp_state`: when the work area is smaller
  than the minimum on EITHER axis, the size is the minimum on BOTH. AC-3 pins
  "1100 x 720 on an 800 x 800 one (the minimum wins)", and the block's per-axis
  formula gives 1100 x 800 there. The frozen criterion wins.
- **A-2** - `layout_state()` of a maximised window reports the normal
  geometry's position in `pos()` terms (the frame's top-left, what `move()`
  takes). Measured offscreen: `normalGeometry().topLeft()` is the CLIENT
  top-left, 2 px inside `pos()` once the window has been shown, so a literal
  reading drifts the window 2 px per session.
- **A-3** - block 6's injected work area: AC-1's file (1600 x 1000 at
  (120, 80)) does not fit 1920 x 1040 under block 1's clamp (its bottom edge is
  1080), so the AC-1 tests inject a 2560 x 1440 area that holds it. Every other
  block-3 test keeps 1920 x 1040.

The helpers `_settle`, `_drag_column_to`, `_resize` and the `chapter_project`
fixture are copied from `tests/ui/test_workspace_breakpoint.py` (MT-048):
`tests` is not a package.
"""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from mangatl import app as app_module
from mangatl import app_paths
from mangatl.domain.page import Chapter, Page
from mangatl.store.project import Project, create_project
from mangatl.ui import tokens_gen
from mangatl.ui.workspace import (
    COLUMN_DEFAULT_NARROW,
    COLUMN_DEFAULT_WIDE,
    COLUMN_MAX_WIDTH,
    COLUMN_MIN_WIDTH,
    Workspace,
)
from mangatl.ui.workspace_state import (
    FIRST_RUN_SIZE,
    STATE_VERSION,
    WorkspaceState,
    clamp_state,
    first_run_size,
    read_state,
    write_state,
)

#: The work area every block-3 test injects (Contract block 6).
DESKTOP = (0, 0, 1920, 1040)
#: The same area, not at the origin: "x negative -> ax" must mean ax, not 0.
OFFSET = (100, 50, 1920, 1040)
#: AC-1's file - 1600 x 1000 at (120, 80) - does NOT fit DESKTOP: its bottom
#: edge would be 1080 > 1040, so the clamp moves y to 40 (A-3). AC-1 is judged
#: on a work area that holds it, so that nothing is clamped.
LARGE = (0, 0, 2560, 1440)
#: The offscreen platform's screen, measured (`availableGeometry()`), and an
#: area of that size for the pure tests.
OFFSCREEN = (0, 0, 800, 800)
MINIMUM = (1100, 720)
COLUMN_RANGE = (280, 560)

#: A width inside 280-560 that also fits beside the canvas minimum at 1100 px
#: (28 + 520 + 450 + 2 * 4 = 1006): the dragged column of AC-2.
DRAGGED = 450


def _state(**changes: Any) -> WorkspaceState:
    base: dict[str, Any] = {
        "width": 1600,
        "height": 1000,
        "x": 120,
        "y": 80,
        "maximized": False,
        "column_width": None,
    }
    base.update(changes)
    return WorkspaceState(**base)


def _raw(**changes: Any) -> dict[str, Any]:
    """The file's JSON object, written by hand - never by `write_state`, so the
    reader is judged against the pinned shape, not against its own writer."""
    data: dict[str, Any] = {
        "version": 1,
        "width": 1600,
        "height": 1000,
        "x": 120,
        "y": 80,
        "maximized": False,
        "column_width": None,
    }
    data.update(changes)
    return data


def _write_raw(path: Path, data: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# =============================================================================
# Settled numbers. Each is a literal HERE and only here.
# =============================================================================


def test_the_remembered_window_numbers_are_the_ones_layout_md_settles() -> None:
    assert FIRST_RUN_SIZE == (1600, 1000)
    assert STATE_VERSION == 1
    assert Workspace.MIN_SIZE == (1100, 720)
    assert (COLUMN_MIN_WIDTH, COLUMN_MAX_WIDTH) == (280, 560)
    assert (COLUMN_DEFAULT_NARROW, COLUMN_DEFAULT_WIDE) == (300, 380)
    assert MINIMUM == Workspace.MIN_SIZE
    assert COLUMN_RANGE == (COLUMN_MIN_WIDTH, COLUMN_MAX_WIDTH)


# =============================================================================
# Block 1 - the state, Qt-free. No test in this section requests qtbot.
# =============================================================================


def test_importing_the_state_module_loads_no_qt() -> None:
    # Contract block 1: "imports only the standard library". A fresh
    # interpreter, because this one has PySide6 loaded already.
    probe = (
        "import sys, mangatl.ui.workspace_state; "
        "print(sorted(m for m in sys.modules if m.split('.')[0] == 'PySide6'))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]", f"workspace_state loaded Qt: {result.stdout}"


def test_the_state_has_exactly_the_six_pinned_fields_in_order() -> None:
    names = [field.name for field in dataclasses.fields(WorkspaceState)]
    assert names == ["width", "height", "x", "y", "maximized", "column_width"]


def test_the_state_is_frozen() -> None:
    state = _state()
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.width = 1200  # type: ignore[misc]


@pytest.mark.parametrize(
    ("work_area", "expected"),
    [
        pytest.param((0, 0, 1920, 1040), (1600, 1000), id="1920x1040-takes-the-default"),
        pytest.param((0, 0, 1400, 900), (1400, 900), id="1400x900-takes-the-work-area"),
        pytest.param((0, 0, 800, 800), (1100, 720), id="800x800-the-minimum-wins"),
        pytest.param((0, 0, 2000, 900), (1600, 900), id="2000x900-mixed-per-axis"),
        pytest.param((0, 0, 1600, 1000), (1600, 1000), id="exactly-the-default"),
        pytest.param((0, 0, 1100, 720), (1100, 720), id="exactly-the-minimum"),
        pytest.param((300, 200, 1400, 900), (1400, 900), id="the-origin-is-irrelevant"),
        # A-1: a work area short of the minimum on ONE axis is the AC-3 rule.
        pytest.param((0, 0, 1920, 700), (1100, 720), id="A-1-short-in-height-only"),
        pytest.param((0, 0, 1000, 1040), (1100, 720), id="A-1-short-in-width-only"),
    ],
)
def test_the_first_run_size_is_the_default_capped_by_the_work_area_never_below_the_minimum(
    work_area: tuple[int, int, int, int], expected: tuple[int, int]
) -> None:
    assert first_run_size(work_area, MINIMUM) == expected


def _clamp(state: WorkspaceState, work_area: tuple[int, int, int, int]) -> WorkspaceState:
    return clamp_state(state, work_area, MINIMUM, COLUMN_RANGE)


def test_a_state_inside_every_limit_is_returned_unchanged() -> None:
    state = _state(width=1500, height=900, x=200, y=100, maximized=True, column_width=400)
    assert _clamp(state, DESKTOP) == state


def test_a_size_below_the_minimum_is_raised_to_the_minimum() -> None:
    clamped = _clamp(_state(width=900, height=500, x=100, y=50), DESKTOP)
    assert clamped == _state(width=1100, height=720, x=100, y=50)


def test_a_size_above_the_work_area_is_cut_to_the_work_area_and_moved_inside_it() -> None:
    clamped = _clamp(_state(width=3000, height=2000, x=10, y=10), DESKTOP)
    assert clamped == _state(width=1920, height=1040, x=0, y=0)


def test_a_width_above_the_work_area_is_cut_to_the_work_area_width_only() -> None:
    clamped = _clamp(_state(width=2500, height=900, x=0, y=100), DESKTOP)
    assert clamped == _state(width=1920, height=900, x=0, y=100)


def test_a_top_left_far_past_the_work_area_is_moved_to_the_nearest_point_inside() -> None:
    # x into [0, 1920 - 1600] = [0, 320]; y into [0, 1040 - 1000] = [0, 40].
    clamped = _clamp(_state(x=5000, y=5000), DESKTOP)
    assert (clamped.x, clamped.y) == (320, 40)


def test_a_top_left_past_an_offset_work_area_lands_on_its_far_edge() -> None:
    # x into [100, 100 + 1920 - 1600] = [100, 420]; y into [50, 50 + 40] = [50, 90].
    clamped = _clamp(_state(x=5000, y=5000), OFFSET)
    assert (clamped.x, clamped.y) == (420, 90)


def test_a_window_whose_bottom_edge_overhangs_the_work_area_is_moved_up_into_it() -> None:
    # A-3: the whole window is brought inside, not only its top-left point.
    # y into [0, 1040 - 1000] = [0, 40]; x = 120 is already in [0, 320].
    clamped = _clamp(_state(x=120, y=80), DESKTOP)
    assert (clamped.x, clamped.y) == (120, 40)


def test_a_negative_top_left_is_moved_to_the_work_area_origin() -> None:
    clamped = _clamp(_state(x=-300, y=-40), DESKTOP)
    assert (clamped.x, clamped.y) == (0, 0)


def test_a_negative_top_left_is_moved_to_an_offset_work_areas_origin_not_to_zero() -> None:
    clamped = _clamp(_state(x=-300, y=-40), OFFSET)
    assert (clamped.x, clamped.y) == (100, 50)


def test_a_work_area_smaller_than_the_minimum_keeps_the_minimum_and_its_left_edge() -> None:
    # A-1: 800 x 800 cannot hold 1100 x 720, so the size is the minimum on both
    # axes. x: aw 800 < 1100 -> ax. y: ah 800 >= 720 -> 20 stays in [0, 80].
    clamped = _clamp(_state(width=1500, height=900, x=10, y=20), OFFSCREEN)
    assert clamped == _state(width=1100, height=720, x=0, y=20)


def test_an_offset_work_area_narrower_than_the_minimum_puts_x_on_its_left_edge() -> None:
    # x: aw 800 < 1100 -> ax = 50. y: 20 into [30, 30 + 80] -> 30.
    clamped = _clamp(_state(width=1500, height=900, x=10, y=20), (50, 30, 800, 800))
    assert (clamped.width, clamped.height, clamped.x, clamped.y) == (1100, 720, 50, 30)


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        pytest.param(100, 280, id="100-raised-to-280"),
        pytest.param(279, 280, id="279-raised-to-280"),
        pytest.param(280, 280, id="280-kept"),
        pytest.param(400, 400, id="400-kept"),
        pytest.param(560, 560, id="560-kept"),
        pytest.param(561, 560, id="561-cut-to-560"),
        pytest.param(900, 560, id="900-cut-to-560"),
        pytest.param(None, None, id="never-dragged-stays-None"),
    ],
)
def test_the_column_width_is_clamped_into_280_to_560_and_none_stays_none(
    stored: int | None, expected: int | None
) -> None:
    assert _clamp(_state(column_width=stored), DESKTOP).column_width == expected


def test_clamping_keeps_the_maximised_flag() -> None:
    assert _clamp(_state(width=900, maximized=True), DESKTOP).maximized is True


def test_a_missing_file_reads_as_no_state(tmp_path: Path) -> None:
    assert read_state(tmp_path / "workspace.json") is None


def test_a_valid_file_reads_as_exactly_its_state(tmp_path: Path) -> None:
    path = _write_raw(
        tmp_path / "workspace.json",
        _raw(width=1500, height=900, x=-10, y=20, maximized=True, column_width=400),
    )
    assert read_state(path) == _state(
        width=1500, height=900, x=-10, y=20, maximized=True, column_width=400
    )


def test_a_valid_file_with_an_undragged_column_reads_column_width_none(tmp_path: Path) -> None:
    path = _write_raw(tmp_path / "workspace.json", _raw(column_width=None))
    assert read_state(path) == _state(column_width=None)


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b"", id="empty"),
        pytest.param(b"\x00\xff\xfe junk \x80", id="junk-bytes"),
        pytest.param(b"{not json", id="truncated-json"),
        pytest.param(b"[1600, 1000, 120, 80]", id="a-json-list"),
        pytest.param(b'"workspace"', id="a-json-string"),
        pytest.param(b"null", id="json-null"),
    ],
)
def test_a_file_that_is_not_a_json_object_reads_as_no_state(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "workspace.json"
    path.write_bytes(content)
    assert read_state(path) is None


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(_raw(version=2), id="version-2"),
        pytest.param(_raw(version=0), id="version-0"),
        pytest.param(_raw(version="1"), id="version-a-string"),
        pytest.param({k: v for k, v in _raw().items() if k != "version"}, id="no-version"),
        pytest.param({k: v for k, v in _raw().items() if k != "width"}, id="no-width"),
        pytest.param({k: v for k, v in _raw().items() if k != "y"}, id="no-y"),
        pytest.param({k: v for k, v in _raw().items() if k != "maximized"}, id="no-maximized"),
        pytest.param(
            {k: v for k, v in _raw().items() if k != "column_width"}, id="no-column-width"
        ),
        pytest.param(_raw(width=True), id="width-true-bool-is-not-int"),
        pytest.param(_raw(x=False), id="x-false-bool-is-not-int"),
        pytest.param(_raw(height=1000.0), id="height-a-float"),
        pytest.param(_raw(width="1600"), id="width-a-string"),
        pytest.param(_raw(y=None), id="y-null"),
        pytest.param(_raw(maximized=1), id="maximized-an-int"),
        pytest.param(_raw(maximized="false"), id="maximized-a-string"),
        pytest.param(_raw(column_width=True), id="column-width-true"),
        pytest.param(_raw(column_width="400"), id="column-width-a-string"),
        pytest.param(_raw(column_width=400.0), id="column-width-a-float"),
    ],
)
def test_a_file_of_another_version_or_with_a_field_missing_or_mistyped_reads_as_no_state(
    tmp_path: Path, data: dict[str, Any]
) -> None:
    path = _write_raw(tmp_path / "workspace.json", data)
    assert read_state(path) is None


def test_a_directory_where_the_file_should_be_reads_as_no_state(tmp_path: Path) -> None:
    path = tmp_path / "workspace.json"
    path.mkdir()
    assert read_state(path) is None


def test_a_path_under_a_regular_file_reads_as_no_state(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    assert read_state(blocker / "workspace.json") is None


def test_writing_creates_the_missing_parent_folders_and_reports_success(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "er" / "workspace.json"
    assert write_state(path, _state()) is True
    assert path.is_file()


def test_the_written_file_is_exactly_the_pinned_json_object(tmp_path: Path) -> None:
    path = tmp_path / "workspace.json"
    write_state(path, _state(width=1500, height=900, x=-4, y=20, maximized=True, column_width=400))
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "version": 1,
        "width": 1500,
        "height": 900,
        "x": -4,
        "y": 20,
        "maximized": True,
        "column_width": 400,
    }


def test_an_undragged_column_is_written_as_json_null(tmp_path: Path) -> None:
    path = tmp_path / "workspace.json"
    write_state(path, _state(column_width=None))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "column_width" in data
    assert data["column_width"] is None


def test_writing_replaces_an_earlier_file(tmp_path: Path) -> None:
    path = _write_raw(tmp_path / "workspace.json", _raw(width=9999))
    assert write_state(path, _state(width=1200)) is True
    assert json.loads(path.read_text(encoding="utf-8"))["width"] == 1200


def test_a_written_state_reads_back_equal(tmp_path: Path) -> None:
    path = tmp_path / "workspace.json"
    for state in (
        _state(),
        _state(width=1100, height=720, x=-8, y=0, maximized=True, column_width=280),
        _state(width=1920, height=1040, x=0, y=0, maximized=False, column_width=560),
    ):
        assert write_state(path, state) is True
        assert read_state(path) == state


def test_a_parent_that_is_a_regular_file_makes_writing_report_failure_without_raising(
    tmp_path: Path,
) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    assert write_state(blocker / "workspace.json", _state()) is False
    assert blocker.read_text(encoding="utf-8") == "not a directory"


def test_a_directory_at_the_files_path_makes_writing_report_failure_without_raising(
    tmp_path: Path,
) -> None:
    path = tmp_path / "workspace.json"
    path.mkdir()
    assert write_state(path, _state()) is False
    assert path.is_dir()


# =============================================================================
# Block 3 - a bare Workspace armed with remember_layout. Every work area injected.
# =============================================================================

WIDE = 1900  # above the 1440 breakpoint
NARROW = 1100  # the window minimum, below it
HEIGHT = 720

PAGES: tuple[tuple[str, QSize], ...] = (
    ("001.png", QSize(64, 96)),
    ("002.png", QSize(72, 104)),
)


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


def _remembered(
    qtbot,  # type: ignore[no-untyped-def]
    path: Path,
    work_area: tuple[int, int, int, int] = DESKTOP,
    project: Project | None = None,
) -> Workspace:
    """A Workspace armed on `path`, shown and settled. `load_chapter` runs
    FIRST when a project is given, because it resets `_column_dragged`."""
    window = Workspace()
    qtbot.addWidget(window)
    if project is not None:
        window.load_chapter(project)
    window.remember_layout(path, work_area=lambda: work_area)
    with qtbot.waitExposed(window):
        window.show()
    _settle()
    return window


def _size(window: Workspace) -> tuple[int, int]:
    return (window.width(), window.height())


def _pos(window: Workspace) -> tuple[int, int]:
    return (window.pos().x(), window.pos().y())


def _drag_column_to(window: Workspace, splitter_pos: int) -> None:
    """Drag the divider between canvas and column (handle index 2)."""
    window.splitter.moveSplitter(splitter_pos, 2)
    _settle()


def _resize(window: Workspace, width: int) -> None:
    window.resize(width, HEIGHT)
    _settle()
    assert window.width() == width, "the window did not settle at the requested width"


def _image(size: QSize) -> QImage:
    image = QImage(size, QImage.Format.Format_RGB32)
    image.fill(QColor(tokens_gen.COLOR_TEXT_PRIMARY))
    return image


@pytest.fixture
def chapter_project(tmp_path: Path) -> Iterator[Project]:
    """A real project over two genuine PNGs."""
    source = tmp_path / "chapter"
    source.mkdir()
    pages = []
    for ordinal, (filename, size) in enumerate(PAGES):
        assert _image(size).save(str(source / filename), "PNG")
        pages.append(
            Page(
                ordinal=ordinal,
                filename=filename,
                width=size.width(),
                height=size.height(),
                sha256=str(ordinal) * 64,
            )
        )
    chapter = Chapter(source_dir=source, pages=tuple(pages))
    with create_project(chapter, tmp_path / "chapter.mtproj") as project:
        yield project


# --- AC-1: size, position, maximised ------------------------------------------


def test_a_remembered_size_and_position_are_what_the_window_opens_at(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    path = _write_raw(tmp_path / "workspace.json", _raw(width=1600, height=1000, x=120, y=80))
    window = _remembered(qtbot, path, LARGE)
    assert _size(window) == (1600, 1000)
    assert _pos(window) == (120, 80)
    assert not window.isMaximized()


def test_a_remembered_maximised_window_opens_maximised_and_restores_to_its_normal_geometry(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    path = _write_raw(tmp_path / "workspace.json", _raw(maximized=True))
    window = _remembered(qtbot, path, LARGE)
    assert window.isMaximized()

    window.showNormal()
    _settle()

    assert not window.isMaximized()
    assert _size(window) == (1600, 1000)
    assert _pos(window) == (120, 80)


def test_layout_state_is_the_shown_windows_size_position_and_flags(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    path = _write_raw(tmp_path / "workspace.json", _raw(width=1500, height=900, x=200, y=100))
    window = _remembered(qtbot, path)
    assert window.layout_state() == _state(
        width=1500, height=900, x=200, y=100, maximized=False, column_width=None
    )


def test_closing_a_resized_and_moved_window_writes_exactly_its_layout_state(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    path = tmp_path / "workspace.json"  # no file: the first run
    window = _remembered(qtbot, path)
    window.resize(1500, 900)
    window.move(200, 100)
    _settle()
    expected = _state(width=1500, height=900, x=200, y=100, maximized=False, column_width=None)
    assert window.layout_state() == expected

    window.close()

    assert read_state(path) == expected


def test_closing_a_window_opened_maximised_writes_its_normal_geometry_and_the_flag(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    path = _write_raw(tmp_path / "workspace.json", _raw(maximized=True))
    window = _remembered(qtbot, path, LARGE)
    assert window.isMaximized()
    expected = _state(width=1600, height=1000, x=120, y=80, maximized=True, column_width=None)
    assert window.layout_state() == expected

    window.close()

    assert read_state(path) == expected


def test_a_window_maximised_after_a_move_writes_the_moved_position_and_reopens_there(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    # A-2: the position is pos()'s, not normalGeometry()'s client top-left
    # (measured 2 px inside it offscreen) - or every session drifts the window.
    path = tmp_path / "workspace.json"
    window = _remembered(qtbot, path)
    window.resize(1500, 900)
    window.move(200, 100)
    _settle()
    window.showMaximized()
    _settle()
    assert window.isMaximized()
    expected = _state(width=1500, height=900, x=200, y=100, maximized=True, column_width=None)
    assert window.layout_state() == expected

    window.close()
    assert read_state(path) == expected

    again = _remembered(qtbot, path)
    assert again.isMaximized()
    again.showNormal()
    _settle()
    assert (_size(again), _pos(again)) == ((1500, 900), (200, 100))


# --- AC-3: no usable file is the first run ---------------------------------------


@pytest.mark.parametrize(
    ("work_area", "size", "column"),
    [
        pytest.param((0, 0, 1920, 1040), (1600, 1000), 380, id="1920x1040"),
        pytest.param((0, 0, 1400, 900), (1400, 900), 300, id="1400x900"),
        pytest.param((0, 0, 800, 800), (1100, 720), 300, id="800x800-the-minimum-wins"),
    ],
)
def test_with_no_state_file_the_window_opens_at_the_first_run_size_with_the_default_column(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
    work_area: tuple[int, int, int, int],
    size: tuple[int, int],
    column: int,
) -> None:
    window = _remembered(qtbot, tmp_path / "workspace.json", work_area)
    assert _size(window) == size
    assert window.splitter.sizes()[2] == column
    assert window._column_dragged is False
    assert not window.isMaximized()


def _unusable(tmp_path: Path, kind: str) -> Path:
    path = tmp_path / "workspace.json"
    if kind == "a-directory":
        path.mkdir()
    elif kind == "junk-bytes":
        path.write_bytes(b"\x00\xff\xfe junk \x80")
    elif kind == "not-json":
        path.write_text("{width: 1500", encoding="utf-8")
    elif kind == "version-2":
        _write_raw(path, _raw(version=2, width=1500, height=900, column_width=400))
    elif kind == "width-true":
        _write_raw(path, _raw(width=True, column_width=400))
    else:  # pragma: no cover - a parametrize typo
        raise AssertionError(kind)
    return path


@pytest.mark.parametrize(
    "kind", ["a-directory", "junk-bytes", "not-json", "version-2", "width-true"]
)
def test_an_unusable_state_file_is_the_first_run(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
    kind: str,
) -> None:
    window = _remembered(qtbot, _unusable(tmp_path, kind), DESKTOP)
    assert _size(window) == (1600, 1000)
    assert window.splitter.sizes()[2] == COLUMN_DEFAULT_WIDE
    assert window._column_dragged is False


# --- AC-4: the file's values are clamped before they are applied --------------------


def test_a_remembered_size_below_the_minimum_opens_at_the_minimum(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    path = _write_raw(tmp_path / "workspace.json", _raw(width=900, height=500, x=100, y=50))
    window = _remembered(qtbot, path)
    assert _size(window) == (1100, 720)
    assert _pos(window) == (100, 50)


def test_a_remembered_size_above_the_work_area_opens_at_the_work_area(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    path = _write_raw(tmp_path / "workspace.json", _raw(width=3000, height=2000, x=10, y=10))
    window = _remembered(qtbot, path)
    assert _size(window) == (1920, 1040)
    assert _pos(window) == (0, 0)


def test_a_remembered_position_off_the_work_area_opens_inside_it(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    path = _write_raw(tmp_path / "workspace.json", _raw(x=5000, y=5000))
    window = _remembered(qtbot, path)
    assert _pos(window) == (320, 40)


def test_a_remembered_negative_position_opens_at_the_work_area_origin(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    path = _write_raw(tmp_path / "workspace.json", _raw(x=-300, y=-40))
    window = _remembered(qtbot, path, OFFSET)
    assert _pos(window) == (100, 50)


@pytest.mark.parametrize(
    ("stored", "shown"),
    [pytest.param(100, 280, id="100-opens-at-280"), pytest.param(900, 560, id="900-opens-at-560")],
)
def test_a_remembered_column_outside_280_to_560_opens_clamped(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
    stored: int,
    shown: int,
) -> None:
    path = _write_raw(tmp_path / "workspace.json", _raw(column_width=stored))
    window = _remembered(qtbot, path)
    assert _size(window) == (1600, 1000)
    assert window.splitter.sizes()[2] == shown
    assert window._column_dragged is True


# --- AC-2: the dragged column survives the session ---------------------------------


def test_a_dragged_column_is_reopened_at_its_width_and_keeps_it_across_the_breakpoint(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
    chapter_project: Project,
) -> None:
    path = tmp_path / "workspace.json"
    first = _remembered(qtbot, path, DESKTOP, chapter_project)
    assert _size(first) == (1600, 1000)
    splitter = first.splitter
    _drag_column_to(first, splitter.width() - splitter.handleWidth() - DRAGGED)
    assert splitter.sizes()[2] == DRAGGED, "the drag did not land where the test aimed it"
    assert first._column_dragged is True

    first.close()
    state = read_state(path)
    assert state is not None
    assert state.column_width == DRAGGED

    second = _remembered(qtbot, path, DESKTOP, chapter_project)
    assert second.splitter.sizes()[2] == DRAGGED
    assert second._column_dragged is True

    # MT-048's rule across the session: a drag survives a crossing either way.
    _resize(second, NARROW)
    assert second.splitter.sizes()[2] == DRAGGED
    _resize(second, WIDE)
    assert second.splitter.sizes()[2] == DRAGGED


def test_an_undragged_column_is_written_as_null_and_reopens_at_the_breakpoint_default(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
    chapter_project: Project,
) -> None:
    path = tmp_path / "workspace.json"
    first = _remembered(qtbot, path, DESKTOP, chapter_project)
    assert first.layout_state().column_width is None

    first.close()
    state = read_state(path)
    assert state is not None
    assert state.column_width is None
    assert json.loads(path.read_text(encoding="utf-8"))["column_width"] is None

    second = _remembered(qtbot, path, DESKTOP, chapter_project)
    assert second.splitter.sizes()[2] == COLUMN_DEFAULT_WIDE
    assert second._column_dragged is False
    _resize(second, NARROW)
    assert second.splitter.sizes()[2] == COLUMN_DEFAULT_NARROW


def test_layout_state_reports_a_dragged_columns_width(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    window = _remembered(qtbot, tmp_path / "workspace.json")
    splitter = window.splitter
    _drag_column_to(window, splitter.width() - splitter.handleWidth() - DRAGGED)
    assert splitter.sizes()[2] == DRAGGED
    assert window.layout_state().column_width == DRAGGED


# --- AC-4's last clause: unarmed windows touch nothing; a failed write never blocks --


def test_a_workspace_never_armed_reads_and_writes_no_file(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    appdata = Path(os.environ["APPDATA"])
    assert not (appdata / "mangatl").exists()
    window = Workspace()
    qtbot.addWidget(window)
    with qtbot.waitExposed(window):
        window.show()
    _settle()
    window.close()
    _settle()
    assert not (appdata / "mangatl").exists()


def test_a_workspace_never_armed_ignores_a_state_file_at_the_real_path(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    path = _write_raw(
        app_paths.workspace_state_path(), _raw(width=1500, height=900, column_width=400)
    )
    before = path.read_bytes()
    window = Workspace()
    qtbot.addWidget(window)
    with qtbot.waitExposed(window):
        window.show()
    _settle()
    assert _size(window) == (1100, 720)
    assert window._column_dragged is False

    window.close()
    _settle()
    assert path.read_bytes() == before


def test_a_state_path_that_cannot_be_written_never_stops_the_window_closing(
    qtbot,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    window = _remembered(qtbot, blocker / "workspace.json")

    with qtbot.waitSignal(window.closed, timeout=5_000):
        assert window.close() is True

    assert not window.isVisible()
    assert blocker.read_text(encoding="utf-8") == "not a directory"


# =============================================================================
# Block 4 - through mangatl.app.build_window, with the DEFAULT work area.
# =============================================================================

#: Measured: the offscreen platform's `availableGeometry()` is (0, 0, 800, 800).
#: A file of 1500 x 900 at (10, 20) is clamped against it (A-1): 800 cannot
#: hold 1100, so the size is the minimum and x the area's left edge; y = 20
#: already lies in [0, 800 - 720].
BUILT_FILE = {"width": 1500, "height": 900, "x": 10, "y": 20, "column_width": 400}
BUILT_OPENS = _state(width=1100, height=720, x=0, y=20, maximized=False, column_width=400)


@pytest.fixture
def chapter_folder(tmp_path: Path) -> Path:
    """A chapter folder whose sibling `.mtproj` project exists, CLOSED."""
    folder = tmp_path / "chapter"
    folder.mkdir()
    pages = []
    for ordinal, (filename, size) in enumerate(PAGES):
        assert _image(size).save(str(folder / filename), "PNG")
        pages.append(
            Page(
                ordinal=ordinal,
                filename=filename,
                width=size.width(),
                height=size.height(),
                sha256=str(ordinal) * 64,
            )
        )
    chapter = Chapter(source_dir=folder, pages=tuple(pages))
    with create_project(chapter, tmp_path / "chapter.mtproj"):
        pass
    return folder


@pytest.mark.usefixtures("every_opened_project_is_closed", "every_built_window_is_closed")
def test_the_app_applies_the_state_file_beside_settings_json_and_rewrites_it_on_close(
    qtbot,  # type: ignore[no-untyped-def]
    chapter_folder: Path,
) -> None:
    path = _write_raw(app_paths.workspace_state_path(), _raw(**BUILT_FILE))
    assert path == Path(os.environ["APPDATA"]) / "mangatl" / "workspace.json"

    window = app_module.build_window([str(chapter_folder)])
    qtbot.addWidget(window)
    assert isinstance(window, Workspace)
    with qtbot.waitExposed(window):
        window.show()
    _settle()

    assert _size(window) == (1100, 720)
    assert _pos(window) == (0, 20)
    assert window.splitter.sizes()[2] == 400

    window.close()
    _settle()

    assert read_state(path) == BUILT_OPENS


@pytest.mark.usefixtures("every_opened_project_is_closed", "every_built_window_is_closed")
def test_the_app_arms_remembering_after_loading_the_chapter(
    qtbot,  # type: ignore[no-untyped-def]
    chapter_folder: Path,
) -> None:
    # `load_chapter` resets `_column_dragged` (MT-048 block 4): had
    # `remember_layout` run first, the remembered drag would be forgotten here.
    _write_raw(app_paths.workspace_state_path(), _raw(**BUILT_FILE))

    window = app_module.build_window([str(chapter_folder)])
    qtbot.addWidget(window)

    assert isinstance(window, Workspace)
    assert window._column_dragged is True
    assert window.page_strip.currentRow() == 0


@pytest.mark.usefixtures("every_opened_project_is_closed", "every_built_window_is_closed")
def test_the_app_with_no_state_file_opens_at_the_first_run_size_and_writes_one_on_close(
    qtbot,  # type: ignore[no-untyped-def]
    chapter_folder: Path,
) -> None:
    path = app_paths.workspace_state_path()
    assert not path.exists()

    window = app_module.build_window([str(chapter_folder)])
    qtbot.addWidget(window)
    with qtbot.waitExposed(window):
        window.show()
    _settle()
    # first_run_size((0, 0, 800, 800), (1100, 720)) == (1100, 720): AC-3.
    assert _size(window) == (1100, 720)
    assert window._column_dragged is False

    window.close()
    _settle()

    state = read_state(path)
    assert state is not None
    assert (state.width, state.height, state.maximized, state.column_width) == (
        1100,
        720,
        False,
        None,
    )
