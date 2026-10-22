"""MT-087 AC-1..AC-4: the full-width page strip shows a thumbnail of every page.

**Oracle partition (story `## Contract`).**

- *Settled*, read out and never derived: `THUMBNAIL_WIDTH == 72` and the row's
  `space.3` either side (`tokens_gen.SPACE_S3 == 12`: 12 + 72 + 12 = 96,
  `layout.md` §"Review workspace"); `THUMBNAIL_BATCH == 4` (PO-2); the
  placeholder tokens `color.surface.sunken` / `color.border.subtle` with the
  hairline width (PO-4, `components.md` §`PageStrip`); 1900 / 1100 px.
- *Mechanical*, pinned exactly: `thumbnail_size(w, h) ==
  QSize(72, max(1, round(72 * h / w)))` from the page's STORED dimensions;
  `decode_thumbnail` returns an image of exactly the size asked for, or `None`;
  the three states `pending` / `shown` / `failed`; the decode counter's
  arithmetic in AC-1/3/4; the index as the row text in both modes and the
  filename as the tooltip (PO-1); MT-015 AC-6's recovery.
- *Oracle-free*: none (PO-2 replaced the wall-clock bound with a mechanism).

**Decodes are counted, not timed.** `_Decodes` replaces
`mangatl.ui.workspace.decode_thumbnail` (the Contract makes the strip look the
helper up on that module) with a wrapper around the real
`mangatl.ui.thumbnail.decode_thumbnail` that records each path it is asked
for. Its own negative control is
`test_the_decode_counter_counts_a_direct_call_through_the_workspace_module`.

**Waiting is by state, never by clock.** `qtbot.waitUntil(lambda:
strip.pending_thumbnails() == 0, timeout=10_000)` is an upper bound on a
state. Where a test asserts that nothing happens, it runs a fixed number of
`QApplication.processEvents()` passes - `_IDLE_PASSES`, four times what a
running queue needs to drain - so "nothing decoded" means "nothing decoded in
more event-loop passes than the work takes", not "nothing within N ms". Measured
in RED (scratch script, not this file): a repeating zero-interval `QTimer`
fires exactly once per `processEvents()` pass under `QT_QPA_PLATFORM=offscreen`
on Windows (20 of 20 passes), and a 10-page queue in batches of 4 reads
0, 4, 8, 10 across passes.

**Pages are flat colours,** a different hue each, so a thumbnail's centre pixel
names the page it was decoded from. Two aspects (120 x 180 and 180 x 120), so
`thumbnail_size` is exercised both ways through the strip.

**RED.** `mangatl.ui.thumbnail` does not exist, and neither do
`THUMBNAIL_BATCH`, `PageStrip.set_thumbnails`, `thumbnail`, `thumbnail_state`
or `pending_thumbnails`: the file fails at collection and no assertion in it,
the counter's control included, has run. Expected values are in the story's
handoff.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from importlib.resources import files
from itertools import pairwise
from pathlib import Path

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from mangatl.domain.page import Chapter, Page
from mangatl.domain.page_status import PageProgress
from mangatl.store.project import Project, create_project
from mangatl.ui import tokens_gen
from mangatl.ui.canvas import FAILED, LOADED
from mangatl.ui.thumbnail import THUMBNAIL_WIDTH, decode_thumbnail, thumbnail_size
from mangatl.ui.workspace import STRIP_WIDTH, THUMBNAIL_BATCH, PageStrip, Workspace

# --- Settled ---------------------------------------------------------------------
DESIGN_THUMBNAIL_WIDTH = 72  # layout.md: "72px thumbnail + space.3 either side"
DESIGN_BATCH = 4  # PO-2
DESIGN_DEFAULT_AREA = QSize(72, 96)  # block 3: the area before set_thumbnails
WIDE = 1900
NARROW = 1100
WIDE_TOO = 1500  # still >= 1440: a resize within the wide regime
HEIGHT = 720

# --- The fixtures' pages ---------------------------------------------------------
TALL = (120, 180)  # 2:3 -> 72 x 108
BROAD = (180, 120)  # 3:2 -> 72 x 48
JUNK_BYTES = b"these bytes are not a PNG, or any image at all"
PENDING = PageProgress("pending", 0, 0, 0)

#: Enough passes for a running queue to drain several times over.
_IDLE_PASSES = 40


def _colour(i: int) -> QColor:
    """Page i's flat fill: a different hue per page (10 distinct for i < 10)."""
    return QColor.fromHsv((36 * i) % 360, 200, 200)


def _write_png(path: Path, size: tuple[int, int], colour: QColor) -> None:
    image = QImage(QSize(*size), QImage.Format.Format_RGB32)
    image.fill(colour)
    assert image.save(str(path), "PNG"), f"could not write {path}"


@dataclass(frozen=True)
class _Pages:
    source: Path
    filenames: tuple[str, ...]
    sizes: tuple[tuple[int, int], ...]  # the STORED (width, height) of each page
    colours: tuple[QColor | None, ...]  # None for the junk page

    def path(self, i: int) -> Path:
        return self.source / self.filenames[i]


def _pages(source: Path, specs: Sequence[tuple[tuple[int, int], bool]]) -> _Pages:
    """One file per spec, named 001.png...; `(size, decodable)`."""
    source.mkdir()
    names, sizes, colours = [], [], []
    for i, (size, decodable) in enumerate(specs):
        name = f"{i + 1:03d}.png"
        if decodable:
            _write_png(source / name, size, _colour(i))
            colours.append(_colour(i))
        else:
            (source / name).write_bytes(JUNK_BYTES)
            colours.append(None)
        names.append(name)
        sizes.append(size)
    return _Pages(source, tuple(names), tuple(sizes), tuple(colours))


def _project(pages: _Pages, at: Path) -> Project:
    chapter = Chapter(
        source_dir=pages.source,
        pages=tuple(
            Page(ordinal=i, filename=n, width=w, height=h, sha256=f"{i % 10}" * 64)
            for i, (n, (w, h)) in enumerate(zip(pages.filenames, pages.sizes, strict=True))
        ),
    )
    return create_project(chapter, at)


@pytest.fixture
def three(tmp_path: Path) -> _Pages:
    """A tall page, a broad page and a junk-bytes `*.png` (MT-015 AC-6's shape)."""
    return _pages(tmp_path / "chapter", [(TALL, True), (BROAD, True), (TALL, False)])


GOOD_TALL, GOOD_BROAD, JUNK = 0, 1, 2


@pytest.fixture
def three_project(three: _Pages, tmp_path: Path) -> Iterator[Project]:
    with _project(three, tmp_path / "chapter.mtproj") as project:
        yield project


TEN = 10  # more than two batches, so batching is observable


@pytest.fixture
def ten(tmp_path: Path) -> _Pages:
    """Ten decodable pages, alternating tall and broad."""
    return _pages(
        tmp_path / "chapter", [((TALL if i % 2 == 0 else BROAD), True) for i in range(TEN)]
    )


@pytest.fixture
def ten_project(ten: _Pages, tmp_path: Path) -> Iterator[Project]:
    with _project(ten, tmp_path / "chapter.mtproj") as project:
        yield project


# --- The decode counter --------------------------------------------------------


class _Decodes:
    """Counts calls to `mangatl.ui.workspace.decode_thumbnail`, passing each
    through to the real `mangatl.ui.thumbnail.decode_thumbnail`."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.paths: list[Path] = []

        def counting(path: Path, size: QSize) -> QImage | None:
            self.paths.append(Path(path))
            return decode_thumbnail(path, size)

        monkeypatch.setattr("mangatl.ui.workspace.decode_thumbnail", counting)

    @property
    def count(self) -> int:
        return len(self.paths)

    def of(self, path: Path) -> int:
        return self.paths.count(path)


# --- Qt helpers -----------------------------------------------------------------


def _sheet() -> str:
    return files("mangatl.ui").joinpath("theme.qss").read_text(encoding="utf-8")


THEME_IN = Path(__file__).resolve().parents[2] / "docs" / "wiki" / "design" / "theme.qss.in"


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


def _idle() -> None:
    for _ in range(_IDLE_PASSES):
        QApplication.processEvents()


def _row(strip: PageStrip, row: int) -> QWidget:
    widget = strip.itemWidget(strip.item(row))
    assert widget is not None, f"strip row {row} has no item widget"
    return widget


def _thumb(strip: PageStrip, row: int) -> QLabel:
    found = _row(strip, row).findChild(QLabel, "pageThumbnail")
    assert found is not None, f"strip row {row}'s widget has no QLabel named pageThumbnail"
    return found


def _label(strip: PageStrip, row: int) -> QLabel:
    found = _row(strip, row).findChild(QLabel, "pageLabel")
    assert found is not None, f"strip row {row}'s widget has no QLabel named pageLabel"
    return found


def _visible(strip: PageStrip) -> list[bool]:
    return [_thumb(strip, i).isVisibleTo(strip) for i in range(strip.count())]


def _centre(pixmap: QPixmap) -> str:
    image = pixmap.toImage()
    return image.pixelColor(image.width() // 2, image.height() // 2).name()


def _drain(qtbot, strip: PageStrip) -> None:  # type: ignore[no-untyped-def]
    qtbot.waitUntil(lambda: strip.pending_thumbnails() == 0, timeout=10_000)
    _settle()


def _strip(qtbot) -> PageStrip:  # type: ignore[no-untyped-def]
    strip = PageStrip()
    qtbot.addWidget(strip)
    strip.setStyleSheet(_sheet())
    strip.resize(strip.width(), 600)
    with qtbot.waitExposed(strip):
        strip.show()
    _settle()
    return strip


def _load(strip: PageStrip, pages: _Pages) -> None:
    strip.set_pages(pages.filenames, [PENDING] * len(pages.filenames))
    strip.set_thumbnails(pages.source, pages.sizes)


def _open(qtbot, width: int) -> Workspace:  # type: ignore[no-untyped-def]
    window = Workspace()
    qtbot.addWidget(window)
    window.setStyleSheet(_sheet())
    window.resize(width, HEIGHT)
    with qtbot.waitExposed(window):
        window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    _settle()
    return window


def _resize(window: Workspace, width: int) -> None:
    window.resize(width, HEIGHT)
    _settle()
    assert window.width() == width, "the window did not settle at the requested width"


# =============================================================================
# Block 1: the settled numbers and the decode helper
# =============================================================================


def test_the_thumbnail_is_72_px_wide_with_space_3_either_side_filling_the_96_px_strip() -> None:
    assert THUMBNAIL_WIDTH == DESIGN_THUMBNAIL_WIDTH
    assert tokens_gen.SPACE_S3 == 12
    assert tokens_gen.SPACE_S3 + THUMBNAIL_WIDTH + tokens_gen.SPACE_S3 == STRIP_WIDTH == 96


def test_thumbnails_decode_in_batches_of_four() -> None:
    assert THUMBNAIL_BATCH == DESIGN_BATCH


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (600, 900, QSize(72, 108)),  # 2:3
        (900, 600, QSize(72, 48)),  # 3:2
        (120, 180, QSize(72, 108)),  # the fixture's tall page
        (180, 120, QSize(72, 48)),  # the fixture's broad page
        (7, 10, QSize(72, 103)),  # 102.857... rounds to 103, not truncated to 102
        (72, 72, QSize(72, 72)),
        (10_000, 1, QSize(72, 1)),  # 0.0072 rounds to 0: clamped to 1
    ],
    ids=["2x3", "3x2", "tall", "broad", "rounds", "square", "degenerate"],
)
def test_thumbnail_size_is_72_wide_with_the_stored_pages_aspect(
    width: int, height: int, expected: QSize
) -> None:
    assert thumbnail_size(width, height) == expected


def test_decoding_a_real_png_gives_an_image_of_exactly_the_asked_size_and_its_colour(
    three: _Pages,
) -> None:
    size = thumbnail_size(*TALL)
    image = decode_thumbnail(three.path(GOOD_TALL), size)
    assert isinstance(image, QImage)
    assert image.size() == size == QSize(72, 108)
    assert image.pixelColor(36, 54).name() == three.colours[GOOD_TALL].name()  # type: ignore[union-attr]


def test_decoding_gives_exactly_the_asked_size_even_when_it_is_not_the_files_aspect(
    three: _Pages,
) -> None:
    """The size comes from the store (MT-062's precedent); the decode does not
    second-guess it by keeping the file's own aspect (that would be 32 x 48)."""
    image = decode_thumbnail(three.path(GOOD_TALL), QSize(72, 48))
    assert image is not None
    assert image.size() == QSize(72, 48)


@pytest.mark.parametrize("case", ["junk", "empty", "missing", "directory"])
def test_bytes_that_do_not_decode_give_none_rather_than_raising(three: _Pages, case: str) -> None:
    if case == "junk":
        path = three.path(JUNK)
    elif case == "empty":
        path = three.source / "empty.png"
        path.write_bytes(b"")
    elif case == "missing":
        path = three.source / "not-there.png"
    else:
        path = three.source
    assert decode_thumbnail(path, QSize(72, 108)) is None


# =============================================================================
# Block 4: the placeholder in the sheet (PO-4)
# =============================================================================


def test_the_generated_sheet_grounds_the_thumbnail_area_as_the_placeholder() -> None:
    rules = re.findall(r"QLabel#pageThumbnail\s*\{([^}]*)\}", _sheet())
    assert len(rules) == 1, f"QLabel#pageThumbnail rules in theme.qss: {rules}"
    declarations = sorted(d.strip() for d in rules[0].split(";") if d.strip())
    assert declarations == sorted(
        [
            f"background-color: {tokens_gen.TOKENS['color.surface.sunken']}",
            f"border: {tokens_gen.TOKENS['border-width.hairline']}px solid "
            f"{tokens_gen.TOKENS['color.border.subtle']}",
        ]
    )


def test_the_sheet_source_names_the_placeholder_by_token_never_by_value() -> None:
    source = THEME_IN.read_text(encoding="utf-8")
    assert re.search(
        r"QLabel#pageThumbnail\s*\{\s*"
        r"background-color:\s*@\{color\.surface\.sunken\}\s*;\s*"
        r"border:\s*@\{border-width\.hairline\}px solid @\{color\.border\.subtle\}\s*;\s*\}",
        source,
    ), "theme.qss.in has no token-spelled QLabel#pageThumbnail rule"


# =============================================================================
# The instrument
# =============================================================================


def test_the_decode_counter_counts_a_direct_call_through_the_workspace_module(
    three: _Pages, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative control for every count below: the wrapper sees a call made the
    way the strip is contracted to make it, and passes the real result through."""
    import mangatl.ui.workspace as workspace_module

    decodes = _Decodes(monkeypatch)
    image = workspace_module.decode_thumbnail(three.path(GOOD_BROAD), QSize(72, 48))
    assert decodes.count == 1
    assert decodes.paths == [three.path(GOOD_BROAD)]
    assert image is not None and image.size() == QSize(72, 48)


# =============================================================================
# Blocks 2-3 on a standalone strip: AC-1, AC-2
# =============================================================================


def test_before_set_thumbnails_each_rows_thumbnail_area_is_72_by_96_and_empty(
    qtbot, three: _Pages
) -> None:  # type: ignore[no-untyped-def]
    strip = _strip(qtbot)
    strip.set_pages(three.filenames, [PENDING] * 3)
    _settle()

    for i in range(3):
        thumb = _thumb(strip, i)
        assert (thumb.minimumSize(), thumb.maximumSize()) == (
            DESIGN_DEFAULT_AREA,
            DESIGN_DEFAULT_AREA,
        ), i
        assert thumb.pixmap().isNull(), i
    assert strip.pending_thumbnails() == 0


def test_set_thumbnails_sizes_every_area_from_the_stored_size_and_queues_before_decoding(
    qtbot, three: _Pages, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Block 2: the areas are sized NOW, so rows do not reflow when an image
    lands; nothing is decoded inside the call."""
    strip = _strip(qtbot)
    decodes = _Decodes(monkeypatch)
    _load(strip, three)

    assert decodes.count == 0
    assert strip.pending_thumbnails() == 3
    for i in range(3):
        size = thumbnail_size(*three.sizes[i])
        thumb = _thumb(strip, i)
        assert (thumb.minimumSize(), thumb.maximumSize()) == (size, size), i
        assert strip.thumbnail_state(i) == "pending", i
        assert thumb.property("state") == "pending", i
        assert strip.thumbnail(i) is None, i


def test_at_96_px_every_decodable_row_shows_its_own_page_at_its_thumbnail_size(
    qtbot, three: _Pages, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """AC-1: shown, sized from the stored dimensions, the page's own pixels."""
    strip = _strip(qtbot)
    decodes = _Decodes(monkeypatch)
    _load(strip, three)
    _drain(qtbot, strip)

    assert not strip.is_rail
    for i in (GOOD_TALL, GOOD_BROAD):
        size = thumbnail_size(*three.sizes[i])
        thumb = _thumb(strip, i)
        pixmap = strip.thumbnail(i)
        colour = three.colours[i].name()  # type: ignore[union-attr]
        assert strip.thumbnail_state(i) == "shown", i
        assert thumb.property("state") == "shown", i
        assert thumb.isVisibleTo(strip), i
        assert thumb.size() == size, i
        assert isinstance(pixmap, QPixmap), i
        assert pixmap.size() == size, i
        assert _centre(pixmap) == colour, f"row {i} shows another page's pixels"
        assert thumb.pixmap().size() == size, i
        assert _centre(thumb.pixmap()) == colour, f"row {i}'s label shows another page"
    assert thumbnail_size(*three.sizes[GOOD_TALL]) == QSize(72, 108)
    assert thumbnail_size(*three.sizes[GOOD_BROAD]) == QSize(72, 48)
    assert sorted(decodes.paths) == sorted(three.path(i) for i in range(3)), "decoded once each"


def test_the_thumbnail_takes_its_size_from_the_stored_dimensions_not_the_file(
    qtbot, three: _Pages
) -> None:  # type: ignore[no-untyped-def]
    """MT-062's precedent: a tall file stored as broad is shown 72 x 48."""
    strip = _strip(qtbot)
    strip.set_pages(three.filenames[:1], [PENDING])
    strip.set_thumbnails(three.source, [BROAD])
    _drain(qtbot, strip)

    pixmap = strip.thumbnail(0)
    assert pixmap is not None
    assert pixmap.size() == QSize(72, 48)
    assert _thumb(strip, 0).size() == QSize(72, 48)


def test_at_96_px_the_rows_contents_margins_are_space_3_either_side(qtbot, three: _Pages) -> None:  # type: ignore[no-untyped-def]
    """Block 3: 12 + 72 + 12. Widget and layout margins are summed, so either
    is GREEN's choice."""
    strip = _strip(qtbot)
    _load(strip, three)
    _drain(qtbot, strip)

    for i in range(3):
        row = _row(strip, i)
        layout = row.layout()
        assert layout is not None, i
        left = row.contentsMargins().left() + layout.contentsMargins().left()
        right = row.contentsMargins().right() + layout.contentsMargins().right()
        assert (left, right) == (tokens_gen.SPACE_S3, tokens_gen.SPACE_S3), i


def test_the_row_text_is_the_index_in_both_modes_and_the_filename_is_the_tooltip(
    qtbot, three: _Pages
) -> None:  # type: ignore[no-untyped-def]
    """PO-1: glyph + index under the thumbnail; the filename is the tooltip and
    stays in the accessible name (MT-086 block 3, unchanged)."""
    strip = _strip(qtbot)
    _load(strip, three)
    _drain(qtbot, strip)
    indices = ["1", "2", "3"]
    names = [f"Page {i + 1} of 3, {n}, not translated yet" for i, n in enumerate(three.filenames)]

    def seen() -> tuple[list[str], list[str], list[str], list[str]]:
        return (
            [strip.item(i).text() for i in range(3)],
            [_label(strip, i).text() for i in range(3)],
            [strip.item(i).toolTip() for i in range(3)],
            [strip.item(i).data(Qt.ItemDataRole.AccessibleTextRole) for i in range(3)],
        )

    full = seen()
    strip.set_rail(True)
    _settle()
    rail = seen()
    strip.set_rail(False)
    _settle()
    full_again = seen()

    expected = (indices, indices, list(three.filenames), names)
    assert full == expected
    assert rail == expected
    assert full_again == expected


def test_an_undecodable_page_keeps_the_placeholder_and_is_tried_exactly_once(
    qtbot, three: _Pages, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """AC-2: failed, no pixmap, the area still shown, never retried - not by
    more event-loop passes and not by crossing into the rail and back."""
    strip = _strip(qtbot)
    decodes = _Decodes(monkeypatch)
    _load(strip, three)
    _drain(qtbot, strip)
    strip.set_rail(True)
    _settle()
    strip.set_rail(False)
    _idle()

    thumb = _thumb(strip, JUNK)
    assert strip.thumbnail_state(JUNK) == "failed"
    assert thumb.property("state") == "failed"
    assert strip.thumbnail(JUNK) is None
    assert thumb.pixmap().isNull(), "the failed row shows a pixmap"
    assert thumb.isVisibleTo(strip), "the placeholder is not shown"
    assert thumb.size() == thumbnail_size(*three.sizes[JUNK])
    assert decodes.of(three.path(JUNK)) == 1, f"junk page tried {decodes.of(three.path(JUNK))}x"
    assert decodes.count == 3
    assert strip.pending_thumbnails() == 0


def test_crossing_into_the_rail_hides_every_thumbnail_and_back_shows_the_same_ones(
    qtbot, three: _Pages, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    strip = _strip(qtbot)
    decodes = _Decodes(monkeypatch)
    _load(strip, three)
    _drain(qtbot, strip)
    keys = [strip.thumbnail(i).cacheKey() for i in (GOOD_TALL, GOOD_BROAD)]  # type: ignore[union-attr]
    assert _visible(strip) == [True, True, True]

    strip.set_rail(True)
    _idle()
    in_rail = (_visible(strip), [strip.thumbnail_state(i) for i in range(3)])
    strip.set_rail(False)
    _idle()

    assert in_rail == ([False, False, False], ["shown", "shown", "failed"])
    assert _visible(strip) == [True, True, True]
    assert [strip.thumbnail(i).cacheKey() for i in (GOOD_TALL, GOOD_BROAD)] == keys  # type: ignore[union-attr]
    assert decodes.count == 3


def test_set_thumbnails_in_the_rail_queues_every_page_and_decodes_none_until_the_full_strip(
    qtbot, three: _Pages, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    strip = _strip(qtbot)
    strip.set_rail(True)
    decodes = _Decodes(monkeypatch)
    _load(strip, three)
    _idle()

    assert (decodes.count, strip.pending_thumbnails()) == (0, 3)
    assert [strip.thumbnail_state(i) for i in range(3)] == ["pending"] * 3
    assert _visible(strip) == [False, False, False]

    strip.set_rail(False)
    _drain(qtbot, strip)
    assert decodes.count == 3
    assert [strip.thumbnail_state(i) for i in range(3)] == ["shown", "shown", "failed"]


def test_crossing_into_the_rail_mid_queue_stops_decoding_and_the_full_strip_resumes_it(
    qtbot, ten: _Pages, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """AC-3 / block 2 (DV-2's target): `set_rail(True)` stops a RUNNING queue;
    `set_rail(False)` restarts it where it stopped, decoding no page twice."""
    strip = _strip(qtbot)
    decodes = _Decodes(monkeypatch)
    _load(strip, ten)
    for _ in range(_IDLE_PASSES):
        QApplication.processEvents()
        if decodes.count > 0:
            break
    started = decodes.count

    strip.set_rail(True)
    _idle()
    in_rail = (decodes.count, strip.pending_thumbnails())
    strip.set_rail(False)
    _drain(qtbot, strip)

    assert 0 < started < TEN, f"the queue had not started, or finished, in one pass: {started}"
    assert in_rail == (started, TEN - started), "the rail kept decoding"
    assert decodes.paths == [ten.path(i) for i in range(TEN)], "a page decoded twice, or skipped"


def test_set_pages_forgets_the_thumbnails_and_the_queue_and_the_next_chapter_decodes_again(
    qtbot, three: _Pages, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Block 2: cached for the life of the chapter - until the next set_pages."""
    strip = _strip(qtbot)
    decodes = _Decodes(monkeypatch)
    strip.set_pages(three.filenames, [PENDING] * 3)
    strip.set_thumbnails(three.source, three.sizes)
    strip.set_pages(three.filenames, [PENDING] * 3)  # before a single pass
    _idle()

    assert (decodes.count, strip.pending_thumbnails()) == (0, 0)
    assert [strip.thumbnail(i) for i in range(3)] == [None, None, None]

    strip.set_thumbnails(three.source, three.sizes)
    _drain(qtbot, strip)
    strip.set_pages(three.filenames, [PENDING] * 3)
    _idle()
    after_reset = (decodes.count, [strip.thumbnail(i) for i in range(3)])
    strip.set_thumbnails(three.source, three.sizes)
    _drain(qtbot, strip)

    assert after_reset == (3, [None, None, None])
    assert decodes.count == 6
    assert [strip.thumbnail_state(i) for i in range(3)] == ["shown", "shown", "failed"]


# =============================================================================
# Through Workspace.load_chapter (block 5): AC-1..AC-4
# =============================================================================


def test_load_chapter_returns_before_any_thumbnail_is_decoded(
    qtbot, ten_project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """AC-4 (DV-1's target): the chapter opens without waiting on thumbnails."""
    window = _open(qtbot, WIDE)
    decodes = _Decodes(monkeypatch)
    window.load_chapter(ten_project)

    assert decodes.count == 0
    assert window.page_strip.pending_thumbnails() == TEN


def test_thumbnails_decode_at_most_four_per_event_loop_pass_until_every_page_is_done(
    qtbot, ten_project: Project, ten: _Pages, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """AC-4: monotone, at most THUMBNAIL_BATCH per `processEvents` pass, the
    queue shrinking by exactly what was decoded, ending at the page count."""
    window = _open(qtbot, WIDE)
    strip = window.page_strip
    decodes = _Decodes(monkeypatch)
    window.load_chapter(ten_project)

    counts, pending = [decodes.count], [strip.pending_thumbnails()]
    for _ in range(_IDLE_PASSES):
        QApplication.processEvents()
        counts.append(decodes.count)
        pending.append(strip.pending_thumbnails())
        if counts[-1] == TEN:
            break
    steps = [b - a for a, b in pairwise(counts)]

    assert counts[0] == 0
    assert counts[-1] == TEN, f"decodes per pass: {counts}"
    assert all(0 <= s <= DESIGN_BATCH for s in steps), f"decodes per pass: {counts}"
    assert pending == [TEN - c for c in counts], f"pending {pending} against decoded {counts}"
    assert decodes.paths == [ten.path(i) for i in range(TEN)], "not in ordinal order"


def test_at_1900_px_every_page_is_decoded_once_and_shown_at_its_stored_aspect(
    qtbot, ten_project: Project, ten: _Pages, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """AC-1 through load_chapter: the stored (width, height) reach the strip in
    that order (the alternating aspects catch a swap)."""
    window = _open(qtbot, WIDE)
    strip = window.page_strip
    decodes = _Decodes(monkeypatch)
    window.load_chapter(ten_project)
    _drain(qtbot, strip)

    assert decodes.count == TEN
    assert [strip.thumbnail_state(i) for i in range(TEN)] == ["shown"] * TEN
    assert _visible(strip) == [True] * TEN
    assert [strip.thumbnail(i).size() for i in range(TEN)] == [  # type: ignore[union-attr]
        thumbnail_size(*ten.sizes[i]) for i in range(TEN)
    ]
    assert [_centre(strip.thumbnail(i)) for i in range(TEN)] == [  # type: ignore[arg-type]
        ten.colours[i].name()  # type: ignore[union-attr]
        for i in range(TEN)
    ]


def test_selecting_rows_repolishing_and_resizing_within_the_wide_regime_decode_nothing_more(
    qtbot, ten_project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """AC-1: once per page."""
    window = _open(qtbot, WIDE)
    strip = window.page_strip
    decodes = _Decodes(monkeypatch)
    window.load_chapter(ten_project)
    _drain(qtbot, strip)
    assert decodes.count == TEN

    for row in (3, 0, 9, 5):
        strip.setCurrentRow(row)
        _settle()
    strip.set_rail(False)  # a second set_rail(False): already the full strip
    window.setStyleSheet(_sheet())  # re-polish
    _resize(window, WIDE_TOO)
    _resize(window, WIDE)
    _idle()

    assert decodes.count == TEN
    assert strip.pending_thumbnails() == 0
    assert _visible(strip) == [True] * TEN


def test_below_1440_loading_a_chapter_decodes_no_thumbnail_and_shows_none(
    qtbot, ten_project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """AC-3 (DV-2's target)."""
    window = _open(qtbot, NARROW)
    strip = window.page_strip
    decodes = _Decodes(monkeypatch)
    window.load_chapter(ten_project)
    _idle()

    assert strip.is_rail
    assert decodes.count == 0
    assert strip.pending_thumbnails() == TEN
    assert [strip.thumbnail_state(i) for i in range(TEN)] == ["pending"] * TEN
    assert _visible(strip) == [False] * TEN


def test_crossing_up_decodes_every_page_crossing_back_hides_them_and_up_again_reshows_them(
    qtbot, ten_project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """AC-3: decoded on the way up, hidden but kept on the way down, shown again
    with the counter unchanged."""
    window = _open(qtbot, NARROW)
    strip = window.page_strip
    decodes = _Decodes(monkeypatch)
    window.load_chapter(ten_project)
    _idle()
    assert decodes.count == 0

    _resize(window, WIDE)
    _drain(qtbot, strip)
    up = (decodes.count, _visible(strip))
    keys = [strip.thumbnail(i).cacheKey() for i in range(TEN)]  # type: ignore[union-attr]

    _resize(window, NARROW)
    _idle()
    down = (decodes.count, _visible(strip), [strip.thumbnail_state(i) for i in range(TEN)])
    kept = [strip.thumbnail(i).cacheKey() for i in range(TEN)]  # type: ignore[union-attr]

    _resize(window, WIDE)
    _idle()
    up_again = (decodes.count, _visible(strip))

    assert up == (TEN, [True] * TEN)
    assert down == (TEN, [False] * TEN, ["shown"] * TEN)
    assert kept == keys, "crossing down discarded the thumbnails"
    assert up_again == (TEN, [True] * TEN)
    assert [strip.thumbnail(i).cacheKey() for i in range(TEN)] == keys  # type: ignore[union-attr]


def test_with_an_undecodable_page_the_strip_still_opens_pages_both_ways(
    qtbot, three_project: Project, three: _Pages, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """AC-2 / MT-015 AC-6: the junk page's row is the placeholder, selecting it
    shows the page-failed state naming the file, and a good page still loads.
    Selecting decodes no thumbnail again."""
    window = _open(qtbot, WIDE)
    strip = window.page_strip
    decodes = _Decodes(monkeypatch)
    window.load_chapter(three_project)
    _drain(qtbot, strip)
    assert strip.thumbnail_state(JUNK) == "failed"

    strip.setCurrentRow(JUNK)
    _settle()
    canvas = window.page_canvas
    failed = (
        canvas.state(),
        canvas.page_item is None,
        three.filenames[JUNK] in canvas.message.text(),
    )

    strip.setCurrentRow(GOOD_TALL)
    _settle()

    assert failed == (FAILED, True, True)
    assert canvas.state() == LOADED
    assert canvas.page_item is not None
    assert canvas.page_item.pixmap().size() == QSize(*TALL)
    assert decodes.of(three.path(JUNK)) == 1
    assert decodes.count == 3
    assert [strip.thumbnail_state(i) for i in range(3)] == ["shown", "shown", "failed"]
