"""MT-105: the run proposes the glossary once, before any page is translated.

`pipeline.prelude.glossary_prelude` builds a `ChapterStep`. Since **MT-130** the
runner calls it between its two passes - after the reading pass, before the
translating pass's first `PageStarted` (MT-130 PO-5 supersedes MT-105's "before
the first page"). These tests drive it through the **real** `run_chapter` as a
two-pass run: the reading pass is `_AlreadyRead` (the fixture has already stored
what OCR would have), and the recording page stage is the translating pass
(`after_prelude`), so every "before any page stage" below now reads "before the
translating pass's first stage". A fake proposer stands where
`partial(gemini.propose_glossary, client)` stands in production.

**Oracle partition** (the story's): AC-5 is *settled* - the rate row's $2.00 in
and $12.00 out per million tokens are read out, not derived, so a token costs 2
micro-dollars in and 12 out. Everything else is *mechanical* and pinned
exactly. The pass's own cost is worked by hand:

    50,000 in x $2.00 + 3,000 out x $12.00 = 100,000 + 36,000 = 136,000 micro

**The fixture seeds OCR lines through the store first** (PO-4): a fresh chapter
has none, and the prelude skips an empty listing (PO-1, AC-7). Page 1 (ordinal 1)
is left with no lines on purpose, between two pages that have them, so a
prelude that dropped empty pages before handing them over would renumber
"Page 3" as "Page 2" in the listing - `glossary_pass_text` numbers by index.

**Imports of the module under test are inside the helpers**, so that in RED
its absence fails each test on its own and does not take this file dark at
collection.

**The single-transaction clause** is pinned with a sqlite trigger that refuses
the marker's write, wherever and however the implementation writes it: if the
upserts and the mark share one transaction, the refusal rolls the terms back
too; if they do not, the terms survive and the test fails. No internal of the
prelude is reached for.

**What these tests do NOT constrain**, so it stays GREEN's choice: the value of
`CallPriced.projection` (only its type), how the prelude reads the pages,
whether excluded regions' lines reach the listing (no fixture excludes one),
the wording of any message, and whether the prelude runs at all on a run
whose every page is already done (AC-2 is satisfied by the marker either way).

**Timing.** No `pytest-timeout` in this project, so there is no budget to size.
Every test builds a three-page chapter of tiny PNGs on `tmp_path`.
"""

from __future__ import annotations

import dataclasses
import inspect
import sqlite3
import typing
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from mangatl.domain.budget import DEFAULT_CEILING, Projection
from mangatl.domain.events import (
    CallPriced,
    PageStarted,
    RunAborted,
    RunEvent,
    RunStarted,
)
from mangatl.domain.glossary import (
    MAX_GLOSSARY_TOKENS,
    GlossaryEntry,
    ProposedTerm,
    estimate_tokens,
    render_block,
)
from mangatl.domain.line import OcrResult
from mangatl.domain.money import Usd
from mangatl.domain.rates import price
from mangatl.domain.region import RawRegion
from mangatl.domain.translation import CallInfo, GlossaryProposal, TokenUsage
from mangatl.pipeline.continuity import build_prompt_context
from mangatl.pipeline.runner import BUDGET, RUN_ABORTED, RUN_FINISHED, RunOutcome, run_chapter
from mangatl.pipeline.stage import PageContext
from mangatl.store.glossary import read_entries
from mangatl.store.intake import read_chapter
from mangatl.store.ledger import record_call
from mangatl.store.project import PAGE_DONE, PAGE_PENDING, Project, create_project, project_dir_for
from mangatl.translate.glossary_pass import GLOSSARY_PASS_MAX_OUTPUT_TOKENS, glossary_pass_text

# -- the numbers ---------------------------------------------------------------

_GEMINI = "gemini-3.1-pro-preview"
#: Not in the rate table: `price` raises `UnknownModel` for it.
_UNPRICED = "gemini-0-not-a-model"

#: The rate row, read out (AC-5, settled): micro-dollars per token.
_IN_MICRO_PER_TOKEN = 2
_OUT_MICRO_PER_TOKEN = 12

_PASS_USAGE = TokenUsage(50_000, 3_000, 0, 0)
#: Worked by hand in the module docstring - not read out of `price`.
_PASS_MICRO = 136_000

_TERMS = (
    ProposedTerm("ケンジ", "Kenji", "name"),
    ProposedTerm("先輩", "senpai", "honorific"),
)
#: What AC-1 says the glossary holds: both terms, first seen on page 0, from the
#: model. Built by hand rather than through `merge`.
_EXPECTED_ENTRIES = [
    GlossaryEntry("ケンジ", "Kenji", "name", 0, 0, "model"),
    GlossaryEntry("先輩", "senpai", "honorific", 0, 0, "model"),
]

_SOURCE_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 30, 20),
    ("p2.png", 40, 30),
    ("p3.png", 50, 40),
)
#: OCR seeded per ordinal; ordinal 1 deliberately has none (module docstring).
_SEEDED_LINES: dict[int, tuple[OcrResult, ...]] = {
    0: (OcrResult("ケンジ、待って"), OcrResult("先輩…")),
    2: (OcrResult("ケンジ先輩"), OcrResult("", ocr_empty=True)),
}

_STAGE = "fake-page-stage"


def _usd(micro: int) -> Usd:
    return Usd.from_micro(micro)


def _ring(x: int, y: int) -> tuple[tuple[int, int], ...]:
    return ((x, y), (x + 4, y), (x + 4, y + 4), (x, y + 4), (x, y))


def _never() -> bool:
    return False


# -- doubles -------------------------------------------------------------------


class _Proposer:
    """Stands where `partial(gemini.propose_glossary, client)` stands.

    Records the pages it was handed and appends to the shared `log`, so "the
    proposer ran before any page stage" is an assertion on one ordered record.
    """

    def __init__(
        self,
        log: list[object],
        *,
        terms: Sequence[Any] = _TERMS,
        usage: TokenUsage = _PASS_USAGE,
        model_id: str = _GEMINI,
        raises: Exception | None = None,
    ) -> None:
        self.log = log
        self.terms = tuple(terms)
        self.usage = usage
        self.model_id = model_id
        self.raises = raises
        self.received: list[list[tuple[OcrResult, ...]]] = []

    @property
    def calls(self) -> int:
        return len(self.received)

    def __call__(self, pages: Sequence[Sequence[OcrResult]]) -> GlossaryProposal:
        self.received.append([tuple(page) for page in pages])
        self.log.append("propose")
        if self.raises is not None:
            raise self.raises
        return GlossaryProposal(
            terms=self.terms,
            usage=self.usage,
            call=CallInfo(request_id="req-glossary-1", model_id=self.model_id),
        )


@dataclass
class _Snapshot:
    """What the store held when the first page stage first ran."""

    entries: list[GlossaryEntry]
    proposed_at: str | None
    page_two_glossary_block: str


@dataclass
class _RecordingStage:
    """A page stage that records `("stage", ordinal)` into the shared log and,
    the first time it runs, snapshots the glossary, the marker and page 2's
    context block - "before any page stage runs", observed from the inside.

    Not frozen, for `Stage.name`'s reason (MT-035 R-1)."""

    log: list[object]
    snapshot: list[_Snapshot] = field(default_factory=list)
    name: str = _STAGE

    def run(self, ctx: PageContext) -> None:
        if not self.snapshot:
            self.snapshot.append(
                _Snapshot(
                    entries=read_entries(ctx.project),
                    proposed_at=ctx.project.glossary_proposed_at(),
                    page_two_glossary_block=build_prompt_context(ctx.project, 1).glossary_block,
                )
            )
        self.log.append(("stage", ctx.page.ordinal))

    def is_done(self, ctx: PageContext) -> bool:
        return ctx.project.page_status(ctx.page.ordinal) == PAGE_DONE


class _AlreadyRead:
    """MT-130: the reading pass's stand-in. Every page reports its reading
    done - the fixture stored the OCR itself (PO-4) - so the reading pass emits
    `PageSkipped` for each page and runs nothing."""

    name = "already-read"

    def run(self, ctx: PageContext) -> None:  # pragma: no cover - always done
        raise AssertionError("the reading pass ran a stage the fixture had done")

    def is_done(self, ctx: PageContext) -> bool:
        return True


# -- fixture -------------------------------------------------------------------


@dataclass
class _World:
    project: Project
    db_path: Path
    log: list[object]

    def set_ceiling(self, micro: int | None) -> None:
        """Raw SQL, as `test_budget_run.py` does: no shipped writer exists."""
        with self.project.transaction() as cursor:
            cursor.execute("UPDATE chapter SET budget_ceiling_micro_usd = ?", (micro,))

    def open_run(self) -> int:
        with self.project.transaction() as cursor:
            chapter_id = int(cursor.execute("SELECT id FROM chapter").fetchone()[0])
            cursor.execute(
                "INSERT INTO run (chapter_id, started_at) VALUES (?, ?)",
                (chapter_id, "2026-11-01T09:00:00+00:00"),
            )
            return int(cursor.execute("SELECT last_insert_rowid()").fetchone()[0])

    def stored_pages(self) -> list[tuple[OcrResult, ...]]:
        return [self.project.read_lines(page.ordinal) for page in self.project.pages()]

    def pass_estimate_micro(self) -> int:
        """AC-5's projection, by hand: `estimate_tokens(glossary_pass_text(pages))`
        in and `GLOSSARY_PASS_MAX_OUTPUT_TOKENS` out, at the rate row's 2 and 12
        micro-dollars a token."""
        tokens_in = estimate_tokens(glossary_pass_text(self.stored_pages()))
        return (
            tokens_in * _IN_MICRO_PER_TOKEN + GLOSSARY_PASS_MAX_OUTPUT_TOKENS * _OUT_MICRO_PER_TOKEN
        )

    def ledger(self) -> list[tuple[object, ...]]:
        """Every ledger row, oldest first, through a connection that knows
        nothing of `mangatl.store`."""
        connection = sqlite3.connect(self.db_path)
        try:
            return connection.execute(
                "SELECT page_id, pricing, cost_micro_usd, model_id, request_id,"
                " input_tokens, output_tokens, run_id FROM llm_call ORDER BY id"
            ).fetchall()
        finally:
            connection.close()

    def run(
        self,
        proposer: _Proposer | None = None,
        *,
        stage: _RecordingStage | None = None,
        bind: bool = True,
    ) -> tuple[list[RunEvent], RunOutcome, _RecordingStage]:
        """One whole two-pass run through the real runner (MT-130): the
        reading pass `_AlreadyRead`, the recording stage after the prelude, the
        prelude bound unless `bind=False`."""
        stage = stage if stage is not None else _RecordingStage(self.log)
        prelude = (
            _prelude(proposer if proposer is not None else _Proposer(self.log)) if bind else None
        )
        events: list[RunEvent] = []
        outcome = run_chapter(  # type: ignore[call-arg]
            self.project,
            (_AlreadyRead(),),
            events.append,
            _never,
            prelude=prelude,
            after_prelude=(stage,),
        )
        return events, outcome, stage


def _prelude(proposer: Callable[..., GlossaryProposal], model_id: str = _GEMINI) -> Any:
    """`glossary_prelude` bound as `compose` binds it for Gemini: the listing
    and the output limit are `translate`'s, handed in (Contract, as amended)."""
    from mangatl.pipeline.prelude import glossary_prelude  # type: ignore[import-not-found]

    return glossary_prelude(
        proposer,
        model_id,
        listing=glossary_pass_text,
        max_output_tokens=GLOSSARY_PASS_MAX_OUTPUT_TOKENS,
    )


def _seed_lines(project: Project, mask: bytes, lines: dict[int, tuple[OcrResult, ...]]) -> None:
    for ordinal, results in lines.items():
        project.write_regions(
            ordinal,
            [
                RawRegion(polygon=_ring(index * 10, 0), mask=mask, confidence=1.0, kind="bubble")
                for index in range(len(results))
            ],
        )
        project.write_lines(ordinal, results)


def _make_world(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
    lines: dict[int, tuple[OcrResult, ...]],
) -> Iterator[_World]:
    source_dir = tmp_path / "scans"
    source_dir.mkdir(parents=True)
    for index, (filename, width, height) in enumerate(_SOURCE_PAGES):
        (source_dir / filename).write_bytes(png_bytes(width, height, (index * 40, 0, 0)))
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        _seed_lines(project, one_bit_png(8, 8, [(0, 0, 4, 4)]), lines)
        yield _World(project, project_dir_for(source_dir) / "project.db", [])


@pytest.fixture
def world(
    tmp_path: Path, png_bytes: Callable[..., bytes], one_bit_png: Callable[..., bytes]
) -> Iterator[_World]:
    """Three pages; OCR stored on ordinals 0 and 2 (PO-4)."""
    yield from _make_world(tmp_path, png_bytes, one_bit_png, _SEEDED_LINES)


@pytest.fixture
def fresh_world(
    tmp_path: Path, png_bytes: Callable[..., bytes], one_bit_png: Callable[..., bytes]
) -> Iterator[_World]:
    """Three pages and no OCR at all: the first interactive run's normal case
    (PO-1)."""
    yield from _make_world(tmp_path, png_bytes, one_bit_png, {})


@pytest.fixture
def wordless_world(
    tmp_path: Path, png_bytes: Callable[..., bytes], one_bit_png: Callable[..., bytes]
) -> Iterator[_World]:
    """Regions and lines stored, every one `ocr_empty`: the listing is still
    `""`, so this is AC-7's given reached by a second route."""
    empty = (OcrResult("", ocr_empty=True),)
    yield from _make_world(tmp_path, png_bytes, one_bit_png, {0: empty, 1: empty, 2: empty})


def _of[E](events: Sequence[RunEvent], kind: type[E]) -> list[E]:
    return [event for event in events if isinstance(event, kind)]


def _index_of_first(events: Sequence[RunEvent], kind: type[object]) -> int:
    return next(index for index, event in enumerate(events) if isinstance(event, kind))


# =============================================================================
# The shapes the Contract fixes (as amended in RED)
# =============================================================================


def test_call_priced_ordinal_admits_none_for_a_chapter_level_call() -> None:
    """The widening, as a type: `None` is a chapter-level call."""
    hints = typing.get_type_hints(CallPriced)

    assert hints["ordinal"] == int | None, (
        f"CallPriced.ordinal is annotated {hints['ordinal']!r}; MT-105 widens it to int | None"
    )


def test_the_pipeline_carries_the_two_passes_and_the_prelude_and_nothing_else() -> None:
    """MT-130 C-3 / AC-13: `["stages", "prelude", "after_prelude"]`, in that
    order, `after_prelude` defaulting to `()` so every two-argument constructor
    in the tree stays valid; `page_stages` is both passes in run order."""
    from mangatl.pipeline.prelude import Pipeline

    names = [f.name for f in dataclasses.fields(Pipeline)]
    pipeline = Pipeline(stages=(), prelude=None)

    assert names == ["stages", "prelude", "after_prelude"]
    assert pipeline.after_prelude == ()  # type: ignore[attr-defined]
    with pytest.raises(dataclasses.FrozenInstanceError):
        pipeline.prelude = None  # type: ignore[misc]
    a, b, c = _AlreadyRead(), _AlreadyRead(), _AlreadyRead()
    split = Pipeline(stages=(a, b), prelude=None, after_prelude=(c,))  # type: ignore[call-arg]
    assert split.page_stages == (a, b, c)  # type: ignore[attr-defined]
    assert type(split.page_stages) is tuple  # type: ignore[attr-defined]
    assert Pipeline(stages=(a,), prelude=None).page_stages == (a,)  # type: ignore[attr-defined]


def test_the_glossary_prelude_takes_the_listing_and_the_output_limit_by_keyword() -> None:
    """`pipeline` may not import `translate`, so the listing function and the
    output limit arrive as arguments `compose` binds (Contract, as amended)."""
    from mangatl.pipeline.prelude import glossary_prelude  # type: ignore[import-not-found]

    parameters = inspect.signature(glossary_prelude).parameters
    kinds = {name: parameter.kind for name, parameter in parameters.items()}

    assert kinds == {
        "propose": inspect.Parameter.POSITIONAL_OR_KEYWORD,
        "model_id": inspect.Parameter.POSITIONAL_OR_KEYWORD,
        "listing": inspect.Parameter.KEYWORD_ONLY,
        "max_output_tokens": inspect.Parameter.KEYWORD_ONLY,
    }
    assert all(p.default is inspect.Parameter.empty for p in parameters.values()), (
        "no glossary_prelude argument may default: a default listing or limit is"
        " translate's value spelled a second time"
    )


# =============================================================================
# AC-1: the terms are in the store before any translating stage runs (MT-130)
# =============================================================================


def test_the_proposed_terms_are_in_the_glossary_before_the_first_page_stage_runs(
    world: _World,
) -> None:
    _, outcome, stage = world.run()

    assert outcome.outcome == RUN_FINISHED, f"the run did not finish: {outcome}"
    assert stage.snapshot, "no page stage ran at all"
    (seen,) = stage.snapshot
    assert seen.entries == _EXPECTED_ENTRIES, (
        f"when the first page stage ran the glossary held {seen.entries};"
        " AC-1 has both proposed terms there, first seen on page 0, source 'model'"
    )


def test_the_marker_is_set_before_the_first_page_stage_runs(world: _World) -> None:
    _, _, stage = world.run()

    (seen,) = stage.snapshot
    assert seen.proposed_at is not None, (
        "glossary_proposed_at was unset when page 1's first stage ran"
    )
    assert world.project.glossary_proposed_at() == seen.proposed_at


def test_page_twos_context_block_renders_the_proposed_terms(world: _World) -> None:
    _, _, stage = world.run()

    (seen,) = stage.snapshot
    expected = render_block(_EXPECTED_ENTRIES, MAX_GLOSSARY_TOKENS)
    assert expected != "", "the oracle rendered nothing; the control is broken"
    assert seen.page_two_glossary_block == expected, (
        f"page 2's glossary block was {seen.page_two_glossary_block!r}; AC-1 renders both terms"
    )


def test_the_proposer_runs_once_and_before_every_page_stage(world: _World) -> None:
    proposer = _Proposer(world.log)

    world.run(proposer)

    assert proposer.calls == 1
    assert world.log == ["propose", ("stage", 0), ("stage", 1), ("stage", 2)], (
        f"the run's order was {world.log}; the proposer runs once, before page 1's stages"
    )


def test_the_proposer_is_handed_every_pages_stored_lines_in_ordinal_order(world: _World) -> None:
    """Every page, the empty one included: `glossary_pass_text` numbers its
    headers by index, so a prelude that dropped ordinal 1 before handing the
    pages over would label ordinal 2's lines "Page 2"."""
    proposer = _Proposer(world.log)

    world.run(proposer)

    assert proposer.received == [[_SEEDED_LINES[0], (), _SEEDED_LINES[2]]], (
        f"the proposer was handed {proposer.received}"
    )


def test_a_term_with_a_blank_side_is_not_written(world: _World) -> None:
    """The prelude merges as a page does (`domain.glossary.merge`): a proposal
    with a blank side is dropped, and the rest are kept."""
    proposer = _Proposer(world.log, terms=(*_TERMS, ProposedTerm("ユキ", "  ", "name")))

    world.run(proposer)

    assert read_entries(world.project) == _EXPECTED_ENTRIES


# =============================================================================
# AC-2: once per chapter - the marker is the evidence
# =============================================================================


def test_a_second_run_does_not_call_the_proposer_again(world: _World) -> None:
    proposer = _Proposer(world.log)
    world.run(proposer)

    events, outcome, _ = world.run(proposer)

    assert proposer.calls == 1, f"the proposer was called {proposer.calls} times over two runs"
    assert outcome.outcome == RUN_FINISHED
    assert _of(events, CallPriced) == [], "the second run emitted a CallPriced for no call"


def test_a_second_run_writes_no_second_ledger_row_and_leaves_the_glossary_alone(
    world: _World,
) -> None:
    proposer = _Proposer(world.log)
    world.run(proposer)
    rows_before = world.ledger()
    entries_before = read_entries(world.project)
    marker_before = world.project.glossary_proposed_at()

    world.run(proposer)

    assert len(rows_before) == 1
    assert world.ledger() == rows_before, "a second run wrote to the ledger"
    assert read_entries(world.project) == entries_before == _EXPECTED_ENTRIES
    assert world.project.glossary_proposed_at() == marker_before, "the marker was re-stamped"


def test_a_chapter_already_marked_is_not_proposed_for_even_with_no_glossary_and_no_bill(
    world: _World,
) -> None:
    """The marker alone is what skips: nothing in the glossary and nothing in
    the ledger here, and still no call."""
    world.project.mark_glossary_proposed()
    proposer = _Proposer(world.log)

    events, outcome, _ = world.run(proposer)

    assert proposer.calls == 0
    assert outcome.outcome == RUN_FINISHED
    assert _of(events, CallPriced) == []
    assert world.ledger() == []
    assert read_entries(world.project) == []


def test_a_chapter_level_bill_without_the_marker_does_not_skip_the_pass(world: _World) -> None:
    """The control for the test above, from the other side: "a ledger row
    proves a bill, not that the terms were written" (Context). A prelude that
    skipped on a chapter-level ledger row would pass AC-2 and fail this."""
    run_id = world.open_run()
    record_call(world.project, run_id, None, "req-earlier", price(_GEMINI, TokenUsage(10, 0, 0, 0)))
    proposer = _Proposer(world.log)

    world.run(proposer)

    assert proposer.calls == 1
    assert read_entries(world.project) == _EXPECTED_ENTRIES
    assert world.project.glossary_proposed_at() is not None


# =============================================================================
# AC-3: the guard is before the call
# =============================================================================


def test_a_ceiling_below_the_pass_estimate_refuses_before_the_proposer_is_called(
    world: _World,
) -> None:
    world.set_ceiling(50_000)
    assert world.pass_estimate_micro() > 50_000, "the fixture's ceiling is not below the estimate"
    proposer = _Proposer(world.log)

    events, outcome, stage = world.run(proposer)

    assert proposer.calls == 0, "the proposer was called although the guard refuses the pass"
    assert events[-1] == RunAborted(reason=BUDGET, ordinal=None), (
        f"the run ended with {events[-1]!r}; AC-3 is RunAborted(reason='budget', ordinal=None)"
    )
    assert outcome.outcome == RUN_ABORTED and outcome.aborted_reason == BUDGET
    assert _of(events, PageStarted) == [] and stage.snapshot == [], "a page started anyway"


def test_a_refused_pass_writes_no_ledger_row_no_term_and_no_marker(world: _World) -> None:
    world.set_ceiling(50_000)

    events, _, _ = world.run()

    assert world.ledger() == []
    assert read_entries(world.project) == []
    assert world.project.glossary_proposed_at() is None
    assert _of(events, CallPriced) == []


def test_the_guard_counts_what_the_chapter_has_already_spent(world: _World) -> None:
    """PO-2's resumed run: `spent` is the chapter's total, not zero. 20 micro
    already spent (10 input tokens x 2) against a ceiling 19 micro above the
    estimate refuses; 20 above permits (the comparison is inclusive)."""
    run_id = world.open_run()
    record_call(world.project, run_id, 0, "req-page-1", price(_GEMINI, TokenUsage(10, 0, 0, 0)))
    world.set_ceiling(world.pass_estimate_micro() + 19)
    proposer = _Proposer(world.log)

    events, _, _ = world.run(proposer)

    assert proposer.calls == 0, "the guard ignored the 20 micro-dollars already spent"
    assert events[-1] == RunAborted(reason=BUDGET, ordinal=None)


def test_the_guard_permits_a_pass_landing_exactly_on_the_ceiling_after_earlier_spend(
    world: _World,
) -> None:
    run_id = world.open_run()
    record_call(world.project, run_id, 0, "req-page-1", price(_GEMINI, TokenUsage(10, 0, 0, 0)))
    world.set_ceiling(world.pass_estimate_micro() + 20)
    proposer = _Proposer(world.log)

    world.run(proposer)

    assert proposer.calls == 1


# =============================================================================
# AC-4: one chapter-level ledger row, and CallPriced(None) before PageStarted(0)
# =============================================================================


def test_the_pass_is_billed_as_exactly_one_chapter_level_row_at_the_interactive_rate(
    world: _World,
) -> None:
    events, _, _ = world.run()
    (started,) = _of(events, RunStarted)

    assert world.ledger() == [
        (None, "standard", _PASS_MICRO, _GEMINI, "req-glossary-1", 50_000, 3_000, started.run_id)
    ], f"the ledger holds {world.ledger()}"


def test_the_bill_is_announced_as_a_chapter_level_call_priced_before_page_one_starts(
    world: _World,
) -> None:
    world.set_ceiling(1_000_000)

    events, _, _ = world.run()

    (priced,) = _of(events, CallPriced)
    assert priced.ordinal is None, f"the pass's CallPriced names ordinal {priced.ordinal!r}"
    assert priced.spent == _usd(_PASS_MICRO), f"spent is {priced.spent!r}, not $0.136"
    assert priced.ceiling == _usd(1_000_000), (
        f"ceiling is {priced.ceiling!r}; the chapter's stored ceiling is $1.00"
    )
    assert isinstance(priced.projection, Projection)
    assert (
        _index_of_first(events, RunStarted)
        < _index_of_first(events, CallPriced)
        < _index_of_first(events, PageStarted)
    ), f"the stream's order is {[type(e).__name__ for e in events]}"
    assert _of(events, PageStarted)[0] == PageStarted(ordinal=0)


def test_with_no_stored_ceiling_the_call_priced_carries_the_default_ceiling(world: _World) -> None:
    events, _, _ = world.run()

    (priced,) = _of(events, CallPriced)
    assert priced.ceiling == DEFAULT_CEILING


# =============================================================================
# AC-5: the pass's projection is the listing's estimate in, the limit out
# =============================================================================


def test_the_output_limit_the_estimate_is_built_on_is_8192() -> None:
    """Settled: MT-104's `GLOSSARY_PASS_MAX_OUTPUT_TOKENS`, read out."""
    assert GLOSSARY_PASS_MAX_OUTPUT_TOKENS == 8_192


def test_a_ceiling_exactly_at_the_pass_estimate_permits_the_pass(world: _World) -> None:
    """Inclusive: $0 spent + the estimate lands exactly on the ceiling. A
    projection built on a larger output count, or on a longer listing, refuses
    here."""
    world.set_ceiling(world.pass_estimate_micro())
    proposer = _Proposer(world.log)

    _, outcome, _ = world.run(proposer)

    assert proposer.calls == 1, (
        f"a ceiling of exactly {world.pass_estimate_micro()} micro refused the pass;"
        " the projection is not estimate_tokens(listing) in + 8,192 out"
    )
    assert outcome.outcome == RUN_FINISHED


def test_a_ceiling_one_micro_dollar_below_the_pass_estimate_refuses_the_pass(
    world: _World,
) -> None:
    """A projection built on a smaller output count (the page cap, 4,096), on
    a shorter listing, or on no output at all, permits here."""
    world.set_ceiling(world.pass_estimate_micro() - 1)
    proposer = _Proposer(world.log)

    events, _, _ = world.run(proposer)

    assert proposer.calls == 0, (
        f"a ceiling of {world.pass_estimate_micro() - 1} micro permitted the pass;"
        " the projection is under estimate_tokens(listing) in + 8,192 out"
    )
    assert events[-1] == RunAborted(reason=BUDGET, ordinal=None)


def test_the_estimate_is_priced_at_the_model_the_prelude_was_bound_with(world: _World) -> None:
    """`model_id` prices the estimate: bound to a model the rate table does not
    list, the guard cannot price the pass, and the run aborts naming no page
    before any call is made."""
    proposer = _Proposer(world.log)

    events, outcome, _ = _run_bound(world, _prelude(proposer, _UNPRICED))

    assert proposer.calls == 0
    aborted = events[-1]
    assert isinstance(aborted, RunAborted) and aborted.ordinal is None
    assert aborted.reason is not None and aborted.reason.startswith("UnknownModel"), (
        f"the run aborted with {aborted.reason!r}"
    )
    assert outcome.outcome == RUN_ABORTED


# =============================================================================
# AC-7: an empty listing skips the pass (PO-1)
# =============================================================================


@pytest.mark.parametrize("which", ["fresh_world", "wordless_world"])
def test_an_empty_listing_calls_nothing_bills_nothing_and_leaves_the_marker_unset(
    which: str, request: pytest.FixtureRequest
) -> None:
    world: _World = request.getfixturevalue(which)
    assert glossary_pass_text(world.stored_pages()) == "", "the fixture's listing is not empty"
    proposer = _Proposer(world.log)

    events, outcome, _ = world.run(proposer)

    assert proposer.calls == 0
    assert _of(events, CallPriced) == []
    assert world.ledger() == []
    assert world.project.glossary_proposed_at() is None, (
        "an empty listing set the marker, so a later run with OCR stored would never propose"
    )
    assert outcome.outcome == RUN_FINISHED


def test_with_an_empty_listing_the_pages_run_exactly_as_with_no_prelude(
    fresh_world: _World,
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
) -> None:
    """The stream of a bound run over an empty listing equals an unbound run's
    over an identical chapter, event for event (durations aside). Both are
    two-pass since MT-130; the unbound one passes `prelude=None`."""
    bound_events, _, _ = fresh_world.run()
    unbound = _make_world(tmp_path / "unbound", png_bytes, one_bit_png, {})
    try:
        unbound_events, _, _ = next(unbound).run(bind=False)
    finally:
        unbound.close()

    def projected(events: Sequence[RunEvent]) -> list[tuple[str, object]]:
        return [
            (type(e).__name__, getattr(e, "ordinal", None))
            for e in events
            if not isinstance(e, RunStarted)
        ]

    assert projected(bound_events) == projected(unbound_events)
    assert fresh_world.log == [("stage", 0), ("stage", 1), ("stage", 2)]


def test_an_empty_listing_is_skipped_before_the_guard_so_a_zero_ceiling_does_not_abort(
    fresh_world: _World,
) -> None:
    """ "Page 1's stages run as they do without a prelude": a $0.00 ceiling
    refuses every call, and an empty listing makes none, so the pages run."""
    fresh_world.set_ceiling(0)

    events, outcome, _ = fresh_world.run()

    assert outcome.outcome == RUN_FINISHED, f"the run ended {outcome}"
    assert _of(events, RunAborted) == []
    assert fresh_world.log == [("stage", 0), ("stage", 1), ("stage", 2)]


def test_a_later_run_with_ocr_stored_still_proposes_after_an_empty_one(
    fresh_world: _World, one_bit_png: Callable[..., bytes]
) -> None:
    """PO-1's reason for leaving the marker unset, observed: the pages are
    reset to pending and OCR stored, as a resumed run would find them."""
    proposer = _Proposer(fresh_world.log)
    fresh_world.run(proposer)
    _seed_lines(fresh_world.project, one_bit_png(8, 8, [(0, 0, 4, 4)]), _SEEDED_LINES)
    with fresh_world.project.transaction() as cursor:
        cursor.execute("UPDATE page SET status = ?", (PAGE_PENDING,))

    fresh_world.run(proposer)

    assert proposer.calls == 1
    assert read_entries(fresh_world.project) == _EXPECTED_ENTRIES


# =============================================================================
# Failure after the call: the upserts and the mark are one transaction
# =============================================================================

_TRIGGER = (
    "CREATE TRIGGER refuse_the_marker BEFORE UPDATE OF glossary_proposed_at ON chapter"
    " BEGIN SELECT RAISE(ABORT, 'injected: the marker write failed'); END"
)


def test_a_failed_marker_write_leaves_no_term_behind(world: _World) -> None:
    """The trigger refuses the marker's write, however it is spelled. In one
    transaction with the upserts, the terms roll back with it; written in a
    transaction of their own before it, they survive - and this fails."""
    with world.project.transaction() as cursor:
        cursor.execute(_TRIGGER)

    events, outcome, stage = world.run()

    aborted = events[-1]
    assert isinstance(aborted, RunAborted) and aborted.ordinal is None, (
        f"the run ended with {aborted!r}"
    )
    assert aborted.reason is not None and "injected: the marker write failed" in aborted.reason
    assert read_entries(world.project) == [], (
        f"the glossary kept {read_entries(world.project)} after the marker write failed;"
        " the upserts and the mark are one transaction"
    )
    assert world.project.glossary_proposed_at() is None
    assert stage.snapshot == [] and _of(events, PageStarted) == []
    assert outcome.outcome == RUN_ABORTED


#: The other direction: refuse the **second** term's insert. A marker written in
#: its own transaction before the upserts survives this; the first term,
#: upserted on its own, survives it too.
_TERM_TRIGGER = (
    "CREATE TRIGGER refuse_the_second_term BEFORE INSERT ON glossary"
    " WHEN NEW.term_ja = '先輩'"
    " BEGIN SELECT RAISE(ABORT, 'injected: the second term write failed'); END"
)


def test_a_failed_term_write_leaves_no_marker_and_no_other_term_behind(world: _World) -> None:
    """With `test_a_failed_marker_write_leaves_no_term_behind` this covers both
    orders: terms committed before the mark fail that test, a mark committed
    before the terms fails this one."""
    with world.project.transaction() as cursor:
        cursor.execute(_TERM_TRIGGER)

    events, _, stage = world.run()

    aborted = events[-1]
    assert isinstance(aborted, RunAborted) and aborted.ordinal is None, (
        f"the run ended with {aborted!r}"
    )
    assert aborted.reason is not None and "injected: the second term write failed" in aborted.reason
    assert world.project.glossary_proposed_at() is None, (
        "the marker survived a failed term write; the upserts and the mark are one transaction"
    )
    assert read_entries(world.project) == [], (
        f"the glossary kept {read_entries(world.project)}; one term was written on its own"
    )
    assert stage.snapshot == []


def test_a_failed_marker_write_still_leaves_the_bill_in_the_ledger(world: _World) -> None:
    """The bill is its own transaction, written first (Contract: call,
    record_call, CallPriced, then the upserts and the mark). A paid call whose
    terms were lost is re-proposed and billed twice; the alternative loses the
    spend, which the guard can never recover."""
    with world.project.transaction() as cursor:
        cursor.execute(_TRIGGER)

    events, _, _ = world.run()

    assert [row[2] for row in world.ledger()] == [_PASS_MICRO]
    assert len(_of(events, CallPriced)) == 1


def test_a_proposer_that_raises_aborts_naming_no_page_and_writes_nothing(world: _World) -> None:
    proposer = _Proposer(world.log, raises=ValueError("the glossary pass answer has no key"))

    events, outcome, stage = world.run(proposer)

    assert events[-1] == RunAborted(
        reason="ValueError: the glossary pass answer has no key", ordinal=None
    ), f"the run ended with {events[-1]!r}"
    assert outcome.outcome == RUN_ABORTED
    assert world.ledger() == []
    assert read_entries(world.project) == []
    assert world.project.glossary_proposed_at() is None
    assert stage.snapshot == []


def test_an_unpriceable_answer_writes_no_bill_no_term_and_no_marker(world: _World) -> None:
    """The proposal names a model the rate table does not list: `price` raises
    before either write, as on a page (MT-044 C-7 clause 3)."""
    proposer = _Proposer(world.log, model_id=_UNPRICED)

    events, _, _ = world.run(proposer)

    aborted = events[-1]
    assert isinstance(aborted, RunAborted) and aborted.ordinal is None
    assert aborted.reason is not None and aborted.reason.startswith("UnknownModel")
    assert world.ledger() == []
    assert read_entries(world.project) == []
    assert world.project.glossary_proposed_at() is None


def _run_bound(world: _World, prelude: Any) -> tuple[list[RunEvent], RunOutcome, _RecordingStage]:
    stage = _RecordingStage(world.log)
    events: list[RunEvent] = []
    outcome = run_chapter(  # type: ignore[call-arg]
        world.project,
        (_AlreadyRead(),),
        events.append,
        _never,
        prelude=prelude,
        after_prelude=(stage,),
    )
    return events, outcome, stage
