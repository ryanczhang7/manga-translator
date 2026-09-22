"""`mangatl.pipeline.detect_stage`: the stage that writes a page's regions.

Covers AC-1 (reading order reaches the store), AC-2 (one call, the page's own
bytes, the scans untouched), AC-3 (the `is_done` truth table and the runner's
skip), AC-4 (a re-run that finds fewer regions), AC-5 (a page with no text) and
AC-6 (a detector that raises leaves the previous run's regions intact). AC-7 to
AC-9 are the detect adapter and live in `test_detect_page.py`; AC-10 is the real
detector and lives in `tests/integration/`.

**The detector is injected, and that is forced by the `lint` gate rather than
chosen for taste** (MT-035 C-1, reproduced twice before dispatch). Import-linter
contract 5 lists `mangatl.pipeline` among its `source_modules` and sets no
`allow_indirect_imports`, and every module in `mangatl.detect` reaches
`onnxruntime` through `columns -> postprocess -> session`. So `pipeline` may not
import `mangatl.detect` **at all**, not even the `DetectorSession` protocol -
that protocol lives in the very file that does the import. The stage therefore
names its detector behind `PageDetector = Callable[[bytes], Sequence[RawRegion]]`,
whose two halves are stdlib and `domain`.
`test_the_stage_module_imports_nothing_that_contract_five_forbids` is the unit
tripwire for that, so the constraint is falsifiable in `unit` and not only in
`lint`.

**The fake detector is a double for `run`, not for `is_done`.** Done-ness is
read out of the store on every test here, because "does this page already have
regions" is the whole of AC-3 and a stubbed answer would test nothing
(`test_pipeline.py` makes the same choice, for the same reason).

**Timing.** There is no `pytest-timeout` in this project and no per-test timeout
exists, so there is no budget in this file to size; if a later story adds one,
every test and hook here needs one. The dominant cost is `conftest._one_bit_png`,
a per-pixel Python loop, so the fixture page is 40x30 (1,200 px) rather than
page-sized: MT-009 measured 281 ms for a 1125x1600 mask and 7 ms for a small
one, and reading order never looks at mask pixels.
"""

from __future__ import annotations

import ast
import hashlib
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import get_args, get_origin

import pytest

from mangatl.domain.events import PageSkipped, PageStarted, RunEvent, RunFinished, RunStarted
from mangatl.domain.reading_order import order_regions, sort_regions
from mangatl.domain.region import RawRegion
from mangatl.pipeline.detect_stage import DetectStage, PageDetector
from mangatl.pipeline.runner import RUN_FINISHED, run_chapter
from mangatl.pipeline.stage import PageContext
from mangatl.store.intake import read_chapter
from mangatl.store.project import Project, create_project, project_dir_for

# -- the fixture chapter -------------------------------------------------------

#: Three pages at three distinct sizes, so every page's PNG bytes differ and
#: AC-2's "the page's OWN bytes" is a claim with something to be false about.
_SOURCE_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 30, 20),
    ("p2.png", 40, 30),
    ("p3.png", 50, 40),
)

#: The page every criterion below runs against, and it is **not ordinal 0**.
#:
#: That is a requirement on RED rather than an accident (MT-035 DV-3). GATES
#: mutates `write_regions(ctx.page.ordinal, ordered)` to `write_regions(0,
#: ordered)` - one token, a plausible typo, nothing omitted - and AC-1's test can
#: only catch it if the page under test sits somewhere other than 0. A suite that
#: catches an omission can be blind to a corruption.
_TARGET_ORDINAL = 1
_TARGET = _SOURCE_PAGES[_TARGET_ORDINAL]
_PAGE_WIDTH, _PAGE_HEIGHT = _TARGET[1], _TARGET[2]

#: `DetectStage.name`, pinned as a literal because the event stream carries it.
_DETECT = "detect"


class _DetectorExploded(Exception):
    """AC-6's injected detector failure.

    A bespoke type, so the test cannot pass by catching a real error raised
    somewhere else for another reason.
    """


# -- regions, in an order that is not reading order ----------------------------
#
# Reading order is right to left, top to bottom (MT-009): regions are grouped
# into horizontal bands, bands run top to bottom, and each band runs right to
# left. These three sit in two bands - two side by side at the top, one below -
# so the reading order is top-right, top-left, bottom-left.


def _ring(x0: int, y0: int, x1: int, y1: int) -> tuple[tuple[int, int], ...]:
    """A closed rectangular ring, which is what `RawRegion.polygon` requires."""
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))


@dataclass(frozen=True)
class _Fixture:
    """The fixture chapter, its project, and the page under test."""

    source_dir: Path
    project: Project
    mask: bytes
    #: MT-044 C-1: `PageContext` carries the run, with no default. `DetectStage`
    #: never reads it - the field is on the context because the context is what
    #: the runner hands every stage - but the id is a real `run` row's all the
    #: same, so nothing here teaches the habit of inventing one.
    run_id: int

    @property
    def context(self) -> PageContext:
        return self.page_context(_TARGET_ORDINAL)

    def page_context(self, ordinal: int) -> PageContext:
        page = next(page for page in self.project.pages() if page.ordinal == ordinal)
        return PageContext(project=self.project, page=page, run_id=self.run_id)

    def region(self, x0: int, y0: int, x1: int, y1: int, confidence: float) -> RawRegion:
        """One region at a rectangle. `confidence` is exactly representable in
        binary, so the store round trip is bit-identical and the whole
        `RawRegion` can be compared with `==`."""
        return RawRegion(
            polygon=_ring(x0, y0, x1, y1),
            mask=self.mask,
            confidence=confidence,
            kind="bubble",
        )

    @property
    def top_right(self) -> RawRegion:
        return self.region(28, 2, 38, 8, 0.5)

    @property
    def top_left(self) -> RawRegion:
        return self.region(2, 2, 12, 8, 0.75)

    @property
    def bottom_left(self) -> RawRegion:
        return self.region(2, 20, 12, 28, 0.25)

    @property
    def reading_order(self) -> list[RawRegion]:
        """The three regions in reading order: top-right, top-left, bottom-left."""
        return [self.top_right, self.top_left, self.bottom_left]

    @property
    def detector_order(self) -> list[RawRegion]:
        """The order the *detector* hands them over: the exact reverse.

        `regions_from_detection` emits by bounding-box `(y0, x0)` and
        `merge_columns` preserves that, so a real detector's order is
        top-to-bottom then left-to-right - never reading order. A full reversal
        is the sharpest version of that: every position differs, so a stage
        writing the detector's order straight through is wrong at index 0.
        """
        return [self.bottom_left, self.top_left, self.top_right]


@pytest.fixture
def fixture(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
) -> Iterator[_Fixture]:
    """A three-page project on `tmp_path`, with the scans in a `scans/` subfolder.

    A subfolder rather than `tmp_path` itself, so `<source>.mtproj` and
    `<source>_en` are also inside `tmp_path` and the test leaves nothing outside
    its own directory - `test_pipeline.py`'s `_build_source` makes the same
    choice.
    """
    source_dir = tmp_path / "scans"
    source_dir.mkdir()
    for index, (filename, width, height) in enumerate(_SOURCE_PAGES):
        # A distinct fill per page as well as a distinct size, so two pages
        # cannot share bytes even if a later story equalises the sizes.
        (source_dir / filename).write_bytes(png_bytes(width, height, (index * 40, 0, 0)))

    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        yield _Fixture(
            source_dir=source_dir,
            project=project,
            mask=one_bit_png(_PAGE_WIDTH, _PAGE_HEIGHT, [(0, 0, 4, 4)]),
            run_id=_open_run(project),
        )


def _open_run(project: Project) -> int:
    """A real `run` row, for MT-044 C-1's `PageContext.run_id`."""
    with project.transaction() as cursor:
        chapter_id = int(cursor.execute("SELECT id FROM chapter").fetchone()[0])
        cursor.execute(
            "INSERT INTO run (chapter_id, started_at) VALUES (?, ?)",
            (chapter_id, "2026-09-21T09:00:00+00:00"),
        )
        return int(cursor.execute("SELECT last_insert_rowid()").fetchone()[0])


# -- the fake detector ---------------------------------------------------------


class _FakeDetector:
    """A `PageDetector`: page bytes in, regions out, in the order given.

    Records every call, because AC-2 is a claim about the call count and the
    exact argument and AC-3 is a claim that there was no call at all.
    """

    def __init__(
        self,
        regions: Sequence[RawRegion] = (),
        *,
        explode: bool = False,
    ) -> None:
        self._regions = list(regions)
        self._explode = explode
        self.seen: list[bytes] = []

    @property
    def calls(self) -> int:
        return len(self.seen)

    def __call__(self, image_bytes: bytes) -> Sequence[RawRegion]:
        self.seen.append(image_bytes)
        if self._explode:
            raise _DetectorExploded("boom-in-the-detector")
        return list(self._regions)


def _snapshot(root: Path) -> dict[str, str | None]:
    """relative path -> sha256 of contents, or None for a directory.

    The same shape as `test_pipeline.py`'s and `test_project.py`'s, and
    duplicated for the same reason: directories are included, over `rglob("*")`,
    so AC-2 catches a *directory* appearing under the source folder as well as a
    file being created, edited or removed.
    """
    return {
        str(entry.relative_to(root)): (
            hashlib.sha256(entry.read_bytes()).hexdigest() if entry.is_file() else None
        )
        for entry in sorted(root.rglob("*"))
    }


def _never() -> bool:
    """The `cancelled` predicate for a run nobody cancels.

    A plain callable, which is the point of `run_chapter`'s signature: no Qt, no
    threading primitive, no queue.
    """
    return False


def _projected(events: Sequence[RunEvent]) -> list[tuple[str, int | None]]:
    """Each event as `(type name, ordinal or None)`.

    `StageFinished.elapsed_ms` is a measured duration, so the stream is asserted
    as an ordered projection and never as a list of dataclasses (MT-006 PO-7).
    """
    return [(type(event).__name__, getattr(event, "ordinal", None)) for event in events]


# -- the module's shape --------------------------------------------------------


def test_the_stage_is_exported_from_mangatl_pipeline_detect_stage_under_that_name(
    fixture: _Fixture,
) -> None:
    """C-3's module path, `__all__`, field name and stage name, pinned exactly.

    `name` is a field with a default rather than a `ClassVar`: the `Stage`
    protocol declares `name: str` as an instance attribute, and `mypy` refuses a
    `ClassVar` against a protocol member typed that way.
    """
    import mangatl.pipeline.detect_stage as module

    assert module.__all__ == ["DetectStage", "PageDetector"]

    detector = _FakeDetector()
    stage = DetectStage(detect=detector)

    assert stage.name == _DETECT
    assert stage.detect is detector
    # A `Stage` is a Protocol rather than a base class, so this is the whole of
    # what conformance means at runtime; AC-3 then hands it to `run_chapter`.
    assert callable(stage.run)
    assert callable(stage.is_done)
    assert isinstance(stage.is_done(fixture.context), bool)


def test_the_stage_name_is_a_settable_instance_attribute_as_the_protocol_requires() -> None:
    """C-3 as amended in RED: `DetectStage` must not be a **frozen** dataclass.

    `Stage.name: str` is a settable protocol member, and mypy holds a class to
    that. C-3 already recorded that a `ClassVar` fails it; measured in RED, so
    does `@dataclass(frozen=True)`, for a second and independent reason. Against
    the shipped `Stage`, with `PassThroughStage` in the same list as a control:

        Protocol member Stage.name expected settable variable,
        got read-only attribute        # @dataclass(frozen=True), name: str
        Protocol member Stage.name expected instance variable,
        got class variable             # @dataclass(frozen=True), name: ClassVar[str]
        (no error)                     # @dataclass, name: str
        (no error)                     # PassThroughStage, the shipped baseline

    `mypy src` cannot catch this while nothing in `src` annotates a
    `DetectStage` as a `Stage` - production wiring is out of scope here - so the
    trap would surface in whichever later story first assembles a real run, as a
    change to a class this story shipped. Assignment is the one runtime-visible
    consequence of "settable", and a frozen dataclass raises
    `dataclasses.FrozenInstanceError` on it, so this is the assertion that keeps
    the amendment honest. Nothing should ever rename a live stage; the point is
    that it *could*.
    """
    stage = DetectStage(detect=_FakeDetector())

    stage.name = "renamed"

    assert stage.name == "renamed"


def test_the_page_detector_alias_is_page_bytes_in_and_a_sequence_of_regions_out() -> None:
    """C-3's `PageDetector`, introspected rather than trusted.

    Asserted through `get_origin`/`get_args` so the claim is about the alias's
    *meaning* and not about which module `Callable` was imported from:
    `typing.Callable[...]` and `collections.abc.Callable[...]` are unequal
    objects that answer these three questions identically (verified in RED).

    This is the type that keeps `pipeline` clean: `bytes` is stdlib and
    `RawRegion` is `domain`, so naming the detector costs no import of
    `mangatl.detect` (C-1).
    """
    assert get_origin(PageDetector) is Callable

    parameters, returned = get_args(PageDetector)

    assert parameters == [bytes]
    assert get_origin(returned) is Sequence
    assert get_args(returned) == (RawRegion,)


def test_the_stage_module_imports_nothing_that_contract_five_forbids() -> None:
    """C-1's seam, as a unit tripwire rather than only as a `lint` contract.

    Import-linter catches the indirect chain `pipeline -> detect.columns ->
    detect.postprocess -> detect.session -> onnxruntime`, and it is a required
    gate. This test is here because the failure it prevents is *cheap to make
    and expensive to diagnose*: an implementer reaching for `numpy` to decode a
    mask, or for `DetectorSession` to type a parameter, gets told which import
    broke the seam by name, in the phase that added it.

    The module's own imports are read out of its AST, so the docstring may
    discuss `mangatl.detect` freely - which C-3 requires it to.
    """
    import mangatl.pipeline.detect_stage as module

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
        for root in ("mangatl.detect", "numpy", "PIL", "cv2", "onnxruntime")
        if name == root or name.startswith(f"{root}.")
    )
    assert forbidden == [], (
        f"{forbidden} is imported by mangatl.pipeline.detect_stage. Contract 5"
        " forbids mangatl.pipeline from reaching onnxruntime even indirectly, and"
        " every module in mangatl.detect reaches it. If the stage wants one of"
        " these, the seam is in the wrong place - see MT-035 C-1."
    )


# -- AC-1: reading order reaches the store -------------------------------------


def test_a_pages_regions_are_stored_in_reading_order_whatever_order_they_arrived_in(
    fixture: _Fixture,
) -> None:
    """AC-1, and EPIC-03's done-when sentence: index 0 is the top-right region
    and index n-1 the bottom-left.

    The first two assertions are the control on the fixture itself. Without
    them a stage that wrote the detector's order straight through would satisfy
    AC-1 by accident, and the criterion would measure nothing. Measured in RED
    outside the framework: `order_regions(detector_order) == [2, 1, 0]`.

    It also pins C-3's "the stage opens no transaction": `write_regions` opens
    its own and `Project.transaction()` is deliberately not reentrant (MT-005
    PO-5), so a stage that wrapped the write raises `RuntimeError` here.
    """
    detector_order = fixture.detector_order

    assert order_regions(detector_order) != list(range(len(detector_order))), (
        "the fixture's detector order IS its reading order, so this test cannot"
        " tell an ordering stage from a pass-through one"
    )
    assert order_regions(detector_order) == [2, 1, 0]

    detector = _FakeDetector(detector_order)
    DetectStage(detect=detector).run(fixture.context)

    stored = fixture.project.read_regions(_TARGET_ORDINAL)

    assert list(stored) == fixture.reading_order
    assert stored[0] == fixture.top_right, "reading_index 0 is not the top-right region"
    assert stored[-1] == fixture.bottom_left, "the last region is not the bottom-left one"
    # The settled identity `sort_regions(r) == [r[i] for i in order_regions(r)]`
    # (MT-009, verified at domain/reading_order.py:155), read out rather than
    # re-derived.
    assert list(stored) == sort_regions(detector_order)


# -- AC-2: one call, the page's own bytes, the scans untouched -----------------


def test_the_detector_is_called_once_with_the_pages_own_bytes(fixture: _Fixture) -> None:
    """AC-2's first half. One inference per page, on the file the page names.

    The "not another page's bytes" assertion is what makes it a claim about
    *this* page: a stage that read `pages()[0]` every time would otherwise pass
    on a one-page chapter and on any chapter whose pages happened to be equal.
    """
    detector = _FakeDetector(fixture.reading_order)
    context = fixture.context

    DetectStage(detect=detector).run(context)

    expected = (fixture.source_dir / context.page.filename).read_bytes()
    assert detector.calls == 1, f"the detector ran {detector.calls} times, not once"
    assert detector.seen == [expected]
    others = {
        page.filename: (fixture.source_dir / page.filename).read_bytes()
        for page in fixture.project.pages()
        if page.ordinal != _TARGET_ORDINAL
    }
    assert detector.seen[0] not in others.values(), (
        f"the detector was handed some other page's bytes; page {_TARGET_ORDINAL} is"
        f" {context.page.filename}, and the chapter also holds {sorted(others)}"
    )


def test_running_the_stage_leaves_the_users_scans_byte_for_byte_unchanged(
    fixture: _Fixture,
) -> None:
    """AC-2's second half. `architecture.md` §5: the source folder is read-only
    to this app, always - and that is the promise a user's only copy of a scan
    depends on.

    The snapshot covers directories as well as files, so a scratch folder
    appearing beside the scans fails this too.
    """
    before = _snapshot(fixture.source_dir)
    assert before, "the snapshot is empty, so it cannot detect a change"

    DetectStage(detect=_FakeDetector(fixture.reading_order)).run(fixture.context)

    assert _snapshot(fixture.source_dir) == before


# -- AC-3: the is_done truth table, and the runner's skip ----------------------


def test_is_done_is_true_for_a_page_with_stored_regions_and_false_without(
    fixture: _Fixture,
) -> None:
    """AC-3's truth table, both rows, on one page so nothing else can differ.

    C-6: "has regions" is the only honest thing the detect stage can read back,
    because regions are the only thing it writes.
    """
    stage = DetectStage(detect=_FakeDetector(fixture.reading_order))
    context = fixture.context

    assert stage.is_done(context) is False, "a page with no stored regions is not done"

    stage.run(context)

    assert stage.is_done(context) is True, "a page whose regions are in the store is done"
    # And it is per page, not per chapter: the other two pages were not touched.
    assert stage.is_done(fixture.page_context(0)) is False
    assert stage.is_done(fixture.page_context(2)) is False


def test_a_run_over_pages_that_already_have_regions_skips_them_without_detecting(
    fixture: _Fixture,
) -> None:
    """AC-3's second half, through the real runner.

    `run_chapter` emits `PageSkipped` when `stages and all(stage.is_done(ctx))`
    (MT-006, runner.py:147), so this is the composition of that skip with this
    stage's own done-ness - which is the whole point of resume: a killed run
    must not pay for a second GPU inference on a page it already detected.

    Every page is pre-populated, using a *different* detector instance, so the
    detector under test can assert zero calls rather than "no calls for page 1".
    """
    for ordinal in range(len(_SOURCE_PAGES)):
        seeding = DetectStage(detect=_FakeDetector(fixture.reading_order))
        seeding.run(fixture.page_context(ordinal))

    detector = _FakeDetector(fixture.reading_order)
    events: list[RunEvent] = []
    outcome = run_chapter(fixture.project, [DetectStage(detect=detector)], events.append, _never)

    assert detector.calls == 0, (
        f"the detector ran {detector.calls} times on pages that already have regions"
    )
    assert _projected(events) == [
        (RunStarted.__name__, None),
        (PageSkipped.__name__, 0),
        (PageSkipped.__name__, 1),
        (PageSkipped.__name__, 2),
        (RunFinished.__name__, None),
    ]
    assert [type(event).__name__ for event in events].count(PageStarted.__name__) == 0
    assert outcome.outcome == RUN_FINISHED
    assert outcome.pages_done == len(_SOURCE_PAGES)


# -- AC-4: a re-run that finds fewer regions -----------------------------------


def test_a_rerun_that_finds_fewer_regions_leaves_none_of_the_previous_run_behind(
    fixture: _Fixture,
) -> None:
    """AC-4. The store holds exactly the new set, in reading order, no stragglers.

    `write_regions` is a page-level replace that deletes rows at
    `reading_index >= len(regions)` (MT-007 A-11, verified at
    store/project.py:333+), so "no stragglers" is already the store's behaviour -
    what this pins is that the stage performs **one** write of the whole new set
    and does not, say, upsert region by region.

    The second run's two regions are handed over in a non-reading order too
    (measured: `order_regions` of them is `[1, 0]`), so a stage that dropped the
    ordering step on the re-run path alone still fails.
    """
    first = fixture.reading_order
    DetectStage(detect=_FakeDetector(fixture.detector_order)).run(fixture.context)
    assert len(fixture.project.read_regions(_TARGET_ORDINAL)) == len(first) == 3

    fewer = [fixture.top_left, fixture.top_right]
    assert order_regions(fewer) == [1, 0], "the re-run's order is already reading order"
    DetectStage(detect=_FakeDetector(fewer)).run(fixture.context)

    stored = fixture.project.read_regions(_TARGET_ORDINAL)

    assert list(stored) == [fixture.top_right, fixture.top_left]
    assert len(stored) == 2
    assert fixture.bottom_left not in stored, (
        "a region from the previous run survived into the new set"
    )
    assert [region.polygon for region in stored] == [
        fixture.top_right.polygon,
        fixture.top_left.polygon,
    ]


# -- AC-5: a page the detector finds nothing on --------------------------------


@pytest.mark.parametrize("prepopulated", [False, True], ids=["fresh", "previously-detected"])
def test_a_page_the_detector_finds_no_text_on_stores_nothing_and_stays_not_done(
    fixture: _Fixture,
    prepopulated: bool,
) -> None:
    """AC-5, and it is a decision rather than an oversight (C-6).

    A genuinely textless page is re-detected on every run. That is accepted for
    v1 because re-detecting is idempotent and costs one GPU inference - no API
    spend, no data loss - whereas a per-stage completion marker is a schema
    change this story has no mandate for. Written as a criterion so it is
    falsifiable: if a later story adds per-stage markers, this is what it amends.

    The `previously-detected` case is the extreme of AC-4: `write_regions(n, ())`
    clears the page, which is the honest answer for a page the detector now finds
    nothing on.
    """
    stage = DetectStage(detect=_FakeDetector(()))
    context = fixture.context
    if prepopulated:
        DetectStage(detect=_FakeDetector(fixture.detector_order)).run(context)
        assert stage.is_done(context) is True

    stage.run(context)

    assert fixture.project.read_regions(_TARGET_ORDINAL) == ()
    assert stage.is_done(context) is False, (
        "a page with no regions reads as done, so a textless page would never be"
        " re-detected and C-6's decision is not the one that shipped"
    )


# -- AC-6: a detector that raises leaves the previous run intact ---------------


def test_a_detector_that_raises_leaves_the_pages_stored_regions_untouched(
    fixture: _Fixture,
) -> None:
    """AC-6, and it is the one criterion that catches a stage which clears first.

    The stage writes **once**, after it has every region, and never clears
    first. A stage that opened with `write_regions(ordinal, ())` would pass every
    other criterion in this file and destroy a page's regions - and, once MT-010
    lands, the `line` rows attached to them - every time an inference failed.

    The propagation is asserted here and nothing more: `run_chapter` emitting
    `RunAborted` naming the page is MT-006 AC-4's, and re-asserting it here would
    test the runner rather than this stage.
    """
    DetectStage(detect=_FakeDetector(fixture.detector_order)).run(fixture.context)
    before = fixture.project.read_regions(_TARGET_ORDINAL)
    assert len(before) == 3, "the fixture must already hold a previous run's regions"

    exploding = _FakeDetector(explode=True)
    with pytest.raises(_DetectorExploded):
        DetectStage(detect=exploding).run(fixture.context)

    assert exploding.calls == 1
    assert fixture.project.read_regions(_TARGET_ORDINAL) == before
    assert list(fixture.project.read_regions(_TARGET_ORDINAL)) == fixture.reading_order
