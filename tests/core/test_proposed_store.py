"""`store.project.Project.write_proposed` / `read_proposed`: C-6.

This is where **AC-5**'s "remains NULL" and **AC-6**'s "nothing is written to
the store" are actually decided. The stage-level halves are in
`tests/core/test_translate_stage.py`.

**NULL `proposed_en` *is* "untranslated".** AC-5 says a region is flagged
untranslated and C-6 is explicit that this is **not a new column**:
`line.proposed_en` is already `TEXT` and nullable, and `store/schema.py` says so
deliberately - *"NULL `final_en` means unedited ... `proposed_en` too, because
OCR writes `source_ja` before translation exists."* A story that added an
`untranslated` column would need a schema version bump and a `_migrate_to_v3`,
and would stop being one RED->GREEN cycle. `SCHEMA_VERSION` staying at 2 is
asserted below, because that is the cheapest way to notice it drifting.

**A `Mapping` keyed by reading index, not a positional `Sequence`** - unlike
`write_lines`, which is positional (MT-007 A-11). Two reasons, both criteria:
AC-5 needs "region 3 was omitted" to be distinguishable from "region 3 was
translated as the empty string", and AC-6 needs an index outside the page to be
*expressible* so that it can be rejected.

**`write_proposed` updates only the rows it names.** By the time a user re-runs
a chapter, those rows carry translations that cost real money
(`architecture.md` §4/§6), so it never clears the page first. That is the most
expensive silent bug available in this story and it has its own test below.

**Timing.** No `pytest-timeout` in this project and no per-test timeout exists,
so there is no budget in this file to size; if a later story adds one, every
test and hook here needs one. The dominant cost is `conftest._one_bit_png`
(MT-009: 281 ms page-sized, 7 ms small), so the fixture pages are 30-50 px wide,
exactly as `test_ocr_stage.py` sizes its own.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from mangatl.domain.line import OcrResult
from mangatl.domain.region import RawRegion
from mangatl.store.intake import read_chapter
from mangatl.store.project import (
    SCHEMA_VERSION,
    Project,
    create_project,
    project_dir_for,
)

_SOURCE_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 30, 20),
    ("p2.png", 40, 30),
    ("p3.png", 50, 40),
)

#: The page every test runs against, and it is **not ordinal 0** - MT-035 DV-3's
#: reason: a mutation of `write_proposed(ctx.page.ordinal, ...)` to
#: `write_proposed(0, ...)` is one token, a plausible typo, and invisible to a
#: test whose page sits at 0.
_TARGET_ORDINAL = 1
_PAGE_WIDTH, _PAGE_HEIGHT = _SOURCE_PAGES[_TARGET_ORDINAL][1], _SOURCE_PAGES[_TARGET_ORDINAL][2]

#: What OCR left on the page before translation ran. Distinct, and one of them
#: is the `ocr_empty` case, so "the write did not disturb the Japanese" has
#: something to be false about in both directions.
_LINES: tuple[OcrResult, ...] = (
    OcrResult(text="醜鬼が人間の言う通りに動いたりね"),
    OcrResult(text="", ocr_empty=True),
    OcrResult(text="……なるほど"),
)

#: A previous run's proposals, on every region. The money `architecture.md`
#: §4/§6 is about.
_EXISTING: dict[int, str] = {
    0: "A demon obeying a human? Please.",
    1: "",
    2: "...I see.",
}


def _ring(x0: int, y0: int, x1: int, y1: int) -> tuple[tuple[int, int], ...]:
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))


@dataclass(frozen=True)
class _Fixture:
    source_dir: Path
    project: Project
    mask: bytes

    @property
    def regions(self) -> tuple[RawRegion, ...]:
        """Three regions **already in reading order**, as detect left them.

        Their rectangles are deliberately not in geometric order - region 0 is
        to the right of region 1 - so `read_proposed`'s "ordered by
        `reading_index`" is a claim about the stored index rather than one a
        `rowid` or a `polygon` sort would satisfy by accident.
        """
        return (
            RawRegion(polygon=_ring(20, 2, 30, 8), mask=self.mask, confidence=0.5, kind="bubble"),
            RawRegion(polygon=_ring(2, 2, 12, 8), mask=self.mask, confidence=0.75, kind="bubble"),
            RawRegion(polygon=_ring(2, 20, 12, 28), mask=self.mask, confidence=0.25, kind="box"),
        )

    def seed(self, *, proposals: bool = False, ordinal: int = _TARGET_ORDINAL) -> None:
        """Regions, then lines, then - optionally - a previous run's English."""
        self.project.write_regions(ordinal, self.regions)
        self.project.write_lines(ordinal, _LINES)
        if proposals:
            self.project.write_proposed(ordinal, _EXISTING)


@pytest.fixture
def fixture(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
) -> Iterator[_Fixture]:
    """A three-page project on `tmp_path`, scans in a `scans/` subfolder.

    A subfolder so that `<source>.mtproj` and `<source>_en` are also inside
    `tmp_path` and the test leaves nothing outside its own directory -
    `test_ocr_stage.py` and `test_detect_stage.py` make the same choice.
    """
    source_dir = tmp_path / "scans"
    source_dir.mkdir()
    for index, (filename, width, height) in enumerate(_SOURCE_PAGES):
        (source_dir / filename).write_bytes(png_bytes(width, height, (index * 40, 0, 0)))

    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        yield _Fixture(
            source_dir=source_dir,
            project=project,
            mask=one_bit_png(_PAGE_WIDTH, _PAGE_HEIGHT, [(0, 0, 4, 4)]),
        )


# -- the shape of the store ----------------------------------------------------


def test_storing_a_proposal_needs_no_schema_version_bump() -> None:
    """C-6. `line.proposed_en` already exists, already is nullable, and
    `schema.py` already says why. If this number moves, the story grew a
    migration and a `_migrate_to_v3` and stopped being one cycle.

    **MT-012 is that story, and it grew that migration on purpose** (PO-5):
    AC-2's rate-table version per ledger row, AC-3's integer micro-dollars and
    AC-4's append-only triggers are all unsatisfiable at version 2. What this
    test still says is what it always said - MT-009 did not need a bump - so
    the number is updated rather than the assertion removed. If it moves again,
    ask the same question again."""
    assert SCHEMA_VERSION == 3


def test_the_two_methods_are_named_on_the_project_beside_their_line_siblings() -> None:
    """C-6: "two new methods ... mirroring `write_lines`/`read_lines`". The
    existing four are asserted alongside, because `## Callers of changed
    signatures` says none of them changes and this is the cheapest place to keep
    that true."""
    for name in ("write_proposed", "read_proposed"):
        assert callable(getattr(Project, name)), f"Project.{name} is missing"
    for name in ("write_lines", "read_lines", "write_regions", "read_regions"):
        assert callable(getattr(Project, name)), f"Project.{name} was removed"


# -- the round trip ------------------------------------------------------------


def test_a_proposal_is_stored_against_the_region_at_that_reading_index(
    fixture: _Fixture,
) -> None:
    """The mapping is by reading index, and the read comes back in that order.

    Not a positional coincidence: the fixture's regions are in reading order but
    **not** in geometric order, so a reader that sorted by polygon would hand
    back region 1's English against region 0.
    """
    fixture.seed()

    fixture.project.write_proposed(_TARGET_ORDINAL, {0: "Alpha.", 2: "Gamma."})

    assert fixture.project.read_proposed(_TARGET_ORDINAL) == ("Alpha.", None, "Gamma.")


def test_a_region_with_no_proposal_reads_back_as_none(fixture: _Fixture) -> None:
    """**AC-5**, at the level the criterion is written about: region 3's - here
    region 1's - `proposed_en` remains NULL, and the others are still assigned.
    The page is not discarded."""
    fixture.seed()

    fixture.project.write_proposed(_TARGET_ORDINAL, {0: "Alpha.", 2: "Gamma."})
    proposed = fixture.project.read_proposed(_TARGET_ORDINAL)

    assert proposed[1] is None, "an omitted region must read back as NULL, not as ''"
    assert proposed[0] is not None and proposed[2] is not None


def test_the_empty_string_is_distinguishable_from_an_omitted_region(
    fixture: _Fixture,
) -> None:
    """C-6's stated reason for a `Mapping` rather than a `Sequence`, as the one
    assertion that can tell the two apart.

    A model that proposes `""` for a bubble of pure punctuation has answered;
    a model that omitted the bubble has not. `read_proposed` returning `""` for
    the first and `None` for the second is the whole difference, and an
    implementation storing `""` for both - or `NULL` for both - passes every
    other test in this file.
    """
    fixture.seed()

    fixture.project.write_proposed(_TARGET_ORDINAL, {1: ""})
    proposed = fixture.project.read_proposed(_TARGET_ORDINAL)

    assert proposed[1] == ""
    assert proposed[1] is not None
    assert proposed[0] is None and proposed[2] is None


def test_a_page_with_no_regions_reads_back_as_an_empty_tuple(fixture: _Fixture) -> None:
    """The zero of zero-one-many. A page the detector found nothing on, or one
    that has not been detected yet, is the normal state of every page before the
    detect stage - empty rather than an exception, exactly as `read_lines` is."""
    assert fixture.project.read_proposed(_TARGET_ORDINAL) == ()


def test_a_single_region_page_round_trips(fixture: _Fixture) -> None:
    """The one of zero-one-many."""
    fixture.project.write_regions(_TARGET_ORDINAL, fixture.regions[:1])
    fixture.project.write_lines(_TARGET_ORDINAL, _LINES[:1])

    fixture.project.write_proposed(_TARGET_ORDINAL, {0: "Alpha."})

    assert fixture.project.read_proposed(_TARGET_ORDINAL) == ("Alpha.",)


def test_an_empty_mapping_writes_nothing_and_raises_nothing(fixture: _Fixture) -> None:
    """AC-7's page reaches the store as `{}` (C-2: "an EMPTY mapping is AC-7's
    no-call page"), and it must be a no-op rather than an error or a clear."""
    fixture.seed(proposals=True)

    fixture.project.write_proposed(_TARGET_ORDINAL, {})

    assert fixture.project.read_proposed(_TARGET_ORDINAL) == (
        "A demon obeying a human? Please.",
        "",
        "...I see.",
    )


# -- the expensive silent bug --------------------------------------------------


def test_a_write_leaves_every_row_it_does_not_name_exactly_as_it_was(
    fixture: _Fixture,
) -> None:
    """C-6: `write_proposed` **updates only the rows it names** and never clears
    the page first.

    This is the most expensive thing in the story to get wrong and the hardest
    to see. A re-run of a chapter where the model omits region 2 this time must
    leave region 2's previous English alone: it cost real money
    (`architecture.md` §4/§6) and the user may already have accepted it. An
    implementation that did `UPDATE line SET proposed_en = NULL` for the page
    before writing passes every other test in this file, because every other
    test starts from an empty page.
    """
    fixture.seed(proposals=True)

    fixture.project.write_proposed(_TARGET_ORDINAL, {1: "A fresh line for region 1."})

    assert fixture.project.read_proposed(_TARGET_ORDINAL) == (
        "A demon obeying a human? Please.",
        "A fresh line for region 1.",
        "...I see.",
    )


def test_a_write_does_not_disturb_the_japanese_the_ocr_stage_left(
    fixture: _Fixture,
) -> None:
    """The other direction of the same upsert. `line` rows carry `source_ja` and
    `ocr_empty`; a `write_proposed` implemented as an INSERT ... ON CONFLICT
    that named those columns in its `DO UPDATE` would blank the transcription
    the OCR stage paid 50 ms a region for."""
    fixture.seed()

    fixture.project.write_proposed(_TARGET_ORDINAL, {0: "Alpha.", 1: "Beta.", 2: "Gamma."})

    assert fixture.project.read_lines(_TARGET_ORDINAL) == _LINES


def test_a_write_touches_only_the_page_it_names(fixture: _Fixture) -> None:
    """MT-035 DV-3's mutation, at this level: `write_proposed(0, ...)` in place
    of `write_proposed(ctx.page.ordinal, ...)`. The target page is ordinal 1, so
    page 0's rows are what a mis-aimed write lands on."""
    fixture.seed()
    fixture.seed(ordinal=0)

    fixture.project.write_proposed(_TARGET_ORDINAL, {0: "Alpha.", 1: "Beta.", 2: "Gamma."})

    assert fixture.project.read_proposed(0) == (None, None, None)
    assert fixture.project.read_proposed(2) == ()


# -- AC-6 at the store: an index the page does not have ------------------------


def test_an_index_the_page_does_not_have_is_refused_and_nothing_is_written(
    fixture: _Fixture,
) -> None:
    """**AC-6**'s "nothing is written to the store", at the store.

    C-6 says the `Mapping` exists so that an index outside the page is
    *expressible* **so that it can be rejected**, and a rejection needs a named
    type. See MT-011 `## Contract` C-6's RED amendment for why it is
    `ValueError` rather than `UnknownRegionIndex`: `mangatl.store` sits *below*
    `mangatl.translate` in the layers contract and may not import it, and
    `write_lines`'s `zip(..., strict=True)` already raises `ValueError` for
    exactly this class of caller mistake.

    "Nothing is written" is the half that matters: the write opens its own
    transaction, so a refusal partway through a mapping must roll back the
    regions it had already reached rather than leaving half a page translated.
    """
    fixture.seed()

    with pytest.raises(ValueError, match=r"\b9\b"):
        fixture.project.write_proposed(_TARGET_ORDINAL, {0: "Alpha.", 9: "A ninth bubble."})

    assert fixture.project.read_proposed(_TARGET_ORDINAL) == (None, None, None)


def test_an_index_one_past_the_end_of_the_page_is_refused_too(fixture: _Fixture) -> None:
    """The boundary: the page has three regions, so `3` is the off-by-one a
    caller counting from one produces, and the value a bounds check written as
    `index > len(regions)` lets through."""
    fixture.seed()

    with pytest.raises(ValueError, match=r"\b3\b"):
        fixture.project.write_proposed(_TARGET_ORDINAL, {3: "A fourth bubble."})


# -- C-6: it opens its own transaction -----------------------------------------


def test_write_proposed_refuses_a_caller_that_already_holds_a_transaction(
    fixture: _Fixture,
) -> None:
    """C-6's last bullet. `Project.transaction()` is deliberately **not
    reentrant** (MT-005 PO-5) - `with conn:` does not nest, so the inner exit
    would commit and defeat the outer rollback - and `write_proposed` opens its
    own, exactly as `write_lines` and `write_regions` do.

    So `TranslateStage.run` must not wrap the call, and this is what makes that
    a fact rather than a note in a docstring.
    """
    fixture.seed()

    with pytest.raises(RuntimeError, match="reentrant"), fixture.project.transaction():
        fixture.project.write_proposed(_TARGET_ORDINAL, {0: "Alpha."})


def test_read_proposed_is_usable_inside_a_transaction(fixture: _Fixture) -> None:
    """The read is a read: `read_lines` and `read_regions` both go straight to
    the connection and neither opens a transaction, so a caller already holding
    one can still ask what is stored. Without this, `is_done` could not be
    called from anywhere that holds one."""
    fixture.seed(proposals=True)

    with fixture.project.transaction():
        assert fixture.project.read_proposed(_TARGET_ORDINAL)[0] is not None
