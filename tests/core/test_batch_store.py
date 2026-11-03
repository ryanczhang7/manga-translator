"""MT-103 AC-4 and MT-137 AC-3..AC-7: `mangatl.store.batch`, the record of a
submitted Batch API job.

A batch job outlives the process that submitted it: the provider holds the
requests for up to a day, and a closed app must be able to find the jobs it
left running and resume collecting (MT-111, MT-112). So the store keeps one
row per job - the provider's job name, the run that submitted it, the model,
its state and when, and (MT-137) **the consecutive run of pages it holds**,
`first_ordinal .. last_ordinal` - and answers one question for a resume:
**which jobs are still pending?**

MT-103 said "at most one pending job". MT-111 PO-1 splits a volume into
several inline jobs, so MT-137 makes it "**no two pending jobs share a
page**": `record_submission` refuses a range that overlaps a pending row,
raising `BatchPending` that names the job in the way, and writes nothing; a
disjoint range is accepted. `pending_jobs` is every pending row, in page
order. The double bill MT-103 guarded against is still impossible.

**Rows are observed with a plain `sqlite3` reader** as well as through the
store, `test_ledger.py`'s convention: a module that is uniformly wrong
round-trips through itself. `mark_collected` and `mark_failed` have no read
function of their own in the contract, so "the job reads back `collected`" is a
read of the `batch_job` row itself.

**Names MT-137 adds are imported inside the tests that use them**
(`pending_jobs`), so while one is missing it is one red test each, not a file
that fails at collection.

**Timing.** No `pytest-timeout` in this project; each test builds a six-page
chapter of tiny PNGs on `tmp_path`.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mangatl.domain.batch import BatchJob
from mangatl.store.batch import (
    BatchPending,
    mark_collected,
    mark_failed,
    record_submission,
)
from mangatl.store.intake import read_chapter
from mangatl.store.project import Project, create_project, project_dir_for

_MODEL = "gemini-3.1-pro-preview"

#: Six pages, ordinals 0..5, so every range AC-4 and AC-5 name lies inside the
#: chapter. The store does not check a range against the page count (no
#: criterion asks it to); this only keeps the fixtures honest.
_PAGES = ("p1.png", "p2.png", "p3.png", "p4.png", "p5.png", "p6.png")


def _raw(db_path: Path, sql: str, parameters: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(db_path)
    try:
        with connection:
            return list(connection.execute(sql, parameters))
    finally:
        connection.close()


def _job_row(db_path: Path, job_id: int) -> tuple[object, ...]:
    """(run_id, provider_job_id, model_id, state, submitted_at, collected_at,
    failure, first_ordinal, last_ordinal) for one job, read without
    `mangatl.store`."""
    rows = _raw(
        db_path,
        "SELECT run_id, provider_job_id, model_id, state, submitted_at, collected_at, failure,"
        " first_ordinal, last_ordinal FROM batch_job WHERE id = ?",
        (job_id,),
    )
    assert len(rows) == 1, f"job {job_id}: {rows}"
    return rows[0]


def _count(db_path: Path) -> int:
    return int(str(_raw(db_path, "SELECT COUNT(*) FROM batch_job")[0][0]))


def _utc(stamp: object) -> datetime:
    """Parse an ISO-8601 instant and insist it is aware and UTC."""
    assert isinstance(stamp, str), stamp
    parsed = datetime.fromisoformat(stamp)
    assert parsed.utcoffset() == UTC.utcoffset(None), f"{stamp} is not a UTC instant"
    return parsed


def _number(value: int) -> re.Pattern[str]:
    """`value` as a whole number: `7` does not match inside `17` or `70`, and
    `1` does not match inside `-1`."""
    return re.compile(rf"(?<![\d-]){re.escape(str(value))}(?!\d)")


@pytest.fixture
def source_dir(tmp_path: Path, png_bytes: Callable[..., bytes]) -> Path:
    folder = tmp_path / "chapter"
    folder.mkdir()
    for name in _PAGES:
        (folder / name).write_bytes(png_bytes(8, 6))
    return folder


@pytest.fixture
def project(source_dir: Path) -> Iterator[Project]:
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as opened:
        yield opened


@pytest.fixture
def db_path(source_dir: Path) -> Path:
    return project_dir_for(source_dir) / "project.db"


@pytest.fixture
def run_id(project: Project) -> int:
    with project.transaction() as cursor:
        chapter_id = cursor.execute("SELECT id FROM chapter").fetchone()[0]
        cursor.execute(
            "INSERT INTO run (chapter_id, started_at) VALUES (?, ?)",
            (chapter_id, "2026-10-31T09:00:00+00:00"),
        )
        return int(cursor.lastrowid or 0)


# -- the module's surface (MT-137 AC-7) ----------------------------------------------


def test_the_store_exports_pending_jobs_and_no_longer_exports_pending_job() -> None:
    """**MT-137 AC-7**: `__all__` is exactly the five names, in this order, and
    the one-or-none `pending_job` is gone from the module, not merely from
    `__all__` - a resume that still called it would see one job of three."""
    import mangatl.store.batch as batch

    assert batch.__all__ == [
        "BatchPending",
        "mark_collected",
        "mark_failed",
        "pending_jobs",
        "record_submission",
    ]
    assert not hasattr(batch, "pending_job"), "store.batch still defines pending_job"
    assert callable(getattr(batch, "pending_jobs", None)), "store.batch has no pending_jobs"


# -- the value (MT-137 AC-3) ---------------------------------------------------------


@pytest.mark.parametrize(
    ("first", "last", "expected"),
    [(0, 0, range(0, 1)), (2, 4, range(2, 5)), (0, 199, range(0, 200))],
    ids=["one-page-at-zero", "three-pages", "a-whole-volume"],
)
def test_a_batch_jobs_ordinals_are_the_inclusive_range_of_its_pages(
    first: int, last: int, expected: range
) -> None:
    """**MT-137 AC-3**: `BatchJob.ordinals` is `range(first_ordinal,
    last_ordinal + 1)` - a `range`, inclusive of the last page, so a one-page
    job holds exactly one page and not none."""
    job = BatchJob(
        id=1,
        run_id=1,
        provider_job_id="batches/abc",
        model_id=_MODEL,
        state="submitted",
        submitted_at="2026-11-03T09:00:00+00:00",
        collected_at=None,
        failure=None,
        first_ordinal=first,
        last_ordinal=last,
    )

    assert isinstance(job.ordinals, range), type(job.ordinals)
    assert job.ordinals == expected
    assert (job.first_ordinal, job.last_ordinal) == (first, last)


# -- submission ----------------------------------------------------------------------


def test_a_project_with_no_jobs_has_nothing_pending(project: Project) -> None:
    """**MT-137 AC-4** (MT-103's empty case, re-pointed): an empty tuple, not
    `None` and not an exception - a resume asks this of every project, and
    almost every project has never submitted a batch."""
    from mangatl.store.batch import pending_jobs

    assert pending_jobs(project) == ()
    assert isinstance(pending_jobs(project), tuple)


def test_recording_a_submission_returns_the_id_of_the_row_it_wrote(
    project: Project, db_path: Path, run_id: int
) -> None:
    """**MT-103 AC-4, MT-137 AC-3**: `record_submission` returns a job id, and
    it is the id of a `batch_job` row carrying the run, the provider's job
    name, the model, state `submitted`, no `collected_at`, no failure - and the
    two ordinals it was given."""
    job_id = record_submission(project, run_id, "batches/abc", _MODEL, 2, 4)

    assert isinstance(job_id, int)
    row = _job_row(db_path, job_id)
    assert row[:4] == (run_id, "batches/abc", _MODEL, "submitted")
    assert row[5:] == (None, None, 2, 4)


def test_a_submission_is_stamped_with_the_utc_time_it_was_recorded(
    project: Project, db_path: Path, run_id: int
) -> None:
    before = datetime.now(UTC)
    job_id = record_submission(project, run_id, "batches/abc", _MODEL, 0, 5)
    after = datetime.now(UTC)

    assert before <= _utc(_job_row(db_path, job_id)[4]) <= after


def test_the_submitted_job_is_the_pending_one_with_both_ordinals(
    project: Project, db_path: Path, run_id: int
) -> None:
    """**MT-103 AC-4, MT-137 AC-3**: `pending_jobs` reads the job back as the
    one `BatchJob` in a tuple, state `"submitted"`, every field the row's -
    both ordinals included - and its `ordinals` are the pages it was given."""
    from mangatl.store.batch import pending_jobs

    job_id = record_submission(project, run_id, "batches/abc", _MODEL, 2, 4)
    submitted_at = _job_row(db_path, job_id)[4]

    pending = pending_jobs(project)
    assert pending == (
        BatchJob(
            id=job_id,
            run_id=run_id,
            provider_job_id="batches/abc",
            model_id=_MODEL,
            state="submitted",
            submitted_at=str(submitted_at),
            collected_at=None,
            failure=None,
            first_ordinal=2,
            last_ordinal=4,
        ),
    )
    assert pending[0].ordinals == range(2, 5)


# -- several pending, disjoint (MT-137 AC-4) -----------------------------------------


def test_two_submissions_with_disjoint_ranges_are_both_recorded_and_both_pending(
    project: Project, db_path: Path, run_id: int
) -> None:
    """**MT-137 AC-4**: `0..1` then `2..2` - adjacent, sharing no page - both
    succeed and both are pending. A store that kept MT-103's "any pending job
    refuses" fails the second call; one that compared `<` where it means `<=`
    (treating touching ranges as overlapping) fails it too."""
    from mangatl.store.batch import pending_jobs

    first = record_submission(project, run_id, "batches/a", _MODEL, 0, 1)
    second = record_submission(project, run_id, "batches/b", _MODEL, 2, 2)

    assert first != second
    assert _count(db_path) == 2
    assert [(job.id, job.provider_job_id, job.first_ordinal, job.last_ordinal)
            for job in pending_jobs(project)] == [
        (first, "batches/a", 0, 1),
        (second, "batches/b", 2, 2),
    ]  # fmt: skip


def test_pending_jobs_are_in_page_order_whatever_order_they_were_submitted_in(
    project: Project, run_id: int
) -> None:
    """**MT-137 AC-4**: ordered by `first_ordinal`, not by id. Submitted
    `4..5`, then `0..1`, then `2..3`, they read back `0..1, 2..3, 4..5` - so
    `ORDER BY id` (the insertion order) fails, and so does no ORDER BY."""
    from mangatl.store.batch import pending_jobs

    late = record_submission(project, run_id, "batches/late", _MODEL, 4, 5)
    early = record_submission(project, run_id, "batches/early", _MODEL, 0, 1)
    middle = record_submission(project, run_id, "batches/middle", _MODEL, 2, 3)

    assert [(job.id, job.first_ordinal) for job in pending_jobs(project)] == [
        (early, 0),
        (middle, 2),
        (late, 4),
    ]


def test_pending_jobs_leaves_out_every_settled_job(project: Project, run_id: int) -> None:
    """**MT-137 AC-4**: "every pending row" - a collected job and a failed job
    over other pages are not pending, and the one submitted job between them
    is the whole answer."""
    from mangatl.store.batch import pending_jobs

    collected = record_submission(project, run_id, "batches/collected", _MODEL, 0, 1)
    mark_collected(project, collected)
    pending = record_submission(project, run_id, "batches/pending", _MODEL, 2, 3)
    failed = record_submission(project, run_id, "batches/failed", _MODEL, 4, 5)
    mark_failed(project, failed, "boom")

    assert [job.id for job in pending_jobs(project)] == [pending]


# -- collection and failure ----------------------------------------------------------


def test_a_collected_job_is_no_longer_pending_and_reads_back_collected(
    project: Project, db_path: Path, run_id: int
) -> None:
    """**MT-103 AC-4**: after `mark_collected`, nothing is pending and the row
    reads `"collected"` with a UTC `collected_at` of now, no failure, and its
    ordinals untouched."""
    from mangatl.store.batch import pending_jobs

    job_id = record_submission(project, run_id, "batches/abc", _MODEL, 0, 5)

    before = datetime.now(UTC)
    mark_collected(project, job_id)
    after = datetime.now(UTC)

    assert pending_jobs(project) == ()
    row = _job_row(db_path, job_id)
    assert row[:4] == (run_id, "batches/abc", _MODEL, "collected")
    assert before <= _utc(row[5]) <= after
    assert row[6:] == (None, 0, 5)


def test_a_failed_job_is_no_longer_pending_and_reads_back_failed_with_its_reason(
    project: Project, db_path: Path, run_id: int
) -> None:
    """**MT-103 AC-4**: after `mark_failed(..., reason)` the row reads
    `"failed"` with that reason verbatim, and nothing is pending."""
    from mangatl.store.batch import pending_jobs

    job_id = record_submission(project, run_id, "batches/abc", _MODEL, 0, 5)

    mark_failed(project, job_id, "JOB_STATE_EXPIRED: not collected within 48h")

    assert pending_jobs(project) == ()
    row = _job_row(db_path, job_id)
    assert row[:4] == (run_id, "batches/abc", _MODEL, "failed")
    assert row[6:] == ("JOB_STATE_EXPIRED: not collected within 48h", 0, 5)


def test_marking_one_job_leaves_another_jobs_row_alone(
    project: Project, db_path: Path, run_id: int
) -> None:
    """**MT-137 AC-7** (MT-103's test, re-pointed): a `mark_*` with no `WHERE
    id` would pass every test above that holds one row. Three jobs over
    disjoint pages, all submitted before any is settled - which MT-137 now
    allows - then fail A, collect B, fail C. A `mark_collected` that touched
    every row turns A `collected`; a `mark_failed` that did turns B `failed`.
    Each row reads (state, has collected_at, failure)."""
    a = record_submission(project, run_id, "batches/a", _MODEL, 0, 1)
    b = record_submission(project, run_id, "batches/b", _MODEL, 2, 3)
    c = record_submission(project, run_id, "batches/c", _MODEL, 4, 5)
    mark_failed(project, a, "boom")
    mark_collected(project, b)
    mark_failed(project, c, "late")

    def settled(job_id: int) -> tuple[object, bool, object]:
        row = _job_row(db_path, job_id)
        return row[3], row[5] is not None, row[6]

    assert len({a, b, c}) == 3
    assert [settled(job_id) for job_id in (a, b, c)] == [
        ("failed", False, "boom"),
        ("collected", True, None),
        ("failed", False, "late"),
    ]


def test_marking_one_of_two_pending_jobs_leaves_the_other_pending(
    project: Project, db_path: Path, run_id: int
) -> None:
    """**MT-137 AC-7**: with two jobs in flight at once, settling one leaves
    the other `submitted` and the only pending job - the case MT-103 could not
    have, because it never held two pending rows."""
    from mangatl.store.batch import pending_jobs

    a = record_submission(project, run_id, "batches/a", _MODEL, 0, 2)
    b = record_submission(project, run_id, "batches/b", _MODEL, 3, 5)

    mark_collected(project, a)
    assert [job.id for job in pending_jobs(project)] == [b]
    still = _job_row(db_path, b)
    assert (still[3], still[5], still[6]) == ("submitted", None, None)

    mark_failed(project, b, "reason")
    assert pending_jobs(project) == ()
    assert _job_row(db_path, a)[3] == "collected"


# -- no two pending jobs share a page (MT-137 AC-5) ----------------------------------

#: (pending range, refused range): AC-5's three cases - an overlap at one
#: end, an overlap at the other, a range that encloses the pending one - and
#: the identical range, MT-103's original double bill.
_OVERLAPS = [
    ((0, 1), (1, 1)),
    ((0, 2), (2, 3)),
    ((2, 2), (0, 5)),
    ((2, 3), (2, 3)),
]
_OVERLAP_IDS = ["shares-its-last-page", "starts-on-its-last-page", "encloses-it", "identical"]

#: How many settled jobs are recorded before the pending one, so the pending
#: job's id is 7 - a number no page in `_OVERLAPS` can be, so a message that
#: names only pages cannot satisfy the id needle.
_BURNED = 6


def _pending_with_id_seven(project: Project, run_id: int, first: int, last: int) -> int:
    for n in range(_BURNED):
        burned = record_submission(project, run_id, f"batches/burned-{n}", _MODEL, 0, 5)
        mark_failed(project, burned, "burned")
    pending = record_submission(project, run_id, "batches/abc", _MODEL, first, last)
    assert pending == _BURNED + 1, pending
    return pending


@pytest.mark.parametrize(("held", "wanted"), _OVERLAPS, ids=_OVERLAP_IDS)
def test_a_submission_sharing_any_page_with_a_pending_job_is_refused_naming_that_job(
    project: Project,
    db_path: Path,
    run_id: int,
    held: tuple[int, int],
    wanted: tuple[int, int],
) -> None:
    """**MT-137 AC-5**: `BatchPending`, whose message names the pending job by
    its id (7) **and** its provider id (`batches/abc`) - not the job being
    refused - and no row is written: the count is what it was, `batches/def`
    is nowhere, and the pending job is still the only pending one."""
    from mangatl.store.batch import pending_jobs

    pending = _pending_with_id_seven(project, run_id, *held)
    assert pending not in {*range(held[0], held[1] + 1), *range(wanted[0], wanted[1] + 1)}
    rows_before = _count(db_path)

    with pytest.raises(BatchPending) as excinfo:
        record_submission(project, run_id, "batches/def", _MODEL, *wanted)

    message = str(excinfo.value)
    assert _number(pending).search(message), f"the message does not name job {pending}: {message}"
    assert re.search(r"(?<![\w/])batches/abc(?![\w/])", message), message
    assert _count(db_path) == rows_before
    assert _raw(
        db_path, "SELECT COUNT(*) FROM batch_job WHERE provider_job_id = 'batches/def'"
    ) == [(0,)]
    assert [job.id for job in pending_jobs(project)] == [pending]


@pytest.mark.parametrize("settle", ["collected", "failed"])
@pytest.mark.parametrize(("held", "wanted"), _OVERLAPS, ids=_OVERLAP_IDS)
def test_the_same_range_is_accepted_once_the_pending_job_settles(
    project: Project,
    run_id: int,
    settle: str,
    held: tuple[int, int],
    wanted: tuple[int, int],
) -> None:
    """**MT-137 AC-5**, second half, and the negative control for the refusal
    above: a store that refused every overlapping range, pending or not, would
    pass it. Once the job in the way is collected - or failed - the same range
    is recorded and is the one pending job."""
    from mangatl.store.batch import pending_jobs

    first = record_submission(project, run_id, "batches/abc", _MODEL, *held)
    if settle == "collected":
        mark_collected(project, first)
    else:
        mark_failed(project, first, "reason")

    second = record_submission(project, run_id, "batches/def", _MODEL, *wanted)

    assert [
        (job.id, job.provider_job_id, job.state, job.first_ordinal, job.last_ordinal)
        for job in pending_jobs(project)
    ] == [(second, "batches/def", "submitted", *wanted)]


# -- an impossible range (MT-137 AC-6) -----------------------------------------------


@pytest.mark.parametrize(
    ("first", "last"),
    [(3, 2), (1, 0), (-1, 3), (-1, 0), (-2, -5)],
    ids=["first-past-last", "one-past", "negative-first", "negative-first-at-zero", "both-wrong"],
)
def test_an_impossible_range_is_a_value_error_naming_both_numbers_and_writes_nothing(
    project: Project, db_path: Path, run_id: int, first: int, last: int
) -> None:
    """**MT-137 AC-6**: `first_ordinal > last_ordinal` or `first_ordinal < 0`
    raises `ValueError` before any write - a `ValueError` raised by the store,
    not the CHECK's `sqlite3.IntegrityError` - whose message carries both
    numbers as whole numbers. No row is written."""
    with pytest.raises(ValueError) as excinfo:
        record_submission(project, run_id, "batches/abc", _MODEL, first, last)

    assert not isinstance(excinfo.value, sqlite3.Error), type(excinfo.value)
    message = str(excinfo.value)
    assert re.search(rf"(?<![\d-]){first}(?!\d)", message), f"{first} not in: {message}"
    assert re.search(rf"(?<![\d-]){last}(?!\d)", message), f"{last} not in: {message}"
    assert _count(db_path) == 0


def test_an_impossible_range_is_refused_as_a_value_error_even_while_a_job_is_pending(
    project: Project, db_path: Path, run_id: int
) -> None:
    """**MT-137 AC-6**, "before any write" and `## Contract`'s "before the
    transaction": `5..4` against a pending `0..5` would also satisfy the
    overlap predicate, so a store that validated inside the transaction, after
    the overlap check, raises `BatchPending` here instead of `ValueError`."""
    record_submission(project, run_id, "batches/abc", _MODEL, 0, 5)

    with pytest.raises(ValueError) as excinfo:
        record_submission(project, run_id, "batches/def", _MODEL, 5, 4)

    assert not isinstance(excinfo.value, BatchPending)
    assert _count(db_path) == 1


def test_the_boundary_ranges_an_impossible_range_neighbours_are_accepted(
    project: Project, db_path: Path, run_id: int
) -> None:
    """The **negative control** for AC-6: a guard written `first >= last` or
    `first <= 0` refuses a one-page job, or any job starting at page 0. `0..0`
    and `5..5` - a one-page job at each end of the chapter - are recorded."""
    zero = record_submission(project, run_id, "batches/zero", _MODEL, 0, 0)
    five = record_submission(project, run_id, "batches/five", _MODEL, 5, 5)

    assert _job_row(db_path, zero)[7:] == (0, 0)
    assert _job_row(db_path, five)[7:] == (5, 5)
