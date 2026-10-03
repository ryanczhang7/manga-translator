"""MT-020 C-4: what a run measures, checked against fontTools read directly.

`measure_run` is what AC-1's containment and AC-4's feasibility both rest on, so
its two numbers are pinned against an independent reading of the file: the
advance as the plain `hmtx` sum (no kerning, no GPOS), the ink as BoundsPen
bounds flipped to y-down.
"""

from __future__ import annotations

import _typeset_oracle as oracle
import pytest

from mangatl.typeset.font import Faces, MissingGlyph, load_faces
from mangatl.typeset.measure import RunMetrics, measure_run

KEYS = ("regular", "italic", "bold", "bold_italic")

#: "AV" and "To" are classic kerning pairs: a kerned advance would differ from
#: the plain hmtx sum this compares against.
SAMPLE = "AV To, Wait\u2026 \u201cHey!\u201d"


@pytest.fixture(scope="module")
def faces() -> Faces:
    return load_faces()


@pytest.mark.parametrize("key", KEYS)
def test_advance_is_the_plain_hmtx_sum_scaled_to_the_size(faces: Faces, key: str) -> None:
    metrics = measure_run(SAMPLE, faces[key], 30.0)
    assert isinstance(metrics, RunMetrics)
    assert metrics.advance == pytest.approx(oracle.advance_px(SAMPLE, key, 30.0), rel=1e-12)


@pytest.mark.parametrize("key", ["regular", "bold"])
def test_ink_is_the_union_of_glyph_bounds_with_y_growing_down(faces: Faces, key: str) -> None:
    metrics = measure_run("Hg", faces[key], 40.0)
    expected = oracle.ink_px("Hg", key, 40.0)
    assert expected is not None
    assert metrics.ink == pytest.approx(expected, rel=1e-12, abs=1e-9)
    # y down: the cap of H is above the baseline (negative), the tail of g below.
    assert metrics.ink is not None
    assert metrics.ink[1] < 0 < metrics.ink[3]


def test_a_space_has_an_advance_and_no_ink(faces: Faces) -> None:
    metrics = measure_run(" ", faces["regular"], 20.0)
    assert metrics.advance == pytest.approx(oracle.advance_px(" ", "regular", 20.0), rel=1e-12)
    assert metrics.advance > 0
    assert metrics.ink is None


def test_the_empty_string_measures_zero_with_no_ink(faces: Faces) -> None:
    assert measure_run("", faces["regular"], 20.0) == RunMetrics(advance=0.0, ink=None)


@pytest.mark.parametrize("key", KEYS)
def test_a_character_the_face_lacks_raises_missing_glyph_naming_it(faces: Faces, key: str) -> None:
    # Hiragana: what an untranslated line would leak. Checked absent from the
    # file first, so this is a fact about the font and not an assumption.
    assert 0x3042 not in oracle.cmap(key)
    with pytest.raises(MissingGlyph) as excinfo:
        measure_run("ok \u3042", faces[key], 20.0)
    assert excinfo.value.char == "\u3042"
    assert excinfo.value.face == key
