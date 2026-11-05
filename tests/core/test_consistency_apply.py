"""MT-115: the consistency pass applied - corrections land on untouched proposals.

`pipeline.consistency.run_consistency_pass` reads a volume's current English
(AC-3), guards each chunk before its call (AC-4, D6), ledgers each chunk as a
chapter-level row (AC-5), and applies the parsed corrections to `proposed` lines
only, keeping the previous text and the reason in a `correction` row (AC-1,
AC-2). `consistency_step` wraps it as a `ChapterStep`, which `collect_volume`
and `run_chapter` run as their `postlude` (AC-6).

**Oracle partition: all mechanical** (the story's). Every expectation is read
out of the pinned `## Contract` or an existing module: the text is the real
`translate.consistency.consistency_text` over pages built by hand here, the
guard's figures are `call_estimate` on that real text, and the bills are the
Gemini 3.1 Pro Preview interactive row - $2.00 in and $12.00 out per million
tokens, so 2 and 12 micro-dollars a token:

    pass answer 1  TokenUsage(1000, 200, 0, 0)   2000 + 2400 = 4400 micro
    pass answer 2  TokenUsage(500, 100, 0, 0)    1000 + 1200 = 2200 micro

`test_the_interactive_row_prices_the_two_answers_at_the_written_out_figures`
checks the literals against `price` once, as a precondition.

**The world is real**: a `.mtproj` on `tmp_path` with three tiny PNG pages,
regions and OCR lines seeded through the store, proposals written through
`write_proposed`, the user's acts through `store.lines.commit_line` (so a line's
status is the derived one `read_review_lines` reports), one glossary entry
through `store.glossary.upsert`, and one `run` row. The one double is the pass
(`_Pass`), standing where `partial(gemini.run_consistency, client)` stands: it
records every text it was sent and answers the JSON the test configured.

    page 0  [0] ケンジ、待って  "Kenji, wait"
            [1] 先輩…          "Senpai..."
    page 1  [0] どこへ行くの    "Where are you going"
            [1] (ocr_empty)    no English - failed, absent from the text
    page 2  [0] ケンジ先輩      "Kenji-sempai"
            [1] 走れ            no proposal - absent from the text

**Imports of every name MT-115 adds are inside the helpers** (`_pipeline`,
`_corrections_applied`, `_domain_page_lines`, `_collect_volume`, `_run_chapter`),
so in RED each test fails on the named absence and the file is never dark at
collection.

**What these tests do NOT constrain**, so it stays GREEN's choice: whether a
line with no English is left out of its `PageLines` or carried with `en=None`
(the text and every estimate are identical either way); whether `chunk` is
called when no page is kept; the wording of any message; how the pass reads the
pages beyond `read_review_lines`' derived status.

**Timing.** No `pytest-timeout` in this project, so there is no budget to size;
every test builds a three-page chapter of tiny PNGs on `tmp_path`.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import sqlite3
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

import pytest

from mangatl.domain.batch import BatchJob, BatchResults
from mangatl.domain.budget import DEFAULT_CEILING, Projection, call_estimate, page_estimate
from mangatl.domain.correction import ConsistencyResult, Correction
from mangatl.domain.events import (
    BatchCollected,
    CallPriced,
    RunAborted,
    RunEvent,
    RunFinished,
    StageFinished,
)
from mangatl.domain.glossary import (
    MAX_GLOSSARY_TOKENS,
    GlossaryEntry,
    estimate_tokens,
    render_block,
)
from mangatl.domain.line import OcrResult
from mangatl.domain.money import Usd
from mangatl.domain.rates import price
from mangatl.domain.region import RawRegion
from mangatl.domain.translation import CallInfo, TokenUsage, TranslationResult
from mangatl.pipeline.runner import BUDGET, RUN_ABORTED, RUN_FINISHED, RunOutcome
from mangatl.pipeline.stage import BudgetRefused, PageContext
from mangatl.store.batch import record_submission
from mangatl.store.corrections import corrections_for
from mangatl.store.glossary import read_entries, upsert
from mangatl.store.intake import read_chapter
from mangatl.store.ledger import chapter_call_costs, chapter_total, record_call
from mangatl.store.lines import commit_line, read_review_lines
from mangatl.store.project import PAGE_DONE, Project, create_project, project_dir_for
from mangatl.translate import consistency as tc

# -- the numbers ---------------------------------------------------------------

_GEMINI = "gemini-3.1-pro-preview"

_USAGE_1 = TokenUsage(1000, 200, 0, 0)
_USAGE_2 = TokenUsage(500, 100, 0, 0)
#: Worked by hand in the module docstring - not read out of `price`.
_MICRO_1 = 4_400
_MICRO_2 = 2_200

_SOURCE_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 30, 20),
    ("p2.png", 40, 30),
    ("p3.png", 50, 40),
)

_LINES: dict[int, tuple[OcrResult, ...]] = {
    0: (OcrResult("ケンジ、待って"), OcrResult("先輩…")),
    1: (OcrResult("どこへ行くの"), OcrResult("", ocr_empty=True)),
    2: (OcrResult("ケンジ先輩"), OcrResult("走れ")),
}

_PROPOSED: dict[int, dict[int, str]] = {
    0: {0: "Kenji, wait", 1: "Senpai..."},
    1: {0: "Where are you going"},
    2: {0: "Kenji-sempai"},
}

_GLOSSARY = GlossaryEntry("ケンジ", "Kenji", "name", 0, 2, "model")

_REASON_A = "the volume writes the ellipsis as one character"
_REASON_B = "the glossary renders 先輩 as senpai"


def _item(page_ordinal: int, reading_index: int, corrected_en: str, reason: str) -> dict[str, Any]:
    """One answer item, in the RESPONSE's numbering: 1-based `page`."""
    return {
        "page": page_ordinal + 1,
        "reading_index": reading_index,
        "corrected_en": corrected_en,
        "reason": reason,
    }


def _answer(*items: dict[str, Any]) -> str:
    return json.dumps({tc.CORRECTIONS_KEY: list(items)}, ensure_ascii=False)


#: AC-1's two corrections, on proposed lines of two different pages.
_FIX_A = _item(0, 1, "Senpai…", _REASON_A)
_FIX_B = _item(2, 0, "Kenji-senpai", _REASON_B)


# -- the names MT-115 adds, imported lazily ------------------------------------


def _pipeline() -> Any:
    import mangatl.pipeline.consistency as module  # type: ignore[import-not-found]

    return module


def _corrections_applied(*values: int) -> Any:
    from mangatl.domain.events import CorrectionsApplied  # type: ignore[attr-defined]

    return CorrectionsApplied(*values)


def _domain_page_lines() -> Any:
    from mangatl.domain.correction import PageLines  # type: ignore[attr-defined]

    return PageLines


def _tools(chunk: Callable[..., Any] = tc.chunk_pages, **overrides: Any) -> Any:
    """`ConsistencyTools` bound as `compose.build_consistency` binds it:
    `translate.consistency`'s four, `chunk` overridable for a two-chunk run."""
    values: dict[str, Any] = {
        "text": tc.consistency_text,
        "chunk": chunk,
        "parse": tc.parse_corrections,
        "max_output_tokens": tc.CONSISTENCY_MAX_OUTPUT_TOKENS,
    }
    values.update(overrides)
    return _pipeline().ConsistencyTools(**values)


def _collect_volume(*args: Any, **kwargs: Any) -> Any:
    from mangatl.pipeline.batch import collect_volume

    return collect_volume(*args, **kwargs)


def _run_chapter(*args: Any, **kwargs: Any) -> RunOutcome:
    from mangatl.pipeline.runner import run_chapter

    return run_chapter(*args, **kwargs)


# -- the double ----------------------------------------------------------------


class _Pass:
    """Stands where `partial(gemini.run_consistency, client)` stands: records
    every text it was sent and answers the next configured answer, numbered
    request ids `req-consistency-1`, `-2`, ..."""

    def __init__(
        self,
        *answers: str,
        usages: Sequence[TokenUsage] = (_USAGE_1, _USAGE_2),
        raises: Exception | None = None,
    ) -> None:
        self.answers = list(answers)
        self.usages = list(usages)
        self.raises = raises
        self.received: list[str] = []

    @property
    def calls(self) -> int:
        return len(self.received)

    def __call__(self, text: str) -> ConsistencyResult:
        self.received.append(text)
        if self.raises is not None:
            raise self.raises
        n = len(self.received)
        return ConsistencyResult(
            text=self.answers[n - 1],
            usage=self.usages[n - 1],
            call=CallInfo(request_id=f"req-consistency-{n}", model_id=_GEMINI),
        )


@dataclass
class _RecordingChunk:
    """A `chunk` that records the pages it was handed, then cuts as asked."""

    max_tokens: int = tc.CONSISTENCY_MAX_INPUT_TOKENS
    handed: list[list[int]] = field(default_factory=list)

    def __call__(self, pages: Sequence[Any], glossary_block: str) -> Any:
        self.handed.append([page.ordinal for page in pages])
        return tc.chunk_pages(pages, glossary_block, self.max_tokens)


# -- the world -----------------------------------------------------------------


@dataclass
class _World:
    project: Project
    db_path: Path
    run_id: int
    events: list[RunEvent] = field(default_factory=list)

    def set_ceiling(self, micro: int | None) -> None:
        with self.project.transaction() as cursor:
            cursor.execute("UPDATE chapter SET budget_ceiling_micro_usd = ?", (micro,))

    def block(self) -> str:
        """The per-page prompt's glossary block, `pipeline.continuity`'s rule."""
        return render_block(read_entries(self.project), MAX_GLOSSARY_TOKENS)

    def run_pass(self, pass_: _Pass, tools: Any = None) -> Any:
        return _pipeline().run_consistency_pass(
            self.project,
            self.run_id,
            pass_,
            tools if tools is not None else _tools(),
            _GEMINI,
            self.events.append,
        )

    def step(self, pass_: _Pass, tools: Any = None) -> Any:
        return _pipeline().consistency_step(
            pass_, tools if tools is not None else _tools(), _GEMINI
        )

    def line(self, ordinal: int, reading_index: int) -> Any:
        line = read_review_lines(self.project, ordinal)[reading_index]
        assert line is not None
        return line

    def english(self) -> dict[tuple[int, int], tuple[str | None, str | None, str]]:
        """Every line's `(proposed_en, final_en, status)`, by address."""
        return {
            (page.ordinal, line.reading_index): (line.proposed_en, line.final_en, line.status)
            for page in self.project.pages()
            for line in read_review_lines(self.project, page.ordinal)
            if line is not None
        }

    def all_corrections(self) -> list[Correction]:
        return [
            c for page in self.project.pages() for c in corrections_for(self.project, page.ordinal)
        ]

    def chapter_rows(self) -> list[tuple[object, ...]]:
        """Chapter-level ledger rows, oldest first, through a connection that
        knows nothing of `mangatl.store`."""
        return self._raw(
            "SELECT page_id, pricing, cost_micro_usd, model_id, request_id,"
            " input_tokens, output_tokens, run_id FROM llm_call"
            " WHERE page_id IS NULL ORDER BY id"
        )

    def ledger_count(self) -> int:
        ((count,),) = self._raw("SELECT COUNT(*) FROM llm_call")
        return int(str(count))

    def correction_count(self) -> int:
        ((count,),) = self._raw("SELECT COUNT(*) FROM correction")
        return int(str(count))

    def marker(self) -> Any:
        return self.project.consistency_run_id()  # type: ignore[attr-defined]

    def _raw(self, sql: str) -> list[tuple[object, ...]]:
        connection = sqlite3.connect(self.db_path)
        try:
            return connection.execute(sql).fetchall()
        finally:
            connection.close()


def _ring(x: int) -> tuple[tuple[int, int], ...]:
    return ((x, 0), (x + 4, 0), (x + 4, 4), (x, 4), (x, 0))


def _insert_run(project: Project) -> int:
    with project.transaction() as cursor:
        chapter_id = int(cursor.execute("SELECT id FROM chapter").fetchone()[0])
        cursor.execute(
            "INSERT INTO run (chapter_id, started_at) VALUES (?, ?)",
            (chapter_id, "2026-11-05T09:00:00+00:00"),
        )
        return int(cursor.execute("SELECT last_insert_rowid()").fetchone()[0])


def _make_world(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
    proposed: Mapping[int, Mapping[int, str]],
) -> Iterator[_World]:
    source_dir = tmp_path / "scans"
    source_dir.mkdir(parents=True)
    for index, (filename, width, height) in enumerate(_SOURCE_PAGES):
        (source_dir / filename).write_bytes(png_bytes(width, height, (index * 40, 0, 0)))
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        mask = one_bit_png(8, 8, [(0, 0, 4, 4)])
        for ordinal, results in _LINES.items():
            project.write_regions(
                ordinal,
                [
                    RawRegion(polygon=_ring(i * 10), mask=mask, confidence=1.0, kind="bubble")
                    for i in range(len(results))
                ],
            )
            project.write_lines(ordinal, results)
        for ordinal, lines in proposed.items():
            project.write_proposed(ordinal, dict(lines))
        upsert(project, _GLOSSARY)
        run_id = _insert_run(project)
        yield _World(project, project_dir_for(source_dir) / "project.db", run_id)


@pytest.fixture
def world(
    tmp_path: Path, png_bytes: Callable[..., bytes], one_bit_png: Callable[..., bytes]
) -> Iterator[_World]:
    """Three pages, every translated line untouched (`proposed`)."""
    yield from _make_world(tmp_path, png_bytes, one_bit_png, _PROPOSED)


@pytest.fixture
def untranslated_world(
    tmp_path: Path, png_bytes: Callable[..., bytes], one_bit_png: Callable[..., bytes]
) -> Iterator[_World]:
    """Three pages with OCR and no English anywhere: nothing to send."""
    yield from _make_world(tmp_path, png_bytes, one_bit_png, {})


@pytest.fixture
def gap_world(
    tmp_path: Path, png_bytes: Callable[..., bytes], one_bit_png: Callable[..., bytes]
) -> Iterator[_World]:
    """Page 1 has no English at all; pages 0 and 2 have their proposals."""
    yield from _make_world(tmp_path, png_bytes, one_bit_png, {0: _PROPOSED[0], 2: _PROPOSED[2]})


def _pages(*pages: tuple[int, tuple[tuple[int, str, str], ...]]) -> list[Any]:
    """The pages the pass is expected to see, built by hand with the
    re-exported `PageLines` (which exists today, so building the oracle does
    not depend on the move)."""
    return [tc.PageLines(ordinal, lines) for ordinal, lines in pages]


#: What the pass sees of the untouched world (AC-3): pages in ordinal order,
#: each line's `proposed_en`, the two English-less lines absent.
def _untouched_pages() -> list[Any]:
    return _pages(
        (0, ((0, "ケンジ、待って", "Kenji, wait"), (1, "先輩…", "Senpai..."))),
        (1, ((0, "どこへ行くの", "Where are you going"),)),
        (2, ((0, "ケンジ先輩", "Kenji-sempai"),)),
    )


def _estimate(text: str) -> Usd:
    """The guard's estimate for one chunk's text (Contract, "Per chunk")."""
    return call_estimate(
        _GEMINI, TokenUsage(estimate_tokens(text), tc.CONSISTENCY_MAX_OUTPUT_TOKENS, 0, 0)
    )


def _two_chunks(world: _World) -> tuple[int, list[str]]:
    """The `max_tokens` that cuts the untouched world into pages (0, 1) and
    (2,), and the two chunk texts - with the cut asserted, so a fixture that
    stopped producing two chunks fails here and not in a test downstream."""
    pages = _untouched_pages()
    block = world.block()
    limit = estimate_tokens(tc.consistency_text(pages[:2], block))
    chunks = tc.chunk_pages(pages, block, limit)
    assert [[p.ordinal for p in chunk] for chunk in chunks] == [[0, 1], [2]], chunks
    return limit, [tc.consistency_text(chunk, block) for chunk in chunks]


def _of[E](events: Sequence[RunEvent], kind: type[E]) -> list[E]:
    return [event for event in events if isinstance(event, kind)]


def _no_spend_projection() -> Projection:
    """`budget.project(chapter_call_costs, 0)` on a chapter with no page row:
    the bootstrap page estimate, nothing remaining, no samples."""
    return Projection(
        next_call=page_estimate(_GEMINI),
        remaining_chapter=Usd.from_micro(0),
        basis="estimate",
        sample_count=0,
    )


# =============================================================================
# Preconditions on the oracle itself
# =============================================================================


def test_the_interactive_row_prices_the_two_answers_at_the_written_out_figures() -> None:
    assert price(_GEMINI, _USAGE_1).cost == Usd.from_micro(_MICRO_1)
    assert price(_GEMINI, _USAGE_2).cost == Usd.from_micro(_MICRO_2)


def test_the_world_has_a_glossary_block_and_every_translated_line_reads_proposed(
    world: _World,
) -> None:
    assert world.block() != "", "the oracle's glossary block is empty; the control is broken"
    assert world.english() == {
        (0, 0): ("Kenji, wait", None, "proposed"),
        (0, 1): ("Senpai...", None, "proposed"),
        (1, 0): ("Where are you going", None, "proposed"),
        (1, 1): (None, None, "failed"),
        (2, 0): ("Kenji-sempai", None, "proposed"),
        (2, 1): (None, None, "proposed"),
    }


# =============================================================================
# The shapes the pinned Contract fixes
# =============================================================================


def test_corrections_applied_is_a_frozen_event_with_the_five_counts_in_order() -> None:
    from mangatl.domain.events import CorrectionsApplied  # type: ignore[attr-defined]

    names = [f.name for f in dataclasses.fields(CorrectionsApplied)]
    event = CorrectionsApplied(1, 2, 3, 4, 5)

    assert names == [
        "applied",
        "skipped_user_lines",
        "unchanged_returned",
        "chunks_run",
        "chunks_refused",
    ]
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.applied = 0  # type: ignore[misc]


def test_corrections_applied_is_a_run_event() -> None:
    import typing

    from mangatl.domain.events import CorrectionsApplied  # type: ignore[attr-defined]

    assert CorrectionsApplied in typing.get_args(RunEvent)


def test_page_lines_lives_in_the_domain_and_translate_re_exports_the_same_class() -> None:
    import mangatl.domain.correction as domain_correction

    page_lines = _domain_page_lines()

    assert page_lines is tc.PageLines, "translate.consistency.PageLines is a second class"
    assert "PageLines" in domain_correction.__all__
    assert [f.name for f in dataclasses.fields(page_lines)] == ["ordinal", "lines"]


def test_consistency_tools_is_frozen_with_the_four_bound_values_in_order() -> None:
    tools_type = _pipeline().ConsistencyTools
    tools = _tools()

    assert [f.name for f in dataclasses.fields(tools_type)] == [
        "text",
        "chunk",
        "parse",
        "max_output_tokens",
    ]
    with pytest.raises(dataclasses.FrozenInstanceError):
        tools.max_output_tokens = 0


def test_run_consistency_pass_takes_the_contracts_six_arguments_in_order() -> None:
    parameters = list(inspect.signature(_pipeline().run_consistency_pass).parameters)

    assert parameters == ["project", "run_id", "pass_", "tools", "model_id", "emit"]


def test_consistency_step_takes_the_pass_the_tools_and_the_model() -> None:
    parameters = list(inspect.signature(_pipeline().consistency_step).parameters)

    assert parameters == ["pass_", "tools", "model_id"]


# =============================================================================
# AC-1: corrections land on proposed lines, with the reason kept
# =============================================================================


def test_each_corrected_line_carries_the_correction_as_its_proposal_and_is_still_proposed(
    world: _World,
) -> None:
    world.run_pass(_Pass(_answer(_FIX_A, _FIX_B)))

    after = world.english()
    assert after[(0, 1)] == ("Senpai…", None, "proposed"), f"page 0 line 1 is {after[(0, 1)]}"
    assert after[(2, 0)] == ("Kenji-senpai", None, "proposed"), f"page 2 line 0 is {after[(2, 0)]}"


def test_lines_no_correction_names_keep_their_proposal(world: _World) -> None:
    before = world.english()

    world.run_pass(_Pass(_answer(_FIX_A, _FIX_B)))

    after = world.english()
    untouched = set(before) - {(0, 1), (2, 0)}
    assert {key: after[key] for key in untouched} == {key: before[key] for key in untouched}


def test_each_correction_is_recorded_with_the_previous_text_the_new_text_and_the_reason(
    world: _World,
) -> None:
    world.run_pass(_Pass(_answer(_FIX_A, _FIX_B)))

    assert corrections_for(world.project, 0) == (
        Correction(world.run_id, 0, 1, "Senpai...", "Senpai…", _REASON_A),
    )
    assert corrections_for(world.project, 1) == ()
    assert corrections_for(world.project, 2) == (
        Correction(world.run_id, 2, 0, "Kenji-sempai", "Kenji-senpai", _REASON_B),
    )


def test_the_pass_is_billed_as_one_chapter_level_row_at_the_interactive_rate(
    world: _World,
) -> None:
    world.run_pass(_Pass(_answer(_FIX_A, _FIX_B)))

    assert world.chapter_rows() == [
        (None, "standard", _MICRO_1, _GEMINI, "req-consistency-1", 1000, 200, world.run_id)
    ], f"the ledger's chapter-level rows are {world.chapter_rows()}"
    assert world.ledger_count() == 1


def test_corrections_applied_follows_one_chapter_level_call_priced(world: _World) -> None:
    returned = world.run_pass(_Pass(_answer(_FIX_A, _FIX_B)))

    expected = _corrections_applied(2, 0, 0, 1, 0)
    assert world.events == [
        CallPriced(
            ordinal=None,
            spent=Usd.from_micro(_MICRO_1),
            ceiling=DEFAULT_CEILING,
            projection=_no_spend_projection(),
        ),
        expected,
    ], f"emitted {world.events}"
    assert returned == expected


def test_the_step_emits_the_same_stream_as_the_pass_and_returns_nothing(world: _World) -> None:
    """Contract amendment RED-A1: the pass emits its `CorrectionsApplied`; the
    step adds no second one."""
    step = world.step(_Pass(_answer(_FIX_A, _FIX_B)))

    returned = step(world.project, world.run_id, world.events.append)

    assert returned is None
    assert [type(e).__name__ for e in world.events] == ["CallPriced", "CorrectionsApplied"]
    assert world.events[-1] == _corrections_applied(2, 0, 0, 1, 0)


def test_the_marker_is_the_passes_run_after_a_completed_pass(world: _World) -> None:
    assert world.marker() is None

    world.run_pass(_Pass(_answer(_FIX_A, _FIX_B)))

    assert world.marker() == world.run_id


def test_an_answer_with_no_corrections_bills_marks_and_reports_zero(world: _World) -> None:
    returned = world.run_pass(_Pass(_answer()))

    assert returned == _corrections_applied(0, 0, 0, 1, 0)
    assert world.correction_count() == 0
    assert len(world.chapter_rows()) == 1
    assert world.marker() == world.run_id


# =============================================================================
# AC-2: accepted, edited and reverted lines are never changed
# =============================================================================


def _commit_user_lines(world: _World) -> None:
    """(0, 0) accepted with its own text, (2, 0) edited, (0, 1) reverted."""
    commit_line(world.project, 0, 0, "Kenji, wait.", "accepted")
    commit_line(world.project, 2, 0, "Kenji-senpai, wait", "edited")
    commit_line(world.project, 0, 1, None, "reverted")


def test_a_correction_to_an_accepted_or_edited_line_changes_neither_line(world: _World) -> None:
    _commit_user_lines(world)
    before = world.english()
    assert before[(0, 0)][2] == "accepted" and before[(2, 0)][2] == "edited"

    world.run_pass(
        _Pass(_answer(_item(0, 0, "Kenji! Wait!", "tone"), _item(2, 0, "Senpai Kenji", "order")))
    )

    after = world.english()
    assert after[(0, 0)] == before[(0, 0)] == ("Kenji, wait", "Kenji, wait.", "accepted")
    assert after[(2, 0)] == before[(2, 0)] == ("Kenji-sempai", "Kenji-senpai, wait", "edited")


def test_a_correction_to_a_user_line_writes_no_correction_row(world: _World) -> None:
    _commit_user_lines(world)

    world.run_pass(
        _Pass(_answer(_item(0, 0, "Kenji! Wait!", "tone"), _item(2, 0, "Senpai Kenji", "order")))
    )

    assert world.correction_count() == 0, f"recorded {world.all_corrections()}"


def test_two_corrections_to_user_lines_read_applied_zero_skipped_two(world: _World) -> None:
    _commit_user_lines(world)

    returned = world.run_pass(
        _Pass(_answer(_item(0, 0, "Kenji! Wait!", "tone"), _item(2, 0, "Senpai Kenji", "order")))
    )

    assert returned == _corrections_applied(0, 2, 0, 1, 0)
    assert world.events[-1] == _corrections_applied(0, 2, 0, 1, 0)


def test_a_correction_to_a_reverted_line_is_skipped_too(world: _World) -> None:
    """Reverted is a user act (`COMMITTED_STATUSES`): the user said "not that"
    and the pass may not say it again."""
    _commit_user_lines(world)
    before = world.english()
    assert before[(0, 1)] == ("Senpai...", None, "reverted")

    returned = world.run_pass(_Pass(_answer(_item(0, 1, "Senpai…", _REASON_A))))

    assert world.english()[(0, 1)] == before[(0, 1)]
    assert world.correction_count() == 0
    assert returned == _corrections_applied(0, 1, 0, 1, 0)


def test_user_lines_are_skipped_while_proposed_ones_beside_them_are_applied(
    world: _World,
) -> None:
    """The negative control for the skips above: a pass that skipped every
    line would pass them. (1, 0) is still proposed and is applied."""
    _commit_user_lines(world)

    returned = world.run_pass(
        _Pass(
            _answer(
                _item(0, 0, "Kenji! Wait!", "tone"),
                _item(1, 0, "Where are you off to", "voice"),
            )
        )
    )

    assert returned == _corrections_applied(1, 1, 0, 1, 0)
    assert world.english()[(1, 0)] == ("Where are you off to", None, "proposed")
    assert corrections_for(world.project, 1) == (
        Correction(world.run_id, 1, 0, "Where are you going", "Where are you off to", "voice"),
    )


def test_an_item_equal_to_the_current_english_is_counted_unchanged_and_not_applied(
    world: _World,
) -> None:
    returned = world.run_pass(
        _Pass(_answer(_item(1, 0, "Where are you going", "restated"), _FIX_A))
    )

    assert returned == _corrections_applied(1, 0, 1, 1, 0)
    assert world.correction_count() == 1
    assert corrections_for(world.project, 1) == ()


def test_an_item_equal_to_a_user_lines_final_text_is_unchanged_not_skipped(world: _World) -> None:
    """`current` for an accepted line is its `final_en`: restating it is
    `unchanged_returned`, not a skipped user line."""
    _commit_user_lines(world)

    returned = world.run_pass(_Pass(_answer(_item(0, 0, "Kenji, wait.", "restated"))))

    assert returned == _corrections_applied(0, 0, 1, 1, 0)


# =============================================================================
# AC-3: the text the pass receives
# =============================================================================


def test_the_pass_is_sent_the_glossary_block_and_every_pages_proposals(world: _World) -> None:
    pass_ = _Pass(_answer())
    expected = tc.consistency_text(_untouched_pages(), world.block())

    world.run_pass(pass_)

    assert pass_.received == [expected], f"the pass was sent {pass_.received!r}"


def test_the_text_carries_final_en_for_user_lines_and_proposed_en_otherwise(
    world: _World,
) -> None:
    """Accepted and edited lines read their `final_en`; a reverted line its
    `proposed_en`; and an accepted line with no `final_en` its `proposed_en`
    (the control: an implementation reading `final_en` blindly sends `None`
    there and drops the line)."""
    _commit_user_lines(world)
    commit_line(world.project, 1, 0, None, "accepted")
    pass_ = _Pass(_answer())
    expected = tc.consistency_text(
        _pages(
            (0, ((0, "ケンジ、待って", "Kenji, wait."), (1, "先輩…", "Senpai..."))),
            (1, ((0, "どこへ行くの", "Where are you going"),)),
            (2, ((0, "ケンジ先輩", "Kenji-senpai, wait"),)),
        ),
        world.block(),
    )

    world.run_pass(pass_)

    assert pass_.received == [expected], f"the pass was sent {pass_.received!r}"


def test_an_excluded_line_is_absent_from_the_text(world: _World) -> None:
    world.project.set_excluded(0, 1, "user")
    pass_ = _Pass(_answer())
    expected = tc.consistency_text(
        _pages(
            (0, ((0, "ケンジ、待って", "Kenji, wait"),)),
            (1, ((0, "どこへ行くの", "Where are you going"),)),
            (2, ((0, "ケンジ先輩", "Kenji-sempai"),)),
        ),
        world.block(),
    )

    world.run_pass(pass_)

    assert pass_.received == [expected]


def test_a_page_with_no_english_is_dropped_before_chunking(gap_world: _World) -> None:
    chunk = _RecordingChunk()
    pass_ = _Pass(_answer())
    expected = tc.consistency_text(
        _pages(
            (0, ((0, "ケンジ、待って", "Kenji, wait"), (1, "先輩…", "Senpai..."))),
            (2, ((0, "ケンジ先輩", "Kenji-sempai"),)),
        ),
        gap_world.block(),
    )

    gap_world.run_pass(pass_, _tools(chunk=chunk))

    assert chunk.handed == [[0, 2]], f"chunk was handed pages {chunk.handed}"
    assert pass_.received == [expected]


def test_a_correction_to_a_line_the_text_did_not_show_fails_the_pass(world: _World) -> None:
    """(1, 1) is `failed`, absent from the text and from `current`, so the
    parse refuses the answer (`UnknownLine`) after the bill and before any
    write; the marker stays unset."""
    with pytest.raises(tc.UnknownLine):
        world.run_pass(_Pass(_answer(_item(1, 1, "...", "filled in"), _FIX_A)))

    assert len(world.chapter_rows()) == 1, "the call was made: its bill stands"
    assert world.correction_count() == 0
    assert world.english()[(0, 1)] == ("Senpai...", None, "proposed")
    assert world.marker() is None


# =============================================================================
# AC-4: the guard, before each chunk's call
# =============================================================================


def test_a_ceiling_below_the_first_chunks_estimate_refuses_before_the_pass_is_called(
    world: _World,
) -> None:
    text = tc.consistency_text(_untouched_pages(), world.block())
    world.set_ceiling(_estimate(text).micro() - 1)
    pass_ = _Pass(_answer(_FIX_A, _FIX_B))

    with pytest.raises(BudgetRefused):
        world.run_pass(pass_)

    assert pass_.calls == 0


def test_a_refused_first_chunk_writes_nothing_emits_nothing_and_leaves_the_marker_unset(
    world: _World,
) -> None:
    text = tc.consistency_text(_untouched_pages(), world.block())
    world.set_ceiling(_estimate(text).micro() - 1)
    before = world.english()

    with pytest.raises(BudgetRefused):
        world.run_pass(_Pass(_answer(_FIX_A, _FIX_B)))

    assert world.ledger_count() == 0
    assert world.correction_count() == 0
    assert world.english() == before
    assert world.events == [], f"a refused pass emitted {world.events}"
    assert world.marker() is None


def test_a_ceiling_exactly_at_the_first_chunks_estimate_permits_it(world: _World) -> None:
    """Inclusive, `Budget.check`'s rule. The control for the refusal above: an
    estimate built on more output than `CONSISTENCY_MAX_OUTPUT_TOKENS` (8,192)
    or on a longer text refuses here; one built on less permits one below."""
    text = tc.consistency_text(_untouched_pages(), world.block())
    world.set_ceiling(_estimate(text).micro())
    pass_ = _Pass(_answer(_FIX_A))

    world.run_pass(pass_)

    assert pass_.calls == 1


def test_the_refusal_carries_the_first_chunks_estimate_and_the_rest_of_the_pass(
    world: _World,
) -> None:
    """`Projection(next_call=estimate_0, remaining_chapter=estimate_0 +
    estimate_1, basis="estimate", sample_count=0)` - the remaining chunks are
    the rest of the chapter (Contract, "Per chunk")."""
    limit, texts = _two_chunks(world)
    first, second = (_estimate(text) for text in texts)
    world.set_ceiling(first.micro() - 1)

    with pytest.raises(BudgetRefused) as raised:
        world.run_pass(_Pass(), _tools(chunk=partial(tc.chunk_pages, max_tokens=limit)))

    decision = raised.value.decision
    assert decision.projection == Projection(
        next_call=first,
        remaining_chapter=Usd.from_micro(first.micro() + second.micro()),
        basis="estimate",
        sample_count=0,
    ), f"the refusal projected {decision.projection}"
    assert decision.spent == Usd.from_micro(0)
    assert decision.ceiling == Usd.from_micro(first.micro() - 1)


def test_the_guard_counts_what_the_chapter_has_already_spent(world: _World) -> None:
    """20 micro already spent on page 0 (10 input tokens x 2) against a ceiling
    19 micro above the estimate refuses; 20 above permits."""
    record_call(
        world.project, world.run_id, 0, "req-page-0", price(_GEMINI, TokenUsage(10, 0, 0, 0))
    )
    text = tc.consistency_text(_untouched_pages(), world.block())
    world.set_ceiling(_estimate(text).micro() + 19)
    pass_ = _Pass(_answer())

    with pytest.raises(BudgetRefused):
        world.run_pass(pass_)
    assert pass_.calls == 0

    world.set_ceiling(_estimate(text).micro() + 20)
    world.run_pass(pass_)
    assert pass_.calls == 1


def test_a_ceiling_admitting_only_the_first_of_two_chunks_applies_and_bills_the_first(
    world: _World,
) -> None:
    """Chunk 1 (pages 0, 1) runs and bills 4,400 micro; chunk 2 (page 2) would
    then land one micro-dollar over: `4400 + estimate_1 - 1` admits
    `estimate_0` (asserted) and refuses `4400 + estimate_1`."""
    limit, texts = _two_chunks(world)
    first, second = (_estimate(text) for text in texts)
    ceiling = _MICRO_1 + second.micro() - 1
    assert first.micro() <= ceiling, (first, ceiling)
    world.set_ceiling(ceiling)
    pass_ = _Pass(_answer(_FIX_A), _answer(_FIX_B))

    returned = world.run_pass(pass_, _tools(chunk=partial(tc.chunk_pages, max_tokens=limit)))

    assert pass_.received == texts[:1], "the pass was not called exactly once, on chunk 1"
    assert world.english()[(0, 1)] == ("Senpai…", None, "proposed")
    assert world.english()[(2, 0)] == ("Kenji-sempai", None, "proposed")
    assert world.chapter_rows() == [
        (None, "standard", _MICRO_1, _GEMINI, "req-consistency-1", 1000, 200, world.run_id)
    ]
    assert returned == _corrections_applied(1, 0, 0, 1, 1)
    assert world.events[-1] == returned
    assert world.marker() is None, "a pass refused part-way was marked as run"


def test_a_ceiling_admitting_both_chunks_exactly_runs_both_and_marks_the_pass(
    world: _World,
) -> None:
    """The control for the part-way refusal: one micro-dollar more and the
    second chunk lands exactly on the ceiling."""
    limit, texts = _two_chunks(world)
    second = _estimate(texts[1])
    world.set_ceiling(_MICRO_1 + second.micro())
    pass_ = _Pass(_answer(_FIX_A), _answer(_FIX_B))

    returned = world.run_pass(pass_, _tools(chunk=partial(tc.chunk_pages, max_tokens=limit)))

    assert pass_.received == texts
    assert returned == _corrections_applied(2, 0, 0, 2, 0)
    assert world.marker() == world.run_id


def test_a_page_too_large_for_any_chunk_propagates_before_any_call(world: _World) -> None:
    pass_ = _Pass(_answer())

    with pytest.raises(tc.PageTooLarge):
        world.run_pass(pass_, _tools(chunk=partial(tc.chunk_pages, max_tokens=1)))

    assert pass_.calls == 0
    assert world.marker() is None


# =============================================================================
# AC-5: one chapter-level ledger row per chunk that ran
# =============================================================================


def test_each_chunk_has_one_chapter_level_row_with_its_own_request_id(world: _World) -> None:
    limit, _ = _two_chunks(world)

    world.run_pass(
        _Pass(_answer(_FIX_A), _answer(_FIX_B)),
        _tools(chunk=partial(tc.chunk_pages, max_tokens=limit)),
    )

    assert world.chapter_rows() == [
        (None, "standard", _MICRO_1, _GEMINI, "req-consistency-1", 1000, 200, world.run_id),
        (None, "standard", _MICRO_2, _GEMINI, "req-consistency-2", 500, 100, world.run_id),
    ], f"the ledger's chapter-level rows are {world.chapter_rows()}"


def test_chapter_total_grows_by_the_chunks_sum_and_the_page_samples_do_not_change(
    world: _World,
) -> None:
    """A page row first (20 micro), so `chapter_call_costs` has something to
    keep: chapter-level rows are spend, never samples (MT-103 AC-2)."""
    record_call(
        world.project, world.run_id, 0, "req-page-0", price(_GEMINI, TokenUsage(10, 0, 0, 0))
    )
    limit, _ = _two_chunks(world)
    total_before = chapter_total(world.project)
    samples_before = chapter_call_costs(world.project)

    world.run_pass(
        _Pass(_answer(_FIX_A), _answer(_FIX_B)),
        _tools(chunk=partial(tc.chunk_pages, max_tokens=limit)),
    )

    assert chapter_total(world.project) == Usd.from_micro(
        total_before.micro() + _MICRO_1 + _MICRO_2
    )
    assert chapter_call_costs(world.project) == samples_before == (Usd.from_micro(20),)


def test_each_chunk_is_announced_by_its_own_chapter_level_call_priced(world: _World) -> None:
    limit, _ = _two_chunks(world)

    world.run_pass(
        _Pass(_answer(_FIX_A), _answer(_FIX_B)),
        _tools(chunk=partial(tc.chunk_pages, max_tokens=limit)),
    )

    assert world.events == [
        CallPriced(None, Usd.from_micro(_MICRO_1), DEFAULT_CEILING, _no_spend_projection()),
        CallPriced(
            None, Usd.from_micro(_MICRO_1 + _MICRO_2), DEFAULT_CEILING, _no_spend_projection()
        ),
        _corrections_applied(2, 0, 0, 2, 0),
    ], f"emitted {world.events}"


# =============================================================================
# Already ran, and nothing to send
# =============================================================================


def test_a_chapter_whose_pass_already_ran_calls_nothing_writes_nothing_and_emits_nothing(
    world: _World,
) -> None:
    world.project.mark_consistency_run(world.run_id)  # type: ignore[attr-defined]
    pass_ = _Pass(_answer(_FIX_A))
    before = world.english()

    returned = world.run_pass(pass_)

    assert returned is None
    assert pass_.calls == 0
    assert world.events == []
    assert world.ledger_count() == 0
    assert world.english() == before
    assert world.marker() == world.run_id


def test_a_second_pass_after_a_completed_one_does_not_call_again(world: _World) -> None:
    pass_ = _Pass(_answer(_FIX_A), _answer(_FIX_B))
    world.run_pass(pass_)
    world.events.clear()

    returned = world.run_pass(pass_)

    assert pass_.calls == 1, f"the pass was called {pass_.calls} times over two passes"
    assert returned is None
    assert world.events == []
    assert len(world.chapter_rows()) == 1


def test_a_pass_refused_part_way_runs_whole_again_later(world: _World) -> None:
    """The marker stays unset after a part-way refusal, so a later run under a
    higher ceiling runs every chunk again; chunk 1's already-applied correction
    then comes back as `unchanged_returned`."""
    limit, texts = _two_chunks(world)
    world.set_ceiling(_MICRO_1 + _estimate(texts[1]).micro() - 1)
    tools = _tools(chunk=partial(tc.chunk_pages, max_tokens=limit))
    world.run_pass(_Pass(_answer(_FIX_A)), tools)
    world.set_ceiling(None)
    again = _Pass(_answer(_FIX_A), _answer(_FIX_B))

    returned = world.run_pass(again, tools)

    assert again.calls == 2
    assert returned == _corrections_applied(1, 0, 1, 2, 0)
    assert world.marker() == world.run_id


def test_a_volume_with_no_english_calls_nothing_and_is_marked_with_zero_counts(
    untranslated_world: _World,
) -> None:
    pass_ = _Pass(_answer())

    returned = untranslated_world.run_pass(pass_)

    assert pass_.calls == 0
    assert returned == _corrections_applied(0, 0, 0, 0, 0)
    assert untranslated_world.events == [_corrections_applied(0, 0, 0, 0, 0)]
    assert untranslated_world.ledger_count() == 0
    assert untranslated_world.marker() == untranslated_world.run_id


def test_a_volume_with_no_english_is_not_guarded_so_a_zero_ceiling_does_not_refuse(
    untranslated_world: _World,
) -> None:
    untranslated_world.set_ceiling(0)

    returned = untranslated_world.run_pass(_Pass(_answer()))

    assert returned == _corrections_applied(0, 0, 0, 0, 0)


# =============================================================================
# Apply's order: the row first, then the write
# =============================================================================


def test_a_refused_proposal_write_leaves_the_correction_recorded_and_the_line_unchanged(
    world: _World,
) -> None:
    """`record_correction` **then** `write_proposed` (Contract, "Apply"): with
    the line's `proposed_en` update refused by a trigger, the row is there and
    the line is not changed. Written the other way round, the refused write
    comes first and no row is recorded."""
    connection = sqlite3.connect(world.db_path)
    try:
        connection.execute(
            "CREATE TRIGGER refuse_proposed BEFORE UPDATE OF proposed_en ON line"
            " BEGIN SELECT RAISE(ABORT, 'proposed_en refused'); END"
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(sqlite3.DatabaseError):
        world.run_pass(_Pass(_answer(_FIX_A)))

    assert world.all_corrections() == [
        Correction(world.run_id, 0, 1, "Senpai...", "Senpai…", _REASON_A)
    ]
    assert world.english()[(0, 1)] == ("Senpai...", None, "proposed")
    assert world.marker() is None


# =============================================================================
# AC-6, batch half: the step as `collect_volume`'s postlude
# =============================================================================


def _translated(lines: Mapping[int, str], n: int) -> TranslationResult:
    return TranslationResult(
        lines=dict(lines),
        usage=TokenUsage(100, 10, 0, 0),
        call=CallInfo(f"item-{n}", _GEMINI),
        proposed_terms=(),
    )


class _Collector:
    """Answers every page of the job with `_PROPOSED`'s lines."""

    def __call__(self, provider_job_id: str, pages: Sequence[Any]) -> Any:
        return BatchResults(
            {
                page.ordinal: _translated(_PROPOSED.get(page.ordinal, {}), page.ordinal)
                for page in pages
            }
        )


def _job(world: _World, first: int, last: int, name: str) -> BatchJob:
    from mangatl.store.batch import pending_jobs

    job_id = record_submission(world.project, world.run_id, name, _GEMINI, first, last)
    (job,) = [j for j in pending_jobs(world.project) if j.id == job_id]
    return job


def _collect(world: _World, job: BatchJob, step: Any) -> Any:
    return _collect_volume(
        world.project,
        job,
        _Collector(),
        page_estimate(_GEMINI, pricing="batch"),
        world.events.append,
        postlude=step,
    )


def test_collecting_the_volumes_only_job_runs_the_pass_after_batch_collected(
    untranslated_world: _World,
) -> None:
    world = untranslated_world
    job = _job(world, 0, 2, "batches/only")
    pass_ = _Pass(_answer(_FIX_A, _FIX_B))

    _collect(world, job, world.step(pass_))

    assert pass_.received == [tc.consistency_text(_untouched_pages(), world.block())]
    names = [type(e).__name__ for e in world.events]
    assert names[-3:] == ["BatchCollected", "CallPriced", "CorrectionsApplied"], names
    assert world.events[-1] == _corrections_applied(2, 0, 0, 1, 0)
    assert world.marker() == job.run_id


def test_a_second_collection_after_the_pass_ran_does_not_call_it_again(
    untranslated_world: _World,
) -> None:
    world = untranslated_world
    pass_ = _Pass(_answer(_FIX_A, _FIX_B))
    step = world.step(pass_)
    _collect(world, _job(world, 0, 2, "batches/first"), step)
    world.events.clear()

    _collect(world, _job(world, 0, 2, "batches/again"), step)

    assert pass_.calls == 1, f"the pass was called {pass_.calls} times over two collections"
    assert [type(e).__name__ for e in world.events][-1] == "BatchCollected"


def test_a_job_that_is_not_the_last_pending_one_does_not_run_the_pass(
    untranslated_world: _World,
) -> None:
    world = untranslated_world
    first = _job(world, 0, 1, "batches/first")
    last = _job(world, 2, 2, "batches/last")
    pass_ = _Pass(_answer(_FIX_A, _FIX_B))
    step = world.step(pass_)

    _collect(world, first, step)
    assert pass_.calls == 0, "the pass ran while a job of the volume was still submitted"

    _collect(world, last, step)
    assert pass_.calls == 1


def test_a_refused_pass_after_collection_emits_run_aborted_budget_and_returns_the_answer(
    untranslated_world: _World,
) -> None:
    world = untranslated_world
    world.set_ceiling(0)
    job = _job(world, 0, 2, "batches/only")
    pass_ = _Pass(_answer(_FIX_A))

    answer = _collect(world, job, world.step(pass_))

    assert isinstance(answer, BatchResults)
    assert pass_.calls == 0
    assert world.events[-1] == RunAborted(reason=BUDGET, ordinal=None)
    assert isinstance(world.events[-2], BatchCollected)
    assert world.marker() is None


def test_a_failed_pass_after_collection_emits_run_aborted_with_its_type_and_message(
    untranslated_world: _World,
) -> None:
    world = untranslated_world
    job = _job(world, 0, 2, "batches/only")
    pass_ = _Pass(raises=RuntimeError("the provider hung up"))

    answer = _collect(world, job, world.step(pass_))

    assert isinstance(answer, BatchResults)
    assert world.events[-1] == RunAborted(reason="RuntimeError: the provider hung up", ordinal=None)
    assert world.marker() is None


# =============================================================================
# AC-6, synchronous half: the step as `run_chapter`'s postlude
# =============================================================================


@dataclass
class _NoopStage:
    name: str = "noop"

    def run(self, ctx: PageContext) -> None:
        return None

    def is_done(self, ctx: PageContext) -> bool:
        return ctx.project.page_status(ctx.page.ordinal) == PAGE_DONE


def _never() -> bool:
    return False


def _run(world: _World, step: Any) -> tuple[list[RunEvent], RunOutcome]:
    events: list[RunEvent] = []
    outcome = _run_chapter(world.project, (_NoopStage(),), events.append, _never, postlude=step)
    return events, outcome


def test_a_run_ends_with_the_pass_between_the_last_page_and_run_finished(world: _World) -> None:
    pass_ = _Pass(_answer(_FIX_A, _FIX_B))

    events, outcome = _run(world, world.step(pass_))

    names = [type(e).__name__ for e in events]
    assert names[-4:] == ["StageFinished", "CallPriced", "CorrectionsApplied", "RunFinished"], names
    assert _of(events, StageFinished)[-1].ordinal == 2
    assert events[-2] == _corrections_applied(2, 0, 0, 1, 0)
    assert outcome.outcome == RUN_FINISHED
    assert world.marker() == outcome.run_id
    assert world.chapter_rows()[0][-1] == outcome.run_id, "the bill is not the run's"


def test_a_second_run_does_not_call_the_pass_again(world: _World) -> None:
    pass_ = _Pass(_answer(_FIX_A, _FIX_B))
    step = world.step(pass_)
    _run(world, step)

    events, outcome = _run(world, step)

    assert pass_.calls == 1, f"the pass was called {pass_.calls} times over two runs"
    assert outcome.outcome == RUN_FINISHED
    assert _of(events, CallPriced) == []
    assert [type(e).__name__ for e in events if type(e).__name__ == "CorrectionsApplied"] == []


def test_a_refused_pass_ends_the_run_aborted_budget_with_every_page_done(world: _World) -> None:
    world.set_ceiling(0)
    pass_ = _Pass(_answer(_FIX_A))

    events, outcome = _run(world, world.step(pass_))

    assert pass_.calls == 0
    assert events[-1] == RunAborted(reason=BUDGET, ordinal=None)
    assert outcome.outcome == RUN_ABORTED and outcome.aborted_reason == BUDGET
    assert outcome.pages_done == 3
    assert _of(events, RunFinished) == []
    assert world.marker() is None


def test_a_parse_failure_ends_the_run_aborted_naming_the_error_and_no_page(world: _World) -> None:
    events, outcome = _run(world, world.step(_Pass("not json")))

    last = events[-1]
    assert isinstance(last, RunAborted) and last.ordinal is None
    assert last.reason is not None and last.reason.startswith("JSONDecodeError: "), last.reason
    assert outcome.outcome == RUN_ABORTED and outcome.pages_done == 3
