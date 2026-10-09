"""MT-024 AC-5 (startup half), AC-7 (in process) and C-6: `mangatl.app`.

**The startup refusal (AC-5).** `main` is driven in process with the recording
`QApplication` stand-in `test_app_theme_startup.py` uses (only one real
`QApplication` exists per process and qtbot made it; a real `exec()` blocks).
`mangatl.app.check_bundled_models` - the seam C-6 names - is replaced to return
an error string; `build_window` and `MainWindow` are replaced with recorders.
When the check fails, `main` builds `MainWindow(notice=<the message>)`, shows
it, runs `exec`, never calls `build_window`, and returns 1. When it passes,
`main` takes the normal path. The check runs after the theme is applied and
before any window is built: the notice is themed like every other window.

**`--check` (C-6).** `main(["mangatl", "--check", <path>])` returns
`self_check(Path(path))` before any `QApplication` is constructed - a
`console=False` binary has no stdout, so the report goes to the file.

**`self_check` itself**, in process, with the detector loader replaced, so the
six-line format is pinned without a frozen binary. The frozen binary is
`tests/frozen/test_self_check.py`'s.

**`check_bundled_models`**, the real one: `None` when `bundled_models_dir()`
is not a directory, `None` when it verifies, the `ModelHashMismatch` message
otherwise. It and `self_check` verify against `bundled_manifest()` - in a
checkout that is `packaging/models.json`, beside the download directory, not
inside it (C-3) - which the tests below pin by putting the manifest somewhere
the models directory's own `models.json` is not.

`tests/ui/conftest.py` replaces `check_bundled_models` with `lambda: None` and
points `bundled_models_dir` at a missing directory for every UI test; this file
overrides both per test, and takes the real function from that fixture's value.

RED: `check_bundled_models`, `self_check`, `bundled_models_dir` and
`bundled_manifest` do not exist. Every name is replaced with `raising=False`
or reached in the test body, so the file collects and each test fails on its
own assertion or on the missing name.

What these tests do NOT constrain: the text of a failing theme or fonts line
(only that a failure returns 1), the order in which `self_check` does its six
checks, and whether `check_bundled_models` logs.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Sequence
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QMainWindow

from mangatl import app as app_module
from mangatl.ui.main_window import MainWindow

CUDA = "CUDAExecutionProvider"
CPU = "CPUExecutionProvider"
MESSAGE = "lama_fp32.onnx: sha256 " + "0" * 64 + " != " + "1" * 64


# -- the recording stand-ins ---------------------------------------------------


class _Run:
    """One `main` run's event log, and the windows it constructed."""

    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []
        self.constructed: list[dict[str, Any]] = []
        self.windows: list[QMainWindow] = []


def _install(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    check: Callable[[], str | None],
) -> _Run:
    run = _Run()
    real_build = app_module.build_window

    def recording_check() -> str | None:
        run.events.append(("check_bundled_models", None))
        return check()

    def recording_build(arguments: Sequence[str], **options: Any) -> QMainWindow:
        run.events.append(("build_window", list(arguments)))
        return real_build(arguments, **options)

    class _RecordingMainWindow(MainWindow):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            run.events.append(("MainWindow", dict(kwargs)))
            run.constructed.append(dict(kwargs))
            super().__init__(*args, **kwargs)
            qtbot.addWidget(self)
            run.windows.append(self)

        def show(self) -> None:
            run.events.append(("show", self))
            super().show()

    class _RecordingQApplication:
        def __init__(self, argv: list[str]) -> None:
            run.events.append(("QApplication", list(argv)))

        def setStyleSheet(self, sheet: str) -> None:
            run.events.append(("setStyleSheet", None))

        def exec(self) -> int:
            run.events.append(("exec", None))
            for window in run.windows:
                window.close()
            return 0

    monkeypatch.setattr(app_module, "check_bundled_models", recording_check, raising=False)
    monkeypatch.setattr(app_module, "build_window", recording_build)
    monkeypatch.setattr(app_module, "MainWindow", _RecordingMainWindow)
    monkeypatch.setattr(app_module, "QApplication", _RecordingQApplication)
    return run


def _names(run: _Run) -> list[str]:
    return [name for name, _ in run.events]


# -- AC-5: a bundled weight that does not verify stops the app -------------------


def test_a_weight_that_does_not_verify_opens_a_notice_naming_it_and_exits_one(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _install(qtbot, monkeypatch, lambda: MESSAGE)

    code = app_module.main(["mangatl"])

    assert code == 1, f"main returned {code}; AC-5 is 1 when a bundled weight does not verify"
    assert "build_window" not in _names(run), (
        f"main built the normal window after the startup check failed: {_names(run)}"
    )
    assert run.constructed == [{"notice": MESSAGE}], (
        f"main constructed {run.constructed}; AC-5 is one MainWindow(notice=<the message>)"
    )


def test_the_notice_is_shown_and_the_event_loop_runs_before_main_returns(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _install(qtbot, monkeypatch, lambda: MESSAGE)

    app_module.main(["mangatl"])

    names = _names(run)
    assert names == [
        "QApplication",
        "setStyleSheet",
        "check_bundled_models",
        "MainWindow",
        "show",
        "exec",
    ], names


def test_the_check_refuses_whatever_folder_was_named_on_the_command_line(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run = _install(qtbot, monkeypatch, lambda: MESSAGE)

    assert app_module.main(["mangatl", str(tmp_path)]) == 1
    assert "build_window" not in _names(run)
    assert run.constructed == [{"notice": MESSAGE}]


@pytest.mark.parametrize(
    "argv",
    [["mangatl"], ["mangatl", "a folder"]],
    ids=["no argument", "a folder"],
)
def test_when_the_weights_verify_main_builds_its_window_as_before(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    argv: list[str],
) -> None:
    run = _install(qtbot, monkeypatch, lambda: None)
    arguments = [str(tmp_path / argument) for argument in argv[1:]]

    code = app_module.main([argv[0], *arguments])

    names = _names(run)
    assert code == 0
    assert names.count("check_bundled_models") == 1, (
        f"main called check_bundled_models {names.count('check_bundled_models')} times;"
        f" C-6 is once, after the theme and before the window: {names}"
    )
    assert names.index("setStyleSheet") < names.index("check_bundled_models")
    assert names.index("check_bundled_models") < names.index("build_window")
    assert [name for name in names if name == "build_window"] == ["build_window"]
    assert all(kwargs.get("notice") != MESSAGE for kwargs in run.constructed)


# -- C-6: `--check` ------------------------------------------------------------------


def _no_qapplication(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    touched: list[str] = []

    class _Refused:
        def __init__(self, argv: list[str]) -> None:
            touched.append("QApplication")
            raise AssertionError(
                f"main({argv!r}) constructed a QApplication; C-6 returns self_check's"
                " result before any application exists"
            )

    monkeypatch.setattr(app_module, "QApplication", _Refused)
    monkeypatch.setattr(app_module, "build_window", lambda *a, **k: touched.append("build"))
    return touched


@pytest.mark.parametrize("result", [0, 1])
def test_check_returns_self_checks_result_before_any_application_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, result: int
) -> None:
    touched = _no_qapplication(monkeypatch)
    reports: list[Path] = []

    def recording(report: Path) -> int:
        reports.append(report)
        return result

    monkeypatch.setattr(app_module, "self_check", recording, raising=False)
    report = tmp_path / "report.txt"

    code = app_module.main(["mangatl.exe", "--check", str(report)])

    assert code == result
    assert reports == [report], f"self_check was handed {reports}"
    assert all(type(path) is type(report) for path in reports), "self_check takes a Path"
    assert touched == [], f"--check constructed {touched} before returning"


@pytest.mark.parametrize(
    "arguments",
    [["--check"], ["--check", "a", "b"], ["a", "--check"]],
    ids=["no report path", "two report paths", "check second"],
)
def test_only_check_and_one_path_is_the_check(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
) -> None:
    """C-6: `argv[1:] == ["--check", <path>]` exactly; every other shape goes to
    `build_window` as before (`USAGE_NOTICE` is unchanged)."""
    calls: list[Path] = []
    monkeypatch.setattr(
        app_module, "self_check", lambda report: calls.append(report) or 0, raising=False
    )
    run = _install(qtbot, monkeypatch, lambda: None)

    app_module.main(["mangatl", *arguments])

    assert calls == []
    assert ("build_window", arguments) in run.events


# -- the real `check_bundled_models` ---------------------------------------------------


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


#: A small models directory in C-6 of MT-036's layout. Only these few bytes are
#: hashed; nothing reads a real weight.
WEIGHTS: dict[str, bytes] = {
    "comic-text-detector.onnx": b"a detector",
    "manga-ocr/vocab.txt": b"[PAD]\n",
    "lama_fp32.onnx": b"an inpainter",
}


def _bundle(
    root: Path, monkeypatch: pytest.MonkeyPatch, *, on_disk: dict[str, bytes | None] | None = None
) -> tuple[Path, Path]:
    """A models directory and a manifest for it, with `bundled_models_dir()`
    and `bundled_manifest()` answering them. The manifest is NOT inside the
    models directory, where a checkout's never is."""
    models = root / "models"
    models.mkdir(parents=True)
    written = dict(WEIGHTS, **(on_disk or {}))
    for path, data in written.items():
        if data is not None:
            (models / path).parent.mkdir(parents=True, exist_ok=True)
            (models / path).write_bytes(data)
    entries = [
        {
            "name": path,
            "role": "detect",
            "repo": "example/repo",
            "revision": "0" * 40,
            "file": path,
            "path": path,
            "sha256": _sha(data),
            "bytes": len(data),
            "licence": "Apache-2.0",
        }
        for path, data in WEIGHTS.items()
    ]
    manifest = root / "models.json"
    manifest.write_text(json.dumps({"models": entries}), encoding="utf-8")
    for name in ("mangatl.app", "mangatl.app_paths"):
        monkeypatch.setattr(f"{name}.bundled_models_dir", lambda: models, raising=False)
        monkeypatch.setattr(f"{name}.bundled_manifest", lambda: manifest, raising=False)
    return models, manifest


def _real_check(original: object) -> Callable[[], str | None]:
    assert callable(original), "mangatl.app.check_bundled_models does not exist (MT-024 C-6)"
    check: Callable[[], str | None] = original
    return check


def test_a_checkout_with_no_bundled_models_passes_the_startup_check(
    original_check_bundled_models: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # conftest points bundled_models_dir at a missing directory: a plain checkout.
    check = _real_check(original_check_bundled_models)
    for name in ("mangatl.app", "mangatl.app_paths"):
        monkeypatch.setattr(f"{name}.bundled_manifest", lambda: tmp_path / "x.json", raising=False)

    assert check() is None


def test_bundled_models_that_verify_pass_the_startup_check(
    original_check_bundled_models: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    check = _real_check(original_check_bundled_models)
    _bundle(tmp_path, monkeypatch)

    assert check() is None


def test_a_bundled_weight_that_does_not_verify_is_the_startup_checks_answer(
    original_check_bundled_models: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    check = _real_check(original_check_bundled_models)
    _bundle(tmp_path, monkeypatch, on_disk={"lama_fp32.onnx": b"another inpainter"})

    assert check() == (
        f"lama_fp32.onnx: sha256 {_sha(b'another inpainter')} != {_sha(WEIGHTS['lama_fp32.onnx'])}"
    )


def test_a_missing_bundled_weight_is_the_startup_checks_answer(
    original_check_bundled_models: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    check = _real_check(original_check_bundled_models)
    _bundle(tmp_path, monkeypatch, on_disk={"manga-ocr/vocab.txt": None})

    assert check() == "manga-ocr/vocab.txt: missing"


# -- `self_check`, in process ------------------------------------------------------


class _FakeDetector:
    def __init__(self, reports: list[str]) -> None:
        self.reports = reports

    def get_providers(self) -> Sequence[str]:
        return list(self.reports)


@pytest.fixture
def detector_loads(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Path, tuple[str, ...]]]:
    """`load_detector` replaced at every name `self_check` could import it by
    (C-6: imported inside the function), reporting the CPU whatever it was asked
    for; CUDA and CPU both "available"."""
    loads: list[tuple[Path, tuple[str, ...]]] = []

    def fake(path: Path, providers: Sequence[str]) -> _FakeDetector:
        loads.append((Path(path), tuple(providers)))
        return _FakeDetector([CPU])

    monkeypatch.setattr("mangatl.detect.session.load_detector", fake)
    monkeypatch.setattr("mangatl.compose.load_detector", fake)
    monkeypatch.setattr("mangatl.compose.available_providers", lambda: [CPU, CUDA], raising=False)
    return loads


def _resource_bytes(name: str) -> int:
    return len(files("mangatl.ui").joinpath(name).read_bytes())


def _expected_report(models_line: str) -> list[str]:
    return [
        f"theme: ok ({_resource_bytes('theme.qss')} bytes)",
        f"theme-template: ok ({_resource_bytes('theme.qss.tmpl')} bytes)",
        f"theme-hc-template: ok ({_resource_bytes('theme_hc.qss.tmpl')} bytes)",
        "fonts: ok (4 faces, OFL.txt)",
        models_line,
        f"provider: {CPU}",
    ]


def _self_check() -> Callable[[Path], int]:
    function = getattr(app_module, "self_check", None)
    assert callable(function), "mangatl.app.self_check does not exist (MT-024 C-6)"
    checked: Callable[[Path], int] = function
    return checked


def test_self_check_writes_the_six_lines_and_returns_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    detector_loads: list[tuple[Path, tuple[str, ...]]],
) -> None:
    _bundle(tmp_path / "bundle", monkeypatch)
    report = tmp_path / "report.txt"

    code = _self_check()(report)

    assert report.read_text(encoding="utf-8").splitlines() == _expected_report(
        f"models: ok ({len(WEIGHTS)} verified)"
    )
    assert code == 0


def test_the_provider_line_is_the_detectors_actual_provider_not_the_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    detector_loads: list[tuple[Path, tuple[str, ...]]],
) -> None:
    """CUDA and CPU available, so CUDA is requested; the fake detector says CPU,
    and so must the report (AC-7, C-6: `selected_provider(detector)`). Only the
    detector is loaded, from the bundled models directory."""
    models, _ = _bundle(tmp_path / "bundle", monkeypatch)
    report = tmp_path / "report.txt"

    _self_check()(report)

    assert detector_loads == [(models / "comic-text-detector.onnx", (CUDA, CPU))]
    assert report.read_text(encoding="utf-8").splitlines()[-1] == f"provider: {CPU}"


def test_self_check_reports_a_weight_that_does_not_verify_and_returns_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    detector_loads: list[tuple[Path, tuple[str, ...]]],
) -> None:
    tampered = WEIGHTS["manga-ocr/vocab.txt"] + b"\n"
    _bundle(tmp_path / "bundle", monkeypatch, on_disk={"manga-ocr/vocab.txt": tampered})
    report = tmp_path / "report.txt"

    code = _self_check()(report)

    lines = report.read_text(encoding="utf-8").splitlines()
    expected = _expected_report(
        f"models: manga-ocr/vocab.txt: sha256 {_sha(tampered)}"
        f" != {_sha(WEIGHTS['manga-ocr/vocab.txt'])}"
    )
    assert code == 1
    assert len(lines) == 6, lines
    assert lines[:5] == expected[:5]
    assert re.fullmatch(r"provider: \S.*", lines[5]), lines[5]


def test_self_check_reports_a_missing_weight_and_returns_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    detector_loads: list[tuple[Path, tuple[str, ...]]],
) -> None:
    _bundle(tmp_path / "bundle", monkeypatch, on_disk={"lama_fp32.onnx": None})
    report = tmp_path / "report.txt"

    code = _self_check()(report)

    lines = report.read_text(encoding="utf-8").splitlines()
    assert code == 1
    assert len(lines) == 6, lines
    assert lines[4] == "models: lama_fp32.onnx: missing"
