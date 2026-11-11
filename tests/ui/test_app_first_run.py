"""MT-077 C-3: `mangatl.app` asks for the Gemini API key at first run, stores
it, and builds the window's pipeline with it.

What each part pins:

- `first_run(settings_file, env, ask)` - AC-1 (ask when there is no key;
  Cancel writes nothing), AC-2 (a key is written, other keys survive), AC-4
  (no ask when the environment or the file has a key), AC-5 (logged masked;
  an unwritable file is a returned message without the key).
- `translation_env(env, settings_file)` - the stored key overlaid on a copy of
  the environment; AC-6, the environment wins; the environment is never
  mutated.
- `build_stages(models_dir)` - AC-3 and AC-6 at the seam: with
  `mangatl.compose.build_pipeline` replaced by a recorder, the selection it is
  handed is `Selection("gemini", <the right key>)`; with no key anywhere the
  `NoApiKey` refusal is raised and the recorder is never called (no weight
  loads).
- the window path - AC-1's "Start's error names the missing key" and AC-3's
  "before any project is created", through `build_window` with a `RunSetup`
  whose builder is the real `app.build_stages`.
- `main` - AC-1's ordering: the key is asked for after the bundled weights are
  checked and before the window is built; Cancel still builds the window; the
  failed-check path never asks; a returned problem reaches `show_warning`.

**The environment.** Where the contract takes the environment as an argument
the test passes a dict. Where the code reads `os.environ` (`build_stages`,
`main`), every key variable and `MANGATL_PROVIDER` is cleared first: the
developer's machine may have any of them set. `APPDATA` is a fresh directory
per test (`tests/conftest.py`), so `settings_path()` is this test's own.

**Oracle: mechanical, pinned exactly.** The NoApiKey sentence and the INFO line
are spelled out here, never read back from the module under test.

RED: `first_run`, `translation_env`, `show_warning` and the new `build_stages`
body do not exist. Every new name is reached in the test body, so the file
collects and each test fails on its own `AttributeError` or assertion.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow, QPushButton

import mangatl.compose as compose_module
from mangatl import app as app_module
from mangatl.app_paths import settings_path
from mangatl.domain.page import Chapter
from mangatl.store.project import project_dir_for
from mangatl.translate.provider import AmbiguousProvider, NoApiKey, ProviderUnavailable, Selection
from mangatl.ui import tokens_gen
from mangatl.ui.intake import FolderDropTarget
from mangatl.ui.main_window import MainWindow
from mangatl.ui.run import RunSetup
from mangatl.ui.summary import ChapterSummary

GEMINI = "GEMINI_API_KEY"
#: Every variable `select_provider` reads, cleared wherever `os.environ` is.
PROVIDER_VARIABLES = ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "MANGATL_PROVIDER")

STORED_KEY = "AIzaSyStoredQ7vK9mZxW0000aaaa"
ENV_KEY = "AIzaSyEnvironJ3pL8nRtY1111bbbb"
TYPED_KEY = "AIzaSyTypedH5sD2wQkU2222cccc"
FONT_DIR = "D:/fonts/manga"

#: MT-078 AC-3's sentence, spelled out (test_translate_provider.py pins it).
NO_API_KEY_TEXT = (
    "no API key is set: set ANTHROPIC_API_KEY, GEMINI_API_KEY or OPENAI_API_KEY,"
    " or run with --no-translate"
)
LOGGER = "mangatl.app"

#: Liveness bound for the window to become active offscreen.
ACTIVE_MS = 5_000


# =============================================================================
# Helpers
# =============================================================================


def _clear_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in PROVIDER_VARIABLES:
        monkeypatch.delenv(name, raising=False)


def _settings_file(tmp_path: Path) -> Path:
    return tmp_path / "mangatl" / "settings.json"


def _store(file: Path, obj: Any) -> bytes:
    file.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(obj, indent=2).encode("utf-8")
    file.write_bytes(data)
    return data


def _leaks(key: str, text: str) -> list[str]:
    """Every five-character run of `key` that appears in `text`: AC-5 allows at
    most the last four characters, so any five in a row is a leak."""
    return sorted({key[i : i + 5] for i in range(len(key) - 4) if key[i : i + 5] in text})


def _log_text(caplog: pytest.LogCaptureFixture) -> str:
    """Every record's message and the formatted log (tracebacks included)."""
    return "\n".join([*(r.getMessage() for r in caplog.records), caplog.text])


class Asker:
    """`ask` for `first_run`: records each call and answers `answer`."""

    def __init__(self, answer: str | None) -> None:
        self.answer = answer
        self.calls = 0

    def __call__(self) -> str | None:
        self.calls += 1
        return self.answer


class PipelineRecorder:
    """Stands in for `mangatl.compose.build_pipeline`: no weight is loaded."""

    def __init__(self, *, raise_after: Exception | None = None, pipeline: object = None) -> None:
        self.calls: list[tuple[Path, dict[str, Any]]] = []
        self.raise_after = raise_after
        #: MT-130: the pipeline to hand back, when a test builds its own.
        self.pipeline = pipeline

    def __call__(self, models_dir: Path, **kwargs: Any) -> object:
        self.calls.append((models_dir, dict(kwargs)))
        if self.raise_after is not None:
            raise self.raise_after
        if self.pipeline is not None:
            return self.pipeline
        # MT-105: `build_pipeline` returns `Pipeline(stages, prelude)`. Imported
        # here so that its absence in RED fails only the tests that build.
        from mangatl.pipeline.prelude import Pipeline  # type: ignore[import-not-found]

        return Pipeline(stages=(), prelude=None)


def _record_pipeline(
    monkeypatch: pytest.MonkeyPatch, recorder: PipelineRecorder | None = None
) -> PipelineRecorder:
    recorder = recorder if recorder is not None else PipelineRecorder()
    monkeypatch.setattr(compose_module, "build_pipeline", recorder)
    return recorder


def _selection_of(recorder: PipelineRecorder) -> object:
    assert len(recorder.calls) == 1, (
        f"build_pipeline was called {len(recorder.calls)} times; Start builds once"
    )
    _, kwargs = recorder.calls[0]
    assert kwargs.get("translate") is True, f"build_pipeline got {kwargs}; translate=True"
    assert "selection" in kwargs, (
        f"build_pipeline got {sorted(kwargs)}; C-3 passes selection= explicitly"
    )
    return kwargs["selection"]


# =============================================================================
# first_run - AC-1, AC-2, AC-4, AC-5
# =============================================================================


def test_with_a_key_in_the_environment_no_dialog_is_shown(tmp_path: Path) -> None:
    """AC-4, environment half."""
    file = _settings_file(tmp_path)
    ask = Asker(TYPED_KEY)

    problem = app_module.first_run(file, {GEMINI: ENV_KEY}, ask)

    assert ask.calls == 0, "first_run asked for a key although GEMINI_API_KEY is set (AC-4)"
    assert problem is None
    assert not file.exists(), "first_run wrote a settings file it had no key to write"


def test_with_a_key_in_the_settings_file_no_dialog_is_shown(tmp_path: Path) -> None:
    """AC-4, settings half."""
    file = _settings_file(tmp_path)
    before = _store(file, {"gemini_api_key": STORED_KEY})
    ask = Asker(TYPED_KEY)

    problem = app_module.first_run(file, {}, ask)

    assert ask.calls == 0, "first_run asked for a key although settings.json holds one (AC-4)"
    assert problem is None
    assert file.read_bytes() == before


@pytest.mark.parametrize(
    ("contents", "env"),
    [
        (None, {}),
        ({"lettering_font_dir": FONT_DIR}, {}),
        ({"gemini_api_key": ""}, {}),
        ({"gemini_api_key": None}, {GEMINI: ""}),
        (None, {"ANTHROPIC_API_KEY": "sk-ant-other-provider"}),
    ],
    ids=[
        "no file",
        "file without the key",
        "empty stored key",
        "null stored key, empty variable",
        "another provider's key only",
    ],
)
def test_with_no_gemini_key_anywhere_the_dialog_is_shown_once(
    tmp_path: Path, contents: Any, env: dict[str, str]
) -> None:
    """AC-1: no `gemini_api_key` in the file and no `GEMINI_API_KEY` - ask."""
    file = _settings_file(tmp_path)
    if contents is not None:
        _store(file, contents)
    ask = Asker(None)

    app_module.first_run(file, env, ask)

    assert ask.calls == 1, f"first_run asked {ask.calls} times; AC-1 asks once"


def test_cancel_writes_nothing_and_reports_no_problem(tmp_path: Path) -> None:
    """AC-1: Cancel leaves the app runnable in review-only mode."""
    file = _settings_file(tmp_path)
    ask = Asker(None)

    problem = app_module.first_run(file, {}, ask)

    assert problem is None
    assert not file.exists(), "Cancel wrote a settings file"
    assert not file.parent.exists(), "Cancel created the settings folder"


def test_cancel_leaves_an_existing_settings_file_untouched(tmp_path: Path) -> None:
    file = _settings_file(tmp_path)
    before = _store(file, {"lettering_font_dir": FONT_DIR})

    problem = app_module.first_run(file, {}, Asker(None))

    assert problem is None
    assert file.read_bytes() == before


def test_an_entered_key_is_stored_beside_the_existing_settings(tmp_path: Path) -> None:
    """AC-2 through first_run: the key lands, the font folder survives."""
    file = _settings_file(tmp_path)
    _store(file, {"lettering_font_dir": FONT_DIR, "zoom": 2})

    problem = app_module.first_run(file, {}, Asker(TYPED_KEY))

    assert problem is None
    assert json.loads(file.read_text(encoding="utf-8")) == {
        "lettering_font_dir": FONT_DIR,
        "zoom": 2,
        "gemini_api_key": TYPED_KEY,
    }


def test_an_entered_key_is_logged_once_masked(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """AC-5: one INFO line naming the last four characters, and no more."""
    caplog.set_level(logging.DEBUG)
    file = _settings_file(tmp_path)

    app_module.first_run(file, {}, Asker(TYPED_KEY))

    saved = [
        (r.name, r.levelno, r.getMessage())
        for r in caplog.records
        if r.getMessage().startswith("Gemini API key saved")
    ]
    assert saved == [(LOGGER, logging.INFO, "Gemini API key saved (****cccc)")], (
        f"the save was logged as {saved}; C-3 is one INFO line on {LOGGER!r}"
    )
    assert _leaks(TYPED_KEY, _log_text(caplog)) == [], (
        "a log record carries more than the key's last four characters (AC-5)"
    )


def test_a_settings_file_that_cannot_be_parsed_is_reported_without_the_key(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """C-3: `SettingsUnreadable` from the write is logged at WARNING and
    returned as the message `main` shows - and neither carries the key (AC-5).
    The user's file is not overwritten (C-1)."""
    caplog.set_level(logging.DEBUG)
    file = _settings_file(tmp_path)
    file.parent.mkdir(parents=True)
    before = b'{"lettering_font_dir": "D:/fonts",\n'
    file.write_bytes(before)

    problem = app_module.first_run(file, {}, Asker(TYPED_KEY))

    assert isinstance(problem, str), f"first_run returned {problem!r}; C-3 returns str(error)"
    assert problem.startswith(f"{file} could not be read: "), problem
    assert _leaks(TYPED_KEY, problem) == [], f"the returned message leaks the key: {problem!r}"
    assert file.read_bytes() == before, "the unparsable settings file was overwritten"
    warnings = [r for r in caplog.records if r.name == LOGGER and r.levelno == logging.WARNING]
    assert len(warnings) >= 1, "C-3 logs the unreadable settings file at WARNING"
    assert _leaks(TYPED_KEY, _log_text(caplog)) == [], "a log record carries the key (AC-5)"


def test_a_write_the_disk_refuses_is_reported_without_the_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """C-3: an `OSError` from the write is a returned message too, not a
    traceback out of `main`."""
    import mangatl.store.settings as settings_module

    caplog.set_level(logging.DEBUG)
    file = _settings_file(tmp_path)

    def refuse(src: Any, dst: Any) -> None:
        raise PermissionError(13, "Access is denied", str(dst))

    monkeypatch.setattr(settings_module.os, "replace", refuse)

    problem = app_module.first_run(file, {}, Asker(TYPED_KEY))

    assert isinstance(problem, str) and "Access is denied" in problem, (
        f"first_run returned {problem!r}; C-3 returns str(error) for an OSError"
    )
    assert _leaks(TYPED_KEY, problem) == []
    assert _leaks(TYPED_KEY, _log_text(caplog)) == []
    assert any(r.name == LOGGER and r.levelno == logging.WARNING for r in caplog.records)


# =============================================================================
# translation_env - the stored key overlaid on a copy; the environment wins
# =============================================================================


def test_the_stored_key_fills_an_environment_without_one(tmp_path: Path) -> None:
    file = _settings_file(tmp_path)
    _store(file, {"gemini_api_key": STORED_KEY})
    env = {"PATH": "C:/Windows"}

    result = app_module.translation_env(env, file)

    assert result == {"PATH": "C:/Windows", GEMINI: STORED_KEY}
    assert env == {"PATH": "C:/Windows"}, "translation_env mutated the environment it was given"


def test_an_empty_variable_counts_as_unset(tmp_path: Path) -> None:
    file = _settings_file(tmp_path)
    _store(file, {"gemini_api_key": STORED_KEY})

    assert app_module.translation_env({GEMINI: ""}, file) == {GEMINI: STORED_KEY}


def test_the_environment_key_wins_over_the_stored_one(tmp_path: Path) -> None:
    """AC-6 / PO-2."""
    file = _settings_file(tmp_path)
    _store(file, {"gemini_api_key": STORED_KEY})

    result = app_module.translation_env({GEMINI: ENV_KEY}, file)

    assert result[GEMINI] == ENV_KEY, (
        f"translation_env carries {result[GEMINI]!r}; AC-6 is the environment's key"
    )


@pytest.mark.parametrize(
    "contents",
    [None, {"lettering_font_dir": FONT_DIR}, {"gemini_api_key": ""}],
    ids=["no file", "no key", "empty key"],
)
def test_without_a_stored_key_the_environment_is_copied_unchanged(
    tmp_path: Path, contents: Any
) -> None:
    file = _settings_file(tmp_path)
    if contents is not None:
        _store(file, contents)
    env = {"PATH": "C:/Windows", "ANTHROPIC_API_KEY": "sk-ant-x"}

    result = app_module.translation_env(env, file)

    assert result == env
    assert result is not env, "translation_env returned the environment itself, not a copy"


def test_translation_env_never_mutates_the_mapping_it_is_given(tmp_path: Path) -> None:
    """A read-only mapping: any write into it raises."""
    file = _settings_file(tmp_path)
    _store(file, {"gemini_api_key": STORED_KEY})
    env = MappingProxyType({"PATH": "C:/Windows"})

    result = app_module.translation_env(env, file)

    assert isinstance(result, dict)
    assert result[GEMINI] == STORED_KEY


# =============================================================================
# build_stages - AC-3, AC-6 at the seam (no weight is loaded)
# =============================================================================


def test_start_selects_gemini_with_the_stored_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC-3: a key in settings.json and none in the environment."""
    _clear_provider_env(monkeypatch)
    _store(settings_path(), {"gemini_api_key": STORED_KEY, "lettering_font_dir": FONT_DIR})
    recorder = _record_pipeline(monkeypatch)

    app_module.build_stages(tmp_path)

    assert _selection_of(recorder) == Selection("gemini", STORED_KEY)
    assert recorder.calls[0][0] == tmp_path


def test_start_does_not_put_the_stored_key_into_the_process_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import os

    _clear_provider_env(monkeypatch)
    _store(settings_path(), {"gemini_api_key": STORED_KEY})
    recorder = _record_pipeline(monkeypatch)

    app_module.build_stages(tmp_path)

    assert _selection_of(recorder) == Selection("gemini", STORED_KEY), (
        "precondition: the stored key reached the selection"
    )
    assert GEMINI not in os.environ, "build_stages wrote the stored key into os.environ"


class _NamedStage:
    """A `Stage` that is only an identity: MT-139 AC-1 compares by `is`."""

    def __init__(self, name: str) -> None:
        self.name = name

    def run(self, ctx: object) -> None:  # pragma: no cover - never run here
        raise AssertionError("build_stages runs no stage")

    def is_done(self, ctx: object) -> bool:  # pragma: no cover - never run here
        raise AssertionError("build_stages runs no stage")


def test_build_stages_returns_the_pipeline_build_pipeline_returned_prelude_included(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """MT-139 AC-1 (supersedes MT-130 AC-15's
    `test_build_stages_returns_both_passes_in_run_order_for_the_windows_single_pass_run`,
    MT-139 PO-1): `app.build_stages` hands back `build_pipeline`'s very
    `Pipeline` - both passes AND the chapter step - built once, with
    translation on, the selection and the context mode as before. MT-130's
    `.page_stages` dropped the prelude; that is the defect this story removes."""
    from mangatl.pipeline.prelude import Pipeline

    _clear_provider_env(monkeypatch)
    monkeypatch.delenv("MANGATL_CONTEXT_MODE", raising=False)
    _store(settings_path(), {"gemini_api_key": STORED_KEY})
    a, b, c = _NamedStage("a"), _NamedStage("b"), _NamedStage("c")

    def prelude(project: object, run_id: int, emit: object) -> None:  # pragma: no cover
        raise AssertionError("build_stages runs no prelude")

    pipeline = Pipeline(stages=(a, b), prelude=prelude, after_prelude=(c,))  # type: ignore[arg-type]
    recorder = _record_pipeline(monkeypatch, PipelineRecorder(pipeline=pipeline))

    built = app_module.build_stages(tmp_path)

    assert built is pipeline, (
        f"build_stages returned {built!r}, not the Pipeline build_pipeline returned"
    )
    assert recorder.calls == [
        (
            tmp_path,
            {
                "translate": True,
                "selection": Selection("gemini", STORED_KEY),
                "context_mode": "rolling",
            },
        )
    ]


def test_the_default_window_setup_starts_through_the_real_build_stages(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    """MT-139 AC-1: `build_window([])`'s default `RunSetup` carries
    `app.build_stages` itself - the window's Start is the real builder, not a
    copy or a wrapper that could drop the prelude again."""
    window = app_module.build_window([])
    qtbot.addWidget(window)
    setup = getattr(window, "_run_setup", None)

    assert isinstance(setup, RunSetup)
    assert setup.build_stages is app_module.build_stages
    window.close()


def test_start_selects_the_environments_key_over_a_different_stored_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC-6."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv(GEMINI, ENV_KEY)
    _store(settings_path(), {"gemini_api_key": STORED_KEY})
    recorder = _record_pipeline(monkeypatch)

    app_module.build_stages(tmp_path)

    selection = _selection_of(recorder)
    assert selection == Selection("gemini", ENV_KEY), (
        "Start's selection does not carry the environment's key (AC-6: the environment wins)"
    )


def test_start_selects_the_environments_key_with_no_stored_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC-4's other half at Start: the environment alone is enough."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv(GEMINI, ENV_KEY)
    recorder = _record_pipeline(monkeypatch)

    app_module.build_stages(tmp_path)

    assert _selection_of(recorder) == Selection("gemini", ENV_KEY)


def test_an_explicit_gemini_choice_is_satisfied_by_the_stored_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """C-3: `MANGATL_PROVIDER` is the explicit choice, and the stored key is in
    the mapping `select_provider` reads."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("MANGATL_PROVIDER", "gemini")
    _store(settings_path(), {"gemini_api_key": STORED_KEY})
    recorder = _record_pipeline(monkeypatch)

    app_module.build_stages(tmp_path)

    assert _selection_of(recorder) == Selection("gemini", STORED_KEY)


def test_a_keyless_start_is_refused_before_build_pipeline_is_called(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC-3: no key anywhere and translate=True - `NoApiKey`, and no weight
    loads because `build_pipeline` is never reached."""
    _clear_provider_env(monkeypatch)
    recorder = _record_pipeline(monkeypatch)

    with pytest.raises(NoApiKey) as caught:
        app_module.build_stages(tmp_path)

    assert str(caught.value) == NO_API_KEY_TEXT
    assert recorder.calls == [], (
        f"build_pipeline was called {recorder.calls} before the refusal; AC-3 refuses"
        " before any weight loads"
    )


# =============================================================================
# The window path - Start through the real app.build_stages
# =============================================================================


def _png() -> bytes:
    image = QImage(QSize(60, 80), QImage.Format.Format_RGB32)
    image.fill(QColor(tokens_gen.TOKENS["color.surface.raised"]))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    buffer.close()
    return bytes(data.data())


def _chapter_folder(root: Path) -> Path:
    folder = root / "ch 01"
    folder.mkdir()
    png = _png()
    for index in range(2):
        (folder / f"{index + 1:02d}.png").write_bytes(png)
    return folder.resolve()


def _settle() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


def _press_start(qtbot, window: QMainWindow, folder: Path) -> None:  # type: ignore[no-untyped-def]
    qtbot.addWidget(window)
    window.resize(900, 600)
    with qtbot.waitExposed(window):
        window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow, timeout=ACTIVE_MS)
    assert isinstance(window, MainWindow)
    if not isinstance(window.centralWidget(), ChapterSummary):
        chapter = app_module.open_folder(folder)
        assert isinstance(chapter, Chapter)
        window.show_summary(chapter)
        _settle()
    summary = window.centralWidget()
    assert isinstance(summary, ChapterSummary)
    button = summary.findChild(QPushButton, "summary-start")
    assert button is not None, "the summary has no QPushButton named 'summary-start'"
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    _settle()


def _window(tmp_path: Path, folder: Path) -> QMainWindow:
    models = tmp_path / "models"
    models.mkdir()
    # MT-100 C-5: the window's model selector is the real `app.selected_model`,
    # which makes the same resolution `build_stages` makes at Start.
    return app_module.build_window(
        [str(folder)],
        run_setup=RunSetup(lambda: models, app_module.build_stages, app_module.selected_model),
    )


def test_a_keyless_start_shows_the_error_naming_the_key_and_creates_nothing(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """AC-1 (review-only: Start's error names the missing key) and AC-3 (no
    weight loads, no project is created)."""
    _clear_provider_env(monkeypatch)
    # The recorder refuses if reached, so a build_stages that does reach it shows
    # this sentence instead of starting a run - the failure is then the headline.
    recorder = _record_pipeline(
        monkeypatch, PipelineRecorder(raise_after=ProviderUnavailable("build_pipeline was reached"))
    )
    folder = _chapter_folder(tmp_path)
    window = _window(tmp_path, folder)

    _press_start(qtbot, window, folder)

    target = window.centralWidget()
    assert isinstance(target, FolderDropTarget), (
        f"after a keyless Start the central widget is {type(target).__name__},"
        " not the drop target's error state"
    )
    assert target.headline.text() == NO_API_KEY_TEXT
    assert GEMINI in target.headline.text(), "the error does not name GEMINI_API_KEY (AC-1)"
    assert recorder.calls == [], "build_pipeline was reached: weights would have loaded (AC-3)"
    assert not project_dir_for(folder).exists(), "a keyless Start created a project (AC-3)"
    window.close()


def test_a_start_with_the_stored_key_hands_its_selection_to_the_pipeline(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """AC-3 through the window: Start's builder is the real `app.build_stages`.
    The recorder refuses after recording, so the run stops before any project
    is created and the test needs no worker thread."""
    _clear_provider_env(monkeypatch)
    _store(settings_path(), {"gemini_api_key": STORED_KEY})
    recorder = _record_pipeline(
        monkeypatch, PipelineRecorder(raise_after=ProviderUnavailable("recorded, stop here"))
    )
    folder = _chapter_folder(tmp_path)
    window = _window(tmp_path, folder)

    _press_start(qtbot, window, folder)

    assert _selection_of(recorder) == Selection("gemini", STORED_KEY)
    assert recorder.calls[0][0] == tmp_path / "models"
    window.close()


def test_a_keyless_window_shows_no_estimate_and_its_start_still_fails_naming_the_key(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """MT-100 AC-4 through the real `app.selected_model` and `app.build_stages`:
    the summary says why there is no estimate - the `NoApiKey` sentence - and
    pressing Start fails exactly as it did before (MT-077 AC-1)."""
    _clear_provider_env(monkeypatch)
    recorder = _record_pipeline(
        monkeypatch, PipelineRecorder(raise_after=ProviderUnavailable("build_pipeline was reached"))
    )
    folder = _chapter_folder(tmp_path)
    window = _window(tmp_path, folder)
    summary = window.centralWidget()
    assert isinstance(summary, ChapterSummary), f"central is {type(summary).__name__}"

    assert summary.cost_estimate.lines == (f"No estimate: {NO_API_KEY_TEXT}.", "Budget $2.00.")
    assert summary.cost_estimate.over_budget is False

    _press_start(qtbot, window, folder)

    target = window.centralWidget()
    assert isinstance(target, FolderDropTarget)
    assert target.headline.text() == NO_API_KEY_TEXT
    assert recorder.calls == []
    window.close()


# =============================================================================
# selected_model - MT-100 C-5: the model Start would call, for the estimate
# =============================================================================
#
# The same resolution `build_stages` makes at Start - `select_provider` over
# `translation_env(os.environ, settings_path())`, the choice from
# `MANGATL_PROVIDER` - then `model_for(provider)`. `os.environ` is set to
# exactly the variables each test names (`_clear_provider_env` first);
# `settings_path()` is this test's own empty `APPDATA` unless a test stores a
# key there.

#: MT-078 AC-2's sentence for anthropic + gemini, spelled out.
AMBIGUOUS_TEXT = (
    "API keys are set for more than one provider (anthropic, gemini);"
    " choose one with --provider or MANGATL_PROVIDER"
)


def test_a_gemini_key_alone_selects_the_gemini_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """MT-100 AC-1's environment: `GEMINI_API_KEY` is the only key set."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv(GEMINI, ENV_KEY)

    assert app_module.selected_model() == "gemini-3.1-pro-preview"


def test_an_anthropic_key_alone_selects_the_claude_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """MT-100 AC-3's environment."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-dummy-0000")

    assert app_module.selected_model() == "claude-opus-5"


def test_the_stored_gemini_key_selects_the_gemini_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """MT-077's stored key counts, as it does at Start: `translation_env`."""
    _clear_provider_env(monkeypatch)
    _store(settings_path(), {"gemini_api_key": STORED_KEY})

    assert app_module.selected_model() == "gemini-3.1-pro-preview"


def test_no_key_anywhere_is_refused_with_the_no_api_key_sentence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MT-100 AC-4: the `ProviderError` the summary quotes."""
    _clear_provider_env(monkeypatch)

    with pytest.raises(NoApiKey) as caught:
        app_module.selected_model()

    assert str(caught.value) == NO_API_KEY_TEXT


def test_two_keys_and_no_choice_are_refused_as_ambiguous(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-dummy-0000")
    monkeypatch.setenv(GEMINI, ENV_KEY)

    with pytest.raises(AmbiguousProvider) as caught:
        app_module.selected_model()

    assert str(caught.value) == AMBIGUOUS_TEXT


def test_two_keys_and_an_explicit_choice_select_the_chosen_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`MANGATL_PROVIDER` decides, as at Start."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-dummy-0000")
    monkeypatch.setenv(GEMINI, ENV_KEY)
    monkeypatch.setenv("MANGATL_PROVIDER", "anthropic")

    assert app_module.selected_model() == "claude-opus-5"


def test_an_openai_key_alone_is_refused_as_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """MT-100 AC-8 / Out of scope: openai has no translator and no model."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-oai-dummy-0000")

    with pytest.raises(ProviderUnavailable) as caught:
        app_module.selected_model()

    assert str(caught.value) == "translation with openai is not available yet"


def test_the_default_window_setup_prices_with_selected_model(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """MT-100 C-5: `build_window`'s default `RunSetup` carries `selected_model`,
    so a window built with no setup of its own prices on the environment's
    model. A Gemini key alone: two pages at $0.04 (MT-149 R-2b)."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv(GEMINI, ENV_KEY)
    folder = _chapter_folder(tmp_path)

    window = app_module.build_window([str(folder)])
    qtbot.addWidget(window)

    summary = window.centralWidget()
    assert isinstance(summary, ChapterSummary)
    assert summary.cost_estimate.lines[0] == (
        "Estimated for 2 pages with gemini-3.1-pro-preview: $0.08."
    )
    window.close()


# =============================================================================
# main - AC-1's order, AC-4 at startup
# =============================================================================


class _Run:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.windows: list[QMainWindow] = []


def _install_main(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    *,
    check: Callable[[], str | None] = lambda: None,
    answer: str | None = None,
) -> _Run:
    """`main` in process: a recording QApplication stand-in (a real `exec()`
    blocks), recording `check_bundled_models`, `build_window`, `ask_api_key`
    and `show_warning`. `first_run` is the real one."""
    run = _Run()
    real_build = app_module.build_window

    def recording_check() -> str | None:
        run.events.append("check_bundled_models")
        return check()

    def recording_build(arguments: Sequence[str], **options: Any) -> QMainWindow:
        run.events.append("build_window")
        window = real_build(arguments, **options)
        qtbot.addWidget(window)
        run.windows.append(window)
        return window

    def recording_ask(parent: object = None) -> str | None:
        run.events.append("ask_api_key")
        return answer

    def recording_warning(message: str) -> None:
        run.events.append(f"show_warning: {message}")

    class _RecordingQApplication:
        def __init__(self, argv: list[str]) -> None:
            run.events.append("QApplication")

        def setStyleSheet(self, sheet: str) -> None:
            pass

        def exec(self) -> int:
            run.events.append("exec")
            for window in run.windows:
                window.close()
            return 0

    monkeypatch.setattr(app_module, "check_bundled_models", recording_check)
    monkeypatch.setattr(app_module, "build_window", recording_build)
    monkeypatch.setattr(app_module, "ask_api_key", recording_ask, raising=False)
    monkeypatch.setattr(app_module, "show_warning", recording_warning, raising=False)
    monkeypatch.setattr(app_module, "QApplication", _RecordingQApplication)
    return run


def test_with_no_key_main_asks_after_the_weight_check_and_before_the_window(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-1: the dialog comes before the intake window is usable."""
    _clear_provider_env(monkeypatch)
    run = _install_main(qtbot, monkeypatch, answer=None)

    code = app_module.main(["mangatl"])

    assert run.events == [
        "QApplication",
        "check_bundled_models",
        "ask_api_key",
        "build_window",
        "exec",
    ], run.events
    assert code == 0, "Cancel at first run must leave the app running (AC-1, review-only)"
    assert not settings_path().exists(), "Cancel wrote a settings file"


def test_a_key_entered_at_startup_is_stored_before_the_window_is_built(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_provider_env(monkeypatch)
    run = _install_main(qtbot, monkeypatch, answer=TYPED_KEY)

    app_module.main(["mangatl"])

    assert run.events == [
        "QApplication",
        "check_bundled_models",
        "ask_api_key",
        "build_window",
        "exec",
    ], run.events
    stored = json.loads(settings_path().read_text(encoding="utf-8"))
    assert stored == {"gemini_api_key": TYPED_KEY}


@pytest.mark.parametrize("where", ["environment", "settings"])
def test_with_a_key_already_present_main_does_not_ask(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    where: str,
) -> None:
    """AC-4 at startup."""
    _clear_provider_env(monkeypatch)
    if where == "environment":
        monkeypatch.setenv(GEMINI, ENV_KEY)
    else:
        _store(settings_path(), {"gemini_api_key": STORED_KEY})
    run = _install_main(qtbot, monkeypatch, answer=TYPED_KEY)
    real_first_run = app_module.first_run
    consulted: list[tuple[Path, object]] = []

    def spy(settings_file: Path, env: Any, ask: Any) -> str | None:
        consulted.append((settings_file, env))
        return real_first_run(settings_file, env, ask)

    monkeypatch.setattr(app_module, "first_run", spy)

    app_module.main(["mangatl"])

    import os

    assert consulted == [(settings_path(), os.environ)], (
        f"main consulted first_run with {consulted}; C-3 is once, with settings_path()"
        " and os.environ - the control that this test reached the first-run step"
    )
    assert "ask_api_key" not in run.events, f"main asked although the {where} holds a key"
    assert run.events == ["QApplication", "check_bundled_models", "build_window", "exec"]


def test_a_failed_weight_check_never_asks_for_the_key(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-3: the failed-weights notice path is not the first-run path. Control:
    the same install with a passing check asks (the first test above)."""
    _clear_provider_env(monkeypatch)
    run = _install_main(qtbot, monkeypatch, check=lambda: "lama_fp32.onnx: sha256 mismatch")
    first_run_calls: list[object] = []
    # raising=True: the name must exist for "never called" to mean anything.
    monkeypatch.setattr(app_module, "first_run", lambda *a: first_run_calls.append(a))
    monkeypatch.setattr(app_module, "MainWindow", _closing_main_window(qtbot, run))

    code = app_module.main(["mangatl"])

    assert code == 1
    assert "ask_api_key" not in run.events, run.events
    assert first_run_calls == [], "main reached first_run on the failed-check path"


def test_an_unwritable_settings_file_is_shown_as_a_warning_and_the_window_still_opens(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-3: `first_run`'s returned problem reaches `show_warning`, before the
    window; the message never carries the key (AC-5)."""
    _clear_provider_env(monkeypatch)
    file = settings_path()
    file.parent.mkdir(parents=True)
    file.write_bytes(b"not json at all")
    run = _install_main(qtbot, monkeypatch, answer=TYPED_KEY)

    app_module.main(["mangatl"])

    warnings = [e for e in run.events if e.startswith("show_warning: ")]
    assert len(warnings) == 1, f"show_warning was called {len(warnings)} times: {run.events}"
    (warning,) = warnings
    assert warning.startswith(f"show_warning: {file} could not be read: "), warning
    assert _leaks(TYPED_KEY, warning) == [], f"the warning leaks the key: {warning!r}"
    assert run.events.index(warning) < run.events.index("build_window"), run.events
    assert file.read_bytes() == b"not json at all"


def test_the_seams_are_exported() -> None:
    for name in ("first_run", "translation_env", "ask_api_key", "show_warning"):
        assert name in app_module.__all__, f"{name} is not in mangatl.app.__all__ (C-3)"


def test_ask_api_key_is_the_dialog_modules_function(first_run_seams: Any) -> None:
    """C-3: `mangatl.app.ask_api_key` is a re-exported import - the seam -
    of `mangatl.ui.api_key_dialog.ask_api_key`. The autouse stub (C-4) replaced
    the name; the fixture kept what was there before."""
    import importlib

    dialog_module = importlib.import_module("mangatl.ui.api_key_dialog")

    assert first_run_seams.original_ask_api_key is dialog_module.ask_api_key, (
        "mangatl.app.ask_api_key is not mangatl.ui.api_key_dialog.ask_api_key (C-3)"
    )


def test_show_warning_is_a_settings_message_box(
    monkeypatch: pytest.MonkeyPatch, first_run_seams: Any
) -> None:
    """C-3: `show_warning(message)` is `QMessageBox.warning(None, "Settings",
    message)`. The autouse stub replaced the name; the fixture kept the real one."""
    real = first_run_seams.original_show_warning
    assert callable(real), "mangatl.app has no show_warning (C-3)"
    calls: list[tuple[object, str, str]] = []

    class _Box:
        @staticmethod
        def warning(parent: object, title: str, text: str, *rest: object) -> None:
            calls.append((parent, title, text))

    monkeypatch.setattr(app_module, "QMessageBox", _Box, raising=False)

    real("the message")

    assert calls == [(None, "Settings", "the message")]


def _closing_main_window(qtbot, run: _Run) -> type[MainWindow]:  # type: ignore[no-untyped-def]
    """`MainWindow` for the failed-check path: the notice it builds is held by
    the run, so the stand-in `exec` closes it."""

    class _Made(MainWindow):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            qtbot.addWidget(self)
            run.windows.append(self)

    return _Made


# =============================================================================
# MT-113 C-6: app.build_batch - the batch setup for the provider Start would use
# =============================================================================
#
# The same selection `build_stages` makes (the environment plus the stored key,
# `MANGATL_PROVIDER` choosing between two), handed to
# `compose.build_batch_submit`; `None` from it is `None` here. The collect half
# is `collect_volume` bound to `compose.build_batch_collector(selection)` at the
# batch-tier estimate, and the ceiling is the stored one the guard uses. Both
# compose builders are replaced at their module names, so no client is built.

#: MT-111 AC-1's batch-tier page estimate for gemini-3.1-pro-preview, written out.
BATCH_ESTIMATE_MICRO = 20_000

BatchSeams = tuple["BatchSubmitSpy", list[object], "FakeCollector"]


class BatchSubmitSpy:
    """`compose.build_batch_submit`: records each selection; `None` for
    anthropic, as the real one answers, else a closure sentinel."""

    def __init__(self) -> None:
        self.selections: list[object] = []
        self.closure = object()

    def __call__(self, selection: Any) -> object:
        self.selections.append(selection)
        return None if selection.provider == "anthropic" else self.closure


class FakeCollector:
    """`compose.build_batch_collector`'s collector: `(job name, pages) -> answer`.

    Answers every page with an empty, zero-usage result, so `collect_volume`
    writes and prices it - and its first `CallPriced` projects from the page
    estimate it was bound with (one priced call is under
    `MIN_SAMPLES_FOR_PROJECTION`, so the projection IS the estimate)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[int]]] = []

    def __call__(self, job_name: str, pages: Sequence[Any]) -> Any:
        from mangatl.domain.batch import BatchResults
        from mangatl.domain.translation import TokenUsage, TranslationResult

        self.calls.append((job_name, [page.ordinal for page in pages]))
        empty = TranslationResult(
            lines={}, usage=TokenUsage(0, 0, 0, 0), call=None, proposed_terms=()
        )
        return BatchResults({page.ordinal: empty for page in pages})


class ConsistencySpy:
    """`compose.build_consistency` (MT-141 C-2): records each selection it is
    asked for and answers `None` - "no pass", so a collection's events are
    exactly today's - unless `steps_wanted`, when it answers a fresh
    `RecordingStep` per call and keeps each in `steps`."""

    def __init__(self) -> None:
        self.selections: list[object] = []
        self.steps: list[RecordingStep] = []
        self.steps_wanted = False

    def __call__(self, selection: Any) -> RecordingStep | None:
        self.selections.append(selection)
        if not self.steps_wanted:
            return None
        step = RecordingStep()
        self.steps.append(step)
        return step


def _pass_marker() -> Any:
    """What a `RecordingStep` emits, so its place in a collection's events -
    and that it was handed the collection's own `emit` - is observable."""
    from mangatl.domain.events import CorrectionsApplied

    return CorrectionsApplied(
        applied=0, skipped_user_lines=0, unchanged_returned=0, chunks_run=1, chunks_refused=0
    )


class RecordingStep:
    """A `ChapterStep` `(project, run_id, emit) -> None` standing for the
    consistency pass: records each run id and emits `_pass_marker()`."""

    def __init__(self) -> None:
        self.run_ids: list[int] = []

    def __call__(self, project: Any, run_id: int, emit: Callable[[Any], None]) -> None:
        self.run_ids.append(run_id)
        emit(_pass_marker())


@pytest.fixture
def consistency_seam(monkeypatch: pytest.MonkeyPatch) -> ConsistencySpy:
    """`compose.build_consistency` replaced at its module name, as
    `batch_seams` replaces the batch builders - `app` imports it inside the
    function, so the name is looked up at each call. No client is built."""
    spy = ConsistencySpy()
    monkeypatch.setattr(compose_module, "build_consistency", spy)
    return spy


@pytest.fixture
def batch_seams(monkeypatch: pytest.MonkeyPatch, consistency_seam: ConsistencySpy) -> BatchSeams:
    # MT-141 C-2: `build_batch` builds the consistency pass too; with the batch
    # seams installed, the pass is the spy's `None` unless a test asks for a step.
    submit = BatchSubmitSpy()
    collector_selections: list[object] = []
    collector = FakeCollector()

    def build_batch_collector(selection: Any) -> FakeCollector:
        collector_selections.append(selection)
        return collector

    # raising=False: `build_batch_submit` does not exist before GREEN.
    monkeypatch.setattr(compose_module, "build_batch_submit", submit, raising=False)
    monkeypatch.setattr(compose_module, "build_batch_collector", build_batch_collector)
    return submit, collector_selections, collector


def _build_batch() -> Any:
    return app_module.build_batch()  # type: ignore[attr-defined]


def test_build_batch_binds_the_gemini_selection_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, batch_seams: BatchSeams
) -> None:
    submit, collector_selections, _collector = batch_seams
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv(GEMINI, ENV_KEY)

    setup = _build_batch()

    assert setup is not None, "a Gemini key alone has a batch"
    assert submit.selections == [Selection("gemini", ENV_KEY)]
    assert setup.submit is submit.closure
    assert collector_selections == [Selection("gemini", ENV_KEY)]


def test_build_batch_selects_the_stored_key_as_build_stages_does(
    monkeypatch: pytest.MonkeyPatch, batch_seams: BatchSeams
) -> None:
    submit, _selections, _collector = batch_seams
    _clear_provider_env(monkeypatch)
    _store(settings_path(), {"gemini_api_key": STORED_KEY})

    _build_batch()

    assert submit.selections == [Selection("gemini", STORED_KEY)]


def test_build_batch_is_none_for_a_provider_with_no_batch(
    monkeypatch: pytest.MonkeyPatch, batch_seams: BatchSeams
) -> None:
    submit, _selections, _collector = batch_seams
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    assert _build_batch() is None
    assert [getattr(s, "provider", None) for s in submit.selections] == ["anthropic"]


def test_build_batch_refuses_a_keyless_start_before_binding_anything(
    monkeypatch: pytest.MonkeyPatch, batch_seams: BatchSeams
) -> None:
    submit, collector_selections, _collector = batch_seams
    _clear_provider_env(monkeypatch)

    with pytest.raises(NoApiKey):
        _build_batch()
    assert submit.selections == []
    assert collector_selections == []


def _project_with_a_job(tmp_path: Path) -> tuple[Any, Any]:
    from mangatl.store.batch import pending_jobs, record_submission
    from mangatl.store.intake import read_chapter
    from mangatl.store.project import create_project

    folder = _chapter_folder(tmp_path)
    project = create_project(read_chapter(folder), project_dir_for(folder))
    with project.transaction() as cursor:
        chapter_id = int(cursor.execute("SELECT id FROM chapter").fetchone()[0])
        cursor.execute(
            "INSERT INTO run (chapter_id, started_at) VALUES (?, ?)",
            (chapter_id, "2026-11-04T08:00:00+00:00"),
        )
        run_id = int(cursor.execute("SELECT last_insert_rowid()").fetchone()[0])
    record_submission(project, run_id, "batches/abc", "gemini-3.1-pro-preview", 0, 1)
    (job,) = pending_jobs(project)
    return project, job


def test_build_batch_collects_one_job_through_collect_volume_at_the_batch_estimate(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    batch_seams: BatchSeams,
) -> None:
    from mangatl.domain.events import BatchCollected, CallPriced
    from mangatl.domain.money import Usd
    from mangatl.store.batch import pending_jobs

    _submit, _selections, collector = batch_seams
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv(GEMINI, ENV_KEY)
    setup = _build_batch()
    project, job = _project_with_a_job(tmp_path)
    events: list[object] = []
    try:
        # C-3's call shape, positionally, exactly as the controller makes it.
        setup.collect(project, job, events.append)
        left = pending_jobs(project)
    finally:
        project.__exit__(None, None, None)

    assert collector.calls == [("batches/abc", [0, 1])], (
        "the collect half did not ask the selection's collector for the job's pages"
    )
    assert left == (), "collect_volume did not collect the job"
    priced = [e for e in events if isinstance(e, CallPriced)]
    assert [e.ordinal for e in priced] == [0, 1]
    assert priced[0].projection.next_call == Usd.from_micro(BATCH_ESTIMATE_MICRO), (
        f"the collection projected {priced[0].projection.next_call}; C-6 binds the BATCH-tier"
        " estimate, $0.02 (the standard tier is $0.04)"
    )
    assert events[-1] == BatchCollected(job.id, 2, 0, ())


def test_build_batch_ceiling_is_the_stored_one_else_the_default(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    batch_seams: BatchSeams,
) -> None:
    from mangatl.domain.money import Usd

    _clear_provider_env(monkeypatch)
    monkeypatch.setenv(GEMINI, ENV_KEY)
    setup = _build_batch()
    project, _job = _project_with_a_job(tmp_path)
    try:
        default = setup.ceiling(project)
        with project.transaction() as cursor:
            cursor.execute("UPDATE chapter SET budget_ceiling_micro_usd = ?", (750_000,))
        stored = setup.ceiling(project)
    finally:
        project.__exit__(None, None, None)

    assert default == Usd.from_micro(2_000_000), "with nothing stored the ceiling is $2.00"
    assert stored == Usd.from_micro(750_000)


def test_the_default_window_setup_carries_build_batch(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    """MT-113 PO-1, at the app: `build_window`'s default `RunSetup` passes
    `app.build_batch`, so a window built with no setup of its own submits."""
    window = app_module.build_window([])
    qtbot.addWidget(window)
    setup = getattr(window, "_run_setup", None)

    assert isinstance(setup, RunSetup)
    missing = "app.build_batch is missing"
    assert setup.build_batch is getattr(app_module, "build_batch", missing)  # type: ignore[attr-defined]
    window.close()


# =============================================================================
# MT-141 AC-1: the collect closure hands `collect_volume` the consistency pass
# =============================================================================
#
# `build_batch` builds `compose.build_consistency(selection)` once per call,
# from the selection its collector was built from, and the collect closure
# passes it as `collect_volume(..., postlude=step)`. `collect_volume` runs it
# after the `BatchCollected` of the volume's last job, with the job's run id
# (MT-115 AC-6) - observed here through `RecordingStep`'s run ids and the
# marker it emits through the collection's own `emit`.


def _project_with_jobs(tmp_path: Path, ranges: Sequence[tuple[int, int]]) -> tuple[Any, Any]:
    """`_project_with_a_job`'s project, with one submitted job per range."""
    from mangatl.store.batch import pending_jobs, record_submission
    from mangatl.store.intake import read_chapter
    from mangatl.store.project import create_project

    folder = _chapter_folder(tmp_path)
    project = create_project(read_chapter(folder), project_dir_for(folder))
    with project.transaction() as cursor:
        chapter_id = int(cursor.execute("SELECT id FROM chapter").fetchone()[0])
        cursor.execute(
            "INSERT INTO run (chapter_id, started_at) VALUES (?, ?)",
            (chapter_id, "2026-11-04T08:00:00+00:00"),
        )
        run_id = int(cursor.execute("SELECT last_insert_rowid()").fetchone()[0])
    for k, (first, last) in enumerate(ranges):
        record_submission(project, run_id, f"batches/{k}", "gemini-3.1-pro-preview", first, last)
    return project, pending_jobs(project)


def test_build_batch_collects_the_volumes_only_job_then_runs_the_pass_once_with_its_run_id(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    batch_seams: BatchSeams,
    consistency_seam: ConsistencySpy,
) -> None:
    """AC-1, the batch half of the story's central claim (DV-2 puts the
    defect back): the step is built from the collector's selection, and runs
    exactly once, after the job's `BatchCollected`, with the job's run id,
    through the collection's `emit`."""
    from mangatl.domain.events import BatchCollected

    _submit, collector_selections, _collector = batch_seams
    consistency_seam.steps_wanted = True
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv(GEMINI, ENV_KEY)
    setup = _build_batch()
    project, job = _project_with_a_job(tmp_path)
    events: list[object] = []
    try:
        setup.collect(project, job, events.append)
    finally:
        project.__exit__(None, None, None)

    assert consistency_seam.selections == collector_selections == [Selection("gemini", ENV_KEY)], (
        f"build_consistency was asked for {consistency_seam.selections}; the collector's"
        f" selection is {collector_selections}"
    )
    (step,) = consistency_seam.steps
    assert step.run_ids == [job.run_id], f"the pass ran {len(step.run_ids)} times"
    assert events[-2:] == [BatchCollected(job.id, 2, 0, ()), _pass_marker()], (
        "the pass did not run after the job's BatchCollected, through the collection's emit"
    )


def test_build_batch_builds_the_pass_once_per_call_and_runs_it_only_after_the_last_job(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    batch_seams: BatchSeams,
    consistency_seam: ConsistencySpy,
) -> None:
    """AC-1: once per `build_batch` call, not once per collection - two
    jobs collected through one setup share one step, which runs once, after
    the second (the volume's last) job."""
    from mangatl.domain.events import BatchCollected

    consistency_seam.steps_wanted = True
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv(GEMINI, ENV_KEY)
    setup = _build_batch()
    project, (first, second) = _project_with_jobs(tmp_path, ((0, 0), (1, 1)))
    events: list[object] = []
    try:
        setup.collect(project, first, events.append)
        assert consistency_seam.selections == [Selection("gemini", ENV_KEY)]
        (step,) = consistency_seam.steps
        assert step.run_ids == [], "the pass ran with a job of the volume still pending"
        setup.collect(project, second, events.append)
    finally:
        project.__exit__(None, None, None)

    assert len(consistency_seam.selections) == 1, "a collection built the pass again"
    assert step.run_ids == [second.run_id]
    assert events[-2:] == [BatchCollected(second.id, 1, 0, ()), _pass_marker()]


def test_a_second_build_batch_call_builds_a_second_pass_from_a_second_selection(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    batch_seams: BatchSeams,
    consistency_seam: ConsistencySpy,
) -> None:
    """AC-1: each `build_batch()` resolves its own selection and builds its
    own step; a collection through the second runs the second step only."""
    _submit, collector_selections, _collector = batch_seams
    consistency_seam.steps_wanted = True
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv(GEMINI, ENV_KEY)
    _build_batch()
    second = _build_batch()

    assert consistency_seam.selections == [Selection("gemini", ENV_KEY)] * 2
    assert collector_selections == consistency_seam.selections
    assert len(consistency_seam.steps) == 2
    one, two = consistency_seam.steps
    assert one is not two

    project, job = _project_with_a_job(tmp_path)
    try:
        second.collect(project, job, lambda event: None)
    finally:
        project.__exit__(None, None, None)

    assert (one.run_ids, two.run_ids) == ([], [job.run_id])


def test_a_build_batch_whose_pass_is_none_collects_exactly_as_today(
    qtbot,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    batch_seams: BatchSeams,
    consistency_seam: ConsistencySpy,
) -> None:
    """AC-1 / AC-6: `build_consistency` was asked (an anthropic-like "no
    pass" answer here), and the collection's events are today's - the
    pages' `CallPriced`, then `BatchCollected`, last."""
    from mangatl.domain.events import BatchCollected, CallPriced

    _clear_provider_env(monkeypatch)
    monkeypatch.setenv(GEMINI, ENV_KEY)
    setup = _build_batch()
    project, job = _project_with_a_job(tmp_path)
    events: list[object] = []
    try:
        setup.collect(project, job, events.append)
    finally:
        project.__exit__(None, None, None)

    assert consistency_seam.selections == [Selection("gemini", ENV_KEY)], (
        "build_batch did not ask build_consistency for the selection's pass"
    )
    assert [type(e) for e in events] == [CallPriced, CallPriced, BatchCollected]
    assert events[-1] == BatchCollected(job.id, 2, 0, ())


# =============================================================================
# MT-141 AC-2 / AC-6: app.build_postlude - the pass a Start would run
# =============================================================================


def _build_postlude() -> Any:
    return app_module.build_postlude()  # type: ignore[attr-defined]


def test_build_postlude_is_exported_beside_build_batch() -> None:
    """C-2: a public name of `mangatl.app`."""
    assert "build_postlude" in app_module.__all__


def test_build_postlude_builds_the_pass_for_the_environments_gemini_key(
    monkeypatch: pytest.MonkeyPatch, consistency_seam: ConsistencySpy
) -> None:
    """AC-2: the selection `build_stages` makes; the step is
    `build_consistency`'s, handed back itself."""
    consistency_seam.steps_wanted = True
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv(GEMINI, ENV_KEY)

    step = _build_postlude()

    assert consistency_seam.selections == [Selection("gemini", ENV_KEY)]
    assert step is consistency_seam.steps[0]


def test_build_postlude_selects_the_stored_key_as_build_stages_does(
    monkeypatch: pytest.MonkeyPatch, consistency_seam: ConsistencySpy
) -> None:
    """AC-2: the environment plus the stored key."""
    _clear_provider_env(monkeypatch)
    _store(settings_path(), {"gemini_api_key": STORED_KEY})

    _build_postlude()

    assert consistency_seam.selections == [Selection("gemini", STORED_KEY)]


def test_build_postlude_lets_mangatl_provider_choose_between_two_keys(
    monkeypatch: pytest.MonkeyPatch, consistency_seam: ConsistencySpy
) -> None:
    """AC-2: `MANGATL_PROVIDER` choosing between two."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-dummy-0000")
    monkeypatch.setenv(GEMINI, ENV_KEY)
    monkeypatch.setenv("MANGATL_PROVIDER", "gemini")

    _build_postlude()

    assert consistency_seam.selections == [Selection("gemini", ENV_KEY)]


def test_build_postlude_is_none_for_an_anthropic_selection(
    monkeypatch: pytest.MonkeyPatch, consistency_seam: ConsistencySpy
) -> None:
    """AC-6: `build_consistency` is asked for the anthropic selection, and its
    `None` - anthropic has no pass - is the answer."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-dummy-0000")

    assert _build_postlude() is None
    assert [getattr(s, "provider", None) for s in consistency_seam.selections] == ["anthropic"]


def test_build_postlude_refuses_a_keyless_start_before_building_anything(
    monkeypatch: pytest.MonkeyPatch, consistency_seam: ConsistencySpy
) -> None:
    """AC-6: no key anywhere - `NoApiKey`, the sentence `build_stages`
    raises, and `build_consistency` is never reached."""
    _clear_provider_env(monkeypatch)

    with pytest.raises(NoApiKey) as caught:
        _build_postlude()

    assert str(caught.value) == NO_API_KEY_TEXT
    assert consistency_seam.selections == []


def test_the_default_window_setup_carries_build_postlude(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    """AC-2: `build_window`'s default `RunSetup` carries `app.build_postlude`
    itself, so a window built with no setup of its own runs the pass."""
    window = app_module.build_window([])
    qtbot.addWidget(window)
    setup = getattr(window, "_run_setup", None)

    assert isinstance(setup, RunSetup)
    missing = "app.build_postlude is missing"
    assert setup.build_postlude is getattr(app_module, "build_postlude", missing)  # type: ignore[attr-defined]
    window.close()
