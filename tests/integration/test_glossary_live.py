"""MT-045 AC-1 + AC-2: a name stays the same across two live-translated pages.

**Oracle-free, stochastic, with a negative control.** The synthetic pair in
`fixtures/translate/kakeru-*` (C-1) names 翔 - Shō / Sho / Shou / Kakeru, several
defensible readings - once per page, bare kanji, no furigana. Each run
translates page 1 with `EMPTY_CONTEXT` and page 2 either with the continuity
context built from page 1's result exactly as the pipeline builds it
(`context_on`, AC-3 pins the equality) or with `EMPTY_CONTEXT`. A run is
consistent iff the two name lines read the same (C-2's `reading`) and neither
reads `"?"`.

- **AC-1:** continuity ON consistent in at least 9 of `K` = 10 runs.
- **AC-2, the negative control:** continuity OFF inconsistent in at least 4 of
  10. If the OFF arm is >= 7/10 consistent the fixture is not exercising the
  mechanism and the test FAILS - the fixture changes, never the bar.

Both bars are asserted in the one live test, after the full printout: the
per-run table (each run printed as it completes), page 1's proposed terms
for 翔, both counts and the total cost.

**Marked `network`** (the whole file), so it runs only in the optional
`integration` gate (`pytest -m "gpu or network"`), never on CI. **Skips** when
`GEMINI_API_KEY` is unset; `google.genai` is imported inside the test body.
The live test spends about $0.22 per run (4 calls x K at MT-080's measured
~$0.0055 a page). Run it with the output visible:

    uv run pytest -q -s tests/integration/test_glossary_live.py -m network

The non-live tests here (fixture, `NAME_REGION`, `reading`) run under the same
command; to run them WITHOUT spending, deselect the live one:

    uv run pytest -q tests/integration/test_glossary_live.py -k "not keeps_its_reading"

**The helper is shared, not copied.** `context_on`, `reading`, `READINGS`,
`NAME_REGION` and the loader live in `tests/core/_glossary_live.py`, reached
through `_shared()` below as one module object per process; the mirror test
(`tests/core/test_glossary_live_mirror.py`) asserts the function this file
calls IS the one it checks against the pipeline.

**Timing.** No `pytest-timeout` in this project, so no budget to size. 40
sequential calls at thinking level MEDIUM; the SDK's own HTTP timeout applies
per call. MEASURED in RED (2026-10-13, dev machine, not CI): one call took
73 s and the next 10 s, so a full K = 10 run is somewhere between ~7 and ~50
minutes - run it in the background and read the per-run rows as they arrive.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest
from PIL import Image

from mangatl.domain.glossary import EMPTY_CONTEXT, PromptContext
from mangatl.domain.rates import price
from mangatl.domain.translation import TranslationResult

pytestmark = pytest.mark.network

_REPO = Path(__file__).resolve().parents[2]
_HELPER = _REPO / "tests" / "core" / "_glossary_live.py"
_HELPER_NAME = "_glossary_live"

#: PO-1 of MT-080 names exactly this variable; passed to the client explicitly.
_KEY_ENV = "GEMINI_API_KEY"

#: Runs per arm (PO-2). A module constant so a development smoke run can lower
#: it locally; the committed value, and the one the bars are written for, is 10.
K = 10
ON_CONSISTENT_AT_LEAST = 9  # AC-1
OFF_INCONSISTENT_AT_LEAST = 4  # AC-2


def _shared() -> ModuleType:
    """The one `_glossary_live` module of this process: the one pytest already
    imported from `tests/core` if it did, else that same file loaded by path
    under the same name and registered, so a later `import _glossary_live`
    gets this object too."""
    if _HELPER_NAME in sys.modules:
        return sys.modules[_HELPER_NAME]
    spec = importlib.util.spec_from_file_location(_HELPER_NAME, _HELPER)
    assert spec is not None and spec.loader is not None, _HELPER
    module = importlib.util.module_from_spec(spec)
    sys.modules[_HELPER_NAME] = module
    spec.loader.exec_module(module)
    return module


_helper = _shared()
context_on = _helper.context_on
reading = _helper.reading
READINGS: tuple[str, ...] = _helper.READINGS
NAME_REGION: dict[str, int] = _helper.NAME_REGION
NAME: str = _helper.NAME
load_ocr = _helper.load_ocr
PAGES: dict[str, Path] = _helper.PAGES


# -- non-live: the fixture (C-1) and the measure (C-2) -----------------------------


def test_the_kakeru_ocr_fixture_loads_two_pages_of_readable_regions_in_reading_order() -> None:
    ocr = load_ocr()

    assert sorted(ocr) == ["p1", "p2"]
    for page, regions in ocr.items():
        assert 3 <= len(regions) <= 5, f"{page}: C-1 asks for 3-5 bubbles, got {len(regions)}"
        assert not any(region.ocr_empty for region in regions), page
    assert ocr["p1"] != ocr["p2"], "the two pages carry the same dialogue"


def test_the_name_region_on_each_page_is_the_only_one_that_says_kakeru() -> None:
    ocr = load_ocr()

    for page, regions in ocr.items():
        holders = [index for index, region in enumerate(regions) if NAME in region.text]
        assert holders == [NAME_REGION[page]], (
            f"{page}: 翔 is in regions {holders}, NAME_REGION says {NAME_REGION[page]}"
        )


def test_the_name_sits_in_a_different_sentence_position_on_each_page() -> None:
    ocr = load_ocr()

    p1 = ocr["p1"][NAME_REGION["p1"]].text
    p2 = ocr["p2"][NAME_REGION["p2"]].text
    assert p1.rindex(NAME) != p2.rindex(NAME), (p1, p2)


def test_no_region_carries_romaji_that_would_hand_the_model_a_reading() -> None:
    ocr = load_ocr()

    for page, regions in ocr.items():
        for region in regions:
            assert not any("a" <= c.lower() <= "z" for c in region.text), (page, region.text)


def test_both_pages_are_white_portrait_pngs_the_adapter_will_not_resize() -> None:
    for page, path in PAGES.items():
        with Image.open(path) as image:
            width, height = image.size
            assert image.format == "PNG", page
            assert height > width, f"{page}: {image.size} is not portrait"
            assert max(width, height) <= 1568, f"{page}: {image.size} would be resized"
            assert image.convert("L").getpixel((width // 2, 2)) == 255, f"{page}: not white"
    assert PAGES["p1"].read_bytes() != PAGES["p2"].read_bytes(), "the same image twice"


def test_the_committed_pages_are_the_ones_the_readme_records() -> None:
    """The README's provenance is a claim about these bytes; a re-rendered or
    hand-edited page without an updated README fails here."""
    readme = (_REPO / "fixtures" / "translate" / "README.md").read_text(encoding="utf-8")
    for path in PAGES.values():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert f"`{digest}`" in readme, f"{path.name}: SHA-256 {digest} is not in the README"


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Shou, over here!", "Shou"),
        ("Sho, over here!", "Sho"),
        ("Shō, over here!", "Shō"),
        ("Hey, Shoh!", "Shoh"),
        ("Syo, wait!", "Syo"),
        ("Kakeru, this way!", "Kakeru"),
        ("Did Shou already go?", "Shou"),
        ("Shou-kun, wait!", "Shou"),
        ("Is Shō's bag here?", "Shō"),
        ("Kakeru, should we go?", "Kakeru"),
        ("Show me the way!", "?"),
        ("Should we go?", "?"),
        ("Over here!", "?"),
        ("shou, lower case is not a reading", "?"),
        ("", "?"),
    ],
)
def test_reading_extracts_the_romanisation_of_the_name_from_a_line(
    line: str, expected: str
) -> None:
    assert reading(line) == expected


def test_readings_are_ordered_so_a_short_form_cannot_pre_empt_a_long_one() -> None:
    sh = [r for r in READINGS if r.startswith("Sh")]
    assert sh.index("Sho") > sh.index("Shou")
    assert sh.index("Sho") > sh.index("Shoh")


# -- live: AC-1 + AC-2 ---------------------------------------------------------------


@dataclass(frozen=True)
class _Run:
    arm: str
    r1: str
    r2: str
    line1: str
    line2: str
    terms: tuple[str, ...]
    usage: tuple[str, ...]
    cost: Decimal

    @property
    def consistent(self) -> bool:
        return self.r1 == self.r2 != "?"


def test_live_a_name_keeps_its_reading_with_continuity_and_drifts_without_it() -> None:
    """AC-1 and AC-2 together: one price, both arms, one printout."""
    key = os.environ.get(_KEY_ENV)
    if not key:
        pytest.skip(f"{_KEY_ENV} is not set: AC-1/AC-2 are a live measurement")

    from google.genai import Client

    from mangatl.translate import gemini

    ocr = load_ocr()
    image = {page: path.read_bytes() for page, path in PAGES.items()}
    client = Client(api_key=key)
    runs: list[_Run] = []

    def call(page: str, context: PromptContext) -> tuple[TranslationResult, str, Decimal]:
        result = gemini.translate_page(client, image[page], ocr[page], context)
        assert result.call is not None, f"{page}: no call was made"
        record = price(result.call.model_id, result.usage)
        u = result.usage
        usage = f"{page} in={u.input_tokens} out={u.output_tokens} cr={u.cache_read_tokens}"
        return result, usage, record.cost.amount

    def run(arm: str) -> _Run:
        p1, u1, c1 = call("p1", EMPTY_CONTEXT)
        context = context_on(p1, ocr["p1"]) if arm == "on" else EMPTY_CONTEXT
        p2, u2, c2 = call("p2", context)
        line1 = p1.lines.get(NAME_REGION["p1"], "")
        line2 = p2.lines.get(NAME_REGION["p2"], "")
        terms = tuple(
            f"{t.term_ja}={t.term_en}({t.note})" for t in p1.proposed_terms if NAME in t.term_ja
        )
        return _Run(arm, reading(line1), reading(line2), line1, line2, terms, (u1, u2), c1 + c2)

    _say(f"\n--- MT-045 AC-1/AC-2: K = {K} per arm, alternated on/off ---")
    _say(f"{'#':>2} {'arm':<3} {'r1':<6} {'r2':<6} {'consistent':<10} p1 proposed 翔 terms")
    started = time.monotonic()
    try:
        for _ in range(K):
            for arm in ("on", "off"):  # alternated (C-3)
                runs.append(run(arm))
                _say_run(len(runs) - 1, runs[-1], time.monotonic() - started)
    finally:
        _say_totals(runs)

    on = [r for r in runs if r.arm == "on"]
    off = [r for r in runs if r.arm == "off"]
    on_consistent = sum(r.consistent for r in on)
    off_inconsistent = sum(not r.consistent for r in off)
    failures = []
    if on_consistent < ON_CONSISTENT_AT_LEAST:
        failures.append(
            f"AC-1: continuity ON consistent in {on_consistent}/{K},"
            f" needs >= {ON_CONSISTENT_AT_LEAST}"
        )
    if off_inconsistent < OFF_INCONSISTENT_AT_LEAST:
        failures.append(
            f"AC-2: continuity OFF inconsistent in only {off_inconsistent}/{K}, needs"
            f" >= {OFF_INCONSISTENT_AT_LEAST} - the fixture does not exercise the mechanism"
            " (change the fixture, never the bar)"
        )
    assert not failures, "; ".join(failures)


def _say(line: str) -> None:
    """Print `line` whatever the console's encoding: on Windows a piped stdout is
    cp1252, which cannot carry 翔, and a `UnicodeEncodeError` in the printout
    would throw away a paid run's record."""
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(line.encode(encoding, "backslashreplace").decode(encoding), flush=True)


def _say_run(index: int, r: _Run, elapsed: float) -> None:
    """One run's rows, printed as soon as it completes, so a run killed part way
    still leaves its record."""
    _say(
        f"{index:>2} {r.arm:<3} {r.r1:<6} {r.r2:<6} {('yes' if r.consistent else 'NO'):<10}"
        f" {', '.join(r.terms) or '-'}"
    )
    _say(f"{'':>14} p1[{NAME_REGION['p1']}]: {r.line1!r}")
    _say(f"{'':>14} p2[{NAME_REGION['p2']}]: {r.line2!r}")
    _say(f"{'':>14} {' | '.join(r.usage)} | cost ${r.cost} | t+{elapsed:.0f}s")


def _say_totals(runs: list[_Run]) -> None:
    on = [r for r in runs if r.arm == "on"]
    off = [r for r in runs if r.arm == "off"]
    _say(
        f"continuity ON : consistent {sum(r.consistent for r in on)}/{len(on)}"
        f" (AC-1 needs >= {ON_CONSISTENT_AT_LEAST} of {K})"
    )
    _say(
        f"continuity OFF: inconsistent {sum(not r.consistent for r in off)}/{len(off)}"
        f" (AC-2 needs >= {OFF_INCONSISTENT_AT_LEAST} of {K})"
    )
    _say(f"total cost: ${sum((r.cost for r in runs), Decimal(0))} over {2 * len(runs)} calls")
