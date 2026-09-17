"""AC-6 and AC-7: the real `manga-ocr` export, real crops, on the machine with
the GPU.

**Why these two criteria cannot be met anywhere else.** AC-6's subject is whether
this pipeline transcribes *vertical* Japanese, and AC-7's is whether furigana the
detector did not strip stays out of the text. Neither is a property of this
repository's code: a synthetic fixture would make both true by construction, and
a fake session makes them vacuous. Everything else in MT-010 runs against a fake
in `tests/core/` and is read by the `unit` and `coverage` gates
(`architecture.md` §2).

**The crops are derived from the detector's own boxes, not hand-picked** (C-9,
PO-5). MT-002 E5 recorded the reason in its own method note: *"my rectangles had
clipped the text, not that the model failed ... a bad crop is indistinguishable
from a bad model unless you look at the crop."* So this file runs the real
detector over `spikes/MT-002/pages/014.jpg`, sorts its regions into reading
order, and transcribes those. The ground-truth strings are committed - they are
text, not scans - and the crops are reproduced at test time.

**The ruby-alone control of AC-7 is the documented exception.** MT-008 measured
that the detector's dilation absorbs ruby columns, so no box isolates one. That
crop is a hand-picked rectangle whose coordinates are transcribed below as a
constant with the page and scan size named, the way `_SFX_012` is in
`test_detector_session.py`.

**The data is gitignored and these tests skip cleanly without it.** The pages and
the weights live under `spikes/**`, which `.gitignore` covers: non-redistributable
scans of a commercial release, and model weights. A checkout without them skips.

**Numbers measured in RED on this machine, 2026-09-16, before this file existed**,
by performing the same steps in a throwaway script outside pytest
(`CUDAExecutionProvider`, `onnxruntime-gpu 1.30.0`):

| Quantity | Value |
|---|---|
| Regions the detector finds on `014.jpg` | 9 |
| Mean character accuracy, all 9, normalisation applied | **1.0000** (9/9 exact) |
| Mean character accuracy with C-7's normalisation removed | **0.9222** |
| Mean character accuracy, every crop rotated 90 degrees | **0.0947** (max 0.6000) |
| Ruby-alone crop at (1052, 548, 1082, 622) | `しゅうき` |
| Greedy decode, one crop | 48.2 ms mean, 79.0 ms max |
| Encoder + decoder session construction | 0.72 s (warm file cache) |

Those are **RED's numbers against a throwaway script, not against the shipped
module**. GREEN measures them again through `mangatl.ocr` and records the
measured values beside the expected ones - see the story's handoff table. The
story's C-8 leaves `OCR_MIN_ACCURACY` for GREEN to settle; this file reads it out
and constrains it from below, it does not choose it.

**Timing.** There is no `pytest-timeout` in this project and no per-test timeout
exists, so there is no budget in this file to size - the same note
`test_detector_session.py` carries. If a later story adds one, every test *and
every hook* here needs one, sized from CI rather than from this machine: the
session fixtures are module-scoped and cost about a second once, and the whole
file is 19 decodes at 48 ms.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray
from PIL import Image

from mangatl.detect.page import detect_page_regions
from mangatl.detect.session import load_detector
from mangatl.domain.line import OcrResult
from mangatl.domain.reading_order import sort_regions
from mangatl.domain.region import RawRegion
from mangatl.ocr.decode import decode
from mangatl.ocr.generate import greedy_generate
from mangatl.ocr.page import OCR_MIN_ACCURACY, transcribe_page_regions
from mangatl.ocr.preprocess import MODEL_INPUT_SIZE, crop_for_region, to_model_input
from mangatl.ocr.session import (
    DECODER_FILENAME,
    ENCODER_FILENAME,
    VOCAB_FILENAME,
    OcrSession,
    load_ocr,
    load_vocab,
    selected_provider,
)

pytestmark = pytest.mark.gpu

_SPIKES = Path(__file__).resolve().parents[2] / "spikes"
_DETECTOR = _SPIKES / "MT-002" / "models" / "comic-text-detector-onnx" / "comic-text-detector.onnx"
_PAGES = _SPIKES / "MT-002" / "pages"

#: `load_ocr` takes a **directory** (C-1), and the three files it expects are
#: named by `ENCODER_FILENAME`, `DECODER_FILENAME` and `VOCAB_FILENAME`. The
#: spike laid the two graphs out under `onnx/` and the vocabulary in a sibling
#: repo checkout, so neither directory holds all three and `ocr_model_dir`
#: assembles one out of symlinks-or-copies below.
_ONNX_DIR = _SPIKES / "MT-002" / "models" / "manga-ocr-base-ONNX" / "onnx"
_VOCAB_SRC = _SPIKES / "MT-002" / "models" / "manga-ocr-base" / "vocab.txt"

_PROVIDERS = ("CUDAExecutionProvider", "CPUExecutionProvider")

#: The page every criterion below runs against: 1125 x 1600, the size of every
#: scan under `spikes/MT-002/pages/`.
_PAGE = "014.jpg"
_SCAN_SIZE = (1125, 1600)

#: The nine regions the real detector finds on `014.jpg`, in **reading order**,
#: with the transcription a human read off the page beside each.
#:
#: The boxes are the polygon bounding boxes `(x0, y0, x1, y1)` MEASURED IN RED on
#: this machine, and they are asserted rather than used: if the detector ever
#: moves, this file must say "the boxes moved" instead of quietly scoring the
#: wrong crop against the wrong string.
#:
#: The strings are the **hand annotation**, and they are not the model's output
#: copied back. They come from MT-002 E5 Test 2, where a human read all nine off
#: the page and recorded them; RED re-read three of them off the scan directly
#: (index 0, 2 and 4, enlarged) before transcribing this table. Two differ
#: deliberately from what the raw decoder emits, and those two are what make
#: C-7's normalisation load-bearing here rather than only in `tests/core`:
#:
#: * index 0 is typeset with a FULL-WIDTH question mark and the decoder emits a
#:   half-width `?` - E5's own `?` against `?` case, measured again in RED;
#: * index 4 is typeset as two ellipsis characters and the decoder emits six
#:   half-width stops.
#:
#: With C-7 removed those two score 0.9000 and 0.4000 and the mean falls from
#: 1.0000 to 0.9222 - which is deferred verification 4, and it fires.
_GROUND_TRUTH: tuple[tuple[tuple[int, int, int, int], str], ...] = (
    ((944, 48, 1001, 194), "人間側のメリットは？"),  # noqa: RUF001 - typeset full-width
    ((99, 47, 293, 226), "神が協力する事で魔都の資源をリスクなく使い放題"),
    ((943, 557, 1071, 732), "醜鬼が人間の言う通りに動いたりね"),
    ((357, 565, 472, 740), "神の威信が高まった事で桃も安定供給"),
    ((232, 549, 284, 645), "……なるほど"),
    ((968, 907, 1059, 1132), "「魔都を国の力とする」"),
    ((799, 1063, 879, 1244), "私の理想に近いわ"),
    ((155, 1081, 273, 1264), "総理達もそれを望んでいる筈"),
    ((922, 1430, 1053, 1555), "この提案罠の可能性は十分にある"),
)

#: AC-7's furigana case: the region at index 2 is 醜鬼 with the ruby しゅうき
#: beside it, the exact crop MT-002 E5 Test 2 called out as box 02.
_FURIGANA_INDEX = 2
_RUBY_TEXT = "しゅうき"
_MAIN_TEXT_WITHOUT_RUBY = "醜鬼が人間の言う通りに動いたりね"

#: **A hand-picked rectangle, and the only one in this file** (C-9's documented
#: exception). `(x0, y0, x1, y1)` on the 1125 x 1600 scan of `014.jpg`, tight
#: around the ruby column しゅうき that sits to the right of 醜鬼 inside the
#: bubble at `(943, 557, 1071, 732)`. Located in RED by enlarging that bubble 4x
#: and reading the coordinates off it; six nested rectangles from (1060, 552,
#: 1078, 610) out to (1050, 545, 1085, 620) all transcribe to `しゅうき`, so the
#: control is not balanced on one lucky crop.
_RUBY_CROP = (1052, 548, 1082, 622)


def _require(path: Path) -> None:
    if not path.exists():
        pytest.skip(f"{path} is not present: gitignored spike data, see the module docstring")


@pytest.fixture(scope="module")
def ocr_model_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A directory laid out the way `load_ocr` expects it.

    `load_ocr(model_dir, providers)` looks for `ENCODER_FILENAME`,
    `DECODER_FILENAME` and `VOCAB_FILENAME` side by side (C-1). The spike's
    checkout puts the graphs under `onnx/` and the vocabulary in a different
    repository, so this assembles the three into one directory. Hard links where
    the platform allows them - the encoder alone is 343 MB and copying it per
    module scope is a third of a gigabyte of I/O for nothing.
    """
    for source in (_ONNX_DIR / ENCODER_FILENAME, _ONNX_DIR / DECODER_FILENAME, _VOCAB_SRC):
        _require(source)

    directory = tmp_path_factory.mktemp("manga-ocr-model")
    for source, name in (
        (_ONNX_DIR / ENCODER_FILENAME, ENCODER_FILENAME),
        (_ONNX_DIR / DECODER_FILENAME, DECODER_FILENAME),
        (_VOCAB_SRC, VOCAB_FILENAME),
    ):
        target = directory / name
        try:
            target.hardlink_to(source)
        except OSError:
            target.write_bytes(source.read_bytes())
    return directory


@pytest.fixture(scope="module")
def session(ocr_model_dir: Path) -> Iterator[OcrSession]:
    """The real encoder and decoder, built once for the module.

    Module scope because construction costs about 0.7 s (measured in RED, warm
    file cache) and every test here wants the same two graphs.
    """
    yield load_ocr(ocr_model_dir, _PROVIDERS)


@pytest.fixture(scope="module")
def vocab(ocr_model_dir: Path) -> Mapping[int, str]:
    return load_vocab(ocr_model_dir / VOCAB_FILENAME)


@pytest.fixture(scope="module")
def page() -> NDArray[np.uint8]:
    _require(_PAGES / _PAGE)
    with Image.open(_PAGES / _PAGE) as image:
        return np.asarray(image.convert("RGB"), dtype=np.uint8)


@pytest.fixture(scope="module")
def regions() -> tuple[RawRegion, ...]:
    """The detector's own regions on `014.jpg`, in reading order.

    The whole detect chain, exactly as `DetectStage` runs it (MT-035): the real
    graph, `detect_page_regions`, then `sort_regions`. Deriving the crops rather
    than hand-picking them is C-9, and the reason is E5's method note.
    """
    _require(_DETECTOR)
    _require(_PAGES / _PAGE)
    detector = load_detector(_DETECTOR, _PROVIDERS)
    return tuple(sort_regions(detect_page_regions(detector, (_PAGES / _PAGE).read_bytes())))


@pytest.fixture(scope="module")
def transcriptions(
    session: OcrSession,
    vocab: Mapping[int, str],
    regions: tuple[RawRegion, ...],
) -> tuple[OcrResult, ...]:
    """All nine regions transcribed in one call, through the shipped composition.

    Module scope: nine greedy decodes at 48 ms each are cheap but not free, and
    three tests read the same answer. `transcribe_page_regions` rather than the
    pieces, so this is the path `OcrStage` will actually walk.
    """
    _require(_PAGES / _PAGE)
    return tuple(transcribe_page_regions(session, vocab, (_PAGES / _PAGE).read_bytes(), regions))


# -- the accuracy metric -------------------------------------------------------
#
# C-8 fixes the metric and leaves the threshold to GREEN: **character-level
# accuracy, 1 - normalised Levenshtein distance against the annotation**. It is
# written out here rather than taken from a library because the only libraries
# that offer it are not dependencies of this project, and because a metric a
# reader cannot check is a threshold nobody can argue with.


def _levenshtein(a: str, b: str) -> int:
    """Edit distance, iterative two-row. Strings here are tens of characters."""
    if a == b:
        return 0
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (0 if ca == cb else 1))
            )
        previous = current
    return previous[-1]


def _accuracy(got: str, expected: str) -> float:
    """`1 - distance / max(len)`, clamped into [0, 1] by construction.

    Two empty strings score 1.0: nothing was expected and nothing was produced.
    That case cannot arise against `_GROUND_TRUTH`, every entry of which is
    non-empty, and it is defined so the helper has no undefined input.
    """
    longest = max(len(got), len(expected))
    return 1.0 if longest == 0 else 1.0 - _levenshtein(got, expected) / longest


def _normalised(text: str) -> str:
    """The annotation put through the same normal form `decode` produces.

    The comparison has to be like for like: the ground truth is what a human
    *reads* on the page, and C-7's normalisation is what the pipeline produces,
    so the annotation is run through the shipped `decode` with a one-entry
    vocabulary. Re-implementing the normalisation here would compare the
    pipeline against a second copy of itself, which is the mistake `tdd-cycle`
    warns about under "the independence of what observes a mutation" - but the
    alternative, hand-transcribing the normal form, would silently encode
    whatever the pipeline happens to do. So: the ground truth is annotated as
    the page reads, and the ONE transformation applied to both sides is the one
    C-7 names.
    """
    return decode([0], {0: text})


def test_the_provider_actually_selected_is_the_one_the_session_reports(
    session: OcrSession,
) -> None:
    """The MT-002 E2 check, for this pair of graphs.

    `get_available_providers()` advertises CUDA identically whether or not the
    DLLs loaded and is worthless (MT-002 PO-3); `session.get_providers()` is
    honest. Asserted here for the same reason MT-007 asserted it for the
    detector: a silent fall back to CPU turns 48 ms a crop into 158 ms with no
    error anywhere, and nothing else in this suite would notice.
    """
    reported = session.get_providers()

    assert selected_provider(session) == reported[0]
    assert reported[0] == "CUDAExecutionProvider", (
        f"CUDAExecutionProvider is not first in {list(reported)}. Either"
        " ort.preload_dlls(cuda=True, cudnn=True, msvc=True) did not run before the"
        " first InferenceSession, or this machine has no CUDA."
    )


def test_the_shipped_vocabulary_is_the_character_level_one_decode_assumes(
    vocab: Mapping[int, str],
) -> None:
    """`load_vocab` against the real `vocab.txt`, and the two facts `decode`
    rests on.

    MEASURED IN RED by reading the file: **6144 entries**, matching the decoder's
    `logits [batch, seq, 6144]` and `config.json`'s `decoder.vocab_size`; ids 0-4
    are `[PAD] [UNK] [CLS] [SEP] [MASK]`; and **not one entry begins with `##`**,
    because the decoder is `cl-tohoku/bert-base-japanese-char-v2`, a
    character-level model. That last is why `decode` has no word-piece branch -
    `spikes/MT-002/ocr.py` carried one and it was dead code.
    """
    assert len(vocab) == 6144
    assert [vocab[i] for i in range(5)] == ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]"]
    continuations = [token for token in vocab.values() if token.startswith("##")]
    assert continuations == [], (
        f"{len(continuations)} word-piece continuations in a vocabulary RED measured to"
        " have none; decode's no-subword assumption no longer holds"
    )


def test_the_detector_still_finds_the_nine_boxes_this_files_annotation_is_keyed_to(
    regions: tuple[RawRegion, ...],
) -> None:
    """The control on the fixture, before any accuracy is computed.

    `_GROUND_TRUTH` is keyed by position in reading order. If the detector moves,
    every accuracy below is scored against the wrong string and AC-6 fails for a
    reason that has nothing to do with OCR. This test is what makes that failure
    legible: it says "the boxes moved", and names which.

    The nine were measured by MT-002 E5, re-measured byte-identically by MT-030,
    and re-measured a third time in RED here.
    """
    boxes = tuple(
        (
            min(x for x, _ in region.polygon),
            min(y for _, y in region.polygon),
            max(x for x, _ in region.polygon),
            max(y for _, y in region.polygon),
        )
        for region in regions
    )
    expected = tuple(box for box, _text in _GROUND_TRUTH)

    assert len(regions) == 9
    assert boxes == expected


# -- AC-6: vertical Japanese, and the rotated control --------------------------


def test_every_vertical_fixture_crop_meets_the_accuracy_threshold(
    transcriptions: tuple[OcrResult, ...],
) -> None:
    """**AC-6.** Nine crops of vertical Japanese, character accuracy per crop.

    All nine are vertical columns inside speech bubbles on a real scan, including
    the two hardest cases on the page (MT-002 E5): white text over solid black
    artwork at index 5, and a crop containing furigana at index 2. RED measured
    **1.0000 on every one of them** through a throwaway script; the threshold is
    GREEN's to settle with stated headroom (C-8), and this reads it out.

    The `not text` guard is not decoration. MT-002 E5 Test 3 measured that this
    export hallucinates confident Japanese on text-free crops and exposes no
    score, so *nothing* here may treat an empty transcription as a signal - but
    an empty transcription on a crop that demonstrably contains text is a defect
    that a mean accuracy could absorb, and a per-crop assertion cannot.
    """

    scores = [
        (index, _accuracy(result.text, _normalised(text)), result.text)
        for index, (result, (_box, text)) in enumerate(
            zip(transcriptions, _GROUND_TRUTH, strict=True)
        )
    ]

    below = [
        (index, round(score, 4), got) for index, score, got in scores if score < OCR_MIN_ACCURACY
    ]
    assert below == [], (
        f"{len(below)} of 9 vertical crops scored below OCR_MIN_ACCURACY"
        f" ({OCR_MIN_ACCURACY}): {below}. RED measured 1.0000 on all nine."
    )
    assert not any(result.ocr_empty for result in transcriptions), (
        "the model emitted no tokens at all for a crop that contains text"
    )


def test_the_same_crops_rotated_ninety_degrees_score_far_below_the_threshold(
    session: OcrSession,
    vocab: Mapping[int, str],
    page: NDArray[np.uint8],
    regions: tuple[RawRegion, ...],
) -> None:
    """**AC-6's control, and the assertion that makes AC-1's "do not rotate" rule
    enforceable rather than a comment.**

    `manga-ocr` is trained on manga crops in their native orientation
    (`stack.md` §5/O6). If rotating the input did not hurt, this suite would not
    be measuring transcription of *vertical* text at all and C-2 would be
    unverified. It is the single most valuable control in the story, and it is
    the same defect deferred verification 1 asks GATES to inject.

    **The control is on the MEAN, not per crop, and that is measured rather than
    convenient.** RED's rotated scores were 0.0000, 0.0000, 0.0000, 0.0526,
    0.6000, 0.1333, 0.0000, 0.0000, 0.0667 - mean **0.0947**. The one outlier is
    index 4, `……なるほど`, whose rotated output `......村の地` keeps all six
    normalised stops; six of eleven characters correct is 0.6000, which is above
    half of any sane threshold while being obviously garbage. So the aggregate is
    what "materially worse" means here, and the per-crop assertion beside it is
    the weaker, always-true one: no rotated crop reaches the threshold.

    EXPECTED VALUES, RECORDED IN RED AND UNVERIFIED IN RED: mean 0.0947, max
    0.6000. Measured by a throwaway script outside pytest, because in RED
    `mangatl.ocr` does not exist and this file does not import. GREEN confirms
    them against the shipped module.
    """

    scores: list[float] = []
    for region, (_box, text) in zip(regions, _GROUND_TRUTH, strict=True):
        crop = crop_for_region(page, region)
        rotated = np.ascontiguousarray(np.rot90(crop, 1))
        hidden = session.encode(to_model_input(rotated, MODEL_INPUT_SIZE))
        scores.append(_accuracy(_greedy(session, vocab, hidden), _normalised(text)))

    mean = sum(scores) / len(scores)
    assert mean < OCR_MIN_ACCURACY / 2, (
        f"rotating every crop 90 degrees left the mean character accuracy at {mean:.4f},"
        f" which is not below half of OCR_MIN_ACCURACY ({OCR_MIN_ACCURACY / 2}). Either"
        " the crops are not vertical text, or the pipeline is rotating them back -"
        " in which case AC-1's 'no rotation' rule is unverified. RED measured 0.0947."
    )
    assert max(scores) < OCR_MIN_ACCURACY, (
        f"a rotated crop scored {max(scores):.4f}, at or above the threshold a correctly"
        " oriented one has to clear"
    )


def test_the_threshold_is_high_enough_that_dropping_the_normalisation_breaks_it() -> None:
    """C-8's floor, and it is derived from a measurement rather than chosen.

    RED measured the nine transcriptions twice: **1.0000** mean with C-7's
    normalisation and **0.9222** without, the drop coming entirely from index 0
    (0.9000, a half-width `?` against a typeset full-width one) and index 4
    (0.4000, six stops against two ellipsis characters).

    So a threshold at or below 0.9000 would let the h2z step be deleted and AC-6
    would still pass on every crop - which is exactly the "a threshold that
    absorbs a known, fixable 33-point defect" C-7 warns about, and it would make
    deferred verification 4 unfireable. Above 0.9000, index 0 alone catches it.

    The upper bound is the story's, not RED's: C-8 says a threshold set to
    whatever the implementation scored is not a threshold, so it must sit below
    the measured 1.0000 with stated headroom.
    """

    assert 0.9 < OCR_MIN_ACCURACY < 1.0, (
        f"OCR_MIN_ACCURACY is {OCR_MIN_ACCURACY}. At or below 0.9000 the h2z"
        " normalisation of C-7 could be deleted without AC-6 noticing (RED measured"
        " 0.9000 for crop 0 without it); at 1.0 it is the measurement, not a threshold."
    )


# -- AC-7: furigana the detector did not strip ---------------------------------


def test_the_ruby_characters_do_not_appear_in_the_main_columns_transcription(
    transcriptions: tuple[OcrResult, ...],
) -> None:
    """**AC-7.** The crop at index 2 contains 醜鬼 with the ruby しゅうき beside
    it, and the transcription must carry the kanji and not the ruby.

    This is `stack.md` §5/O6's other half, and it is handled by **model choice**
    rather than by a pre-processing step: `manga-ocr` is trained to drop ruby, and
    MT-002 E5 Test 2 box 02 measured exactly that. Nothing in this story strips
    furigana, and MT-008's column merge deliberately absorbs the ruby column into
    its parent rather than deleting it.

    **CORRECTED ON A RETURN TO RED** (`## Regressions`, defect 1). This test
    used to assert `sorted(set(_RUBY_TEXT) & set(text)) == []` as well, on the
    reasoning that four ruby characters scattered through the text would be a
    leak even if they never appeared consecutively. That reasoning is wrong, and
    self-contradictorily so: the ruby is `しゅうき` and the annotation is
    `醜鬼が人間の言う通りに動いたりね`, which contains `う` in `言う`. The
    intersection is therefore `{う}` *whenever the equality above passes*, so no
    implementation could satisfy both assertions one line apart. GREEN reported
    it; the orchestrator reproduced it independently by enumeration, without the
    model (`## Notes` PO-7).

    AC-7's own wording is that the ruby characters "do not appear in the
    transcription", and the criterion is met: `"しゅうき" in text` is `False`.
    So the assertion is the **string**, which is what the criterion says and what
    a leaked ruby column would actually look like - `manga-ocr` reads a column top
    to bottom, so ruby it failed to drop arrives as its own contiguous run, not
    as four kana sprinkled through the sentence.

    Two stronger readings were considered and rejected with the repair (PO-7):
    intersecting only the ruby-exclusive characters `{し, ゅ, き}`, and asserting
    both. Both encode this particular annotation into the control, so a later
    fixture with a `し` in its main column would fail for no reason.
    """
    text = transcriptions[_FURIGANA_INDEX].text

    # AC-7's own clause first, so that a pipeline which reads the ruby column
    # instead of its base text fails on *this* assertion rather than on the
    # equality below. The order matters: it is what the probe in `## Regressions`
    # drives, and an assertion that can only ever be reached after a stricter one
    # has passed is an assertion no mutation can single out.
    assert _RUBY_TEXT not in text, (
        f"the transcription {text!r} contains the ruby {_RUBY_TEXT!r}; O6 says the"
        " model is trained to drop it, and MT-002 E5 Test 2 box 02 measured that"
    )
    assert text == _normalised(_MAIN_TEXT_WITHOUT_RUBY)


def test_the_ruby_column_on_its_own_transcribes_to_the_ruby_characters(
    session: OcrSession,
    vocab: Mapping[int, str],
    page: NDArray[np.uint8],
) -> None:
    """**AC-7's control, and it is mandatory** - otherwise AC-7 passes because the
    model outputs nothing.

    Without it, a pipeline that returned the empty string for every crop would
    satisfy AC-7 perfectly. This shows the ruby is legible to this model when it
    is the only thing in the frame, so its absence from the main column's
    transcription is the model dropping it rather than the model failing to see
    it.

    The rectangle is hand-picked - the one in this file - because MT-008 measured
    that the detector's dilation absorbs ruby columns and no box isolates one
    (C-9's documented exception).

    EXPECTED VALUE, RECORDED IN RED AND UNVERIFIED IN RED: exactly `しゅうき`,
    from a throwaway script outside pytest on six nested rectangles around this
    one. GREEN confirms the measured value against the shipped module.
    """
    x0, y0, x1, y1 = _RUBY_CROP
    assert (x1, y1) <= _SCAN_SIZE, "the hand-picked ruby rectangle is off the page"

    crop = np.ascontiguousarray(page[y0:y1, x0:x1])
    hidden = session.encode(to_model_input(crop, MODEL_INPUT_SIZE))

    assert _greedy(session, vocab, hidden) == _RUBY_TEXT, (
        "the ruby column alone did not transcribe to its own characters, so AC-7"
        " above may be passing because the model reads nothing there at all"
    )


# -- helpers that drive the session directly -----------------------------------
#
# The two control tests transcribe a crop that is not one of the page's regions,
# so they cannot go through `transcribe_page_regions`. They compose the same
# three shipped pieces by hand instead.


def _greedy(session: OcrSession, vocab: Mapping[int, str], hidden: NDArray[np.float32]) -> str:
    """One crop's encoder output, greedily decoded and post-processed.

    The three shipped pieces composed by hand - `greedy_generate` over a
    `DecoderStep` closed over this crop's hidden state, then `decode`. Identical
    to what `transcribe_page_regions` does internally, and written out here only
    because both control crops are outside the page's region list.
    """

    def step(tokens: Sequence[int]) -> NDArray[np.float32]:
        return session.decode_step(hidden, tokens)

    return decode(greedy_generate(step), vocab)
