"""The chapter step: work the run does once, before page 1 (MT-105).

`run_chapter` walks pages through per-page stages; a `ChapterStep` is the one
thing it runs for the chapter as a whole, after `RunStarted` and before the
first `PageStarted`. The only step today is the glossary pre-pass
(EPIC-09 PO-2): one call that proposes the volume's terms up front so every
page is translated against the same glossary.

**This module may not import `mangatl.translate`** (the layers contract and the
"Only translate imports anthropic / google.genai" contracts, exactly as
`translate_stage` records). So the proposer is a `Callable` - a bare
`partial(gemini.propose_glossary, client)` satisfies `GlossaryProposer` - and
the listing it is sent and its output limit are arguments `compose` binds
(MT-105 RED-A1): `translate.glossary_pass.glossary_pass_text` and
`GLOSSARY_PASS_MAX_OUTPUT_TOKENS`. A default here would be `translate`'s value
spelled a second time.

The order of `glossary_prelude`'s step is the story's, and each move is a test
away from being wrong:

1. **The marker first.** `glossary_proposed_at` set means the pass ran and its
   terms were written; nothing else is evidence of that - a ledger row proves a
   bill, not a write.
2. **An empty listing skips before the guard** (PO-1, AC-7): no call, no event,
   no ledger row and no marker, so a later run with OCR stored still proposes.
   A fresh chapter's first interactive run is this case.
3. **The guard before the call** (D6). The estimate is the listing's
   `estimate_tokens` in and the request's output limit out, priced at the bound
   model's interactive row; `Budget.check` is the existing inclusive
   comparison against everything the chapter has spent.
4. **The bill in its own transaction, first**, then `CallPriced(ordinal=None)`,
   then the merged terms and the marker in **one** transaction
   (`store.glossary.write_proposed_glossary`). A failed term write leaves the
   bill - the call was made and paid for - and neither terms nor marker.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from mangatl.domain.budget import Projection, call_estimate, page_estimate
from mangatl.domain.events import CallPriced, RunEvent
from mangatl.domain.glossary import estimate_tokens, merge
from mangatl.domain.line import OcrResult
from mangatl.domain.rates import price
from mangatl.domain.translation import GlossaryProposal, TokenUsage
from mangatl.pipeline.stage import BudgetRefused, Stage
from mangatl.pipeline.translate_stage import budget_for
from mangatl.store.glossary import read_entries, write_proposed_glossary
from mangatl.store.ledger import chapter_call_costs, chapter_total, record_call
from mangatl.store.project import Project

__all__ = [
    "ChapterStep",
    "GlossaryListing",
    "GlossaryProposer",
    "Pipeline",
    "glossary_prelude",
]

#: The volume's OCR, one sequence per page in ordinal order, to its proposal.
GlossaryProposer = Callable[[Sequence[Sequence[OcrResult]]], GlossaryProposal]

#: The text the proposer sends for those pages - what the estimate is built on.
GlossaryListing = Callable[[Sequence[Sequence[OcrResult]]], str]

#: `(project, run_id, emit)`: run once for the chapter, before the first page.
ChapterStep = Callable[[Project, int, Callable[[RunEvent], None]], None]


@dataclass(frozen=True)
class Pipeline:
    """What `compose.build_pipeline` hands a caller: the page stages and the
    chapter step to run before them (`None` when there is none).

    A dataclass rather than a pair so that a caller still treating the return
    as the stage tuple fails loudly - `Pipeline` is not iterable - instead of
    iterating `(stages, prelude)` as two stages (RED-A2). It lives here and not
    in `compose` so `ui` and `cli` can name it without the composition root.
    """

    stages: tuple[Stage, ...]
    prelude: ChapterStep | None


def glossary_prelude(
    propose: GlossaryProposer,
    model_id: str,
    *,
    listing: GlossaryListing,
    max_output_tokens: int,
) -> ChapterStep:
    """The glossary pre-pass as a `ChapterStep` (module docstring, steps 1-4).

    `model_id` prices the guard's estimate, and is the bound provider's model;
    the bill itself is priced at the model the answer reports. Raises
    `BudgetRefused` when the guard refuses, before `propose` is called; any
    other failure (the proposer's, an unpriceable answer, a refused write)
    propagates for the runner to report.
    """

    def step(project: Project, run_id: int, emit: Callable[[RunEvent], None]) -> None:
        if project.glossary_proposed_at() is not None:
            return
        pages = [project.read_lines(page.ordinal) for page in project.pages()]
        text = listing(pages)
        if text == "":
            return

        estimate = call_estimate(
            model_id, TokenUsage(estimate_tokens(text), max_output_tokens, 0, 0)
        )
        budget = budget_for(project, page_estimate(model_id))
        decision = budget.check(
            chapter_total(project),
            Projection(
                next_call=estimate,
                remaining_chapter=estimate,
                basis="estimate",
                sample_count=len(chapter_call_costs(project)),
            ),
        )
        if not decision.permitted:
            raise BudgetRefused(decision)

        proposal = propose(pages)
        record_call(
            project,
            run_id,
            None,
            proposal.call.request_id,
            price(proposal.call.model_id, proposal.usage),
        )
        emit(
            CallPriced(
                ordinal=None,
                spent=chapter_total(project),
                ceiling=budget.ceiling,
                # PO-7: the pass sits before page 1, so every page is ahead of it.
                projection=budget.project(chapter_call_costs(project), len(pages)),
            )
        )
        before = read_entries(project)
        unchanged = set(before)
        after = merge(before, proposal.terms, 0)
        write_proposed_glossary(project, [entry for entry in after if entry not in unchanged])

    return step
