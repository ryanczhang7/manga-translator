"""`mangatl.pipeline.continuity` and `TranslateStage` with continuity wired in.

MT-014 C-8 and C-9. Covers **AC-1** end to end (page 0's proposal is in page
1's request), the stage halves of **AC-4** (page N carries page N-1's proposed
English) and **AC-5** (page 1 carries nothing and does not fail), and the order
C-9 fixes: `record_call` -> glossary -> `write_proposed`.

**MT-106 amended this file in RED** ("pages stop proposing glossary terms"):
the stage marks the glossary's terms seen and merges nothing a page proposes
(AC-3). Every stage test that relied on a page's proposal reaching the glossary
now seeds the glossary with `upsert`, as the pre-pass would have left it, and
asserts the proposal is ignored; MT-014 AC-1's end-to-end test asserts the
*chapter's* glossary reaches page 2. AC-3 itself runs on a four-page chapter
(`chapter_of_four`), so its page is ordinal 3.

**Why `pipeline` and not `translate`** (C-8, PO-5): the caller is
`TranslateStage`, which may not import `mangatl.translate` at all under the
*"Only translate imports anthropic"* contract. `pipeline` may import `store`
and `domain`, which is all this needs - asserted below off the module's AST,
as `test_translate_stage.py` does for the stage.

**The translator is a scripted double**, as everywhere in MT-011's and
MT-044's suites: no network, no client. It returns the results it was given,
in call order, and records the `PromptContext` each call was handed - that
record *is* the request's context, because `translate_page` passes it to
`build_request` unchanged (C-5, asserted in `test_translate_client.py`).
`test_the_proposal_from_page_one_is_in_page_twos_request` joins the two by
calling the real `build_request` on the recorded context.

**Timing.** No `pytest-timeout` in this project and no per-test timeout, so
there is no budget in this file to size. Each test builds a three-page chapter
of tiny PNGs on `tmp_path`.
"""

from __future__ import annotations

import ast
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest

from mangatl.domain.budget import BOOTSTRAP_PAGE_ESTIMATE
from mangatl.domain.glossary import (
    EMPTY_CONTEXT,
    MAX_GLOSSARY_TOKENS,
    MAX_ROLLING_TOKENS,
    GlossaryEntry,
    PromptContext,
    ProposedTerm,
    estimate_tokens,
)
from mangatl.domain.line import OcrResult
from mangatl.domain.rates import UnknownModel
from mangatl.domain.region import RawRegion
from mangatl.domain.translation import CallInfo, TokenUsage, TranslationResult
from mangatl.pipeline.continuity import build_prompt_context
from mangatl.pipeline.stage import PageContext
from mangatl.pipeline.translate_stage import TranslateStage
from mangatl.store.glossary import read_entries, upsert
from mangatl.store.intake import read_chapter
from mangatl.store.project import Project, create_project, project_dir_for
from mangatl.translate.prompt import build_request

_SOURCE_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 30, 20),
    ("p2.png", 40, 30),
    ("p3.png", 50, 40),
)

#: What OCR left on each page, two regions apiece. さくら is on pages 0, 1 and
#: 2; 東京 only on page 2.
_OCR: tuple[tuple[str, str], ...] = (
    ("さくら、待って!", "どこへ行くの?"),
    ("さくらはどこ?", "家へ。"),
    ("東京タワーだ", "さくら!"),
)

_ROLLING_HEADER = "Previous page, in reading order:"
_GLOSSARY_HEADER = "Glossary - use these renderings exactly:"

_USAGE = TokenUsage(input_tokens=3011, output_tokens=712, cache_read_tokens=0, cache_write_tokens=0)


def _ring(x0: int, y0: int, x1: int, y1: int) -> tuple[tuple[int, int], ...]:
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))


@dataclass(frozen=True)
class _Chapter:
    source_dir: Path
    project: Project
    run_id: int

    @property
    def db_path(self) -> Path:
        return project_dir_for(self.source_dir) / "project.db"

    def context(self, ordinal: int) -> PageContext:
        page = next(page for page in self.project.pages() if page.ordinal == ordinal)
        return PageContext(
            project=self.project, page=page, run_id=self.run_id, emit=lambda _event: None
        )

    def page_bytes(self, ordinal: int) -> bytes:
        page = next(page for page in self.project.pages() if page.ordinal == ordinal)
        return (self.source_dir / page.filename).read_bytes()

    def ledger_rows(self) -> int:
        connection = sqlite3.connect(self.db_path)
        try:
            return int(connection.execute("SELECT count(*) FROM llm_call").fetchone()[0])
        finally:
            connection.close()


@pytest.fixture
def chapter(
    tmp_path: Path, png_bytes: Callable[..., bytes], one_bit_png: Callable[..., bytes]
) -> Iterator[_Chapter]:
    with _open_chapter(tmp_path, png_bytes, one_bit_png, _SOURCE_PAGES, _OCR) as opened:
        yield opened


#: MT-106 AC-3's chapter: the target page is **ordinal 3**, so a `mark_seen`
#: or `merge` handed the wrong ordinal (0, or the loop index of a three-page
#: fixture) cannot pass by coincidence. さくら and ケンジ are on page 3; 東京 is
#: only on page 1.
_SOURCE_PAGES_OF_FOUR: tuple[tuple[str, int, int], ...] = (
    *_SOURCE_PAGES,
    ("p4.png", 60, 50),
)
_OCR_OF_FOUR: tuple[tuple[str, str], ...] = (
    ("さくら、待って!", "どこへ行くの?"),
    ("東京タワーだ", "家へ。"),
    ("行くぞ", "走れ!"),
    ("さくら!", "ケンジはどこ?"),
)


@pytest.fixture
def chapter_of_four(
    tmp_path: Path, png_bytes: Callable[..., bytes], one_bit_png: Callable[..., bytes]
) -> Iterator[_Chapter]:
    with _open_chapter(
        tmp_path, png_bytes, one_bit_png, _SOURCE_PAGES_OF_FOUR, _OCR_OF_FOUR
    ) as opened:
        yield opened


@contextmanager
def _open_chapter(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
    source_pages: Sequence[tuple[str, int, int]],
    ocr: Sequence[tuple[str, str]],
) -> Iterator[_Chapter]:
    """A chapter whose every page has two regions and the given OCR text, and
    one `run` row. Factored out of `chapter` by MT-106 so AC-3 can use four
    pages; the three-page chapter is built exactly as before."""
    source_dir = tmp_path / "scans"
    source_dir.mkdir()
    for index, (filename, width, height) in enumerate(source_pages):
        (source_dir / filename).write_bytes(png_bytes(width, height, (index * 40, 0, 0)))
    mask = one_bit_png(30, 20, [(0, 0, 4, 4)])

    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        for ordinal, texts in enumerate(ocr):
            project.write_regions(
                ordinal,
                tuple(
                    RawRegion(
                        polygon=_ring(2, 2 + 8 * i, 12, 8 + 8 * i),
                        mask=mask,
                        confidence=0.5,
                        kind="bubble",
                    )
                    for i in range(len(texts))
                ),
            )
            project.write_lines(ordinal, [OcrResult(text=text) for text in texts])
        with project.transaction() as cursor:
            chapter_id = int(cursor.execute("SELECT id FROM chapter").fetchone()[0])
            cursor.execute(
                "INSERT INTO run (chapter_id, started_at) VALUES (?, ?)",
                (chapter_id, "2026-09-28T09:00:00+00:00"),
            )
            run_id = int(cursor.execute("SELECT last_insert_rowid()").fetchone()[0])
        yield _Chapter(source_dir=source_dir, project=project, run_id=run_id)


def _result(
    lines: dict[int, str],
    terms: Sequence[ProposedTerm] = (),
    *,
    model_id: str = "claude-opus-5",
    call: bool = True,
) -> TranslationResult:
    return TranslationResult(
        lines=lines,
        usage=_USAGE if call else TokenUsage(0, 0, 0, 0),
        call=CallInfo(request_id="msg_continuity", model_id=model_id) if call else None,
        proposed_terms=tuple(terms),
    )


class _Scripted:
    """A `PageTranslator` that returns its scripted results in call order and
    records the context each call was handed."""

    def __init__(self, *results: TranslationResult) -> None:
        self._results = list(results)
        self.contexts: list[PromptContext] = []
        self.seen: list[tuple[bytes, tuple[OcrResult, ...]]] = []

    def __call__(
        self, image: bytes, results: Sequence[OcrResult], context: PromptContext
    ) -> TranslationResult:
        self.contexts.append(context)
        self.seen.append((image, tuple(results)))
        return self._results[len(self.contexts) - 1]


# -- C-8: build_prompt_context ----------------------------------------------------


def test_the_module_imports_nothing_the_two_contracts_forbid() -> None:
    """C-8's reason for being in `pipeline`, as a `unit` tripwire beside the
    `lint` one: no `anthropic`, nothing under `mangatl.translate`, no stage."""
    import mangatl.pipeline.continuity as module

    source = Path(module.__file__ or "").read_text(encoding="utf-8")
    imported: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.append(node.module)

    for name in imported:
        assert not name.startswith("anthropic"), f"{name}: pipeline may not import anthropic"
        assert not name.startswith("mangatl.translate"), (
            f"{name}: pipeline may not reach anthropic through mangatl.translate"
        )


def test_page_one_gets_the_empty_context_even_with_a_glossary_on_disk(
    chapter: _Chapter,
) -> None:
    """**AC-5**, and C-8's first bullet: ordinal 0 is `EMPTY_CONTEXT` - no
    glossary, no rolling context - whatever the store holds. A chapter being
    re-run from the top has a glossary already, and page 1 still gets MT-011's
    three-block request."""
    upsert(chapter.project, GlossaryEntry("さくら", "Sakura", "name", 0, 2, "model"))

    assert build_prompt_context(chapter.project, 0) == EMPTY_CONTEXT


def test_page_two_gets_the_glossary_and_page_ones_proposed_english(chapter: _Chapter) -> None:
    """C-8's second bullet, exactly: the rendered glossary and the previous
    page's proposed lines, **NULLs removed**, in reading order."""
    upsert(chapter.project, GlossaryEntry("さくら", "Sakura", "name", 0, 0, "model"))
    chapter.project.write_proposed(0, {1: "Where are you going?"})

    assert build_prompt_context(chapter.project, 1) == PromptContext(
        glossary_block=f"{_GLOSSARY_HEADER}\nさくら = Sakura (name)",
        rolling_block=f"{_ROLLING_HEADER}\nWhere are you going?",
    )


def test_page_three_reads_page_two_and_not_page_one(chapter: _Chapter) -> None:
    """C-8's `ordinal - 1`, on a page that is not 1: `read_proposed(0)` in
    place of `read_proposed(ordinal - 1)` is one token (MT-035 DV-3)."""
    chapter.project.write_proposed(0, {0: "Wait up, Sakura!", 1: "Where are you going?"})
    chapter.project.write_proposed(1, {0: "Where is Sakura?", 1: "Home."})

    context = build_prompt_context(chapter.project, 2)

    assert context.rolling_block == f"{_ROLLING_HEADER}\nWhere is Sakura?\nHome."


def test_the_rolling_context_is_the_proposed_english_and_not_the_users_edit(
    chapter: _Chapter,
) -> None:
    """C-8: "AC-4 reads **`proposed_en`**, as the criterion says, not
    `final_en`." The user's edit reaches the next page through the glossary
    (AC-2), not through the rolling block."""
    chapter.project.write_proposed(0, {0: "Wait up, Sakura!", 1: "Where are you going?"})
    with chapter.project.transaction() as cursor:
        cursor.execute("UPDATE line SET final_en = 'EDITED BY THE USER'")

    context = build_prompt_context(chapter.project, 1)

    assert context.rolling_block == (f"{_ROLLING_HEADER}\nWait up, Sakura!\nWhere are you going?")


def test_a_second_page_with_nothing_before_it_gets_an_empty_context(
    chapter: _Chapter,
) -> None:
    """No glossary and an untranslated previous page: both blocks `""`, which
    is the empty context by value - so `build_request` sends MT-011's shape
    (C-3 compares by `==`)."""
    assert build_prompt_context(chapter.project, 1) == EMPTY_CONTEXT


def test_each_block_is_held_to_its_own_cap_and_not_the_others(chapter: _Chapter) -> None:
    """C-8 passes `MAX_GLOSSARY_TOKENS` to the glossary and `MAX_ROLLING_TOKENS`
    to the rolling block. Both sides are sized **between** 400 and 500 tokens,
    so the two caps swapped is caught from both directions: the glossary would
    come back whole at 500 and over its 400, and the rolling block would lose
    lines at 400 that fit its 500."""
    for index in range(40):
        upsert(
            chapter.project,
            GlossaryEntry(
                f"名前{index:02d}", f"Name Number {index:02d}", "name", index, index, "model"
            ),
        )
    rolling = [f"Line {index:02d}: the rolling context is long." for index in range(2)]
    long_line = "A very long bubble of dialogue that goes on and on. " * 24
    chapter.project.write_proposed(0, {0: rolling[0], 1: long_line + rolling[1]})
    whole_glossary = estimate_tokens(
        "\n".join(
            [_GLOSSARY_HEADER]
            + [f"名前{index:02d} = Name Number {index:02d} (name)" for index in range(40)]
        )
    )
    whole_rolling = estimate_tokens(
        "\n".join([_ROLLING_HEADER, rolling[0], long_line + rolling[1]])
    )
    assert MAX_GLOSSARY_TOKENS < whole_glossary <= MAX_ROLLING_TOKENS, whole_glossary
    assert MAX_GLOSSARY_TOKENS < whole_rolling <= MAX_ROLLING_TOKENS, whole_rolling

    context = build_prompt_context(chapter.project, 1)

    assert estimate_tokens(context.glossary_block) <= MAX_GLOSSARY_TOKENS
    assert context.glossary_block.startswith(_GLOSSARY_HEADER)
    assert estimate_tokens(context.rolling_block) == whole_rolling, (
        "the rolling block was cut below MAX_ROLLING_TOKENS"
    )


# -- C-9: the stage, and AC-1 end to end --------------------------------------------


def test_the_chapters_glossary_is_in_page_twos_request_and_page_ones_proposal_is_not(
    chapter: _Chapter,
) -> None:
    """**MT-014 AC-1**, as MT-106 leaves it: the glossary reaches the next
    page's request, but it is the chapter's glossary - seeded here as the
    pre-pass would have written it - and not what page 0's model proposed.
    Page 0 proposes a re-rendering of さくら and a new term, 家; page 1's
    `glossary_block` and the context text block `build_request` assembles from
    it carry `さくら = Sakura (name)` and neither proposal."""
    upsert(chapter.project, GlossaryEntry("さくら", "Sakura", "name", 0, 0, "model"))
    translator = _Scripted(
        _result(
            {0: "Wait, Sakura-chan!"},
            [ProposedTerm("さくら", "Sakura-chan", "name"), ProposedTerm("家", "Home", "place")],
        ),
        _result({0: "Where's Sakura?"}),
    )
    stage = TranslateStage(page_estimate=BOOTSTRAP_PAGE_ESTIMATE, translate=translator)

    stage.run(chapter.context(0))
    stage.run(chapter.context(1))

    page_two = translator.contexts[1]
    assert page_two.glossary_block.split("\n") == [_GLOSSARY_HEADER, "さくら = Sakura (name)"], (
        "page 1 was told something other than the chapter's one glossary term -"
        " page 0's proposals reached the glossary"
    )
    request, _ = build_request(chapter.page_bytes(1), chapter.project.read_lines(1), page_two)
    context_block = request["messages"][0]["content"][1]
    assert context_block["type"] == "text"
    assert "さくら = Sakura (name)" in context_block["text"]
    assert "Home" not in context_block["text"]


def test_page_one_is_translated_with_the_empty_context(chapter: _Chapter) -> None:
    """**AC-5** at the stage: the first page's translator call is handed
    `EMPTY_CONTEXT`, and the page completes."""
    translator = _Scripted(_result({0: "Wait, Sakura!"}))

    TranslateStage(page_estimate=BOOTSTRAP_PAGE_ESTIMATE, translate=translator).run(
        chapter.context(0)
    )

    assert translator.contexts == [EMPTY_CONTEXT]
    assert chapter.project.read_proposed(0) == ("Wait, Sakura!", None)


def test_page_n_is_handed_page_n_minus_ones_proposed_lines(chapter: _Chapter) -> None:
    """**AC-4** at the stage (the "not the image" half is the request's, in
    `test_translate_prompt.py`): page 2's call carries page 1's English, in
    reading order, and the image it is handed is its own page's."""
    translator = _Scripted(
        _result({0: "Wait, Sakura!", 1: "Where are you going?"}),
        _result({0: "Where's Sakura?", 1: "Home."}),
        _result({}),
    )
    stage = TranslateStage(page_estimate=BOOTSTRAP_PAGE_ESTIMATE, translate=translator)

    for ordinal in range(3):
        stage.run(chapter.context(ordinal))

    assert translator.contexts[2].rolling_block == f"{_ROLLING_HEADER}\nWhere's Sakura?\nHome."
    assert translator.seen[2][0] == chapter.page_bytes(2)


def test_a_translated_page_marks_the_glossary_seen_and_adds_and_re_renders_nothing(
    chapter_of_four: _Chapter,
) -> None:
    """**MT-106 AC-3.** A glossary of two terms - さくら, in page 3's OCR, and
    東京, not - and a translator whose result for page 3 proposes **a new
    term** (ケンジ, which is on the page too, so "added because sighted" is
    caught as well) **and a new rendering of an existing one** (さくら as
    "Sakura-chan"). Afterwards さくら is last seen on 3, 東京 keeps its page,
    nothing was added and no `term_en` changed: the whole `read_entries` list,
    not a count. (Supersedes MT-014 C-9's "a proposed term is stored".)"""
    seeded = [
        GlossaryEntry("さくら", "Sakura", "name", 0, 0, "model"),
        GlossaryEntry("東京", "Tokyo", "place", 1, 1, "user"),
    ]
    for entry in seeded:
        upsert(chapter_of_four.project, entry)
    translator = _Scripted(
        _result(
            {0: "Sakura-chan!", 1: "Where's Kenji?"},
            [
                ProposedTerm("ケンジ", "Kenji", "name"),
                ProposedTerm("さくら", "Sakura-chan", "name"),
            ],
        )
    )

    TranslateStage(page_estimate=BOOTSTRAP_PAGE_ESTIMATE, translate=translator).run(
        chapter_of_four.context(3)
    )

    assert read_entries(chapter_of_four.project) == [
        GlossaryEntry("さくら", "Sakura", "name", 0, 3, "model"),
        GlossaryEntry("東京", "Tokyo", "place", 1, 1, "user"),
    ], "the page's proposals reached the glossary, or its sighting was not marked on page 3"
    assert chapter_of_four.project.read_proposed(3) == ("Sakura-chan!", "Where's Kenji?")


def test_a_term_a_page_proposes_into_an_empty_glossary_is_not_stored(chapter: _Chapter) -> None:
    """MT-106 AC-3's zero: with no pre-pass glossary at all - a Claude run (PO-4)
    - a page's proposal leaves the glossary empty rather than starting one."""
    translator = _Scripted(
        _result({0: "Where's Sakura?"}, [ProposedTerm("さくら", "Sakura", "name")])
    )

    TranslateStage(page_estimate=BOOTSTRAP_PAGE_ESTIMATE, translate=translator).run(
        chapter.context(1)
    )

    assert read_entries(chapter.project) == [], "a page's proposed term was stored"


def test_a_name_on_the_page_is_seen_there_even_when_nobody_re_proposes_it(
    chapter: _Chapter,
) -> None:
    """C-9 step 4's `mark_seen` over the page's OCR: 東京 and さくら are both in
    page 2's source text, so both are last seen on page 2 though the model
    proposed nothing; けんじ is not, and keeps its page."""
    for entry in (
        GlossaryEntry("さくら", "Sakura", "name", 0, 0, "model"),
        GlossaryEntry("東京", "Tokyo", "place", 0, 1, "user"),
        GlossaryEntry("けんじ", "Kenji", "name", 0, 1, "model"),
    ):
        upsert(chapter.project, entry)

    TranslateStage(
        page_estimate=BOOTSTRAP_PAGE_ESTIMATE, translate=_Scripted(_result({0: "It's Tokyo Tower"}))
    ).run(chapter.context(2))

    assert read_entries(chapter.project) == [
        GlossaryEntry("さくら", "Sakura", "name", 0, 2, "model"),
        GlossaryEntry("東京", "Tokyo", "place", 0, 2, "user"),
        GlossaryEntry("けんじ", "Kenji", "name", 0, 1, "model"),
    ]


def test_a_later_page_cannot_re_render_a_name_the_chapter_already_has(
    chapter: _Chapter,
) -> None:
    """The story's reason for existing, at the stage: page 1's model proposes
    "Sakura-chan" for a name the chapter's glossary already has as "Sakura".
    The chapter keeps "Sakura", and page 2 is told so. MT-106: the glossary is
    seeded as the pre-pass would leave it (a page no longer starts one), and
    the re-rendering is ignored because pages write nothing to the glossary."""
    upsert(chapter.project, GlossaryEntry("さくら", "Sakura", "name", 0, 0, "model"))
    translator = _Scripted(
        _result({0: "Wait, Sakura!"}, [ProposedTerm("さくら", "Sakura", "name")]),
        _result({0: "Where's Sakura-chan?"}, [ProposedTerm("さくら", "Sakura-chan", "name")]),
        _result({}),
    )
    stage = TranslateStage(page_estimate=BOOTSTRAP_PAGE_ESTIMATE, translate=translator)

    for ordinal in range(3):
        stage.run(chapter.context(ordinal))

    assert read_entries(chapter.project) == [
        GlossaryEntry("さくら", "Sakura", "name", 0, 2, "model")
    ]
    assert "さくら = Sakura (name)" in translator.contexts[2].glossary_block.split("\n")


def test_the_glossary_is_written_before_the_proposals(chapter: _Chapter) -> None:
    """C-9's order, second half: glossary **before** `write_proposed`. The
    result names region 99, so `write_proposed` raises with nothing written
    (MT-011 C-6); the page's sightings must already be on disk, and so must its
    bill (MT-044 C-7). The other order marks the page done with its sightings
    never recorded. MT-106: the glossary step marks seen and merges nothing, so
    the evidence is a seeded entry whose `last_seen_page` page 1 moves - the
    re-rendering the result proposes is ignored either way."""
    upsert(chapter.project, GlossaryEntry("さくら", "Sakura", "name", 0, 0, "model"))
    translator = _Scripted(
        _result({99: "a region that is not there"}, [ProposedTerm("さくら", "Sakura-chan", "name")])
    )

    with pytest.raises(ValueError, match=r"\b99\b"):
        TranslateStage(page_estimate=BOOTSTRAP_PAGE_ESTIMATE, translate=translator).run(
            chapter.context(1)
        )

    assert read_entries(chapter.project) == [
        GlossaryEntry("さくら", "Sakura", "name", 0, 1, "model")
    ], "page 1's sighting of さくら was not on disk when write_proposed raised"
    assert chapter.ledger_rows() == 1
    assert chapter.project.read_proposed(0) == (None, None)


def test_a_call_that_cannot_be_priced_writes_no_glossary_either(chapter: _Chapter) -> None:
    """C-9's order, first half: `record_call(...)` is "unchanged, and still
    first", and `price(...)` sits inside its argument list (MT-044 C-7 clause
    3), so an unpriceable model raises before **any** write. A glossary step
    moved ahead of the ledger would leave this page's names behind. MT-106:
    with no merge, an empty glossary stays `[]` whatever the order, so the
    evidence is a seeded entry page 1 would mark seen - it must not move."""
    seeded = GlossaryEntry("さくら", "Sakura", "name", 0, 0, "model")
    upsert(chapter.project, seeded)
    translator = _Scripted(
        _result(
            {0: "Wait, Sakura!"},
            [ProposedTerm("さくら", "Sakura", "name")],
            model_id="claude-not-in-the-rate-table",
        )
    )

    with pytest.raises(UnknownModel):
        TranslateStage(page_estimate=BOOTSTRAP_PAGE_ESTIMATE, translate=translator).run(
            chapter.context(1)
        )

    assert read_entries(chapter.project) == [seeded], (
        "the glossary step ran before the unpriceable call was refused"
    )
    assert chapter.ledger_rows() == 0
    assert chapter.project.read_proposed(0) == (None, None)


def test_a_wordless_page_still_runs_the_glossary_step_and_changes_nothing(
    chapter: _Chapter,
) -> None:
    """C-9: "A wordless page (`call is None`) still runs step 4: `mark_seen`
    over an all-empty page changes nothing, and nothing is proposed." The page
    completes, writes no bill and no proposals, and the glossary is exactly as
    it was."""
    chapter.project.write_lines(
        1, [OcrResult(text="", ocr_empty=True), OcrResult(text="", ocr_empty=True)]
    )
    before = [GlossaryEntry("さくら", "Sakura", "name", 0, 0, "model")]
    upsert(chapter.project, before[0])

    TranslateStage(
        page_estimate=BOOTSTRAP_PAGE_ESTIMATE, translate=_Scripted(_result({}, call=False))
    ).run(chapter.context(1))

    assert read_entries(chapter.project) == before
    assert chapter.ledger_rows() == 0
    assert chapter.project.read_proposed(1) == (None, None)


def test_re_running_a_page_leaves_the_seeded_glossary_as_it_was(chapter: _Chapter) -> None:
    """`mark_seen` is idempotent (C-9's reason the order is safe, as MT-106
    words it): a page re-translated after a crash re-proposes its names - a
    re-rendering and a new term - and the glossary is exactly the seeded one,
    sighted on the page, both times."""
    upsert(chapter.project, GlossaryEntry("さくら", "Sakura", "name", 0, 0, "model"))
    terms = [ProposedTerm("さくら", "Sakura-chan", "name"), ProposedTerm("どこ", "where", "")]
    translator = _Scripted(_result({0: "Wait!"}, terms), _result({0: "Wait!"}, terms))
    stage = TranslateStage(page_estimate=BOOTSTRAP_PAGE_ESTIMATE, translate=translator)

    stage.run(chapter.context(1))
    stage.run(chapter.context(1))

    assert read_entries(chapter.project) == [
        GlossaryEntry("さくら", "Sakura", "name", 0, 1, "model")
    ], "re-running the page let its proposals into the glossary"


# -- MT-107: the `neighbours` mode, and `rolling` unchanged ---------------------------
#
# `mode=` and `context_mode=` are new in MT-107; until GREEN every test below is a
# `TypeError` on that keyword (or a wrong context), one test at a time, and every
# MT-014 test above keeps running. They are the AC-3 oracle and are not touched.
#
# The expected strings are spelled out from `_OCR` and the two settled headers,
# never rendered by the module under test.

_PREVIOUS_JA = "Previous page, Japanese:"
_NEXT_JA = "Next page, Japanese:"

#: English proposed for every page, so "no proposed English appears" (AC-2) has
#: something to leak. None of these strings occurs in `_OCR` or in the glossary.
_PROPOSED: tuple[dict[int, str], ...] = (
    {0: "Wait up, Sakura!", 1: "Where are you going?"},
    {0: "Where is Sakura?", 1: "Home."},
    {0: "It's Tokyo Tower", 1: "Sakura!!"},
)


def _propose_everywhere(chapter: _Chapter) -> None:
    for ordinal, lines in enumerate(_PROPOSED):
        chapter.project.write_proposed(ordinal, lines)


def _sakura(chapter: _Chapter) -> str:
    """Store one glossary entry and return the block it renders as."""
    upsert(chapter.project, GlossaryEntry("さくら", "Sakura", "name", 0, 2, "model"))
    return f"{_GLOSSARY_HEADER}\nさくら = Sakura (name)"


def _english_leaks(context: PromptContext) -> list[str]:
    return [
        english
        for lines in _PROPOSED
        for english in lines.values()
        if english in context.glossary_block or english in context.rolling_block
    ]


def test_neighbours_on_the_first_page_is_the_glossary_and_the_next_pages_japanese(
    chapter: _Chapter,
) -> None:
    """**AC-2, ordinal 0**: page 1 is no longer `EMPTY_CONTEXT` in this mode -
    it has a next page. The glossary block is rendered on page 0 too (`##
    Contract`), and there is no previous header."""
    glossary = _sakura(chapter)
    _propose_everywhere(chapter)

    context = build_prompt_context(chapter.project, 0, mode="neighbours")

    assert context == PromptContext(
        glossary_block=glossary,
        rolling_block=f"{_NEXT_JA}\nさくらはどこ?\n家へ。",
    )
    assert _english_leaks(context) == []


def test_neighbours_on_a_middle_page_is_the_page_before_and_the_page_after(
    chapter: _Chapter,
) -> None:
    """**AC-2, ordinal 1**: pages 1 and 3's Japanese, previous first, and not
    page 1's proposed English - which `rolling` would have carried."""
    glossary = _sakura(chapter)
    _propose_everywhere(chapter)

    context = build_prompt_context(chapter.project, 1, mode="neighbours")

    assert context == PromptContext(
        glossary_block=glossary,
        rolling_block=(
            f"{_PREVIOUS_JA}\nさくら、待って!\nどこへ行くの?\n\n{_NEXT_JA}\n東京タワーだ\nさくら!"
        ),
    )
    assert _english_leaks(context) == [], "proposed English reached a neighbours context"


def test_neighbours_on_the_last_page_is_the_previous_page_only(chapter: _Chapter) -> None:
    """**AC-2, ordinal 2** (the last, `len(project.pages()) - 1`): page 2's
    Japanese and no next header."""
    glossary = _sakura(chapter)
    _propose_everywhere(chapter)

    context = build_prompt_context(chapter.project, 2, mode="neighbours")

    assert context == PromptContext(
        glossary_block=glossary,
        rolling_block=f"{_PREVIOUS_JA}\nさくらはどこ?\n家へ。",
    )
    assert _english_leaks(context) == []


def test_no_proposed_english_reaches_any_neighbours_context(chapter: _Chapter) -> None:
    """**AC-2**'s "no proposed English appears in any of them, even when every
    page has a proposal stored", as one collected check over every ordinal -
    the assertion DV-1 must turn red by reading `read_proposed(ordinal - 1)`.
    Control: the same store in `rolling` mode does carry English, so the
    needle can find it."""
    _propose_everywhere(chapter)

    leaks = {
        ordinal: _english_leaks(build_prompt_context(chapter.project, ordinal, mode="neighbours"))
        for ordinal in range(len(_PROPOSED))
    }
    rolling_leaks = _english_leaks(build_prompt_context(chapter.project, 1, mode="rolling"))

    assert leaks == {0: [], 1: [], 2: []}, f"proposed English in a neighbours context: {leaks}"
    assert rolling_leaks == ["Wait up, Sakura!", "Where are you going?"], (
        f"control: rolling mode should carry page 0's English, found {rolling_leaks}"
    )


def test_a_region_ocr_read_as_empty_is_left_out_of_the_neighbours(chapter: _Chapter) -> None:
    """`## Contract`: `[r.text for r in project.read_lines(k) if not
    r.ocr_empty]`. An `ocr_empty` line on either neighbour is dropped, so no
    blank line appears inside a section. Without the filter page 0's block
    would read `...Japanese:\\n\\nどこへ行くの?`."""
    chapter.project.write_lines(0, [OcrResult(text="", ocr_empty=True), OcrResult("どこへ行くの?")])
    chapter.project.write_lines(2, [OcrResult("東京タワーだ"), OcrResult(text="", ocr_empty=True)])

    context = build_prompt_context(chapter.project, 1, mode="neighbours")

    assert context.rolling_block == (f"{_PREVIOUS_JA}\nどこへ行くの?\n\n{_NEXT_JA}\n東京タワーだ")


def test_a_neighbour_that_read_as_entirely_empty_has_no_header(chapter: _Chapter) -> None:
    """A wordless next page is an empty list once filtered, so its header is
    omitted (AC-1 through AC-2) - not `Next page, Japanese:` over nothing."""
    chapter.project.write_lines(
        2, [OcrResult(text="", ocr_empty=True), OcrResult(text="", ocr_empty=True)]
    )

    context = build_prompt_context(chapter.project, 1, mode="neighbours")

    assert context == PromptContext("", f"{_PREVIOUS_JA}\nさくら、待って!\nどこへ行くの?")


def test_neighbours_holds_the_glossary_to_its_cap_and_the_japanese_to_the_rolling_cap(
    chapter: _Chapter,
) -> None:
    """`## Contract`: `render_block(glossary, MAX_GLOSSARY_TOKENS)` and
    `render_neighbours(..., MAX_ROLLING_TOKENS)`. Both sides are sized between
    400 and 500 tokens, as the rolling caps test above is, so the two caps
    swapped is caught from both directions: the next page's 461-token block
    must come back whole, and the 40-entry glossary must be cut to 400."""
    for index in range(40):
        upsert(
            chapter.project,
            GlossaryEntry(
                f"名前{index:02d}", f"Name Number {index:02d}", "name", index, index, "model"
            ),
        )
    long_line = "あ" * 450
    chapter.project.write_lines(1, [OcrResult(long_line), OcrResult("家へ。")])
    whole_next = f"{_NEXT_JA}\n{long_line}\n家へ。"
    whole_glossary = estimate_tokens(
        "\n".join(
            [_GLOSSARY_HEADER]
            + [f"名前{index:02d} = Name Number {index:02d} (name)" for index in range(40)]
        )
    )
    assert estimate_tokens(whole_next) == 461
    assert MAX_GLOSSARY_TOKENS < whole_glossary <= MAX_ROLLING_TOKENS, whole_glossary

    context = build_prompt_context(chapter.project, 0, mode="neighbours")

    assert context.rolling_block == whole_next, "the next page was cut below MAX_ROLLING_TOKENS"
    assert estimate_tokens(context.glossary_block) <= MAX_GLOSSARY_TOKENS
    assert context.glossary_block.startswith(_GLOSSARY_HEADER)


@pytest.mark.parametrize("ordinal", [0, 1, 2])
def test_rolling_by_name_is_the_rolling_context_byte_for_byte(
    chapter: _Chapter, ordinal: int
) -> None:
    """**AC-3**, the explicit half: `mode="rolling"` is today's output for every
    ordinal - page 0 `EMPTY_CONTEXT` whatever the store holds, later pages the
    glossary and the previous page's PROPOSED English - and equal to the call
    with no mode. The no-mode half is every MT-014 test above, unchanged."""
    glossary = _sakura(chapter)
    _propose_everywhere(chapter)
    expected = (
        EMPTY_CONTEXT,
        PromptContext(glossary, f"{_ROLLING_HEADER}\nWait up, Sakura!\nWhere are you going?"),
        PromptContext(glossary, f"{_ROLLING_HEADER}\nWhere is Sakura?\nHome."),
    )[ordinal]

    assert build_prompt_context(chapter.project, ordinal, mode="rolling") == expected
    assert build_prompt_context(chapter.project, ordinal) == expected


def _neighbours_middle() -> PromptContext:
    return PromptContext(
        "",
        f"{_PREVIOUS_JA}\nさくら、待って!\nどこへ行くの?\n\n{_NEXT_JA}\n東京タワーだ\nさくら!",
    )


def _run_page_one_twice(chapter: _Chapter, mode: str) -> _Scripted:
    """Run page 1 through the stage in `mode`, rewrite page 0's proposal, and
    run page 1 again: the two contexts the translator was handed are AC-4's."""
    translator = _Scripted(_result({0: "Where's Sakura?"}), _result({0: "Where's Sakura?"}))
    stage = TranslateStage(
        translate=translator, page_estimate=BOOTSTRAP_PAGE_ESTIMATE, context_mode=mode
    )
    chapter.project.write_proposed(0, {0: "Wait up, Sakura!", 1: "Where are you going?"})
    stage.run(chapter.context(1))
    chapter.project.write_proposed(0, {0: "REWRITTEN between runs", 1: "and this too"})
    stage.run(chapter.context(1))
    return translator


def test_in_neighbours_mode_rewriting_the_previous_proposal_does_not_change_the_request(
    chapter: _Chapter,
) -> None:
    """**AC-4**: `TranslateStage(..., context_mode="neighbours")` builds page
    1's request from a context that page 0's proposal does not reach - the two
    runs hand the translator the same context, and it is the neighbours'
    Japanese (so the equality is not two empty contexts agreeing). The
    independence assertion DV-1 must turn red."""
    translator = _run_page_one_twice(chapter, "neighbours")

    assert translator.contexts[0] == _neighbours_middle(), (
        f"the stage did not build a neighbours context: {translator.contexts[0]!r}"
    )
    assert translator.contexts[1] == translator.contexts[0], (
        "page 0's rewritten proposal changed page 1's neighbours context:"
        f" {translator.contexts[0]!r} -> {translator.contexts[1]!r}"
    )


def test_in_rolling_mode_rewriting_the_previous_proposal_does_change_the_request(
    chapter: _Chapter,
) -> None:
    """**AC-4**'s other half, and the control on the one above: the same two
    runs in `rolling` mode hand over page 0's English, before and after."""
    translator = _run_page_one_twice(chapter, "rolling")

    assert [context.rolling_block for context in translator.contexts] == [
        f"{_ROLLING_HEADER}\nWait up, Sakura!\nWhere are you going?",
        f"{_ROLLING_HEADER}\nREWRITTEN between runs\nand this too",
    ]


def test_a_neighbours_stage_hands_the_first_page_the_next_pages_japanese(
    chapter: _Chapter,
) -> None:
    """`TranslateStage.run` passes `mode=self.context_mode` for every page,
    page 0 included: in this mode page 1's call is not `EMPTY_CONTEXT`."""
    translator = _Scripted(_result({0: "Wait, Sakura!"}))

    TranslateStage(
        translate=translator, page_estimate=BOOTSTRAP_PAGE_ESTIMATE, context_mode="neighbours"
    ).run(chapter.context(0))

    assert translator.contexts == [PromptContext("", f"{_NEXT_JA}\nさくらはどこ?\n家へ。")]
