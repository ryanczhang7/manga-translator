"""`mangatl.ocr.decode`: token ids to the Japanese string a human would read.

Covers **AC-3** in full: the model's special tokens stripped, the half-width
forms MT-002 E5 measured normalised to full-width, and no trailing whitespace.

**C-7 is a measurement, not a preference, and it is pinned here by assertion
rather than by comment.** MT-002 E5 Test 1 scored the export against the upstream
author's own ground-truth set twice: **6/12 raw** and **10/12** after the
upstream project's own `post_process`. All four recovered files differed
*entirely* in half-width versus full-width punctuation and digits - `!!!` against
`！！！`, `?` against `？`, `LINK!私達7人` against `ＬＩＮＫ！私達７人`. RED
reproduced both numbers on this machine (6/12 and 10/12, character accuracy
0.9113 and 0.9743) before writing this file. Omitting the step makes the model
look 33 points worse than it is, and makes `OCR_MIN_ACCURACY` absorb a known,
fixable defect - which is how a threshold stops being a threshold.

**The vocabulary here is a fake, and a small one.** The real `vocab.txt` is 6144
lines and belongs to `tests/integration/`; what AC-3 is about is the
transformation, and a hand-built mapping is the only way to state the expected
string as a literal rather than as a second implementation of the decoder.

**Two facts about the real vocabulary that shape these tests**, both measured in
RED by reading `spikes/MT-002/models/manga-ocr-base/vocab.txt`:

* ids 0-4 are `[PAD]`, `[UNK]`, `[CLS]`, `[SEP]`, `[MASK]` - so `BOS_TOKEN_ID`
  is `[CLS]` and `EOS_TOKEN_ID` is `[SEP]`, and both are special *tokens* as well
  as control ids;
* **not one of the 6144 entries begins with `##`.** The decoder is
  `cl-tohoku/bert-base-japanese-char-v2`, a character-level model, so there are
  no word-piece continuations to strip. `spikes/MT-002/ocr.py` carried a
  `t[2:] if t.startswith("##")` branch and RED measured it to be dead code
  against this vocabulary. GREEN should not reproduce it: an unreachable branch
  is a hole in the `coverage` gate and a claim about the vocabulary that nothing
  checks.

**Timing.** There is no `pytest-timeout` in this project and no per-test timeout
exists, so there is no budget in this file to size; if a later story adds one,
every test and hook here needs one. Nothing here is slower than a string join.
"""

# ruff: noqa: RUF001, RUF002
#
# RUF001/2/3 warn that a full-width character "looks like" its ASCII twin and may
# have been typed by accident. In this one file that rule is exactly inverted:
# telling those two apart IS the subject. C-7 is the step that maps one onto the
# other, and MT-002 E5 measured that omitting it costs 6/12 against 10/12 exact
# matches. Every U+FF01, U+FF1F, U+FF0E and U+FF2C below is deliberate, and
# spelling them as escapes would make the expected strings unreadable at exactly
# the place a reader needs to see them. Scoped to this file and to these three
# rules; nothing else here is suppressed.

from __future__ import annotations

from collections.abc import Mapping

import pytest

from mangatl.ocr.decode import SPECIAL_TOKENS, decode

# -- the fake vocabulary -------------------------------------------------------
#
# Ids 0-4 match the real `vocab.txt` exactly, so a decoder that hard-codes the
# real special ids and one that looks them up in `SPECIAL_TOKENS` both behave the
# same here - which is deliberate: AC-3 is about the output string, and C-1 makes
# `SPECIAL_TOKENS` a set of *strings*, so the lookup is by token text.
#
# Everything from 10 upwards is arbitrary and is chosen to exercise one clause of
# C-7 each.

_PAD, _UNK, _CLS, _SEP, _MASK = 0, 1, 2, 3, 4

_VOCAB: Mapping[int, str] = {
    _PAD: "[PAD]",
    _UNK: "[UNK]",
    _CLS: "[CLS]",
    _SEP: "[SEP]",
    _MASK: "[MASK]",
    10: "ゴ",
    11: "メ",
    12: "ン",
    13: "!",  # half-width, E5's `!!!` case
    14: "?",  # half-width, E5's `?` case
    15: "7",  # half-width digit, E5's `私達7人` case
    16: "私",
    17: "達",
    18: "人",
    19: "L",  # half-width Latin, E5's `LINK!` case
    20: "I",
    21: "N",
    22: "K",
    23: "…",  # a real ellipsis character, U+2026
    24: "・",  # KATAKANA MIDDLE DOT, which manga uses as an ellipsis dot
    25: " ",  # an ASCII space
    26: "な",
    27: "る",
    28: "ほ",
    29: "ど",
    30: "！",  # ALREADY full-width: normalising twice must not move it again
    31: "７",  # already full-width digit
}


# -- the special tokens --------------------------------------------------------


def test_the_four_special_tokens_the_export_actually_emits_are_all_declared() -> None:
    """C-1's `SPECIAL_TOKENS`, against the real vocabulary's first four entries.

    `[CLS]` and `[SEP]` are the sequence delimiters (`generation_config.json`:
    `decoder_start_token_id: 2`, `eos_token_id: 3`), `[PAD]` is id 0 and `[UNK]`
    is id 1 and the graph can emit either. `spikes/MT-002/ocr.py` stripped
    exactly these four.

    A **subset** assertion, not equality: whether `[MASK]` and the 2000-odd
    `<unusedN>` entries are also listed is the implementer's choice, and this
    story has no evidence either way about what the graph does with them. What it
    may not do is leave one of these four in the user's text.
    """
    assert {"[PAD]", "[UNK]", "[CLS]", "[SEP]"} <= set(SPECIAL_TOKENS)
    assert isinstance(SPECIAL_TOKENS, frozenset)


# -- AC-3: the decoded string --------------------------------------------------


def test_a_known_token_sequence_decodes_to_the_expected_japanese_string() -> None:
    """AC-3's whole sentence in one assertion, on E5's own example.

    `ＬＩＮＫ！私達７人` is the upstream ground truth for `07.jpg`; the raw decoder
    produced `LINK!私達7人`, and that single file is one of the four the
    normalisation recovered. The sequence is wrapped in `[CLS]` and `[SEP]`
    exactly as the graph emits it, so stripping is exercised at both ends at once.
    """
    tokens = [_CLS, 19, 20, 21, 22, 13, 16, 17, 15, 18, _SEP]

    assert decode(tokens, _VOCAB) == "ＬＩＮＫ！私達７人"


def test_the_half_width_forms_the_audit_measured_all_become_full_width() -> None:
    """AC-3's normalisation clause, one row per form MT-002 E5 named.

    Accumulated and asserted once rather than asserted per case, so a failure
    names **every** form that is wrong instead of stopping at the first - which
    matters here because the three clauses of C-7 (ASCII, digits, ellipsis) are
    independent and an implementation can easily get one and miss another.
    """
    cases: tuple[tuple[str, list[int], str], ...] = (
        ("E5: !!! -> ！！！", [_CLS, 13, 13, 13, _SEP], "！！！"),
        ("E5: ? -> ？", [_CLS, 14, _SEP], "？"),
        ("E5: digit 7 -> ７", [_CLS, 15, _SEP], "７"),
        ("E5: LINK -> ＬＩＮＫ", [_CLS, 19, 20, 21, 22, _SEP], "ＬＩＮＫ"),
        ("already full-width ！ is unchanged", [_CLS, 30, _SEP], "！"),
        ("already full-width ７ is unchanged", [_CLS, 31, _SEP], "７"),
        ("Japanese is untouched", [_CLS, 10, 11, 12, _SEP], "ゴメン"),
    )

    wrong = [
        f"{name}: got {decode(tokens, _VOCAB)!r}, want {expected!r}"
        for name, tokens, expected in cases
        if decode(tokens, _VOCAB) != expected
    ]

    assert wrong == [], f"{len(wrong)} of {len(cases)} normalisation cases are wrong: {wrong}"


def test_a_string_that_is_already_full_width_is_left_exactly_where_it_is() -> None:
    """C-7 as an idempotence property, which is the cheapest way to catch a
    normalisation implemented as an **unguarded** codepoint offset.

    A hand-rolled `chr(ord(c) + 0xFEE0)` applied without a range check turns
    `！` (U+FF01) into U+1FEE1, which is not a character anybody typed - and the
    result still *looks* right on every input that was half-width to begin with,
    so the sweep above passes and only this fails. C-7 permits a hand-rolled
    offset only if it is proved equivalent to `jaconv.h2z(ascii=True,
    digit=True)` over the ASCII and digit ranges; the two tests together are that
    proof, in both directions.
    """
    fullwidth = [chr(c) for c in range(0xFF01, 0xFF5F)]
    vocab = dict(_VOCAB) | {2000 + index: char for index, char in enumerate(fullwidth)}

    moved = [
        (char, decode([_CLS, 2000 + index, _SEP], vocab))
        for index, char in enumerate(fullwidth)
        if decode([_CLS, 2000 + index, _SEP], vocab) != char
    ]

    assert moved == [], f"{len(moved)} already-full-width characters were widened again: {moved}"


def test_every_printable_ascii_codepoint_maps_to_its_own_full_width_twin() -> None:
    """C-7's proof obligation in full, over the whole range it names.

    `jaconv.h2z(ascii=True, digit=True)` maps U+0021 to U+007E onto U+FF01 to
    U+FF5E, a constant offset of 0xFEE0. Whether GREEN takes the dependency or
    hand-rolls the offset, C-7 requires the equivalence to be *proved over the
    range* rather than spot-checked, and 94 codepoints is cheap enough to do
    exhaustively.

    The three characters C-7 treats specially are excluded here and asserted
    separately: `.` participates in the ellipsis collapse, and the space is
    stripped rather than widened.
    """
    excluded = {".", " "}
    codepoints = [c for c in range(0x21, 0x7F) if chr(c) not in excluded]
    vocab = dict(_VOCAB) | {1000 + index: chr(c) for index, c in enumerate(codepoints)}

    wrong = [
        (chr(c), decode([_CLS, 1000 + index, _SEP], vocab), chr(c + 0xFEE0))
        for index, c in enumerate(codepoints)
        if decode([_CLS, 1000 + index, _SEP], vocab) != chr(c + 0xFEE0)
    ]

    assert wrong == [], f"{len(wrong)} of {len(codepoints)} ASCII codepoints do not widen: {wrong}"


def test_an_ellipsis_becomes_the_dots_the_upstream_ground_truth_is_written_with() -> None:
    """AC-3's ellipsis clause, which is the *second* half of E5's `post_process`
    and the one a reader is most likely to drop as cosmetic.

    Upstream does `t.replace('…', '...')` and then collapses any run of two or
    more `・` or `.` to that many `.`, and only then widens. So `…` ends up as
    three FULL-WIDTH stops, `．．．` - which is exactly what E5 recorded the
    post-processed `01.jpg` output as: `立川で見た、穴への下の巨大な眼は．．．`.

    RED measured this to be load-bearing on real pages, not only on the oracle
    set: `014.jpg`'s box at (232, 549, 284, 645) is typeset `……なるほど` and the
    raw decoder emits `......なるほど`. With this clause removed that one crop
    scores **0.4000** instead of 1.0000, which is what makes deferred
    verification 4 fire.
    """
    assert decode([_CLS, 23, 26, 27, 28, 29, _SEP], _VOCAB) == "．．．なるほど"
    assert decode([_CLS, 23, 23, 26, 27, 28, 29, _SEP], _VOCAB) == "．．．．．．なるほど"
    # A run of katakana middle dots is the same ellipsis set in a different
    # glyph, and upstream folds it into the same normal form.
    assert decode([_CLS, 24, 24, 24, _SEP], _VOCAB) == "．．．"


def test_the_decoded_string_carries_no_leading_or_trailing_whitespace() -> None:
    """AC-3's last clause, and it is a claim about the *whole* string, not only
    its ends.

    Upstream's `post_process` opens with `''.join(t.split())`, which removes
    every run of whitespace anywhere - not a `.strip()`. A Japanese line has no
    spaces in it, so a space the decoder emitted is an artefact, and one left in
    the middle survives into the translation prompt and into the typeset page.
    """
    tokens = [_CLS, 25, 25, 10, 11, 25, 12, 25, _SEP]

    text = decode(tokens, _VOCAB)

    assert text == "ゴメン"
    assert text == text.strip()
    assert " " not in text
    assert "　" not in text, "an ASCII space was widened to an ideographic space, not removed"


@pytest.mark.parametrize(
    ("name", "tokens"),
    [
        ("empty", []),
        ("delimiters only", [_CLS, _SEP]),
        ("every special", [_CLS, _PAD, _UNK, _MASK, _SEP]),
        ("whitespace only", [_CLS, 25, 25, _SEP]),
    ],
)
def test_a_sequence_with_nothing_printable_in_it_decodes_to_the_empty_string(
    name: str, tokens: list[int]
) -> None:
    """AC-3's empty boundary, and the input AC-4's control is built on.

    Decoding to `""` is a **successful read of nothing printable** and is not the
    same event as the model emitting no tokens at all (C-5). `decode` cannot tell
    those apart and must not try: it is handed a token sequence and returns a
    string. The distinction is made one layer up, in `transcribe_page_regions`,
    and `test_ocr_page.py` is where it is asserted.
    """
    assert decode(tokens, _VOCAB) == "", name


def test_an_id_the_vocabulary_does_not_contain_raises_rather_than_being_skipped() -> None:
    """The error path, and the reason it is a raise.

    The graph's logits are 6144 wide and the vocabulary is 6144 long, so an id
    outside it means the vocabulary and the weights do not belong together -
    someone paired `vocab.txt` with a different export. Silently dropping the
    token gives a plausible-looking Japanese string with characters missing,
    which is exactly the failure `architecture.md` D11 calls worse than a miss,
    and no gate anywhere would see it.
    """
    with pytest.raises(LookupError):
        decode([_CLS, 6143, _SEP], _VOCAB)
