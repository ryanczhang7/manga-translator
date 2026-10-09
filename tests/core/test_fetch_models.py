"""MT-024 AC-1 and C-1: `packaging/fetch_models.py` and `packaging/models.json`.

**The fetch, against a fake opener.** `fetch_all(manifest, target, *,
opener=urlopen)` is driven with an opener that serves bytes of the test's
choosing, so every branch - the URL, the `.part` file, the hash checked while
streaming, the warm cache, the mismatch that leaves nothing behind - runs on
every machine with no network. The mismatch branch is the negative control
C-1 asks for and it runs everywhere.

The fake opener accepts what `urllib.request.urlopen` accepts - a URL string or
a `Request`, plus any keyword (`timeout=`) - and returns a context-managed
response with `read(size)`, `status`, `getcode()` and `headers`. Its `read`
serves at most 7 bytes a call whatever size is asked for (`http.client` may
return short reads), so a reader that stops after one `read` truncates.

**The script is a script, not a package**: it is loaded by path with
`importlib.util.spec_from_file_location`, as `uv run python
packaging/fetch_models.py` would run it.

**The real manifest**: parsed with `json` (not with the code under test) and
compared with `_settled_models`, transcribed from the story; its `path` column
is compared with the layout constants `build_pipeline` reads, so the manifest
cannot drift from C-6 of MT-036.

RED: neither `packaging/fetch_models.py` nor `packaging/models.json` exists.
Each test loads them in its body and fails on that absence, by name.

What these tests do NOT constrain: the chunk size, whether redirects are
followed by `urlopen` or by hand, the order of downloads, what `fetch_all`
does with the entries after a mismatch, and what `main` prints on success.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import urllib.request
from collections.abc import Callable
from pathlib import Path
from types import ModuleType, TracebackType
from typing import Any

import _settled_models as settled
import pytest

from mangatl.compose import DETECTOR_FILENAME, INPAINTER_FILENAME, OCR_SUBDIR
from mangatl.ocr.session import DECODER_FILENAME, ENCODER_FILENAME, VOCAB_FILENAME


def _script() -> ModuleType:
    """`packaging/fetch_models.py`, loaded by path under a private name."""
    path = settled.FETCH_SCRIPT
    assert path.is_file(), f"{path} does not exist (MT-024 C-1)"
    spec = importlib.util.spec_from_file_location("_mt024_fetch_models", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _mismatch() -> type[Exception]:
    """C-2's exception: the fetch and the app share one (C-1's last clause)."""
    from mangatl.models.manifest import ModelHashMismatch

    error: type[Exception] = ModelHashMismatch
    return error


# -- the fake opener -------------------------------------------------------------


class _Response(io.BytesIO):
    """An HTTP response body that hands out at most `chunk` bytes per read."""

    status = 200

    def __init__(self, data: bytes, on_read: Callable[[], None], chunk: int = 7) -> None:
        super().__init__(data)
        self._on_read = on_read
        self._chunk = chunk
        self.headers: dict[str, str] = {"Content-Length": str(len(data))}

    def read(self, size: int | None = -1) -> bytes:
        self._on_read()
        if size is None or size < 0:
            size = self._chunk
        return super().read(min(size, self._chunk))

    def read1(self, size: int | None = -1) -> bytes:
        return self.read(size)

    def readinto(self, buffer: Any) -> int:
        data = self.read(len(buffer))
        memoryview(buffer)[: len(data)] = data
        return len(data)

    def getcode(self) -> int:
        return self.status

    def __enter__(self) -> _Response:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


class _Opener:
    """Serves `served[url]`; records each URL asked for, and what the target
    directory looked like at every read after the first."""

    def __init__(self, served: dict[str, bytes], paths: dict[str, str], target: Path) -> None:
        self.served = served
        self.paths = paths
        self.target = target
        self.urls: list[str] = []
        self.during: list[tuple[str, bool, bool]] = []

    def __call__(self, request: str | urllib.request.Request, *args: Any, **kwargs: Any) -> Any:
        url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
        self.urls.append(url)
        assert url in self.served, f"fetch asked for {url}, which no manifest entry names"
        path = self.paths[url]
        reads = [0]

        def observe() -> None:
            reads[0] += 1
            if reads[0] > 1:
                part = self.target / f"{path}.part"
                final = self.target / path
                self.during.append((path, part.exists(), final.exists()))

        return _Response(self.served[url], observe)


def _url(entry: dict[str, object]) -> str:
    return f"https://huggingface.co/{entry['repo']}/resolve/{entry['revision']}/{entry['file']}"


def _entry(path: str, data: bytes, *, repo: str, revision: str, file: str) -> dict[str, object]:
    return {
        "name": path.replace("/", "-"),
        "role": "ocr",
        "repo": repo,
        "revision": revision,
        "file": file,
        "path": path,
        "sha256": _sha(data),
        "bytes": len(data),
        "licence": "Apache-2.0",
    }


#: Two entries: one at the top of the models directory, one in a subdirectory
#: whose `file` (the repository's name for it) differs from its `path`.
CONTENT = {
    "detector.onnx": b"the detector's weights, 41 bytes of them.",
    "manga-ocr/encoder_model.onnx": bytes(range(256)) * 3,
}
ENTRIES = [
    _entry(
        "detector.onnx",
        CONTENT["detector.onnx"],
        repo="someone/detector",
        revision="a" * 40,
        file="detector.onnx",
    ),
    _entry(
        "manga-ocr/encoder_model.onnx",
        CONTENT["manga-ocr/encoder_model.onnx"],
        repo="someone/ocr-ONNX",
        revision="b" * 40,
        file="onnx/encoder_model.onnx",
    ),
]


def _world(
    tmp_path: Path,
    *,
    serve: dict[str, bytes] | None = None,
    entries: list[dict[str, object]] = ENTRIES,
) -> tuple[Path, Path, _Opener]:
    """A manifest, an empty target directory, and an opener serving `serve`
    (by `path`; the manifest's own bytes by default)."""
    manifest = tmp_path / "models.json"
    manifest.write_text(json.dumps({"models": entries}), encoding="utf-8")
    target = tmp_path / "models"
    bodies = dict(CONTENT, **(serve or {}))
    served = {_url(entry): bodies[str(entry["path"])] for entry in entries}
    paths = {_url(entry): str(entry["path"]) for entry in entries}
    opener = _Opener(served, paths, target)
    return manifest, target, opener


# -- fetch_all -------------------------------------------------------------------


def test_every_entry_is_fetched_from_its_pinned_revision_on_hugging_face(tmp_path: Path) -> None:
    manifest, target, opener = _world(tmp_path)

    _script().fetch_all(manifest, target, opener=opener)

    assert sorted(opener.urls) == sorted(
        [
            "https://huggingface.co/someone/detector/resolve/" + "a" * 40 + "/detector.onnx",
            "https://huggingface.co/someone/ocr-ONNX/resolve/"
            + "b" * 40
            + "/onnx/encoder_model.onnx",
        ]
    ), f"fetched {opener.urls}"
    assert len(opener.urls) == 2, f"each file is fetched once: {opener.urls}"


def test_each_file_lands_at_its_manifest_path_with_the_served_bytes(tmp_path: Path) -> None:
    manifest, target, opener = _world(tmp_path)

    _script().fetch_all(manifest, target, opener=opener)

    for path, data in CONTENT.items():
        assert (target / path).read_bytes() == data, f"{path} does not hold what was served"
    left = sorted(p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file())
    assert left == sorted(CONTENT), f"the target holds {left}; a .part was left behind?"


def test_fetch_all_returns_the_paths_it_downloaded_in_manifest_order(tmp_path: Path) -> None:
    manifest, target, opener = _world(tmp_path)

    fetched = _script().fetch_all(manifest, target, opener=opener)

    assert fetched == [target / str(entry["path"]) for entry in ENTRIES]


def test_a_download_streams_into_a_part_file_and_only_then_takes_its_name(
    tmp_path: Path,
) -> None:
    """C-1: streamed to `{path}.part`, renamed to `{path}` only once the hash
    matches. Observed from inside the stream: at every read after the first,
    the `.part` exists and the final name does not."""
    manifest, target, opener = _world(tmp_path)

    _script().fetch_all(manifest, target, opener=opener)

    for path in CONTENT:
        seen = [(part, final) for p, part, final in opener.during if p == path]
        assert seen, f"{path} was read in one call; C-1 streams it"
        assert all(part and not final for part, final in seen), (
            f"while {path} streamed, (.part exists, final exists) was {seen};"
            " C-1 is (True, False) throughout"
        )


def test_a_file_already_present_with_the_right_hash_is_not_downloaded(tmp_path: Path) -> None:
    manifest, target, opener = _world(tmp_path)
    present = target / "detector.onnx"
    present.parent.mkdir(parents=True)
    present.write_bytes(CONTENT["detector.onnx"])

    fetched = _script().fetch_all(manifest, target, opener=opener)

    assert _url(ENTRIES[0]) not in opener.urls, (
        "detector.onnx was already present with its manifest hash and was downloaded"
        " again; C-1: a developer downloads 728 MB once, a warm CI cache not at all"
    )
    assert opener.urls == [_url(ENTRIES[1])]
    assert fetched == [target / "manga-ocr/encoder_model.onnx"]
    assert present.read_bytes() == CONTENT["detector.onnx"]


def test_a_warm_directory_fetches_nothing(tmp_path: Path) -> None:
    manifest, target, opener = _world(tmp_path)
    _script().fetch_all(manifest, target, opener=opener)
    opener.urls.clear()

    fetched = _script().fetch_all(manifest, target, opener=opener)

    assert opener.urls == []
    assert fetched == []


def test_a_file_present_with_the_wrong_hash_is_downloaded_again(tmp_path: Path) -> None:
    manifest, target, opener = _world(tmp_path)
    stale = target / "detector.onnx"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"an older export")

    _script().fetch_all(manifest, target, opener=opener)

    assert _url(ENTRIES[0]) in opener.urls
    assert stale.read_bytes() == CONTENT["detector.onnx"]


def test_bytes_that_do_not_match_the_manifest_raise_naming_the_file_and_both_hashes(
    tmp_path: Path,
) -> None:
    """The negative control C-1 asks for, on every machine: the opener serves
    other bytes for the subdirectory entry."""
    wrong = CONTENT["manga-ocr/encoder_model.onnx"] + b"!"
    manifest, target, opener = _world(tmp_path, serve={"manga-ocr/encoder_model.onnx": wrong})

    with pytest.raises(_mismatch()) as raised:
        _script().fetch_all(manifest, target, opener=opener)

    expected = _sha(CONTENT["manga-ocr/encoder_model.onnx"])
    assert str(raised.value) == (
        f"manga-ocr/encoder_model.onnx: sha256 {_sha(wrong)} != {expected}"
    )


def test_a_mismatch_leaves_neither_the_file_nor_its_part_behind(tmp_path: Path) -> None:
    wrong = b"not the detector"
    manifest, target, opener = _world(tmp_path, serve={"detector.onnx": wrong})

    with pytest.raises(_mismatch(), match=r"^detector.onnx: "):
        _script().fetch_all(manifest, target, opener=opener)

    assert not (target / "detector.onnx").exists(), "the mismatched bytes took the file's name"
    assert not (target / "detector.onnx.part").exists(), "the .part was left behind"


def test_a_mismatch_over_a_stale_file_does_not_leave_the_wrong_bytes_in_its_place(
    tmp_path: Path,
) -> None:
    manifest, target, opener = _world(tmp_path, serve={"detector.onnx": b"still wrong"})
    stale = target / "detector.onnx"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"an older export")

    with pytest.raises(_mismatch(), match=r"^detector.onnx: "):
        _script().fetch_all(manifest, target, opener=opener)

    assert not (target / "detector.onnx.part").exists()
    assert not stale.exists() or stale.read_bytes() != b"still wrong"


# -- main ------------------------------------------------------------------------


def test_main_exits_zero_when_every_file_verifies(tmp_path: Path) -> None:
    manifest, target, opener = _world(tmp_path)

    code = _script().main(["--manifest", str(manifest), "--target", str(target)], opener=opener)

    assert code == 0
    assert (target / "detector.onnx").read_bytes() == CONTENT["detector.onnx"]


def test_main_exits_one_naming_the_file_the_expected_hash_and_the_actual(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-1: *"a fetch whose bytes do not match the manifest exits non-zero
    naming the file, leaves no partial file behind, and no build runs"* - the
    gate command is `fetch && pyinstaller`, so exit 1 is what stops the build."""
    wrong = b"not the detector"
    manifest, target, opener = _world(tmp_path, serve={"detector.onnx": wrong})

    code = _script().main(["--manifest", str(manifest), "--target", str(target)], opener=opener)

    assert code == 1
    lines = capsys.readouterr().err.splitlines()
    message = f"detector.onnx: sha256 {_sha(wrong)} != {_sha(CONTENT['detector.onnx'])}"
    assert any(line.endswith(message) for line in lines), (
        f"stderr does not end a line with {message!r}: {lines}"
    )
    assert not (target / "detector.onnx").exists()
    assert not (target / "detector.onnx.part").exists()


def test_main_defaults_to_the_manifest_and_models_directory_beside_the_script(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no arguments: `packaging/models.json` into `packaging/models/`.
    `fetch_all` is replaced at the script's own name, so nothing is fetched."""
    module = _script()
    calls: list[tuple[Path, Path]] = []

    def recording(manifest: Path, target: Path, **options: object) -> list[Path]:
        calls.append((Path(manifest), Path(target)))
        return []

    monkeypatch.setattr(module, "fetch_all", recording)

    assert module.main([]) == 0
    assert calls == [(settled.MANIFEST, settled.REPO_ROOT / "packaging" / "models")]


def test_the_default_opener_is_urllib_urlopen() -> None:
    """C-1: no new dependency. `fetch_all`'s and `main`'s `opener` default to
    `urllib.request.urlopen` itself."""
    import inspect

    module = _script()
    for function in (module.fetch_all, module.main):
        parameter = inspect.signature(function).parameters["opener"]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is urllib.request.urlopen


def test_the_script_takes_nothing_from_mangatl_but_the_manifest_module() -> None:
    """C-1: it imports `mangatl.models.manifest` for the parser and the hashing,
    nothing else from `mangatl`, and nothing from `onnxruntime`."""
    import ast

    assert settled.FETCH_SCRIPT.is_file(), f"{settled.FETCH_SCRIPT} does not exist (MT-024 C-1)"
    tree = ast.parse(settled.FETCH_SCRIPT.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
    ours = sorted(name for name in imported if name.split(".")[0] == "mangatl")
    assert ours == ["mangatl.models.manifest"], f"the fetch script imports {ours}"
    assert not any(name.split(".")[0] == "onnxruntime" for name in imported)


# -- packaging/models.json, the real one -------------------------------------------


def _real_entries() -> list[dict[str, object]]:
    assert settled.MANIFEST.is_file(), f"{settled.MANIFEST} does not exist (MT-024 C-1)"
    document = json.loads(settled.MANIFEST.read_text(encoding="utf-8"))
    assert list(document) == ["models"], f"models.json has top-level keys {list(document)}"
    entries: list[dict[str, object]] = document["models"]
    return entries


def test_the_real_manifest_is_the_five_settled_entries_field_for_field() -> None:
    entries = _real_entries()

    assert [entry.get("name") for entry in entries] == [
        entry["name"] for entry in settled.SETTLED_ENTRIES
    ]
    for entry, expected in zip(entries, settled.SETTLED_ENTRIES, strict=True):
        assert entry == expected, f"manifest entry {expected['name']} differs from C-1"


def test_the_real_manifest_paths_are_the_layout_build_pipeline_reads() -> None:
    """C-1: `path` is MT-036 C-6 exactly, compared with the constants
    themselves so the manifest cannot drift from what `build_pipeline` opens."""
    paths = [entry["path"] for entry in _real_entries()]

    assert paths == [
        DETECTOR_FILENAME,
        f"{OCR_SUBDIR}/{ENCODER_FILENAME}",
        f"{OCR_SUBDIR}/{DECODER_FILENAME}",
        f"{OCR_SUBDIR}/{VOCAB_FILENAME}",
        INPAINTER_FILENAME,
    ]
