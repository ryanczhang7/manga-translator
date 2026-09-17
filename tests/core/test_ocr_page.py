"""`mangatl.ocr.page` and `mangatl.domain.line`: one page's regions transcribed.

Covers **AC-4** (the empty sequence is flagged `ocr_empty`, and its mandatory
control: a specials-only sequence decodes to `""` and is **not** flagged) and the
in-memory half of **AC-5** (one result per region, position for position, each
derived from its own crop). AC-5's store half - the text landing against the
right `region.reading_index` - is `test_line_store.py`'s; AC-9's stage is
`test_ocr_stage.py`'s.

**Nothing here loads a model** (`architecture.md` §2). The fake `OcrSession`
below is a double for the *graph*, and it is built so that the thing AC-5 is
actually about cannot be faked past:

    encode(pixels)  ->  a 1x1x1 hidden state carrying the call index
    decode_step(encoder_hidden, tokens)  ->  logits for
                                             sequences[int(encoder_hidden[0,0,0])]

So a `transcribe_page_regions` that encoded every region and then decoded them
all against the *last* hidden state - or against the first, or that reused one
encode across the page - produces the wrong text for eight of nine regions and is
caught by name. A fake that ignored `encoder_hidden` would let all of those pass.
That is `tdd-cycle`'s rule about the independence of what observes a mutation,
applied to the one wire this module owns: C-1's `encoder_hidden` threading.

**`ocr_empty` means "the model emitted no tokens", not "the text is empty"**
(C-5), and the whole of AC-4 is that those two differ. `__post_init__` enforces
the one direction that must hold - `ocr_empty` implies `text == ""` - and
deliberately not the converse, because a flag enforced in both directions is
`text == ""` spelled twice and AC-4's control could not fail.

**Timing.** There is no `pytest-timeout` in this project and no per-test timeout
exists, so there is no budget in this file to size; if a later story adds one,
every test and hook here needs one. The dominant cost is `conftest._one_bit_png`,
a per-pixel Python loop, so the fixture page is 60 x 40 (2,400 px) rather than
page-sized - MT-009 measured 281 ms for a 1125x1600 mask and 7 ms for a small
one, and transcription never looks at mask pixels.
"""

from __future__ import annotations

import struct
import zlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import FrozenInstanceError

import numpy as np
import pytest
from numpy.typing import NDArray

from mangatl.domain.line import OcrResult
from mangatl.domain.region import RawRegion
from mangatl.ocr.page import transcribe_page_regions

_PAGE_W, _PAGE_H = 60, 40

# Ids 0-4 as the real `vocab.txt` has them, measured in RED; everything from 10
# up is this file's own.
_PAD, _UNK, _CLS, _SEP, _MASK = 0, 1, 2, 3, 4
_VOCAB: Mapping[int, str] = {
    _PAD: "[PAD]",
    _UNK: "[UNK]",
    _CLS: "[CLS]",
    _SEP: "[SEP]",
    _MASK: "[MASK]",
    10: "あ",
    11: "い",
    12: "う",
    13: "え",
    14: "お",
}

#: The decoder's real logit width (measured: `logits [batch, seq, 6144]`).
_VOCAB_WIDTH = 6144


class _FakeSession:
    """An `OcrSession` whose answer depends on **which** crop it was given.

    `encode` returns a hidden state carrying the index of the call, and
    `decode_step` uses that index to pick which token sequence to emit. The
    crops themselves are recorded so AC-5 can assert that each region's own
    pixels reached the encoder.
    """

    def __init__(self, sequences: Sequence[Sequence[int]]) -> None:
        self._sequences = [tuple(s) for s in sequences]
        self.encoded: list[NDArray[np.float32]] = []
        self.steps: list[tuple[int, tuple[int, ...]]] = []

    def encode(self, pixels: NDArray[np.float32]) -> NDArray[np.float32]:
        self.encoded.append(np.array(pixels, dtype=np.float32, copy=True))
        return np.full((1, 1, 1), float(len(self.encoded) - 1), dtype=np.float32)

    def decode_step(
        self, encoder_hidden: NDArray[np.float32], tokens: Sequence[int]
    ) -> NDArray[np.float32]:
        which = round(float(np.asarray(encoder_hidden).reshape(-1)[0]))
        self.steps.append((which, tuple(int(t) for t in tokens)))
        sequence = self._sequences[which]
        position = len(tokens) - 1
        wanted = sequence[position] if position < len(sequence) else _SEP
        logits = np.full(_VOCAB_WIDTH, -1e4, dtype=np.float32)
        logits[wanted] = 1e4
        return logits

    def get_providers(self) -> Sequence[str]:
        return ("CPUExecutionProvider",)


def _ring(x0: int, y0: int, x1: int, y1: int) -> tuple[tuple[int, int], ...]:
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))


def _varied_page_png(width: int, height: int) -> bytes:
    """An 8-bit RGB PNG in which **no two pixels are alike**, standard library only.

    `conftest.png_bytes` fills a page with one colour, which is right for the
    intake tests and useless here: three crops of a uniform page are three
    identical tensors, and every "this region got its own pixels" assertion below
    would pass against a transcriber that cropped nothing at all. Same chunk
    recipe as `conftest._png_bytes` (MT-004 `## Contract` PO-2), different
    payload.

    `page[y, x] == (index // 256, index % 256, 7)` for `index = y * width + x`,
    which is the same scheme `test_ocr_preprocess.py` uses for AC-1's page.
    """
    raw = bytearray()
    for y in range(height):
        raw += b"\x00"
        for x in range(width):
            index = y * width + x
            raw += bytes((index // 256, index % 256, 7))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


@pytest.fixture
def page_bytes() -> bytes:
    """One page's encoded bytes, as the stage reads them off disk.

    `transcribe_page_regions` takes **encoded bytes** rather than an array, for
    the reason `detect.page.detect_page_regions` does: the decode belongs to the
    adapter, and `domain` may not import PIL (`architecture.md` §3 contract 2).
    """
    return _varied_page_png(_PAGE_W, _PAGE_H)


@pytest.fixture
def regions(one_bit_png: Callable[..., bytes]) -> tuple[RawRegion, ...]:
    """Three regions at three **disjoint, differently shaped** rectangles.

    Disjoint and differently shaped is the point: a transcriber that cropped the
    same rectangle three times, or that handed the whole page over three times,
    produces three identical crops and is caught by
    `test_each_region_is_encoded_from_its_own_crop_and_not_from_the_page`.
    """
    mask = one_bit_png(_PAGE_W, _PAGE_H, [(0, 0, 4, 4)])
    return (
        RawRegion(polygon=_ring(38, 4, 50, 22), mask=mask, confidence=0.5, kind="bubble"),
        RawRegion(polygon=_ring(8, 6, 26, 18), mask=mask, confidence=0.75, kind="bubble"),
        RawRegion(polygon=_ring(10, 26, 20, 36), mask=mask, confidence=0.25, kind="box"),
    )


# -- OcrResult, and the one-directional invariant C-5 requires -----------------


def test_an_ocr_result_carries_the_text_and_the_flag_and_defaults_to_not_empty() -> None:
    """C-1's `OcrResult`: `text`, `ocr_empty` defaulting to `False`, frozen.

    Frozen because it is a value: two results with the same text and the same
    flag are the same result, and nothing in the pipeline mutates one after it is
    built. The default matters because `write_lines` and every construction site
    that has real text should not have to mention the flag at all.
    """
    result = OcrResult(text="あいう")

    assert result.text == "あいう"
    assert result.ocr_empty is False
    assert result == OcrResult(text="あいう", ocr_empty=False)
    with pytest.raises(FrozenInstanceError):
        result.text = "changed"  # type: ignore[misc]


def test_a_result_flagged_ocr_empty_with_text_in_it_is_refused_at_construction() -> None:
    """C-1/C-5's `__post_init__`: `ocr_empty` implies `text == ""`.

    Refused where it is built rather than two stages later in a review screen
    that shows a line both as "read nothing" and as carrying words. `RawRegion`
    makes the same choice for the same reason.
    """
    with pytest.raises(ValueError, match="ocr_empty"):
        OcrResult(text="あ", ocr_empty=True)


def test_an_empty_string_without_the_flag_is_a_legal_result_and_that_is_the_point() -> None:
    """C-5's converse, **deliberately not enforced**, and the reason AC-4 has a
    control at all.

    A specials-only decode is a successful read of nothing printable; an empty
    token sequence is the model declining to emit. If `__post_init__` also
    enforced `text == "" implies ocr_empty`, the flag would be `text == ""`
    restated, it would carry no information, and AC-4's control below could not
    fail. This assertion is what stops a later story "tidying" the invariant into
    symmetry.
    """
    result = OcrResult(text="", ocr_empty=False)

    assert result.text == ""
    assert result.ocr_empty is False
    assert result != OcrResult(text="", ocr_empty=True)


# -- AC-4: the empty sequence, and its mandatory control ----------------------


def test_a_model_that_emits_no_tokens_at_all_is_flagged_ocr_empty(
    page_bytes: bytes, regions: tuple[RawRegion, ...]
) -> None:
    """AC-4's first half. The session returns EOS immediately, so nothing was
    emitted, and the region is flagged rather than silently carrying `""` as if
    it had been read.

    The flag is per region, not per page: the other two regions on the same page
    transcribe normally in the same call, which is what stops an implementation
    flagging the whole page whenever any region is empty.
    """
    session = _FakeSession([(), (10, 11), (12, 13, 14)])

    results = transcribe_page_regions(session, _VOCAB, page_bytes, regions)

    assert results[0] == OcrResult(text="", ocr_empty=True)
    assert results[1] == OcrResult(text="あい", ocr_empty=False)
    assert results[2] == OcrResult(text="うえお", ocr_empty=False)


def test_a_model_that_emits_only_special_tokens_reads_empty_without_the_flag(
    page_bytes: bytes, regions: tuple[RawRegion, ...]
) -> None:
    """**AC-4's control, and it is mandatory** (C-5).

    `[PAD]`, `[UNK]` and `[MASK]` are tokens the graph really emitted, so this is
    a *successful* read whose printable content happens to be nothing. Its text
    is `""` and its `ocr_empty` is `False`, and the difference from the test
    above is the entire justification for the flag existing and for the schema
    going to version 2 (PO-3).

    An implementation that set `ocr_empty = not text` passes every other
    assertion in this file and fails exactly here. That is what a negative
    control is for.

    EXPECTED VALUE, RECORDED IN RED AND UNVERIFIED IN RED: `OcrResult(text="",
    ocr_empty=False)`. Computed outside the framework from the decode rules -
    `mangatl.ocr` does not exist yet, so this file fails at import and not one
    assertion in it has executed. GREEN must confirm the measured value.
    """
    session = _FakeSession([(_PAD, _UNK, _MASK), (10,), (11,)])

    results = transcribe_page_regions(session, _VOCAB, page_bytes, regions)

    assert results[0].text == ""
    assert results[0].ocr_empty is False, (
        "a sequence of special tokens only was flagged ocr_empty. The flag means"
        " 'the model emitted no tokens' (C-5); flagged on empty TEXT it is"
        ' `text == ""` spelled twice and carries no information at all.'
    )
    assert results[0] != OcrResult(text="", ocr_empty=True)
    assert [r.text for r in results] == ["", "あ", "い"]


def test_the_empty_and_specials_only_cases_are_distinguishable_from_each_other(
    page_bytes: bytes, regions: tuple[RawRegion, ...]
) -> None:
    """AC-4 as one assertion: the two inputs produce results that are not equal.

    Stated separately from the two tests above because it is the claim the store
    then has to carry across a reopen (AC-10), and because a failure here reads
    as "the flag does not distinguish anything" rather than as a wrong string.
    """
    emitted_nothing = transcribe_page_regions(
        _FakeSession([(), (10,), (11,)]), _VOCAB, page_bytes, regions
    )[0]
    emitted_specials = transcribe_page_regions(
        _FakeSession([(_PAD, _SEP), (10,), (11,)]), _VOCAB, page_bytes, regions
    )[0]

    assert emitted_nothing.text == emitted_specials.text == ""
    assert emitted_nothing != emitted_specials
    assert (emitted_nothing.ocr_empty, emitted_specials.ocr_empty) == (True, False)


# -- AC-5: one result per region, position for position ------------------------


def test_every_region_gets_its_own_result_at_its_own_position(
    page_bytes: bytes, regions: tuple[RawRegion, ...]
) -> None:
    """AC-5's in-memory half. Position is the only carrier of identity here.

    `RawRegion` holds no id and no index of its own (MT-009 PO-1), so the
    sequence handed back **is** the mapping: `results[i]` belongs to
    `regions[i]`. The three sequences are distinct and in an order that is not
    sorted, so a transcriber that returned them in encode order but reversed, or
    that sorted by text, fails on content rather than on length.
    """
    session = _FakeSession([(12, 13), (10,), (14, 10, 11)])

    results = transcribe_page_regions(session, _VOCAB, page_bytes, regions)

    assert len(results) == len(regions)
    assert [r.text for r in results] == ["うえ", "あ", "おあい"]
    assert all(isinstance(r, OcrResult) for r in results)


def test_each_region_is_encoded_from_its_own_crop_and_not_from_the_page(
    page_bytes: bytes, regions: tuple[RawRegion, ...]
) -> None:
    """AC-5's mechanism: one encode per region, each of that region's own pixels.

    The three regions are disjoint and differently shaped, so three identical
    encoder inputs means the crop step did not happen. The tensors are all
    `(1, 3, 224, 224)` by the time the encoder sees them, so "differently shaped"
    cannot be asserted on the shape - it is asserted on the **content**, which is
    the only place the difference survives the resize.
    """
    session = _FakeSession([(10,), (11,), (12,)])

    transcribe_page_regions(session, _VOCAB, page_bytes, regions)

    assert len(session.encoded) == len(regions), (
        f"the encoder ran {len(session.encoded)} times for {len(regions)} regions"
    )
    for tensor in session.encoded:
        assert tensor.dtype == np.float32
        assert tensor.shape == (1, 3, 224, 224)
    fingerprints = {tuple(np.asarray(t).reshape(-1)[::997].tolist()) for t in session.encoded}
    assert len(fingerprints) == len(regions), (
        "two regions produced identical encoder input, so the crops are not the"
        " regions' own pixels - every region was handed the same image"
    )


def test_each_decode_runs_against_its_own_regions_encoder_hidden_state(
    page_bytes: bytes, regions: tuple[RawRegion, ...]
) -> None:
    """C-1's `encoder_hidden` threading, which no assertion on the text alone can
    reach.

    The fake decides what to emit from the hidden state it is handed, so a
    transcriber that encoded all three regions and then decoded them against one
    shared hidden state returns the same text three times. Recorded per call, so
    the failure names which region was decoded against which encode rather than
    only that the strings were wrong.
    """
    session = _FakeSession([(10,), (11,), (12,)])

    results = transcribe_page_regions(session, _VOCAB, page_bytes, regions)

    assert [r.text for r in results] == ["あ", "い", "う"]
    # Every decode of region i used encode i - two steps each (one emitting the
    # character, one emitting EOS), and never a hidden state from another region.
    assert [which for which, _ in session.steps] == [0, 0, 1, 1, 2, 2]
    assert [tokens for _, tokens in session.steps] == [
        (_CLS,),
        (_CLS, 10),
        (_CLS,),
        (_CLS, 11),
        (_CLS,),
        (_CLS, 12),
    ]


@pytest.mark.parametrize("count", [0, 1], ids=["no regions", "one region"])
def test_a_page_with_no_regions_or_one_region_is_handled_without_a_special_case(
    page_bytes: bytes, regions: tuple[RawRegion, ...], count: int
) -> None:
    """AC-5's empty and one boundaries.

    A page the detector found no text on is real - MT-035 AC-5 ships that case
    deliberately - and it must cost **zero** inferences rather than one on the
    whole page. The `no regions` row is what makes that falsifiable.
    """
    session = _FakeSession([(10,), (11,), (12,)])

    results = transcribe_page_regions(session, _VOCAB, page_bytes, regions[:count])

    assert len(results) == count
    assert len(session.encoded) == count
