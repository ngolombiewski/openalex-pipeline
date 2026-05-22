from __future__ import annotations

import json
from pathlib import Path

import pytest

from openalex_pipeline.extraction.exceptions import CorruptedState, QueryMismatch
from openalex_pipeline.extraction.models import YearReport, YearState
from openalex_pipeline.extraction.storage import (
    classify_year,
    finalize_year,
    initialize_year,
    read_year_report,
    write_page,
)

from .conftest import (
    read_json,
    write_cursor,
    write_meta,
    write_page_file,
    write_year_report,
    year_dir,
)


def test_classify_year_returns_fresh_for_missing_year_dir(root: Path, query: str) -> None:
    status = classify_year(root, 1980, query)

    assert status.state is YearState.FRESH
    assert status.cursor is None
    assert status.next_page is None


def test_classify_year_returns_fresh_for_empty_year_dir(root: Path, query: str) -> None:
    year_dir(root, 1980).mkdir(parents=True)

    status = classify_year(root, 1980, query)

    assert status.state is YearState.FRESH
    assert status.cursor is None
    assert status.next_page is None


def test_initialize_year_writes_meta_and_initial_cursor(root: Path, query: str) -> None:
    initialize_year(root, 1980, query, meta_count=12)

    meta = read_json(year_dir(root, 1980) / "_META.json")
    cursor = read_json(year_dir(root, 1980) / "_CURSOR.json")

    assert meta["query"] == query
    assert meta["expected_count"] == 12
    assert isinstance(meta["started_at"], str)
    assert meta["started_at"]
    assert cursor == {"cursor": "*", "next_page": 1}


def test_write_page_writes_records_without_extracted_at_and_advances_cursor(
    root: Path,
) -> None:
    write_page(
        root,
        1980,
        [{"id": "W1", "title": "First"}, {"id": "W2", "title": "Second"}],
        next_cursor="cursor-2",
        page_number=1,
    )

    page_path = year_dir(root, 1980) / "page-0001.jsonl"
    records = [json.loads(line) for line in page_path.read_text(encoding="utf-8").splitlines()]

    assert records == [
        {"id": "W1", "title": "First"},
        {"id": "W2", "title": "Second"},
    ]
    assert all("_extracted_at" not in record for record in records)
    assert read_json(year_dir(root, 1980) / "_CURSOR.json") == {
        "cursor": "cursor-2",
        "next_page": 2,
    }


def test_write_page_writes_zero_byte_file_for_empty_records(root: Path) -> None:
    write_page(root, 1980, [], next_cursor=None, page_number=3)

    page_path = year_dir(root, 1980) / "page-0003.jsonl"

    assert page_path.exists()
    assert page_path.stat().st_size == 0
    assert read_json(year_dir(root, 1980) / "_CURSOR.json") == {
        "cursor": None,
        "next_page": 4,
    }


def test_classify_year_returns_in_progress_with_resume_pointer(
    root: Path,
    query: str,
) -> None:
    write_meta(root, 1980, query=query)
    write_cursor(root, 1980, cursor="cursor-2", next_page=2)
    write_page_file(root, 1980, 1, [{"id": "W1"}])

    status = classify_year(root, 1980, query)

    assert status.state is YearState.IN_PROGRESS
    assert status.cursor == "cursor-2"
    assert status.next_page == 2


def test_classify_year_allows_finalize_pending_cursor_null(
    root: Path,
    query: str,
) -> None:
    write_meta(root, 1980, query=query, expected_count=1)
    write_cursor(root, 1980, cursor=None, next_page=2)
    write_page_file(root, 1980, 1, [{"id": "W1"}])

    status = classify_year(root, 1980, query)

    assert status.state is YearState.IN_PROGRESS
    assert status.cursor is None
    assert status.next_page == 2


def test_finalize_year_writes_report_and_returns_year_report(
    root: Path,
    query: str,
) -> None:
    write_meta(root, 1980, query=query, expected_count=3)
    write_page_file(root, 1980, 1, [{"id": "W1"}, {"id": "W2"}])
    write_page_file(root, 1980, 2, [{"id": "W3"}])

    report = finalize_year(root, 1980)
    report_json = read_json(year_dir(root, 1980) / "_YEAR_REPORT.json")

    assert isinstance(report, YearReport)
    assert report.query == query
    assert report.year == 1980
    assert report.started_at == "2026-05-19T10:30:00Z"
    assert report.expected_count == 3
    assert report.records_fetched == 3
    assert report.page_count == 2
    assert report.count_mismatch is False
    assert isinstance(report.completed_at, str)
    assert report_json == {
        "query": report.query,
        "year": report.year,
        "started_at": report.started_at,
        "completed_at": report.completed_at,
        "expected_count": report.expected_count,
        "records_fetched": report.records_fetched,
        "page_count": report.page_count,
        "count_mismatch": report.count_mismatch,
    }


def test_finalize_year_records_non_blocking_count_mismatch(
    root: Path,
    query: str,
) -> None:
    write_meta(root, 1980, query=query, expected_count=3)
    write_page_file(root, 1980, 1, [{"id": "W1"}, {"id": "W2"}])

    report = finalize_year(root, 1980)

    assert report.records_fetched == 2
    assert report.page_count == 1
    assert report.count_mismatch is True
    assert read_json(year_dir(root, 1980) / "_YEAR_REPORT.json")["count_mismatch"] is True


def test_classify_year_complete_uses_report_query_and_ignores_cursor(
    root: Path,
    query: str,
) -> None:
    write_year_report(root, 1980, query=query)

    status = classify_year(root, 1980, query)

    assert status.state is YearState.COMPLETE
    assert status.cursor is None
    assert status.next_page is None


def test_classify_year_complete_does_not_depend_on_cursor_query(
    root: Path,
    query: str,
) -> None:
    write_meta(root, 1980, query="different-query")
    write_cursor(root, 1980, cursor="stale-cursor", next_page=99)
    write_page_file(root, 1980, 1, [{"id": "W1"}])
    write_year_report(root, 1980, query=query)

    status = classify_year(root, 1980, query)

    assert status.state is YearState.COMPLETE
    assert status.cursor is None
    assert status.next_page is None


def test_classify_year_raises_query_mismatch_for_in_progress_meta_query(
    root: Path,
    query: str,
) -> None:
    write_meta(root, 1980, query="different-query")
    write_cursor(root, 1980, cursor="cursor-2", next_page=2)
    write_page_file(root, 1980, 1, [{"id": "W1"}])

    with pytest.raises(QueryMismatch):
        classify_year(root, 1980, query)


def test_classify_year_raises_query_mismatch_for_complete_report_query(
    root: Path,
    query: str,
) -> None:
    write_year_report(root, 1980, query="different-query")

    with pytest.raises(QueryMismatch):
        classify_year(root, 1980, query)


def test_classify_year_query_mismatch_message_omits_select_columns(
    root: Path,
) -> None:
    stored_query = (
        "works?filter=primary_topic.field.id:17,publication_year:1980"
        "&select=id,title,publication_year"
        "&per_page=200"
    )
    current_query = (
        "works?filter=primary_topic.field.id:17,publication_year:1981"
        "&select=id,title,publication_year"
        "&per_page=200"
    )
    write_year_report(root, 1980, query=stored_query)

    with pytest.raises(QueryMismatch) as exc_info:
        classify_year(root, 1980, current_query)

    message = str(exc_info.value)
    assert "select=<omitted>" in message
    assert "select=id,title,publication_year" not in message
    assert "publication_year:1980" in message
    assert "publication_year:1981" in message


def test_classify_year_raises_corrupted_state_for_meta_without_cursor_or_page(
    root: Path,
    query: str,
) -> None:
    write_meta(root, 1980, query=query)

    with pytest.raises(CorruptedState):
        classify_year(root, 1980, query)


def test_classify_year_raises_corrupted_state_for_cursor_and_page_without_meta(
    root: Path,
    query: str,
) -> None:
    write_cursor(root, 1980, cursor="cursor-2", next_page=2)
    write_page_file(root, 1980, 1, [{"id": "W1"}])

    with pytest.raises(CorruptedState):
        classify_year(root, 1980, query)


def test_classify_year_raises_corrupted_state_for_meta_and_cursor_without_page(
    root: Path,
    query: str,
) -> None:
    # Invariant 6: ">=1 page file for any non-fresh year". meta + cursor with
    # zero page files is the broken case.
    write_meta(root, 1980, query=query)
    write_cursor(root, 1980, cursor="cursor-2", next_page=2)

    with pytest.raises(CorruptedState):
        classify_year(root, 1980, query)


def test_classify_year_raises_corrupted_state_for_meta_and_page_without_cursor(
    root: Path,
    query: str,
) -> None:
    write_meta(root, 1980, query=query)
    write_page_file(root, 1980, 1, [{"id": "W1"}])

    with pytest.raises(CorruptedState):
        classify_year(root, 1980, query)


def test_classify_year_raises_corrupted_state_for_non_string_cursor(
    root: Path,
    query: str,
) -> None:
    write_meta(root, 1980, query=query)
    write_page_file(root, 1980, 1, [{"id": "W1"}])
    # Write a _CURSOR.json with a numeric cursor to simulate disk corruption.
    (year_dir(root, 1980) / "_CURSOR.json").write_text(
        '{"cursor": 123, "next_page": 2}', encoding="utf-8"
    )

    with pytest.raises(CorruptedState):
        classify_year(root, 1980, query)


def test_write_page_overwrites_existing_page_file(root: Path) -> None:
    # Resume idempotency hangs on write_page always overwriting page-{N}.
    write_page(
        root,
        1980,
        [{"id": "W1", "stale": True}],
        next_cursor="cursor-2",
        page_number=1,
    )
    write_page(
        root,
        1980,
        [{"id": "W1", "stale": False}, {"id": "W2"}],
        next_cursor="cursor-2b",
        page_number=1,
    )

    page_path = year_dir(root, 1980) / "page-0001.jsonl"
    records = [json.loads(line) for line in page_path.read_text(encoding="utf-8").splitlines()]

    assert records == [{"id": "W1", "stale": False}, {"id": "W2"}]
    assert read_json(year_dir(root, 1980) / "_CURSOR.json") == {
        "cursor": "cursor-2b",
        "next_page": 2,
    }


def test_read_year_report_returns_parsed_report(root: Path, query: str) -> None:
    write_year_report(
        root,
        1980,
        query=query,
        started_at="2026-05-19T10:30:00Z",
        completed_at="2026-05-19T10:45:00Z",
        expected_count=2,
        records_fetched=2,
        page_count=1,
        count_mismatch=False,
    )

    report = read_year_report(root, 1980)

    assert isinstance(report, YearReport)
    assert report.query == query
    assert report.year == 1980
    assert report.started_at == "2026-05-19T10:30:00Z"
    assert report.completed_at == "2026-05-19T10:45:00Z"
    assert report.expected_count == 2
    assert report.records_fetched == 2
    assert report.page_count == 1
    assert report.count_mismatch is False
