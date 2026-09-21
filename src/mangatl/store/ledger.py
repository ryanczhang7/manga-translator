"""The cost ledger: one row per API call, and the totals read back off it.

MT-012. `domain/rates.py` prices a call; this module writes it down and adds it
up. Together they are the brief's feature 8 - "show what the run cost, per
chapter and running, so the $2/chapter constraint is observable rather than
assumed".

**Append-only is a property of the schema, not of this module** (AC-4). There is
no `update_call` here and there never should be, but that is not what makes the
ledger append-only: `schema.LLM_CALL_DDL`'s two triggers are, and they survive
the next agent to open this file with a good idea. A run's spend cannot be
quietly rewritten, and "quietly" includes rewriting it to nothing.

**Integer micro-dollars on disk** (PO-2). `cost_micro_usd` is an INTEGER and
the totals below are SQL `SUM()` over integers, which is exact. The old
`cost_usd REAL` was an IEEE-754 double and a chapter total of $0.27928 is not a
dyadic rational, so AC-3's "no floating-point drift" holds by construction
rather than by tolerance. `Usd.micro()` is the only bridge across, in both
directions.

**`record_call` takes a page *ordinal* and resolves it** (RED-A4). The ordinal
is the page's identity for the whole product (MT-004) and is what a caller in
`pipeline` has; `llm_call.page_id` is a foreign key to `page.id`. Storing one
where the other belongs agrees with itself on any chapter whose first page id
happens to be 0 and points at the wrong page everywhere else.

**`at` is stamped here** and is not a parameter: `llm_call.at` is NOT NULL, and
an aware ISO-8601 instant is the shape `create_project` and `pipeline/runner.py`
already write. A naive local timestamp in a ledger cannot be ordered against one
from another machine.
"""

from __future__ import annotations

from datetime import UTC, datetime

from mangatl.domain.money import Usd
from mangatl.domain.rates import CostRecord
from mangatl.store.project import Project

__all__ = ["chapter_total", "record_call", "run_total"]

#: Both cache counts are named in the column list, write before read, matching
#: `CostRecord`'s field order and `llm_call`'s columns - the one order in which
#: the factor-of-12.5 swap `domain/translation.py` warns about cannot happen.
#: `rate_table_version` is supplied explicitly: the column's `DEFAULT ''` exists
#: for rows that genuinely do not know, and a freshly priced call knows.
_INSERT_CALL = (
    "INSERT INTO llm_call (run_id, page_id, request_id, model_id, input_tokens,"
    " output_tokens, cache_write_tokens, cache_read_tokens, cost_micro_usd,"
    " rate_table_version, at)"
    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)

_SELECT_PAGE_ID = "SELECT id FROM page WHERE ordinal = ?"

#: `COALESCE`, because `SUM()` over no rows is SQL NULL rather than 0: a chapter
#: that has not called the model has spent nothing, and that is a `Usd` of zero
#: and not a `None` for the caller to trip over.
_SELECT_TOTAL = "SELECT COALESCE(SUM(cost_micro_usd), 0) FROM llm_call"

#: AC-6's whole point is what this statement does **not** say. `chapter_total`
#: has no `WHERE run_id`: a resume is a second `run` row against one chapter
#: (`schema.py`: "runs are events"), and the $2 ceiling is a question about the
#: chapter, so filtering to the current run would under-report every resumed
#: chapter by exactly the amount already spent on it.
_SELECT_RUN_TOTAL = f"{_SELECT_TOTAL} WHERE run_id = ?"


def record_call(
    project: Project,
    run_id: int,
    ordinal: int,
    request_id: str,
    record: CostRecord,
) -> None:
    """Append one priced call to the ledger, against a run and a page ordinal.

    The cost is stored as `record.cost.micro()` - a whole number of
    micro-dollars - and the rate table that priced it travels with it, because
    a ledger that cannot say which table priced a call cannot be reconciled
    against the provider's bill.

    Nothing here is idempotent and nothing deduplicates: the same page retried
    with the same model and the same counts is a **second bill**, not a
    duplicate row, and `llm_call` carries no UNIQUE key for that reason.
    """
    with project.transaction() as cursor:
        page_id = cursor.execute(_SELECT_PAGE_ID, (ordinal,)).fetchone()[0]
        cursor.execute(
            _INSERT_CALL,
            (
                run_id,
                page_id,
                request_id,
                record.model_id,
                record.input_tokens,
                record.output_tokens,
                record.cache_write_tokens,
                record.cache_read_tokens,
                record.cost.micro(),
                record.rate_table_version,
                datetime.now(UTC).isoformat(),
            ),
        )


def chapter_total(project: Project) -> Usd:
    """What this chapter has spent, across **every** run of it (AC-6).

    One project file is one chapter, so every ledger row in it belongs to that
    chapter; the sum is deliberately unqualified.
    """
    with project.transaction() as cursor:
        return Usd.from_micro(int(cursor.execute(_SELECT_TOTAL).fetchone()[0]))


def run_total(project: Project, run_id: int) -> Usd:
    """What one run of this chapter spent. The per-run view, not the budget."""
    with project.transaction() as cursor:
        return Usd.from_micro(int(cursor.execute(_SELECT_RUN_TOTAL, (run_id,)).fetchone()[0]))
