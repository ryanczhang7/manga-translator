"""`mangatl.translate.provider`: which provider a run translates with (MT-078).

Covers **AC-1 to AC-5** and **C-6** at the one function that decides them,
`select_provider(explicit, env)`, and **C-1**'s shape: the names, the order of
`PROVIDERS`, the variable names, a frozen `Selection`, one exception base.

**Oracle partition: all mechanical** (story `## Acceptance criteria`). Mappings
in, a `Selection` or one named exception with one exact message out. Every
message below is pinned **character for character** rather than by
containment, because containment is the needle that cannot fail: a message
listing all three providers "names every provider whose key is set" in the
two-key case too, and an AC-2 assertion built from `in` would pass it. The
exact strings are RED's to choose (C-1, "exact text pinned by RED") and are
spelled out here as literals - never read back off the module - so the test
and the code cannot agree by construction.

**The environment is a plain dict.** C-1 makes the environment an argument,
exactly as `compose.resolve_models_dir` takes it (MT-036), so nothing here
touches `os.environ`, needs `monkeypatch`, or depends on what the developer
has exported.

**C-6 is pinned on every refusal that sees a key.** Each key below is a
recognisable dummy (`sk-SECRET-...`), distinct per provider, and every raised
message is checked for it - in whole, and for its last four characters, since
MT-077 will be the story that decides whether *any* part of a key may be shown
and this one shows none.

What these tests do NOT constrain: whether `explicit=""` (an empty
`MANGATL_PROVIDER`) is "no choice" or an unknown provider; which refusal wins
when an unknown choice meets a keyless environment; the exception classes'
constructor signatures beyond "a message"; `__all__`; and `Selection`'s
`repr`. Those are the implementer's.

**RED:** the module does not exist, so this file fails at import and **no
assertion in it has run** - the controls included. The story's handoff records
each one's expected outcome.
"""

from __future__ import annotations

import ast
import dataclasses
import subprocess
import sys
from collections.abc import Mapping
from itertools import combinations
from pathlib import Path

import pytest

import mangatl.translate.provider as provider_module
from mangatl.translate.provider import (
    KEY_VARS,
    PROVIDER_VAR,
    PROVIDERS,
    AmbiguousProvider,
    KeyMissingForProvider,
    NoApiKey,
    ProviderError,
    ProviderUnavailable,
    Selection,
    UnknownProvider,
    select_provider,
)

# -- the settled names, spelled out -------------------------------------------

#: PO-1's three variables, as the user types them into a shell.
_VARS: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
}

#: A recognisable, distinct dummy key per provider: a message carrying one is a
#: C-6 leak, and which one it carries says which branch leaked it.
_SECRETS: dict[str, str] = {
    "anthropic": "sk-SECRET-ant-0123",
    "gemini": "sk-SECRET-gem-4567",
    "openai": "sk-SECRET-oai-89ab",
}

# -- the exact messages (C-1: "exact text pinned by RED") ----------------------

_NO_KEY = (
    "no API key is set: set ANTHROPIC_API_KEY, GEMINI_API_KEY or OPENAI_API_KEY,"
    " or run with --no-translate"
)


def _ambiguous(names: tuple[str, ...]) -> str:
    """AC-2. `names` in `PROVIDERS` order, joined with `", "`."""
    return (
        f"API keys are set for more than one provider ({', '.join(names)});"
        " choose one with --provider or MANGATL_PROVIDER"
    )


def _key_missing(provider: str) -> str:
    """AC-4, the refusal half."""
    return f"provider {provider} was chosen but {_VARS[provider]} is not set"


def _unknown(value: str) -> str:
    """AC-5. The bad value in `repr` form, so an empty or space-padded value is
    visible, and the three valid names in `PROVIDERS` order."""
    return f"unknown provider {value!r}: choose one of anthropic, gemini, openai"


def _env(*providers: str, **extra: str) -> dict[str, str]:
    """An environment holding exactly `providers`' keys, plus `extra`."""
    env = {_VARS[name]: _SECRETS[name] for name in providers}
    env.update(extra)
    return env


def _assert_no_key_in(message: str) -> None:
    """C-6: no key value, in whole or by its last four characters."""
    leaked = [
        name for name, secret in _SECRETS.items() if secret in message or secret[-4:] in message
    ]
    assert leaked == [], f"the message carries the {leaked} key (C-6): {message!r}"


# =============================================================================
# C-1: the module's shape
# =============================================================================


def test_the_three_providers_are_named_in_the_one_order_every_message_uses() -> None:
    assert PROVIDERS == ("anthropic", "gemini", "openai"), (
        f"PROVIDERS is {PROVIDERS!r}; C-1 fixes the names and this order"
    )


def test_each_provider_is_read_from_the_variable_the_user_was_told_to_set() -> None:
    # PO-1: a promise to a person typing into a shell, spelled out above.
    assert dict(KEY_VARS) == _VARS


def test_the_choice_variable_is_mangatl_provider() -> None:
    assert PROVIDER_VAR == "MANGATL_PROVIDER"


def test_a_selection_is_a_frozen_provider_and_key_pair() -> None:
    selection = Selection("gemini", "k")

    assert [field.name for field in dataclasses.fields(Selection)] == ["provider", "api_key"]
    assert (selection.provider, selection.api_key) == ("gemini", "k")
    assert selection == Selection(provider="gemini", api_key="k")
    with pytest.raises(dataclasses.FrozenInstanceError):
        selection.provider = "openai"  # type: ignore[misc]


@pytest.mark.parametrize(
    "error",
    [NoApiKey, AmbiguousProvider, KeyMissingForProvider, UnknownProvider, ProviderUnavailable],
)
def test_every_refusal_is_one_base_the_cli_and_the_window_can_catch(error: type) -> None:
    """C-1: `cli.main` and the window catch `ProviderError` and nothing finer,
    so a refusal outside the base reaches the user as a traceback."""
    assert issubclass(error, ProviderError)
    assert error is not ProviderError
    assert str(error("the message")) == "the message", (
        "the exception's str is not its message; cli and the window show str(error)"
    )


def test_provider_error_is_an_ordinary_exception() -> None:
    assert issubclass(ProviderError, Exception)


# -- C-1: "it imports no SDK" ---------------------------------------------------

#: The SDK roots this epic's providers ship as. `google` covers both
#: `google.genai` and `google.generativeai`.
_SDK_ROOTS = ("anthropic", "openai", "google", "onnxruntime")


def _imported_modules(source: str) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.append(node.module)
    return modules


def test_control_the_import_scan_sees_a_function_body_sdk_import() -> None:
    planted = "from __future__ import annotations\ndef f():\n    import anthropic\n"

    assert _imported_modules(planted) == ["__future__", "anthropic"]


def test_the_module_imports_only_the_standard_library_and_domain() -> None:
    """C-1, read off the source: *"It may import `domain` only."* Every import
    anywhere in the file - module level or a function body, which
    import-linter also reports - is stdlib or `mangatl.domain`."""
    source = Path(provider_module.__file__).read_text(encoding="utf-8")
    stdlib = sys.stdlib_module_names | {"__future__"}

    foreign = [
        name
        for name in _imported_modules(source)
        if name.split(".")[0] not in stdlib
        and name != "mangatl.domain"
        and not name.startswith("mangatl.domain.")
    ]
    assert foreign == [], f"mangatl.translate.provider imports {foreign}; C-1 allows domain only"


def test_importing_the_module_loads_no_sdk_at_all() -> None:
    """C-1, observed rather than read: a fresh interpreter imports the module
    and reports which SDK roots ended up in `sys.modules`. Catches what the
    source scan cannot - an SDK pulled in transitively, through `mangatl`'s
    own package `__init__`s."""
    probe = (
        "import sys\n"
        "import mangatl.translate.provider\n"
        f"roots = {_SDK_ROOTS!r}\n"
        "print(sorted({m.split('.')[0] for m in sys.modules} & set(roots)))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False, timeout=60
    )

    assert result.returncode == 0, f"the import failed in a fresh interpreter: {result.stderr}"
    assert result.stdout.strip() == "[]", (
        f"importing mangatl.translate.provider loaded {result.stdout.strip()}; C-1 says it"
        " imports no SDK, so selection is testable with no SDK and no credential"
    )


def test_control_the_fresh_interpreter_probe_sees_an_sdk_when_one_is_imported() -> None:
    """The probe above with `anthropic` imported on purpose: a probe that
    printed `[]` for everything would make that test green forever."""
    probe = (
        "import sys\nimport anthropic\n"
        f"roots = {_SDK_ROOTS!r}\n"
        "print(sorted({m.split('.')[0] for m in sys.modules} & set(roots)))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False, timeout=60
    )

    assert "anthropic" in result.stdout, f"the probe did not see anthropic: {result.stdout!r}"


# =============================================================================
# AC-1: exactly one key, no choice -> that provider, with that key
# =============================================================================


@pytest.mark.parametrize("provider", ["anthropic", "gemini", "openai"])
def test_the_one_key_that_is_set_decides_the_provider_and_is_carried(provider: str) -> None:
    selection = select_provider(None, _env(provider, PATH="/usr/bin", HOME="/home/u"))

    assert selection == Selection(provider, _SECRETS[provider]), (  # type: ignore[arg-type]
        f"with only {_VARS[provider]} set the selection is {selection!r}"
    )


@pytest.mark.parametrize(
    ("empty", "real"),
    [("anthropic", "openai"), ("gemini", "anthropic"), ("openai", "gemini")],
)
def test_a_key_set_to_the_empty_string_counts_as_unset(empty: str, real: str) -> None:
    """AC-1's last clause: `FOO=` is "not set". A selector that asked only
    whether the name was *present* would call this ambiguous."""
    env = _env(real, **{_VARS[empty]: ""})

    assert select_provider(None, env) == Selection(real, _SECRETS[real])  # type: ignore[arg-type]


def test_a_key_with_surrounding_whitespace_is_passed_through_as_it_is() -> None:
    """C-1: no stripping - the SDK will reject a padded key, and that is the
    right place for the user to hear about it."""
    selection = select_provider(None, {"GEMINI_API_KEY": "  padded-key \n"})

    assert selection == Selection("gemini", "  padded-key \n")


def test_a_whitespace_only_key_is_set_not_empty() -> None:
    """C-1: "set" is non-empty **after no stripping**, so `"   "` is a key -
    and with a second key beside it the selection refuses to guess."""
    with pytest.raises(AmbiguousProvider):
        select_provider(None, _env("openai", ANTHROPIC_API_KEY="   "))


def test_a_variable_that_merely_resembles_a_key_is_not_one() -> None:
    env = {
        "ANTHROPIC_KEY": "x",
        "GEMINI_KEY": "x",
        "OPENAI_API_KEY_OLD": "x",
        "openai_api_key": "x",
        "GEMINI_API_KEY": _SECRETS["gemini"],
    }

    assert select_provider(None, env) == Selection("gemini", _SECRETS["gemini"])


# =============================================================================
# AC-2: two or more keys, no choice -> refuse to guess
# =============================================================================

_MULTI: list[tuple[str, ...]] = [
    *combinations(("anthropic", "gemini", "openai"), 2),
    ("anthropic", "gemini", "openai"),
]


@pytest.mark.parametrize("providers", _MULTI, ids=["+".join(p) for p in _MULTI])
def test_several_keys_and_no_choice_refuse_to_guess_and_name_every_one_set(
    providers: tuple[str, ...],
) -> None:
    """**AC-2, the story's central claim.** An exception, not a return: a
    selector that picked the first key it found returns a `Selection` here and
    this test fails on "DID NOT RAISE". The message is pinned exactly, so it
    names the providers whose keys are set **and no other** - a message that
    listed all three would satisfy a containment check in the two-key cases."""
    with pytest.raises(AmbiguousProvider) as raised:
        select_provider(None, _env(*providers))

    assert str(raised.value) == _ambiguous(providers)
    _assert_no_key_in(str(raised.value))


def test_the_choice_variable_in_the_mapping_is_not_read_by_the_selector() -> None:
    """C-1: *"`select_provider` itself does not read `PROVIDER_VAR`"* - the
    caller resolves flag-over-variable and passes one choice. So with
    `explicit=None` a `MANGATL_PROVIDER` sitting in `env` changes nothing, and
    two keys still refuse."""
    env = _env("anthropic", "gemini", MANGATL_PROVIDER="gemini")

    with pytest.raises(AmbiguousProvider) as raised:
        select_provider(None, env)

    assert str(raised.value) == _ambiguous(("anthropic", "gemini"))


# =============================================================================
# AC-3: no key at all
# =============================================================================


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"ANTHROPIC_API_KEY": "", "GEMINI_API_KEY": "", "OPENAI_API_KEY": ""},
        {"PATH": "/usr/bin", "MANGATL_MODELS": "/models"},
    ],
    ids=["empty", "all-three-empty-strings", "unrelated-only"],
)
def test_no_key_names_all_three_variables_and_the_way_to_run_without_one(
    env: Mapping[str, str],
) -> None:
    with pytest.raises(NoApiKey) as raised:
        select_provider(None, env)

    assert str(raised.value) == _NO_KEY


# =============================================================================
# AC-4: an explicit choice wins over the other keys, and needs its own
# =============================================================================


@pytest.mark.parametrize("provider", ["anthropic", "gemini", "openai"])
def test_an_explicit_choice_wins_even_with_every_key_set(provider: str) -> None:
    """Each key is distinct, so the carried key says which provider's variable
    was read - a selector that chose right and carried the first key it saw
    fails here."""
    selection = select_provider(provider, _env("anthropic", "gemini", "openai"))

    assert selection == Selection(provider, _SECRETS[provider])  # type: ignore[arg-type]


@pytest.mark.parametrize("provider", ["anthropic", "gemini", "openai"])
def test_an_explicit_choice_whose_key_is_missing_is_refused_by_name(provider: str) -> None:
    """The other two keys are set: falling back to one of them would be the
    guess PO-1 forbids."""
    others = [name for name in ("anthropic", "gemini", "openai") if name != provider]

    with pytest.raises(KeyMissingForProvider) as raised:
        select_provider(provider, _env(*others))

    assert str(raised.value) == _key_missing(provider)
    _assert_no_key_in(str(raised.value))


def test_an_explicit_choice_whose_key_is_the_empty_string_is_refused() -> None:
    with pytest.raises(KeyMissingForProvider) as raised:
        select_provider("openai", _env("anthropic", OPENAI_API_KEY=""))

    assert str(raised.value) == _key_missing("openai")


# =============================================================================
# AC-5: an explicit choice that is not one of the three
# =============================================================================


@pytest.mark.parametrize("value", ["Anthropic", "claude", "GEMINI", "OpenAI", "gpt"])
def test_an_unknown_choice_names_the_bad_value_and_the_three_valid_ones(value: str) -> None:
    """Case-sensitive, lowercase only. Every key is set, so a selector that
    ignored a bad choice would fall through to AC-2's refusal - a different
    exception, and this test says so."""
    with pytest.raises(UnknownProvider) as raised:
        select_provider(value, _env("anthropic", "gemini", "openai"))

    assert str(raised.value) == _unknown(value)
    _assert_no_key_in(str(raised.value))
