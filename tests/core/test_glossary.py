"""`mangatl.domain.glossary`: the glossary and the rolling context as pure values.

MT-014 C-1. Covers **AC-3** in full (least-recently-**seen** eviction, the cap,
user entries last), the rendering half of **AC-1** and **AC-4**, and the pieces
every other criterion rests on: `estimate_tokens`, `merge`, `mark_seen`,
`render_block`, `render_rolling`.

**Every number here is settled and read out, never derived** (C-10):
`MAX_GLOSSARY_TOKENS = 400`, `MAX_ROLLING_TOKENS = 500`, their sum 900 is
`docs/wiki/cost-model.awk`'s `ROLLING`, and the one token counter is
`estimate_tokens(t) == ceil(len(t.encode("utf-8")) / 3)`. No test in this file
counts tokens any other way: the invariants below call the module's own
`estimate_tokens`, and `estimate_tokens` itself is pinned against literals.

**The AC-3 fixture discriminates, and that is the point of it** (C-10, DV-2).
`_DISCRIMINATING` holds an entry that is old by *addition* but recent by
*sighting* (`first_seen_page=0, last_seen_page=17`) beside one that is newer by
addition but stale (`first_seen_page=5, last_seen_page=5`), at a cap where
exactly one line has to go and either would do. Least-recently-seen drops the
second; least-recently-added would drop the first. The two rules give two
different strings, and the test asserts one of them exactly.

MEASURED IN RED, outside pytest, with a 20-line reference renderer in a plain
`uv run python` (the module under test does not exist yet, so nothing in this
file has run): the discriminating block is 38 tokens whole, 30 without either
contested line, so at a cap of 30 the correct rule returns
`さくら + 東京` and the least-recently-added rule returns `東京 + けんじ`. The
full table is in the story's `## Handoff: RED -> GREEN`; GREEN confirms it.

`coverage-core` holds `src/mangatl/domain/**` at **100 % with branch
coverage**, so every arm the contract names has a test here rather than an
incidental one from a stage test.

**Timing.** No `pytest-timeout` in this project and no per-test timeout, so
there is no budget in this file to size. The largest loop renders an
8-entry block at 75 caps; everything is in memory.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Sequence
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
    mark_seen,
    merge,
    render_block,
    render_rolling,
)

#: C-1's two headers, verbatim.
_HEADER = "Glossary - use these renderings exactly:"
_ROLLING_HEADER = "Previous page, in reading order:"

_COST_MODEL = Path(__file__).resolve().parents[2] / "docs" / "wiki" / "cost-model.awk"


def _entry(
    term_ja: str,
    term_en: str,
    note: str = "",
    first: int = 0,
    last: int | None = None,
    source: str = "model",
) -> GlossaryEntry:
    return GlossaryEntry(
        term_ja=term_ja,
        term_en=term_en,
        note=note,
        first_seen_page=first,
        last_seen_page=first if last is None else last,
        source=source,  # type: ignore[arg-type]
    )


def _names(block: str) -> list[str]:
    """The `term_ja` of every entry line in a rendered block, in block order."""
    if block == "":
        return []
    header, *lines = block.split("\n")
    assert header == _HEADER, f"the block does not start with the header: {block!r}"
    return [line.split(" = ")[0] for line in lines]


# -- the constants, and the one counter ---------------------------------------


def test_the_two_caps_are_the_settled_400_and_500_and_sum_to_the_cost_models_900() -> None:
    """C-1's numbers, read out rather than derived. The sum is checked against
    `cost-model.awk`'s `ROLLING` itself, so the day someone retunes one cap
    without the other the test names the budget it just broke - the $1.14
    chapter estimate rests on 900 (`stack.md` §5/O4, PO-3)."""
    match = re.search(r"^\s*ROLLING\s*=\s*(\d+)", _COST_MODEL.read_text(encoding="utf-8"), re.M)
    assert match is not None, f"no ROLLING in {_COST_MODEL}"

    assert MAX_GLOSSARY_TOKENS == 400
    assert MAX_ROLLING_TOKENS == 500
    assert MAX_GLOSSARY_TOKENS + MAX_ROLLING_TOKENS == int(match.group(1)) == 900


@pytest.mark.parametrize(
    ("text", "tokens"),
    [
        pytest.param("", 0, id="empty-is-zero"),
        pytest.param("a", 1, id="one-byte-rounds-up"),
        pytest.param("abc", 1, id="three-bytes-is-one"),
        pytest.param("abcd", 2, id="four-bytes-is-two"),
        pytest.param("abcdef", 2, id="six-bytes-is-two"),
        pytest.param("さ", 1, id="one-kana-is-three-bytes"),
        pytest.param("さa", 2, id="kana-plus-ascii-is-four-bytes"),
        pytest.param("さくら", 3, id="three-kana"),
        pytest.param(_HEADER, 14, id="the-glossary-header-is-40-bytes"),
    ],
)
def test_the_token_estimate_is_the_ceiling_of_utf8_bytes_over_three(text: str, tokens: int) -> None:
    """C-1: `ceil(len(text.encode("utf-8")) / 3)`, the one counter. Measured
    on **bytes**, not characters - a character count makes さくら one token and
    under-counts Japanese threefold, which is the unsafe direction for a cap -
    and rounded **up**, the safe one."""
    assert estimate_tokens(text) == tokens


# -- the value types ------------------------------------------------------------


def test_the_value_types_are_frozen_with_the_fields_c1_names_in_order() -> None:
    """C-1's shapes. Field **order** is pinned because C-1 itself constructs
    `GlossaryEntry(term_ja, term_en, note, page, page, "model")` positionally,
    and `PromptContext("", "")` likewise."""
    assert [f.name for f in dataclasses.fields(ProposedTerm)] == ["term_ja", "term_en", "note"]
    assert [f.name for f in dataclasses.fields(GlossaryEntry)] == [
        "term_ja",
        "term_en",
        "note",
        "first_seen_page",
        "last_seen_page",
        "source",
    ]
    assert [f.name for f in dataclasses.fields(PromptContext)] == [
        "glossary_block",
        "rolling_block",
    ]
    with pytest.raises(dataclasses.FrozenInstanceError):
        _entry("さくら", "Sakura").term_en = "Sakura-chan"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        ProposedTerm("さくら", "Sakura", "name").term_en = "x"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        EMPTY_CONTEXT.glossary_block = "x"  # type: ignore[misc]


def test_the_empty_context_is_two_empty_blocks() -> None:
    """C-1: `EMPTY_CONTEXT = PromptContext("", "")` - page 1's context (AC-5),
    compared by value in `build_request` (C-3)."""
    assert PromptContext("", "") == EMPTY_CONTEXT
    assert EMPTY_CONTEXT.glossary_block == ""
    assert EMPTY_CONTEXT.rolling_block == ""


# -- merge (C-1) ---------------------------------------------------------------


def test_a_new_term_is_appended_as_a_model_entry_first_and_last_seen_on_this_page() -> None:
    """C-1's first bullet, and **AC-1**'s domain half: page 0 proposes
    "Sakura" for さくら, and the chapter now has that pairing."""
    merged = merge([], [ProposedTerm("さくら", "Sakura", "name")], 0)

    assert merged == [GlossaryEntry("さくら", "Sakura", "name", 0, 0, "model")]
    assert type(merged) is list


def test_a_known_term_keeps_its_rendering_and_only_its_last_sighting_moves() -> None:
    """C-1's second bullet, and the whole story in one assertion: page 17's
    model saying "Sakura-chan" is exactly the inconsistency MT-014 ends, so the
    chapter keeps "Sakura". `last_seen_page` moves to 17; nothing else does."""
    existing = [GlossaryEntry("さくら", "Sakura", "name", 3, 9, "model")]

    merged = merge(existing, [ProposedTerm("さくら", "Sakura-chan", "honorific")], 17)

    assert merged == [GlossaryEntry("さくら", "Sakura", "name", 3, 17, "model")]


def test_a_users_entry_is_kept_whatever_the_model_proposes_later() -> None:
    """C-1: "keeps its `term_en`, `note`, `first_seen_page` and `source`
    **whatever its source**" - and the human's choice outranks the machine's
    (AC-2), so a `"user"` entry stays `"user"` and keeps the user's words."""
    existing = [GlossaryEntry("さくら", "Sakura-chan", "name", 0, 2, "user")]

    merged = merge(existing, [ProposedTerm("さくら", "Sakura", "name")], 4)

    assert merged == [GlossaryEntry("さくら", "Sakura-chan", "name", 0, 4, "user")]


def test_re_proposing_a_term_on_an_earlier_page_does_not_move_its_sighting_backwards() -> None:
    """C-1: `max(existing, page)`. A re-run of page 2 after page 9 has been
    translated must not make a character look stale."""
    existing = [GlossaryEntry("さくら", "Sakura", "name", 0, 9, "model")]

    assert merge(existing, [ProposedTerm("さくら", "Sakura", "name")], 2) == existing


@pytest.mark.parametrize(
    ("term_ja", "term_en"),
    [
        pytest.param("", "Sakura", id="empty-term_ja"),
        pytest.param("さくら", "", id="empty-term_en"),
        pytest.param("  ", "Sakura", id="blank-term_ja"),
        pytest.param("さくら", " \t", id="blank-term_en"),
    ],
)
def test_a_proposal_with_an_empty_side_is_dropped(term_ja: str, term_en: str) -> None:
    """C-1's third bullet, after `.strip()`. An empty `term_ja` is a substring
    of **every** source text, so it would be "seen" on every page and could
    never be evicted; an empty `term_en` is an instruction to render a name as
    nothing. The good proposal beside it still lands."""
    merged = merge(
        [],
        [ProposedTerm(term_ja, term_en, "name"), ProposedTerm("けんじ", "Kenji", "name")],
        1,
    )

    assert merged == [GlossaryEntry("けんじ", "Kenji", "name", 1, 1, "model")]


def test_two_proposals_for_one_term_in_one_batch_keep_the_first() -> None:
    """C-1's fourth bullet: the first wins, so one response cannot introduce a
    name twice with two renderings and leave which one survives to dict order."""
    merged = merge(
        [],
        [
            ProposedTerm("さくら", "Sakura", "name"),
            ProposedTerm("さくら", "Sakura-chan", "honorific"),
        ],
        0,
    )

    assert merged == [GlossaryEntry("さくら", "Sakura", "name", 0, 0, "model")]


def test_existing_order_is_kept_and_new_entries_follow_in_proposal_order() -> None:
    """C-1's last bullet. The existing entries are deliberately **not** in any
    sorted order, so an implementation that re-sorted them is caught; the two
    new ones arrive in an order that is not alphabetical either."""
    existing = [
        GlossaryEntry("東京", "Tokyo", "place", 4, 4, "model"),
        GlossaryEntry("あ組", "Class A", "", 1, 2, "model"),
    ]

    merged = merge(
        existing,
        [
            ProposedTerm("ゆき", "Yuki", "name"),
            ProposedTerm("あ組", "Group A", ""),
            ProposedTerm("けんじ", "Kenji", "name"),
        ],
        6,
    )

    assert merged == [
        GlossaryEntry("東京", "Tokyo", "place", 4, 4, "model"),
        GlossaryEntry("あ組", "Class A", "", 1, 6, "model"),
        GlossaryEntry("ゆき", "Yuki", "name", 6, 6, "model"),
        GlossaryEntry("けんじ", "Kenji", "name", 6, 6, "model"),
    ]


def test_merging_nothing_changes_nothing_and_merging_twice_is_merging_once() -> None:
    """The zero case, and C-9's reason the glossary write may precede
    `write_proposed`: "a crash after the glossary and before the proposals
    re-translates the page, and `merge` is idempotent"."""
    existing = [GlossaryEntry("さくら", "Sakura", "name", 0, 3, "model")]
    proposed = [ProposedTerm("けんじ", "Kenji", "name"), ProposedTerm("さくら", "S", "")]

    assert merge(existing, [], 5) == existing
    once = merge(existing, proposed, 5)
    assert merge(once, proposed, 5) == once


# -- mark_seen (C-1) -----------------------------------------------------------


def test_an_entry_whose_term_appears_in_the_pages_ocr_is_seen_on_that_page() -> None:
    """C-1's `mark_seen`: a substring of **any** of the page's source texts -
    here the second of two, inside a longer line - moves `last_seen_page` and
    nothing else. This is what makes a character who is on every page "recent"
    when the model does not bother to re-propose them."""
    entries = [
        GlossaryEntry("さくら", "Sakura", "name", 0, 1, "user"),
        GlossaryEntry("けんじ", "Kenji", "name", 0, 1, "model"),
    ]

    seen = mark_seen(entries, ["どうして君がここに", "さくらちゃん、待って!"], 8)

    assert seen == [
        GlossaryEntry("さくら", "Sakura", "name", 0, 8, "user"),
        GlossaryEntry("けんじ", "Kenji", "name", 0, 1, "model"),
    ]
    assert type(seen) is list


def test_a_sighting_on_an_earlier_page_does_not_move_last_seen_backwards() -> None:
    entries = [GlossaryEntry("さくら", "Sakura", "name", 0, 9, "model")]

    assert mark_seen(entries, ["さくら!"], 4) == entries


@pytest.mark.parametrize(
    "source_texts",
    [pytest.param([], id="no-regions"), pytest.param(["", ""], id="all-empty")],
)
def test_a_page_with_no_text_sees_nobody(source_texts: Sequence[str]) -> None:
    """The zero of zero-one-many, and C-9's wordless page: `mark_seen` over an
    all-empty page changes nothing."""
    entries = [GlossaryEntry("さくら", "Sakura", "name", 0, 1, "model")]

    assert mark_seen(entries, source_texts, 6) == entries


# -- render_block (C-1): the exact format ---------------------------------------


def test_the_block_is_the_header_then_one_line_per_entry_in_first_seen_order() -> None:
    """C-1's format, byte for byte: header, one `term_ja = term_en` line per
    entry with ` (note)` only when the note is non-empty, `\\n`-joined, no
    trailing newline, ordered by `(first_seen_page, term_ja)` - whatever order
    the entries arrive in. 先輩 and 醜鬼 tie on page 2 and sort by `term_ja`."""
    entries = [
        _entry("けんじ", "Kenji", "name", first=5),
        _entry("醜鬼", "Ugly Ogre", "", first=2, last=9),
        _entry("さくら", "Sakura", "name", first=0, last=17),
        _entry("先輩", "senpai", "honorific", first=2, last=3, source="user"),
    ]

    assert render_block(entries, MAX_GLOSSARY_TOKENS) == (
        "Glossary - use these renderings exactly:\n"
        "さくら = Sakura (name)\n"
        "先輩 = senpai (honorific)\n"
        "醜鬼 = Ugly Ogre\n"
        "けんじ = Kenji (name)"
    )


def test_no_entries_render_as_nothing_rather_than_as_a_bare_header() -> None:
    """C-1: `""` for no entries - and AC-5's page 1 depends on it, since a
    non-empty glossary block is what adds a text block to the request."""
    assert render_block([], MAX_GLOSSARY_TOKENS) == ""


# -- AC-3: the cap, and least-recently-SEEN first -------------------------------

#: The discriminating fixture (C-10). さくら is the oldest by addition and the
#: most recent but one by sighting; けんじ is newer by addition and stale.
_DISCRIMINATING = [
    _entry("さくら", "Sakura", "name", first=0, last=17),
    _entry("けんじ", "Kenji", "name", first=5, last=5),
    _entry("東京", "Tokyo", "place", first=2, last=20),
]

#: The cap at which exactly one of さくら and けんじ must go and either would
#: do: the whole block is 38 tokens and it is 30 without either of them
#: (MEASURED in RED; see the handoff). Asserted below rather than trusted.
_ONE_MUST_GO = 30


def test_least_recently_seen_goes_first_and_not_least_recently_added() -> None:
    """**AC-3**'s ordering, on a fixture where the two rules disagree.

    Least-recently-added (`first_seen_page`) would drop さくら - on the page
    since page 0, on page 17 too - and keep けんじ, last seen on page 5. That is
    the wrong character to forget. DV-2 is this test going red when the sort
    key's `last_seen_page` is replaced with `first_seen_page`.
    """
    without_kenji = (
        "Glossary - use these renderings exactly:\nさくら = Sakura (name)\n東京 = Tokyo (place)"
    )
    without_sakura = (
        "Glossary - use these renderings exactly:\n東京 = Tokyo (place)\nけんじ = Kenji (name)"
    )
    # The fixture's own precondition: one line must go, and either would fit.
    assert estimate_tokens(render_block(_DISCRIMINATING, 10_000)) > _ONE_MUST_GO
    assert estimate_tokens(without_kenji) <= _ONE_MUST_GO
    assert estimate_tokens(without_sakura) <= _ONE_MUST_GO

    rendered = render_block(_DISCRIMINATING, _ONE_MUST_GO)

    assert rendered != without_sakura, (
        "the entry dropped was the least recently ADDED (さくら, first seen on page 0"
        " but last seen on page 17), not the least recently SEEN (けんじ, page 5)"
    )
    assert rendered == without_kenji


#: The many-entry fixture: six model entries and two user ones, with ties on
#: `last_seen_page` (four at 5) broken by `first_seen_page` and then by
#: `term_ja` (あ組 and いぬ tie on both), and a user entry (先輩) that is the
#: stalest thing in the chapter by every measure.
_MANY = [
    _entry("さくら", "Sakura", "name", first=0, last=17),
    _entry("けんじ", "Kenji", "name", first=5, last=5),
    _entry("東京", "Tokyo", "place", first=2, last=20),
    _entry("醜鬼", "Ugly Ogre", "", first=1, last=5),
    _entry("あ組", "Class A", "", first=3, last=5),
    _entry("いぬ", "Dog", "", first=3, last=5),
    _entry("先輩", "senpai", "honorific", first=0, last=0, source="user"),
    _entry("ゆき", "Yuki-chan", "name", first=4, last=19, source="user"),
]

#: C-1's eviction order for `_MANY`, first removed first, written out by hand
#: from `(source == "user", last_seen_page, first_seen_page, term_ja)`.
_MANY_EVICTION_ORDER = ["醜鬼", "あ組", "いぬ", "けんじ", "さくら", "東京", "先輩", "ゆき"]

_MANY_USERS = {"先輩", "ゆき"}


def _full_many() -> str:
    return render_block(_MANY, 10_000)


def test_at_or_above_its_own_size_the_block_is_rendered_whole() -> None:
    """The boundary from above: a cap equal to the block's own estimate is not
    exceeded, so nothing is dropped. An off-by-one (`>=` for `>`) drops an
    entry here."""
    full = _full_many()

    assert _names(full) == ["さくら", "先輩", "醜鬼", "東京", "あ組", "いぬ", "ゆき", "けんじ"]
    assert render_block(_MANY, estimate_tokens(full)) == full


def test_one_token_under_its_size_drops_exactly_the_first_entry_in_eviction_order() -> None:
    """The boundary from below: one token under, one entry - 醜鬼, which ties
    three others on `last_seen_page` 5 and wins the tie on `first_seen_page`."""
    rendered = render_block(_MANY, estimate_tokens(_full_many()) - 1)

    assert _names(rendered) == ["さくら", "先輩", "東京", "あ組", "いぬ", "ゆき", "けんじ"]


def test_the_block_never_exceeds_the_cap_and_is_never_a_bare_header_at_any_cap() -> None:
    """**AC-3**'s "the block never exceeds the cap", over **every** cap from 0
    to past the block's own size - not one hand-picked value - with the
    violations collected and asserted once. DV-1 is this test going red when
    `render_block` ignores `max_tokens`.

    Two more things hold at every cap, because C-1 says how the dropping
    happens and not only that it does:

    * what survives is a **suffix of the eviction order** - entries are removed
      one at a time, first-removed first, so a later entry is never dropped
      while an earlier one is kept. That also means a small, stale entry is not
      kept in place of a larger, fresher one;
    * the dropping stops **as soon as** it fits - with one more entry (the
      last one removed) the block would have been over the cap.
    """
    full = _full_many()
    violations: list[str] = []
    for cap in range(estimate_tokens(full) + 3):
        rendered = render_block(_MANY, cap)
        kept = _names(rendered)
        if estimate_tokens(rendered) > cap:
            violations.append(f"cap {cap}: {estimate_tokens(rendered)} tokens")
        if rendered.strip() == _HEADER:
            violations.append(f"cap {cap}: a bare header")
        dropped = len(_MANY) - len(kept)
        if set(kept) != set(_MANY_EVICTION_ORDER[dropped:]):
            violations.append(f"cap {cap}: kept {kept}, not a suffix of the eviction order")
        elif dropped > 0:
            one_more = [e for e in _MANY if e.term_ja in _MANY_EVICTION_ORDER[dropped - 1 :]]
            if estimate_tokens(render_block(one_more, 10_000)) <= cap:
                violations.append(f"cap {cap}: dropped {dropped} entries where fewer fitted")

    assert violations == []


def test_user_entries_outlive_every_model_entry_and_the_cap_still_wins() -> None:
    """**PO-3**: the cap wins over "user entries are never evicted". At a cap
    that fits one line, every model entry is gone - including 東京, seen on
    page 20 - and so is the user's own 先輩, because user entries are evicted
    too, least-recently-seen first, once no model entry is left. ゆき survives.
    """
    one_line = "Glossary - use these renderings exactly:\nゆき = Yuki-chan (name)"
    assert estimate_tokens(one_line) == 22

    assert render_block(_MANY, 22) == one_line
    for cap in range(estimate_tokens(_full_many()) + 1):
        kept = set(_names(render_block(_MANY, cap)))
        assert not (kept - _MANY_USERS) or kept >= _MANY_USERS, (
            f"cap {cap}: a model entry {sorted(kept - _MANY_USERS)} outlived a user entry"
        )


def test_a_cap_below_any_single_line_renders_nothing_and_not_a_header() -> None:
    """C-1: "If no entry fits, the result is `""`, never a header alone". The
    smallest one-entry block in `_MANY` is いぬ's at 18 tokens, so 17 fits
    nothing whichever rule is applied; and a cap of 0 is the degenerate case."""
    assert estimate_tokens(render_block([_entry("いぬ", "Dog")], 10_000)) == 18

    assert render_block(_MANY, 17) == ""
    assert render_block(_MANY, 0) == ""
    assert render_block([_entry("いぬ", "Dog")], 17) == ""


def test_the_real_cap_holds_on_a_chapters_worth_of_names() -> None:
    """**AC-3** at `MAX_GLOSSARY_TOKENS` itself: sixty model entries, far over
    400 tokens, render to a block at or under 400, and the entry seen most
    recently is still in it."""
    entries = [
        _entry(f"名前{index:02d}", f"Name Number {index:02d}", "name", first=index, last=index)
        for index in range(60)
    ]
    assert estimate_tokens(render_block(entries, 10_000)) > MAX_GLOSSARY_TOKENS

    rendered = render_block(entries, MAX_GLOSSARY_TOKENS)

    assert estimate_tokens(rendered) <= MAX_GLOSSARY_TOKENS
    assert "名前59 = Name Number 59 (name)" in rendered
    assert "名前00 = " not in rendered


def test_eviction_is_render_only_and_leaves_the_entries_alone() -> None:
    """C-1: "Eviction is **render-only**: the store keeps every entry". The
    input sequence is not mutated, so the caller can still upsert all of it."""
    entries = list(_MANY)

    render_block(entries, 22)

    assert entries == _MANY


# -- render_rolling (C-1): AC-4's cap ---------------------------------------------

_LINES = ["Wait up, Sakura!", "Where are you going?", "...Home."]


def test_the_rolling_block_is_the_header_then_the_lines_in_reading_order() -> None:
    """C-1's rolling format, byte for byte, with nothing dropped at a cap equal
    to its own size (27 tokens, MEASURED in RED)."""
    expected = "Previous page, in reading order:\nWait up, Sakura!\nWhere are you going?\n...Home."
    assert estimate_tokens(expected) == 27

    assert render_rolling(_LINES, MAX_ROLLING_TOKENS) == expected
    assert render_rolling(_LINES, 27) == expected


def test_no_previous_lines_render_as_nothing() -> None:
    assert render_rolling([], MAX_ROLLING_TOKENS) == ""


def test_over_the_cap_lines_are_dropped_from_the_start_not_the_end() -> None:
    """**AC-4**'s cap, and C-1's direction: the **end** of the previous page is
    what the next page continues, so the first line goes first. One token under
    the whole block drops "Wait up, Sakura!" and keeps the other two; a drop
    from the end would keep it and lose "...Home."."""
    assert render_rolling(_LINES, 26) == (
        "Previous page, in reading order:\nWhere are you going?\n...Home."
    )
    assert render_rolling(_LINES, 20) == "Previous page, in reading order:\n...Home."


def test_when_not_even_the_last_line_fits_the_rolling_block_is_empty() -> None:
    """C-1: `""` if no line fits - never a header alone. The header and the
    last line together are 14 tokens, so 13 fits nothing."""
    assert render_rolling(_LINES, 14) == "Previous page, in reading order:\n...Home."
    assert render_rolling(_LINES, 13) == ""
    assert render_rolling(_LINES, 0) == ""


def test_the_rolling_block_never_exceeds_its_cap_and_keeps_a_suffix_at_every_cap() -> None:
    """**AC-4**'s "capped at `MAX_ROLLING_TOKENS`" as an invariant over every
    cap, collected and asserted once: never over, never a bare header, always
    a suffix of the lines, and never shorter than it had to be."""
    violations: list[str] = []
    for cap in range(40):
        rendered = render_rolling(_LINES, cap)
        if estimate_tokens(rendered) > cap:
            violations.append(f"cap {cap}: {estimate_tokens(rendered)} tokens")
        if rendered == "":
            kept: list[str] = []
        else:
            header, *kept = rendered.split("\n")
            if header != _ROLLING_HEADER or not kept:
                violations.append(f"cap {cap}: {rendered!r}")
        if kept != _LINES[len(_LINES) - len(kept) :]:
            violations.append(f"cap {cap}: kept {kept}, not a suffix of the page")
        if len(kept) < len(_LINES):
            one_more = "\n".join([_ROLLING_HEADER, *_LINES[len(_LINES) - len(kept) - 1 :]])
            if estimate_tokens(one_more) <= cap:
                violations.append(f"cap {cap}: dropped a line that fitted")

    assert violations == []


def test_the_real_rolling_cap_holds_on_a_long_previous_page() -> None:
    """**AC-4** at `MAX_ROLLING_TOKENS` itself: sixty lines, 1,131 tokens whole,
    come down to 26 lines and 496 tokens (MEASURED in RED) - the last 26."""
    lines = [
        f"Line {index:02d}: the rolling context keeps the end of the page." for index in range(60)
    ]
    assert estimate_tokens("\n".join([_ROLLING_HEADER, *lines])) == 1131

    rendered = render_rolling(lines, MAX_ROLLING_TOKENS)

    assert estimate_tokens(rendered) <= MAX_ROLLING_TOKENS
    assert rendered == "\n".join([_ROLLING_HEADER, *lines[34:]])
