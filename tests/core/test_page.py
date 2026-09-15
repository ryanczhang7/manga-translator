"""`mangatl.domain.page`: the ordering rule and the two value types.

Covers AC-1 (`p2` sorts before `p10`, not lexicographically), AC-4's shape (the
`Page`/`Chapter` types themselves, independent of any file read), and AC-7
(mixed-case names order deterministically). AC-7 is a `domain` test rather than
a filesystem one -- `A.png` and `a.png` cannot coexist in one directory on this
machine's NTFS volume, so the only place the criterion's real content (the
comparator is total and deterministic) can be pinned is `order_filenames`
itself. `## Contract` PO-4.

Nothing here touches a filesystem or Pillow: `domain` imports nothing of ours
and none of `numpy`/`PIL`/`PySide6`/`onnxruntime`/`anthropic`
(`architecture.md` §3 contract 2), and this file holds it to that by never
importing any of them either.
"""

from __future__ import annotations

import dataclasses
import random
from collections import Counter
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from mangatl.domain.page import PAGE_SUFFIXES, Chapter, Page, natural_key, order_filenames

# -- PAGE_SUFFIXES: pinned exactly, per `## Contract` -------------------------


def test_page_suffixes_are_exactly_png_jpg_and_jpeg() -> None:
    assert frozenset({".png", ".jpg", ".jpeg"}) == PAGE_SUFFIXES


# -- Page / Chapter: frozen dataclasses with the five/two contract fields -----


def test_page_carries_the_five_contract_fields_and_is_frozen() -> None:
    page = Page(ordinal=0, filename="p1.png", width=7, height=3, sha256="0" * 64)
    assert page.ordinal == 0
    assert page.filename == "p1.png"
    assert page.width == 7
    assert page.height == 3
    assert page.sha256 == "0" * 64
    with pytest.raises(dataclasses.FrozenInstanceError):
        page.ordinal = 1  # type: ignore[misc]


def test_chapter_carries_source_dir_and_an_ordered_tuple_of_pages_and_is_frozen() -> None:
    page = Page(ordinal=0, filename="p1.png", width=7, height=3, sha256="0" * 64)
    chapter = Chapter(source_dir=Path("scans"), pages=(page,))
    assert chapter.source_dir == Path("scans")
    assert chapter.pages == (page,)
    with pytest.raises(dataclasses.FrozenInstanceError):
        chapter.pages = ()  # type: ignore[misc]


# -- natural_key: the p2 < p10 rule, direct ------------------------------------

_NATURAL_KEY_PAIRS = [
    pytest.param("p2.png", "p10.png", id="single-digit-run-numeric-not-lexicographic"),
    pytest.param("2x.png", "10x.png", id="leading-digit-run"),
    pytest.param("p1_v2.png", "p1_v10.png", id="second-of-two-digit-runs"),
    pytest.param("apple.png", "banana.png", id="no-digits-falls-back-to-text"),
]


@pytest.mark.parametrize(("smaller", "larger"), _NATURAL_KEY_PAIRS)
def test_natural_key_orders_the_smaller_name_before_the_larger_one(
    smaller: str, larger: str
) -> None:
    assert natural_key(smaller) < natural_key(larger)


def test_natural_key_is_case_folded_so_case_alone_does_not_change_it() -> None:
    # "Case folding happens in the key, not in the filter." `## Contract`.
    # A.png and a.png must compare equal *as keys* -- the tie-break to raw
    # bytes lives one level up, in order_filenames, per the contract's own
    # split of responsibility (tested below).
    assert natural_key("A.png") == natural_key("a.png")


def test_natural_key_treats_zero_padding_as_the_same_numeric_value() -> None:
    # p02 and p2 both split to the digit run 2 -- this is the case the contract
    # calls out explicitly: "not because of any zero-padding the user may or
    # may not have used."
    assert natural_key("p02.png") == natural_key("p2.png")


# -- order_filenames: AC-1 and AC-2's ordering, table-driven -------------------

_ORDER_CASES = [
    pytest.param(
        ["p2.png", "p10.png", "p1.png"],
        ["p1.png", "p2.png", "p10.png"],
        id="ac1-p1-p2-p10-from-jumbled-input",
    ),
    pytest.param(
        ["p1.png", "p2.png", "p10.png"],
        ["p1.png", "p2.png", "p10.png"],
        id="ac1-p1-p2-p10-already-in-order",
    ),
    pytest.param(
        ["p1_v10.png", "p1_v2.png", "p1_v1.png"],
        ["p1_v1.png", "p1_v2.png", "p1_v10.png"],
        id="second-digit-run-drives-the-order",
    ),
    pytest.param(
        ["10x.png", "2x.png", "1x.png"],
        ["1x.png", "2x.png", "10x.png"],
        id="leading-digit-run-drives-the-order",
    ),
    pytest.param(
        ["banana.png", "apple.png", "cherry.png"],
        ["apple.png", "banana.png", "cherry.png"],
        id="no-digits-anywhere-falls-back-to-text-order",
    ),
    pytest.param([], [], id="empty-list"),
    pytest.param(["only.png"], ["only.png"], id="single-item"),
]


@pytest.mark.parametrize(("names", "expected"), _ORDER_CASES)
def test_order_filenames_produces_the_expected_order(names: list[str], expected: list[str]) -> None:
    assert order_filenames(names) == expected


# -- order_filenames: the total tie-break, AC-7 --------------------------------

_TIEBREAK_CASES = [
    pytest.param(
        ["A.png", "a.png"], ["a.png", "A.png"], ["A.png", "a.png"], id="mixed-case-A-before-a"
    ),
    pytest.param(
        ["p2.png", "p02.png"],
        ["p02.png", "p2.png"],
        ["p02.png", "p2.png"],
        id="zero-padding-tie-broken-by-raw-bytes",
    ),
]


@pytest.mark.parametrize(("order_a", "order_b", "expected"), _TIEBREAK_CASES)
def test_names_that_fold_to_the_same_key_are_ordered_deterministically(
    order_a: list[str], order_b: list[str], expected: list[str]
) -> None:
    # "The tie-break must be total. If two names fold to the same key, fall
    # back to the raw byte ordering of the name." `## Contract`. Both ASCII
    # cases here have a byte ordering identical to plain string ordering, so
    # the expected value is unambiguous without needing to pick a text
    # encoding.
    #
    # AC-7's real content, per PO-4: the same input, given in different
    # orders, gives ONE identical output. Both permutations of the input are
    # asserted against the same `expected` list.
    assert order_filenames(order_a) == expected
    assert order_filenames(order_b) == expected


# -- order_filenames: totality and determinism, as a property -----------------

# `## Contract`: "filenames cannot contain a path separator" is the design
# clause this narrowing ties to -- `Page.filename` is documented as "basename
# only, never a path" and a name containing "/" or "\\" is not a basename. NUL
# is excluded because it cannot appear in a filename on any filesystem this
# product targets (NTFS; the brief is Windows-only). Surrogates are excluded
# because they cannot be encoded and are a Python/Hypothesis text-generation
# artifact, not a real filename.
_FILENAME_ALPHABET = st.characters(blacklist_categories=("Cs",), blacklist_characters="/\\\x00")
_filenames = st.text(alphabet=_FILENAME_ALPHABET, min_size=1, max_size=12)


@given(st.lists(_filenames, max_size=8), st.randoms())
@settings(deadline=None, max_examples=100)
def test_order_filenames_is_a_deterministic_permutation_of_its_input(
    names: list[str], rnd: random.Random
) -> None:
    result = order_filenames(names)
    assert Counter(result) == Counter(names), "order_filenames must not add, drop or alter names"

    shuffled = list(names)
    rnd.shuffle(shuffled)
    assert order_filenames(shuffled) == result, (
        "the same names in a different input order must give the same output order"
    )
