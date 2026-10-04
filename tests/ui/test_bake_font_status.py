"""MT-027 PO-2 in the window: a font fallback is a second sentence of the render status.

`Workspace._on_render_baked` states MT-066's sentence, `Rendered N pages to
{folder}.`, unchanged when `BakeReport.font_fallback == "none"`. Otherwise one
space and a second sentence follow it:

    Lettered in Shantell Sans because the font folder in settings could not be used: {detail}.

Both sentences go to `render_status` and to the live region, as the first
already does. No `ErrorBanner` (PO-2).

Driven the way a user drives it - Render pages, confirm - with `preview_bake`
and `bake_chapter` replaced at `mangatl.ui.bake`'s seam (MT-066 C-3) by plain
functions that return at once. `tests/ui/test_bake_render.py`'s rig is not
imported: that file's fakes block and record threads, which this needs neither.

RED: `BakeReport` takes no `font_*` fields, so building the report raises.
"""

from __future__ import annotations

from collections.abc import Iterator
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid

import mangatl.ui.bake as bake_ui
from mangatl.pipeline.bake import BakePreview, BakeReport, LineRef
from mangatl.store.intake import read_chapter
from mangatl.store.project import Project, create_project, open_project, project_dir_for
from mangatl.ui.bake_dialog import BakeConfirmDialog
from mangatl.ui.workspace import Workspace

WAIT_MS = 10_000

#: A detail as `resolve_faces` writes it (row 4); the window passes it through.
GLYPHS_DETAIL = r"C:\Users\me\Fonts\Comic\f1.ttf lacks U+2014, U+2026"
PATH_DETAIL = r"C:\Users\me\Fonts\Gone does not exist"


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


def _png() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (60, 80), (240, 240, 240)).save(buffer, format="PNG")
    return buffer.getvalue()


class _Chapter:
    def __init__(self, window: Workspace, output_dir: Path, reports: list[BakeReport]) -> None:
        self.window = window
        self.output_dir = output_dir
        self.reports = reports


@pytest.fixture
def chapter(qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[_Chapter]:  # type: ignore[no-untyped-def]
    """A two-page chapter open in a shown Workspace; the bake returns
    `reports[0]` (set by the test) at once."""
    source_dir = tmp_path / "ch 01"
    source_dir.mkdir()
    for i in range(2):
        (source_dir / f"{i + 1:02d}.png").write_bytes(_png())
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)):
        pass
    output_dir = source_dir.parent / (source_dir.name + "_en")
    preview = BakePreview(
        output_dir=output_dir,
        page_count=2,
        total_lines=3,
        unreviewed=(LineRef(page_ordinal=1, reading_index=0),),
        failed=(),
        overflowing=(),
    )
    reports: list[BakeReport] = []

    def fake_preview(project: Project) -> BakePreview:
        return preview

    def fake_bake(project: Project, out: Path) -> BakeReport:
        return reports[0]

    monkeypatch.setattr(bake_ui, "preview_bake", fake_preview)
    monkeypatch.setattr(bake_ui, "bake_chapter", fake_bake)
    project = open_project(project_dir_for(source_dir))
    window = Workspace()
    qtbot.addWidget(window)
    window.resize(1100, 720)
    with qtbot.waitExposed(window):
        window.show()
    window.activateWindow()
    window.load_chapter(project)
    _settle()
    try:
        yield _Chapter(window, output_dir, reports)
    finally:
        if isValid(window):
            dialog = getattr(window, "bake_dialog", None)
            if isinstance(dialog, QWidget) and isValid(dialog) and dialog.isVisible():
                dialog.close()
            window.close()
            _settle()
        project.__exit__(None, None, None)


def _render(qtbot, chapter: _Chapter) -> str:  # type: ignore[no-untyped-def]
    window = chapter.window
    window.render_button.click()
    qtbot.waitUntil(
        lambda: (
            isinstance(getattr(window, "bake_dialog", None), BakeConfirmDialog)
            and window.bake_dialog.isVisible()
        ),
        timeout=WAIT_MS,
    )
    _settle()
    QTest.mouseClick(window.bake_dialog.confirm_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: window.render_status.text() != "", timeout=WAIT_MS)
    return window.render_status.text()


def _report(**font: str) -> BakeReport:
    return BakeReport(
        pages_written=2, regions_empty=0, unreviewed_lines=1, pages_uncleaned=0, **font
    )


@pytest.mark.parametrize(
    ("reason", "detail"),
    [("missing_glyphs", GLYPHS_DETAIL), ("missing_path", PATH_DETAIL)],
    ids=["missing-glyphs", "missing-path"],
)
def test_a_font_fallback_adds_a_sentence_saying_shantell_was_used_and_why(
    qtbot,  # type: ignore[no-untyped-def]
    chapter: _Chapter,
    reason: str,
    detail: str,
) -> None:
    chapter.reports.append(
        _report(font_family="Shantell Sans", font_fallback=reason, font_detail=detail)
    )
    expected = (
        f"Rendered 2 pages to {chapter.output_dir}."
        " Lettered in Shantell Sans because the font folder in settings could not be used:"
        f" {detail}."
    )

    assert _render(qtbot, chapter) == expected
    assert chapter.window.live_region.text() == expected
    assert chapter.window.live_region.accessibleName() == expected


def test_with_a_valid_override_the_render_sentence_is_mt066s_unchanged(
    qtbot,  # type: ignore[no-untyped-def]
    chapter: _Chapter,
) -> None:
    # The family is not Shantell, and nothing went wrong: nothing extra is said.
    chapter.reports.append(
        _report(font_family="Boxy Lettering", font_fallback="none", font_detail="")
    )
    expected = f"Rendered 2 pages to {chapter.output_dir}."

    assert _render(qtbot, chapter) == expected
    assert chapter.window.live_region.text() == expected


def test_with_no_override_the_render_sentence_is_mt066s_unchanged(
    qtbot,  # type: ignore[no-untyped-def]
    chapter: _Chapter,
) -> None:
    chapter.reports.append(_report())
    expected = f"Rendered 2 pages to {chapter.output_dir}."

    assert _render(qtbot, chapter) == expected
    assert chapter.window.live_region.text() == expected
