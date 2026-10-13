"""MT-045's shared helper: the measure (C-2), the fixture (C-1) and the
continuity-on context (C-3), in ONE module that both test files reach.

**Why here, and how it is shared.** `tests/` has no `__init__.py`, so neither
test directory is importable from the other by package name. pytest's default
`prepend` import mode puts `tests/core` on `sys.path` when it collects a file
there, so `tests/core/test_glossary_live_mirror.py` does `import _glossary_live`
as `test_bake.py` does `import _bake_world`. The live test in
`tests/integration/` cannot rely on that (it may be collected alone), so its
`_shared()` returns
`sys.modules["_glossary_live"]` when it is already imported and otherwise
loads THIS FILE by path under THAT NAME and registers it. Either way there is
one module object per process, so `context_on` in the live test and in the
mirror test is the same function object (C-5), and
`test_the_live_test_calls_this_helpers_context_on_and_not_a_copy` asserts it.

Imports nothing beyond `mangatl.domain` and the stdlib: no SDK at collection
time.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from mangatl.domain.glossary import (
    MAX_GLOSSARY_TOKENS,
    MAX_ROLLING_TOKENS,
    PromptContext,
    mark_seen,
    merge,
    render_block,
    render_rolling,
)
from mangatl.domain.line import OcrResult
from mangatl.domain.translation import TranslationResult

REPO = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO / "fixtures" / "translate"
OCR_FIXTURE = FIXTURE_DIR / "kakeru-ocr.json"
PAGES = {"p1": FIXTURE_DIR / "kakeru-p1.png", "p2": FIXTURE_DIR / "kakeru-p2.png"}

#: C-1: the reading index of the one bubble on each page that carries 翔.
NAME_REGION: dict[str, int] = {"p1": 1, "p2": 1}

#: The name under test (C-1). Never swapped for a name with one obvious reading.
NAME = "翔"

#: C-2: longest-first among the Sh- readings, so `Sho` cannot pre-empt `Shou`
#: or `Shoh`. Matched as a whole word (see `reading`).
READINGS: tuple[str, ...] = ("Shou", "Shō", "Shoh", "Syo", "Sho", "Kakeru")


def reading(text: str) -> str:
    """C-2 as amended in RED: the first member of `READINGS` that occurs in
    `text` as a **whole word**, case-sensitive; else `"?"`.

    Whole word because a bare substring reads `Sho` out of `Show`, `Should`,
    `Shout` and `Short` - all ordinary English at the start of a sentence -
    and, with `Kakeru` last in `READINGS`, would read `"Kakeru, should we
    go?"` as `Sho`. A word character either side disqualifies the match;
    an apostrophe, hyphen or punctuation does not (`Shō's`, `Shou-kun`)."""
    for candidate in READINGS:
        if re.search(rf"(?<!\w){re.escape(candidate)}(?!\w)", text):
            return candidate
    return "?"


def load_ocr() -> dict[str, tuple[OcrResult, ...]]:
    """`kakeru-ocr.json` -> `{"p1": (OcrResult, ...), "p2": (...)}`, reading order."""
    records: dict[str, list[dict[str, Any]]] = json.loads(OCR_FIXTURE.read_text(encoding="utf-8"))
    return {
        page: tuple(OcrResult(text=r["text"], ocr_empty=r["ocr_empty"]) for r in regions)
        for page, regions in records.items()
    }


def context_on(result_p1: TranslationResult, ocr_p1: Sequence[OcrResult]) -> PromptContext:
    """C-3's continuity-on context for page 2 (ordinal 1): what
    `continuity.build_prompt_context(project, 1)` returns after
    `translate_stage._update_glossary` and `write_proposed` ran on page 0's
    result - computed without a store. AC-3 pins the equality."""
    entries = mark_seen(merge([], result_p1.proposed_terms, 0), [r.text for r in ocr_p1], 0)
    return PromptContext(
        render_block(entries, MAX_GLOSSARY_TOKENS),
        render_rolling(
            [result_p1.lines[i] for i in range(len(ocr_p1)) if i in result_p1.lines],
            MAX_ROLLING_TOKENS,
        ),
    )
