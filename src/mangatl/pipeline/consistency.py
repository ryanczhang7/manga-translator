"""The consistency pass, applied: corrections land on untouched proposals (MT-115).

EPIC-09 PO-7. Once every page of a volume is translated, one text-only pass
reads the volume's current English and returns the lines it would change, each
with a reason (MT-114 builds the request and reads the answer). This module
runs it from the pipeline and applies what it says:

- **What the pass sees** (AC-3): pages in ordinal order, each line's English as
  the volume will read it - the user's `final_en` for an `accepted` or `edited`
  line that has one, `proposed_en` otherwise (`proposed`, `reverted`, an
  accepted line with no text of its own) - and nothing for a `failed` or
  `excluded` line. Statuses are the derived ones `store.lines.read_review_lines`
  reports. A page with no English is dropped before chunking.
- **The guard before each chunk's call** (AC-4, D6): the chunk's
  `estimate_tokens` in and the request's output limit out, priced at the bound
  model's interactive row, against everything the chapter has spent, with the
  rest of the pass as the remaining chapter. A refused **first** chunk raises
  `BudgetRefused` with nothing written; a refused later chunk stops the pass,
  which reports how many ran and leaves the marker unset.
- **Each chunk billed as a chapter-level row** (AC-5): `record_call(..., None,
  ...)` at the standard tier, then `CallPriced(ordinal=None)`.
- **Apply** (AC-1, AC-2): a correction to a `proposed` line is recorded
  (`store.corrections.record_correction`) **and then** written as the line's
  new `proposed_en` - two store transactions, the row first, so a crash between
  them leaves a recorded change that was not applied rather than an applied
  change nobody recorded. A correction to any other line is counted and
  skipped: the user's lines are never changed.
- **Once per chapter** (AC-6): `chapter.consistency_run_id` set means the pass
  completed; it is set only after the last chunk.

**This module may not import `mangatl.translate`** (the layers contract), so the
pass is a `Callable` (`compose` binds `partial(gemini.run_consistency, client)`)
and the text, the chunking and the parse arrive as `ConsistencyTools`, bound by
`compose` from `translate.consistency`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from mangatl.domain.budget import Projection, call_estimate, page_estimate
from mangatl.domain.correction import ConsistencyResult, PageLines, ParsedCorrections
from mangatl.domain.events import CallPriced, CorrectionsApplied, RunEvent
from mangatl.domain.glossary import MAX_GLOSSARY_TOKENS, estimate_tokens, render_block
from mangatl.domain.line import Line, LineStatus
from mangatl.domain.money import Usd
from mangatl.domain.rates import price
from mangatl.domain.translation import TokenUsage
from mangatl.pipeline.prelude import ChapterStep
from mangatl.pipeline.stage import BudgetRefused
from mangatl.pipeline.translate_stage import budget_for
from mangatl.store.corrections import record_correction
from mangatl.store.glossary import read_entries
from mangatl.store.ledger import chapter_call_costs, chapter_total, record_call
from mangatl.store.lines import read_review_lines
from mangatl.store.project import Project

__all__ = [
    "ConsistencyPass",
    "ConsistencyTools",
    "consistency_step",
    "run_consistency_pass",
]

#: One chunk's text to its raw answer, usage and call identity.
ConsistencyPass = Callable[[str], ConsistencyResult]

#: The statuses whose `final_en`, when there is one, is what the volume reads.
_USER_TEXT_STATUSES: frozenset[LineStatus] = frozenset({"accepted", "edited"})

#: The statuses with no English for the pass to read.
_NO_TEXT_STATUSES: frozenset[LineStatus] = frozenset({"failed", "excluded"})


@dataclass(frozen=True)
class ConsistencyTools:
    """`translate.consistency`'s four, bound by `compose`: the chunk's text,
    the volume's cut into chunks, the answer's parse, and the output limit the
    request is sent with (which the guard's estimate is built on)."""

    text: Callable[[Sequence[PageLines], str], str]
    chunk: Callable[[Sequence[PageLines], str], Sequence[Sequence[PageLines]]]
    parse: Callable[[str, Mapping[tuple[int, int], str]], ParsedCorrections]
    max_output_tokens: int


def _english(line: Line) -> str | None:
    """The line's English as the volume will read it (module docstring)."""
    if line.status in _USER_TEXT_STATUSES and line.final_en is not None:
        return line.final_en
    if line.status in _NO_TEXT_STATUSES:
        return None
    return line.proposed_en


def _read_pages(
    project: Project,
) -> tuple[list[PageLines], dict[tuple[int, int], tuple[str, LineStatus]]]:
    """Every page with English, in ordinal order, and each shown line's
    English and status by `(ordinal, reading_index)`."""
    pages: list[PageLines] = []
    shown: dict[tuple[int, int], tuple[str, LineStatus]] = {}
    for page in project.pages():
        lines: list[tuple[int, str, str | None]] = []
        for line in read_review_lines(project, page.ordinal):
            english = None if line is None else _english(line)
            if line is None or english is None:
                continue
            lines.append((line.reading_index, line.source_ja, english))
            shown[(page.ordinal, line.reading_index)] = (english, line.status)
        if lines:
            pages.append(PageLines(page.ordinal, tuple(lines)))
    return pages, shown


def run_consistency_pass(
    project: Project,
    run_id: int,
    pass_: ConsistencyPass,
    tools: ConsistencyTools,
    model_id: str,
    emit: Callable[[RunEvent], None],
) -> CorrectionsApplied | None:
    """Run the pass over the chapter and apply its corrections (module docstring).

    Returns `None`, doing nothing, when the chapter's pass already ran;
    otherwise the `CorrectionsApplied` it also emits. Raises `BudgetRefused`
    when the first chunk is refused, before anything is called or written;
    lets `tools.chunk`'s, `pass_`'s, `tools.parse`'s and the store's failures
    propagate, with earlier chunks' writes standing and the marker unset.
    """
    if project.consistency_run_id() is not None:
        return None

    glossary_block = render_block(read_entries(project), MAX_GLOSSARY_TOKENS)
    pages, shown = _read_pages(project)
    if not pages:
        project.mark_consistency_run(run_id)
        nothing = CorrectionsApplied(0, 0, 0, 0, 0)
        emit(nothing)
        return nothing

    chunks = list(tools.chunk(pages, glossary_block))
    texts = [tools.text(chunk, glossary_block) for chunk in chunks]
    estimates = [
        call_estimate(model_id, TokenUsage(estimate_tokens(text), tools.max_output_tokens, 0, 0))
        for text in texts
    ]

    applied = skipped = unchanged = 0
    for i, (chunk, text) in enumerate(zip(chunks, texts, strict=True)):
        budget = budget_for(project, page_estimate(model_id))
        decision = budget.check(
            chapter_total(project),
            Projection(
                next_call=estimates[i],
                # The chunks still to run are the rest of the chapter.
                remaining_chapter=Usd.from_micro(sum(e.micro() for e in estimates[i:])),
                basis="estimate",
                sample_count=len(chapter_call_costs(project)),
            ),
        )
        if not decision.permitted:
            if i == 0:
                raise BudgetRefused(decision)
            stopped = CorrectionsApplied(applied, skipped, unchanged, i, len(chunks) - i)
            emit(stopped)
            return stopped

        result = pass_(text)
        record_call(
            project,
            run_id,
            None,
            result.call.request_id,
            price(result.call.model_id, result.usage),
        )
        emit(
            CallPriced(
                ordinal=None,
                spent=chapter_total(project),
                ceiling=budget.ceiling,
                # Every page is behind the pass.
                projection=budget.project(chapter_call_costs(project), 0),
            )
        )

        current = {
            (page.ordinal, index): shown[(page.ordinal, index)][0]
            for page in chunk
            for index, _ja, _en in page.lines
        }
        parsed = tools.parse(result.text, current)
        for fix in parsed.corrections:
            key = (fix.page_ordinal, fix.reading_index)
            if shown[key][1] != "proposed":
                skipped += 1
                continue
            # The row first, then the write: each opens its own transaction.
            p, n = key
            record_correction(project, run_id, p, n, current[key], fix.corrected_en, fix.reason)
            project.write_proposed(p, {n: fix.corrected_en})
            applied += 1
        unchanged += parsed.unchanged_returned

    project.mark_consistency_run(run_id)
    done = CorrectionsApplied(applied, skipped, unchanged, len(chunks), 0)
    emit(done)
    return done


def consistency_step(pass_: ConsistencyPass, tools: ConsistencyTools, model_id: str) -> ChapterStep:
    """The pass as a `ChapterStep`, for `collect_volume` and `run_chapter`'s
    `postlude`. It emits nothing of its own (RED-A1): `run_consistency_pass`
    emits its `CorrectionsApplied`."""

    def step(project: Project, run_id: int, emit: Callable[[RunEvent], None]) -> None:
        run_consistency_pass(project, run_id, pass_, tools, model_id, emit)

    return step
