"""`mangatl.pipeline.clean_stage`: the stage that stores one page's cleaned image (MT-065).

Covers AC-1 at the stage (the stored image is exactly what the injected cleaner
returned, and the cleaner was handed the page's own source bytes and its stored
regions), AC-2 (a page with no regions never reaches the cleaner and stores the
source scan, pixel-identical - on a PNG page **and** a JPEG one), AC-3 (the
`is_done` truth table, a second run that cleans nothing, and the resume that
cleans an already-translated chapter without re-detecting, re-reading or paying),
the stage half of AC-4 (re-detection makes the page not-done again), and C-5's
seam (the module imports nothing that reaches `onnxruntime`).

**The cleaner is a fake, and that is the design rather than a shortcut** (C-5).
`mangatl.pipeline` may not import `mangatl.clean` - `clean.inpaint` reaches
`onnxruntime` through `clean.session`, and rule 5 is transitive - so the stage
names its cleaner behind `PageCleaner` and `compose` binds the real one
(`test_compose.py`, AC-6). The composed cleaner's own oracle is MT-019's
`clean_page`, asserted in `test_clean_page_image.py`.

**The fake's output differs from its input** (`_RecordingCleaner`): it returns a
PNG of the page's own size in a fill no source page uses. A fake that returned
its input would make "the stored bytes are the cleaner's" and "the stored bytes
are the source's" the same observation, and DV-3's mutation - storing the source
in place of the cleaned page - would pass every AC-1 test.

**The page under test is ordinal 1, not 0**, for MT-035 DV-3's reason: a
`write_cleaned(0, ...)` typo is only visible on a page that is not page 0.

**Timing.** No `pytest-timeout` in this project, so there is no budget in this
file to size. Every page is at most 40x30; nothing here decodes a mask.
"""

from __future__ import annotations

import ast
import hashlib
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, get_args, get_origin

import pytest
from PIL import Image

from mangatl.domain.events import PageSkipped, RunEvent, StageFinished
from mangatl.domain.line import OcrResult
from mangatl.domain.region import RawRegion
from mangatl.domain.translation import TokenUsage, TranslationResult
from mangatl.pipeline.clean_stage import CleanStage, PageCleaner
from mangatl.pipeline.runner import RUN_FINISHED, run_chapter
from mangatl.pipeline.stage import PageContext
from mangatl.pipeline.stages import build_stages
from mangatl.store.intake import read_chapter
from mangatl.store.project import Project, create_project, project_dir_for

if TYPE_CHECKING:
    from mangatl.domain.glossary import PromptContext

# -- the fixture chapter -------------------------------------------------------

#: Three pages, three sizes, two formats. The JPEG is `conftest`'s 7x3 baseline
#: (C-8, AC-2: "pixel-identical" must not be satisfied by accident of format).
_PNG_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 30, 20),
    ("p2.png", 40, 30),
)
_JPEG_PAGE = "p3.jpg"
_JPEG_ORDINAL = 2
_PAGE_COUNT = len(_PNG_PAGES) + 1

#: The page AC-1 runs against - not ordinal 0 (module docstring).
_TARGET = 1
_TARGET_SIZE = (40, 30)

#: `CleanStage.name`, spelled out: `StageFinished.stage` carries it, and the
#: progress stepper ignores it by that exact name (PO-6).
_CLEAN = "clean"

#: A fill no source page uses, so the cleaner's output is never the source's.
_CLEANED_FILL = (9, 99, 199)


def _ring(x: int, y: int) -> tuple[tuple[int, int], ...]:
    return ((x, y), (x + 4, y), (x + 4, y + 4), (x, y + 4), (x, y))


def _size_of(image_bytes: bytes) -> tuple[int, int]:
    with Image.open(BytesIO(image_bytes)) as image:
        return image.size


def _pixels(image_bytes: bytes) -> bytes:
    """Decoded RGB pixels, the way C-2 says a consumer reads the column."""
    with Image.open(BytesIO(image_bytes)) as image:
        return image.convert("RGB").tobytes()


# -- doubles -------------------------------------------------------------------


class _RecordingCleaner:
    """A `PageCleaner` that records every call and returns a page-sized PNG
    that is never the page it was handed (module docstring)."""

    def __init__(self, png_bytes: Callable[..., bytes], *, size: tuple[int, int] | None = None):
        self._png_bytes = png_bytes
        self._size = size
        self.seen: list[tuple[bytes, tuple[RawRegion, ...]]] = []
        self.returned: list[bytes] = []

    @property
    def calls(self) -> int:
        return len(self.seen)

    def __call__(self, image_bytes: bytes, regions: Sequence[RawRegion]) -> bytes:
        self.seen.append((image_bytes, tuple(regions)))
        width, height = self._size if self._size is not None else _size_of(image_bytes)
        cleaned = self._png_bytes(width, height, _CLEANED_FILL)
        self.returned.append(cleaned)
        return cleaned


class _Detector:
    """A `PageDetector` that finds two regions on every page."""

    def __init__(self, mask: bytes) -> None:
        self.mask = mask
        self.calls = 0

    def __call__(self, image_bytes: bytes) -> Sequence[RawRegion]:
        self.calls += 1
        return (
            RawRegion(polygon=_ring(10, 0), mask=self.mask, confidence=1.0, kind="bubble"),
            RawRegion(polygon=_ring(0, 0), mask=self.mask, confidence=1.0, kind="bubble"),
        )


class _Transcriber:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, image_bytes: bytes, regions: Sequence[RawRegion]) -> Sequence[OcrResult]:
        self.calls += 1
        return tuple(OcrResult(text=f"ja-{index}") for index in range(len(regions)))


class _Translator:
    """`call=None`: the domain's "no API call was made", so no ledger row."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(
        self, image_bytes: bytes, results: Sequence[OcrResult], context: PromptContext
    ) -> TranslationResult:
        self.calls += 1
        return TranslationResult(
            lines={index: f"EN({result.text})" for index, result in enumerate(results)},
            usage=TokenUsage(0, 0, 0, 0),
            call=None,
            proposed_terms=(),
        )


# -- fixture -------------------------------------------------------------------


@dataclass(frozen=True)
class _Fixture:
    source_dir: Path
    db_path: Path
    project: Project
    mask: bytes
    run_id: int

    def context(self, ordinal: int) -> PageContext:
        page = next(page for page in self.project.pages() if page.ordinal == ordinal)
        return PageContext(
            project=self.project, page=page, run_id=self.run_id, emit=lambda _event: None
        )

    def source_bytes(self, ordinal: int) -> bytes:
        page = next(page for page in self.project.pages() if page.ordinal == ordinal)
        return (self.source_dir / page.filename).read_bytes()

    def regions(self, count: int) -> list[RawRegion]:
        """`count` regions, deliberately **not** in any sorted order, so the
        stage handing over anything but the stored sequence is visible."""
        return [
            RawRegion(
                polygon=_ring(4 * index, 2 * index),
                mask=self.mask,
                confidence=0.25 * (index + 1),
                kind="box" if index % 2 else "bubble",
            )
            for index in range(count)
        ]

    def raw(self, sql: str) -> list[tuple[object, ...]]:
        """Read the file with a plain `sqlite3` connection (`test_pipeline.py`'s
        observer convention)."""
        connection = sqlite3.connect(self.db_path)
        try:
            return connection.execute(sql).fetchall()
        finally:
            connection.close()

    def stored(self) -> dict[int, bytes]:
        return {
            int(ordinal): bytes(blob)  # type: ignore[arg-type]
            for ordinal, blob in self.raw(
                "SELECT page.ordinal, cleaned_page.image_blob"
                " FROM cleaned_page JOIN page ON page.id = cleaned_page.page_id"
            )
        }


def _open_run(project: Project) -> int:
    with project.transaction() as cursor:
        chapter_id = int(cursor.execute("SELECT id FROM chapter").fetchone()[0])
        cursor.execute(
            "INSERT INTO run (chapter_id, started_at) VALUES (?, ?)",
            (chapter_id, "2026-10-02T09:00:00+00:00"),
        )
        return int(cursor.execute("SELECT last_insert_rowid()").fetchone()[0])


@pytest.fixture
def fixture(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
    jpeg_7x3_bytes: bytes,
) -> Iterator[_Fixture]:
    source_dir = tmp_path / "scans"
    source_dir.mkdir()
    for index, (filename, width, height) in enumerate(_PNG_PAGES):
        (source_dir / filename).write_bytes(png_bytes(width, height, (index * 40, 7, 0)))
    (source_dir / _JPEG_PAGE).write_bytes(jpeg_7x3_bytes)

    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        yield _Fixture(
            source_dir=source_dir,
            db_path=project_dir_for(source_dir) / "project.db",
            project=project,
            mask=one_bit_png(*_TARGET_SIZE, [(0, 0, 4, 4)]),
            run_id=_open_run(project),
        )


def _never() -> bool:
    return False


def _snapshot(root: Path) -> dict[str, str | None]:
    return {
        str(entry.relative_to(root)): (
            hashlib.sha256(entry.read_bytes()).hexdigest() if entry.is_file() else None
        )
        for entry in sorted(root.rglob("*"))
    }


# -- the module's shape --------------------------------------------------------


def test_the_stage_is_exported_from_mangatl_pipeline_clean_stage_under_that_name(
    fixture: _Fixture, png_bytes: Callable[..., bytes]
) -> None:
    """C-5's module path, `__all__`, field name and stage name, exactly."""
    import mangatl.pipeline.clean_stage as module

    assert module.__all__ == ["CleanStage", "PageCleaner"]

    cleaner = _RecordingCleaner(png_bytes)
    stage = CleanStage(clean=cleaner)

    assert stage.name == _CLEAN
    assert stage.clean is cleaner
    assert isinstance(stage.is_done(fixture.context(_TARGET)), bool)


def test_the_stage_name_is_a_settable_instance_attribute_as_the_protocol_requires(
    png_bytes: Callable[..., bytes],
) -> None:
    """C-5: not `frozen=True`, for MT-035 R-1's reason (`Stage.name` is a
    settable instance attribute, and mypy holds an implementation to that)."""
    stage = CleanStage(clean=_RecordingCleaner(png_bytes))

    stage.name = "renamed"

    assert stage.name == "renamed"


def test_the_page_cleaner_alias_is_page_bytes_and_regions_in_and_image_bytes_out() -> None:
    """C-5's `PageCleaner`, introspected: bytes are stdlib and `RawRegion` is
    `domain`, which is what lets `pipeline` name the cleaner without importing
    `mangatl.clean`."""
    assert get_origin(PageCleaner) is Callable

    parameters, returned = get_args(PageCleaner)

    assert parameters[0] is bytes
    assert get_origin(parameters[1]) is Sequence
    assert get_args(parameters[1]) == (RawRegion,)
    assert len(parameters) == 2
    assert returned is bytes


def test_the_stage_module_imports_nothing_that_contract_five_forbids() -> None:
    """C-5's seam, as a unit tripwire beside the `lint` contract.

    `mangatl.clean.inpaint` reaches `onnxruntime` through `clean.session`, so
    the stage may not import `mangatl.clean` at all - not even to spell
    `InpaintSession`. Read out of the module's AST so the docstring may discuss
    `mangatl.clean` freely.
    """
    import mangatl.pipeline.clean_stage as module

    assert module.__file__ is not None
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)

    forbidden = sorted(
        name
        for name in imported
        for root in (
            "mangatl.clean",
            "mangatl.detect",
            "mangatl.ocr",
            "mangatl.compose",
            "onnxruntime",
            "numpy",
            "PIL",
            "cv2",
        )
        if name == root or name.startswith(f"{root}.")
    )
    assert forbidden == [], (
        f"{forbidden} is imported by mangatl.pipeline.clean_stage. Contract 5"
        " forbids mangatl.pipeline from reaching onnxruntime even indirectly;"
        " the stage takes bytes in and bytes out (C-5) and compose binds the"
        " real cleaner (C-7)."
    )


# -- AC-1: the stored image is the cleaner's, for the page's own inputs --------


def test_a_page_with_regions_stores_exactly_what_the_cleaner_returned(
    fixture: _Fixture, png_bytes: Callable[..., bytes]
) -> None:
    """**AC-1.** The stored bytes equal the fake's return, read back through the
    store and through a plain `sqlite3` connection, and only for this page."""
    fixture.project.write_regions(_TARGET, fixture.regions(3))
    cleaner = _RecordingCleaner(png_bytes)

    CleanStage(clean=cleaner).run(fixture.context(_TARGET))

    assert cleaner.calls == 1, f"the cleaner was called {cleaner.calls} times for one page"
    assert fixture.project.read_cleaned(_TARGET) == cleaner.returned[0], (
        "the stored cleaned image is not the bytes the cleaner returned"
    )
    assert fixture.stored() == {_TARGET: cleaner.returned[0]}, (
        "read through a plain sqlite3 connection, cleaned_page does not hold"
        " exactly one row, for the page that was cleaned, with the cleaner's bytes"
    )
    assert fixture.project.read_cleaned(_TARGET) != fixture.source_bytes(_TARGET), (
        "the control: the fake's output must differ from the source, or this"
        " test cannot tell a stored source from a stored cleaned page"
    )


def test_the_cleaner_is_handed_the_pages_own_source_bytes_and_its_stored_regions_in_order(
    fixture: _Fixture, png_bytes: Callable[..., bytes]
) -> None:
    """**AC-1**, the inputs: *"for that page's source pixels and the erase mask
    of its stored regions"*. The regions are the store's, in stored reading
    order (C-5, §4) - never re-sorted, never re-detected."""
    fixture.project.write_regions(_TARGET, fixture.regions(3))
    fixture.project.write_regions(0, fixture.regions(1))
    cleaner = _RecordingCleaner(png_bytes)

    CleanStage(clean=cleaner).run(fixture.context(_TARGET))

    (image_bytes, regions), *_rest = cleaner.seen
    assert image_bytes == fixture.source_bytes(_TARGET), (
        "the cleaner was not handed this page's own scan"
    )
    assert regions == fixture.project.read_regions(_TARGET), (
        "the cleaner was not handed this page's stored regions in stored order"
    )
    assert len(regions) == 3


def test_a_cleaner_that_returns_the_wrong_size_is_refused_by_name_and_nothing_is_stored(
    fixture: _Fixture, png_bytes: Callable[..., bytes]
) -> None:
    """**AC-1**'s *"the size of the source page"*, on the stage path: C-3's
    size check refuses a mis-bound cleaner with a `ValueError` naming the
    ordinal, and the page stays not-done. The negative control for the size."""
    fixture.project.write_regions(_TARGET, fixture.regions(1))
    stage = CleanStage(clean=_RecordingCleaner(png_bytes, size=(30, 40)))

    with pytest.raises(ValueError, match=rf"(?<!\d){_TARGET}(?!\d)"):
        stage.run(fixture.context(_TARGET))

    assert fixture.project.read_cleaned(_TARGET) is None
    assert stage.is_done(fixture.context(_TARGET)) is False


def test_running_the_stage_leaves_the_users_scans_byte_for_byte_unchanged(
    fixture: _Fixture, png_bytes: Callable[..., bytes]
) -> None:
    """C-5: the source scan is read, never written (`architecture.md` §5)."""
    fixture.project.write_regions(_TARGET, fixture.regions(2))
    before = _snapshot(fixture.source_dir)

    stage = CleanStage(clean=_RecordingCleaner(png_bytes))
    for ordinal in range(_PAGE_COUNT):
        stage.run(fixture.context(ordinal))

    assert _snapshot(fixture.source_dir) == before


# -- AC-2: no regions, no cleaner, the source verbatim -------------------------


def test_a_png_page_with_no_regions_never_reaches_the_cleaner_and_stores_the_source(
    fixture: _Fixture, png_bytes: Callable[..., bytes]
) -> None:
    """**AC-2** on a PNG page: zero calls, and the stored image decodes to the
    source's exact pixels (PO-4: the scan's own bytes, verbatim)."""
    cleaner = _RecordingCleaner(png_bytes)

    CleanStage(clean=cleaner).run(fixture.context(_TARGET))

    assert cleaner.calls == 0, "the cleaner was called for a page with no regions"
    stored = fixture.project.read_cleaned(_TARGET)
    assert stored is not None, "a page with no regions stored no cleaned image"
    assert _pixels(stored) == _pixels(fixture.source_bytes(_TARGET))
    assert _size_of(stored) == _TARGET_SIZE


def test_a_jpeg_page_with_no_regions_stores_an_image_pixel_identical_to_the_source(
    fixture: _Fixture, png_bytes: Callable[..., bytes]
) -> None:
    """**AC-2** on a JPEG page (C-8): a re-encode through any lossy path would
    move pixels here; the source bytes verbatim cannot."""
    cleaner = _RecordingCleaner(png_bytes)

    CleanStage(clean=cleaner).run(fixture.context(_JPEG_ORDINAL))

    assert cleaner.calls == 0
    stored = fixture.project.read_cleaned(_JPEG_ORDINAL)
    assert stored is not None
    assert _pixels(stored) == _pixels(fixture.source_bytes(_JPEG_ORDINAL))
    assert fixture.raw("SELECT count(*) FROM cleaned_page") == [(1,)]


# -- AC-3: is_done, and resume -------------------------------------------------


def test_is_done_is_false_before_the_stage_runs_and_true_once_the_image_is_stored(
    fixture: _Fixture, png_bytes: Callable[..., bytes]
) -> None:
    """**AC-3**, the truth table, and `has_cleaned` agrees at both points."""
    fixture.project.write_regions(_TARGET, fixture.regions(2))
    stage = CleanStage(clean=_RecordingCleaner(png_bytes))
    ctx = fixture.context(_TARGET)

    assert stage.is_done(ctx) is False
    assert fixture.project.has_cleaned(_TARGET) is False

    stage.run(ctx)

    assert stage.is_done(ctx) is True
    assert fixture.project.has_cleaned(_TARGET) is True
    assert stage.is_done(fixture.context(0)) is False, "a different page became done"


def test_is_done_reads_the_stored_cleaned_image_and_nothing_else(
    fixture: _Fixture, png_bytes: Callable[..., bytes]
) -> None:
    """C-5: `is_done` is "a cleaned image is stored" - not regions, lines or
    `page.status`. A page with regions and no image is not done; a page with
    no regions, no lines and status `pending` and an image written directly is."""
    stage = CleanStage(clean=_RecordingCleaner(png_bytes))
    fixture.project.write_regions(0, fixture.regions(1))
    fixture.project.write_cleaned(_TARGET, fixture.source_bytes(_TARGET))

    assert stage.is_done(fixture.context(0)) is False
    assert stage.is_done(fixture.context(_TARGET)) is True
    assert fixture.project.page_status(_TARGET) == "pending"


def test_a_second_run_over_a_cleaned_chapter_calls_the_cleaner_zero_times(
    fixture: _Fixture, png_bytes: Callable[..., bytes]
) -> None:
    """**AC-3**'s last clause through the runner and the real stage list: the
    first run cleans every page, the second skips every page and cleans none."""
    cleaner = _RecordingCleaner(png_bytes)

    outcome = run_chapter(
        fixture.project,
        build_stages(_Detector(fixture.mask), cleaner, _Transcriber(), _Translator()),
        lambda _event: None,
        _never,
    )
    assert outcome.outcome == RUN_FINISHED
    assert cleaner.calls == _PAGE_COUNT, (
        f"the first run cleaned {cleaner.calls} of {_PAGE_COUNT} pages with regions"
    )

    events: list[RunEvent] = []
    run_chapter(
        fixture.project,
        build_stages(_Detector(fixture.mask), cleaner, _Transcriber(), _Translator()),
        events.append,
        _never,
    )

    assert cleaner.calls == _PAGE_COUNT, (
        f"the second run called the cleaner {cleaner.calls - _PAGE_COUNT} more"
        " times; AC-3 says a resumed run does not clean a page that is done"
    )
    skipped = [event.ordinal for event in events if isinstance(event, PageSkipped)]
    assert skipped == list(range(_PAGE_COUNT))


def test_a_translated_chapter_with_no_cleaned_images_is_cleaned_without_detect_ocr_or_spend(
    fixture: _Fixture, png_bytes: Callable[..., bytes]
) -> None:
    """**AC-3** across the migration (C-8, C-9): a page whose detect, OCR and
    translate are done and whose cleaned image is absent - a v6 project opened
    by this build, here the rows deleted - is cleaned on the next run, and
    nothing else runs: no detector, no transcriber and **no translator call**.
    The per-stage skip (MT-036 C-4) is what makes adding a stage free for an
    already-translated chapter."""
    cleaner = _RecordingCleaner(png_bytes)
    run_chapter(
        fixture.project,
        build_stages(_Detector(fixture.mask), cleaner, _Transcriber(), _Translator()),
        lambda _event: None,
        _never,
    )
    connection = sqlite3.connect(fixture.db_path)
    try:
        with connection:
            connection.execute("DELETE FROM cleaned_page")
    finally:
        connection.close()
    assert not any(fixture.project.has_cleaned(n) for n in range(_PAGE_COUNT))

    detector = _Detector(fixture.mask)
    transcriber = _Transcriber()
    translator = _Translator()
    resumed = _RecordingCleaner(png_bytes)
    events: list[RunEvent] = []
    outcome = run_chapter(
        fixture.project,
        build_stages(detector, resumed, transcriber, translator),
        events.append,
        _never,
    )

    assert outcome.outcome == RUN_FINISHED
    assert resumed.calls == _PAGE_COUNT, "the resumed run did not clean every page"
    assert (detector.calls, transcriber.calls, translator.calls) == (0, 0, 0), (
        "(detector, transcriber, translator) calls on a chapter that was already"
        f" detected, read and translated: {(detector.calls, transcriber.calls, translator.calls)}"
    )
    finished = [event.stage for event in events if isinstance(event, StageFinished)]
    assert finished == [_CLEAN] * _PAGE_COUNT
    assert all(fixture.project.has_cleaned(n) for n in range(_PAGE_COUNT))


# -- AC-4, the stage half: re-detection makes the page not-done ----------------


def test_writing_a_pages_regions_again_makes_its_clean_stage_not_done(
    fixture: _Fixture, png_bytes: Callable[..., bytes]
) -> None:
    """**AC-4**, through `is_done`: the store half (exactly which rows go) is
    `test_cleaned_store.py`'s."""
    fixture.project.write_regions(_TARGET, fixture.regions(2))
    fixture.project.write_regions(0, fixture.regions(1))
    stage = CleanStage(clean=_RecordingCleaner(png_bytes))
    stage.run(fixture.context(_TARGET))
    stage.run(fixture.context(0))

    fixture.project.write_regions(_TARGET, fixture.regions(2))

    assert stage.is_done(fixture.context(_TARGET)) is False
    assert stage.is_done(fixture.context(0)) is True
