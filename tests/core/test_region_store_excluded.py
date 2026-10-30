"""`region.excluded` through the store: written, read back, set and cleared
(MT-118 AC-2, AC-3; C-2, C-3).

**Three conventions inherited from MT-005, MT-007 and MT-008, each measured
there:**

- the stored value is observed through a plain `sqlite3` connection, never
  through `Project` - "a codec that is uniformly wrong round-trips through
  itself perfectly" (`tdd-cycle`);
- the round trip is asserted against a project reopened from its path, with the
  writing object closed first;
- `write_regions` upserts, and its `DO UPDATE SET` carries every column - so a
  re-detection overwrites an exclusion exactly as it overwrites a `kind`. That
  is EPIC-10's "Deliberately not" and this story's `## Context`, and it is
  pinned here rather than left to be discovered (`## Out of scope`).

**`set_excluded` touches the one column** of `region` (MT-118 C-3), and no
`line` row: the "unchanged" assertions below therefore compare whole raw rows,
not a field or two. Its effect on `cleaned_page` is MT-119's and has its own
section at the end of this file (MT-119 AC-5): only a restore of a region the
stored image never erased deletes that page's image. The MT-118 tests here seed
no cleaned image, so that rule never fires in them.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from mangatl.domain.line import OcrResult
from mangatl.domain.region import RawRegion
from mangatl.store.intake import read_chapter
from mangatl.store.project import Project, create_project, open_project, project_dir_for

_PAGE_W, _PAGE_H = 320, 240

#: The page the store calls run against, and it is **not ordinal 0** (MT-035
#: DV-3): `read_regions(0)` in place of the ordinal handed in is one token.
_ORDINAL = 1

_LINES: tuple[OcrResult, ...] = (
    OcrResult(text="一つ目"),
    OcrResult(text="二つ目"),
    OcrResult(text="", ocr_empty=True),
)


@pytest.fixture
def source_dir(tmp_path: Path, png_bytes: Callable[..., bytes]) -> Path:
    """A two-page chapter, so a write to one page can be shown not to touch the other."""
    folder = tmp_path / "chapter"
    folder.mkdir()
    for name in ("p1.png", "p2.png"):
        (folder / name).write_bytes(png_bytes(_PAGE_W, _PAGE_H))
    return folder


@pytest.fixture
def project(source_dir: Path) -> Iterator[Project]:
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as opened:
        yield opened


def _db(source_dir: Path) -> Path:
    return project_dir_for(source_dir) / "project.db"


def _raw(db_path: Path, sql: str, parameters: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(db_path)
    try:
        return list(connection.execute(sql, parameters))
    finally:
        connection.close()


def _excluded_column(db_path: Path, ordinal: int) -> list[object]:
    """`SELECT excluded FROM region` for one page, in reading order, read by a
    reader that imports nothing from `mangatl.store`."""
    rows = _raw(
        db_path,
        "SELECT region.excluded FROM region JOIN page ON page.id = region.page_id"
        " WHERE page.ordinal = ? ORDER BY region.reading_index",
        (ordinal,),
    )
    return [row[0] for row in rows]


def _every_region_row(db_path: Path) -> list[tuple[object, ...]]:
    return _raw(db_path, "SELECT * FROM region ORDER BY id")


def _every_line_row(db_path: Path) -> list[tuple[object, ...]]:
    return _raw(db_path, "SELECT * FROM line ORDER BY id")


def _region(
    one_bit_png: Callable[..., bytes],
    rect: tuple[int, int, int, int],
    confidence: float,
    kind: str,
    **extra: object,
) -> RawRegion:
    x0, y0, x1, y1 = rect
    return RawRegion(
        polygon=((x0, y0), (x1 - 1, y0), (x1 - 1, y1 - 1), (x0, y1 - 1), (x0, y0)),
        mask=one_bit_png(_PAGE_W, _PAGE_H, [rect]),
        confidence=confidence,
        kind=kind,  # type: ignore[arg-type]
        **extra,  # type: ignore[arg-type]
    )


def _three(one_bit_png: Callable[..., bytes], **second: object) -> tuple[RawRegion, ...]:
    """Three regions with distinct masks, confidences and kinds; `second` goes
    to the middle one only, so a column filled once rather than per row shows."""
    return (
        _region(one_bit_png, (10, 10, 60, 40), 0.81, "bubble"),
        _region(one_bit_png, (100, 50, 180, 120), 0.42, "box", merged_from=(0, 2), **second),
        _region(one_bit_png, (200, 150, 300, 220), 1.0, "bubble"),
    )


def _seed(project: Project, regions: tuple[RawRegion, ...]) -> None:
    """Regions and their lines on `_ORDINAL`, and the same regions with no
    lines on page 0 - the bystander page every `set_excluded` call must leave
    alone."""
    project.write_regions(_ORDINAL, regions)
    project.write_lines(_ORDINAL, _LINES)
    project.write_regions(0, regions)


# -- AC-2: written and read back ----------------------------------------------------


def test_an_excluded_region_reads_back_excluded_from_a_reopened_project(
    source_dir: Path, one_bit_png: Callable[..., bytes]
) -> None:
    """AC-2, through the store: the second region `"watermark"`, the others
    `None`. Equality covers every field, and the field this story added is
    asserted on its own as well, because equality would not say which field
    was lost."""
    regions = _three(one_bit_png, excluded="watermark")
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as writer:
        writer.write_regions(_ORDINAL, regions)

    with open_project(project_dir_for(source_dir)) as reopened:
        read_back = reopened.read_regions(_ORDINAL)

    assert [region.excluded for region in read_back] == [None, "watermark", None]
    assert read_back == regions


def test_the_exclusion_on_disk_is_the_reason_and_an_included_region_is_null(
    source_dir: Path, one_bit_png: Callable[..., bytes]
) -> None:
    """AC-2, observed by a plain `SELECT excluded FROM region`: `'watermark'`
    on the second row and SQL NULL - not `''`, not `'none'` - on the others."""
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as writer:
        writer.write_regions(_ORDINAL, _three(one_bit_png, excluded="watermark"))

    assert _excluded_column(_db(source_dir), _ORDINAL) == [None, "watermark", None]


def test_a_user_exclusion_is_written_by_write_regions_as_user(
    source_dir: Path, one_bit_png: Callable[..., bytes]
) -> None:
    """The other reason, so a writer that stored a constant `'watermark'` for
    any truthy value is caught."""
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as writer:
        writer.write_regions(_ORDINAL, _three(one_bit_png, excluded="user"))

    assert _excluded_column(_db(source_dir), _ORDINAL) == [None, "user", None]


def test_a_re_detection_overwrites_a_stored_exclusion_like_every_other_column(
    project: Project, source_dir: Path, one_bit_png: Callable[..., bytes]
) -> None:
    """`## Context`, "A consequence for `write_regions`": it upserts on
    `(page_id, reading_index)` and the `DO UPDATE` sets `excluded` from the
    region handed in, so a re-run that finds the same regions unexcluded
    clears a user's exclusion - and one that finds them excluded sets it. Pinned
    in both directions: an upsert that forgot the column would keep the first
    write's value either way."""
    project.write_regions(_ORDINAL, _three(one_bit_png, excluded="user"))
    project.write_regions(_ORDINAL, _three(one_bit_png))

    assert _excluded_column(_db(source_dir), _ORDINAL) == [None, None, None]

    project.write_regions(_ORDINAL, _three(one_bit_png, excluded="watermark"))

    assert _excluded_column(_db(source_dir), _ORDINAL) == [None, "watermark", None]


# -- AC-3: set_excluded sets, and touches nothing else --------------------------------


def test_set_excluded_marks_one_region_and_leaves_its_other_columns_alone(
    project: Project, one_bit_png: Callable[..., bytes]
) -> None:
    """AC-3: `read_regions(ordinal)[1].excluded == "user"`, and the region is
    otherwise the region that was written - mask, polygon, confidence, kind and
    `merged_from` included."""
    regions = _three(one_bit_png)
    _seed(project, regions)

    project.set_excluded(_ORDINAL, 1, "user")

    read_back = project.read_regions(_ORDINAL)
    assert read_back[1].excluded == "user"
    assert read_back == (regions[0], dataclasses.replace(regions[1], excluded="user"), regions[2])


def test_set_excluded_changes_one_column_of_one_row_and_no_line(
    project: Project, source_dir: Path, one_bit_png: Callable[..., bytes]
) -> None:
    """AC-3's "the region's other columns and its `line` row are unchanged",
    at the level of the file: every region row in the chapter and every line
    row, raw, before and after. The one difference allowed is the `excluded`
    cell of the target row. A `line` rewritten, a region row replaced (new id,
    cascade) or the bystander page touched all show here."""
    _seed(project, _three(one_bit_png))
    db_path = _db(source_dir)
    regions_before = _every_region_row(db_path)
    lines_before = _every_line_row(db_path)
    column = [str(row[1]) for row in _raw(db_path, "PRAGMA table_info(region)")].index("excluded")
    target_id = _raw(
        db_path,
        "SELECT region.id FROM region JOIN page ON page.id = region.page_id"
        " WHERE page.ordinal = ? AND region.reading_index = 1",
        (_ORDINAL,),
    )[0][0]

    project.set_excluded(_ORDINAL, 1, "user")

    expected = [
        (*row[:column], "user", *row[column + 1 :]) if row[0] == target_id else row
        for row in regions_before
    ]
    assert _every_region_row(db_path) == expected
    assert _every_line_row(db_path) == lines_before
    assert _excluded_column(db_path, 0) == [None, None, None], "the bystander page"


def test_set_excluded_with_none_clears_the_exclusion(
    project: Project, source_dir: Path, one_bit_png: Callable[..., bytes]
) -> None:
    """AC-3: `set_excluded(ordinal, 1, None)` clears it - to SQL NULL, the
    same "included" a region that was never excluded holds."""
    _seed(project, _three(one_bit_png))
    project.set_excluded(_ORDINAL, 1, "user")
    assert _excluded_column(_db(source_dir), _ORDINAL) == [None, "user", None]

    project.set_excluded(_ORDINAL, 1, None)

    assert project.read_regions(_ORDINAL)[1].excluded is None
    assert _excluded_column(_db(source_dir), _ORDINAL) == [None, None, None]


def test_set_excluded_replaces_one_reason_with_the_other(
    project: Project, source_dir: Path, one_bit_png: Callable[..., bytes]
) -> None:
    """The user restoring a watermark and then excluding it themselves is a
    reason change, and the stored reason is the latest one."""
    _seed(project, _three(one_bit_png, excluded="watermark"))

    project.set_excluded(_ORDINAL, 1, "user")

    assert _excluded_column(_db(source_dir), _ORDINAL) == [None, "user", None]


def test_set_excluded_persists_past_a_reopen(
    source_dir: Path, one_bit_png: Callable[..., bytes]
) -> None:
    """It opens its own transaction, and a transaction that never committed
    persists nothing (MT-005, measured: `rows persisted: 0`)."""
    with create_project(read_chapter(source_dir), project_dir_for(source_dir)) as writer:
        _seed(writer, _three(one_bit_png))
        writer.set_excluded(_ORDINAL, 2, "watermark")

    with open_project(project_dir_for(source_dir)) as reopened:
        assert [r.excluded for r in reopened.read_regions(_ORDINAL)] == [None, None, "watermark"]


# -- AC-3: refusals, with nothing written ---------------------------------------------


@pytest.mark.parametrize("reading_index", [3, 7, -1])
def test_an_index_not_on_the_page_is_refused_naming_it_with_nothing_written(
    project: Project, source_dir: Path, one_bit_png: Callable[..., bytes], reading_index: int
) -> None:
    """AC-3: "an index not on the page raises `ValueError` naming it with
    nothing written". `3` is one past the end; `-1` is the index Python would
    happily resolve to the last region, which is exactly the silent wrong
    write the check exists to refuse.

    The needle is `index <n>`, the shape `write_proposed`'s refusal already
    has ("as `write_proposed` does", C-3), and not a bare number: the page has
    three regions, so a bare `3` is satisfied by a message that names the
    region count and not the index at all."""
    _seed(project, _three(one_bit_png))
    db_path = _db(source_dir)
    before = _every_region_row(db_path)

    with pytest.raises(ValueError, match=rf"\bindex {reading_index}(?!\d)"):
        project.set_excluded(_ORDINAL, reading_index, "user")

    assert _every_region_row(db_path) == before


def test_any_index_on_a_page_with_no_regions_is_refused(project: Project, source_dir: Path) -> None:
    """The zero of zero-one-many: page 0 has no regions here, so index 0 is
    not on it."""
    db_path = _db(source_dir)

    with pytest.raises(ValueError, match=r"\bindex 0(?!\d)"):
        project.set_excluded(0, 0, "user")

    assert _every_region_row(db_path) == []


@pytest.mark.parametrize("reason", ["banana", "Watermark", "", "none"])
def test_a_reason_outside_the_two_is_refused_with_nothing_written(
    project: Project, source_dir: Path, one_bit_png: Callable[..., bytes], reason: str
) -> None:
    """AC-3: "a reason outside the two raises `ValueError`". A `ValueError`
    specifically: a store that let the value through to the column would get
    `sqlite3.IntegrityError` from the CHECK instead, and that is not this."""
    _seed(project, _three(one_bit_png))
    db_path = _db(source_dir)
    before = _every_region_row(db_path)

    with pytest.raises(ValueError):
        project.set_excluded(_ORDINAL, 1, reason)  # type: ignore[arg-type]

    assert _every_region_row(db_path) == before


def test_set_excluded_refuses_a_caller_already_holding_a_transaction(
    project: Project, one_bit_png: Callable[..., bytes]
) -> None:
    """C-3: it opens its own `transaction()`, so like every other write it
    refuses a caller holding one (MT-005 PO-5), rather than committing inside
    the caller's transaction."""
    _seed(project, _three(one_bit_png))

    with pytest.raises(RuntimeError, match="reentrant"), project.transaction():
        project.set_excluded(_ORDINAL, 1, "user")


# -- MT-119 AC-5: what a toggle does to the cleaned image ------------------------------
#
# The rule (C-4; the user's decision of 2026-10-30, "Paste back at render"): the
# stored cleaned image is kept on every toggle EXCEPT a restore of a region the
# image never erased - its index is not in `cleaned_page.erased`, because it was
# excluded when the page was cleaned. That page needs re-cleaning, so the row
# goes. Excluding never invalidates (the bake pastes the source back);
# restoring an erased region never invalidates (its pixels are erased already).
#
# Every image is distinct (`_FILLS`), and "kept" is read byte for byte, with
# its `erased` text, through a plain `sqlite3` connection - together with the
# bystander page 0's row, so a delete keyed on the wrong page and a rewrite of
# the right one both show.

#: One distinct page-sized fill per ordinal.
_FILLS = {0: (10, 20, 30), _ORDINAL: (200, 100, 50)}


def _cleaned_rows(db_path: Path) -> dict[int, tuple[bytes, object]]:
    """ordinal -> (image bytes, erased as stored), for every cleaned page."""
    return {
        int(str(ordinal)): (bytes(blob), erased)  # type: ignore[call-overload]
        for ordinal, blob, erased in _raw(
            db_path,
            "SELECT page.ordinal, cleaned_page.image_blob, cleaned_page.erased"
            " FROM cleaned_page JOIN page ON page.id = cleaned_page.page_id",
        )
    }


def _seed_cleaned(
    project: Project,
    one_bit_png: Callable[..., bytes],
    png_bytes: Callable[..., bytes],
    *,
    erased: tuple[int, ...],
    excluded: str | None = None,
) -> None:
    """`_seed` with region 1 carrying `excluded`, then a cleaned image on both
    pages: `_ORDINAL`'s erased `erased`; page 0's - the bystander - all three."""
    _seed(project, _three(one_bit_png, excluded=excluded))
    project.write_cleaned(_ORDINAL, png_bytes(_PAGE_W, _PAGE_H, _FILLS[_ORDINAL]), erased=erased)
    project.write_cleaned(0, png_bytes(_PAGE_W, _PAGE_H, _FILLS[0]), erased=(0, 1, 2))


@pytest.mark.parametrize(
    "erased", [(0, 1, 2), (0, 2), ()], ids=["erased-it", "never-erased-it", "erased-nothing"]
)
@pytest.mark.parametrize("reason", ["user", "watermark"])
def test_excluding_an_included_region_keeps_the_cleaned_image_whatever_erased_holds(
    project: Project,
    source_dir: Path,
    one_bit_png: Callable[..., bytes],
    png_bytes: Callable[..., bytes],
    erased: tuple[int, ...],
    reason: str,
) -> None:
    """**AC-5 (a)**: excluding never invalidates - the bake pastes the source
    back over the erased area (AC-2), so the image is still the page's. Both
    reasons, and every shape of `erased`, because AC-5 (a) says "whatever
    `erased` holds"."""
    _seed_cleaned(project, one_bit_png, png_bytes, erased=erased)
    db_path = _db(source_dir)
    before = _cleaned_rows(db_path)

    project.set_excluded(_ORDINAL, 1, reason)  # type: ignore[arg-type]

    assert project.has_cleaned(_ORDINAL) is True
    assert _cleaned_rows(db_path) == before
    assert _excluded_column(db_path, _ORDINAL) == [None, reason, None]


@pytest.mark.parametrize("reason", ["user", "watermark"])
def test_restoring_a_region_the_cleaned_image_erased_keeps_the_image(
    project: Project,
    source_dir: Path,
    one_bit_png: Callable[..., bytes],
    png_bytes: Callable[..., bytes],
    reason: str,
) -> None:
    """**AC-5 (b)**: region 1 was removed AFTER the clean - its index is in
    `erased` - so its pixels are erased in the stored image and restoring it
    needs no re-clean."""
    _seed_cleaned(project, one_bit_png, png_bytes, erased=(0, 1, 2), excluded=reason)
    db_path = _db(source_dir)
    before = _cleaned_rows(db_path)

    project.set_excluded(_ORDINAL, 1, None)

    assert project.has_cleaned(_ORDINAL) is True
    assert _cleaned_rows(db_path) == before
    assert _excluded_column(db_path, _ORDINAL) == [None, None, None]


@pytest.mark.parametrize("reason", ["user", "watermark"])
def test_restoring_a_region_the_cleaned_image_never_erased_deletes_that_pages_image_only(
    project: Project,
    source_dir: Path,
    one_bit_png: Callable[..., bytes],
    png_bytes: Callable[..., bytes],
    reason: str,
) -> None:
    """**AC-5 (c)**: region 1 was excluded when the page was cleaned - `erased`
    is `{0, 2}` - so the stored image still carries its Japanese, and the
    English would sit on top of it. The row goes: `has_cleaned` is `False`,
    `read_cleaned` and `read_erased` are `None`, and page 0's row is byte for
    byte what it was."""
    _seed_cleaned(project, one_bit_png, png_bytes, erased=(0, 2), excluded=reason)
    db_path = _db(source_dir)
    bystander = _cleaned_rows(db_path)[0]

    project.set_excluded(_ORDINAL, 1, None)

    assert project.has_cleaned(_ORDINAL) is False, (
        "restoring a region the stored image never erased left the image in place;"
        " AC-5 (c) says the page must be re-cleaned"
    )
    assert project.read_cleaned(_ORDINAL) is None
    assert project.read_erased(_ORDINAL) is None
    assert _cleaned_rows(db_path) == {0: bystander}, "another page's image was touched"
    assert _excluded_column(db_path, _ORDINAL) == [None, None, None]


@pytest.mark.parametrize(
    ("excluded", "again"),
    [("user", "user"), ("watermark", "watermark"), (None, None)],
    ids=["user-again", "watermark-again", "included-again"],
)
def test_setting_the_value_a_region_already_has_keeps_the_cleaned_image(
    project: Project,
    source_dir: Path,
    one_bit_png: Callable[..., bytes],
    png_bytes: Callable[..., bytes],
    excluded: str | None,
    again: str | None,
) -> None:
    """**AC-5 (d)**: a no-op keeps the image. `erased` is `{0, 2}` - the shape
    in which a restore WOULD delete - so `set_excluded(..., None)` on a region
    that is already included is told apart from a restore by the region's
    current value, not by `erased` alone (C-4: "the current value is not
    `None` (a restore)")."""
    _seed_cleaned(project, one_bit_png, png_bytes, erased=(0, 2), excluded=excluded)
    db_path = _db(source_dir)
    before = _cleaned_rows(db_path)

    project.set_excluded(_ORDINAL, 1, again)  # type: ignore[arg-type]

    assert project.has_cleaned(_ORDINAL) is True
    assert _cleaned_rows(db_path) == before
    assert _excluded_column(db_path, _ORDINAL) == [None, again, None]


def test_changing_one_reason_for_the_other_is_not_a_restore_and_keeps_the_image(
    project: Project,
    source_dir: Path,
    one_bit_png: Callable[..., bytes],
    png_bytes: Callable[..., bytes],
) -> None:
    """`watermark` to `user` on a never-erased region: still excluded, so
    nothing will be typeset over its Japanese and nothing needs re-cleaning."""
    _seed_cleaned(project, one_bit_png, png_bytes, erased=(0, 2), excluded="watermark")
    db_path = _db(source_dir)
    before = _cleaned_rows(db_path)

    project.set_excluded(_ORDINAL, 1, "user")

    assert _cleaned_rows(db_path) == before
    assert _excluded_column(db_path, _ORDINAL) == [None, "user", None]


def test_restoring_a_region_on_a_page_with_no_cleaned_image_deletes_nothing_and_restores_it(
    project: Project,
    source_dir: Path,
    one_bit_png: Callable[..., bytes],
    png_bytes: Callable[..., bytes],
) -> None:
    """The edge: no `cleaned_page` row for the page - nothing to invalidate,
    and the restore itself still lands. Page 0's image is untouched."""
    _seed(project, _three(one_bit_png, excluded="user"))
    project.write_cleaned(0, png_bytes(_PAGE_W, _PAGE_H, _FILLS[0]), erased=(0, 1, 2))
    db_path = _db(source_dir)
    before = _cleaned_rows(db_path)

    project.set_excluded(_ORDINAL, 1, None)

    assert _cleaned_rows(db_path) == before
    assert _excluded_column(db_path, _ORDINAL) == [None, None, None]


def test_a_delete_that_fails_leaves_the_exclusion_unchanged(
    project: Project,
    source_dir: Path,
    one_bit_png: Callable[..., bytes],
    png_bytes: Callable[..., bytes],
) -> None:
    """**AC-5**'s last clause: the `region.excluded` write and the delete are
    one transaction. A trigger on the file makes `DELETE FROM cleaned_page`
    abort; the restore that needs the delete must then raise, and leave the
    region excluded and the image in place - an `UPDATE` committed on its own
    would leave the region restored over a page still carrying its Japanese.

    The trigger is created through a plain connection AFTER the seed, because
    `write_regions` deletes from `cleaned_page` as well."""
    _seed_cleaned(project, one_bit_png, png_bytes, erased=(0, 2), excluded="user")
    db_path = _db(source_dir)
    connection = sqlite3.connect(db_path)
    try:
        with connection:
            connection.execute(
                "CREATE TRIGGER mt119_injected_delete_failure BEFORE DELETE ON cleaned_page"
                " BEGIN SELECT RAISE(ABORT, 'mt119 injected delete failure'); END"
            )
    finally:
        connection.close()
    before = _cleaned_rows(db_path)

    with pytest.raises(sqlite3.Error, match="mt119 injected delete failure"):
        project.set_excluded(_ORDINAL, 1, None)

    assert _excluded_column(db_path, _ORDINAL) == [None, "user", None]
    assert _cleaned_rows(db_path) == before
