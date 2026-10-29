"""`TranslateStage` and an excluded region: never sent, never proposed for
(MT-118 AC-5, AC-6, AC-7; C-4).

The stage hands its translator **only the included regions**, as a contiguous
listing - the model never learns an excluded region existed (PO-3) - and maps
the answer's indices (`0..len(sent)-1`) back to reading indices before writing.
The translator packages are unchanged, so everything here is observed at the
`PageTranslator` seam and in the store.

**Why a separate file from `test_translate_stage.py`.** That file is MT-011's
specification and every test in it builds `RawRegion`s without the new field;
this one needs `excluded=` in its fixture, which does not exist in RED. Kept
apart, the older suite keeps running while this one is red.

**AC-6's guard is not the stage's.** The no-call rule is `all(result.ocr_empty
...)` over what the translator is handed, and it lives inside the translators
(`translate/client.py:86`, `translate/gemini.py:139`), which this layer may not
import (MT-011 C-1). `_Guarded` below applies the same rule, word for word, so
"the guard fires" is observable here as "no call was priced": no ledger row, no
`CallPriced`, no proposal. What makes AC-6 true is the stage handing over only
`ocr_empty` results, and that is what is asserted first in each test.

**The target page is ordinal 1, not 0** (MT-035 DV-3), and page 0 carries a
*different* exclusion, so a stage that read `read_regions(0)` sends the wrong
set and is caught.

**Timing.** No `pytest-timeout` in this project; pages are 30-50 px and the
one-bit mask is the dominant cost (`test_translate_stage.py`'s measurement).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from mangatl.domain.budget import BOOTSTRAP_PAGE_ESTIMATE
from mangatl.domain.events import CallPriced, RunEvent
from mangatl.domain.glossary import GlossaryEntry
from mangatl.domain.line import OcrResult
from mangatl.domain.region import RawRegion
from mangatl.domain.translation import CallInfo, TokenUsage, TranslationResult
from mangatl.pipeline.stage import PageContext
from mangatl.pipeline.translate_stage import TranslateStage
from mangatl.store.glossary import read_entries, upsert
from mangatl.store.intake import read_chapter
from mangatl.store.project import Project, create_project, project_dir_for

if TYPE_CHECKING:
    from mangatl.domain.glossary import PromptContext

_SOURCE_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 30, 20),
    ("p2.png", 40, 30),
    ("p3.png", 50, 40),
)

_TARGET_ORDINAL = 1

#: What OCR left on the target page: three regions, three distinct texts.
_A = OcrResult(text="一つ目の台詞")
_B = OcrResult(text="透かしの文字")
_C = OcrResult(text="三つ目")
_LINES: tuple[OcrResult, ...] = (_A, _B, _C)

#: AC-6's page: the included regions read empty, the excluded middle one has text.
_EMPTY = OcrResult(text="", ocr_empty=True)
_EMPTY_AROUND_TEXT: tuple[OcrResult, ...] = (_EMPTY, _B, _EMPTY)

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
        page = next(page for page in self.project.pages() if page.ordinal == _TARGET_ORDINAL)
        return PageContext(
            project=self.project, page=page, run_id=self.run_id, emit=self.events.append
        )

    def seed(
        self,
        excluded: Sequence[str | None],
        lines: Sequence[OcrResult] = _LINES,
        *,
        ordinal: int = _TARGET_ORDINAL,
    ) -> None:
        """Three regions on `ordinal`, the i-th carrying `excluded[i]`, and
        their lines.

        The field is passed only when it is set, so a page with nothing
        excluded is built exactly as every pre-MT-118 site builds one - which
        lets the controls below run, and pass, against today's stage in RED."""
        regions = tuple(
            RawRegion(
                polygon=_ring(2, 2 + 8 * i, 12, 8 + 8 * i),
                mask=self.mask,
                confidence=0.5,
                kind="bubble",
                **({} if reason is None else {"excluded": reason}),  # type: ignore[arg-type]
            )
            for i, reason in enumerate(excluded)
        )
        self.project.write_regions(ordinal, regions)
        self.project.write_lines(ordinal, lines)

    def ledger_rows(self) -> int:
        connection = sqlite3.connect(project_dir_for(self.source_dir) / "project.db")
        try:
            return int(connection.execute("SELECT count(*) FROM llm_call").fetchone()[0])
        finally:
            connection.close()

    def priced(self) -> list[CallPriced]:
        return [event for event in self.events if isinstance(event, CallPriced)]


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
                (chapter_id, "2026-10-29T09:00:00+00:00"),
            )
            run_id = int(cursor.execute("SELECT last_insert_rowid()").fetchone()[0])
        yield _Chapter(
            source_dir=source_dir,
            project=project,
            mask=one_bit_png(40, 30, [(0, 0, 4, 4)]),
            run_id=run_id,
        )


class _Guarded:
    """A `PageTranslator` that applies the translators' own no-call guard.

    `all(result.ocr_empty for result in ocr_results)` - `translate/client.py`
    and `translate/gemini.py` verbatim - returns the wordless-page result with
    `call=None`, exactly as they do. Otherwise it "calls the model": a priced
    `CallInfo` and the scripted `lines`, keyed by the index **in the listing it
    was handed**, which is all a real translator can key by."""

    def __init__(self, lines: dict[int, str] | None = None) -> None:
        self._lines = dict(lines or {})
        self.seen: list[tuple[OcrResult, ...]] = []
        self.made_a_call = 0

    def __call__(
        self, image: bytes, ocr_results: Sequence[OcrResult], context: PromptContext
    ) -> TranslationResult:
        self.seen.append(tuple(ocr_results))
        if all(result.ocr_empty for result in ocr_results):
            return TranslationResult(
                lines={}, usage=TokenUsage(0, 0, 0, 0), call=None, proposed_terms=()
            )
        self.made_a_call += 1
        return TranslationResult(
            lines=dict(self._lines),
            usage=_USAGE,
            call=CallInfo(request_id="msg_excluded", model_id=_MODEL_ID),
            proposed_terms=(),
        )


def _run(chapter: _Chapter, translator: _Guarded) -> None:
    TranslateStage(page_estimate=BOOTSTRAP_PAGE_ESTIMATE, translate=translator).run(chapter.context)


# -- AC-5 ----------------------------------------------------------------------


def test_an_excluded_region_is_not_sent_and_the_answer_is_mapped_back_around_it(
    chapter: _Chapter,
) -> None:
    """**AC-5**: the translator is handed **two** results - the first and the
    third region's, in that order - and its answer `{0: "A", 1: "C"}`, keyed by
    the listing it saw, lands on reading indices 0 and 2. The excluded region's
    `proposed_en` stays NULL.

    Page 0 carries a different exclusion (its first region), so a stage that
    read page 0's regions would send `(B, C)` and is caught on the first
    assertion."""
    chapter.seed(["watermark", None, None], ordinal=0)
    chapter.seed([None, "watermark", None])
    translator = _Guarded({0: "A", 1: "C"})

    _run(chapter, translator)

    assert translator.seen == [(_A, _C)], (
        f"the translator was handed {len(translator.seen[0])} result(s); AC-5 sends"
        " the two included regions and never the excluded one"
    )
    assert chapter.project.read_proposed(_TARGET_ORDINAL) == ("A", None, "C")


def test_with_nothing_excluded_the_same_page_sends_three_and_stores_three(
    chapter: _Chapter,
) -> None:
    """AC-5's control: the same page, nothing excluded - three results handed
    over and `("A", "B", "C")` stored. Without it, a stage that dropped the
    middle region of every page would pass the test above."""
    chapter.seed([None, None, None])
    translator = _Guarded({0: "A", 1: "B", 2: "C"})

    _run(chapter, translator)

    assert translator.seen == [(_A, _B, _C)]
    assert chapter.project.read_proposed(_TARGET_ORDINAL) == ("A", "B", "C")


def test_an_excluded_first_region_shifts_every_answer_by_one(chapter: _Chapter) -> None:
    """The mapping, from the other end: with region 0 excluded the listing is
    `(B, C)`, and the model's `0` is reading index 1. A stage that wrote the
    answer's keys straight through would put "B" on the excluded region."""
    chapter.seed(["user", None, None])
    translator = _Guarded({0: "B", 1: "C"})

    _run(chapter, translator)

    assert translator.seen == [(_B, _C)]
    assert chapter.project.read_proposed(_TARGET_ORDINAL) == (None, "B", "C")


def test_a_partly_excluded_page_is_done_once_an_included_region_has_a_proposal(
    chapter: _Chapter,
) -> None:
    """C-4: `is_done` is unchanged - a page whose only proposal-less region is
    the excluded one is done, so a resumed run does not pay for it again."""
    chapter.seed([None, "watermark", None])
    stage = TranslateStage(page_estimate=BOOTSTRAP_PAGE_ESTIMATE, translate=_Guarded({0: "A"}))

    stage.run(chapter.context)

    assert stage.is_done(chapter.context) is True


# -- AC-6 ----------------------------------------------------------------------


def test_a_page_whose_only_text_is_excluded_makes_no_call(chapter: _Chapter) -> None:
    """**AC-6**: the included regions are both `ocr_empty` and the excluded one
    has text. The translator is handed only the two empty results, so the
    existing guard fires - no ledger row, no `CallPriced`, no proposal."""
    chapter.seed([None, "watermark", None], _EMPTY_AROUND_TEXT)
    translator = _Guarded({0: "A", 1: "B", 2: "C"})

    _run(chapter, translator)

    assert translator.seen == [(_EMPTY, _EMPTY)], (
        "the translator was handed the excluded region's text, so the no-call"
        " guard over what it is handed cannot fire"
    )
    assert translator.made_a_call == 0
    assert chapter.ledger_rows() == 0
    assert chapter.priced() == []
    assert chapter.project.read_proposed(_TARGET_ORDINAL) == (None, None, None)


def test_the_same_page_with_the_region_restored_makes_a_call(chapter: _Chapter) -> None:
    """AC-6's control: un-exclude that region and a call is made - one ledger
    row, one `CallPriced`, and the proposal stored. Without it, a guard that
    never let anything through would pass the test above."""
    chapter.seed([None, "watermark", None], _EMPTY_AROUND_TEXT)
    chapter.project.set_excluded(_TARGET_ORDINAL, 1, None)
    translator = _Guarded({1: "B"})

    _run(chapter, translator)

    assert translator.seen == [_EMPTY_AROUND_TEXT]
    assert translator.made_a_call == 1
    assert chapter.ledger_rows() == 1
    assert [event.ordinal for event in chapter.priced()] == [_TARGET_ORDINAL]
    assert chapter.project.read_proposed(_TARGET_ORDINAL) == (None, "B", None)


def test_a_page_with_every_region_excluded_hands_over_nothing_and_makes_no_call(
    chapter: _Chapter,
) -> None:
    """AC-6's edge, pinned rather than special-cased (C-4): with no included
    region the translator is handed an empty sequence, `all([])` is `True`, and
    the existing guard makes no call. Nothing is priced and nothing proposed,
    and the page is never done - re-running it is free."""
    chapter.seed(["watermark", "user", "watermark"])
    translator = _Guarded({0: "A"})
    stage = TranslateStage(page_estimate=BOOTSTRAP_PAGE_ESTIMATE, translate=translator)

    stage.run(chapter.context)

    assert translator.seen == [()]
    assert translator.made_a_call == 0
    assert chapter.ledger_rows() == 0
    assert chapter.priced() == []
    assert chapter.project.read_proposed(_TARGET_ORDINAL) == (None, None, None)
    assert stage.is_done(chapter.context) is False


# -- AC-7 ----------------------------------------------------------------------

#: A name that appears in the excluded region's text (`_B`) and in no other.
_TERM = GlossaryEntry("透かし", "Watermark", "name", 0, 0, "model")


def test_a_glossary_term_only_in_excluded_text_is_not_marked_seen(chapter: _Chapter) -> None:
    """**AC-7**: the excluded region's `source_ja` contains a glossary term and
    no included region's does, so the term's `last_seen_page` stays where it
    was - the excluded text is not handed to `_update_glossary`."""
    assert _TERM.term_ja in _B.text
    assert all(_TERM.term_ja not in line.text for line in (_A, _C))
    upsert(chapter.project, _TERM)
    chapter.seed([None, "watermark", None])

    _run(chapter, _Guarded({0: "A", 1: "C"}))

    assert read_entries(chapter.project) == [_TERM]


def test_the_same_term_in_included_text_is_marked_seen_on_the_page(chapter: _Chapter) -> None:
    """AC-7's control: nothing excluded, and the same term is last seen on the
    target page. Without it, a glossary that never moved would pass above."""
    upsert(chapter.project, _TERM)
    chapter.seed([None, None, None])

    _run(chapter, _Guarded({0: "A", 1: "B", 2: "C"}))

    assert read_entries(chapter.project) == [
        GlossaryEntry("透かし", "Watermark", "name", 0, _TARGET_ORDINAL, "model")
    ]
