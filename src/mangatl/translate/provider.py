"""Which provider a run translates with, decided from the environment (MT-078).

**PO-1: selection is by which key is set.** One of `ANTHROPIC_API_KEY`,
`GEMINI_API_KEY`, `OPENAI_API_KEY` set means that provider. More than one set
needs an explicit choice - `mangatl-run --provider`, else `MANGATL_PROVIDER` -
and without one the run **refuses to guess**: a named exception carrying a
sentence, never a silent pick.

**Pure, and it imports no SDK** (C-1). The environment is an argument, exactly
as `compose.resolve_models_dir` takes it (MT-036), so every branch is testable
in `tests/core` with a plain dict and no credential. Nothing here may import
`anthropic` or any SDK a later provider brings: `mangatl.ui` and `mangatl.cli`
import this module to catch `ProviderError`, and must not pull a client library
in by doing so. Binding a selection to a translator is `compose`'s job.

**`select_provider` does not read `PROVIDER_VAR`.** The caller resolves "the
flag beats the variable" and passes one explicit choice; an empty choice is "no
choice" (PO-7), the same reading as an empty key.

**No message carries a key's value** (C-6), in whole or in part, and
`Selection`'s `repr` leaves the key out (PO-6).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

__all__ = [
    "KEY_VARS",
    "PROVIDERS",
    "PROVIDER_VAR",
    "AmbiguousProvider",
    "KeyMissingForProvider",
    "NoApiKey",
    "Provider",
    "ProviderError",
    "ProviderUnavailable",
    "Selection",
    "UnknownProvider",
    "select_provider",
]

Provider = Literal["anthropic", "gemini", "openai"]

#: Every provider, in the one order every message names them.
PROVIDERS: tuple[Provider, ...] = ("anthropic", "gemini", "openai")

#: The variable the user was told to set for each provider (PO-1).
KEY_VARS: Mapping[Provider, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
}

#: The explicit choice when more than one key is set. Read by the callers, not
#: by `select_provider`.
PROVIDER_VAR: str = "MANGATL_PROVIDER"


@dataclass(frozen=True)
class Selection:
    """The provider a run translates with, and that provider's key."""

    provider: Provider
    #: Out of the `repr` so that logging a selection cannot print a key (C-6).
    api_key: str = field(repr=False)


class ProviderError(Exception):
    """No provider could be selected or bound. The message is the whole of
    what the user is told, so it names what to set or choose."""


class NoApiKey(ProviderError):
    """None of the three key variables is set (AC-3)."""


class AmbiguousProvider(ProviderError):
    """More than one key is set and nothing chose between them (AC-2)."""


class KeyMissingForProvider(ProviderError):
    """The chosen provider's key is not set (AC-4)."""


class UnknownProvider(ProviderError):
    """The explicit choice is not one of `PROVIDERS` (AC-5)."""


class ProviderUnavailable(ProviderError):
    """A known provider with no translator yet. Raised by `compose` (C-2) and
    defined here so the CLI and the window catch one base."""


def select_provider(explicit: str | None, env: Mapping[str, str]) -> Selection:
    """The provider `explicit` names, else the only one whose key is set.

    "Set" is present and non-empty, with no stripping: a key padded with
    whitespace is passed through for the SDK to reject. `explicit` empty or
    `None` is no choice.
    """
    if explicit:
        provider = _known(explicit)
        key = env.get(KEY_VARS[provider])
        if not key:
            raise KeyMissingForProvider(
                f"provider {provider} was chosen but {KEY_VARS[provider]} is not set"
            )
        return Selection(provider, key)

    set_providers = [provider for provider in PROVIDERS if env.get(KEY_VARS[provider])]
    if not set_providers:
        raise NoApiKey(
            "no API key is set: set ANTHROPIC_API_KEY, GEMINI_API_KEY or OPENAI_API_KEY,"
            " or run with --no-translate"
        )
    if len(set_providers) > 1:
        raise AmbiguousProvider(
            f"API keys are set for more than one provider ({', '.join(set_providers)});"
            f" choose one with --provider or {PROVIDER_VAR}"
        )
    (provider,) = set_providers
    return Selection(provider, env[KEY_VARS[provider]])


def _known(value: str) -> Provider:
    """`value` as a `Provider`, or `UnknownProvider` naming it. Case-sensitive."""
    for provider in PROVIDERS:
        if value == provider:
            return provider
    raise UnknownProvider(f"unknown provider {value!r}: choose one of {', '.join(PROVIDERS)}")
