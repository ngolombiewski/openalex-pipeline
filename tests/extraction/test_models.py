from __future__ import annotations

from openalex_pipeline.extraction.models import (
    RunReport,
    YearOutcome,
    YearReport,
    YearState,
    YearStatus,
)


def test_year_status_defaults_for_fresh_and_complete_do_not_carry_resume_pointer() -> None:
    assert YearStatus(YearState.FRESH) == YearStatus(
        state=YearState.FRESH,
        cursor=None,
        next_page=None,
    )
    assert YearStatus(YearState.COMPLETE) == YearStatus(
        state=YearState.COMPLETE,
        cursor=None,
        next_page=None,
    )


def test_year_status_in_progress_carries_resume_pointer() -> None:
    assert YearStatus(
        state=YearState.IN_PROGRESS,
        cursor="cursor-2",
        next_page=2,
    ).cursor == "cursor-2"


def test_year_status_in_progress_allows_finalize_pending_cursor() -> None:
    status = YearStatus(
        state=YearState.IN_PROGRESS,
        cursor=None,
        next_page=3,
    )

    assert status.cursor is None
    assert status.next_page == 3


def test_year_report_holds_design_pinned_fields() -> None:
    report = YearReport(
        query="works?filter=primary_topic.field.id:17,publication_year:1980",
        year=1980,
        started_at="2026-05-19T10:00:00Z",
        completed_at="2026-05-19T10:05:00Z",
        expected_count=2,
        records_fetched=2,
        page_count=1,
        count_mismatch=False,
    )

    assert report.query == "works?filter=primary_topic.field.id:17,publication_year:1980"
    assert report.year == 1980
    assert report.started_at == "2026-05-19T10:00:00Z"
    assert report.completed_at == "2026-05-19T10:05:00Z"
    assert report.expected_count == 2
    assert report.records_fetched == 2
    assert report.page_count == 1
    assert report.count_mismatch is False


def test_year_outcome_holds_completed_or_skipped_status() -> None:
    report = YearReport(
        query="works?filter=primary_topic.field.id:17,publication_year:1980",
        year=1980,
        started_at="2026-05-19T10:00:00Z",
        completed_at="2026-05-19T10:05:00Z",
        expected_count=2,
        records_fetched=2,
        page_count=1,
        count_mismatch=False,
    )

    assert YearOutcome(year=1980, status="completed", report=report).status == "completed"
    assert YearOutcome(year=1980, status="skipped", report=report).status == "skipped"


def test_run_report_holds_run_status_and_optional_stopped_year() -> None:
    complete_report = RunReport(outcomes=[], status="complete")
    stopped_report = RunReport(
        outcomes=[],
        status="stopped_daily_limit",
        stopped_year=1981,
    )

    assert complete_report.outcomes == []
    assert complete_report.status == "complete"
    assert complete_report.stopped_year is None
    assert stopped_report.status == "stopped_daily_limit"
    assert stopped_report.stopped_year == 1981
