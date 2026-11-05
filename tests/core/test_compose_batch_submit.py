"""MT-113 C-2: `compose.build_batch_submit(selection)`, the provider half of C-1.

`None` for a provider with no batch (Anthropic). Otherwise a `ChapterSubmit`
closure - `(project, models_dir, emit, cancelled) -> job ids` - that does
**nothing at build time** (Start calls the builder on the GUI thread; the
weights load on the worker, when the closure is called) and, when called:
loads `build_pipeline(models_dir, translate=False)`, builds the glossary
prelude around a `GeminiClient(api_key=selection.api_key)` exactly as
`_translator` binds it, takes `build_batch_binding(selection,
display_name=project.chapter.source_dir.name)`, and hands all of it to
`submit_chapter` with `model_for("gemini")` and the batch-tier page estimate.

**Seams, all at `mangatl.compose`'s own names** (the module looks each up as a
global when the closure runs): `GeminiClient` (a recording fake),
`build_pipeline` (a recorder: no weight is ever read here), `glossary_prelude`
and `build_batch_binding` (wrapped: the real ones run, the arguments are
recorded) and `submit_chapter` (a recorder standing where
`pipeline.batch.submit_chapter` is bound - the handoff states that `compose`
imports it by that name).

**Oracle: mechanical.** The model id and the batch estimate are written out
(`gemini-3.1-pro-preview`, $0.02 - MT-111 AC-1's settled figure), never
computed through the module under test.

**RED:** `build_batch_submit` is reached inside `_build_batch_submit`, so each
test fails on the named absence.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

import pytest

import mangatl.compose as compose_module
from mangatl.domain.events import RunEvent
from mangatl.domain.money import Usd
from mangatl.pipeline.prelude import Pipeline
from mangatl.store.intake import read_chapter
from mangatl.store.project import Project, create_project, project_dir_for
from mangatl.translate import gemini
from mangatl.translate.glossary_pass import GLOSSARY_PASS_MAX_OUTPUT_TOKENS, glossary_pass_text
from mangatl.translate.provider import Selection

_KEY = "AIzaSyBatchSubmitKey0000aaaa"
_MODEL = "gemini-3.1-pro-preview"
#: MT-111 AC-1's settled batch-tier estimate for that model, written out.
_BATCH_ESTIMATE = Usd.from_micro(20_000)
#: The folder name: `display_name` is the chapter folder's name (C-2).
_FOLDER = "Chapter 7 - The Bridge"

_REAL_BUILD_PIPELINE = compose_module.build_pipeline


class _FakeClient:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        self.kwargs = dict(kwargs)


class _Stage:
    """A stage object `build_pipeline`'s recorder hands back: identity only."""

    name = "detect"

    def run(self, ctx: Any) -> None:
        raise AssertionError("no stage runs in these tests")

    def is_done(self, ctx: Any) -> bool:
        return False


@dataclass
class _Seams:
    clients: list[_FakeClient] = field(default_factory=list)
    pipelines: list[tuple[tuple[Any, ...], dict[str, Any]]] = field(default_factory=list)
    stages: tuple[Any, ...] = (_Stage(), _Stage())
    preludes: list[dict[str, Any]] = field(default_factory=list)
    prelude_steps: list[Any] = field(default_factory=list)
    bindings: list[dict[str, Any]] = field(default_factory=list)
    binding_values: list[Any] = field(default_factory=list)
    submits: list[dict[str, Any]] = field(default_factory=list)
    returns: tuple[int, ...] = (41, 42)


@pytest.fixture
def seams(monkeypatch: pytest.MonkeyPatch) -> _Seams:
    made = _Seams()

    def construct(*args: object, **kwargs: object) -> _FakeClient:
        client = _FakeClient(*args, **kwargs)
        made.clients.append(client)
        return client

    def build_pipeline(*args: Any, **kwargs: Any) -> Pipeline:
        made.pipelines.append((args, kwargs))
        return Pipeline(stages=made.stages, prelude=None)

    real_prelude = compose_module.glossary_prelude

    def glossary_prelude(*args: Any, **kwargs: Any) -> Any:
        bound = inspect.signature(real_prelude).bind(*args, **kwargs)
        made.preludes.append(dict(bound.arguments))
        step = real_prelude(*args, **kwargs)
        made.prelude_steps.append(step)
        return step

    real_binding = compose_module.build_batch_binding

    def build_batch_binding(*args: Any, **kwargs: Any) -> Any:
        bound = inspect.signature(real_binding).bind(*args, **kwargs)
        made.bindings.append(dict(bound.arguments))
        value = real_binding(*args, **kwargs)
        made.binding_values.append(value)
        return value

    def submit_chapter(
        project: Any,
        stages: Any,
        prelude: Any,
        submit: Any,
        request_size: Any,
        model_id: Any,
        page_estimate: Any,
        emit: Any,
        cancelled: Any,
    ) -> tuple[int, ...]:
        made.submits.append(
            {
                "project": project,
                "stages": stages,
                "prelude": prelude,
                "submit": submit,
                "request_size": request_size,
                "model_id": model_id,
                "page_estimate": page_estimate,
                "emit": emit,
                "cancelled": cancelled,
            }
        )
        return made.returns

    monkeypatch.setattr("mangatl.compose.GeminiClient", construct)
    monkeypatch.setattr("mangatl.compose.build_pipeline", build_pipeline)
    monkeypatch.setattr("mangatl.compose.glossary_prelude", glossary_prelude)
    monkeypatch.setattr("mangatl.compose.build_batch_binding", build_batch_binding)
    # raising=False: the name does not exist in `compose` before GREEN, and the
    # tests below fail on `build_batch_submit` first either way.
    monkeypatch.setattr("mangatl.compose.submit_chapter", submit_chapter, raising=False)
    return made


@pytest.fixture
def project(tmp_path: Path, png_bytes: Callable[..., bytes]) -> Iterator[Project]:
    folder = tmp_path / _FOLDER
    folder.mkdir()
    (folder / "01.png").write_bytes(png_bytes(20, 16))
    with create_project(read_chapter(folder), project_dir_for(folder)) as made:
        yield made


def _build_batch_submit(selection: Selection) -> Any:
    from mangatl.compose import build_batch_submit  # type: ignore[attr-defined]

    return build_batch_submit(selection)


def _emit(event: RunEvent) -> None:
    raise AssertionError("no event is emitted by the recorders")


def _never() -> bool:
    return False


# -- None for a provider with no batch -------------------------------------------


def test_an_anthropic_selection_has_no_batch_submit_and_builds_nothing(seams: _Seams) -> None:
    assert _build_batch_submit(Selection("anthropic", "sk-ant-x")) is None
    assert seams.clients == [], "an Anthropic selection constructed a GeminiClient"
    assert seams.pipelines == [], "an Anthropic selection reached build_pipeline"


# -- build time: nothing loads ------------------------------------------------------


def test_a_gemini_batch_submit_loads_no_weight_until_it_is_called(seams: _Seams) -> None:
    """Start calls the builder on the GUI thread (C-2): the weights must load on
    the worker, when the closure runs, never here."""
    submit = _build_batch_submit(Selection("gemini", _KEY))

    assert callable(submit), f"build_batch_submit answered {submit!r} for gemini"
    assert seams.pipelines == [], "build_batch_submit loaded the local stages at build time"
    assert seams.submits == []


# -- call time: the closure's wiring --------------------------------------------------


def test_calling_it_loads_the_local_stages_only_from_the_models_folder(
    seams: _Seams, project: Project, tmp_path: Path
) -> None:
    models = tmp_path / "models"

    _build_batch_submit(Selection("gemini", _KEY))(project, models, _emit, _never)

    assert len(seams.pipelines) == 1, f"build_pipeline was called {len(seams.pipelines)} times"
    args, kwargs = seams.pipelines[0]
    bound = inspect.signature(_REAL_BUILD_PIPELINE).bind(*args, **kwargs)
    assert bound.arguments == {"models_dir": models, "translate": False}, (
        f"build_pipeline was called with {bound.arguments}; C-2 is"
        " build_pipeline(models_dir, translate=False) - the LOCAL stages"
    )
    assert seams.submits[0]["stages"] == seams.stages


def test_calling_it_hands_submit_chapter_the_gemini_model_and_the_batch_estimate(
    seams: _Seams, project: Project, tmp_path: Path
) -> None:
    ids = _build_batch_submit(Selection("gemini", _KEY))(project, tmp_path, _emit, _never)

    assert len(seams.submits) == 1, f"submit_chapter was called {len(seams.submits)} times"
    call = seams.submits[0]
    assert call["project"] is project
    assert call["model_id"] == _MODEL
    assert call["page_estimate"] == _BATCH_ESTIMATE, (
        f"page_estimate was {call['page_estimate']}; C-2 is the batch tier, $0.02"
    )
    assert call["emit"] is _emit
    assert call["cancelled"] is _never
    assert ids == seams.returns, "the closure did not return submit_chapter's job ids"


def test_the_prelude_is_the_glossary_pass_around_a_client_with_the_selections_key(
    seams: _Seams, project: Project, tmp_path: Path
) -> None:
    _build_batch_submit(Selection("gemini", _KEY))(project, tmp_path, _emit, _never)

    assert len(seams.preludes) == 1, f"glossary_prelude was built {len(seams.preludes)} times"
    built = seams.preludes[0]
    propose = built["propose"]
    assert isinstance(propose, partial) and propose.func is gemini.propose_glossary, (
        f"the prelude proposes with {propose!r}, not partial(gemini.propose_glossary, client)"
    )
    (client,) = propose.args
    assert isinstance(client, _FakeClient) and client.kwargs == {"api_key": _KEY}
    assert built["model_id"] == _MODEL
    assert built["listing"] is glossary_pass_text
    assert built["max_output_tokens"] == GLOSSARY_PASS_MAX_OUTPUT_TOKENS
    assert seams.submits[0]["prelude"] is seams.prelude_steps[0], (
        "submit_chapter was not handed the glossary prelude that was built"
    )


def test_the_batch_binding_is_named_for_the_chapter_folder_and_handed_over(
    seams: _Seams, project: Project, tmp_path: Path
) -> None:
    selection = Selection("gemini", _KEY)

    _build_batch_submit(selection)(project, tmp_path, _emit, _never)

    assert len(seams.bindings) == 1, f"build_batch_binding was called {len(seams.bindings)} times"
    assert seams.bindings[0] == {"selection": selection, "display_name": _FOLDER}
    binding = seams.binding_values[0]
    call = seams.submits[0]
    assert call["submit"] is binding.submit
    assert call["request_size"] is binding.request_size


def test_every_client_the_closure_builds_carries_the_selections_key(
    seams: _Seams, project: Project, tmp_path: Path
) -> None:
    _build_batch_submit(Selection("gemini", _KEY))(project, tmp_path, _emit, _never)

    assert seams.clients, "no GeminiClient was built"
    assert [(c.args, c.kwargs) for c in seams.clients] == [((), {"api_key": _KEY})] * len(
        seams.clients
    ), "a GeminiClient was built without the selection's key, passed as api_key="
