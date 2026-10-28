# Gemini Batch API facts: discount, config, caching, turnaround, the 200k tier - MT-101

*Spike run 2026-10-28 by the `lead-po` agent on Claude Fable 5.1
(`claude-fable-5-1`), dispatched for MT-101. Branch
`story/MT-101-gemini-batch-api-facts-discount-config-c`, phase PLANNED. No
source, test, gate or `project.conf` file was changed; the only write is this
document. The SDK facts were introspected from the installed `google-genai`
2.29.0 (`uv.lock`), which is the version `translate/gemini.py` was written
against (MT-080 V-3). The live probe (AC-7) is **PENDING**: the account
reported `prepayment credits are depleted` on 2026-10-28 (MT-100 gate run,
MT-101 `## Notes` PO-1).*

Every fact below carries one of three tags: **[READ]** from a page or the
installed SDK, **[MEASURED]** by the live probe (none yet), **[INFERRED]**
where two sources are combined. A number with no `## Sources` entry is not
decided.

## Sources

All read 2026-10-28 (UTC). "Last updated" is the page's own footer line.

| # | URL | Last updated |
|---|---|---|
| S1 | https://ai.google.dev/gemini-api/docs/batch-api | 2026-09-17 |
| S2 | https://ai.google.dev/gemini-api/docs/pricing | 2026-10-28 |
| S3 | https://ai.google.dev/gemini-api/docs/caching | 2026-10-23 |
| S4 | https://ai.google.dev/gemini-api/docs/structured-output | 2026-10-21 |
| S5 | https://ai.google.dev/gemini-api/docs/thinking | 2026-10-14 |
| S6 | https://ai.google.dev/gemini-api/docs/rate-limits | 2026-10-26 |
| S7 | https://ai.google.dev/api/batch-mode (REST reference, `batches` resource) | 2026-10-13 |
| S8 | https://ai.google.dev/gemini-api/docs/models/gemini-3.1-pro-preview | 2026-10-09 |
| S9 | https://googleapis.github.io/python-genai/ (SDK reference; the batch types section is past the first 100k characters and was NOT read there - S10 replaces it) | none shown |
| S10 | the installed `google-genai` 2.29.0, introspected with `inspect.signature` and `model_fields` under `uv run python` (command in F-10) | package upload 2026-10-07 (`uv.lock`) |
| S11 | https://github.com/googleapis/python-genai/issues/1103 ("No support for thinking budget in batch request API") | opened 2025-07-08, closed 2025-08-11 |
| S12 | https://discuss.ai.google.dev/t/structured-output-in-gemini-2-5-flash-lite-batch-mode-input-file/102297 (forum, community answer - supporting only) | not recorded |

Pages read through `WebFetch`, which summarises the page; where a quote is
given it is the summariser's verbatim excerpt. Prices change: S2's footer is
today's date, so the rates below are the ones published on the day of reading.

## Findings

Each finding says what the page says, and nothing more. Interpretation is in
`## Decided`.

- **F-1 - the discount [READ, S1, S2].** S1: batch is priced "at 50% of the
  standard cost" and "50% of the standard interactive API cost for the
  equivalent model." S2's paid-tier feature list: "Batch API (50% cost
  reduction)." S2's Gemini 3.1 Pro Preview table, paid tier, per 1M tokens:

  | Row | Standard <=200k | Standard >200k | Batch <=200k | Batch >200k |
  |---|---|---|---|---|
  | Input | $2.00 | $4.00 | $1.00 | $2.00 |
  | Output "(including thinking tokens)" | $12.00 | $18.00 | $6.00 | $9.00 |
  | Context caching | $0.20 | $0.40 | "Same as Standard": $0.20 | $0.40 |
  | Cache storage | $4.50 / 1M tokens / hour | same | same | same |

  S2 labels the output row "Output price (including thinking tokens)" for
  Standard, Batch, Flex and Priority alike. The Batch context-caching row
  reads "_Same as Standard_" - caching is NOT discounted in batch. Flex has the
  same numbers as Batch; Priority is 1.8x Standard. Neither is this epic's.
- **F-2 - the tier wording [READ, S2].** The input row reads "$2.00, prompts
  <= 200k tokens" and "$4.00, prompts > 200k tokens"; other rows shorten it to
  "prompts > 200k". No footnote says how the threshold is measured; the only
  footnotes are "*" (search charges) and "**" ("Can be tested in Google AI
  Studio."). The word is **prompts**, not "requests" or "total".
- **F-3 - what batch accepts [READ, S1].** "You can include any request
  configurations you would use in a standard non-batch request", with the
  examples temperature, system instructions, other modalities, tools (Google
  Search) and structured output. "The supported modalities for Batch API are
  the same as what's supported on the interactive (or non-batch) API." S1's
  structured-output example sets `'response_mime_type': 'application/json'`
  and `'response_schema': list[Recipe]` inside each request's `config`;
  `response_json_schema` does not appear on S1. **Thinking is not mentioned
  in S1's body** (only in the site navigation). S1 says the feature "is
  currently only available with the generateContent API" - which is the API
  `translate/gemini.py` uses.
- **F-4 - thinking in batch, from the SDK's tracker [READ, S11].** Issue
  #1103 (SDK 1.24.0, `gemini-2.5-flash`): `thinking_config` inside an inline
  request's `config` was refused at **create** time with `400
  INVALID_ARGUMENT`, message "Unknown name "thinkingConfig" at
  'batch.input_config.requests.requests[1].request.generation_config'". A
  maintainer closed it on 2025-08-11 as completed: "This is working.
  InlinedRequest.config.thinking_config.", against v1.29.0. So a rejected
  config field is reported as a 400 on `client.batches.create`, not as a
  per-request error after the job runs - the whole batch is refused and
  nothing is billed. Whether `thinking_level` (rather than `thinking_budget`)
  is accepted in batch on 3.1 Pro is **NOT FOUND in the docs read**; it is
  what the live probe is for.
- **F-5 - the config fields exist on the model [READ, S5, S8, S10].** S8
  lists for `gemini-3.1-pro-preview`: Batch API "Supported", Caching
  "Supported", Structured outputs "Supported", Thinking "Supported"; input
  limit 1,048,576 tokens, output limit 65,536. S5: `gemini-3.1-pro-preview`
  thinks at `high` by default and supports `low`, `medium`, `high` (no
  `minimal`); `max_output_tokens` "sets the maximum number of tokens a
  response can generate, including thought tokens"; "response pricing is the
  sum of output tokens and thinking tokens". S10: `GenerateContentConfig` has
  `response_mime_type`, `response_json_schema`, `thinking_config`,
  `max_output_tokens`, `system_instruction`, `cached_content`;
  `ThinkingLevel` = `THINKING_LEVEL_UNSPECIFIED, MINIMAL, LOW, MEDIUM, HIGH`.
- **F-6 - structured output page [READ, S4].** S4 has been rewritten around
  the Interactions API (`client.interactions.create(... response_format=...)`)
  and no longer names `response_mime_type` / `response_json_schema`; it
  confirms `additionalProperties` is supported ("Can be a boolean or a
  schema"). It does not mention batch. The `generateContent` spelling the
  adapter uses is S10's (both fields exist on `GenerateContentConfig`) and
  MT-080 V-3's ("the SDK refuses both at once" - unchanged in 2.29.0).
- **F-7 - caching in batch [READ, S1, S3].** S1: "Context caching is supported
  for batch requests" by "specifying the `cached_content` resource name in the
  configuration", and "If a request in your batch results in a cache hit, you
  pay the standard context caching rates." That is **explicit** caching. S3
  says implicit caching "is enabled by default for all Gemini 2.5 and newer
  models" with a 4,096-token minimum for Gemini 3.1 Pro Preview, and S3's body
  does not mention batch at all. Whether **implicit** cache hits occur inside
  a batch job is **NOT FOUND in the docs read**. S3 also now reports cache
  hits as `usage.total_cached_tokens` (Interactions API); the `generateContent`
  field the adapter reads, `cached_content_token_count`, still exists in
  S10's `GenerateContentResponseUsageMetadata`.
- **F-8 - turnaround and expiry [READ, S1].** "The target turnaround time is
  24 hours, but in majority of cases, it is much quicker." "Batch jobs are
  designed to complete within a 24-hour turnaround time."
  "`JOB_STATE_EXPIRED`: The job has expired because it was running or pending
  for more than 48 hours." "The job will not have any results to retrieve."
  Nothing is said about a job between 24 h and 48 h; it is simply still
  running. Results of a finished job are "available for download for 6 weeks,
  before they are permanently deleted" (file output; inline results live on
  the job resource). Job creation is not idempotent: resubmitting creates a
  second job.
- **F-9 - limits [READ, S1, S6].** Inline requests: "keep the total request
  size under 20MB"; input file: 2 GB; file storage: 20 GB; "Concurrent batch
  requests: 100"; enqueued tokens for Gemini 3.1 Pro Preview: Tier 1
  5,000,000, Tier 2 500,000,000, Tier 3 1,000,000,000. Batch limits are
  "separate from the non-batch API calls." No per-batch request count is
  stated.
- **F-10 - the SDK's spellings [READ, S10].** Command:
  `uv run python -c "import inspect; from google.genai import types;
  from google.genai.batches import Batches; ..."` printing
  `inspect.signature` of each method and `model_fields` of each type.
  - `Batches.create(*, model: str, src: BatchJobSource | list[InlinedRequest]
    | str | <dicts>, config: CreateBatchJobConfig | None = None) -> BatchJob`
  - `Batches.get(*, name: str, config=None) -> BatchJob`
  - `Batches.list(*, config: ListBatchJobsConfig | None) -> Pager[BatchJob]`
  - `Batches.cancel(*, name: str, config=None) -> None`
  - `Batches.delete(*, name: str, config=None) -> DeleteResourceJob`
  - `InlinedRequest(model: str | None, contents: ContentListUnion, metadata:
    dict[str, str] | None, config: GenerateContentConfig | None)` - a per-request
    `GenerateContentConfig`, the same type `build_request` returns.
  - `CreateBatchJobConfig(http_options, display_name: str | None, dest:
    BatchJobDestination | str | None, webhook_config)`
  - `BatchJob(name, display_name, state: JobState, error: JobError,
    create_time, start_time, end_time, update_time, model, src, dest:
    BatchJobDestination, completion_stats, output_info)`
  - `BatchJobDestination(format, gcs_uri, bigquery_uri, file_name,
    inlined_responses: list[InlinedResponse], inlined_embed_content_responses,
    vertex_dataset)`
  - `InlinedResponse(response: GenerateContentResponse | None, metadata:
    dict[str, str] | None, error: JobError | None)`
  - `JobError(details: list[str] | None, code: int | None, message: str | None)`
  - `JobState` members: `JOB_STATE_UNSPECIFIED, JOB_STATE_QUEUED,
    JOB_STATE_PENDING, JOB_STATE_RUNNING, JOB_STATE_SUCCEEDED,
    JOB_STATE_FAILED, JOB_STATE_CANCELLING, JOB_STATE_CANCELLED,
    JOB_STATE_PAUSED, JOB_STATE_EXPIRED, JOB_STATE_UPDATING,
    JOB_STATE_PARTIALLY_SUCCEEDED`.
  S1 documents six of these for the Gemini API (`PENDING, RUNNING, SUCCEEDED,
  FAILED, CANCELLED, EXPIRED`); the rest are Vertex AI's, carried by the
  shared SDK. S7's REST enum is `BATCH_STATE_*` with the same six names; the
  SDK maps it to `JobState`, and `batch_job.state.name` is what S1's examples
  compare. S7 adds `batchStats` (`requestCount`, `successfulRequestCount`,
  `failedRequestCount`, `pendingRequestCount`) on the REST resource, which
  the SDK exposes as `completion_stats`; S1: "Check the `batchStats` for
  `failedRequestCount` after a job completes."
- **F-11 - how a per-request error is reported [READ, S1, S7, S10].** Inline:
  each `InlinedResponse` has either `.response` or `.error` (S1 "has either
  `.response` ... or `.error`"); the error is a `JobError(code, message,
  details)` (S10), a `Status` in REST (S7). File output: each line "is a
  `GenerateContentResponse` or a status object" (S1), keyed by the request's
  `"key"`. Inline requests may carry `metadata: {"key": ...}` (S1's REST
  example; S10's `InlinedRequest.metadata`) and the response echoes it in
  `InlinedResponse.metadata` - the only way to pair inline responses with
  requests other than by position. **The order of `inlined_responses` relative
  to `src` is not stated** on S1 or S7: NOT FOUND.
- **F-12 - per-response usage [READ, S10; S1 silent].** S1 does not mention
  `usage_metadata`. S10: `InlinedResponse.response` is a full
  `GenerateContentResponse`, whose `usage_metadata` has the fields the adapter
  reads (`prompt_token_count`, `candidates_token_count`,
  `thoughts_token_count`, `cached_content_token_count`), so `_usage_of` in
  `translate/gemini.py` applies unchanged to a batch item. That the counts are
  actually populated in a batch response is what the live probe confirms.
- **F-13 - the epic's cost case [READ, EPIC-09 `## Why now`].** The epic's
  figures (per-page ~$5.10, batch ~$3.10 for 200 pages) were computed at a
  50% discount. F-1 confirms 50% on input and output and 0% on cache reads;
  with cache reads expected to be zero (`translate/gemini.py` C-2: a page's
  prefix is under the 4,096-token minimum), the ratio of the batch bill to the
  interactive bill is 0.50 exactly, and the epic's case stands as written.

## Live probe

**Status: PENDING** - the user runs this once the account has credit (it
reported "prepayment credits are depleted" on 2026-10-28) and pastes the
output into the results block below. Until then AC-7, and the "live probe"
column of D-4, are open.

**What it does.** Builds one page request with `build_request` from
`mangatl.translate.gemini` - the exact `GenerateContentConfig` the per-page
path sends (`response_mime_type`, `response_json_schema`, `thinking_config
= ThinkingConfig(thinking_level=MEDIUM)`, `max_output_tokens = 4096`,
`system_instruction`) - on the fixture page `fixtures/translate/kakeru-p1.png`
with three fake OCR regions, wraps it in one `InlinedRequest`, submits a batch
of one, polls until a terminal state, and prints the job name, final state,
the usage counts as the API reported them, the parsed JSON (or the rejection
verbatim), and the cost at the interactive row (`domain.rates.price`) beside
the batch figure from D-1. Then the control: the same request through
`translate_page` interactively.

**Cost estimate.** A 1,568-px page is ~1,000-1,300 image tokens plus ~1,500
tokens of system prompt, schema and listing; output at `MEDIUM` thinking is
~500-2,000 tokens. Interactive leg: ~3k x $2 + ~2k x $12 per 1M = **~$0.03
at most**; batch leg half that. Both legs together: **under $0.05**, in
practice a cent or two. (The story's "well under a cent" holds for the batch
leg's input; the thinking output is what makes it cents.)

**Run it** from the repository root with `GEMINI_API_KEY` set:

```bash
uv run python docs/wiki/audits/probe_MT-101.py   # after saving the block below to that path
```

Save the block to a gitignored or untracked path (the spike commits no code);
delete it afterwards. It imports `_usage_of`, a private helper, deliberately:
the probe wants to know whether the **adapter's own** reading of usage works on
a batch item, not whether a re-implementation does.

```python
"""MT-101 live probe: one Gemini batch of one page request, exactly as the
per-page path builds it, then the same request interactively as the control.

Prints everything AC-7 asks for. Unreviewed spike code; not production.
"""

from __future__ import annotations

import json
import os
import sys
import time
from decimal import Decimal
from pathlib import Path

from google.genai import Client, types

from mangatl.domain.glossary import EMPTY_CONTEXT
from mangatl.domain.line import OcrResult
from mangatl.domain.rates import price
from mangatl.translate.gemini import MODEL_ID, _usage_of, build_request, translate_page

# D-1 (MT-101): Gemini 3.1 Pro Preview, Batch, prompts <= 200k tokens, USD per 1M.
BATCH_INPUT = Decimal("1.00")
BATCH_OUTPUT = Decimal("6.00")
BATCH_CACHE_READ = Decimal("0.20")  # "Same as Standard" - no batch discount on cache

PAGE = Path("fixtures/translate/kakeru-p1.png")
REGIONS = [
    OcrResult("おはよう、カケル。"),
    OcrResult("今日も遅刻するの？"),
    OcrResult("…うるさいな。"),
]
POLL_SECONDS = 30
TERMINAL = {"JOB_STATE_SUCCEEDED", "JOB_STATE_FAILED", "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED"}


def batch_cost(usage) -> Decimal:
    """What D-1 says the batch leg costs, in dollars, unrounded."""
    return (
        Decimal(usage.input_tokens) * BATCH_INPUT
        + Decimal(usage.output_tokens) * BATCH_OUTPUT
        + Decimal(usage.cache_read_tokens) * BATCH_CACHE_READ
    ) / Decimal(1_000_000)


def report_usage(label: str, response) -> None:
    meta = response.usage_metadata
    print(f"[{label}] usage_metadata as reported: {meta.model_dump(exclude_none=True) if meta else None}")
    usage = _usage_of(meta)
    print(f"[{label}] TokenUsage: {usage}")
    interactive = price(MODEL_ID, usage)
    print(f"[{label}] interactive row ({interactive.rate_table_version}): ${interactive.cost}")
    print(f"[{label}] batch figure (MT-101 D-1): ${batch_cost(usage):.6f}")
    text = response.text or ""
    print(f"[{label}] response.text (verbatim):\n{text}")
    try:
        print(f"[{label}] parsed JSON: {json.dumps(json.loads(text), ensure_ascii=False, indent=2)}")
    except json.JSONDecodeError as exc:
        print(f"[{label}] NOT JSON: {exc}")


def main() -> int:
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY is not set", file=sys.stderr)
        return 2
    client = Client(api_key=os.environ["GEMINI_API_KEY"])
    page = PAGE.read_bytes()

    # --- the batch leg --------------------------------------------------------
    request = build_request(page, REGIONS, EMPTY_CONTEXT)
    config: types.GenerateContentConfig = request["config"]
    print("request config (what the per-page path sends):")
    print(json.dumps(config.model_dump(exclude_none=True), ensure_ascii=False, indent=2, default=str)[:4000])

    inlined = types.InlinedRequest(
        contents=request["contents"],
        config=config,
        metadata={"key": "kakeru-p1"},
    )
    try:
        job = client.batches.create(
            model=request["model"],
            src=[inlined],
            config=types.CreateBatchJobConfig(display_name="mt-101-probe"),
        )
    except Exception as exc:  # the create-time 400 of S11 lands here
        print(f"batches.create REJECTED (verbatim): {type(exc).__name__}: {exc}")
        job = None

    if job is not None:
        print(f"job name: {job.name}  state: {job.state.name if job.state else None}  created: {job.create_time}")
        started = time.monotonic()
        while job.state is None or job.state.name not in TERMINAL:
            time.sleep(POLL_SECONDS)
            job = client.batches.get(name=job.name)
            print(f"  {time.monotonic() - started:7.0f}s  {job.state.name if job.state else None}")
        print(f"final state: {job.state.name}  start: {job.start_time}  end: {job.end_time}")
        print(f"job.error: {job.error}")
        print(f"completion_stats: {job.completion_stats}")
        responses = (job.dest.inlined_responses if job.dest else None) or []
        print(f"inlined_responses: {len(responses)}")
        for i, item in enumerate(responses):
            print(f"-- item {i} metadata={item.metadata}")
            if item.error is not None:
                print(f"   per-request error (verbatim): {item.error}")
            if item.response is not None:
                report_usage(f"batch item {i}", item.response)

    # --- the control: the same request, interactively ------------------------
    print("\n=== control: translate_page interactively ===")
    try:
        result = translate_page(client, page, REGIONS, EMPTY_CONTEXT)
        print(f"call: {result.call}")
        print(f"usage: {result.usage}")
        print(f"interactive row: ${price(MODEL_ID, result.usage).cost}")
        print(f"lines: {result.lines}")
        print(f"proposed_terms: {result.proposed_terms}")
    except Exception as exc:
        print(f"control FAILED (verbatim): {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

**Results**

```text
PENDING — the user runs this once the account has credit (it reported
"prepayment credits are depleted" on 2026-10-28) and pastes the output here.
```

When pasted, fill in: job name, final state, turnaround (start to end time,
recorded as one observation, not a measurement - `## Out of scope`), each
field of `usage_metadata` as reported, the parsed JSON or the rejection text,
the interactive price beside the batch figure, and the control's result. If
the batch item fails where the control parses, the field the batch path
rejected is named in D-4 and the `## Decided` entry is amended with the
evidence.

## Decided

Each decision is one sentence plus its source. A later story cites them as
`MT-101 D-n`. Facts tagged **docs** rest on the pages in `## Sources`; the
one tagged **probe** is open until `## Live probe` has results.

**AC-2 - rates**

- **D-1** - Gemini 3.1 Pro Preview batch rates, prompts <= 200k tokens, as
  `Decimal` strings for the rate table: `input_per_mtok = "1.00"`,
  `output_per_mtok = "6.00"` (thinking tokens **included** - the row is
  "Output price (including thinking tokens)"), `cache_read_per_mtok = "0.20"`
  (batch caching is "Same as Standard"), `cache_write_per_mtok = "1.00"` (equal
  to input, by the same reasoning as the interactive row: implicit caching has
  no write surcharge and the adapter always reports 0 cache-write tokens).
  Source: S2 (F-1).
- **D-2** - The ratio of batch to interactive is **0.50 on input and output
  and 1.00 on cache reads**; with cache reads at zero (`translate/gemini.py`
  C-2, S3's 4,096-token minimum) a page's batch bill is exactly half its
  interactive bill, so EPIC-09 `## Why now` stands as written and needs no
  restatement. Source: S1, S2, S3 (F-1, F-7, F-13).
- **D-3** - Interactive rates are unchanged from `domain/rates.py`'s
  `2026-10-12` row ($2.00 / $12.00 / cache read $0.20, <=200k); the batch
  row is a new row, not a correction. Source: S2 (F-1).

**AC-3 - the request config in batch**

- **D-4** - Per field of the config `build_request` sends:

  | Field | Docs say | Live probe |
  |---|---|---|
  | `response_mime_type="application/json"` | accepted - S1's own batch example sets it (F-3) | pending |
  | `response_json_schema=<schema>` | accepted by the "any request configuration" rule (S1, F-3), but S1's example uses `response_schema`, not `response_json_schema`; `additionalProperties` is supported (S4, F-6) | pending |
  | `thinking_config=ThinkingConfig(thinking_level=MEDIUM)` | **NOT FOUND in the docs read** - S1's body never mentions thinking; S11 shows `InlinedRequest.config.thinking_config` working with `thinking_budget` since SDK 1.29 (F-4); `thinking_level` on 3.1 Pro in batch is unconfirmed | pending - this is the field the probe exists for |
  | `max_output_tokens=4096` | accepted by the "any request configuration" rule (S1); includes thought tokens (S5, F-5) | pending |
  | `system_instruction=SYSTEM_PROMPT` | accepted - S1 lists "system instructions" (F-3) | pending |

  Source: S1, S4, S5, S11. **For MT-110:** a config field the batch path
  refuses is refused at `client.batches.create` as a `400 INVALID_ARGUMENT`
  naming the field (S11), before anything is billed, so the adapter's
  submit step must surface that error verbatim and the story's RED must
  cover it; the per-request `.error` path (D-8) is for failures after
  acceptance.
- **D-5** - Submit inline with `client.batches.create(model=MODEL_ID,
  src=[types.InlinedRequest(contents=..., config=<GenerateContentConfig>,
  metadata={"key": <page id>}), ...], config=types.CreateBatchJobConfig(
  display_name=...))`, which returns a `BatchJob` whose `.name` is
  `batches/<id>`; the `config` on each `InlinedRequest` is the very
  `GenerateContentConfig` `build_request` returns. Source: S1, S10 (F-10).
- **D-6** - Poll with `client.batches.get(name=job.name)` and compare
  `job.state.name` against the Gemini API's six states `JOB_STATE_PENDING`,
  `JOB_STATE_RUNNING`, `JOB_STATE_SUCCEEDED`, `JOB_STATE_FAILED`,
  `JOB_STATE_CANCELLED`, `JOB_STATE_EXPIRED` (the SDK enum carries six more
  Vertex-only members, F-10); `client.batches.cancel(name=)` stops new
  requests, `client.batches.delete(name=)` removes the job, `client.batches
  .list()` pages `BatchJob`s. Source: S1, S10 (F-10). No polling interval is
  prescribed; S1's examples use 30 s.
- **D-7** - Read inline results from `job.dest.inlined_responses`, a list of
  `InlinedResponse(response: GenerateContentResponse | None, error: JobError |
  None, metadata)`; `response.usage_metadata` carries the same fields the
  adapter's `_usage_of` reads, so a batch item is priced by the unchanged
  mapping `input = P - C`, `output = K + T`, `cache_read = C`. Source: S1, S10
  (F-11, F-12). **For MT-110:** pair responses to pages by the echoed
  `metadata["key"]`, never by position, because the response order is NOT
  FOUND in S1 or S7.
- **D-8** - A per-request failure is an `InlinedResponse` with `.error =
  JobError(code, message, details)` and no `.response`; the job itself still
  reaches `JOB_STATE_SUCCEEDED`, and `job.completion_stats` (REST
  `batchStats.failedRequestCount`) counts them. Source: S1, S7, S10 (F-10,
  F-11). The exact `code` values are NOT FOUND; MT-110 treats any `.error` as
  that page failed and records the message verbatim.
- **D-9** - Inline submission is limited to 20 MB total request size, 100
  concurrent batch jobs and 5,000,000 enqueued tokens on Tier 1 (500M on Tier
  2, 1B on Tier 3) for this model; a 200-page volume at capped JPEGs (the
  fixture `kakeru-p1.png` caps to 90,619 bytes through `prepare_page_image`,
  measured 2026-10-28) is ~18 MB of image and ~24 MB once base64-encoded in
  the request body, which is **at or over the 20 MB inline limit**, so MT-110
  must either chunk a volume into several inline jobs or use file input
  (`client.files.upload` of a JSONL whose lines are `{"key", "request"}`, 2 GB
  max), and MT-111's projection must check the enqueued-token quota of the
  user's tier. Source: S1, S6 (F-9). Which the user's account tier is: NOT
  FOUND here; MT-111 asks.

**AC-4 - caching in batch**

- **D-10** - Explicit caching applies to batch requests (`cached_content` in
  a request's config) at the standard, undiscounted cache rate ($0.20 / 1M
  <=200k); whether implicit caching fires inside a batch job is NOT FOUND, and
  with every page prompt under the 4,096-token implicit minimum the batch
  estimate (MT-111) **carries no cache read** - it prices `cache_read_tokens =
  0`, and the ledger records whatever the response actually reports. Source:
  S1, S3 (F-7).

**AC-5 - turnaround**

- **D-11** - Google's target is 24 hours ("in majority of cases, it is much
  quicker"); the maximum is 48 hours, after which the job becomes
  `JOB_STATE_EXPIRED` and "will not have any results to retrieve"; nothing is
  said about the interval between 24 h and 48 h, so MT-112's waiting state
  treats `EXPIRED` as a terminal failure of every page in the job and
  everything else as still pending. Source: S1 (F-8). Whether an expired job
  bills for requests completed before expiry: NOT FOUND; MT-112 ledgers only
  responses it receives.

**AC-6 - the pricing tier**

- **D-12** - The tier threshold is **200,000 tokens, measured on the prompt**
  ("prompts <= 200k tokens" / "prompts > 200k tokens" - the output row keys
  on the same prompt size, F-2), with the >200k rates: interactive input
  $4.00, output $18.00, cache read $0.40; batch input $2.00, output $9.00,
  cache read $0.40 (as `Decimal` strings `"4.00"`, `"18.00"`, `"0.40"`,
  `"2.00"`, `"9.00"`, `"0.40"`). Source: S2 (F-1, F-2). MT-114 chunks each
  consistency-pass request so its prompt stays under 200,000 tokens; whether
  the threshold counts cached prompt tokens is NOT FOUND, so MT-114 counts the
  whole prompt.
- **D-13** - No page request of this product approaches the tier: one page is
  ~3,000 prompt tokens, so MT-102's batch row is the <=200k tier and `price`
  needs no tier selection for per-page calls; the tier matters only to
  MT-114's chunking. Source: D-12 and `translate/gemini.py` C-2. **[INFERRED]**

### For the implementing stories

The discount **is** 50% on input and output; the placeholders MT-102, MT-104,
MT-110 and MT-114 assume ($1.00 / $6.00 / $0.10) are right on the first two and
**wrong on the third**:

- **MT-102** - `cache_read_per_mtok` for the Gemini batch row is **`"0.20"`,
  not `"0.10"`** (D-1: "Same as Standard"); `cache_write_per_mtok` is `"1.00"`
  by the interactive row's rule. Input `"1.00"` and output `"6.00"` stand.
- **MT-104**, **MT-114** - any cache-read placeholder of $0.10 is $0.20; the
  rest stands. MT-114 additionally reads D-12: the threshold is on the prompt.
- **MT-110** - D-4's create-time 400 path, D-7's key-based pairing, D-9's
  20 MB inline limit (a volume does not fit inline).
- **MT-111** - D-9's enqueued-token quota by tier, D-10's zero cache read in
  the projection.
- **MT-112** - D-11's `EXPIRED` as terminal failure.
- **AC-7 / D-4's probe column** stays open until the user pastes the probe
  results; the thinking-config row is the one with no documentary answer.
