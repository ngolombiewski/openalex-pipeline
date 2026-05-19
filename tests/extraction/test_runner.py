from __future__ import annotations

from datetime import UTC, datetime

import pytest
import responses

from openalex_pipeline.extraction.config import Settings
from openalex_pipeline.extraction.constants import OPENALEX_BASE_URL
from openalex_pipeline.extraction.errors import BadRequest, DriftDetected
from openalex_pipeline.extraction import runner
from openalex_pipeline.extraction.runner import run
from openalex_pipeline.extraction.types import ResumePlan, ResumeTarget, YearMeta

from .conftest import assert_year_complete, write_cursor, write_meta, write_page_file, write_success


def add_openalex_page(
    *,
    records: list[dict],
    count: int,
    next_cursor: str | None,
    status: int = 200,
) -> None:
    responses.add(
        responses.GET,
        f"{OPENALEX_BASE_URL}/works",
        json={"meta": {"count": count, "next_cursor": next_cursor}, "results": records},
        status=status,
    )


def request_cursors() -> list[str]:
    return [call.request.params["cursor"] for call in responses.calls]


@responses.activate
def test_run_fetches_fresh_year_pages_and_finalizes(settings: Settings) -> None:
    settings = settings.model_copy(update={"year_range": "1980"})
    add_openalex_page(records=[{"id": "W1"}, {"id": "W2"}], count=3, next_cursor="cursor-2")
    add_openalex_page(records=[{"id": "W3"}], count=3, next_cursor=None)

    summary = run(settings)

    assert summary.stopped_reason == "all_complete"
    assert summary.total_records_fetched == 3
    assert len(summary.years) == 1
    assert summary.years[0].status == "complete"
    assert summary.years[0].pages_fetched == 2
    assert summary.years[0].records_fetched == 3
    assert_year_complete(settings, 1980)


@responses.activate
def test_run_stops_cleanly_on_credits_exhausted(settings: Settings) -> None:
    settings = settings.model_copy(update={"year_range": "1980"})
    responses.add(responses.GET, f"{OPENALEX_BASE_URL}/works", json={}, status=429)

    summary = run(settings)

    assert summary.stopped_reason == "credits_exhausted"
    assert summary.total_records_fetched == 0


@responses.activate
def test_run_resumes_stale_by_one_cursor_by_overwriting_last_page(
    settings: Settings,
) -> None:
    # M5: page write happens before cursor write, so a crash can leave _CURSOR
    # pointing at the page already on disk. Matching ordered IDs prove this
    # stale-by-one state and allow overwrite instead of append.
    settings = settings.model_copy(update={"year_range": "1980"})
    write_meta(settings, 1980, expected_count=2)
    write_page_file(settings, 1980, 1, ["W1", "W2"])
    write_cursor(settings, 1980, "cursor-stale")
    add_openalex_page(records=[{"id": "W1"}, {"id": "W2"}], count=2, next_cursor=None)

    summary = run(settings)

    assert summary.stopped_reason == "all_complete"
    assert summary.years[0].status == "complete"
    assert summary.years[0].pages_fetched == 1
    assert_year_complete(settings, 1980)


@responses.activate
def test_run_resumes_cleanly_when_cursor_points_to_new_page(settings: Settings) -> None:
    settings = settings.model_copy(update={"year_range": "1980"})
    write_meta(settings, 1980, expected_count=3)
    write_page_file(settings, 1980, 1, ["W1", "W2"])
    write_cursor(settings, 1980, "cursor-2")
    add_openalex_page(records=[{"id": "W3"}], count=3, next_cursor=None)

    summary = run(settings)

    assert summary.stopped_reason == "all_complete"
    assert summary.years[0].status == "complete"
    assert summary.years[0].pages_fetched == 1
    assert summary.years[0].records_fetched == 1
    assert_year_complete(settings, 1980)


@responses.activate
def test_run_detects_drift_discards_year_and_restarts_once(settings: Settings) -> None:
    # M6: the first response after resume re-checks meta.count. A mismatch
    # means the saved cursor belongs to an old result set, so the runner
    # discards the year and retries once from cursor="*".
    settings = settings.model_copy(update={"year_range": "1980"})
    write_meta(settings, 1980, expected_count=2)
    write_page_file(settings, 1980, 1, ["W1"])
    write_cursor(settings, 1980, "cursor-2")
    add_openalex_page(records=[{"id": "W2"}], count=3, next_cursor=None)
    add_openalex_page(records=[{"id": "W1"}, {"id": "W2"}, {"id": "W3"}], count=3, next_cursor=None)

    summary = run(settings)

    assert summary.stopped_reason == "all_complete"
    assert summary.years[0].status == "drifted_restarted"
    assert summary.years[0].pages_fetched == 1
    assert summary.years[0].records_fetched == 3
    assert summary.total_records_fetched == 3
    assert request_cursors() == ["cursor-2", "*"]
    assert_year_complete(settings, 1980)


def test_run_propagates_second_drift_in_same_year(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
) -> None:
    meta = YearMeta(
        filter="primary_topic.field.id:17,publication_year:1980",
        expected_count=2,
        started_at=datetime.now(UTC),
    )
    target = ResumeTarget(
        year=1980,
        next_page_number=2,
        next_cursor="cursor-2",
        existing_meta=meta,
    )
    monkeypatch.setattr(
        runner,
        "scan",
        lambda _: ResumePlan(target=target, recovery=None, completed_years=frozenset()),
        raising=False,
    )

    class StubStorage:
        @staticmethod
        def discard_year(_settings: Settings, year: int) -> None:
            assert year == 1980

    monkeypatch.setattr(
        runner,
        "storage",
        StubStorage,
        raising=False,
    )

    def raise_drift(*_args: object) -> None:
        raise DriftDetected(1980, 2, 3)

    monkeypatch.setattr(
        runner,
        "_process_year",
        raise_drift,
    )

    with pytest.raises(DriftDetected):
        run(settings)


@responses.activate
def test_run_propagates_bad_request(settings: Settings) -> None:
    settings = settings.model_copy(update={"year_range": "1980"})
    responses.add(responses.GET, f"{OPENALEX_BASE_URL}/works", json={}, status=400)

    with pytest.raises(BadRequest):
        run(settings)


@responses.activate
def test_run_processes_multiple_years_in_range(settings: Settings) -> None:
    settings = settings.model_copy(update={"year_range": "1980-1981"})
    add_openalex_page(records=[{"id": "W1980"}], count=1, next_cursor=None)
    add_openalex_page(records=[{"id": "W1981"}], count=1, next_cursor=None)

    summary = run(settings)

    assert summary.stopped_reason == "all_complete"
    assert [outcome.year for outcome in summary.years] == [1980, 1981]
    assert [outcome.status for outcome in summary.years] == ["complete", "complete"]
    assert summary.total_records_fetched == 2
    assert request_cursors() == ["*", "*"]
    assert_year_complete(settings, 1980)
    assert_year_complete(settings, 1981)


@responses.activate
def test_run_skips_already_completed_years_and_processes_next(
    settings: Settings,
) -> None:
    settings = settings.model_copy(update={"year_range": "1980-1981"})
    write_meta(settings, 1980, expected_count=1)
    write_page_file(settings, 1980, 1, ["W1980"])
    write_success(settings, 1980)
    add_openalex_page(records=[{"id": "W1981"}], count=1, next_cursor=None)

    summary = run(settings)

    assert summary.stopped_reason == "all_complete"
    assert [outcome.year for outcome in summary.years] == [1980, 1981]
    assert [outcome.status for outcome in summary.years] == [
        "skipped_complete",
        "complete",
    ]
    assert summary.total_records_fetched == 1
    assert request_cursors() == ["*"]
    assert_year_complete(settings, 1980)
    assert_year_complete(settings, 1981)
