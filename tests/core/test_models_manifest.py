"""MT-024 AC-5 (first half) and C-2: `mangatl.models.manifest`.

`verify_bundled_models(root, manifest=None)` returns `None` when every entry of
the manifest is present under `root` with the manifest's SHA-256, and raises
`ModelHashMismatch` for the **first entry in manifest order** that is not, with
the message `"<path>: missing"` or `"<path>: sha256 <actual> != <expected>"`.
`<path>` is the manifest's own `path` string - forward slashes, as written in
`models.json` - never an OS path.

Every directory here is built by the test out of a few small files whose
hashes the test computes with `hashlib` itself; nothing reads a real weight.
The one real-file case is the manifest parse at the bottom, which reads
`packaging/models.json` (a few KB) and compares it with the story's settled
values.

RED: `mangatl.models.manifest` does not exist. Each test imports it in its
body (`_manifest()`), so the file collects and every test fails on that
import, one by one.

What these tests do NOT constrain: what `load_manifest` does with a malformed
or missing manifest, whether `verify_bundled_models` also checks `bytes`,
whether it stops reading files after the first mismatch, and what
`ModelHashMismatch` derives from beyond `Exception`.
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib
import json
from pathlib import Path
from types import ModuleType

import _settled_models as settled
import pytest


def _manifest() -> ModuleType:
    return importlib.import_module("mangatl.models.manifest")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _entry(path: str, data: bytes, *, name: str | None = None) -> dict[str, object]:
    return {
        "name": name or path.replace("/", "-"),
        "role": "detect",
        "repo": "example/repo",
        "revision": "0" * 40,
        "file": path.rsplit("/", 1)[-1],
        "path": path,
        "sha256": _sha(data),
        "bytes": len(data),
        "licence": "Apache-2.0",
    }


#: Three small files, one of them in a subdirectory: the layout's shape.
FILES: dict[str, bytes] = {
    "detector.onnx": b"detector weights",
    "manga-ocr/vocab.txt": b"[PAD]\n[UNK]\n",
    "lama.onnx": b"\x00\x01\x02 lama",
}


def _models_dir(
    root: Path,
    files: dict[str, bytes] = FILES,
    *,
    on_disk: dict[str, bytes | None] | None = None,
    manifest_at: Path | None = None,
) -> Path:
    """`root` holding `files` and a manifest for them.

    `on_disk` overrides what is actually written: `None` for a file that is
    left out, other bytes for a file whose content differs from the manifest.
    The manifest goes to `root/models.json` unless `manifest_at` says otherwise.
    """
    root.mkdir(parents=True, exist_ok=True)
    written = dict(files)
    written.update(on_disk or {})
    for path, data in written.items():
        if data is None:
            continue
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    manifest = {"models": [_entry(path, data) for path, data in files.items()]}
    (manifest_at or root / "models.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


# -- the module's names --------------------------------------------------------


def test_the_manifest_file_is_called_models_json() -> None:
    assert _manifest().MANIFEST_FILENAME == "models.json"


def test_a_model_entry_carries_the_nine_fields_of_the_manifest_in_order() -> None:
    entry_type = _manifest().ModelEntry
    assert dataclasses.is_dataclass(entry_type)
    assert tuple(field.name for field in dataclasses.fields(entry_type)) == settled.ENTRY_FIELDS


def test_a_model_entry_is_frozen() -> None:
    entry = _manifest().ModelEntry(**_entry("a.onnx", b"a"))
    with pytest.raises(dataclasses.FrozenInstanceError):
        entry.sha256 = "0" * 64


def test_a_hash_mismatch_is_an_exception_a_caller_can_catch_by_name() -> None:
    assert issubclass(_manifest().ModelHashMismatch, Exception)


# -- load_manifest ---------------------------------------------------------------


def test_loading_a_manifest_returns_one_entry_per_model_in_file_order(tmp_path: Path) -> None:
    module = _manifest()
    root = _models_dir(tmp_path / "models")

    entries = module.load_manifest(root / "models.json")

    assert type(entries) is tuple, f"load_manifest returned a {type(entries).__name__}"
    assert entries == tuple(module.ModelEntry(**_entry(p, d)) for p, d in FILES.items())
    assert [entry.path for entry in entries] == list(FILES)
    assert all(type(entry.bytes) is int for entry in entries)


def test_loading_a_manifest_with_no_models_returns_an_empty_tuple(tmp_path: Path) -> None:
    manifest = tmp_path / "models.json"
    manifest.write_text('{"models": []}', encoding="utf-8")

    assert _manifest().load_manifest(manifest) == ()


def test_the_real_manifest_loads_as_the_five_settled_entries() -> None:
    """C-1's JSON, through the one parser the build and the app share. The
    oracle is `_settled_models`, transcribed from the story; DV-1 alters one
    `sha256` in `packaging/models.json` and this goes red naming that entry."""
    module = _manifest()
    assert settled.MANIFEST.is_file(), f"{settled.MANIFEST} does not exist (C-1)"

    entries = module.load_manifest(settled.MANIFEST)

    assert entries == tuple(module.ModelEntry(**entry) for entry in settled.SETTLED_ENTRIES)


# -- sha256_of ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "size",
    [0, 1, (1 << 20) - 1, 1 << 20, (1 << 20) + 1, (5 << 20) // 2],
    ids=["empty", "one byte", "a chunk less one", "one chunk", "a chunk and one", "2.5 MiB"],
)
def test_sha256_of_a_file_is_the_lowercase_hex_digest_of_its_bytes(
    tmp_path: Path, size: int
) -> None:
    # The sizes straddle C-2's 1 MiB chunk: a chunked reader that drops or
    # repeats the last partial chunk fails at one of them.
    data = bytes((index * 31 + 7) % 251 for index in range(size))
    path = tmp_path / "blob.bin"
    path.write_bytes(data)

    assert _manifest().sha256_of(path) == hashlib.sha256(data).hexdigest()


# -- verify_bundled_models ---------------------------------------------------------


def test_a_models_directory_whose_every_file_verifies_returns_none(tmp_path: Path) -> None:
    root = _models_dir(tmp_path / "models")

    assert _manifest().verify_bundled_models(root) is None


def test_the_manifest_defaults_to_models_json_inside_the_models_directory(
    tmp_path: Path,
) -> None:
    # A missing file is reported only if the default manifest was read: with
    # no manifest consulted, nothing would be found missing.
    module = _manifest()
    root = _models_dir(tmp_path / "models", on_disk={"lama.onnx": None})

    with pytest.raises(module.ModelHashMismatch) as raised:
        module.verify_bundled_models(root)

    assert str(raised.value) == "lama.onnx: missing"


def test_an_explicit_manifest_is_the_one_that_is_read(tmp_path: Path) -> None:
    module = _manifest()
    elsewhere = tmp_path / "elsewhere.json"
    root = _models_dir(tmp_path / "models", manifest_at=elsewhere)
    assert not (root / "models.json").exists()

    assert module.verify_bundled_models(root, elsewhere) is None
    assert module.verify_bundled_models(root, manifest=elsewhere) is None


def test_an_explicit_manifest_wins_over_one_inside_the_directory(tmp_path: Path) -> None:
    module = _manifest()
    root = _models_dir(tmp_path / "models")
    stricter = tmp_path / "stricter.json"
    extra = dict(FILES, **{"absent.onnx": b"never written"})
    stricter.write_text(
        json.dumps({"models": [_entry(p, d) for p, d in extra.items()]}), encoding="utf-8"
    )

    with pytest.raises(module.ModelHashMismatch) as raised:
        module.verify_bundled_models(root, stricter)

    assert str(raised.value) == "absent.onnx: missing"


def test_a_missing_file_is_named_and_said_to_be_missing(tmp_path: Path) -> None:
    module = _manifest()
    root = _models_dir(tmp_path / "models", on_disk={"manga-ocr/vocab.txt": None})

    with pytest.raises(module.ModelHashMismatch) as raised:
        module.verify_bundled_models(root)

    assert str(raised.value) == "manga-ocr/vocab.txt: missing"


def test_a_file_with_other_bytes_is_named_with_the_hash_it_had_and_the_one_expected(
    tmp_path: Path,
) -> None:
    module = _manifest()
    tampered = b"[PAD]\n[UNK]\n!"  # one byte appended: the frozen control's alteration
    root = _models_dir(tmp_path / "models", on_disk={"manga-ocr/vocab.txt": tampered})

    with pytest.raises(module.ModelHashMismatch) as raised:
        module.verify_bundled_models(root)

    expected = _sha(FILES["manga-ocr/vocab.txt"])
    assert str(raised.value) == f"manga-ocr/vocab.txt: sha256 {_sha(tampered)} != {expected}"


def test_a_file_of_the_right_size_and_the_wrong_bytes_is_still_a_mismatch(
    tmp_path: Path,
) -> None:
    # The hash is the check, not the size: same length, one byte flipped.
    module = _manifest()
    original = FILES["detector.onnx"]
    flipped = bytes([original[0] ^ 1]) + original[1:]
    root = _models_dir(tmp_path / "models", on_disk={"detector.onnx": flipped})

    with pytest.raises(module.ModelHashMismatch) as raised:
        module.verify_bundled_models(root)

    assert str(raised.value) == f"detector.onnx: sha256 {_sha(flipped)} != {_sha(original)}"


def test_the_first_failing_entry_in_manifest_order_is_the_one_reported(tmp_path: Path) -> None:
    """Two failures, in an order that is neither alphabetical nor the order the
    files were written: only manifest order picks `z-first.onnx`."""
    module = _manifest()
    files = {"z-first.onnx": b"z", "a-second.onnx": b"a", "m-ok.onnx": b"m"}
    root = _models_dir(
        tmp_path / "models",
        files,
        on_disk={"a-second.onnx": None, "z-first.onnx": b"zz"},
    )

    with pytest.raises(module.ModelHashMismatch) as raised:
        module.verify_bundled_models(root)

    assert str(raised.value) == f"z-first.onnx: sha256 {_sha(b'zz')} != {_sha(b'z')}"


def test_a_failure_after_good_entries_is_still_found(tmp_path: Path) -> None:
    module = _manifest()
    root = _models_dir(tmp_path / "models", on_disk={"lama.onnx": b"other"})

    with pytest.raises(module.ModelHashMismatch) as raised:
        module.verify_bundled_models(root)

    assert str(raised.value) == f"lama.onnx: sha256 {_sha(b'other')} != {_sha(FILES['lama.onnx'])}"


def test_a_manifest_with_no_models_verifies_an_empty_directory(tmp_path: Path) -> None:
    root = tmp_path / "models"
    root.mkdir()
    (root / "models.json").write_text('{"models": []}', encoding="utf-8")

    assert _manifest().verify_bundled_models(root) is None


def test_verifying_writes_nothing(tmp_path: Path) -> None:
    root = _models_dir(tmp_path / "models", on_disk={"lama.onnx": None})
    before = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
    module = _manifest()

    with pytest.raises(module.ModelHashMismatch):
        module.verify_bundled_models(root)

    assert sorted(path.relative_to(root).as_posix() for path in root.rglob("*")) == before
