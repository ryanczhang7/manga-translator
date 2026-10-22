"""Entry point: `mangatl [<folder>]`.

With no argument it opens the folder intake (MT-055): a window that asks for a
chapter folder. With a chapter folder whose sibling `<folder>.mtproj` project
exists it opens the review `Workspace` on that chapter, first page shown
(MT-054). A folder of pages with no project opens the intake window showing
that chapter's summary - what a run would read - and a folder that cannot be
read as a chapter (no page images, not listable, a page that will not decode)
opens the intake window in its error state saying why (MT-057, PO-3/PO-8).
Anything else - a path that is not a folder, a project from a newer build, too
many arguments - opens a window with a notice saying what is wrong. Nothing
here creates a project or writes anything.

**The composition root for the window (MT-059, PO-3).** Every intake window is
given a `RunSetup`: `resolve_models` (`$MANGATL_MODELS`, read when Start is
pressed) and `build_stages` (`mangatl.compose.build_pipeline`, translation
on). Both import `mangatl.compose` inside their bodies, so a launch that only
reviews never loads `onnxruntime` or `anthropic`; import-linter counts those
imports all the same, which is why this module is exempt from the two
contracts that confine them, as `mangatl.cli` is. The window - `mangatl.ui` -
never imports `compose`; the run itself, and creating the project, are the
window's (`mangatl.ui.main_window`, `mangatl.ui.run`), never this module's.

`open_folder` is the one folder -> outcome decision. The command line calls it
and the intake window is handed it, so a folder picked or dropped in the window
behaves exactly as the same folder named on the command line.

`build_window` is the seam and is tested in process; `main` is a shell over it.

**The Gemini API key (MT-077).** At startup, after the bundled weights verify
and before the window is built, `first_run` asks for the key once - only when
neither `GEMINI_API_KEY` nor `settings.json` holds one - and stores what is
entered there. Cancel stores nothing and the app opens for review only. At
Start, `build_stages` reads the stored key into a *copy* of the environment
(`translation_env`; a key set in the environment wins, PO-2) and selects the
provider from that copy, so a keyless Start is refused before any weight loads.
A key is never logged or shown in full - only as `mask_key` renders it.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from importlib.resources import files
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox

from mangatl.app_paths import (
    bundled_manifest,
    bundled_models_dir,
    settings_path,
    workspace_state_path,
)
from mangatl.domain.page import Chapter
from mangatl.models.manifest import ModelHashMismatch, load_manifest, verify_bundled_models
from mangatl.models.providers import select_providers
from mangatl.pipeline.stage import Stage
from mangatl.store.intake import NoPagesFound, UnreadablePage, read_chapter
from mangatl.store.project import SchemaTooNew, open_project, project_dir_for
from mangatl.store.settings import (
    API_KEY_SETTING,
    SettingsUnreadable,
    gemini_api_key,
    mask_key,
    write_setting,
)
from mangatl.translate.provider import KEY_VARS, PROVIDER_VAR, select_provider
from mangatl.ui.api_key_dialog import ask_api_key
from mangatl.ui.contrast import SystemContrastSource
from mangatl.ui.main_window import MainWindow
from mangatl.ui.run import RunSetup
from mangatl.ui.stylesheet import BASE_TEMPLATE_RESOURCE, HC_TEMPLATE_RESOURCE, THEME_RESOURCE
from mangatl.ui.theme import ThemeController, apply_theme
from mangatl.ui.workspace import Workspace

__all__ = [
    "IntakeError",
    "ask_api_key",
    "build_stages",
    "build_window",
    "check_bundled_models",
    "first_run",
    "main",
    "open_folder",
    "resolve_models",
    "self_check",
    "show_warning",
    "translation_env",
]

_log = logging.getLogger("mangatl.app")

#: The variable a Gemini key is set in, never re-spelled (MT-078 PO-1).
_GEMINI_VAR = KEY_VARS["gemini"]

# The folder is always resolved, so the text names it the same way from any
# working directory.
NO_FOLDER_NOTICE = "No such folder: {folder}"
USAGE_NOTICE = "mangatl opens one chapter folder:  mangatl <folder>"
NO_PAGES_ERROR = "No page images in {folder}. This tool reads .png and .jpg files."
UNREADABLE_PAGE_ERROR = (
    "{filename} could not be opened as a page image."
    " Remove or replace it, then choose the folder again."
)
UNLISTABLE_ERROR = "Windows would not let this app read {folder}.\n{os_error}"

#: The running theme controller (MT-028): `main` keeps it here so a live
#: contrast change still reaches it after `main`'s locals are gone.
_theme: ThemeController | None = None


class IntakeError(str):
    """An outcome that is the intake's own error state (AC-2, AC-3, AC-6),
    as opposed to a notice (no such folder, a newer build's project).

    A `str` subclass so every caller that shows a reason keeps working; only
    the command line needs the difference, to pick the intake window over the
    notice window (MT-057 PO-8)."""

    __slots__ = ()


def open_folder(folder: Path) -> QMainWindow | Chapter | str:
    """What `folder` opens as: its project's `Workspace` NOT shown, the
    `Chapter` a run would read when it has no project, or the reason it is
    neither - an `IntakeError` when the folder itself cannot be read as a
    chapter, a plain notice otherwise."""
    folder = folder.resolve()
    if not folder.is_dir():
        return NO_FOLDER_NOTICE.format(folder=folder)
    try:
        # `open_project` checks the path before sqlite can create anything, so
        # a folder with no project writes nothing.
        project = open_project(project_dir_for(folder))
    except FileNotFoundError:
        return _read(folder)
    except SchemaTooNew as error:
        return str(error)
    window = Workspace()
    if _theme is not None:
        # The canvas follows the running contrast theme (MT-073 AC-6).
        window.follow_theme(_theme)
    window.load_chapter(project)
    window.page_strip.setCurrentRow(0)
    # After `load_chapter`, which forgets a dragged column (MT-048): the
    # remembered one must survive it (MT-088 block 4).
    window.remember_layout(workspace_state_path())
    # The window owns the project from here: closed after the pending saves.
    window.closed.connect(lambda: project.__exit__(None, None, None))
    return window


def _read(folder: Path) -> Chapter | IntakeError:
    """`folder` read by the store, in the order a run will use - one listing,
    one sort, both `read_chapter`'s (MT-057 C-2). Reads only."""
    try:
        return read_chapter(folder)
    except NoPagesFound:
        return IntakeError(NO_PAGES_ERROR.format(folder=folder))
    except UnreadablePage as error:
        # Named from the attribute, never parsed out of the message (C-1).
        return IntakeError(UNREADABLE_PAGE_ERROR.format(filename=error.filename))
    except OSError as error:
        # The operating system's own words, passed through, not paraphrased.
        os_error = error.strerror if error.strerror is not None else str(error)
        return IntakeError(UNLISTABLE_ERROR.format(folder=folder, os_error=os_error))


def resolve_models() -> Path | None:
    """The models folder `$MANGATL_MODELS` names, read now, else the bundled
    weights when they are there (MT-024 AC-9), or `None` when neither is."""
    from mangatl.compose import ModelsNotFound, resolve_models_dir

    try:
        return resolve_models_dir(None, os.environ, bundled_models_dir())
    except ModelsNotFound:
        return None


def translation_env(env: Mapping[str, str], settings_file: Path) -> dict[str, str]:
    """A copy of `env` carrying the stored Gemini key when `env` has none.

    A key set in the environment wins over the stored one (PO-2, AC-6); an
    empty variable counts as unset. `env` itself is never changed.
    """
    result = dict(env)
    if not result.get(_GEMINI_VAR):
        stored = gemini_api_key(settings_file)
        if stored:
            result[_GEMINI_VAR] = stored
    return result


def build_stages(models_dir: Path) -> tuple[Stage, ...]:
    """The real stage list, translation on - what `mangatl-run` runs, with the
    provider selected from the environment plus the stored key.

    `select_provider` refuses (`NoApiKey`, ...) before `build_pipeline` is
    called, so a refused Start loads no weight."""
    from mangatl.compose import build_pipeline

    env = translation_env(os.environ, settings_path())
    selection = select_provider(os.environ.get(PROVIDER_VAR) or None, env)
    return build_pipeline(models_dir, translate=True, selection=selection)


def first_run(
    settings_file: Path, env: Mapping[str, str], ask: Callable[[], str | None]
) -> str | None:
    """Ask for the Gemini key once when neither `env` nor `settings_file` has one.

    A key entered is stored in `settings_file` beside whatever it held. Returns
    `None`, or - when the file could not be written - why, as a message that
    never carries the key (AC-5). Cancel (`ask()` returning `None`) writes
    nothing: the app runs for review only.
    """
    if env.get(_GEMINI_VAR) or gemini_api_key(settings_file):
        return None
    key = ask()
    if key is None:
        return None
    try:
        write_setting(settings_file, API_KEY_SETTING, key)
    except (SettingsUnreadable, OSError) as error:
        _log.warning("Gemini API key not saved: %s", error)
        return str(error)
    _log.info("Gemini API key saved (%s)", mask_key(key))
    return None


def show_warning(message: str) -> None:
    """A warning box titled "Settings". The seam `main` calls and tests replace."""
    QMessageBox.warning(None, "Settings", message)


def build_window(arguments: Sequence[str], *, run_setup: RunSetup | None = None) -> QMainWindow:
    """The window for a command line without the program name, NOT shown.

    Every intake window gets `run_setup`, by default the real one - looked up
    when this runs, so it is this module's `resolve_models` and `build_stages`
    as they are then."""
    if run_setup is None:
        run_setup = RunSetup(resolve_models, build_stages)
    if not arguments:
        return MainWindow(open_folder=open_folder, run_setup=run_setup)
    if len(arguments) > 1:
        return MainWindow(notice=USAGE_NOTICE)
    outcome = open_folder(Path(arguments[0]))
    if isinstance(outcome, Chapter):
        intake = MainWindow(open_folder=open_folder, run_setup=run_setup)
        intake.show_summary(outcome)
        return intake
    if isinstance(outcome, IntakeError):
        intake = MainWindow(open_folder=open_folder, run_setup=run_setup)
        intake.show_error(outcome)
        return intake
    if isinstance(outcome, str):
        return MainWindow(notice=outcome)
    return outcome


def check_bundled_models() -> str | None:
    """Why the bundled weights cannot be trusted, or `None` (MT-024 AC-5, C-6).

    `None` when there is no bundled models directory (a plain checkout) or every
    weight verifies; the `ModelHashMismatch` message otherwise. Verified against
    `bundled_manifest()`, which in a checkout sits beside the download directory
    rather than inside it. The seam `main` calls and tests replace.
    """
    root = bundled_models_dir()
    if not root.is_dir():
        return None
    try:
        verify_bundled_models(root, bundled_manifest())
    except ModelHashMismatch as error:
        return str(error)
    return None


def self_check(report: Path) -> int:
    """`mangatl --check <report>`: does the installed app load what it ships?

    MT-024 C-6, AC-7. Writes six lines to `report` - the three theme resources,
    the fonts, the weights and the provider the detector actually runs on - and
    returns 0, or 1 when any line failed, with its reason on that line. A file,
    never stdout: the frozen binary is `console=False` and has none. Every
    check is caught, because an exception here would open a traceback window
    on a machine nobody is watching.
    """
    lines: list[str] = []
    failed = False
    for label, resource in (
        ("theme", THEME_RESOURCE),
        ("theme-template", BASE_TEMPLATE_RESOURCE),
        ("theme-hc-template", HC_TEMPLATE_RESOURCE),
    ):
        try:
            size = len(files("mangatl.ui").joinpath(resource).read_bytes())
        except OSError as error:
            lines.append(f"{label}: {error}")
            failed = True
        else:
            lines.append(f"{label}: ok ({size} bytes)")

    from mangatl.typeset.font import FACE_FILES, FONT_DIR, OFL_FILENAME

    shipped = [*FACE_FILES.values(), FONT_DIR / OFL_FILENAME]
    absent = [path.name for path in shipped if not path.is_file()]
    if absent:
        lines.append(f"fonts: missing {', '.join(absent)}")
        failed = True
    else:
        lines.append(f"fonts: ok ({len(FACE_FILES)} faces, {OFL_FILENAME})")

    try:
        verify_bundled_models(bundled_models_dir(), bundled_manifest())
        count = len(load_manifest(bundled_manifest()))
    except (ModelHashMismatch, OSError, ValueError) as error:
        lines.append(f"models: {error}")
        failed = True
    else:
        lines.append(f"models: ok ({count} verified)")

    # The detector alone: one session answers which provider is in use.
    from mangatl.compose import DETECTOR_FILENAME, available_providers
    from mangatl.detect.session import load_detector, selected_provider

    try:
        detector = load_detector(
            bundled_models_dir() / DETECTOR_FILENAME, select_providers(available_providers())
        )
        lines.append(f"provider: {selected_provider(detector)}")
    except Exception as error:  # reported on its line, never raised (see above)
        lines.append(f"provider: failed ({error})")
        failed = True

    report.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    """Run the application. Returns the Qt exit code.

    `mangatl --check <report>` - exactly that shape - is `self_check`, returned
    before any `QApplication` exists. Otherwise, after the theme and before any
    window, the bundled weights are verified; a weight that does not verify
    opens a notice naming it and `main` returns 1 (MT-024 AC-5). When they
    verify, `first_run` asks for the Gemini API key if none is set or stored
    (MT-077), and a settings file it could not write is shown as a warning;
    then the window is built.
    """
    global _theme
    argv = argv if argv is not None else sys.argv
    if len(argv) == 3 and argv[1] == "--check":
        return self_check(Path(argv[2]))
    app = QApplication(argv)
    # Before any window is built, so none is ever shown unthemed (MT-061). The
    # controller follows the system contrast theme from here on (MT-028), so it
    # is held on the module, past `main`'s locals.
    _theme = apply_theme(app, SystemContrastSource())
    error = check_bundled_models()
    if error is not None:
        notice = MainWindow(notice=error)
        notice.show()
        app.exec()
        return 1
    # `ask_api_key` and `show_warning` are looked up here, as module globals,
    # so the seams tests replace are the ones used (MT-077 C-3).
    problem = first_run(settings_path(), os.environ, ask_api_key)
    if problem is not None:
        show_warning(problem)
    window = build_window(argv[1:])
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
