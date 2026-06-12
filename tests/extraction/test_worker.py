from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from openalex_pipeline.extraction import worker
from openalex_pipeline.extraction.exceptions import (
    DailyLimitReached,
    EmptyPageAnomaly,
    NonRetryableError,
    QueryMismatch,
)
from openalex_pipeline.extraction.models import YearReport, YearState, YearStatus


ROOT = Path("/extract-root")
YEAR = 1980
QUERY = "works?filter=primary_topic.field.id:17,publication_year:1980"
API_KEY = "test-key"


def make_report(
    *,
    year: int = YEAR,
    query: str = QUERY,
    records_fetched: int = 1,
    page_count: int = 1,
    expected_count: int = 1,
) -> YearReport:
    return YearReport(
        query=query,
        year=year,
        started_at="2026-05-22T10:00:00Z",
        completed_at="2026-05-22T10:01:00Z",
        expected_count=expected_count,
        records_fetched=records_fetched,
        page_count=page_count,
        count_mismatch=records_fetched != expected_count,
    )


class FakeStorage:
    def __init__(
        self,
        status: Any,
        *,
        report: YearReport | None = None,
        calls: list[tuple[Any, ...]] | None = None,
    ) -> None:
        self.status = status
        self.report = report or make_report()
        self.calls = calls if calls is not None else []

    def classify_year(self, root: Path, year: int, query: str) -> Any:
        self.calls.append(("classify_year", root, year, query))
        return self.status

    def initialize_year(self, root: Path, year: int, query: str, meta_count: int) -> None:
        self.calls.append(("initialize_year", root, year, query, meta_count))

    def write_page(
        self,
        root: Path,
        year: int,
        records: list[dict],
        next_cursor: str | None,
        page_number: int,
    ) -> None:
        self.calls.append(("write_page", root, year, records, next_cursor, page_number))

    def read_year_report(self, root: Path, year: int) -> YearReport:
        self.calls.append(("read_year_report", root, year))
        return self.report

    def finalize_year(self, root: Path, year: int) -> YearReport:
        self.calls.append(("finalize_year", root, year))
        return self.report


class FakeFetchPage:
    def __init__(self, pages: list[tuple[list[dict], str | None, int]]) -> None:
        self.pages = pages
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, query: str, cursor: str, api_key: str) -> tuple[list[dict], str | None, int]:
        self.calls.append((query, cursor, api_key))
        return self.pages.pop(0)


def install_storage(monkeypatch: pytest.MonkeyPatch, storage: FakeStorage) -> None:
    # The worker must import the storage module as a module attribute, e.g.
    # ``from . import storage`` (or the absolute equivalent ``from
    # openalex_pipeline.extraction import storage``), and call
    # ``storage.classify_year(...)`` etc. Importing the function names
    # directly (``from .storage import classify_year, ...``) would defeat this
    # seam: the worker would bind the functions on import, and substituting
    # ``worker.storage`` here would attach an attribute nothing reads.
    monkeypatch.setattr(worker, "storage", storage, raising=False)


def test_fresh_year_fetches_initial_page_before_initializing_and_finalizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = make_report(records_fetched=1, page_count=1)
    calls: list[tuple[Any, ...]] = []
    storage = FakeStorage(YearStatus(YearState.FRESH), report=report, calls=calls)
    fetch_page = FakeFetchPage([([{"id": "W1"}], None, 1)])
    install_storage(monkeypatch, storage)

    outcome = worker.process_year(ROOT, YEAR, QUERY, API_KEY, fetch_page)

    assert outcome.year == YEAR
    assert outcome.status == "completed"
    assert outcome.report == report
    assert fetch_page.calls == [(QUERY, "*", API_KEY)]
    assert calls == [
        ("classify_year", ROOT, YEAR, QUERY),
        ("initialize_year", ROOT, YEAR, QUERY, 1),
        ("write_page", ROOT, YEAR, [{"id": "W1"}], None, 1),
        ("finalize_year", ROOT, YEAR),
    ]


def test_multi_page_fresh_year_loops_cursors_and_page_numbers_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = FakeStorage(
        YearStatus(YearState.FRESH),
        report=make_report(records_fetched=3, page_count=3, expected_count=3),
    )
    fetch_page = FakeFetchPage(
        [
            ([{"id": "W1"}], "cursor-2", 3),
            ([{"id": "W2"}], "cursor-3", 3),
            ([{"id": "W3"}], None, 3),
        ]
    )
    install_storage(monkeypatch, storage)

    outcome = worker.process_year(ROOT, YEAR, QUERY, API_KEY, fetch_page)

    assert outcome.status == "completed"
    assert fetch_page.calls == [
        (QUERY, "*", API_KEY),
        (QUERY, "cursor-2", API_KEY),
        (QUERY, "cursor-3", API_KEY),
    ]
    assert [call[-1] for call in storage.calls if call[0] == "write_page"] == [1, 2, 3]


def test_complete_year_skips_fetch_and_reads_persisted_report_from_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = make_report(records_fetched=42, page_count=7, expected_count=42)
    storage = FakeStorage(YearStatus(YearState.COMPLETE), report=report)

    def fetch_page(*_args: object) -> tuple[list[dict], str | None, int]:
        raise AssertionError("complete years must not fetch")

    install_storage(monkeypatch, storage)

    outcome = worker.process_year(ROOT, YEAR, QUERY, API_KEY, fetch_page)

    assert outcome.year == YEAR
    assert outcome.status == "skipped"
    assert outcome.report == report
    assert storage.calls == [
        ("classify_year", ROOT, YEAR, QUERY),
        ("read_year_report", ROOT, YEAR),
    ]


def test_in_progress_resume_starts_from_status_cursor_and_next_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = FakeStorage(YearStatus(YearState.IN_PROGRESS, cursor="cursor-3", next_page=3))
    fetch_page = FakeFetchPage([([{"id": "W3"}], None, 99)])
    install_storage(monkeypatch, storage)

    outcome = worker.process_year(ROOT, YEAR, QUERY, API_KEY, fetch_page)

    assert outcome.status == "completed"
    assert fetch_page.calls == [(QUERY, "cursor-3", API_KEY)]
    # Resume must NOT re-initialize the year; finalize is the last call.
    assert storage.calls == [
        ("classify_year", ROOT, YEAR, QUERY),
        ("write_page", ROOT, YEAR, [{"id": "W3"}], None, 3),
        ("finalize_year", ROOT, YEAR),
    ]


def test_finalize_pending_in_progress_finalizes_without_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = make_report(records_fetched=200, page_count=1, expected_count=200)
    storage = FakeStorage(
        YearStatus(YearState.IN_PROGRESS, cursor=None, next_page=2),
        report=report,
    )

    def fetch_page(*_args: object) -> tuple[list[dict], str | None, int]:
        raise AssertionError("finalize-pending years must not fetch")

    install_storage(monkeypatch, storage)

    outcome = worker.process_year(ROOT, YEAR, QUERY, API_KEY, fetch_page)

    assert outcome.status == "completed"
    assert outcome.report == report
    assert storage.calls == [
        ("classify_year", ROOT, YEAR, QUERY),
        ("finalize_year", ROOT, YEAR),
    ]


def test_zero_result_fresh_year_writes_single_empty_page_and_finalizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Empty first page with no cursor is a legitimate zero-result year: the
    # zero-byte page-0001 IS written (bronze's empty-year path depends on it).
    report = make_report(records_fetched=0, page_count=1, expected_count=0)
    storage = FakeStorage(YearStatus(YearState.FRESH), report=report)
    fetch_page = FakeFetchPage([([], None, 0)])
    install_storage(monkeypatch, storage)

    outcome = worker.process_year(ROOT, YEAR, QUERY, API_KEY, fetch_page)

    assert outcome.status == "completed"
    assert storage.calls == [
        ("classify_year", ROOT, YEAR, QUERY),
        ("initialize_year", ROOT, YEAR, QUERY, 0),
        ("write_page", ROOT, YEAR, [], None, 1),
        ("finalize_year", ROOT, YEAR),
    ]


def test_trailing_empty_page_is_not_written_and_year_finalizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Empty page with no cursor after page 1: end-of-stream shape. The write
    # is skipped (no zero-byte page file in a multi-page year) and the year
    # finalizes over the pages already on disk.
    report = make_report(records_fetched=1, page_count=1, expected_count=1)
    storage = FakeStorage(YearStatus(YearState.FRESH), report=report)
    fetch_page = FakeFetchPage(
        [
            ([{"id": "W1"}], "cursor-2", 1),
            ([], None, 1),
        ]
    )
    install_storage(monkeypatch, storage)

    outcome = worker.process_year(ROOT, YEAR, QUERY, API_KEY, fetch_page)

    assert outcome.status == "completed"
    assert storage.calls == [
        ("classify_year", ROOT, YEAR, QUERY),
        ("initialize_year", ROOT, YEAR, QUERY, 1),
        ("write_page", ROOT, YEAR, [{"id": "W1"}], "cursor-2", 1),
        ("finalize_year", ROOT, YEAR),
    ]


def test_resumed_year_with_trailing_empty_page_skips_write_and_finalizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The stale-cursor resume shape: the persisted cursor fetches an empty
    # page with no cursor. Nothing is written; the year finalizes.
    storage = FakeStorage(YearStatus(YearState.IN_PROGRESS, cursor="cursor-3", next_page=3))
    fetch_page = FakeFetchPage([([], None, 99)])
    install_storage(monkeypatch, storage)

    outcome = worker.process_year(ROOT, YEAR, QUERY, API_KEY, fetch_page)

    assert outcome.status == "completed"
    assert fetch_page.calls == [(QUERY, "cursor-3", API_KEY)]
    assert storage.calls == [
        ("classify_year", ROOT, YEAR, QUERY),
        ("finalize_year", ROOT, YEAR),
    ]


def test_mid_stream_empty_page_with_live_cursor_raises_before_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Empty page WITH a live cursor is anomalous API behavior: raise before
    # writing anything, so the year stays resumable at the same cursor.
    storage = FakeStorage(YearStatus(YearState.FRESH))
    fetch_page = FakeFetchPage(
        [
            ([{"id": "W1"}], "cursor-2", 2),
            ([], "cursor-3", 2),
        ]
    )
    install_storage(monkeypatch, storage)

    with pytest.raises(EmptyPageAnomaly):
        worker.process_year(ROOT, YEAR, QUERY, API_KEY, fetch_page)

    assert storage.calls == [
        ("classify_year", ROOT, YEAR, QUERY),
        ("initialize_year", ROOT, YEAR, QUERY, 2),
        ("write_page", ROOT, YEAR, [{"id": "W1"}], "cursor-2", 1),
    ]
    assert not any(call[0] == "finalize_year" for call in storage.calls)


def test_empty_first_page_with_live_cursor_raises_before_initialize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The fresh-path variant of the anomaly: raise before initialize_year, so
    # a first-fetch anomaly leaves nothing on disk.
    storage = FakeStorage(YearStatus(YearState.FRESH))
    fetch_page = FakeFetchPage([([], "cursor-2", 500)])
    install_storage(monkeypatch, storage)

    with pytest.raises(EmptyPageAnomaly):
        worker.process_year(ROOT, YEAR, QUERY, API_KEY, fetch_page)

    assert storage.calls == [("classify_year", ROOT, YEAR, QUERY)]


def test_daily_limit_reached_from_fetch_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = FakeStorage(YearStatus(YearState.FRESH))
    install_storage(monkeypatch, storage)
    limit = DailyLimitReached("daily limit reached")

    def fetch_page(*_args: object) -> tuple[list[dict], str | None, int]:
        raise limit

    with pytest.raises(DailyLimitReached) as exc_info:
        worker.process_year(ROOT, YEAR, QUERY, API_KEY, fetch_page)

    assert exc_info.value is limit
    assert storage.calls == [("classify_year", ROOT, YEAR, QUERY)]


def test_query_mismatch_from_classify_year_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mismatch = QueryMismatch("stored query != current query")

    class RaisingStorage(FakeStorage):
        def classify_year(self, root: Path, year: int, query: str) -> Any:
            self.calls.append(("classify_year", root, year, query))
            raise mismatch

    storage = RaisingStorage(YearStatus(YearState.FRESH))
    install_storage(monkeypatch, storage)

    def fetch_page(*_args: object) -> tuple[list[dict], str | None, int]:
        raise AssertionError("classify failure must short-circuit before fetch")

    with pytest.raises(QueryMismatch) as exc_info:
        worker.process_year(ROOT, YEAR, QUERY, API_KEY, fetch_page)

    assert exc_info.value is mismatch
    assert storage.calls == [("classify_year", ROOT, YEAR, QUERY)]


def test_mid_loop_non_retryable_error_propagates_without_finalize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Fresh year: first fetch succeeds, second fetch raises. The worker must
    # not call finalize_year -- the year stays IN_PROGRESS on disk so the next
    # invocation can resume from the persisted cursor.
    storage = FakeStorage(YearStatus(YearState.FRESH))
    install_storage(monkeypatch, storage)
    boom = NonRetryableError("HTTP 404")

    class FlakyFetch:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, str]] = []

        def __call__(self, query: str, cursor: str, api_key: str) -> Any:
            self.calls.append((query, cursor, api_key))
            if len(self.calls) == 1:
                return ([{"id": "W1"}], "cursor-2", 2)
            raise boom

    fetch_page = FlakyFetch()

    with pytest.raises(NonRetryableError) as exc_info:
        worker.process_year(ROOT, YEAR, QUERY, API_KEY, fetch_page)

    assert exc_info.value is boom
    assert fetch_page.calls == [(QUERY, "*", API_KEY), (QUERY, "cursor-2", API_KEY)]
    assert storage.calls == [
        ("classify_year", ROOT, YEAR, QUERY),
        ("initialize_year", ROOT, YEAR, QUERY, 2),
        ("write_page", ROOT, YEAR, [{"id": "W1"}], "cursor-2", 1),
    ]
    assert not any(call[0] == "finalize_year" for call in storage.calls)
