from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from openalex_pipeline.extraction import connector, runner
from openalex_pipeline.extraction.exceptions import DailyLimitReached
from openalex_pipeline.extraction.models import YearOutcome, YearReport
from openalex_pipeline.extraction.settings import Settings

DATA_ROOT = Path("/pipeline-data")
ROOT = DATA_ROOT / "extract"
API_KEY = "test-key"
FILTER = "primary_topic.field.id:17"


def make_settings(start: int, end: int) -> Settings:
    return Settings(
        api_key=API_KEY,
        filter=FILTER,
        start_year=start,
        end_year=end,
        data_root=DATA_ROOT,
    )


def make_report(year: int) -> YearReport:
    return YearReport(
        query=runner.canonical_query(FILTER, year),
        year=year,
        started_at="2026-05-22T10:00:00Z",
        completed_at="2026-05-22T10:01:00Z",
        expected_count=1,
        records_fetched=1,
        page_count=1,
        count_mismatch=False,
    )


class FakeProcessYear:
    """Records every call and returns a queued outcome (or raises a queued error)."""

    def __init__(self, *, results: list[Any] | None = None) -> None:
        self.results: list[Any] = results if results is not None else []
        self.calls: list[tuple[Path, int, str, str, Any]] = []

    def __call__(
        self,
        root: Path,
        year: int,
        query: str,
        api_key: str,
        fetch_page: Any,
    ) -> YearOutcome:
        self.calls.append((root, year, query, api_key, fetch_page))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def install(monkeypatch: pytest.MonkeyPatch, fake: FakeProcessYear) -> None:
    monkeypatch.setattr(runner.worker, "process_year", fake)


def test_canonical_query_contains_pinned_filter_select_and_per_page() -> None:
    q = runner.canonical_query(FILTER, 1980)

    assert q.startswith(f"works?filter={FILTER},publication_year:1980")
    assert f"&select={runner.SELECT_COLUMNS}" in q
    assert q.endswith("&per_page=200")
    # No cursor or api_key in the canonical query (those are runtime additions).
    assert "cursor" not in q
    assert "api_key" not in q


def test_run_invokes_worker_for_each_year_with_canonical_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(1980, 1982)
    outcomes = [
        YearOutcome(year=y, status="completed", report=make_report(y))
        for y in settings.years
    ]
    fake = FakeProcessYear(results=list(outcomes))
    install(monkeypatch, fake)

    report = runner.run(settings)

    assert report.status == "complete"
    assert report.stopped_year is None
    assert report.outcomes == outcomes
    assert [call[1] for call in fake.calls] == [1980, 1981, 1982]
    assert [call[2] for call in fake.calls] == [
        runner.canonical_query(FILTER, y) for y in (1980, 1981, 1982)
    ]
    # Every call must receive the configured root, api key, and the real
    # connector.fetch_page (the runner is the only one that wires this).
    assert all(
        call[0] == ROOT and call[3] == API_KEY and call[4] is connector.fetch_page
        for call in fake.calls
    )


def test_run_aggregates_skipped_and_completed_outcomes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(1980, 1981)
    outcomes = [
        YearOutcome(year=1980, status="skipped", report=make_report(1980)),
        YearOutcome(year=1981, status="completed", report=make_report(1981)),
    ]
    fake = FakeProcessYear(results=list(outcomes))
    install(monkeypatch, fake)

    report = runner.run(settings)

    assert report.status == "complete"
    assert report.outcomes == outcomes


def test_run_catches_daily_limit_and_returns_partial_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(1980, 1982)
    first = YearOutcome(year=1980, status="completed", report=make_report(1980))
    fake = FakeProcessYear(results=[first, DailyLimitReached("daily")])
    install(monkeypatch, fake)

    report = runner.run(settings)

    assert report.status == "stopped_daily_limit"
    assert report.stopped_year == 1981
    assert report.outcomes == [first]
    # Year 1982 must NOT have been attempted.
    assert [call[1] for call in fake.calls] == [1980, 1981]


def test_run_does_not_catch_other_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Other(Exception):
        pass

    settings = make_settings(1980, 1980)
    fake = FakeProcessYear(results=[Other("boom")])
    install(monkeypatch, fake)

    with pytest.raises(Other):
        runner.run(settings)
