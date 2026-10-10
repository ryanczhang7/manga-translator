---
id: EPIC-08
title: Translating with the key you have - Gemini and OpenAI beside Claude
status: todo
stories: [MT-078, MT-079, MT-080, MT-081]
---

*Added 2026-10-09 by lead-po on Claude Fable 5.1, from the user's request
raised during MT-038 PLANNED: "Build it so I can use a Google Gemini API or
OpenAI GPT API key as well." The product decisions it rests on (which key
picks the provider, the default model per provider, MT-038 staying
Claude-only) are the user's, dated 2026-10-09, recorded as PO-1 to PO-3 in
MT-078 `## Context`.*

## Goal

A user who has a Google Gemini key or an OpenAI key, and no Anthropic key,
translates a chapter the same way: set the one key, run, review. The provider
is the one whose key is set; with more than one key the user says which, and
the tool never guesses. Every call, on every provider, is priced into the
same ledger and held under the same $2 ceiling, and each provider's per-page
cost is a measured number before the epic is done.

## Why now

The user asked for it, and the cost of waiting is the cost of a second
adapter being written against a seam that was never cut: `EPIC-04` bound
`compose` to one SDK by name, and MT-077 (the first-run key dialog) is about
to make that one key a settings-file fact. Cutting the seam before MT-077
means MT-077 grows from one key to three once, rather than being rewritten.

## Done when

With exactly one of `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`
set, `mangatl-run` and the window translate a chapter on that provider; with
two set and no `--provider`/`MANGATL_PROVIDER`, the run refuses in one line
before loading anything; the ledger prices every Gemini and OpenAI call from
a rate row the run's own `rate_table_version` names; and each of MT-080 and
MT-081 carries, in `## Notes`, one real call's four usage counts, the model
string the provider reported, and the measured cost × 20 beside the $2.00
ceiling. Claude's request is byte-for-byte what MT-011/MT-014 send today.

## Stories

- **MT-078** — the seam: provider selection from the environment and the
  flag, refuse-to-guess, `build_pipeline` binding by provider, Claude
  unchanged behind it.
- **MT-079** — the neutral pieces: system prompt, listing, context, capped
  image, response schema and the JSON parse as public SDK-free functions;
  Claude's request unchanged (chore; runs beside MT-078).
- **MT-080** — Gemini: the adapter, its rate row, its import contract, and
  its live measurement.
- **MT-081** — OpenAI: the same, after MT-080 (they share `compose.py`,
  `rates.py`, `pyproject.toml`).

## Deliberately not in this epic

No settings-file or dialog for the new keys - env vars only (PO-1); MT-077
is re-planned for three keys when it is reached. No provider-specific prompt
wording, image cap or image-token estimate: all three providers are asked
the same question with the same picture, so their measured costs and
acceptance rates are comparable, and tuning per provider is work for after
those measurements exist. No change to the budget guard or its bootstrap
estimate. No change to `docs/wiki/cost-model.awk`, which stays Claude's
model. No `GOOGLE_API_KEY` alias. No second model per provider (Flash, mini)
- a cheaper fallback is one rate row and one constant away once the
adapter exists, and it is a product decision which one.
