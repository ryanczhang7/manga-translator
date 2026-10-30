"""`mangatl.pipeline.resume`: a re-run is stated before it runs (MT-124).

**AC-1..AC-6, all mechanical (C-4).** Every expected value below is a count, a
mapping, a `Usd` read out of `domain.budget` / `store.ledger`, or a
byte-identical dump - nothing is estimated here, and the money is the guard's
own figure, *read out* through the same calls `TranslateStage.run` makes
(`budget_for(...).project(chapter_call_costs(...), n)`), never re-derived from
a formula of this file's.

Conventions, load-bearing rather than stylistic:

- **Fakes follow `test_pipeline.py`'s recording stages (C-3).** `_Recorder`'s
  `is_done` answers from a set of ordinals the test chose and writes down every
  call, and its `run` raises: a preview that ran a stage fails loudly (AC-5).
- **Stage order is pinned with names that do not sort into it.** `a, b` is
  both stage order and alphabetical order, so AC-1's literal alone cannot tell
  "stage order" from `sorted(...)`; the `b, a` case can.
- **AC-6 uses the real `build_stages` over callables that raise if called**,
  and its page is `done` in the store while `clean` is not - so a preview that
  read `page_status` instead of each stage's `is_done` (DV-1) fails it.
- **AC-5's dump is taken by a plain `sqlite3` connection with the project
  closed**, before and after, so an uncommitted write cannot hide and the
  observer shares nothing with `mangatl.store`.

What these tests do NOT constrain: how `rerun_preview` iterates (page-major or
stage-major), whether it builds one `PageContext` per page or per call, whether
`pending` is a plain `dict` or another insertion-ordered `Mapping` (it is
compared with `==` and its key order with `list(...)`), and where `_NO_RUN`
lives - only that the context a stage sees carries `run_id == 0` and an
`emit` that raises `RuntimeError` (C-2).
"""

from __future__ import annotations

import dataclasses
import sqlite3
from collections.abc import Callable, Iterable, Iterator, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from mangatl.domain.budget import DEFAULT_CEILING, MIN_SAMPLES_FOR_PROJECTION
from mangatl.domain.line import OcrResult
from mangatl.domain.money import Usd
from mangatl.domain.rates import CostRecord
from mangatl.domain.region import RawRegion
from mangatl.domain.translation import TranslationResult
from mangatl.pipeline.resume import RerunPreview, rerun_preview
from mangatl.pipeline.stage import PageContext, Stage
from mangatl.pipeline.stages import build_stages
from mangatl.pipeline.translate_stage import budget_for
from mangatl.store.intake import read_chapter
from mangatl.store.ledger import chapter_call_costs, chapter_total, record_call
from mangatl.store.project import PAGE_DONE, Project, create_project, open_project, project_dir_for

if TYPE_CHECKING:
    from mangatl.domain.glossary import PromptContext

# -- fixture chapter -----------------------------------------------------------

_FOUR_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 7, 3),
    ("p2.png", 13, 29),
    ("p3.png", 5, 11),
    ("p4.png", 23, 17),
)
_ONE_PAGE: tuple[tuple[str, int, int], ...] = (("p1.png", 9, 9),)

#: The real stage names (`test_stages.py` pins them; spelled out here for its
#: reason - a rename should show up as a change to the vocabulary).
_DETECT = "detect"
_CLEAN = "clean"
_OCR = "ocr"
_TRANSLATE = "translate"

#: Two distinct per-page estimates, neither `BOOTSTRAP_PAGE_ESTIMATE` ($0.06),
#: so a preview that ignored its argument and fell back to Claude's figure is a
#: different number, not the same one by coincidence.
_ESTIMATE = Usd.from_micro(30_000)
_OTHER_ESTIMATE = Usd.from_micro(45_000)


# -- doubles -------------------------------------------------------------------


class _Recorder:
    """A stage whose `is_done` answers from `done` and counts its calls.

    `run` raises, so AC-5's "no stage's `run` is called" is a crash rather than
    a count somebody has to remember to read.
    """

    def __init__(self, name: str, done: Iterable[int] = ()) -> None:
        self.name = name
        self.done = frozenset(done)
        self.is_done_calls: list[int] = []
        self.contexts: list[PageContext] = []

    def run(self, ctx: PageContext) -> None:
        raise AssertionError(
            f"stage {self.name!r} was run on page {ctx.page.ordinal}; a preview runs nothing"
        )

    def is_done(self, ctx: PageContext) -> bool:
        self.is_done_calls.append(ctx.page.ordinal)
        self.contexts.append(ctx)
        return ctx.page.ordinal in self.done


def _refuse_detect(image_bytes: bytes) -> Sequence[RawRegion]:
    raise AssertionError("the detector was called; a preview runs nothing")


def _refuse_clean(image_bytes: bytes, regions: Sequence[RawRegion]) -> bytes:
    raise AssertionError("the cleaner was called; a preview runs nothing")


def _refuse_transcribe(image_bytes: bytes, regions: Sequence[RawRegion]) -> Sequence[OcrResult]:
    raise AssertionError("the transcriber was called; a preview runs nothing")


def _refuse_translate(
    image_bytes: bytes, results: Sequence[OcrResult], context: PromptContext
) -> TranslationResult:
    raise AssertionError("the translator was called; a preview runs nothing")


# -- helpers -------------------------------------------------------------------


def _source(
    tmp_path: Path, png_bytes: Callable[..., bytes], pages: Sequence[tuple[str, int, int]]
) -> Path:
    source_dir = tmp_path / "scans"
    source_dir.mkdir()
    for filename, width, height in pages:
        (source_dir / filename).write_bytes(png_bytes(width, height))
    return source_dir


@pytest.fixture
def four_pages(tmp_path: Path, png_bytes: Callable[..., bytes]) -> Iterator[Project]:
    source_dir = _source(tmp_path, png_bytes, _FOUR_PAGES)
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        yield project


def _open_run(project: Project) -> int:
    with project.transaction() as cursor:
        chapter_id = int(cursor.execute("SELECT id FROM chapter").fetchone()[0])
        cursor.execute(
            "INSERT INTO run (chapter_id, started_at) VALUES (?, ?)",
            (chapter_id, "2026-10-30T09:00:00+00:00"),
        )
        return int(cursor.execute("SELECT last_insert_rowid()").fetchone()[0])


def _price(project: Project, *micros: int) -> None:
    """Record one priced call per amount against a fresh run, on page 0.

    A `CostRecord` built directly with the cost wanted, so the figure in the
    assertion is the figure in the ledger with no rate table in between.
    """
    run_id = _open_run(project)
    for index, micro in enumerate(micros):
        record = CostRecord(
            model_id="claude-opus-5",
            input_tokens=1,
            output_tokens=1,
            cache_write_tokens=0,
            cache_read_tokens=0,
            cost=Usd.from_micro(micro),
            rate_table_version="test",
        )
        record_call(project, run_id, 0, f"req-{run_id}-{index}", record)


def _set_ceiling(project: Project, micro: int | None) -> None:
    """`test_budget_run.py`'s convention: raw SQL, the store has no writer."""
    with project.transaction() as cursor:
        cursor.execute("UPDATE chapter SET budget_ceiling_micro_usd = ?", (micro,))


def _mark_done(project: Project, ordinal: int) -> None:
    with project.transaction() as cursor:
        cursor.execute("UPDATE page SET status = ? WHERE ordinal = ?", (PAGE_DONE, ordinal))


def _dump(db_path: Path) -> str:
    connection = sqlite3.connect(db_path)
    try:
        return "\n".join(connection.iterdump())
    finally:
        connection.close()


def _translate_half_done() -> list[Stage]:
    """A one-stage list named `translate`, done on pages 0 and 1 of four: two
    pages to translate."""
    return [_Recorder(_TRANSLATE, done={0, 1})]


# -- AC-1: counts, per stage, in stage order ----------------------------------


def test_the_preview_counts_the_pages_a_run_would_start_and_each_stage_it_would_redo(
    four_pages: Project,
) -> None:
    """**AC-1.** Pages 0 and 1 done by both, page 2 by `a` only, page 3 by
    neither: two pages started, `a` redoes one, `b` redoes two."""
    stages = [_Recorder("a", done={0, 1, 2}), _Recorder("b", done={0, 1})]

    preview = rerun_preview(four_pages, stages, _ESTIMATE)

    assert preview.page_count == 4
    assert preview.pages_to_run == 2, (
        f"pages_to_run is {preview.pages_to_run}; pages 2 and 3 each have a stage"
        " not done, so a run would start exactly those two (the PageStarted count)"
    )
    assert preview.pending == {"a": 1, "b": 2}
    assert list(preview.pending) == ["a", "b"]


def test_the_pending_keys_follow_the_stage_list_not_the_alphabet(four_pages: Project) -> None:
    """**AC-1**'s "keys in stage order", discriminated: `a, b` is also sorted
    order, so a preview that sorted its keys passes the literal above."""
    stages = [_Recorder("b", done={0, 1}), _Recorder("a", done={0, 1, 2})]

    preview = rerun_preview(four_pages, stages, _ESTIMATE)

    assert list(preview.pending.items()) == [("b", 2), ("a", 1)], (
        f"pending is {list(preview.pending.items())}; its keys must be in the order"
        " the stages run, which here is b then a"
    )


def test_a_chapter_every_stage_has_finished_previews_as_nothing_to_do(
    four_pages: Project,
) -> None:
    """**AC-1 control**: every stage done on every page."""
    stages = [_Recorder("a", done=range(4)), _Recorder("b", done=range(4))]

    preview = rerun_preview(four_pages, stages, _ESTIMATE)

    assert preview.page_count == 4
    assert preview.pages_to_run == 0
    assert preview.pending == {"a": 0, "b": 0}


def test_a_chapter_nothing_has_touched_previews_as_every_page_through_every_stage(
    four_pages: Project,
) -> None:
    """**AC-1 control**: nothing done anywhere gives 4 everywhere."""
    stages = [_Recorder("a"), _Recorder("b")]

    preview = rerun_preview(four_pages, stages, _ESTIMATE)

    assert preview.page_count == 4
    assert preview.pages_to_run == 4
    assert preview.pending == {"a": 4, "b": 4}


def test_an_empty_stage_list_previews_as_nothing_to_redo(four_pages: Project) -> None:
    """**AC-1 control**: the runner's `stages and all(...)` rule starts every
    page of a zero-stage run but redoes nothing on any of them; the preview
    says 0, stated rather than stumbled into."""
    preview = rerun_preview(four_pages, [], _ESTIMATE)

    assert preview.page_count == 4
    assert preview.pages_to_run == 0
    assert preview.pending == {}
    assert preview.pages_to_translate == 0
    assert preview.estimate == Usd.from_micro(0)


# -- AC-2: the pages the translate stage would run -----------------------------


def test_the_pages_to_translate_are_the_translate_stages_own_pending_count(
    four_pages: Project,
) -> None:
    """**AC-2**: `pages_to_translate == pending["translate"]`, with another
    stage in the list whose count differs so the two cannot be confused."""
    stages = [_Recorder("a", done={0}), _Recorder(_TRANSLATE, done={0, 1})]

    preview = rerun_preview(four_pages, stages, _ESTIMATE)

    assert preview.pending == {"a": 3, _TRANSLATE: 2}
    assert preview.pages_to_translate == 2
    assert preview.pages_to_translate == preview.pending[_TRANSLATE]


def test_a_no_translate_stage_list_translates_nothing_and_costs_nothing(
    four_pages: Project,
) -> None:
    """**AC-2**, the `--no-translate` list from the real builder
    (`build_stages(..., None, None)`): no `translate` key, 0 pages to
    translate, and an estimate of exactly zero - even with a priced history
    that would project a non-zero figure for any page."""
    _price(four_pages, 10_000, 20_000)
    stages = build_stages(_refuse_detect, _refuse_clean, _refuse_transcribe, None, None)

    preview = rerun_preview(four_pages, stages, _ESTIMATE)

    assert list(preview.pending) == [_DETECT, _CLEAN, _OCR]
    assert preview.pages_to_translate == 0
    assert preview.estimate == Usd.from_micro(0)


# -- AC-3: the guard's own figure, read out -----------------------------------


def test_the_estimate_and_ceiling_are_the_guards_own_with_no_stored_ceiling(
    four_pages: Project,
) -> None:
    """**AC-3**, no priced calls and no stored ceiling: the estimate is the
    page estimate times the pages to translate, the ceiling is
    `DEFAULT_CEILING`, the spend is zero."""
    preview = rerun_preview(four_pages, _translate_half_done(), _ESTIMATE)

    budget = budget_for(four_pages, _ESTIMATE)
    assert preview.estimate == budget.project(chapter_call_costs(four_pages), 2).remaining_chapter
    assert preview.estimate == Usd.from_micro(60_000)
    assert preview.spent == chapter_total(four_pages) == Usd.from_micro(0)
    assert preview.ceiling == budget.ceiling
    assert preview.ceiling == DEFAULT_CEILING


def test_a_stored_ceiling_is_the_ceiling_the_preview_reports(four_pages: Project) -> None:
    """**AC-3**: with a ceiling stored, that one and not `DEFAULT_CEILING`."""
    _set_ceiling(four_pages, 1_234_567)

    preview = rerun_preview(four_pages, _translate_half_done(), _ESTIMATE)

    assert preview.ceiling == Usd.from_micro(1_234_567)
    assert preview.ceiling == budget_for(four_pages, _ESTIMATE).ceiling
    assert preview.ceiling != DEFAULT_CEILING


def test_a_stored_zero_ceiling_is_reported_as_zero_not_as_the_default(
    four_pages: Project,
) -> None:
    """**AC-3** edge: $0.00 stored is "refuse everything" (MT-013 AC-7), and a
    preview that treated it as falsy would report $2.00."""
    _set_ceiling(four_pages, 0)

    preview = rerun_preview(four_pages, _translate_half_done(), _ESTIMATE)

    assert preview.ceiling == Usd.from_micro(0)
    assert preview.within_budget is False


def test_the_spend_is_the_whole_chapters_across_every_run(four_pages: Project) -> None:
    """**AC-3**: `spent == chapter_total(project)`, over two runs' rows."""
    _price(four_pages, 7_000)
    _price(four_pages, 11_000)

    preview = rerun_preview(four_pages, _translate_half_done(), _ESTIMATE)

    assert preview.spent == chapter_total(four_pages)
    assert preview.spent == Usd.from_micro(18_000)


def test_with_too_few_priced_calls_the_estimate_follows_the_selected_models_page_estimate(
    four_pages: Project,
) -> None:
    """**AC-3 control**: one priced call is fewer than
    `MIN_SAMPLES_FOR_PROJECTION`, so the projection is the page estimate's and
    changing `page_estimate` must move it."""
    _price(four_pages, *([10_000] * (MIN_SAMPLES_FOR_PROJECTION - 1)))

    first = rerun_preview(four_pages, _translate_half_done(), _ESTIMATE)
    second = rerun_preview(four_pages, _translate_half_done(), _OTHER_ESTIMATE)

    costs = chapter_call_costs(four_pages)
    assert first.estimate == budget_for(four_pages, _ESTIMATE).project(costs, 2).remaining_chapter
    assert second.estimate == (
        budget_for(four_pages, _OTHER_ESTIMATE).project(costs, 2).remaining_chapter
    )
    assert first.estimate == Usd.from_micro(60_000)
    assert second.estimate == Usd.from_micro(90_000)
    assert first.estimate != second.estimate, (
        "the estimate did not move when page_estimate changed, with fewer than"
        " MIN_SAMPLES_FOR_PROJECTION priced calls - the selected model's figure is"
        " being ignored (MT-100)"
    )


def test_with_enough_priced_calls_the_samples_win_over_the_page_estimate(
    four_pages: Project,
) -> None:
    """**AC-3 control**: `MIN_SAMPLES_FOR_PROJECTION` priced calls or more,
    and the projection is the observed mean (rounded up) - `page_estimate`
    no longer moves it. Mean of 10,000 and 20,001 rounds up to 15,001; two
    pages is 30,002."""
    _price(four_pages, 10_000, 20_001)
    assert len(chapter_call_costs(four_pages)) >= MIN_SAMPLES_FOR_PROJECTION

    first = rerun_preview(four_pages, _translate_half_done(), _ESTIMATE)
    second = rerun_preview(four_pages, _translate_half_done(), _OTHER_ESTIMATE)

    costs = chapter_call_costs(four_pages)
    assert first.estimate == budget_for(four_pages, _ESTIMATE).project(costs, 2).remaining_chapter
    assert first.estimate == Usd.from_micro(30_002)
    assert second.estimate == first.estimate, (
        f"the estimate moved from {first.estimate} to {second.estimate} with"
        f" {len(costs)} priced calls; Budget.project's rule is that the samples win"
    )


# -- AC-4: within budget, inclusive --------------------------------------------


def test_an_estimate_that_lands_exactly_on_the_ceiling_is_within_budget(
    four_pages: Project,
) -> None:
    """**AC-4**: spent 10,000 + estimate 2 x 30,000 = 70,000, ceiling 70,000."""
    _price(four_pages, 10_000)
    _set_ceiling(four_pages, 70_000)

    preview = rerun_preview(four_pages, _translate_half_done(), _ESTIMATE)

    assert preview.spent == Usd.from_micro(10_000)
    assert preview.estimate == Usd.from_micro(60_000)
    assert preview.ceiling == Usd.from_micro(70_000)
    assert preview.within_budget is True, (
        "spent + estimate lands exactly on the ceiling and the preview says it is"
        " over; the comparison is inclusive, as Budget.check's is"
    )


def test_one_micro_dollar_over_the_ceiling_is_not_within_budget(four_pages: Project) -> None:
    """**AC-4 control**: the same chapter with a ceiling of 69,999."""
    _price(four_pages, 10_000)
    _set_ceiling(four_pages, 69_999)

    preview = rerun_preview(four_pages, _translate_half_done(), _ESTIMATE)

    assert preview.within_budget is False


def test_spend_alone_is_counted_against_the_ceiling(four_pages: Project) -> None:
    """**AC-4**: `spent` is half of the sum. A preview that compared only the
    estimate with the ceiling would call 40,000 + 60,000 against 70,000 within."""
    _price(four_pages, 40_000)
    _set_ceiling(four_pages, 70_000)

    preview = rerun_preview(four_pages, _translate_half_done(), _ESTIMATE)

    assert preview.estimate == Usd.from_micro(60_000)
    assert preview.within_budget is False


# -- AC-5: writes nothing, runs nothing, consults once -------------------------


def test_the_preview_leaves_the_project_file_byte_identical(
    tmp_path: Path, png_bytes: Callable[..., bytes]
) -> None:
    """**AC-5**: the `sqlite3` dump before and after, taken with the project
    closed, by a connection that imports nothing from `mangatl.store`. Under
    the real stage list, with a priced history and a ceiling, so the money
    half is exercised too."""
    source_dir = _source(tmp_path, png_bytes, _FOUR_PAGES)
    project_dir = project_dir_for(source_dir)
    db_path = project_dir / "project.db"
    with create_project(read_chapter(source_dir), project_dir) as project:
        _price(project, 10_000, 20_000)
        _set_ceiling(project, 500_000)
    before = _dump(db_path)

    with open_project(project_dir) as project:
        stages = build_stages(
            _refuse_detect, _refuse_clean, _refuse_transcribe, _refuse_translate, _ESTIMATE
        )
        preview = rerun_preview(project, stages, _ESTIMATE)

    assert preview.pages_to_run == 4
    assert _dump(db_path) == before, "the preview wrote to the project file"


def test_the_preview_consults_each_stage_at_most_once_per_page_and_runs_none(
    four_pages: Project,
) -> None:
    """**AC-5**: every `is_done` at most once per page (a 200-page chapter
    previews in one pass, not the runner's `all(...)` and then again per
    stage), and no `run` - `_Recorder.run` raises."""
    stages = [_Recorder("a", done={0, 1, 2}), _Recorder("b", done={0, 1}), _Recorder("c")]

    rerun_preview(four_pages, stages, _ESTIMATE)

    for stage in stages:
        repeated = sorted(
            {ordinal for ordinal in stage.is_done_calls if stage.is_done_calls.count(ordinal) > 1}
        )
        assert repeated == [], (
            f"stage {stage.name!r} had is_done called more than once on pages {repeated}"
            f" (calls: {stage.is_done_calls})"
        )


def test_each_stage_is_asked_about_the_right_page_of_the_right_project_with_no_run(
    four_pages: Project,
) -> None:
    """**C-2** (AC-5's "runs nothing"): the context a stage is handed carries
    this project, the page asked about, `run_id == 0` - no run exists - and an
    `emit` that refuses, so a stage that emitted from `is_done` fails loudly."""
    stage = _Recorder("a")

    rerun_preview(four_pages, [stage], _ESTIMATE)

    pages = four_pages.pages()
    assert sorted(stage.is_done_calls) == [page.ordinal for page in pages]
    for ctx in stage.contexts:
        assert ctx.project is four_pages
        assert ctx.page == pages[ctx.page.ordinal]
        assert ctx.run_id == 0, f"a preview handed a stage run_id {ctx.run_id}; no run exists"
        with pytest.raises(RuntimeError):
            ctx.emit(None)  # type: ignore[arg-type]


# -- AC-6: the real stage list, each stage's own rule --------------------------


def _one_page_with_words(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
) -> tuple[Path, Project]:
    source_dir = _source(tmp_path, png_bytes, _ONE_PAGE)
    project = create_project(read_chapter(source_dir), project_dir_for(source_dir))
    mask = one_bit_png(8, 8, [(0, 0, 4, 4)])
    ring = ((0, 0), (4, 0), (4, 4), (0, 4), (0, 0))
    project.write_regions(0, (RawRegion(polygon=ring, mask=mask, confidence=1.0, kind="bubble"),))
    project.write_lines(0, (OcrResult(text="ja-0"),))
    return source_dir, project


def _real_stages() -> tuple[Stage, ...]:
    return build_stages(
        _refuse_detect, _refuse_clean, _refuse_transcribe, _refuse_translate, _ESTIMATE
    )


def test_a_page_whose_cleaned_image_is_missing_reruns_only_clean_though_the_store_calls_it_done(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
) -> None:
    """**AC-6**: regions, lines and a proposal stored, no cleaned image (the
    state MT-119 AC-5c leaves), and the page `done` in the store. Each stage's
    own `is_done` says only `clean` is pending; a preview that read
    `page_status` would say nothing is (DV-1)."""
    _source_dir, project = _one_page_with_words(tmp_path, png_bytes, one_bit_png)
    with project:
        project.write_proposed(0, {0: "EN-0"})
        _mark_done(project, 0)
        assert project.page_status(0) == PAGE_DONE

        preview = rerun_preview(project, _real_stages(), _ESTIMATE)

    assert preview.pending == {_DETECT: 0, _CLEAN: 1, _OCR: 0, _TRANSLATE: 0}
    assert list(preview.pending) == [_DETECT, _CLEAN, _OCR, _TRANSLATE]
    assert preview.page_count == 1
    assert preview.pages_to_run == 1, (
        "the page is done in the store but has no cleaned image; a run would start"
        " it to clean it, and the preview must say so from each stage's is_done"
    )
    assert preview.pages_to_translate == 0
    assert preview.estimate == Usd.from_micro(0)


def test_a_cleaned_page_with_no_proposal_is_priced_for_one_translation(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
) -> None:
    """**AC-6 control**: the same page with its cleaned image stored (MT-119's
    `erased=` keyword: the one region was erased) and no proposal - `clean`
    is done, `translate` is not, and translating one page costs the guard's
    projection for one page, which is not zero."""
    source_dir, project = _one_page_with_words(tmp_path, png_bytes, one_bit_png)
    with project:
        project.write_cleaned(0, (source_dir / "p1.png").read_bytes(), erased=(0,))
        _mark_done(project, 0)

        preview = rerun_preview(project, _real_stages(), _ESTIMATE)
        expected = (
            budget_for(project, _ESTIMATE).project(chapter_call_costs(project), 1).remaining_chapter
        )

    assert preview.pending == {_DETECT: 0, _CLEAN: 0, _OCR: 0, _TRANSLATE: 1}
    assert preview.pages_to_run == 1
    assert preview.pages_to_translate == 1
    assert preview.estimate == expected
    assert preview.estimate == _ESTIMATE
    assert preview.estimate != Usd.from_micro(0)


# -- C-1: the export shape -----------------------------------------------------


def test_the_module_exports_the_preview_and_its_function_and_nothing_else() -> None:
    import mangatl.pipeline.resume as module

    assert module.__all__ == ["RerunPreview", "rerun_preview"]


def test_the_preview_is_a_frozen_record_of_the_eight_figures_in_contract_order() -> None:
    """**C-1**: a frozen dataclass, so MT-125's dialog cannot rewrite the
    figures it was shown."""
    assert dataclasses.is_dataclass(RerunPreview)
    assert RerunPreview.__dataclass_params__.frozen  # type: ignore[attr-defined]
    assert [field.name for field in dataclasses.fields(RerunPreview)] == [
        "page_count",
        "pages_to_run",
        "pending",
        "pages_to_translate",
        "spent",
        "ceiling",
        "estimate",
        "within_budget",
    ]
