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

    def __init__(self, *, raise_after: Exception | None = None) -> None:
        self.calls: list[tuple[Path, dict[str, Any]]] = []
        self.raise_after = raise_after

    def __call__(self, models_dir: Path, **kwargs: Any) -> tuple[()]:
        self.calls.append((models_dir, dict(kwargs)))
        if self.raise_after is not None:
            raise self.raise_after
        return ()


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
    model. A Gemini key alone: two pages at $0.03."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv(GEMINI, ENV_KEY)
    folder = _chapter_folder(tmp_path)

    window = app_module.build_window([str(folder)])
    qtbot.addWidget(window)

    summary = window.centralWidget()
    assert isinstance(summary, ChapterSummary)
    assert summary.cost_estimate.lines[0] == (
        "Estimated for 2 pages with gemini-3.1-pro-preview: $0.06."
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
