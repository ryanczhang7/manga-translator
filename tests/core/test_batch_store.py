"""MT-103 AC-4: `mangatl.store.batch`, the record of a submitted Batch API job.

A batch job outlives the process that submitted it: the provider holds the
requests for up to a day, and a closed app must be able to find the job it
left running and resume collecting (MT-111, MT-112). So the store keeps one
row per job - the provider's job name, the run that submitted it, the model,
its state and when - and answers one question for a resume: **which job is
still pending?**

`pending_job` is "the one row with state `submitted`" (`## Contract`,
Semantics), and "at most one" is not a hope but a refusal: a second
`record_submission` while one is pending raises `BatchPending`, naming the job
that is in the way, and writes nothing. Two pending jobs would make "which one
does a resume collect?" unanswerable.

**Rows are observed with a plain `sqlite3` reader** as well as through the
store, `test_ledger.py`'s convention: a module that is uniformly wrong
round-trips through itself. `mark_collected` and `mark_failed` have no read
function of their own in the contract, so "the job reads back `collected`" is a
read of the `batch_job` row itself.

**Timing.** No `pytest-timeout` in this project; each test builds a two-page
chapter on `tmp_path`.
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
    pending_job,
    record_submission,
)
from mangatl.store.intake import read_chapter
from mangatl.store.project import Project, create_project, project_dir_for

_MODEL = "gemini-3.1-pro-preview"


def _raw(db_path: Path, sql: str, parameters: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(db_path)
    try:
        with connection:
            return list(connection.execute(sql, parameters))
    finally:
        connection.close()


def _job_row(db_path: Path, job_id: int) -> tuple[object, ...]:
    """(run_id, provider_job_id, model_id, state, submitted_at, collected_at,
    failure) for one job, read without `mangatl.store`."""
    rows = _raw(
        db_path,
        "SELECT run_id, provider_job_id, model_id, state, submitted_at, collected_at, failure"
        " FROM batch_job WHERE id = ?",
        (job_id,),
    )
    assert len(rows) == 1, f"job {job_id}: {rows}"
    return rows[0]


def _utc(stamp: object) -> datetime:
    """Parse an ISO-8601 instant and insist it is aware and UTC."""
    assert isinstance(stamp, str), stamp
    parsed = datetime.fromisoformat(stamp)
    assert parsed.utcoffset() == UTC.utcoffset(None), f"{stamp} is not a UTC instant"
    return parsed


@pytest.fixture
def source_dir(tmp_path: Path, png_bytes: Callable[..., bytes]) -> Path:
    folder = tmp_path / "chapter"
    folder.mkdir()
    for name in ("p1.png", "p2.png"):
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


# -- submission ----------------------------------------------------------------------


def test_a_project_with_no_jobs_has_nothing_pending(project: Project) -> None:
    """The empty case: `None`, not an exception - a resume asks this of every
    project, and almost every project has never submitted a batch."""
    assert pending_job(project) is None


def test_recording_a_submission_returns_the_id_of_the_row_it_wrote(
    project: Project, db_path: Path, run_id: int
) -> None:
    """**AC-4**: `record_submission` returns a job id, and it is the id of a
    `batch_job` row carrying the run, the provider's job name, the model and
    state `submitted`, with no `collected_at` and no failure."""
    job_id = record_submission(project, run_id, "batches/abc", _MODEL)

    assert isinstance(job_id, int)
    assert _job_row(db_path, job_id)[:4] == (run_id, "batches/abc", _MODEL, "submitted")
    assert _job_row(db_path, job_id)[5:] == (None, None)


def test_a_submission_is_stamped_with_the_utc_time_it_was_recorded(
    project: Project, db_path: Path, run_id: int
) -> None:
    before = datetime.now(UTC)
    job_id = record_submission(project, run_id, "batches/abc", _MODEL)
    after = datetime.now(UTC)

    assert before <= _utc(_job_row(db_path, job_id)[4]) <= after


def test_the_submitted_job_is_the_pending_one(project: Project, db_path: Path, run_id: int) -> None:
    """**AC-4**: `pending_job` returns that job, as a `BatchJob`, state
    `"submitted"`, every field the row's."""
    job_id = record_submission(project, run_id, "batches/abc", _MODEL)
    submitted_at = _job_row(db_path, job_id)[4]

    assert pending_job(project) == BatchJob(
        id=job_id,
        run_id=run_id,
        provider_job_id="batches/abc",
        model_id=_MODEL,
        state="submitted",
        submitted_at=str(submitted_at),
        collected_at=None,
        failure=None,
    )


# -- collection and failure ----------------------------------------------------------


def test_a_collected_job_is_no_longer_pending_and_reads_back_collected(
    project: Project, db_path: Path, run_id: int
) -> None:
    """**AC-4**: after `mark_collected`, `pending_job` is `None` and the row
    reads `"collected"` with a UTC `collected_at` of now, and no failure."""
    job_id = record_submission(project, run_id, "batches/abc", _MODEL)

    before = datetime.now(UTC)
    mark_collected(project, job_id)
    after = datetime.now(UTC)

    assert pending_job(project) is None
    row = _job_row(db_path, job_id)
    assert row[:4] == (run_id, "batches/abc", _MODEL, "collected")
    assert before <= _utc(row[5]) <= after
    assert row[6] is None


def test_a_failed_job_is_no_longer_pending_and_reads_back_failed_with_its_reason(
    project: Project, db_path: Path, run_id: int
) -> None:
    """**AC-4**: after `mark_failed(..., reason)` the row reads `"failed"`
    with that reason verbatim, and nothing is pending."""
    job_id = record_submission(project, run_id, "batches/abc", _MODEL)

    mark_failed(project, job_id, "JOB_STATE_EXPIRED: not collected within 48h")

    assert pending_job(project) is None
    row = _job_row(db_path, job_id)
    assert row[:4] == (run_id, "batches/abc", _MODEL, "failed")
    assert row[6] == "JOB_STATE_EXPIRED: not collected within 48h"


def test_marking_one_job_leaves_another_jobs_row_alone(
    project: Project, db_path: Path, run_id: int
) -> None:
    """A `mark_*` with no `WHERE id` would pass every test above, which only
    ever hold one row. Three jobs, each settled while the earlier ones exist:
    fail A, collect B, fail C. A `mark_collected` that touched every row turns
    A `collected`; a `mark_failed` that did turns B `failed`. Each row reads
    (state, has collected_at, failure)."""
    a = record_submission(project, run_id, "batches/a", _MODEL)
    mark_failed(project, a, "boom")
    b = record_submission(project, run_id, "batches/b", _MODEL)
    mark_collected(project, b)
    c = record_submission(project, run_id, "batches/c", _MODEL)
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


# -- at most one pending -------------------------------------------------------------


def test_a_second_submission_while_one_is_pending_is_refused_naming_the_pending_job(
    project: Project, db_path: Path, run_id: int
) -> None:
    """**AC-4**: `BatchPending`, and its message names the job in the way -
    `batches/abc`, not the one being refused - and nothing is written."""
    record_submission(project, run_id, "batches/abc", _MODEL)

    with pytest.raises(BatchPending) as excinfo:
        record_submission(project, run_id, "batches/def", _MODEL)

    assert re.search(r"(?<![\w/])batches/abc(?![\w/])", str(excinfo.value)), str(excinfo.value)
    assert _raw(db_path, "SELECT provider_job_id FROM batch_job") == [("batches/abc",)]
    pending = pending_job(project)
    assert pending is not None
    assert pending.provider_job_id == "batches/abc"


@pytest.mark.parametrize("settle", ["collected", "failed"])
def test_a_submission_after_the_pending_job_settles_is_accepted(
    project: Project, run_id: int, settle: str
) -> None:
    """The negative control for the refusal above: a store that refused every
    second submission, ever, would pass it. Once the pending job is collected
    or failed, the next one is recorded and becomes the pending one."""
    first = record_submission(project, run_id, "batches/abc", _MODEL)
    if settle == "collected":
        mark_collected(project, first)
    else:
        mark_failed(project, first, "reason")

    second = record_submission(project, run_id, "batches/def", _MODEL)

    pending = pending_job(project)
    assert pending is not None
    assert (pending.id, pending.provider_job_id, pending.state) == (
        second,
        "batches/def",
        "submitted",
    )
