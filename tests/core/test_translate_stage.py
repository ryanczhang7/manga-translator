"""`mangatl.pipeline.translate_stage`: the page, end to end, minus the network.

Covers **AC-4**, **AC-5**, **AC-6** and **AC-7** at the level a user would
notice them - what ends up in the store - and C-1's module shape with them.

**The module is `pipeline/translate_stage.py` and not `translate/stage.py`, and
that is forced by a required gate rather than chosen for taste** (C-1, measured
by the PO in PO-3/PO-4 with throwaway probe modules, and re-checked in RED
against `pyproject.toml`). Two contracts bite at once, from opposite sides:

* the **layers** contract puts `mangatl.translate` *below* `mangatl.pipeline`,
  so a stage living in `mangatl.translate` may not import `PageContext` at all -

      mangatl.translate is not allowed to import mangatl.pipeline:
      - mangatl.translate._probe_layers -> mangatl.pipeline.stage (l.1)

* and the **"Only translate imports anthropic"** contract lists
  `mangatl.pipeline` among its `source_modules` with **no**
  `allow_indirect_imports`, so this module may not import `mangatl.translate`
  either - not under `TYPE_CHECKING`, not inside a function body, because
  import-linter reports those too -

      mangatl.pipeline is not allowed to import anthropic:
      -   mangatl.pipeline._probe_chain -> mangatl.translate._probe_client (l.1)
          mangatl.translate._probe_client -> anthropic (l.1)

So `TranslateStage` names its collaborator behind `PageTranslator`, whose every
half is stdlib or `domain`, exactly as `OcrStage` names `PageTranscriber` and
`DetectStage` names `PageDetector`. This is MT-010 C-1 and MT-035 C-1 recurring
for the third time. `test_the_stage_module_imports_nothing_the_two_contracts_forbid`
is the `unit` tripwire for it, so the constraint is falsifiable before `lint`
sees it and the failure names the import rather than the contract.

**This file mirrors `tests/core/test_ocr_stage.py` deliberately**, including its
AST read of the module's own imports and its choice of a target page that is
**not ordinal 0**. Both were paid for once already and the reasons have not
changed.

**No `Anthropic` client appears here at all.** The stage's collaborator is a
`PageTranslator`, and the "no API call" half of AC-7 lives one layer down, in
`tests/core/test_translate_client.py`, where the client does.

**Timing.** No `pytest-timeout` in this project and no per-test timeout exists,
so there is no budget in this file to size; if a later story adds one, every
test and hook here needs one. The dominant cost is `conftest._one_bit_png`
(MT-009: 281 ms page-sized, 7 ms small), so the fixture pages are 30-50 px wide.
"""

from __future__ import annotations

import ast
import hashlib
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import get_args, get_origin

import pytest

from mangatl.domain.line import OcrResult
from mangatl.domain.region import RawRegion
from mangatl.domain.translation import TokenUsage, TranslationResult
from mangatl.pipeline.stage import PageContext
from mangatl.pipeline.translate_stage import PageTranslator, TranslateStage
from mangatl.store.intake import read_chapter
from mangatl.store.project import Project, create_project, project_dir_for

# -- the fixture chapter -------------------------------------------------------

#: Three pages at three distinct sizes, so every page's bytes differ and "the
#: page's OWN bytes" is a claim with something to be false about.
_SOURCE_PAGES: tuple[tuple[str, int, int], ...] = (
    ("p1.png", 30, 20),
    ("p2.png", 40, 30),
    ("p3.png", 50, 40),
)

#: The page every criterion runs against, and it is **not ordinal 0** (MT-035
#: DV-3): a mutation of `ctx.page.ordinal` to `0` is one token and a plausible
#: typo, and a test whose page sits at 0 cannot see it.
_TARGET_ORDINAL = 1
_PAGE_WIDTH, _PAGE_HEIGHT = _SOURCE_PAGES[_TARGET_ORDINAL][1], _SOURCE_PAGES[_TARGET_ORDINAL][2]

#: `TranslateStage.name`, pinned as a literal: the event stream carries it and
#: `architecture.md` §5's stage list names it.
_TRANSLATE = "translate"

#: What OCR left on the target page. Three regions, one of which read empty.
_LINES: tuple[OcrResult, ...] = (
    OcrResult(text="醜鬼が人間の言う通りに動いたりね"),
    OcrResult(text="", ocr_empty=True),
    OcrResult(text="……なるほど"),
)

#: AC-7's page: every region read empty.
_ALL_EMPTY: tuple[OcrResult, ...] = tuple(OcrResult(text="", ocr_empty=True) for _ in range(3))

#: A previous run's English on every region - the money `architecture.md` §4/§6
#: is about, and what AC-6's "nothing is written" has to leave alone.
_EXISTING: dict[int, str] = {
    0: "A demon obeying a human? Please.",
    1: "A previous line for region 1.",
    2: "...I see.",
}

_USAGE = TokenUsage(
    input_tokens=3011, output_tokens=712, cache_read_tokens=1499, cache_write_tokens=1873
)


class _UnknownRegionIndexStandIn(Exception):
    """AC-6's exception, raised by the *collaborator*.

    A bespoke type rather than `mangatl.translate.parse.UnknownRegionIndex`, and
    that is the point of C-1: this test file is about `mangatl.pipeline`, whose
    contract is that it names nothing in `mangatl.translate`. What the stage has
    to do with the exception - let it through, having written nothing - is true
    of any exception, so the test says so with one the stage cannot know about.
    """


def _ring(x0: int, y0: int, x1: int, y1: int) -> tuple[tuple[int, int], ...]:
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))


@dataclass(frozen=True)
class _Fixture:
    source_dir: Path
    project: Project
    mask: bytes

    @property
    def context(self) -> PageContext:
        return self.page_context(_TARGET_ORDINAL)

    def page_context(self, ordinal: int) -> PageContext:
        page = next(page for page in self.project.pages() if page.ordinal == ordinal)
        return PageContext(project=self.project, page=page)

    @property
    def regions(self) -> tuple[RawRegion, ...]:
        """Three regions already in reading order, and not in geometric order."""
        return (
            RawRegion(polygon=_ring(20, 2, 30, 8), mask=self.mask, confidence=0.5, kind="bubble"),
            RawRegion(polygon=_ring(2, 2, 12, 8), mask=self.mask, confidence=0.75, kind="bubble"),
            RawRegion(polygon=_ring(2, 20, 12, 28), mask=self.mask, confidence=0.25, kind="box"),
        )

    def seed(
        self,
        lines: Sequence[OcrResult] = _LINES,
        *,
        proposals: bool = False,
        ordinal: int = _TARGET_ORDINAL,
    ) -> None:
        self.project.write_regions(ordinal, self.regions)
        self.project.write_lines(ordinal, lines)
        if proposals:
            self.project.write_proposed(ordinal, _EXISTING)

    @property
    def page_bytes(self) -> bytes:
        page = next(page for page in self.project.pages() if page.ordinal == _TARGET_ORDINAL)
        return (self.source_dir / page.filename).read_bytes()


@pytest.fixture
def fixture(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
) -> Iterator[_Fixture]:
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


class _FakeTranslator:
    """A `PageTranslator`: page bytes and the page's OCR results in, one result
    out. Records every call, because the criteria are claims about the count,
    about the exact bytes and about the exact results it was handed."""

    def __init__(
        self,
        lines: dict[int, str] | None = None,
        *,
        raises: BaseException | None = None,
    ) -> None:
        self._lines = dict(lines or {})
        self._raises = raises
        self.seen: list[tuple[bytes, tuple[OcrResult, ...]]] = []

    @property
    def calls(self) -> int:
        return len(self.seen)

    def __call__(self, image: bytes, results: Sequence[OcrResult]) -> TranslationResult:
        self.seen.append((image, tuple(results)))
        if self._raises is not None:
            raise self._raises
        return TranslationResult(lines=dict(self._lines), usage=_USAGE)


def _snapshot(root: Path) -> dict[str, str | None]:
    """relative path -> sha256 of contents, or None for a directory."""
    return {
        str(entry.relative_to(root)): (
            hashlib.sha256(entry.read_bytes()).hexdigest() if entry.is_file() else None
        )
        for entry in sorted(root.rglob("*"))
    }


# -- the module's shape --------------------------------------------------------


def test_the_stage_is_exported_from_mangatl_pipeline_translate_stage_under_that_name(
    fixture: _Fixture,
) -> None:
    """C-1's module path, `__all__`, field name and stage name, pinned exactly.

    The module path is the criterion here, not decoration: `src/mangatl/
    translate/stage.py` is what the story was first drafted with and it
    **cannot exist** (see the module docstring). An import error from this line
    is the first thing GREEN should read.
    """
    import mangatl.pipeline.translate_stage as module

    assert module.__all__ == ["PageTranslator", "TranslateStage"]

    translator = _FakeTranslator()
    stage = TranslateStage(translate=translator)

    assert stage.name == _TRANSLATE
    assert stage.translate is translator
    assert callable(stage.run)
    assert callable(stage.is_done)
    assert isinstance(stage.is_done(fixture.context), bool)


def test_the_stage_name_is_a_settable_instance_attribute_as_the_protocol_requires() -> None:
    """C-1's "**not** `frozen=True`" - MT-035 amendment R-1, measured twice
    there. `Stage.name` is declared `name: str`, a settable protocol member, and
    mypy holds an implementation to it:

        Protocol member Stage.name expected settable variable,
        got read-only attribute        # @dataclass(frozen=True), name: str
        Protocol member Stage.name expected instance variable,
        got class variable             # @dataclass(frozen=True), name: ClassVar[str]

    Neither spelling of a frozen dataclass satisfies it, so the assignment below
    is the `unit` half of a failure that otherwise only `typecheck` sees.
    """
    stage = TranslateStage(translate=_FakeTranslator())

    stage.name = "renamed"

    assert stage.name == "renamed"


def test_the_stage_module_imports_nothing_the_two_contracts_forbid() -> None:
    """C-1, as a `unit` tripwire rather than only as a `lint` one.

    Read off the module's own source with `ast`, so an import inside a function
    body or under `TYPE_CHECKING` counts exactly as import-linter counts it. The
    difference from `lint` is the message: this names the offending import and
    the contract it breaks, at the moment it is added.
    """
    import mangatl.pipeline.translate_stage as module

    source = Path(module.__file__ or "").read_text(encoding="utf-8")
    imported: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.append(node.module)

    for name in imported:
        assert not name.startswith("anthropic"), (
            f"{name}: mangatl.pipeline is not allowed to import anthropic"
        )
        assert not name.startswith("mangatl.translate"), (
            f"{name}: mangatl.pipeline may not reach anthropic through mangatl.translate"
            " either - the contract has no allow_indirect_imports"
        )
        assert not name.startswith(("mangatl.detect", "mangatl.ocr", "mangatl.clean")), (
            f"{name}: a stage importing a stage makes the layers contract a fiction"
        )


def test_the_page_translator_alias_names_only_stdlib_and_domain_types() -> None:
    """C-1's comment made executable: *"Every half is stdlib or domain. It must
    NOT name anything in mangatl.translate - that is the contract C-1 is
    about."* `bytes` and `Sequence` are stdlib; `OcrResult` and
    `TranslationResult` are `domain`, which is what C-2 is for."""
    assert get_origin(PageTranslator) is not None, "PageTranslator is not a Callable alias"

    arguments, result = get_args(PageTranslator)

    assert arguments == [bytes, Sequence[OcrResult]]
    assert result is TranslationResult


# -- the wiring ----------------------------------------------------------------


def test_the_stage_hands_over_the_pages_own_bytes_and_its_stored_ocr_results(
    fixture: _Fixture,
) -> None:
    """The regions and their text come from the **store**, not from a fresh
    OCR pass: translation runs over what the OCR stage already wrote, in the
    order it was written, so a resumed run translates the same bubbles the user
    will see highlighted (`OcrStage`'s own reason, inherited).

    The target page is ordinal 1 and the three fixture pages are three different
    sizes, so "the page's own bytes" is falsifiable.
    """
    fixture.seed()
    translator = _FakeTranslator({0: "Alpha.", 1: "Beta.", 2: "Gamma."})

    TranslateStage(translate=translator).run(fixture.context)

    assert translator.calls == 1
    image, results = translator.seen[0]
    assert image == fixture.page_bytes
    assert results == _LINES


def test_the_stage_writes_nothing_beside_the_scans(fixture: _Fixture) -> None:
    """`architecture.md` §5: the scans are read-only to this app. The page file
    is read and nothing beside it is written - not a cache, not a resized copy,
    not a scratch folder."""
    fixture.seed()
    before = _snapshot(fixture.source_dir)

    TranslateStage(translate=_FakeTranslator({0: "Alpha."})).run(fixture.context)

    assert _snapshot(fixture.source_dir) == before


# -- AC-4 ----------------------------------------------------------------------


def test_every_region_receives_its_own_proposal_and_no_other_regions(
    fixture: _Fixture,
) -> None:
    """**AC-4**, where a user would see it: the English is on the matching
    `line` row, and no row carries a line belonging to another.

    The three proposals are distinct and are handed over in an order that is not
    the region order, so a stage that wrote them positionally - ignoring the
    mapping's keys - puts the right words on the wrong bubbles. That is the
    corruption `stack.md` §5/O2's "rotate the proposed lines by one region"
    control exists to catch further downstream, and it is silent here.
    """
    fixture.seed()
    lines = {2: "...I see.", 0: "A demon obeying a human? Please.", 1: "A middle line."}

    TranslateStage(translate=_FakeTranslator(lines)).run(fixture.context)

    assert fixture.project.read_proposed(_TARGET_ORDINAL) == (
        "A demon obeying a human? Please.",
        "A middle line.",
        "...I see.",
    )


# -- AC-5 ----------------------------------------------------------------------


def test_a_region_the_model_omitted_keeps_a_null_proposal_and_the_rest_are_stored(
    fixture: _Fixture,
) -> None:
    """**AC-5**, in full, including its last clause: **the page is not
    discarded.**

    Region 1 is absent from the result, so its `proposed_en` stays NULL - which
    is what "untranslated" means (C-6; no new column, no schema bump). Regions 0
    and 2 are still assigned. An implementation that raised on an incomplete
    response, or that skipped the whole write, would throw away two bubbles the
    model paid for because a third was missing.
    """
    fixture.seed()

    TranslateStage(translate=_FakeTranslator({0: "Alpha.", 2: "Gamma."})).run(fixture.context)

    assert fixture.project.read_proposed(_TARGET_ORDINAL) == ("Alpha.", None, "Gamma.")


# -- AC-6 ----------------------------------------------------------------------


def test_an_unknown_region_index_aborts_the_page_with_nothing_written(
    fixture: _Fixture,
) -> None:
    """**AC-6**'s second half: "nothing is written to the store".

    The page is seeded with a *previous* run's proposals on every region, so
    "nothing is written" is a real claim rather than "the page was already
    empty". Those rows cost real money (`architecture.md` §4/§6): a stage that
    cleared the page before calling the translator, or that wrote a partial
    result before the failure, destroys them.

    The stage does not catch the exception - it reaches the runner, which is
    what turns one bad page into one failed page rather than a silent one.
    """
    fixture.seed(proposals=True)
    before = fixture.project.read_proposed(_TARGET_ORDINAL)
    translator = _FakeTranslator(raises=_UnknownRegionIndexStandIn("region 7 is not on this page"))

    with pytest.raises(_UnknownRegionIndexStandIn, match=r"\b7\b"):
        TranslateStage(translate=translator).run(fixture.context)

    assert fixture.project.read_proposed(_TARGET_ORDINAL) == before
    assert before == (
        "A demon obeying a human? Please.",
        "A previous line for region 1.",
        "...I see.",
    )


# -- AC-7 ----------------------------------------------------------------------


def test_a_page_of_wordless_art_completes_with_no_proposed_lines(
    fixture: _Fixture,
) -> None:
    """**AC-7**'s second half. The first half - *no API call is made* - is
    asserted where the client is, in `tests/core/test_translate_client.py`, as
    `client.calls == 0`; the stage has no client and could not see it.

    "Completes" is the criterion: `run` returns, nothing raises, the page is not
    a failure. And nothing is proposed, because there was nothing to propose.
    """
    fixture.seed(_ALL_EMPTY)
    translator = _FakeTranslator({})

    TranslateStage(translate=translator).run(fixture.context)

    assert fixture.project.read_proposed(_TARGET_ORDINAL) == (None, None, None)


def test_a_wordless_page_does_not_clear_what_an_earlier_run_proposed(
    fixture: _Fixture,
) -> None:
    """The resume case of AC-7, and the other way an empty result costs money.
    A page whose OCR rows were later replaced by empties must not take the
    English hanging off them with it."""
    fixture.seed(_ALL_EMPTY, proposals=True)

    TranslateStage(translate=_FakeTranslator({})).run(fixture.context)

    assert fixture.project.read_proposed(_TARGET_ORDINAL) == (
        "A demon obeying a human? Please.",
        "A previous line for region 1.",
        "...I see.",
    )


# -- resume --------------------------------------------------------------------


def test_a_page_with_no_proposals_is_not_done_and_one_with_a_proposal_is(
    fixture: _Fixture,
) -> None:
    """C-1's `is_done`, as MT-011 `## Contract` C-1's RED amendment settles it:
    a page is done once **any** region carries a non-NULL `proposed_en`.

    Directly mirrors `OcrStage.is_done`, which is lines and not regions for the
    same reason (MT-010): a page that has lines but no proposals is exactly the
    state a resumed run must pick up at. Per stage per page, which is what makes
    a killed run resume rather than restart (`architecture.md` §6).
    """
    fixture.seed()
    stage = TranslateStage(translate=_FakeTranslator({0: "Alpha."}))

    assert stage.is_done(fixture.context) is False

    stage.run(fixture.context)

    assert stage.is_done(fixture.context) is True


def test_a_page_with_no_regions_at_all_is_never_done(fixture: _Fixture) -> None:
    """The zero of zero-one-many, and it matches what `OcrStage` and
    `DetectStage` decide for the same page: a page that has not been detected
    writes nothing and is never done."""
    stage = TranslateStage(translate=_FakeTranslator({}))

    assert stage.is_done(fixture.context) is False


def test_is_done_reads_the_page_it_is_given_and_not_the_first_one(
    fixture: _Fixture,
) -> None:
    """MT-035 DV-3 again, on the read side: `read_proposed(0)` in place of
    `read_proposed(ctx.page.ordinal)` is one token, and it would report every
    page of the chapter done as soon as page 0 was."""
    fixture.seed(ordinal=0)
    fixture.seed(ordinal=_TARGET_ORDINAL)
    fixture.project.write_proposed(0, {0: "Alpha."})

    stage = TranslateStage(translate=_FakeTranslator({}))

    assert stage.is_done(fixture.page_context(0)) is True
    assert stage.is_done(fixture.context) is False


# -- C-8: this story does not wire the stage into the pipeline -----------------


def test_the_stage_list_is_left_exactly_as_mt_036_left_it() -> None:
    """**C-8**, PO-6, *decided by the user on 2026-09-18.*

    Wiring `TranslateStage` into `build_stages` now would make every
    `mangatl-run` spend real money with no ledger (MT-012) and no budget guard
    (MT-013), which is the precise failure EPIC-04 exists to prevent. MT-013
    owns the wiring, and it has to go through its own RED because
    `tests/core/test_stages.py` pins this module's `__all__` to an exact list.

    Precedent, not invention: MT-035 shipped `DetectStage` and MT-010 shipped
    `OcrStage`, both correct and neither in any stage list, until MT-036.

    **This test passes on arrival** and is a regression guard for a decision
    rather than for behaviour. It earns its place the way `red-phase.md` asks:
    the probe is in MT-011's `## Handoff: RED -> GREEN`, and it is cheap -
    adding a third stage to `build_stages` turns this red *and*
    `test_stages.py`'s `__all__` assertion with it.

    The import check is read off the module's `ast` and not off its text.
    MEASURED in RED, 2026-09-18: `stages.py` line 17 already says *"the story
    that adds a translate stage changes one line here"*, so a substring search
    for `translate` over the source fails today, against a module nobody has
    touched. That version of this test would have been red on arrival for a
    reason that has nothing to do with C-8.
    """
    import mangatl.pipeline.stages as module

    assert module.__all__ == ["build_stages"]

    tree = ast.parse(Path(module.__file__ or "").read_text(encoding="utf-8"))
    imported = [
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    ]

    assert not any("translate" in name for name in imported), (
        f"pipeline/stages.py imports {imported}; C-8 says MT-013 wires the stage, not this story"
    )
