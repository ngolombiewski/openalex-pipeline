from __future__ import annotations

import json
from datetime import UTC

import pytest
from freezegun import freeze_time

from openalex_pipeline.extraction.config import Settings
from openalex_pipeline.extraction.constants import (
    CURSOR_FILENAME,
    EXTRACTED_AT_FIELD,
    META_FILENAME,
    PAGE_FILENAME_TEMPLATE,
    SUCCESS_FILENAME,
)
from openalex_pipeline.extraction.errors import CorruptedYearState, ReconciliationFailed
from openalex_pipeline.extraction.storage import (
    count_pages_on_disk,
    discard_year,
    finalize_year,
    initialize_year,
    read_cursor,
    read_page_work_ids,
    read_year_meta,
    write_page,
)
from openalex_pipeline.extraction.types import YearMeta

from .conftest import utc_datetime, write_cursor, write_meta, write_page_file, year_dir


def test_initialize_year_writes_meta_json(settings: Settings) -> None:
    meta = YearMeta(
        filter="primary_topic.field.id:17,publication_year:1980",
        expected_count=2,
        started_at=utc_datetime(),
    )

    initialize_year(settings, 1980, meta)

    meta_dict = json.loads((year_dir(settings, 1980) / META_FILENAME).read_text())
    assert meta_dict["filter"] == meta.filter
    assert meta_dict["expected_count"] == 2
    assert meta_dict["started_at"].startswith("2026-05-19T10:30")


def test_initialize_year_is_idempotent_for_matching_meta(settings: Settings) -> None:
    meta = YearMeta(
        filter="primary_topic.field.id:17,publication_year:1980",
        expected_count=2,
        started_at=utc_datetime(),
    )

    initialize_year(settings, 1980, meta)
    initialize_year(settings, 1980, meta)

    assert read_year_meta(settings, 1980) == meta


def test_initialize_year_rejects_conflicting_existing_meta(settings: Settings) -> None:
    initialize_year(
        settings,
        1980,
        YearMeta("primary_topic.field.id:17,publication_year:1980", 2, utc_datetime()),
    )

    with pytest.raises(ValueError):
        initialize_year(
            settings,
            1980,
            YearMeta("primary_topic.field.id:17,publication_year:1980", 3, utc_datetime()),
        )


@freeze_time("2026-05-19T10:30:00Z")
def test_write_page_writes_jsonl_stamps_records_and_updates_cursor(settings: Settings) -> None:
    write_page(
        settings,
        1980,
        1,
        [{"id": "W1", "title": "First"}, {"id": "W2", "title": "Second"}],
        "cursor-2",
    )

    lines = (year_dir(settings, 1980) / PAGE_FILENAME_TEMPLATE.format(number=1)).read_text().splitlines()
    records = [json.loads(line) for line in lines]
    assert [record["id"] for record in records] == ["W1", "W2"]
    assert all(record[EXTRACTED_AT_FIELD].startswith("2026-05-19T10:30:00") for record in records)
    assert read_cursor(settings, 1980) == "cursor-2"


def test_write_page_writes_empty_file_for_valid_zero_result_year(settings: Settings) -> None:
    write_page(settings, 1980, 1, [], None)

    page_path = year_dir(settings, 1980) / PAGE_FILENAME_TEMPLATE.format(number=1)
    assert page_path.exists()
    assert page_path.read_text() == ""
    assert not (year_dir(settings, 1980) / CURSOR_FILENAME).exists()


def test_write_page_refuses_to_overwrite_unless_requested(settings: Settings) -> None:
    write_page(settings, 1980, 1, [{"id": "W1"}], "cursor-2")

    with pytest.raises(FileExistsError):
        write_page(settings, 1980, 1, [{"id": "W1-replacement"}], "cursor-2")


def test_write_page_overwrite_replaces_existing_page_after_stale_cursor_detection(
    settings: Settings,
) -> None:
    # M5 recovery path: after the runner proves the cursor is stale-by-one, the
    # storage layer must allow replacing exactly that already-written page.
    write_page(settings, 1980, 1, [{"id": "W1"}], "cursor-2")

    write_page(settings, 1980, 1, [{"id": "W1"}], "cursor-2b", overwrite=True)

    assert read_page_work_ids(settings, 1980, 1) == ["W1"]
    assert read_cursor(settings, 1980) == "cursor-2b"


def test_read_page_work_ids_returns_ordered_ids(settings: Settings) -> None:
    write_page_file(settings, 1980, 1, ["W1", "W2"])

    assert read_page_work_ids(settings, 1980, 1) == ["W1", "W2"]


def test_finalize_year_writes_success_when_count_matches(settings: Settings) -> None:
    write_meta(settings, 1980, expected_count=2)
    write_page_file(settings, 1980, 1, ["W1", "W2"])

    finalize_year(settings, 1980)

    assert (year_dir(settings, 1980) / SUCCESS_FILENAME).exists()


def test_finalize_year_does_not_write_success_when_count_mismatches(settings: Settings) -> None:
    # M7: _SUCCESS is only written after observed page records equal the
    # immutable expected_count in _META.json.
    write_meta(settings, 1980, expected_count=3)
    write_page_file(settings, 1980, 1, ["W1", "W2"])

    with pytest.raises(ReconciliationFailed):
        finalize_year(settings, 1980)

    assert not (year_dir(settings, 1980) / SUCCESS_FILENAME).exists()


def test_count_pages_on_disk_returns_contiguous_page_count(settings: Settings) -> None:
    write_page_file(settings, 1980, 1, ["W1"])
    write_page_file(settings, 1980, 2, ["W2"])

    assert count_pages_on_disk(settings, 1980) == 2


def test_count_pages_on_disk_raises_on_page_numbering_gap(settings: Settings) -> None:
    # M4 is enforced by the page counter because scan relies on this count to
    # derive the next page number on resume.
    write_page_file(settings, 1980, 1, ["W1"])
    write_page_file(settings, 1980, 3, ["W3"])

    with pytest.raises(CorruptedYearState):
        count_pages_on_disk(settings, 1980)


def test_read_year_meta_parses_started_at_as_utc_datetime(settings: Settings) -> None:
    write_meta(settings, 1980, started_at="2026-05-19T10:30:00Z")

    meta = read_year_meta(settings, 1980)

    assert meta.started_at.tzinfo == UTC


def test_discard_year_removes_existing_year_directory(settings: Settings) -> None:
    write_meta(settings, 1980)
    write_page_file(settings, 1980, 1, ["W1"])
    write_cursor(settings, 1980, "cursor-2")

    discard_year(settings, 1980)

    assert not year_dir(settings, 1980).exists()


def test_discard_year_removes_empty_year_directory(settings: Settings) -> None:
    year_dir(settings, 1980).mkdir(parents=True)

    discard_year(settings, 1980)

    assert not year_dir(settings, 1980).exists()
