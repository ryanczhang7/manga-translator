"""MT-076 AC-1..AC-6: the notices the installer carries, judged in the repository.

**What is judged.** The committed files under `packaging/notices/` - the two
licence texts (AC-1, AC-1b), `notices.json` (AC-5) and the generated
`THIRD_PARTY_NOTICES.txt` (AC-2, AC-3, AC-4, AC-6) - and the generator
`packaging/build_notices.py` that is the only writer of the last one. The built
tree's copy of the same files is `tests/frozen/test_built_tree.py`'s.

**Settled values are read out of the story, never derived.** The two SHA-256
values and byte counts are AC-1/AC-1b (the PO's measurement, PO-3); the
detector's `corresponding_source` and `training_data` strings are Contract
block 1's; the header paragraph and the label padding are block 2's. The
manifest is read with `json`, not with the code under test, so an oracle here
never agrees with the implementation by construction.

**The script is a script, not a package**: it is loaded by path with
`importlib.util.spec_from_file_location`, as `tests/core/test_fetch_models.py`
does. It is loaded ONCE, at module level, so its absence is a single
collection error naming `packaging/build_notices.py` and nothing else. The
module is registered in `sys.modules` before it executes: `dataclasses` looks
the defining module up there to resolve string annotations, and a
`@dataclass` in an unregistered module raises at class creation.

**`main` is redirected through the module's own globals.** `main` reads
`MANIFEST`, `NOTICES` and `OUTPUT` from the module at call time (Contract
block 1, amended A-1), so `monkeypatch.setattr(module, "OUTPUT", tmp)` points
the write path at a scratch file and the committed tree is never written.

What these tests do NOT constrain: what `main` prints on success, whether
`render` builds its text by lines or by template, the drift message for a name
the MANIFEST lists twice (block 1 gives a message only for notices.json), the
message for a name listed three or more times, and where a "twice" line sits
relative to the missing/extra lines.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import _settled_models as settled
import pytest

from mangatl.about import ABOUT_TEXT
from mangatl.models.manifest import ModelEntry, load_manifest

PACKAGING: Final = settled.REPO_ROOT / "packaging"
NOTICES_DIR: Final = PACKAGING / "notices"
NOTICES_JSON: Final = NOTICES_DIR / "notices.json"
OUTPUT: Final = NOTICES_DIR / "THIRD_PARTY_NOTICES.txt"
SCRIPT: Final = PACKAGING / "build_notices.py"


def _load_script() -> ModuleType:
    """`packaging/build_notices.py`, loaded by path under a private name."""
    if not SCRIPT.is_file():
        raise FileNotFoundError(f"{SCRIPT} does not exist (MT-076 Contract block 1)")
    name = "_mt076_build_notices"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


build_notices = _load_script()


# -- settled values, transcribed from the story --------------------------------------

#: AC-1 / AC-1b and PO-3: name -> (SHA-256 of the raw bytes, byte count).
LICENCE_TEXTS: Final = {
    "GPL-3.0.txt": ("3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986", 35149),
    "Apache-2.0.txt": ("cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30", 11358),
}

#: AC-6: `packaging/notices/` holds these and nothing else.
NOTICE_FILES: Final = frozenset(
    {"THIRD_PARTY_NOTICES.txt", "GPL-3.0.txt", "Apache-2.0.txt", "notices.json"}
)

#: Contract block 1's notices.json, in its order.
NOTICE_NAMES: Final = (
    "comic-text-detector",
    "manga-ocr-encoder",
    "manga-ocr-decoder",
    "manga-ocr-vocab",
    "lama",
)

DETECTOR_EXPORT: Final = (
    "https://huggingface.co/mayocream/comic-text-detector-onnx/tree/"
    "a5d67ec772adef819ef5b0e7aa701fcf4c8bf74a"
)
#: Contract block 1, the detector's `corresponding_source`, verbatim.
DETECTOR_CORRESPONDING_SOURCE: Final = (
    "https://github.com/dmMaze/comic-text-detector (the model definition and training code);"
    f" the conveyed weights are the ONNX export at {DETECTOR_EXPORT}"
)
#: AC-3, the sentence that indicates Manga109-s clearly.
MANGA109_SENTENCE: Final = (
    "This detector was trained in part on the Manga109-s dataset"
    " (https://manga109.github.io/manga109-project-website/en/index.html)."
)
#: AC-3 / block 1, the upstream training statement as quoted.
UPSTREAM_TRAINING: Final = (
    'Upstream states: "All models were trained on around 13 thousand anime & comic style'
    " images, 1/3 from Manga109-s, 1/3 from DCM, and 1/3 are synthetic data in a weak"
    ' supervision manner due to the lack of available high-quality annotations."'
)
#: Contract block 1, the detector's `training_data`, verbatim.
DETECTOR_TRAINING_DATA: Final = f"{MANGA109_SENTENCE} {UPSTREAM_TRAINING}"

#: Contract block 2's opening paragraph, line for line.
HEADER: Final = (
    "THIRD-PARTY NOTICES for mangatl\n"
    "\n"
    "This application bundles the model weights and the font listed below. Each is\n"
    "conveyed under its own licence; the full licence texts named here ship beside\n"
    "this file. This file was generated from packaging/models.json and\n"
    "packaging/notices/notices.json by packaging/build_notices.py, and it is an\n"
    "engineer's reading of the licences, not legal advice (architecture.md D13).\n"
)

#: Block 2: labels padded to the width of `Corresponding source:` plus one space.
LABEL_WIDTH: Final = 22

STALE: Final = "THIRD_PARTY_NOTICES.txt is stale; run: uv run python packaging/build_notices.py"


# -- an oracle for block 2, written from the contract, sharing nothing with render ---


def _label(label: str, value: str) -> str:
    return f"{label:<{LABEL_WIDTH}}{value}"


def _expected_text(
    entries: list[dict[str, Any]], notices: list[dict[str, Any]], about_text: str
) -> str:
    by_name = {notice["name"]: notice for notice in notices}
    parts = [HEADER]
    for entry in entries:
        notice = by_name[entry["name"]]
        lines = [
            f"== {entry['name']} ({entry['role']}) ==",
            _label("File:", f"models/{entry['path']}"),
            _label(
                "Source:", f"https://huggingface.co/{entry['repo']} at revision {entry['revision']}"
            ),
            _label("SHA-256:", entry["sha256"]),
            _label("Licence:", entry["licence"]),
            _label("Licence text:", notice["licence_text"]),
            _label("Upstream:", notice["upstream"]),
        ]
        if notice["corresponding_source"]:
            lines.append(_label("Corresponding source:", notice["corresponding_source"]))
        if notice["training_data"]:
            lines.append(_label("Training data:", notice["training_data"]))
        parts.append("\n".join(lines) + "\n")
    parts.append("== Lettering font ==\n" + about_text)
    return "\n".join(parts)


def _manifest_json() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = json.loads(settled.MANIFEST.read_text("utf-8"))["models"]
    return entries


def _notices_json() -> list[dict[str, Any]]:
    notices: list[dict[str, Any]] = json.loads(NOTICES_JSON.read_text("utf-8"))["notices"]
    return notices


def _render_real() -> str:
    text: str = build_notices.render(
        load_manifest(settled.MANIFEST), build_notices.load_notices(NOTICES_JSON), ABOUT_TEXT
    )
    return text


def _blocks(text: str) -> dict[str, str]:
    """Header line (without `== `/` ==`) -> the block's text up to the next header."""
    blocks: dict[str, str] = {}
    for chunk in text.split("\n== ")[1:]:
        head, _, body = chunk.partition(" ==\n")
        blocks[head] = body
    return blocks


def _entry(name: str, role: str = "ocr", **fields: Any) -> ModelEntry:
    values: dict[str, Any] = {
        "repo": f"org/{name}",
        "revision": "0" * 40,
        "file": f"{name}.onnx",
        "path": f"{name}.onnx",
        "sha256": "a" * 64,
        "bytes": 1,
        "licence": "Apache-2.0",
    }
    values.update(fields)
    return ModelEntry(name=name, role=role, **values)


def _notice(name: str, **fields: str) -> Any:
    values = {
        "upstream": f"https://github.com/upstream/{name}",
        "corresponding_source": "",
        "training_data": "",
        "licence_text": "Apache-2.0.txt",
    }
    values.update(fields)
    return build_notices.Notice(name=name, **values)


@pytest.fixture(params=["committed", "rendered"])
def notices_text(request: pytest.FixtureRequest) -> str:
    """AC-2..AC-4 hold over the committed file AND over the rendering of the real inputs."""
    if request.param == "committed":
        assert OUTPUT.is_file(), f"{OUTPUT} is not committed (AC-6, PO-4)"
        return OUTPUT.read_bytes().decode("utf-8")
    return _render_real()


# -- AC-1 / AC-1b: the licence texts, byte for byte -----------------------------------


@pytest.mark.parametrize("name", sorted(LICENCE_TEXTS))
def test_the_committed_licence_text_is_the_canonical_text_byte_for_byte(name: str) -> None:
    path = NOTICES_DIR / name
    expected_sha, expected_size = LICENCE_TEXTS[name]

    assert path.is_file(), f"{path} is missing"
    data = path.read_bytes()
    assert b"\r" not in data, f"{name} carries CR bytes: git or an editor rewrote its endings"
    assert len(data) == expected_size, f"{name} is {len(data)} bytes, not {expected_size}"
    assert hashlib.sha256(data).hexdigest() == expected_sha


def test_the_notices_directory_holds_the_four_files_and_nothing_else() -> None:
    """The spec ships the directory whole (AC-8), so whatever sits here ships."""
    present = {path.name for path in NOTICES_DIR.iterdir()}

    assert present == NOTICE_FILES


# -- notices.json: Contract block 1's shape ------------------------------------------


def test_notices_json_names_the_five_models_in_block_ones_order() -> None:
    assert tuple(notice["name"] for notice in _notices_json()) == NOTICE_NAMES


def test_every_notice_entry_has_the_five_string_keys_and_names_a_shipped_licence_text() -> None:
    keys = {"name", "upstream", "corresponding_source", "training_data", "licence_text"}
    for notice in _notices_json():
        assert set(notice) == keys, notice
        assert all(isinstance(value, str) for value in notice.values()), notice
        assert notice["licence_text"] in LICENCE_TEXTS, notice


def test_notices_json_puts_each_entry_on_its_own_line_so_one_can_be_deleted() -> None:
    """Block 1: one compact object per line, and the last entry is not the one
    DV-1 deletes - so `sed '/"name": "manga-ocr-vocab"/d'` leaves valid JSON."""
    lines = NOTICES_JSON.read_text("utf-8").splitlines()
    for name in NOTICE_NAMES:
        holding = [line for line in lines if f'"name": "{name}"' in line]
        assert len(holding) == 1, f"{name!r} is on {len(holding)} lines"

    without_vocab = [line for line in lines if '"name": "manga-ocr-vocab"' not in line]
    remaining = json.loads("\n".join(without_vocab))["notices"]
    assert [notice["name"] for notice in remaining] == [
        "comic-text-detector",
        "manga-ocr-encoder",
        "manga-ocr-decoder",
        "lama",
    ]


def test_load_notices_returns_the_entries_in_file_order_with_every_field() -> None:
    loaded = build_notices.load_notices(NOTICES_JSON)

    assert isinstance(loaded, tuple)
    assert tuple(notice.name for notice in loaded) == NOTICE_NAMES
    detector = loaded[0]
    assert detector == build_notices.Notice(
        name="comic-text-detector",
        upstream="https://github.com/dmMaze/comic-text-detector",
        corresponding_source=DETECTOR_CORRESPONDING_SOURCE,
        training_data=DETECTOR_TRAINING_DATA,
        licence_text="GPL-3.0.txt",
    )
    for notice in loaded[1:4]:
        assert notice == build_notices.Notice(
            notice.name, "https://github.com/kha-white/manga-ocr", "", "", "Apache-2.0.txt"
        )
    assert loaded[4] == build_notices.Notice(
        "lama", "https://github.com/advimman/lama", "", "", "Apache-2.0.txt"
    )


def test_the_notice_dataclass_is_frozen() -> None:
    notice = _notice("x")

    with pytest.raises(AttributeError):
        notice.name = "y"


# -- AC-2 / AC-3: the GPL component identified, its source offered, Manga109-s named ---


def test_the_detector_block_identifies_the_gpl_component_and_offers_its_source(
    notices_text: str,
) -> None:
    block = _blocks(notices_text)["comic-text-detector (detect)"]
    licence = _manifest_json()[0]["licence"]
    needles = [
        "comic-text-detector.onnx",
        licence,
        "https://github.com/dmMaze/comic-text-detector",
        "mayocream/comic-text-detector-onnx",
        "a5d67ec772adef819ef5b0e7aa701fcf4c8bf74a",
        "1a86ace74961413cbd650002e7bb4dcec4980ffa21b2f19b86933372071d718f",
        f"\nCorresponding source: {DETECTOR_CORRESPONDING_SOURCE}\n",
    ]

    assert licence.startswith("GPL-3.0 "), licence
    missing = [needle for needle in needles if needle not in block]
    assert missing == [], f"the comic-text-detector block lacks {missing}"


def test_the_detector_block_indicates_manga109s_clearly(notices_text: str) -> None:
    block = _blocks(notices_text)["comic-text-detector (detect)"]

    assert MANGA109_SENTENCE in block
    assert UPSTREAM_TRAINING in block
    assert f"\nTraining data:        {DETECTOR_TRAINING_DATA}\n" in block


# -- AC-4: one block per manifest entry, in manifest order, and the font --------------


def test_every_manifest_entry_has_a_block_carrying_its_fields_verbatim(notices_text: str) -> None:
    blocks = _blocks(notices_text)
    problems = []
    for entry in _manifest_json():
        head = f"{entry['name']} ({entry['role']})"
        if head not in blocks:
            problems.append(f"no block headed {head!r}")
            continue
        for key in ("repo", "revision", "sha256", "path", "licence"):
            if str(entry[key]) not in blocks[head]:
                problems.append(f"{head}: {key} {entry[key]!r} is not in its block")

    assert len(_manifest_json()) == 5
    assert problems == [], "\n".join(problems)


def test_the_blocks_are_in_manifest_order_then_the_font(notices_text: str) -> None:
    heads = list(_blocks(notices_text))
    expected = [f"{entry['name']} ({entry['role']})" for entry in _manifest_json()]

    assert heads == [*expected, "Lettering font"]


def test_the_lettering_font_section_is_the_about_text_verbatim_and_ends_the_file(
    notices_text: str,
) -> None:
    assert notices_text.endswith("\n== Lettering font ==\n" + ABOUT_TEXT)


def test_the_rendering_is_block_twos_shape_exactly(notices_text: str) -> None:
    """Block 2: header paragraph, `== name (role) ==`, labels padded to 22,
    `File: models/{path}`, `Source: https://huggingface.co/{repo} at revision
    {revision}`, empty lines omitted, ABOUT_TEXT last. Built here from the
    manifest and notices.json read as JSON."""
    expected = _expected_text(_manifest_json(), _notices_json(), ABOUT_TEXT)

    assert notices_text == expected


def test_no_line_carries_trailing_whitespace_or_a_carriage_return(notices_text: str) -> None:
    assert "\r" not in notices_text
    offenders = [line for line in notices_text.split("\n") if line != line.rstrip()]
    assert offenders == []


# -- render on synthetic inputs: block 2's rules, one at a time ------------------------


def test_render_omits_the_corresponding_source_and_training_lines_when_empty() -> None:
    text = build_notices.render([_entry("solo")], [_notice("solo")], "About\n")

    assert "Corresponding source:" not in text
    assert "Training data:" not in text
    assert text == _expected_text(
        [
            {
                "name": "solo",
                "role": "ocr",
                "repo": "org/solo",
                "revision": "0" * 40,
                "path": "solo.onnx",
                "sha256": "a" * 64,
                "licence": "Apache-2.0",
            }
        ],
        [
            {
                "name": "solo",
                "upstream": "https://github.com/upstream/solo",
                "corresponding_source": "",
                "training_data": "",
                "licence_text": "Apache-2.0.txt",
            }
        ],
        "About\n",
    )


def test_render_follows_manifest_order_not_notices_order() -> None:
    entries = [_entry("b"), _entry("a")]
    notices = [_notice("a"), _notice("b")]

    heads = list(_blocks(build_notices.render(entries, notices, "About\n")))

    assert heads == ["b (ocr)", "a (ocr)", "Lettering font"]


def test_render_writes_the_about_text_it_is_given_including_its_last_newline() -> None:
    text = build_notices.render([_entry("a")], [_notice("a")], "Font line one\nline two\n")

    assert text.endswith("\n\n== Lettering font ==\nFont line one\nline two\n")


# -- AC-5: the drift rule, the negative control ---------------------------------------


def test_drift_is_empty_when_the_two_name_sets_agree() -> None:
    assert build_notices.drift(["a", "b", "c"], ["c", "a", "b"]) == []


def test_drift_is_empty_for_two_empty_lists() -> None:
    assert build_notices.drift([], []) == []


def test_drift_names_a_manifest_entry_with_no_notice() -> None:
    assert build_notices.drift(["a", "b", "c"], ["a", "c"]) == [
        "manifest entry 'b' has no entry in notices.json"
    ]


def test_drift_names_a_notice_entry_with_no_manifest_entry() -> None:
    assert build_notices.drift(["a", "c"], ["a", "x", "c"]) == [
        "notices.json entry 'x' is not in the manifest"
    ]


def test_drift_lists_both_ways_manifest_order_first_then_notices_order() -> None:
    assert build_notices.drift(["a", "m2", "b", "m1"], ["n2", "a", "b", "n1"]) == [
        "manifest entry 'm2' has no entry in notices.json",
        "manifest entry 'm1' has no entry in notices.json",
        "notices.json entry 'n2' is not in the manifest",
        "notices.json entry 'n1' is not in the manifest",
    ]


def test_drift_names_a_notice_listed_twice() -> None:
    assert build_notices.drift(["a", "b"], ["a", "b", "b"]) == ["notices.json names 'b' twice"]


def test_render_refuses_to_omit_a_model_and_carries_the_drift_lines() -> None:
    entries = [_entry("a"), _entry("b")]

    with pytest.raises(build_notices.NoticeDrift) as raised:
        build_notices.render(entries, [_notice("a"), _notice("z")], "About\n")

    assert str(raised.value) == (
        "manifest entry 'b' has no entry in notices.json\n"
        "notices.json entry 'z' is not in the manifest"
    )


def test_notice_drift_is_an_exception() -> None:
    assert issubclass(build_notices.NoticeDrift, Exception)


def test_the_real_manifest_and_the_real_notices_do_not_drift() -> None:
    """O-5, on the committed files: every manifest model has a notice and every
    notice a model. Names read with `json`, so the comparison does not lean on
    `load_notices` or `load_manifest`."""
    manifest_names = [entry["name"] for entry in _manifest_json()]
    notice_names = [notice["name"] for notice in _notices_json()]

    lines = build_notices.drift(manifest_names, notice_names)

    assert lines == [], "\n".join(lines)
    assert sorted(manifest_names) == sorted(notice_names)


# -- AC-6: the committed file is the generation, byte for byte -------------------------


def test_the_committed_notices_file_is_the_rendering_byte_for_byte() -> None:
    assert OUTPUT.is_file(), f"{OUTPUT} is not committed (AC-6, PO-4)"

    assert OUTPUT.read_bytes() == _render_real().encode("utf-8"), (
        "THIRD_PARTY_NOTICES.txt is stale; run: uv run python packaging/build_notices.py"
    )


def test_the_script_paths_are_the_ones_beside_it() -> None:
    assert Path(build_notices.HERE) == PACKAGING
    assert Path(build_notices.MANIFEST) == settled.MANIFEST
    assert Path(build_notices.NOTICES) == NOTICES_JSON
    assert Path(build_notices.OUTPUT) == OUTPUT


def test_check_passes_on_the_committed_tree(capsys: pytest.CaptureFixture[str]) -> None:
    assert build_notices.main(["--check"]) == 0
    assert capsys.readouterr().err == ""


def test_check_fails_naming_the_command_when_the_output_is_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stale = tmp_path / "THIRD_PARTY_NOTICES.txt"
    stale.write_bytes(OUTPUT.read_bytes() + b"one more line\n")
    monkeypatch.setattr(build_notices, "OUTPUT", stale)

    assert build_notices.main(["--check"]) == 1
    assert capsys.readouterr().err.splitlines() == [STALE]
    assert stale.read_bytes().endswith(b"one more line\n"), "--check must not rewrite the file"


def test_main_writes_the_rendering_to_output_as_utf8_with_lf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "THIRD_PARTY_NOTICES.txt"
    monkeypatch.setattr(build_notices, "OUTPUT", target)

    assert build_notices.main([]) == 0
    written = target.read_bytes()
    assert written == _render_real().encode("utf-8")
    assert written == OUTPUT.read_bytes()
    assert b"\r\n" not in written


def test_main_refuses_on_drift_names_the_model_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """DV-1's shape on a scratch copy: one notices.json line deleted."""
    lines = NOTICES_JSON.read_text("utf-8").splitlines(keepends=True)
    short = tmp_path / "notices.json"
    short.write_text(
        "".join(line for line in lines if '"name": "manga-ocr-vocab"' not in line),
        encoding="utf-8",
    )
    target = tmp_path / "THIRD_PARTY_NOTICES.txt"
    monkeypatch.setattr(build_notices, "NOTICES", short)
    monkeypatch.setattr(build_notices, "OUTPUT", target)

    assert build_notices.main([]) == 1
    assert capsys.readouterr().err.splitlines() == [
        "build_notices: manifest entry 'manga-ocr-vocab' has no entry in notices.json"
    ]
    assert not target.exists()

    target.write_bytes(OUTPUT.read_bytes())
    assert build_notices.main(["--check"]) == 1
    assert capsys.readouterr().err.splitlines() == [
        "build_notices: manifest entry 'manga-ocr-vocab' has no entry in notices.json"
    ]
