"""`mangatl.pipeline.continuity` and `TranslateStage` with continuity wired in.

MT-014 C-8 and C-9. Covers **AC-1** end to end (page 0's proposal is in page
1's request), the stage halves of **AC-4** (page N carries page N-1's proposed
English) and **AC-5** (page 1 carries nothing and does not fail), and the order
C-9 fixes: `record_call` -> glossary -> `write_proposed`.

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
from dataclasses import dataclass
from pathlib import Path

import pytest

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
        return PageContext(project=self.project, page=page, run_id=self.run_id)

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
    source_dir = tmp_path / "scans"
    source_dir.mkdir()
    for index, (filename, width, height) in enumerate(_SOURCE_PAGES):
        (source_dir / filename).write_bytes(png_bytes(width, height, (index * 40, 0, 0)))
    mask = one_bit_png(30, 20, [(0, 0, 4, 4)])

    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        for ordinal, texts in enumerate(_OCR):
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


def test_the_proposal_from_page_one_is_in_page_twos_request(chapter: _Chapter) -> None:
    """**AC-1**, as C-10 words it: page 0's response proposes "Sakura" for
    さくら; page 1's `PromptContext.glossary_block` carries the line
    `さくら = Sakura (name)`, and so does the context text block of the request
    `build_request` assembles from it."""
    translator = _Scripted(
        _result({0: "Wait, Sakura!"}, [ProposedTerm("さくら", "Sakura", "name")]),
        _result({0: "Where's Sakura?"}),
    )
    stage = TranslateStage(translate=translator)

    stage.run(chapter.context(0))
    stage.run(chapter.context(1))

    page_two = translator.contexts[1]
    assert "さくら = Sakura (name)" in page_two.glossary_block.split("\n")
    request, _ = build_request(chapter.page_bytes(1), chapter.project.read_lines(1), page_two)
    context_block = request["messages"][0]["content"][1]
    assert context_block["type"] == "text"
    assert "さくら = Sakura (name)" in context_block["text"]


def test_page_one_is_translated_with_the_empty_context(chapter: _Chapter) -> None:
    """**AC-5** at the stage: the first page's translator call is handed
    `EMPTY_CONTEXT`, and the page completes."""
    translator = _Scripted(_result({0: "Wait, Sakura!"}))

    TranslateStage(translate=translator).run(chapter.context(0))

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
    stage = TranslateStage(translate=translator)

    for ordinal in range(3):
        stage.run(chapter.context(ordinal))

    assert translator.contexts[2].rolling_block == f"{_ROLLING_HEADER}\nWhere's Sakura?\nHome."
    assert translator.seen[2][0] == chapter.page_bytes(2)


def test_a_proposed_term_is_stored_as_first_and_last_seen_on_its_page(chapter: _Chapter) -> None:
    """C-9 step 4 with C-1's `merge`: the page is `ctx.page.ordinal`, here 1,
    not 0 - and the entry is a model's."""
    chapter.project.write_proposed(0, {0: "Wait, Sakura!"})
    translator = _Scripted(
        _result({0: "Where's Sakura?"}, [ProposedTerm("さくら", "Sakura", "name")])
    )

    TranslateStage(translate=translator).run(chapter.context(1))

    assert read_entries(chapter.project) == [
        GlossaryEntry("さくら", "Sakura", "name", 1, 1, "model")
    ]


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

    TranslateStage(translate=_Scripted(_result({0: "It's Tokyo Tower"}))).run(chapter.context(2))

    assert read_entries(chapter.project) == [
        GlossaryEntry("さくら", "Sakura", "name", 0, 2, "model"),
        GlossaryEntry("東京", "Tokyo", "place", 0, 2, "user"),
        GlossaryEntry("けんじ", "Kenji", "name", 0, 1, "model"),
    ]


def test_a_later_page_cannot_re_render_a_name_the_chapter_already_has(
    chapter: _Chapter,
) -> None:
    """The story's reason for existing, at the stage: page 1's model proposes
    "Sakura-chan" for a name page 0 introduced as "Sakura". The chapter keeps
    "Sakura" (C-1), and page 2 is told so."""
    translator = _Scripted(
        _result({0: "Wait, Sakura!"}, [ProposedTerm("さくら", "Sakura", "name")]),
        _result({0: "Where's Sakura-chan?"}, [ProposedTerm("さくら", "Sakura-chan", "name")]),
        _result({}),
    )
    stage = TranslateStage(translate=translator)

    for ordinal in range(3):
        stage.run(chapter.context(ordinal))

    assert read_entries(chapter.project) == [
        GlossaryEntry("さくら", "Sakura", "name", 0, 2, "model")
    ]
    assert "さくら = Sakura (name)" in translator.contexts[2].glossary_block.split("\n")


def test_the_glossary_is_written_before_the_proposals(chapter: _Chapter) -> None:
    """C-9's order, second half: glossary **before** `write_proposed`. The
    result names region 99, so `write_proposed` raises with nothing written
    (MT-011 C-6); the page's names must already be on disk, and so must its
    bill (MT-044 C-7). The other order marks the page done with its names never
    recorded."""
    translator = _Scripted(
        _result({99: "a region that is not there"}, [ProposedTerm("さくら", "Sakura", "name")])
    )

    with pytest.raises(ValueError, match=r"\b99\b"):
        TranslateStage(translate=translator).run(chapter.context(0))

    assert read_entries(chapter.project) == [
        GlossaryEntry("さくら", "Sakura", "name", 0, 0, "model")
    ]
    assert chapter.ledger_rows() == 1
    assert chapter.project.read_proposed(0) == (None, None)


def test_a_call_that_cannot_be_priced_writes_no_glossary_either(chapter: _Chapter) -> None:
    """C-9's order, first half: `record_call(...)` is "unchanged, and still
    first", and `price(...)` sits inside its argument list (MT-044 C-7 clause
    3), so an unpriceable model raises before **any** write. A glossary step
    moved ahead of the ledger would leave this page's names behind."""
    translator = _Scripted(
        _result(
            {0: "Wait, Sakura!"},
            [ProposedTerm("さくら", "Sakura", "name")],
            model_id="claude-not-in-the-rate-table",
        )
    )

    with pytest.raises(UnknownModel):
        TranslateStage(translate=translator).run(chapter.context(0))

    assert read_entries(chapter.project) == []
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

    TranslateStage(translate=_Scripted(_result({}, call=False))).run(chapter.context(1))

    assert read_entries(chapter.project) == before
    assert chapter.ledger_rows() == 0
    assert chapter.project.read_proposed(1) == (None, None)


def test_re_running_a_page_leaves_one_entry_per_term(chapter: _Chapter) -> None:
    """`merge` is idempotent (C-9's reason the order is safe): a page
    re-translated after a crash re-proposes its names and the glossary does not
    grow."""
    terms = [ProposedTerm("さくら", "Sakura", "name")]
    translator = _Scripted(_result({0: "Wait!"}, terms), _result({0: "Wait!"}, terms))
    stage = TranslateStage(translate=translator)

    stage.run(chapter.context(0))
    stage.run(chapter.context(0))

    assert read_entries(chapter.project) == [
        GlossaryEntry("さくら", "Sakura", "name", 0, 0, "model")
    ]
