"""MT-062: `RegionsDetected`, the event, and `DetectStage` emitting it (AC-2).

Covers `## Contract` C-1 (the event: data only, frozen, in `__all__` and in the
`RunEvent` union) and C-2 (the emitter: after `write_regions`, from the ordered
regions, once per page the stage runs on, never on a page whose detection is
skipped). The UI half of the story - the thumbnail and the panel - is
`tests/ui/test_run_thumbnail.py`; the window path is `tests/ui/test_start_run.py`.

Oracle partition (C-7): **mechanical, hand-computed.** Every expected polygon
below is a literal ring written out in this file, never a value read back from
the module under test:

- **"After the write"** is observed the way MT-063 observed `CallPriced`: the
  recording `emit` reads `project.read_regions(ordinal)` *at the moment it is
  called*. Emitted before the write (DV-1), the store is still empty on a first
  run and the comparison fails on length.
- **"In the reading order they were stored in"** is observed against a fake
  detector that hands its regions over in the exact *reverse* of reading order,
  so a stage that built `polygons` from the detector's list (DV-2) is wrong at
  index 0. The expected order is written out as literals (top-right, top-left,
  bottom-left - MT-009's right-to-left, top-to-bottom), and is independently
  equal to the store's read-back.
- **"Exactly one per detected page; none on a skipped page"** is a projection of
  a real `run_chapter` stream, as `test_pipeline.py` asserts streams (MT-006
  PO-7: `elapsed_ms` is a clock and is never compared).

The fixture page under test is **ordinal 1, not 0** (MT-035 DV-3's reason): an
event carrying a hard-coded or wrong ordinal is visible.

**RED:** fails at import - `RegionsDetected` does not exist in
`mangatl.domain.events` - so no assertion here has run. No real weights, no GPU,
no waits: every test is synchronous and sub-second.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

import pytest

import mangatl.domain.events as events_module
from mangatl.domain.events import (
    PageSkipped,
    PageStarted,
    RegionsDetected,
    RunEvent,
    RunFinished,
    StageFinished,
)
from mangatl.domain.region import RawRegion
from mangatl.pipeline.detect_stage import DetectStage
from mangatl.pipeline.runner import RUN_FINISHED, run_chapter
from mangatl.pipeline.stage import PageContext
from mangatl.store.intake import read_chapter
from mangatl.store.project import Project, create_project, project_dir_for

# -- the fixture chapter -------------------------------------------------------

#: Three pages, three sizes (so three distinct encodings: the detector can tell
#: which page it was handed).
_SOURCE_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 30, 20),
    ("p2.png", 40, 30),
    ("p3.png", 50, 40),
)
_PAGE_COUNT = len(_SOURCE_PAGES)
_TARGET = 1
_DETECT = "detect"

Ring = tuple[tuple[int, int], ...]


def _ring(x0: int, y0: int, x1: int, y1: int) -> Ring:
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))


#: Reading order is right to left, top to bottom (MT-009). Two bands: the top
#: band holds TOP_RIGHT then TOP_LEFT, the bottom band BOTTOM_LEFT. Every ring
#: fits the smallest fixture page (30 x 20), so one set serves every page.
TOP_RIGHT = _ring(18, 1, 26, 6)
TOP_LEFT = _ring(2, 1, 10, 6)
BOTTOM_LEFT = _ring(2, 12, 10, 18)
#: What AC-2 says the event carries, written out: the stored reading order.
READING_ORDER: tuple[Ring, ...] = (TOP_RIGHT, TOP_LEFT, BOTTOM_LEFT)
#: What the fake detector hands over: the exact reverse, wrong at every index
#: but the middle one.
DETECTOR_ORDER: tuple[Ring, ...] = (BOTTOM_LEFT, TOP_LEFT, TOP_RIGHT)


class _Exploded(Exception):
    """The injected detector failure; bespoke so nothing else can satisfy it."""


class _FakeDetector:
    """A `PageDetector`: bytes in, `DETECTOR_ORDER` (or `rings`) out."""

    def __init__(
        self, mask: bytes, rings: Sequence[Ring] = DETECTOR_ORDER, *, explode: bool = False
    ):
        self._mask = mask
        self._rings = tuple(rings)
        self._explode = explode
        self.calls = 0

    def __call__(self, image_bytes: bytes) -> Sequence[RawRegion]:
        self.calls += 1
        if self._explode:
            raise _Exploded("boom-in-the-detector")
        return [
            RawRegion(polygon=ring, mask=self._mask, confidence=0.5, kind="bubble")
            for ring in self._rings
        ]


@dataclass(frozen=True)
class _Fixture:
    source_dir: Path
    project: Project
    mask: bytes
    run_id: int

    def context(self, ordinal: int, emit: Callable[[RunEvent], None]) -> PageContext:
        page = next(page for page in self.project.pages() if page.ordinal == ordinal)
        return PageContext(project=self.project, page=page, run_id=self.run_id, emit=emit)

    def regions(self, rings: Sequence[Ring]) -> tuple[RawRegion, ...]:
        return tuple(
            RawRegion(polygon=ring, mask=self.mask, confidence=0.5, kind="bubble") for ring in rings
        )


def _open_run(project: Project) -> int:
    with project.transaction() as cursor:
        chapter_id = int(cursor.execute("SELECT id FROM chapter").fetchone()[0])
        cursor.execute(
            "INSERT INTO run (chapter_id, started_at) VALUES (?, ?)",
            (chapter_id, "2026-10-01T09:00:00+00:00"),
        )
        return int(cursor.execute("SELECT last_insert_rowid()").fetchone()[0])


@pytest.fixture
def fixture(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
) -> Iterator[_Fixture]:
    source_dir = tmp_path / "scans"
    source_dir.mkdir()
    for index, (filename, width, height) in enumerate(_SOURCE_PAGES):
        (source_dir / filename).write_bytes(png_bytes(width, height, (index * 40, 0, 0)))
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        yield _Fixture(
            source_dir=source_dir,
            project=project,
            mask=one_bit_png(8, 8, [(0, 0, 4, 4)]),
            run_id=_open_run(project),
        )


def _never() -> bool:
    return False


_Projected = tuple[str, int | None, str | None]


def _projected(events: Sequence[RunEvent]) -> list[_Projected]:
    """`(type name, ordinal, stage)`; the measured duration is thrown away (MT-006 PO-7)."""
    return [
        (type(event).__name__, getattr(event, "ordinal", None), getattr(event, "stage", None))
        for event in events
    ]


class _AlwaysRuns:
    """A second stage that is never done, so a page whose detection is skipped
    is still *started* (a per-stage skip) rather than page-skipped."""

    name = "after"

    def run(self, ctx: PageContext) -> None:
        return None

    def is_done(self, ctx: PageContext) -> bool:
        return False


# =============================================================================
# C-1: the event is data
# =============================================================================


def test_regions_detected_carries_an_ordinal_and_the_polygons_and_nothing_else() -> None:
    event = RegionsDetected(ordinal=3, polygons=(TOP_RIGHT, TOP_LEFT))

    assert [f.name for f in dataclasses.fields(event)] == ["ordinal", "polygons"]
    assert (event.ordinal, event.polygons) == (3, (TOP_RIGHT, TOP_LEFT))


def test_regions_detected_cannot_be_mutated_after_it_is_emitted() -> None:
    # It crosses a thread to a widget (MT-059); a consumer that can rewrite it
    # can rewrite what the next consumer sees.
    event = RegionsDetected(ordinal=1, polygons=())
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.ordinal = 2  # type: ignore[misc]


def test_regions_detected_is_exported_and_is_a_member_of_the_run_event_union() -> None:
    assert "RegionsDetected" in events_module.__all__
    assert RegionsDetected in get_args(RunEvent), "RegionsDetected is not in the RunEvent union"


# =============================================================================
# C-2 / AC-2: the stage emits it, after the write, in stored order
# =============================================================================


def test_the_event_carries_the_polygons_the_store_already_holds_when_it_arrives(
    fixture: _Fixture,
) -> None:
    """DV-1's test. The recording `emit` reads the store at the moment it is
    called: the regions must already be there, and be the event's own polygons
    in the same order. A stage that emitted before `write_regions` hands the
    callback an empty store on a first run."""
    seen: list[tuple[RunEvent, tuple[Ring, ...]]] = []

    def emit(event: RunEvent) -> None:
        stored = fixture.project.read_regions(_TARGET)
        seen.append((event, tuple(region.polygon for region in stored)))

    DetectStage(detect=_FakeDetector(fixture.mask)).run(fixture.context(_TARGET, emit))

    assert len(seen) == 1, f"the stage emitted {len(seen)} events for one detected page"
    event, stored_then = seen[0]
    assert isinstance(event, RegionsDetected), f"the stage emitted {event!r}"
    assert stored_then != (), "RegionsDetected was emitted before the regions were written"
    assert event.polygons == stored_then, (
        "the event's polygons are not the regions the store held when it arrived"
    )


def test_the_event_carries_every_polygon_in_reading_order_not_the_detectors_order(
    fixture: _Fixture,
) -> None:
    """DV-2's test. The detector hands the regions over reversed; the event must
    carry them as stored - top-right, top-left, bottom-left - for page 1."""
    seen: list[RunEvent] = []

    DetectStage(detect=_FakeDetector(fixture.mask)).run(fixture.context(_TARGET, seen.append))

    assert seen == [RegionsDetected(ordinal=_TARGET, polygons=READING_ORDER)], (
        f"expected one RegionsDetected for page {_TARGET} in reading order; got {seen!r}"
    )
    # And that order is the store's, read independently of the event.
    stored = tuple(region.polygon for region in fixture.project.read_regions(_TARGET))
    assert stored == READING_ORDER


def test_the_polygons_are_tuples_all_the_way_down_so_the_event_is_a_hashable_value(
    fixture: _Fixture,
) -> None:
    """C-1 types `polygons` as nested tuples. A list anywhere inside would make
    a frozen event that still cannot be hashed or safely shared across a thread."""
    seen: list[RunEvent] = []

    DetectStage(detect=_FakeDetector(fixture.mask)).run(fixture.context(_TARGET, seen.append))

    (event,) = seen
    assert isinstance(event, RegionsDetected)
    assert type(event.polygons) is tuple
    assert all(type(polygon) is tuple for polygon in event.polygons)
    assert all(type(point) is tuple for polygon in event.polygons for point in polygon)
    hash(event)


def test_a_page_with_no_regions_emits_one_event_with_an_empty_tuple(fixture: _Fixture) -> None:
    seen: list[RunEvent] = []

    DetectStage(detect=_FakeDetector(fixture.mask, rings=())).run(
        fixture.context(_TARGET, seen.append)
    )

    assert seen == [RegionsDetected(ordinal=_TARGET, polygons=())]


def test_a_rerun_emits_the_new_regions_not_the_previous_runs(fixture: _Fixture) -> None:
    """The store is replaced (MT-007 A-11); the event describes what is there now."""
    fixture.project.write_regions(_TARGET, fixture.regions(READING_ORDER))
    seen: list[RunEvent] = []

    DetectStage(detect=_FakeDetector(fixture.mask, rings=(TOP_LEFT,))).run(
        fixture.context(_TARGET, seen.append)
    )

    assert seen == [RegionsDetected(ordinal=_TARGET, polygons=(TOP_LEFT,))]


def test_a_detector_that_raises_emits_nothing(fixture: _Fixture) -> None:
    """No regions were written, so there is nothing to report and the event's
    'after the write' promise would be a lie."""
    seen: list[RunEvent] = []

    with pytest.raises(_Exploded):
        DetectStage(detect=_FakeDetector(fixture.mask, explode=True)).run(
            fixture.context(_TARGET, seen.append)
        )

    assert seen == []


# =============================================================================
# AC-2 through the runner: one per detected page, in place, none when skipped
# =============================================================================


def test_each_detected_page_emits_one_regions_detected_between_its_start_and_detect_finishing(
    fixture: _Fixture,
) -> None:
    events: list[RunEvent] = []
    detector = _FakeDetector(fixture.mask)

    outcome = run_chapter(fixture.project, [DetectStage(detect=detector)], events.append, _never)

    assert outcome.outcome == RUN_FINISHED
    body = [row for row in _projected(events) if row[0] not in ("RunStarted", "RunFinished")]
    assert body == [
        row
        for k in range(_PAGE_COUNT)
        for row in (
            ("PageStarted", k, None),
            ("RegionsDetected", k, None),
            ("StageFinished", k, _DETECT),
        )
    ]
    detected = [event for event in events if isinstance(event, RegionsDetected)]
    assert [event.polygons for event in detected] == [READING_ORDER] * _PAGE_COUNT
    assert isinstance(events[-1], RunFinished)


def test_a_page_already_detected_is_skipped_and_emits_no_regions_detected(
    fixture: _Fixture,
) -> None:
    """Page 1 already has regions and detect is the only stage, so the runner
    page-skips it: no `RegionsDetected(1)`, while pages 0 and 2 get theirs."""
    fixture.project.write_regions(_TARGET, fixture.regions(READING_ORDER))
    events: list[RunEvent] = []
    detector = _FakeDetector(fixture.mask)

    run_chapter(fixture.project, [DetectStage(detect=detector)], events.append, _never)

    assert detector.calls == 2, "precondition: page 1's detection was not skipped"
    assert [e.ordinal for e in events if isinstance(e, PageSkipped)] == [_TARGET]
    assert [e.ordinal for e in events if isinstance(e, RegionsDetected)] == [0, 2]


def test_a_page_whose_detect_stage_alone_is_skipped_is_started_but_emits_no_regions_detected(
    fixture: _Fixture,
) -> None:
    """The per-stage skip (MT-036): page 1 is started because the second stage
    has work, but detection is done there, so `run` is never called and no event
    may appear - in particular not one built from the stored regions."""
    fixture.project.write_regions(_TARGET, fixture.regions(READING_ORDER))
    events: list[RunEvent] = []
    detector = _FakeDetector(fixture.mask)

    run_chapter(
        fixture.project, [DetectStage(detect=detector), _AlwaysRuns()], events.append, _never
    )

    assert [e.ordinal for e in events if isinstance(e, PageStarted)] == [0, 1, 2]
    assert [e.ordinal for e in events if isinstance(e, RegionsDetected)] == [0, 2]
    page_one = [row for row in _projected(events) if row[1] == _TARGET]
    assert page_one == [("PageStarted", _TARGET, None), ("StageFinished", _TARGET, "after")]
    assert not any(
        isinstance(e, StageFinished) and e.ordinal == _TARGET and e.stage == _DETECT for e in events
    )
