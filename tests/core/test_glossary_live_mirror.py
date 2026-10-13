"""MT-045 AC-3: the live test sends what the pipeline sends.

`tests/integration/test_glossary_live.py` builds page 2's continuity context
with `context_on(result_p1, ocr_p1)` (C-3), without a store, so it can run 40
paid calls without a project on disk. This file pins that function to the
pipeline: on a real `Project` holding the same page-0 lines, the **real**
`TranslateStage` runs page 0 with a scripted translator returning the same
`TranslationResult` - so `_update_glossary` and `write_proposed` are the
pipeline's own, not a re-statement of them - and `build_prompt_context(project,
1)` must equal `context_on(...)`, `==`.

**Same function object, not a copy** (C-5). `context_on` is imported from
`tests/core/_glossary_live.py` (on `sys.path` under pytest's default `prepend`
mode, as `_bake_world` is for `test_bake.py`), and
`test_the_live_test_calls_this_helpers_context_on_and_not_a_copy` loads the
live test module by path and asserts its `context_on` IS this one.

Runs under `unit` and `coverage`. No network, no SDK.

**Timing.** No `pytest-timeout` in this project, so no budget to size. Each
case builds a two-page project of tiny PNGs on `tmp_path`.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import _glossary_live
import pytest
from _glossary_live import NAME_REGION, context_on, load_ocr

from mangatl.domain.glossary import (
    EMPTY_CONTEXT,
    PromptContext,
    ProposedTerm,
)
from mangatl.domain.line import OcrResult
from mangatl.domain.region import RawRegion
from mangatl.domain.translation import CallInfo, TokenUsage, TranslationResult
from mangatl.pipeline.continuity import build_prompt_context
from mangatl.pipeline.stage import PageContext
from mangatl.pipeline.translate_stage import TranslateStage
from mangatl.store.intake import read_chapter
from mangatl.store.project import Project, create_project, project_dir_for

_REPO = Path(__file__).resolve().parents[2]
_LIVE_TEST = _REPO / "tests" / "integration" / "test_glossary_live.py"

#: Priced in `domain.rates`, so the stage's `record_call` accepts it.
_MODEL = "gemini-3.1-pro-preview"
_USAGE = TokenUsage(input_tokens=2100, output_tokens=640, cache_read_tokens=0, cache_write_tokens=0)


def _ring(x0: int, y0: int, x1: int, y1: int) -> tuple[tuple[int, int], ...]:
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))


def _result(lines: dict[int, str], terms: Sequence[ProposedTerm] = ()) -> TranslationResult:
    return TranslationResult(
        lines=lines,
        usage=_USAGE,
        call=CallInfo(request_id="mt045-mirror", model_id=_MODEL),
        proposed_terms=tuple(terms),
    )


def _pipeline_context(
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
    ocr_p1: Sequence[OcrResult],
    result_p1: TranslationResult,
) -> PromptContext:
    """Page 0 through the real `TranslateStage`, then the pipeline's own
    context for ordinal 1."""
    source_dir = tmp_path / "scans"
    source_dir.mkdir()
    for index in range(2):
        (source_dir / f"p{index + 1}.png").write_bytes(png_bytes(30, 40, (index * 60, 0, 0)))
    mask = one_bit_png(30, 40, [(0, 0, 4, 4)])

    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as project:
        project.write_regions(
            0,
            tuple(
                RawRegion(
                    polygon=_ring(2, 2 + 8 * i, 12, 8 + 8 * i),
                    mask=mask,
                    confidence=0.5,
                    kind="bubble",
                )
                for i in range(len(ocr_p1))
            ),
        )
        project.write_lines(0, list(ocr_p1))
        run_id = _new_run(project)
        handed: list[PromptContext] = []

        def translator(
            image: bytes, results: Sequence[OcrResult], context: PromptContext
        ) -> TranslationResult:
            handed.append(context)
            assert tuple(results) == tuple(ocr_p1), "the stage read different page-0 lines"
            return result_p1

        page0 = next(page for page in project.pages() if page.ordinal == 0)
        TranslateStage(translate=translator).run(
            PageContext(project=project, page=page0, run_id=run_id, emit=lambda _event: None)
        )
        assert handed == [EMPTY_CONTEXT], "page 1 was not sent EMPTY_CONTEXT"
        return build_prompt_context(project, 1)


def _new_run(project: Project) -> int:
    with project.transaction() as cursor:
        chapter_id = int(cursor.execute("SELECT id FROM chapter").fetchone()[0])
        cursor.execute(
            "INSERT INTO run (chapter_id, started_at) VALUES (?, ?)",
            (chapter_id, "2026-10-13T09:00:00+00:00"),
        )
        return int(cursor.execute("SELECT last_insert_rowid()").fetchone()[0])


# The page-1 results the live test could get back, shaped by hand. Region 2
# omitted in the first: the rolling block must skip it, as `read_proposed`'s
# NULL is skipped. The third adds a region proposed as "" (kept as an empty
# line, PO-7 of MT-014), a blank-sided proposal `merge` drops, and a second
# proposal for 翔 that `merge` must ignore (first one wins).
_CASES = {
    "two proposed terms and one omitted region": _result(
        {0: "Hey, hurry up!", 1: "Shou, over here!", 3: "The train's leaving!"},
        [
            ProposedTerm("翔", "Shou", "name"),
            ProposedTerm("電車", "train", ""),
        ],
    ),
    "no proposals": _result(
        {0: "Hey, hurry up!", 1: "Kakeru, this way!", 2: "Wait for me...", 3: "The train!"}
    ),
    "an empty line, a blank-sided term and a repeated term": _result(
        {0: "", 1: "Sho, this way!", 2: "Wait up..."},
        [
            ProposedTerm("翔", "Sho", "name"),
            ProposedTerm("急げ", "  ", ""),
            ProposedTerm("翔", "Kakeru", "name"),
        ],
    ),
}


@pytest.mark.parametrize("case", list(_CASES))
def test_the_live_tests_page_two_context_equals_what_the_pipeline_builds(
    case: str,
    tmp_path: Path,
    png_bytes: Callable[..., bytes],
    one_bit_png: Callable[..., bytes],
) -> None:
    """AC-3: `context_on(result_p1, ocr_p1) == build_prompt_context(project, 1)`
    after the real stage ran page 0 with that result."""
    ocr_p1 = load_ocr()["p1"]
    result_p1 = _CASES[case]

    pipeline = _pipeline_context(tmp_path, png_bytes, one_bit_png, ocr_p1, result_p1)

    assert context_on(result_p1, ocr_p1) == pipeline


def test_the_two_term_case_actually_carries_a_glossary_and_a_rolling_block(
    tmp_path: Path, png_bytes: Callable[..., bytes], one_bit_png: Callable[..., bytes]
) -> None:
    """The equality above is only worth something if neither side is empty: two
    `EMPTY_CONTEXT`s are equal too. Pins that the two-term case sends 翔's
    entry and page 1's English, omitted region left out."""
    ocr_p1 = load_ocr()["p1"]
    result_p1 = _CASES["two proposed terms and one omitted region"]

    pipeline = _pipeline_context(tmp_path, png_bytes, one_bit_png, ocr_p1, result_p1)

    assert "翔 = Shou (name)" in pipeline.glossary_block.split("\n")
    assert "電車 = train" in pipeline.glossary_block.split("\n")
    assert pipeline.rolling_block.split("\n")[1:] == [
        "Hey, hurry up!",
        "Shou, over here!",
        "The train's leaving!",
    ]


def test_the_mirror_reads_the_same_name_region_the_live_test_scores() -> None:
    assert NAME_REGION == {"p1": 1, "p2": 1}


def test_the_live_test_calls_this_helpers_context_on_and_not_a_copy() -> None:
    """C-5: identity, not equality of behaviour. The live test module is loaded
    by path (it imports no SDK at module level, so this costs nothing); its
    `context_on` must be the very object this file checks against the
    pipeline, so a drift in one place cannot leave the other green."""
    spec = importlib.util.spec_from_file_location("_mt045_live_module", _LIVE_TEST)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered while it executes: its dataclass resolves annotations through
    # `sys.modules[cls.__module__]`.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[spec.name]

    assert module.context_on is context_on
    assert module.context_on is _glossary_live.context_on
    assert module.reading is _glossary_live.reading
    assert sys.modules["_glossary_live"] is _glossary_live


def test_loading_the_live_test_module_does_not_import_the_sdk() -> None:
    """C-4: `google.genai` only inside the live test's body. Checked off the
    module's AST so the answer does not depend on what an earlier test in the
    session imported."""
    import ast

    tree = ast.parse(_LIVE_TEST.read_text(encoding="utf-8"))
    top_level: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            top_level.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_level.append(node.module)
    assert not any(str(name).startswith("google") for name in top_level), top_level
