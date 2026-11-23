"""MT-147 AC-3, AC-4 and C-5: a region the answer lists under `art_text` is
excluded `art` and gets no proposal, through `translate_stage.apply_answer`.

**Oracle partition: mechanical** (C-8). Every expectation is a literal tuple
read off the store - `excluded` per region, `proposed_en` per region - never
recomputed through the code under test.

**The world** is a real `.mtproj` on `tmp_path`: two pages, four regions on
each, four OCR lines on each. The target page is ordinal 1, not 0 (MT-035
DV-3's habit), and page 0 is seeded identically and must stay untouched, so a
write landing on the wrong page is caught.

**The translator is a double at the `PageTranslator` seam** (MT-011 C-1: this
layer may not import `mangatl.translate`). It answers in the key space of the
listing it was handed - the only key space a real translator has - and builds
its `TranslationResult` with `art_text=` only when the test gives it one, so
the controls below construct exactly what every pre-MT-147 site constructs and
run, and pass, against today's stage.

**Why the RED failures look as they do.** `TranslationResult` has no
`art_text` field and `translate_stage` has no `apply_answer` in RED, so each
test that needs either fails on that named absence: a `TypeError` naming
`art_text` from the dataclass, or an `AttributeError` naming `apply_answer`.
`apply_answer` is read off the module at call time (`_apply_answer`), never
imported at the top, so the file always collects.

**Write order (C-5 step 3 before step 4)** is observed with the real store's
two methods wrapped by a recorder (`_record_writes`): the real writes still
happen, and the recorder sees which came first. A `Project` double would pin
which reads `apply_answer` makes, which C-5 leaves to GREEN.

**Timing.** No `pytest-timeout` in this project and no per-test timeout, so
there is no budget in this file to size. Pages are 40x30, masks are one 4x4
rect each through `conftest.one_bit_png`, a few ms per test.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from mangatl.domain.budget import BOOTSTRAP_PAGE_ESTIMATE
from mangatl.domain.events import RunEvent
from mangatl.domain.line import OcrResult
from mangatl.domain.region import RawRegion
from mangatl.domain.translation import CallInfo, TokenUsage, TranslationResult
from mangatl.pipeline import translate_stage
from mangatl.pipeline.stage import BudgetRefused, PageContext
from mangatl.pipeline.translate_stage import TranslateStage
from mangatl.store.intake import read_chapter
from mangatl.store.project import Project, create_project, project_dir_for

if TYPE_CHECKING:
    from mangatl.domain.glossary import PromptContext

_SOURCE_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 40, 30),
    ("p2.png", 40, 30),
)

_TARGET = 1
_OTHER = 0

#: Four regions, four distinct texts. Region 2's is a drawn sound effect.
_LINES: tuple[OcrResult, ...] = (
    OcrResult(text="一つ目の台詞"),
    OcrResult(text="看板の文字"),
    OcrResult(text="ドドド"),
    OcrResult(text="四つ目"),
)

#: A model id `domain.rates.price` knows, so a priced call reaches the ledger.
_MODEL_ID = "claude-opus-5"
_USAGE = TokenUsage(input_tokens=3011, output_tokens=712, cache_read_tokens=0, cache_write_tokens=0)


def _ring(x0: int, y0: int, x1: int, y1: int) -> tuple[tuple[int, int], ...]:
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))


@dataclass
class _Chapter:
    source_dir: Path
    project: Project
    mask: bytes
    run_id: int
    events: list[RunEvent] = field(default_factory=list)

    @property
    def context(self) -> PageContext:
        page = next(page for page in self.project.pages() if page.ordinal == _TARGET)
        return PageContext(
            project=self.project, page=page, run_id=self.run_id, emit=self.events.append
        )

    def seed(self, ordinal: int, excluded: Sequence[str | None] = (None,) * 4) -> None:
        """Four regions on `ordinal`, the i-th carrying `excluded[i]`, and the
        four lines. Regions are stacked top to bottom in one column, so the
        reading order is the order given."""
        regions = tuple(
            RawRegion(
                polygon=_ring(2, 1 + 7 * i, 12, 6 + 7 * i),
                mask=self.mask,
                confidence=0.5,
                kind="bubble",
                **({} if reason is None else {"excluded": reason}),  # type: ignore[arg-type]
            )
            for i, reason in enumerate(excluded)
        )
        self.project.write_regions(ordinal, regions)
        self.project.write_lines(ordinal, _LINES)

    def excluded(self, ordinal: int = _TARGET) -> tuple[str | None, ...]:
        return tuple(region.excluded for region in self.project.read_regions(ordinal))

    def proposed(self, ordinal: int = _TARGET) -> tuple[str | None, ...]:
        return self.project.read_proposed(ordinal)

    def misaligned_flags(self, ordinal: int = _TARGET) -> list[int]:
        rows = self._raw(
            "SELECT line.misaligned FROM region JOIN page ON page.id = region.page_id"
            " JOIN line ON line.region_id = region.id WHERE page.ordinal = ?"
            " ORDER BY region.reading_index",
            (ordinal,),
        )
        return [int(row[0]) for row in rows]

    def ledger_rows(self) -> int:
        ((count,),) = self._raw("SELECT count(*) FROM llm_call", ())
        return int(count)

    def _raw(self, sql: str, parameters: tuple[object, ...]) -> list[tuple[Any, ...]]:
        connection = sqlite3.connect(project_dir_for(self.source_dir) / "project.db")
        try:
            return connection.execute(sql, parameters).fetchall()
        finally:
            connection.close()


@pytest.fixture
def chapter(
    tmp_path: Path, png_bytes: Callable[..., bytes], one_bit_png: Callable[..., bytes]
) -> Iterator[_Chapter]:
    source_dir = tmp_path / "scans"
    source_dir.mkdir()
    for index, (filename, width, height) in enumerate(_SOURCE_PAGES):
        (source_dir / filename).write_bytes(png_bytes(width, height, (index * 40, 0, 0)))

    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        with project.transaction() as cursor:
            chapter_id = int(cursor.execute("SELECT id FROM chapter").fetchone()[0])
            cursor.execute(
                "INSERT INTO run (chapter_id, started_at) VALUES (?, ?)",
                (chapter_id, "2026-11-23T09:00:00+00:00"),
            )
            run_id = int(cursor.execute("SELECT last_insert_rowid()").fetchone()[0])
        world = _Chapter(
            source_dir=source_dir,
            project=project,
            mask=one_bit_png(40, 30, [(3, 2, 7, 6)]),
            run_id=run_id,
        )
        world.seed(_OTHER)
        yield world


# -- the double ------------------------------------------------------------------


class _Answering:
    """A `PageTranslator` that answers `lines`, `misaligned` and `art_text`,
    keyed by the index **in the listing it was handed**, with a priced call.

    `art_text=None` builds the result without the field at all - exactly what
    every construction site before MT-147 builds - so a control using it runs
    against today's `TranslationResult`."""

    def __init__(
        self,
        lines: dict[int, str],
        *,
        art_text: set[int] | None = None,
        misaligned: set[int] | None = None,
        priced: bool = True,
    ) -> None:
        self._lines = lines
        self._art_text = art_text
        self._misaligned = misaligned
        self._priced = priced
        self.seen: list[tuple[OcrResult, ...]] = []

    def __call__(
        self, image: bytes, ocr_results: Sequence[OcrResult], context: PromptContext
    ) -> TranslationResult:
        self.seen.append(tuple(ocr_results))
        extra: dict[str, Any] = {}
        if self._art_text is not None:
            extra["art_text"] = frozenset(self._art_text)
        if self._misaligned is not None:
            extra["misaligned"] = frozenset(self._misaligned)
        return TranslationResult(
            lines=dict(self._lines),
            usage=_USAGE if self._priced else TokenUsage(0, 0, 0, 0),
            call=CallInfo(request_id="msg_art", model_id=_MODEL_ID) if self._priced else None,
            proposed_terms=(),
            **extra,
        )


def _run(chapter: _Chapter, translator: _Answering) -> None:
    TranslateStage(page_estimate=BOOTSTRAP_PAGE_ESTIMATE, translate=translator).run(chapter.context)


def _apply_answer(*args: Any) -> None:
    """`translate_stage.apply_answer`, read at call time so that in RED the
    absence is an `AttributeError` naming it in this test, not a collection
    error for the file."""
    translate_stage.apply_answer(*args)  # type: ignore[attr-defined]


def _result(
    lines: dict[int, str], *, art_text: set[int], misaligned: set[int] | None = None
) -> TranslationResult:
    return TranslationResult(
        lines=lines,
        usage=TokenUsage(0, 0, 0, 0),
        call=None,
        proposed_terms=(),
        misaligned=frozenset(misaligned or ()),
        art_text=frozenset(art_text),  # type: ignore[call-arg]
    )


def _record_writes(monkeypatch: pytest.MonkeyPatch, project: Project) -> list[tuple[Any, ...]]:
    """Wrap the store's two writes on this one `project` so each call is
    recorded, in order, and still performed."""
    calls: list[tuple[Any, ...]] = []
    set_excluded = project.set_excluded
    write_proposed = project.write_proposed

    def recording_set_excluded(ordinal: int, index: int, reason: Any) -> None:
        calls.append(("set_excluded", ordinal, index, reason))
        set_excluded(ordinal, index, reason)

    def recording_write_proposed(
        ordinal: int, proposed: Any, misaligned: Any = frozenset()
    ) -> None:
        calls.append(("write_proposed", ordinal, dict(proposed), frozenset(misaligned)))
        write_proposed(ordinal, proposed, misaligned)

    monkeypatch.setattr(project, "set_excluded", recording_set_excluded)
    monkeypatch.setattr(project, "write_proposed", recording_write_proposed)
    return calls


# -- AC-3: art is excluded, and art wins over a line ----------------------------


def test_regions_the_answer_lists_as_art_are_excluded_art_and_proposed_nothing(
    chapter: _Chapter,
) -> None:
    """**AC-3**: a four-region page; the answer lines regions 0, 1 and 3 and
    lists `art_text: [1, 2]`. Regions 1 and 2 are stored `excluded == "art"`
    with `proposed_en` NULL; regions 0 and 3 carry their proposals."""
    chapter.seed(_TARGET)

    _run(chapter, _Answering({0: "First line.", 1: "SIGN", 3: "Fourth."}, art_text={1, 2}))

    assert chapter.excluded() == (None, "art", "art", None), (
        f"the regions read excluded {chapter.excluded()}; the answer listed 1 and 2 as art"
    )
    assert chapter.proposed() == ("First line.", None, None, "Fourth."), (
        f"the page's proposals are {chapter.proposed()}"
    )


def test_an_art_regions_line_is_discarded_because_art_wins(chapter: _Chapter) -> None:
    """**AC-3**, the clause on its own so a failure reads as the bug: region 1
    is both lined and listed as art, and its English never reaches the store."""
    chapter.seed(_TARGET)

    _run(chapter, _Answering({0: "First line.", 1: "SIGN", 3: "Fourth."}, art_text={1, 2}))

    assert chapter.proposed()[1] is None, (
        f"region 1 is art and still carries the proposal {chapter.proposed()[1]!r}:"
        " art must win over a line for the same region"
    )


def test_control_with_no_art_listed_the_same_answer_excludes_nothing(chapter: _Chapter) -> None:
    """The control for the two tests above: the same lines with no `art_text`
    at all - built the pre-MT-147 way - exclude nothing and store all three
    lines. Without it, a stage that excluded regions 1 and 2 of every page, or
    dropped every second line, would pass them."""
    chapter.seed(_TARGET)

    _run(chapter, _Answering({0: "First line.", 1: "SIGN", 3: "Fourth."}))

    assert chapter.excluded() == (None, None, None, None)
    assert chapter.proposed() == ("First line.", "SIGN", None, "Fourth.")


def test_the_call_is_still_billed_and_the_other_page_untouched_when_art_is_listed(
    chapter: _Chapter,
) -> None:
    """C-5's callers clause: the bill stays where it is, before the write - an
    answer with art in it was still paid for. And the marks land on the page
    being translated, not on page 0."""
    chapter.seed(_TARGET)

    _run(chapter, _Answering({0: "First line."}, art_text={2}))

    assert chapter.ledger_rows() == 1
    assert chapter.excluded(_OTHER) == (None, None, None, None)
    assert chapter.proposed(_OTHER) == (None, None, None, None)


def test_an_art_region_flagged_misaligned_too_is_not_flagged(chapter: _Chapter) -> None:
    """C-5 step 2's other half: art wins over `misaligned` as it wins over a
    line. An art region is no failed translation, and must not read `failed`
    if the user restores it."""
    chapter.seed(_TARGET)

    _run(chapter, _Answering({0: "First line."}, art_text={2}, misaligned={2, 3}))

    assert chapter.excluded() == (None, None, "art", None)
    assert chapter.misaligned_flags() == [0, 0, 0, 1], (
        f"misaligned flags {chapter.misaligned_flags()}: region 2 is art and must not"
        " be flagged; region 3 is not art and must be"
    )


# -- AC-4: the MT-118 mapping, for the new key ----------------------------------


def test_an_art_index_maps_through_the_included_regions_and_the_users_region_stays_user(
    chapter: _Chapter,
) -> None:
    """**AC-4**: region 0 was excluded by the user, so the listing sent is
    regions 1, 2, 3 and the answer's `0` is reading index 1. Region 1 is
    marked `art`; region 0 stays `user`. The lines `{1, 2}` land on regions 2
    and 3. An identity mapping would land the art mark on the user's region
    (which keeps `user`) and leave region 1 unexcluded - DV-3's mutant."""
    chapter.seed(_TARGET, ["user", None, None, None])
    translator = _Answering({1: "Third.", 2: "Fourth."}, art_text={0})

    _run(chapter, translator)

    assert translator.seen == [_LINES[1:]], "the precondition: three regions were sent"
    assert chapter.excluded() == ("user", "art", None, None), (
        f"the regions read excluded {chapter.excluded()}; the answer's art index 0 is"
        " the first region SENT, which is reading index 1"
    )
    assert chapter.proposed() == (None, None, "Third.", "Fourth.")


def test_an_art_index_outside_the_listing_is_refused_before_anything_is_written(
    chapter: _Chapter,
) -> None:
    """C-5 step 1: an art key outside the listing raises `ValueError` naming
    it, and neither the line beside it nor any mark is written. `7`, not `4`:
    the refusal also says how many regions were sent (four), and a needle on
    `4` would be met by the count alone."""
    chapter.seed(_TARGET)

    with pytest.raises(ValueError, match=r"\b7\b"):
        _run(chapter, _Answering({0: "First line."}, art_text={7}, priced=False))

    assert chapter.excluded() == (None, None, None, None)
    assert chapter.proposed() == (None, None, None, None)


# -- C-5: apply_answer, directly --------------------------------------------------


def test_translate_stage_exports_apply_answer() -> None:
    """C-1: `apply_answer` is added to `__all__`, in the sorted order the
    list already uses (RUF022)."""
    assert translate_stage.__all__ == [
        "PageTranslator",
        "TranslateStage",
        "apply_answer",
        "budget_for",
        "pages_remaining",
    ]


def test_apply_answer_marks_art_ascending_before_it_writes_the_proposals(
    chapter: _Chapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-5 steps 3 and 4: one `set_excluded(ordinal, index, "art")` per art
    index, ascending, **then** one `write_proposed` without the art regions'
    lines. Marks first: a crash between them leaves art marked and no
    proposals, which re-translates with the art already excluded; the other
    order leaves a page that reads done with its art typeset."""
    chapter.seed(_TARGET)
    calls = _record_writes(monkeypatch, chapter.project)

    _apply_answer(
        chapter.project,
        _TARGET,
        _result({0: "First line.", 3: "SIGN"}, art_text={3, 1}, misaligned={2}),
        range(4),
    )

    assert calls == [
        ("set_excluded", _TARGET, 1, "art"),
        ("set_excluded", _TARGET, 3, "art"),
        ("write_proposed", _TARGET, {0: "First line."}, frozenset({2})),
    ], f"apply_answer wrote {calls}"


def test_apply_answer_leaves_an_already_excluded_region_its_reason_and_drops_its_line(
    chapter: _Chapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-5 step 3 and PO-2 (the user's answer: keep the existing reason). The
    batch path sends every region, so a `watermark` region can be named in
    `art_text`; it keeps `watermark`, no `set_excluded` is made for it, and its
    line is still dropped. Region 2, included, is marked as usual."""
    chapter.seed(_TARGET, [None, "watermark", None, None])
    calls = _record_writes(monkeypatch, chapter.project)

    _apply_answer(
        chapter.project,
        _TARGET,
        _result({0: "First line.", 1: "WATERMARK"}, art_text={1, 2}),
        range(4),
    )

    assert chapter.excluded() == (None, "watermark", "art", None)
    assert chapter.proposed() == ("First line.", None, None, None)
    assert [call for call in calls if call[0] == "set_excluded"] == [
        ("set_excluded", _TARGET, 2, "art")
    ], f"apply_answer re-marked a region that was already excluded: {calls}"


def test_apply_answer_with_no_art_writes_exactly_what_the_stage_wrote_before(
    chapter: _Chapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The zero of the art set: no mark at all, and one `write_proposed` with
    the mapped lines and misaligned set - the pre-MT-147 write, unchanged."""
    chapter.seed(_TARGET, ["user", None, None, None])
    calls = _record_writes(monkeypatch, chapter.project)

    _apply_answer(
        chapter.project,
        _TARGET,
        _result({0: "Second.", 2: "Fourth."}, art_text=set(), misaligned={1}),
        [1, 2, 3],
    )

    assert calls == [("write_proposed", _TARGET, {1: "Second.", 3: "Fourth."}, frozenset({2}))]
    assert chapter.excluded() == ("user", None, None, None)


# -- R-2: a page with nothing to send is not refused by the budget guard ---------
#
# Diff review round 1, finding 1: the guard ran before `included` was built, so
# a page whose every region is already excluded - all `art`, after a run that
# marked them - was refused within one page estimate of the ceiling although it
# would send nothing. The ceiling here is half of one page estimate, written by
# raw SQL as `test_budget_run._set_ceiling` writes it (no shipped writer).

#: Less than one page estimate: $0.00 spent + one estimate projected > this.
_UNDER_ONE_PAGE_MICRO = BOOTSTRAP_PAGE_ESTIMATE.micro() // 2


def _set_ceiling_under_one_page(project: Project) -> None:
    with project.transaction() as cursor:
        cursor.execute("UPDATE chapter SET budget_ceiling_micro_usd = ?", (_UNDER_ONE_PAGE_MICRO,))


def test_a_page_whose_every_region_is_already_art_is_not_refused_by_the_budget(
    chapter: _Chapter,
) -> None:
    """**R-2**: every region of the page is already `art`, and less than one
    page estimate is left under the ceiling. Nothing would be sent, so the
    stage completes: no `BudgetRefused`, no translator call, no bill, no
    event, and the store reads as it did before."""
    chapter.seed(_TARGET, ["art", "art", "art", "art"])
    _set_ceiling_under_one_page(chapter.project)
    translator = _Answering({})

    try:
        _run(chapter, translator)
    except BudgetRefused as refusal:
        pytest.fail(
            "a page with every region already excluded was refused by the budget"
            f" guard although it sends nothing: {refusal}"
        )

    assert translator.seen == [], (
        f"the translator was handed {translator.seen} for a page with nothing to send"
    )
    assert chapter.ledger_rows() == 0
    assert chapter.events == []
    assert chapter.excluded() == ("art", "art", "art", "art")
    assert chapter.proposed() == (None, None, None, None)


def test_control_the_same_budget_with_one_region_still_included_is_refused(
    chapter: _Chapter,
) -> None:
    """The control for the test above: the same ceiling, three regions `art`
    and one still included. One region would be sent, so the guard refuses
    before the translator is called - the test above is about an empty page,
    not about a guard that is gone or skipped whenever any region is excluded."""
    chapter.seed(_TARGET, ["art", "art", None, "art"])
    _set_ceiling_under_one_page(chapter.project)
    translator = _Answering({0: "Third."})

    with pytest.raises(BudgetRefused):
        _run(chapter, translator)

    assert translator.seen == []
    assert chapter.ledger_rows() == 0
    assert chapter.proposed() == (None, None, None, None)
